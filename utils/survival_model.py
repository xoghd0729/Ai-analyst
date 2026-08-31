"""
utils/survival_model.py
AI Cashflow OS — 배당 생존분석 모델 파이프라인

3단계:
  Step 1: 이산시간 Hazard (Logistic Regression per time-period) — baseline
  Step 2: Cox Proportional Hazards (lifelines)
  Step 3: DeepHit (pycox) — 비례위험 가정 없는 딥러닝 생존모델

입력: data/dividend_dataset.csv (meaningful_cut, event, time_to_event 컬럼 필요)
출력: 종목별 배당 생존곡선(1·3·5년 삭감확률) + C-index 벤치마크 표
"""

import warnings
import numpy as np
import pandas as pd
from pathlib import Path

warnings.filterwarnings("ignore")

# dps_yoy_pct 제외 — 라벨(meaningful_cut = dps<=-30%) 과 직접 연동 → 누수
# 정직한 모델: 재무제표 선행지표만으로 예측
FEATURES = [
    "payout_ratio", "dividend_coverage", "debt_ratio",
    "fcf", "operating_cf", "revenue_yoy_pct", "interest_coverage",
]

DATA_PATH = Path(__file__).parent.parent / "data" / "dividend_dataset.csv"


def load_survival_data(clip_features: bool = True) -> pd.DataFrame:
    df = pd.read_csv(DATA_PATH)
    needed = FEATURES + ["stock_code", "year", "meaningful_cut", "event", "time_to_event"]
    df = df[needed].copy()
    if clip_features:
        for col in FEATURES:
            lo = df[col].quantile(0.01)
            hi = df[col].quantile(0.99)
            df[col] = df[col].clip(lo, hi)
    df[FEATURES] = df[FEATURES].fillna(df[FEATURES].median())
    df = df[df["time_to_event"] >= 1].copy()
    return df


def train_discrete_hazard(df: pd.DataFrame) -> dict:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_score

    X = df[FEATURES].values
    y = df["meaningful_cut"].values

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, class_weight="balanced", C=0.1)),
    ])
    auc_scores = cross_val_score(pipe, X, y, cv=5, scoring="roc_auc")
    pipe.fit(X, y)
    proba = pipe.predict_proba(X)[:, 1]
    c_index = float(roc_auc_score(y, proba)) if y.sum() > 0 else 0.5

    return {
        "model": pipe,
        "cv_auc_mean": float(auc_scores.mean()),
        "cv_auc_std": float(auc_scores.std()),
        "c_index": c_index,
    }


def train_cox_ph(df: pd.DataFrame) -> dict:
    try:
        from lifelines import CoxPHFitter
        from lifelines.utils import concordance_index
    except ImportError:
        return {"error": "pip install lifelines"}

    df_cox = df.groupby("stock_code").first().reset_index()
    df_cox = df_cox[FEATURES + ["time_to_event", "event"]].dropna()

    # 스케일링 — Cox 수렴 안정화
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    df_scaled = df_cox.copy()
    df_scaled[FEATURES] = scaler.fit_transform(df_cox[FEATURES])

    cph = CoxPHFitter(penalizer=0.5)
    try:
        cph.fit(df_scaled, duration_col="time_to_event", event_col="event",
                show_progress=False)
    except Exception as e:
        return {"error": str(e)}

    c_idx = concordance_index(
        df_scaled["time_to_event"],
        -cph.predict_partial_hazard(df_scaled),
        df_scaled["event"],
    )

    hr_table = cph.summary[["coef", "exp(coef)", "p"]].round(3).to_dict()

    return {
        "model": cph,
        "scaler": scaler,
        "c_index": float(c_idx),
        "hazard_ratios": hr_table,
    }


def train_deephit(df: pd.DataFrame, num_nodes=None, epochs=200) -> dict:
    """
    소규모 데이터(~226종목)에 맞게 튜닝:
    - 네트워크 축소: [32, 32] (기존 [64, 64] → 오버피팅 방지)
    - dropout 0.3 (정규화 강화)
    - lr 0.005 (안정적 수렴)
    - batch_size 16 (소규모 데이터)
    - early stopping via val split
    """
    try:
        import torch
        import torchtuples as tt
        from pycox.models import DeepHitSingle
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
    except ImportError:
        return {"error": "pip3 install pycox torchtuples torch"}

    # 소규모 데이터 최적 기본값
    if num_nodes is None:
        num_nodes = [32, 32]

    df_dh = df.groupby("stock_code").first().reset_index()
    df_dh = df_dh[FEATURES + ["time_to_event", "event"]].dropna()

    durations = df_dh["time_to_event"].values.astype(int)
    events    = df_dh["event"].values.astype(float)
    num_durations = int(durations.max()) + 1
    labtrans = DeepHitSingle.label_transform(num_durations)
    y_all = labtrans.fit_transform(durations, events)

    scaler = StandardScaler()
    X_all = scaler.fit_transform(df_dh[FEATURES].values).astype(np.float32)

    # train/val 분리 (early stopping)
    idx_tr, idx_val = train_test_split(
        np.arange(len(X_all)), test_size=0.2, random_state=42,
        stratify=events.astype(int)
    )
    X_tr, X_val = X_all[idx_tr], X_all[idx_val]
    y_tr = (y_all[0][idx_tr], y_all[1][idx_tr])
    y_val = (y_all[0][idx_val], y_all[1][idx_val])

    net = tt.practical.MLPVanilla(
        X_all.shape[1], num_nodes, labtrans.out_features,
        batch_norm=True, dropout=0.3
    )
    model = DeepHitSingle(
        net, tt.optim.Adam(0.005),
        alpha=0.2, sigma=0.1,
        duration_index=labtrans.cuts
    )

    # early stopping: val loss 기준 20 patience
    callbacks = [tt.callbacks.EarlyStopping(patience=20)]
    model.fit(
        X_tr, y_tr,
        epochs=epochs,
        batch_size=16,
        verbose=False,
        val_data=(X_val, y_val),
        callbacks=callbacks,
    )

    surv = model.predict_surv_df(X_all)
    from pycox.evaluation import EvalSurv
    ev = EvalSurv(surv, durations, events, censor_surv="km")
    c_idx = ev.concordance_td()

    return {
        "model": model,
        "scaler": scaler,
        "labtrans": labtrans,
        "c_index": float(c_idx),
        "best_epoch": model.log.to_pandas()['val_loss'].idxmin()
                      if hasattr(model, 'log') else epochs,
    }


def benchmark_xgboost(df: pd.DataFrame) -> dict:
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.model_selection import cross_val_score

    df_b = df.groupby("stock_code").first().reset_index()
    X = df_b[FEATURES].fillna(df_b[FEATURES].median()).values
    y = df_b["event"].values

    xgb = GradientBoostingClassifier(n_estimators=100, random_state=42)
    scores = cross_val_score(xgb, X, y, cv=5, scoring="roc_auc")
    return {"auc_cv": float(scores.mean()), "auc_std": float(scores.std())}


def predict_survival_curve(stock_data: dict, cox_result: dict,
                            horizons=(1, 3, 5)) -> dict:
    if "error" in cox_result:
        return {"error": cox_result["error"]}
    cph = cox_result["model"]
    scaler = cox_result["scaler"]
    row = pd.DataFrame([{f: stock_data.get(f, np.nan) for f in FEATURES}])
    row[FEATURES] = scaler.transform(row[FEATURES].fillna(0))
    surv_fn = cph.predict_survival_function(row)
    result = {}
    for h in horizons:
        idx = min(h, int(surv_fn.index.max()))
        sp = float(surv_fn.loc[idx].values[0])
        result[f"cut_prob_{h}yr"] = round(1 - sp, 4)
        result[f"surv_prob_{h}yr"] = round(sp, 4)
    return result


def run_full_pipeline(verbose=True) -> dict:
    print("=" * 60)
    print("AI Cashflow OS — 배당 생존분석 파이프라인")
    print("=" * 60)

    df = load_survival_data()
    if verbose:
        print(f"\n[데이터] {len(df)} 행, {df['stock_code'].nunique()} 종목")
        print(f"  meaningful_cut=1: {df['meaningful_cut'].sum():.0f} ({df['meaningful_cut'].mean()*100:.1f}%)")
        ev = df.groupby('stock_code')['event'].first()
        print(f"  이벤트 종목: {ev.sum():.0f}/{len(ev)} ({ev.mean()*100:.1f}%)")
        print(f"  피처: {FEATURES}")
        print(f"  ※ dps_yoy_pct 제외 (라벨 누수 방지)")

    results = {}

    print("\n[Step 1] 이산시간 Hazard (Logistic, dps_yoy_pct 제외)...")
    s1 = train_discrete_hazard(df)
    results["discrete_hazard"] = {k: v for k, v in s1.items() if k != "model"}
    print(f"  CV AUC: {s1['cv_auc_mean']:.3f} ± {s1['cv_auc_std']:.3f}")
    print(f"  C-index: {s1['c_index']:.3f}")

    print("\n[Step 2] Cox Proportional Hazards (penalizer=0.5)...")
    s2 = train_cox_ph(df)
    if "error" not in s2:
        results["cox_ph"] = {"c_index": s2["c_index"]}
        print(f"  C-index: {s2['c_index']:.3f}")
        print("  Hazard Ratios (상위 피처):")
        coef = s2["hazard_ratios"]["exp(coef)"]
        for feat, hr in sorted(coef.items(), key=lambda x: abs(x[1]-1), reverse=True)[:4]:
            print(f"    {feat}: HR={hr:.3f}")
    else:
        print(f"  SKIP: {s2['error']}")

    print("\n[Step 3] DeepHit (pycox)...")
    s3 = train_deephit(df)
    if "error" not in s3:
        results["deephit"] = {"c_index": s3["c_index"]}
        print(f"  C-index: {s3['c_index']:.3f}")
    else:
        print(f"  SKIP: {s3['error']}")

    print("\n[Benchmark] XGBoost (종목 단위)...")
    bench = benchmark_xgboost(df)
    results["xgboost"] = bench
    print(f"  CV AUC: {bench['auc_cv']:.3f} ± {bench['auc_std']:.3f}")

    print("\n" + "=" * 60)
    print(f"{'모델':<35} {'C-index/AUC':>12} {'비고':>10}")
    print("-" * 60)
    print(f"{'이산시간 Hazard (Logistic)':<35} {s1['c_index']:>12.3f} {'baseline':>10}")
    if "c_index" in results.get("cox_ph", {}):
        print(f"{'Cox PH (lifelines)':<35} {results['cox_ph']['c_index']:>12.3f} {'HR해석':>10}")
    if "c_index" in results.get("deephit", {}):
        print(f"{'DeepHit (pycox)':<35} {results['deephit']['c_index']:>12.3f} {'SOTA':>10}")
    print(f"{'XGBoost 분류 (CV AUC)':<35} {bench['auc_cv']:>12.3f} {'벤치마크':>10}")
    print("=" * 60)

    return results


if __name__ == "__main__":
    run_full_pipeline()

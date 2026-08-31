"""
scripts/survival_forward_backtest.py  — Survival 모델 워크포워드 비교
======================================================================

XGBoost 3-class vs Cox PH vs GradientBoostingSurvival 비교.
동일한 Out-of-Time 분할 (train: year < Y, test: year == Y) 사용.

평가 기준:
  - 모든 모델 동일: y_risk = (label3 >= 1).astype(int)
  - 지표: PR-AUC, ROC-AUC, 상위 20% 정밀도/재현율

왜 이 비교인가:
  - XGBoost 3-class: 기존 프로덕션 모델 (benchmark)
  - Cox PH: 금융 생존분석 전통적 baseline, 해석 가능
  - GBM Survival: GBDT + Survival loss (scikit-survival)
  - (TabPFN Survival은 survival_pd.py 에서 별도 평가)

실행:
  pip install lifelines scikit-survival  # 최초 1회
  python scripts/survival_forward_backtest.py
  python scripts/survival_forward_backtest.py --start 2019 --top 0.2

결과: results/survival_comparison_report.json
"""
from __future__ import annotations

import argparse
import json
import os
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import average_precision_score, roc_auc_score
import xgboost as xgb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA     = os.path.join(BASE_DIR, "data",    "dividend_dataset.csv")
REPORT   = os.path.join(BASE_DIR, "results", "survival_comparison_report.json")
os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)

BASE_FEATURES = ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex"]
EXTRA = ["payout_ratio", "dps_yoy_pct", "debt_ratio", "interest_coverage", "revenue_yoy_pct"]


# ─────────────────────────────────────────────────
# Feature engineering (공통)
# ─────────────────────────────────────────────────

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[BASE_FEATURES].copy()
    X["div_to_ocf"]   = df["dividends_paid"] / (df["operating_cf"].abs() + 1)
    X["fcf_negative"] = (df["fcf"] < 0).astype(int)
    X["ocf_to_capex"] = df["operating_cf"] / (df["capex"].abs() + 1)
    for c in EXTRA:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors="coerce")
    return X


def make_xgb_weights(y, w_weak=3.0, w_broken=1.3):
    sw = np.ones(len(y))
    sw[np.asarray(y) == 1] = w_weak
    sw[np.asarray(y) == 2] = w_broken
    return sw


TABPFN_MAX_TRAIN = 1024   # TabPFN v1 샘플 상한 (v2는 완화됨)


# ─────────────────────────────────────────────────
# 모델 정의
# ─────────────────────────────────────────────────

def build_xgb():
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc",  StandardScaler()),
        ("clf", xgb.XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
            objective="multi:softprob", num_class=3,
            eval_metric="mlogloss", random_state=42, verbosity=0)),
    ])


def build_cox():
    from lifelines import CoxPHFitter
    return CoxPHFitter(penalizer=0.1)


def build_gbm_survival():
    from sksurv.ensemble import GradientBoostingSurvivalAnalysis
    return GradientBoostingSurvivalAnalysis(
        n_estimators=200, max_depth=3, learning_rate=0.05,
        subsample=0.8, random_state=42,
    )


# ─────────────────────────────────────────────────
# 워크포워드 실행
# ─────────────────────────────────────────────────

def run_xgb(df_tr, df_te, top_frac) -> dict:
    """XGBoost 3-class. 기존 forward_backtest.py 와 동일한 로직."""
    Xtr, ytr = build_features(df_tr), df_tr["label3"]
    Xte, yte = build_features(df_te), df_te["label3"]
    y_risk   = (yte.values >= 1).astype(int)

    m = build_xgb()
    m.fit(Xtr, ytr, clf__sample_weight=make_xgb_weights(ytr))
    proba = m.predict_proba(Xte)
    risk  = proba[:, 1] + proba[:, 2]
    return _metrics(y_risk, risk, top_frac)


def run_tabpfn(df_tr, df_te, top_frac) -> dict | None:
    """
    TabPFN (binary) walk-forward.
    target: label3 >= 1 (0=INTACT, 1=WEAKENING/BROKEN)
    TabPFN v1 1024 샘플 상한 -> stratified subsample.
    """
    try:
        import inspect
        from tabpfn import TabPFNClassifier

        feat_cols = list(build_features(df_tr).columns)
        imp = SimpleImputer(strategy="median")

        Xtr_raw = build_features(df_tr)[feat_cols]
        ytr     = (df_tr["label3"].values >= 1).astype(int)
        Xtr     = imp.fit_transform(Xtr_raw).astype(np.float32)

        # 1024 상한 처리: stratified subsample
        if len(Xtr) > TABPFN_MAX_TRAIN:
            rng = np.random.default_rng(42)
            pos_idx = np.where(ytr == 1)[0]
            neg_idx = np.where(ytr == 0)[0]
            n_pos = min(len(pos_idx), TABPFN_MAX_TRAIN // 4)
            n_neg = TABPFN_MAX_TRAIN - n_pos
            sel = np.concatenate([
                rng.choice(pos_idx, n_pos, replace=False),
                rng.choice(neg_idx, min(n_neg, len(neg_idx)), replace=False),
            ])
            Xtr, ytr = Xtr[sel], ytr[sel]

        Xte_raw = build_features(df_te)[feat_cols]
        Xte     = imp.transform(Xte_raw).astype(np.float32)
        yte     = (df_te["label3"].values >= 1).astype(int)

        sig = inspect.signature(TabPFNClassifier.__init__)
        if "n_estimators" in sig.parameters:
            clf = TabPFNClassifier(n_estimators=4, device="cpu")
        elif "N_ensemble_configurations" in sig.parameters:
            clf = TabPFNClassifier(device="cpu", N_ensemble_configurations=4)
        else:
            clf = TabPFNClassifier()

        clf.fit(Xtr, ytr)
        proba = clf.predict_proba(Xte)
        risk  = proba[:, 1]
        return _metrics(yte, risk, top_frac)
    except ImportError:
        return None
    except Exception as e:
        print(f"    TabPFN 실패: {e}")
        return None


def run_cox(df_tr, df_te, top_frac) -> dict | None:
    """Cox PH (lifelines). event + time_to_event 컬럼 필요."""
    try:
        cox = build_cox()
        feat_cols = list(build_features(df_tr).columns)

        tr_cox = build_features(df_tr).copy()
        tr_cox["event"]         = df_tr["event"].fillna(0).astype(int)
        tr_cox["time_to_event"] = df_tr["time_to_event"].fillna(1).clip(lower=0.1)

        # SimpleImputer
        imp = SimpleImputer(strategy="median")
        tr_feat = pd.DataFrame(imp.fit_transform(tr_cox[feat_cols]),
                               columns=feat_cols)
        tr_feat["event"]         = tr_cox["event"].values
        tr_feat["time_to_event"] = tr_cox["time_to_event"].values

        cox.fit(tr_feat, duration_col="time_to_event", event_col="event")

        te_feat = pd.DataFrame(imp.transform(build_features(df_te)[feat_cols]),
                               columns=feat_cols)
        risk    = cox.predict_partial_hazard(te_feat).values

        y_risk  = (df_te["label3"].values >= 1).astype(int)
        return _metrics(y_risk, risk, top_frac)
    except Exception as e:
        print(f"    Cox PH 실패: {e}")
        return None


def run_gbm_survival(df_tr, df_te, top_frac) -> dict | None:
    """GradientBoostingSurvivalAnalysis (scikit-survival)."""
    try:
        model = build_gbm_survival()
        feat_cols = list(build_features(df_tr).columns)
        imp = SimpleImputer(strategy="median")

        Xtr_raw = build_features(df_tr)[feat_cols]
        Xtr = imp.fit_transform(Xtr_raw)

        # scikit-survival 의 structured array
        ev_tr = df_tr["event"].fillna(0).astype(bool).values
        tt_tr = df_tr["time_to_event"].fillna(1).clip(lower=0.1).values
        y_surv_tr = np.array(list(zip(ev_tr, tt_tr)),
                             dtype=[("event", bool), ("time", float)])

        model.fit(Xtr, y_surv_tr)
        Xte = imp.transform(build_features(df_te)[feat_cols])
        risk = model.predict(Xte)

        y_risk = (df_te["label3"].values >= 1).astype(int)
        return _metrics(y_risk, risk, top_frac)
    except Exception as e:
        print(f"    GBM Survival 실패: {e}")
        return None


def _metrics(y_risk, risk, top_frac) -> dict:
    risk = np.nan_to_num(risk, nan=0.0)
    pr  = average_precision_score(y_risk, risk) if y_risk.sum() > 0 else float("nan")
    roc = roc_auc_score(y_risk, risk) if 0 < y_risk.sum() < len(y_risk) else float("nan")
    order = np.argsort(-risk)
    topn  = max(1, int(len(risk) * top_frac))
    caught = int(y_risk[order[:topn]].sum())
    prec = caught / topn
    rec  = caught / y_risk.sum() if y_risk.sum() else float("nan")
    return {"pr_auc": round(float(pr), 4), "roc_auc": round(float(roc), 4),
            "top_precision": round(prec, 4), "top_recall": round(rec, 4),
            "scores": risk, "truth": y_risk}


# ─────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────

def run(start_year: int, top_frac: float, no_tabpfn: bool = False) -> None:
    # 라이브러리 가용성 체크
    # TabPFN CPU 추론은 walk-forward 루프에서 너무 느림 (fold당 수십 분 이상).
    # --no-tabpfn 플래그(기본값)로 건너뜀.
    # TabPFN 성능은 survival_pd.py CV 결과(ROC 0.583 등)로 별도 보고.
    models_available = {"XGBoost": True, "TabPFN": False, "Cox PH": False, "GBM Survival": False}
    if not no_tabpfn:
        try:
            import tabpfn; models_available["TabPFN"] = True
        except ImportError:
            print("  [SKIP] tabpfn 미설치 — pip install tabpfn==0.1.9 또는 tabpfn>=8.0.0")
    else:
        print("  [SKIP] TabPFN — CPU walk-forward 너무 느림. survival_pd.py CV 결과 참조.")
    try:
        import lifelines; models_available["Cox PH"] = True
    except ImportError:
        print("  [SKIP] lifelines 미설치 — pip install lifelines")
    try:
        import sksurv; models_available["GBM Survival"] = True
    except ImportError:
        print("  [SKIP] scikit-survival 미설치 — pip install scikit-survival")

    df = pd.read_csv(DATA)
    df = df[df["label3"].notna()].copy()
    df["label3"] = df["label3"].astype(int)
    df["year"]   = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)

    if "event" not in df.columns:
        # event 컬럼 없으면 label3 기반으로 생성
        df["event"]         = (df["label3"] >= 1).astype(int)
        df["time_to_event"] = 1.0
        print("  [WARNING] event 컬럼 없음 — label3 기반 대체 생성")

    years = sorted(y for y in df["year"].unique() if y >= start_year)
    print("=" * 70)
    print("  Survival 모델 워크포워드 비교 (XGBoost vs Cox PH vs GBM Survival)")
    print("=" * 70)
    print(f"  테스트 연도: {years}")
    print(f"  활성 모델: {[k for k,v in models_available.items() if v]}")
    print()

    results: dict[str, list] = {k: [] for k, v in models_available.items() if v}
    all_data: dict[str, dict] = {k: {"scores": [], "truth": []} for k in results}

    for Y in years:
        tr = df[df["year"] < Y]
        te = df[df["year"] == Y]
        if len(tr) < 100 or len(te) < 10:
            continue
        if te["label3"].nunique() < 2:
            continue

        y_risk_n = int((te["label3"].values >= 1).sum())
        print(f"  [{Y}] n_train={len(tr):,}  n_test={len(te):,}  n_risk={y_risk_n}")

        for name, runner in [
            ("XGBoost",      lambda: run_xgb(tr, te, top_frac)),
            ("TabPFN",       lambda: run_tabpfn(tr, te, top_frac)),
            ("Cox PH",       lambda: run_cox(tr, te, top_frac)),
            ("GBM Survival", lambda: run_gbm_survival(tr, te, top_frac)),
        ]:
            if not models_available.get(name):
                continue
            r = runner()
            if r is None:
                continue
            print(f"    {name:<16} PR={r['pr_auc']:.3f}  ROC={r['roc_auc']:.3f}"
                  f"  P@20%={r['top_precision']:.2f}  R@20%={r['top_recall']:.2f}")
            results[name].append({"year": int(Y), **{k: v for k, v in r.items()
                                                      if k not in ("scores","truth")}})
            all_data[name]["scores"].append(r["scores"])
            all_data[name]["truth"].append(r["truth"])

    print()
    print("=" * 70)
    print("  [전체 Pooled 결과 비교]")
    print(f"  {'모델':<20}{'PR-AUC':>8}{'ROC-AUC':>9}{'P@20%':>8}{'R@20%':>8}")
    print("-" * 70)

    summary_out = {}
    for name, rows in results.items():
        if not rows:
            continue
        S = np.concatenate(all_data[name]["scores"])
        T = np.concatenate(all_data[name]["truth"])
        pr  = average_precision_score(T, S)
        roc = roc_auc_score(T, S)
        mp  = float(np.nanmean([r["top_precision"] for r in rows]))
        mr  = float(np.nanmean([r["top_recall"]    for r in rows]))
        print(f"  {name:<20}{pr:>8.3f}{roc:>9.3f}{mp:>8.2f}{mr:>8.2f}")
        summary_out[name] = {
            "years": rows,
            "pooled_pr_auc":     round(float(pr),  4),
            "pooled_roc_auc":    round(float(roc), 4),
            "mean_top_precision": round(mp, 4),
            "mean_top_recall":    round(mr, 4),
        }

    print("=" * 70)
    print()
    print("  [해석 가이드]")
    print("  - PR-AUC가 높을수록 불균형 데이터에서 실제 위험종목 탐지 우수")
    print("  - ROC-AUC: 전반적 분류 성능 (0.5=랜덤, 1.0=완벽)")
    print("  - P@20%: 상위 20% 경고 중 실제 위험종목 비율 (정밀도)")
    print("  - R@20%: 실제 위험종목 중 상위 20% 경고로 잡힌 비율 (재현율)")
    print()
    print("  [XGBoost vs Survival 차별화 포인트]")
    print("  - 성능이 비슷하거나 낮더라도 Survival은 '언제' 위험한지를 예측")
    print("  - hazard는 단순 분류가 아닌 시간 의존적 위험도 (time-to-event)")
    print("  - survival_1y: 1년 이내 배당 유지 확률 → 포트폴리오 스토리와 직결")

    json.dump(
        {"top_frac": top_frac, "start_year": start_year,
         "models": summary_out},
        open(REPORT, "w", encoding="utf-8"), ensure_ascii=False, indent=2
    )
    print(f"\n  저장: {REPORT}")
    print("=" * 70)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start",       type=int,   default=2019)
    ap.add_argument("--top",         type=float, default=0.2)
    ap.add_argument("--no-tabpfn",   action="store_true",
                    help="TabPFN 건너뜀 (CPU walk-forward 너무 느림, 기본 권장)")
    args = ap.parse_args()
    run(args.start, args.top, no_tabpfn=args.no_tabpfn)

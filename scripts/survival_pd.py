"""
survival_pd.py — 배당 생존분석 v4 (TabPFN + Cox PH)

v4 변경사항:
  - XGBoost/HistGradientBoosting → TabPFN (NeurIPS 2022, Transformer 기반 meta-learning)
  - TabPFN 특징: 소규모 tabular 데이터 특화, 하이퍼파라미터 불필요, 제로샷 학습
  - Cox PH (lifelines) 결과도 함께 출력 — 생존분석 정통 방법론 병행
  - TabPFN 미설치 시 자동 fallback → HistGradientBoosting

설치:
  pip3 install tabpfn lifelines

TabPFN 제약:
  - v1: 학습 샘플 <= 1024, 피처 <= 100
  - v2 (tabpfn >= 2.0): 제한 완화, sample_weight 지원
  - GroupKFold fold당 학습 샘플이 1024 초과 시 자동 subsample (층화)

실행:
  python3 scripts/survival_pd.py
"""
from __future__ import annotations
import json
import os
import warnings
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.utils.class_weight import compute_sample_weight
from scipy.stats import rankdata

warnings.filterwarnings("ignore")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV  = os.path.join(BASE, "data", "dividend_dataset.csv")

FEATURES_CORE = [
    "dividend_coverage", "payout_ratio", "debt_ratio",
    "interest_coverage", "revenue_yoy_pct",
]

TABPFN_MAX_TRAIN = 1024   # TabPFN v1 학습 샘플 상한


# ─────────────────────────────────────────────────────────────
# 모델 로더 — TabPFN 우선, fallback HistGBM
# ─────────────────────────────────────────────────────────────

def _load_tabpfn():
    """
    TabPFN 로드 (v1 0.1.x / v2 8.x 자동 감지).
    import 성공 여부만 체크 — 실제 모델 로드는 첫 fit에서 확인.

    TabPFN v2 (8.x) HuggingFace 인증 필요 시:
      1. https://huggingface.co/Prior-Labs/tabpfn_3 → 약관 동의
      2. hf auth login
    TabPFN v1 (0.1.9): pip3 install tabpfn==0.1.9  (인증 불필요, torch 필요)
    """
    # 1단계: import만 시도
    try:
        from tabpfn import TabPFNClassifier
    except ImportError as e:
        print(f"  [모델] TabPFN import 실패 ({e})")
        print("         pip3 install tabpfn==0.1.9 또는 torch 설치 필요")
        print("         → HistGBM fallback")
        return None, None

    import tabpfn as _tf
    ver = getattr(_tf, "__version__", "1.x")

    # 2단계: 더미 fit으로 실제 동작 확인
    try:
        _X = np.array([[1,2,3],[4,5,6],[1,2,3],[4,5,6],[1,2,3],
                        [4,5,6],[1,2,3],[4,5,6],[1,2,3],[4,5,6]], dtype=np.float32)
        _y = np.array([0,1,0,1,0,1,0,1,0,1])
        import inspect
        sig = inspect.signature(TabPFNClassifier.__init__)
        if "n_estimators" in sig.parameters:
            _m = TabPFNClassifier(n_estimators=4, device="cpu")
        elif "N_ensemble_configurations" in sig.parameters:
            _m = TabPFNClassifier(device="cpu", N_ensemble_configurations=4)
        else:
            _m = TabPFNClassifier()
        _m.fit(_X, _y)
        print(f"  [모델] TabPFN v{ver} 로드 성공 ✓")
        return TabPFNClassifier, ver
    except Exception as e:
        err = str(e)
        if "HuggingFace" in err or "gated" in err or "authentication" in err:
            print(f"  [모델] TabPFN v{ver} — HuggingFace 인증 필요 → HistGBM fallback")
            print("         해결: hf auth login")
            print("         약관: https://huggingface.co/Prior-Labs/tabpfn_3")
        elif "torch" in err.lower() or "cuda" in err.lower():
            print(f"  [모델] TabPFN v{ver} — PyTorch 필요 → HistGBM fallback")
            print("         해결: pip3 install torch")
        else:
            print(f"  [모델] TabPFN v{ver} 초기화 실패: {err[:80]} → HistGBM fallback")
        return None, None


def _make_catboost(silent=True):
    """CatBoost — TabPFN 미사용 시 기본 모델 (Ordered Boosting, Yandex 2018)."""
    try:
        from catboost import CatBoostClassifier
        return CatBoostClassifier(
            iterations=500,
            learning_rate=0.03,
            depth=6,
            l2_leaf_reg=3.0,
            random_seed=42,
            eval_metric="AUC",
            auto_class_weights="Balanced",
            verbose=0,
        )
    except ImportError:
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_depth=4, learning_rate=0.03, max_iter=500,
            l2_regularization=0.5, min_samples_leaf=5, random_state=42,
        )


def _make_model(TabPFNClass, n_train: int, n_feats: int):
    if TabPFNClass is None:
        return _make_catboost(), False

    try:
        import inspect
        sig = inspect.signature(TabPFNClass.__init__)
        if "n_estimators" in sig.parameters:
            # v2 (8.x): ignore_pretraining_limits=True → CPU 1000+ 샘플 허용
            return TabPFNClass(
                n_estimators=8,
                device="cpu",
                ignore_pretraining_limits=True,
            ), True
        elif "N_ensemble_configurations" in sig.parameters:
            return TabPFNClass(device="cpu", N_ensemble_configurations=8), True
        else:
            return TabPFNClass(ignore_pretraining_limits=True), True
    except Exception:
        try:
            return TabPFNClass(ignore_pretraining_limits=True), True
        except Exception:
            return _make_catboost(), False


def _subsample_balanced(X_tr, y_tr, max_n=TABPFN_MAX_TRAIN, seed=42):
    rng = np.random.RandomState(seed)
    pos_idx = np.where(y_tr == 1)[0]
    neg_idx = np.where(y_tr == 0)[0]
    n_pos = max(1, int(max_n * len(pos_idx) / len(y_tr)))
    n_neg = max_n - n_pos
    chosen_pos = rng.choice(pos_idx, min(n_pos, len(pos_idx)), replace=False)
    chosen_neg = rng.choice(neg_idx, min(n_neg, len(neg_idx)), replace=False)
    return np.sort(np.concatenate([chosen_pos, chosen_neg]))


# ─────────────────────────────────────────────────────────────
# 데이터 로딩
# ─────────────────────────────────────────────────────────────

def load_person_period() -> pd.DataFrame:
    d = pd.read_csv(CSV, dtype={"stock_code": str})
    d["stock_code"] = d["stock_code"].str.zfill(6)

    if "meaningful_cut" not in d.columns:
        d = _add_meaningful_cut(d)

    d = d[d["meaningful_cut"].notna()].copy()
    d["meaningful_cut"] = d["meaningful_cut"].astype(int)
    d = d.sort_values(["stock_code", "year"]).reset_index(drop=True)

    for c in FEATURES_CORE:
        d[c] = pd.to_numeric(d.get(c, pd.Series(dtype=float)), errors="coerce")

    ta  = (pd.to_numeric(d.get("total_liab"), errors="coerce") +
           pd.to_numeric(d.get("total_equity"), errors="coerce")).replace(0, np.nan)
    tl  = pd.to_numeric(d.get("total_liab"), errors="coerce")
    eq  = pd.to_numeric(d.get("total_equity"), errors="coerce")
    ocf = pd.to_numeric(d.get("operating_cf"), errors="coerce")
    fcf = pd.to_numeric(d.get("fcf"), errors="coerce")
    div = pd.to_numeric(d.get("dividends_paid"), errors="coerce").abs().replace(0, np.nan)

    d["ni_to_ta"]   = pd.to_numeric(d.get("net_income"), errors="coerce") / ta
    d["ebit_to_ta"] = pd.to_numeric(d.get("op_income"), errors="coerce") / ta
    d["eq_to_tl"]   = eq / tl.replace(0, np.nan)
    d["rev_to_ta"]  = pd.to_numeric(d.get("revenue"), errors="coerce") / ta
    d["fcf_to_ta"]  = fcf / ta
    d["ocf_to_ta"]  = ocf / ta
    d["liab_to_ta"] = tl / ta
    d["ocf_cov"]    = (ocf / div).clip(-5, 30)
    d["fcf_cov"]    = (fcf / div).clip(-5, 30)
    d["capex_ratio"]= pd.to_numeric(d.get("capex"), errors="coerce").abs() / ocf.abs().replace(0, np.nan)
    d["fcf_negative"] = (fcf < 0).astype(int)

    d["altman_z"] = (1.4 * d["ni_to_ta"].fillna(0) +
                     3.3 * d["ebit_to_ta"].fillna(0) +
                     0.6 * d["eq_to_tl"].fillna(0) +
                     1.0 * d["rev_to_ta"].fillna(0))

    for col in ["dividend_coverage", "debt_ratio", "payout_ratio", "ocf_cov"]:
        d[f"{col}_chg"] = d.groupby("stock_code")[col].diff()

    d["t_index"]         = d.groupby("stock_code").cumcount()
    d["div_history_yrs"] = d["t_index"] + 1
    d["tier"] = pd.cut(d["div_history_yrs"], bins=[0, 2, 4, 99],
                       labels=["T1", "T2", "T3"])

    d["event_next"] = d.groupby("stock_code")["meaningful_cut"].shift(-1)
    for lag in [1, 2, 3]:
        d[f"_mc{lag}"] = d.groupby("stock_code")["meaningful_cut"].shift(-lag)
    d["event_3yr"] = d[["_mc1", "_mc2", "_mc3"]].max(axis=1)
    d.drop(columns=["_mc1", "_mc2", "_mc3"], inplace=True)

    d = d[d["event_next"].notna()].copy().reset_index(drop=True)
    d["event_next"] = d["event_next"].astype(int)
    d["event_3yr"]  = d["event_3yr"].fillna(d["event_next"]).astype(int)

    # ── 매크로 피처 (한국은행 기준금리 + KOSPI 수익률) ──────────────
    bok_rate = {
        2013: 2.50, 2014: 2.00, 2015: 1.50, 2016: 1.25,
        2017: 1.50, 2018: 1.75, 2019: 1.25, 2020: 0.50,
        2021: 1.00, 2022: 3.25, 2023: 3.50, 2024: 3.00,
    }
    kospi_ret = {
        2013: 0.7,  2014: -4.8, 2015: 2.4,  2016: 3.3,
        2017: 21.8, 2018: -17.3,2019: 7.7,  2020: 30.8,
        2021: 3.6,  2022: -24.9,2023: 18.7, 2024: -9.6,
    }
    d["bok_rate"]   = d["year"].map(bok_rate).fillna(2.0)
    d["kospi_ret"]  = d["year"].map(kospi_ret).fillna(0.0)
    d["rate_chg"]   = d["year"].map(bok_rate).diff().fillna(0)  # 금리 변화

    # ── 롤링 트렌드 피처 (3년 기울기) ──────────────────────────────
    for col in ["debt_ratio", "dividend_coverage", "ocf_to_ta"]:
        if col in d.columns:
            def _slope(s):
                s = s.rolling(3, min_periods=2).apply(
                    lambda x: np.polyfit(range(len(x)), x, 1)[0] if len(x) >= 2 else np.nan,
                    raw=True)
                return s
            d[f"{col}_slope"] = d.groupby("stock_code")[col].transform(_slope)

    return d


def _add_meaningful_cut(d: pd.DataFrame) -> pd.DataFrame:
    d = d.sort_values(["stock_code", "year"]).copy()
    d["meaningful_cut"] = 0
    for _, grp in d.groupby("stock_code"):
        grp = grp.reset_index()
        for i in range(len(grp)):
            yoy = grp.loc[i, "dps_yoy_pct"] if "dps_yoy_pct" in grp else np.nan
            if pd.isna(yoy) or yoy > -30:
                continue
            recovered = (i + 1 < len(grp) and
                         pd.notna(grp.loc[i+1, "dps_yoy_pct"]) and
                         grp.loc[i+1, "dps_yoy_pct"] >= 30)
            if not recovered:
                d.loc[grp.loc[i, "index"], "meaningful_cut"] = 1
    return d


# ─────────────────────────────────────────────────────────────
# CV — TabPFN
# ─────────────────────────────────────────────────────────────

def cv_scores_tabpfn(d: pd.DataFrame, feats: list[str],
                     target: str = "event_next",
                     TabPFNClass=None) -> tuple:
    X = d[feats].copy().fillna(d[feats].median())
    for col in X.columns:
        lo, hi = X[col].quantile(0.01), X[col].quantile(0.99)
        X[col] = X[col].clip(lo, hi)
    y = d[target]
    g = d["stock_code"].astype(str)
    oof = np.full(len(y), np.nan)
    used_tabpfn = False

    for fold, (tr, va) in enumerate(GroupKFold(5).split(X, y, g)):
        X_tr, y_tr = X.iloc[tr].values, y.iloc[tr].values
        X_va       = X.iloc[va].values
        if len(X_tr) > TABPFN_MAX_TRAIN:
            sub  = _subsample_balanced(X_tr, y_tr, TABPFN_MAX_TRAIN)
            X_tr, y_tr = X_tr[sub], y_tr[sub]
        model, is_tabpfn = _make_model(TabPFNClass, len(X_tr), X_tr.shape[1])
        if is_tabpfn:
            used_tabpfn = True
        try:
            if is_tabpfn:
                model.fit(X_tr, y_tr)
            else:
                sw = compute_sample_weight("balanced", y_tr)
                model.fit(X_tr, y_tr, sample_weight=sw)
            oof[va] = model.predict_proba(X_va)[:, 1]
        except Exception as e:
            print(f"    fold {fold} 오류: {e}")

    mk = ~np.isnan(oof)
    name = "TabPFN" if used_tabpfn else "HistGBM"
    if mk.sum() == 0 or y[mk].sum() == 0:
        print(f"    ⚠️  [{name}] 전 fold 실패 또는 양성 없음 → 0.5 반환")
        return oof, 0.0, 0.5, float(y.mean()), name
    return (oof,
            average_precision_score(y[mk], oof[mk]),
            roc_auc_score(y[mk], oof[mk]),
            float(y.mean()),
            name)


# ─────────────────────────────────────────────────────────────
# Cox PH
# ─────────────────────────────────────────────────────────────

def run_cox_ph(d: pd.DataFrame, feats: list[str]) -> dict:
    """
    Cox PH 생존분석.
    - 종목 단위 (첫 관측값 기준) time-to-event 구성
    - 피처 NaN은 중앙값 대체 → dropna 대신 가용 종목 최대화
    - penalizer=1.0 (ridge) 으로 수렴 안정화
    """
    try:
        from lifelines import CoxPHFitter
        from lifelines.utils import concordance_index
    except ImportError:
        return {"error": "pip3 install lifelines"}

    surv = []
    for code, grp in d.groupby("stock_code"):
        grp = grp.sort_values("year")
        cut_rows = grp[grp["meaningful_cut"] == 1]
        t  = int(cut_rows.iloc[0]["t_index"]) + 1 if len(cut_rows) else int(grp.iloc[-1]["t_index"]) + 1
        ev = 1 if len(cut_rows) else 0
        row = grp.iloc[0][feats].to_dict()
        row["duration"] = t
        row["event"]    = ev
        surv.append(row)

    df_cox = pd.DataFrame(surv)

    # dropna 대신 피처별 중앙값 대체 → 종목 수 최대화
    for f in feats:
        med = df_cox[f].median()
        df_cox[f] = df_cox[f].fillna(med if pd.notna(med) else 0.0)

    # 분산 0 피처 제거 (Cox 수렴 오류 방지)
    zero_var = [f for f in feats if df_cox[f].std() == 0]
    if zero_var:
        df_cox = df_cox.drop(columns=zero_var)
        feats  = [f for f in feats if f not in zero_var]

    if len(df_cox) < 20 or int(df_cox["event"].sum()) < 5:
        return {"error": f"이벤트 부족: {int(df_cox['event'].sum())}개 (최소 5 필요)"}

    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    df_s = df_cox.copy()
    df_s[feats] = scaler.fit_transform(df_cox[feats])

    cph = CoxPHFitter(penalizer=1.0, l1_ratio=0.0)
    try:
        cph.fit(df_s, duration_col="duration", event_col="event", show_progress=False)
    except Exception as e:
        return {"error": str(e)}

    c_idx = concordance_index(
        df_s["duration"], -cph.predict_partial_hazard(df_s), df_s["event"])

    summary = cph.summary[["coef", "exp(coef)", "p"]].round(3)
    top = summary["coef"].abs().sort_values(ascending=False).head(5).index

    return {
        "c_index":      round(float(c_idx), 3),
        "n_stocks":     len(df_cox),
        "n_events":     int(df_cox["event"].sum()),
        "top_features": summary.loc[top].to_dict(),
    }


# ─────────────────────────────────────────────────────────────
# Altman 벤치마크
# ─────────────────────────────────────────────────────────────

def altman_benchmark(d: pd.DataFrame) -> tuple[float, int]:
    ta = (pd.to_numeric(d.get("total_liab"), errors="coerce") +
          pd.to_numeric(d.get("total_equity"), errors="coerce")).replace(0, np.nan)
    altman = (1.4 * pd.to_numeric(d.get("net_income"), errors="coerce") / ta +
              3.3 * pd.to_numeric(d.get("op_income"), errors="coerce") / ta +
              0.6 * pd.to_numeric(d.get("total_equity"), errors="coerce") /
                    pd.to_numeric(d.get("total_liab"), errors="coerce").replace(0, np.nan) +
              1.0 * pd.to_numeric(d.get("revenue"), errors="coerce") / ta)
    mk = altman.notna()
    if mk.sum() < 20:
        return float("nan"), 0
    return round(roc_auc_score(d.loc[mk, "event_next"], -altman[mk]), 3), int(mk.sum())


# ─────────────────────────────────────────────────────────────
# 시간의존 C-index
# ─────────────────────────────────────────────────────────────

def time_dependent_cindex(d: pd.DataFrame, risk: np.ndarray) -> float:
    dd = d.assign(risk=risk)
    surv = []
    for code, gdf in dd.groupby("stock_code"):
        gdf = gdf.sort_values("year")
        cut = gdf[gdf["event_next"] == 1]
        t   = int(cut.iloc[0]["t_index"]) if len(cut) else int(gdf.iloc[-1]["t_index"])
        ev  = 1 if len(cut) else 0
        surv.append((t, ev, float(gdf.iloc[0]["risk"])))
    sv = pd.DataFrame(surv, columns=["t", "e", "r"])
    conc = tot = 0.0
    for i in range(len(sv)):
        a = sv.iloc[i]
        if a["e"] != 1:
            continue
        comp = sv[sv["t"] > a["t"]]
        tot  += len(comp)
        conc += (a["r"] > comp["r"]).sum() + 0.5 * (a["r"] == comp["r"]).sum()
    return round(conc / tot, 3) if tot else float("nan")


# ─────────────────────────────────────────────────────────────
# 3-Tier 모델
# ─────────────────────────────────────────────────────────────

def run_tier_model(d: pd.DataFrame, feats: list[str],
                   TabPFNClass=None) -> pd.DataFrame:
    d = d.reset_index(drop=True).copy()
    d["tier"] = pd.cut(d["div_history_yrs"], bins=[0, 2, 4, 99],
                       labels=["T1", "T2", "T3"])
    d["risk_score"] = np.nan

    for tier_lbl in ["T1", "T2", "T3"]:
        mask = d["tier"] == tier_lbl
        grp  = d[mask].copy().reset_index(drop=True)
        n_pos    = int(grp["event_next"].sum())
        n_stocks = grp["stock_code"].nunique()

        if tier_lbl == "T1" or n_pos < 3 or n_stocks < 5:
            alt = grp["altman_z"]
            s   = -alt.fillna(alt.median())
            rng = s.max() - s.min()
            d.loc[mask, "risk_score"] = ((s - s.min()) / (rng if rng > 0 else 1)).values
            continue

        target   = "event_3yr" if tier_lbl == "T3" else "event_next"
        X        = grp[feats].fillna(grp[feats].median())
        for col in X.columns:
            lo, hi = X[col].quantile(0.01), X[col].quantile(0.99)
            X[col] = X[col].clip(lo, hi)
        y        = grp[target]
        g        = grp["stock_code"].astype(str)
        n_splits = min(5, n_stocks)
        oof_t    = np.full(len(grp), np.nan)

        for tr, va in GroupKFold(n_splits).split(X, y, g):
            X_tr, y_tr = X.iloc[tr].values, y.iloc[tr].values
            if len(X_tr) > TABPFN_MAX_TRAIN:
                sub  = _subsample_balanced(X_tr, y_tr, TABPFN_MAX_TRAIN)
                X_tr, y_tr = X_tr[sub], y_tr[sub]
            model, is_tabpfn = _make_model(TabPFNClass, len(X_tr), X.shape[1])
            try:
                if is_tabpfn:
                    model.fit(X_tr, y_tr)
                else:
                    sw = compute_sample_weight("balanced", y_tr)
                    model.fit(X_tr, y_tr, sample_weight=sw)
                oof_t[va] = model.predict_proba(X.iloc[va].values)[:, 1]
            except Exception as e:
                print(f"    [{tier_lbl}] 오류: {e}")

        d.loc[mask, "risk_score"] = oof_t

    # rank-percentile 정규화
    d["risk_pct"] = np.nan
    for tier_lbl in ["T1", "T2", "T3"]:
        mask = (d["tier"] == tier_lbl) & d["risk_score"].notna()
        if mask.sum() < 2:
            continue
        d.loc[mask, "risk_pct"] = rankdata(
            d.loc[mask, "risk_score"].values) / (mask.sum() + 1)

    return d


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def main():
    TabPFNClass, tabpfn_ver = _load_tabpfn()
    d = load_person_period()

    feats = [f for f in [
        "dividend_coverage", "payout_ratio", "debt_ratio",
        "interest_coverage", "revenue_yoy_pct",
        "ni_to_ta", "ebit_to_ta", "eq_to_tl", "rev_to_ta",
        "fcf_to_ta", "ocf_to_ta", "liab_to_ta",
        "ocf_cov", "fcf_cov", "capex_ratio", "fcf_negative",
        "altman_z",
        "dividend_coverage_chg", "debt_ratio_chg",
        "payout_ratio_chg", "ocf_cov_chg",
        "t_index",
        # 매크로 피처
        "bok_rate", "kospi_ret", "rate_chg",
        # 롤링 트렌드
        "debt_ratio_slope", "dividend_coverage_slope", "ocf_to_ta_slope",
    ] if f in d.columns]

    # ── Cox PH 스코어 → TabPFN 스태킹 피처 ──────────────────────
    cox_feats_stack = [f for f in [
        "debt_ratio", "ocf_cov", "fcf_cov", "fcf_to_ta", "ocf_to_ta",
        "liab_to_ta", "dividend_coverage", "altman_z",
        "bok_rate", "rate_chg",
    ] if f in d.columns]

    print("[0] Cox PH → 스태킹 스코어 생성...")
    try:
        from lifelines import CoxPHFitter
        cox_d = d[cox_feats_stack + ["event_next", "t_index", "stock_code"]].copy()
        for c in cox_feats_stack:
            cox_d[c] = cox_d[c].fillna(cox_d[c].median())
        # 분산 0 피처 제거
        zero_var = [c for c in cox_feats_stack if cox_d[c].std() < 1e-8]
        cox_feats_use = [c for c in cox_feats_stack if c not in zero_var]
        cph = CoxPHFitter(penalizer=1.0, l1_ratio=0.0)
        cph.fit(cox_d[cox_feats_use + ["t_index", "event_next"]],
                duration_col="t_index", event_col="event_next")
        # 예측값: partial hazard (높을수록 위험)
        d["cox_score"] = cph.predict_partial_hazard(
            cox_d[cox_feats_use + ["t_index", "event_next"]])
        # rank-percentile 정규화
        d["cox_score"] = rankdata(d["cox_score"].fillna(0)) / (len(d) + 1)
        feats = feats + ["cox_score"]
        print(f"    Cox 스태킹 피처 추가 완료 (피처 총 {len(feats)}개)")
    except Exception as e:
        print(f"    Cox 스태킹 실패: {e}")

    model_label = f"TabPFN v{tabpfn_ver}" if TabPFNClass else "HistGBM (fallback)"

    print("=" * 65)
    print(f"AI Cashflow OS — 배당 생존분석 v4  [{model_label}]")
    print("=" * 65)
    tier_dist = d["div_history_yrs"].apply(
        lambda x: "T1(<3yr)" if x <= 2 else ("T2(3-4yr)" if x <= 4 else "T3(5yr+)")
    ).value_counts()
    print(f"\n[데이터] person-period {len(d)} | 종목 {d['stock_code'].nunique()}")
    print(f"  event 1yr={d['event_next'].mean()*100:.1f}% | "
          f"event 3yr={d['event_3yr'].mean()*100:.1f}%")
    print(f"  Tier: {dict(tier_dist)}")
    print(f"  피처 {len(feats)}개\n")

    # ── 1. 1yr Hazard ──
    hz_label = "TabPFN" if TabPFNClass else "HistGBM"
    print(f"[1] 1yr Hazard ({hz_label}, GroupKFold)...")
    oof_1yr, pr_1yr, roc_1yr, ev_1yr, m1 = cv_scores_tabpfn(
        d, feats, "event_next", TabPFNClass)
    cidx_1yr = time_dependent_cindex(d, oof_1yr)
    print(f"    [{m1}] PR-AUC {pr_1yr:.3f} | ROC {roc_1yr:.3f} | C-index {cidx_1yr:.3f}")

    # ── 2. 3yr Hazard ──
    print(f"\n[2] 3yr Hazard ({hz_label}, event_3yr)...")
    oof_3yr, pr_3yr, roc_3yr, ev_3yr, m2 = cv_scores_tabpfn(
        d, feats, "event_3yr", TabPFNClass)
    print(f"    [{m2}] PR-AUC {pr_3yr:.3f} | ROC {roc_3yr:.3f} | "
          f"이벤트율 {ev_3yr*100:.1f}%")

    # ── 3. 앙상블 ──
    oof_ens  = 0.5 * oof_1yr + 0.5 * oof_3yr
    mk_ens   = ~np.isnan(oof_ens)
    if mk_ens.sum() < 2 or d["event_next"][mk_ens].sum() == 0:
        roc_ens = 0.5
    else:
        roc_ens  = roc_auc_score(d["event_next"][mk_ens], oof_ens[mk_ens])
    cidx_ens = time_dependent_cindex(d, oof_ens)
    print(f"\n[3] 앙상블 (1yr + 3yr)")
    print(f"    ROC {roc_ens:.3f} | C-index {cidx_ens:.3f}")

    # ── 4. Altman 벤치마크 ──
    roc_alt, n_alt = altman_benchmark(d)
    print(f"\n[4] Altman Z-score 벤치마크")
    print(f"    ROC {roc_alt:.3f}  (n={n_alt}, 전체의 {n_alt/len(d)*100:.0f}% 커버)")

    # ── 5. Cox PH ──
    print("\n[5] Cox Proportional Hazards (lifelines)...")
    # 고가용 피처 우선 (NaN 중앙값 대체로 전 종목 활용)
    cox_feats = [f for f in [
        "debt_ratio", "ocf_cov", "fcf_cov", "fcf_to_ta", "ocf_to_ta",
        "liab_to_ta", "capex_ratio", "dividend_coverage", "altman_z",
        "dividend_coverage_chg", "ocf_cov_chg",
    ] if f in d.columns]
    cox_res = run_cox_ph(d, cox_feats)
    if "error" not in cox_res:
        print(f"    C-index {cox_res['c_index']:.3f} | "
              f"종목 {cox_res['n_stocks']} | 이벤트 {cox_res['n_events']}")
        print("    주요 Hazard Ratio:")
        for feat, coef in list(cox_res["top_features"]["coef"].items())[:5]:
            hr = cox_res["top_features"]["exp(coef)"][feat]
            p  = cox_res["top_features"]["p"][feat]
            print(f"      {feat:<25} coef={coef:+.3f}  HR={hr:.3f}  p={p:.3f}")
    else:
        print(f"    SKIP: {cox_res['error']}")

    # ── 6. 3-Tier 모델 ──
    print(f"\n[6] 3-Tier 모델 (T1=Altman, T2/T3={model_label})...")
    d_tier    = run_tier_model(d, feats, TabPFNClass)
    mk_t      = d_tier["risk_pct"].notna()
    roc_tier  = roc_auc_score(d_tier.loc[mk_t, "event_next"],
                               d_tier.loc[mk_t, "risk_pct"])
    cidx_tier = time_dependent_cindex(
        d_tier[mk_t].reset_index(drop=True),
        d_tier.loc[mk_t, "risk_pct"].values)
    print(f"    ROC {roc_tier:.3f} | C-index {cidx_tier:.3f}")
    for tier_lbl in ["T1", "T2", "T3"]:
        sub    = d_tier[d_tier["tier"] == tier_lbl]
        sub_mk = sub["risk_score"].notna()
        if sub_mk.sum() > 10 and sub.loc[sub_mk, "event_next"].sum() > 1:
            try:
                r = roc_auc_score(sub.loc[sub_mk, "event_next"],
                                  sub.loc[sub_mk, "risk_score"])
                method = "Altman" if tier_lbl == "T1" else model_label
                print(f"    {tier_lbl}: n={int(sub_mk.sum())} | "
                      f"pos={int(sub.loc[sub_mk,'event_next'].sum())} | "
                      f"ROC {r:.3f}  [{method}]")
            except Exception:
                pass

    # ── 7. Precision@K ──
    print("\n[7] Precision@K (위험 상위 K개 중 실제 삭감이력 종목 비율)")
    scores = d_tier["risk_pct"].fillna(pd.Series(oof_1yr, index=d_tier.index))
    latest = d_tier.groupby("stock_code").tail(1).copy()
    latest["hz"] = scores.reindex(latest.index)
    latest = latest.dropna(subset=["hz"])
    ever_cut = d_tier[d_tier["event_next"] == 1]["stock_code"].unique()
    for k in [10, 20, 30]:
        top_k = latest.nlargest(k, "hz")
        prec  = top_k["stock_code"].isin(ever_cut).mean()
        print(f"    Precision@{k:2d}: {prec*100:.0f}%  "
              f"({int(prec*k)}/{k}개 실제 삭감이력)")

    # ── 7-b. Threshold별 Precision / Recall 분석 ──────────────────
    print("\n[7-b] Threshold별 Precision / Recall (종목 단위, 배당삭감 이력 기준)")
    n_pos_stocks = len(set(latest["stock_code"]) & set(ever_cut))
    n_total_stocks = len(latest)
    base_rate = n_pos_stocks / n_total_stocks if n_total_stocks else 0
    print(f"  전체 종목 {n_total_stocks}개 | 삭감이력 {n_pos_stocks}개 | base rate {base_rate*100:.1f}%")
    print(f"  {'Threshold':>9} {'제거':>5} {'P(%)':>7} {'R(%)':>7} {'F1':>6} {'안전오제거':>9} {'위험포착':>7}")
    print("  " + "-" * 58)
    threshold_rows = []
    for t in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        flagged = latest[latest["hz"] > t]
        n_flag = len(flagged)
        tp = int(flagged["stock_code"].isin(ever_cut).sum())
        fp = n_flag - tp
        fn = n_pos_stocks - tp
        prec = tp / n_flag  if n_flag > 0 else 0.0
        rec  = tp / n_pos_stocks if n_pos_stocks > 0 else 0.0
        f1   = 2*prec*rec / (prec+rec) if (prec+rec) > 0 else 0.0
        print(f"  {t:>9.2f} {n_flag:>5} {prec*100:>6.1f}% {rec*100:>6.1f}% {f1:>6.3f} {fp:>9} {tp:>7}")
        threshold_rows.append({
            "threshold":      t,
            "n_removed":      n_flag,
            "precision":      round(prec, 4),
            "recall":         round(rec, 4),
            "f1":             round(f1, 4),
            "false_positive": fp,   # 안전 종목 오제거 수
            "true_positive":  tp,   # 실제 위험 포착 수
        })

    # ── 8. 생존곡선 예시 ──
    print("\n[8] 배당 생존곡선 (최고위험 5 / 최저위험 5)")
    if "name" in d_tier.columns:
        name_map = d_tier.groupby("stock_code")["name"].first()
        latest["name"] = latest["stock_code"].map(name_map)
    else:
        latest["name"] = latest["stock_code"]
    ex = pd.concat([latest.nsmallest(5, "hz"),
                    latest.nlargest(5, "hz")]).drop_duplicates("stock_code")
    out_examples = []
    for _, r in ex.iterrows():
        h     = float(r["hz"])
        t     = str(r.get("tier", "?"))
        curve = {f"{k}y": round((1-h)**k * 100, 1) for k in (1, 3, 5)}
        nm    = str(r.get("name", r["stock_code"]))[:15]
        print(f"  [{t}] {nm:15}  hz={h*100:4.1f}%  "
              f"1y={curve['1y']}%  3y={curve['3y']}%  5y={curve['5y']}%")
        out_examples.append({
            "code": r["stock_code"], "name": nm, "tier": t,
            "hazard": round(h, 4), **curve})

    # ── 종목별 위험 스코어 저장 (pick_kr_stocks hard gate용) ──
    latest_all = d_tier.groupby("stock_code").tail(1).copy()
    latest_all["hz"] = d_tier["risk_pct"].reindex(latest_all.index)
    name_map2 = d_tier.groupby("stock_code")["name"].first() if "name" in d_tier.columns else {}
    stock_risk = {}
    for _, r in latest_all.iterrows():
        hz = float(r["hz"]) if pd.notna(r.get("hz")) else 0.5
        stock_risk[str(r["stock_code"])] = {
            "hazard_pct": round(hz, 4),
            "tier": str(r.get("tier", "T3")),
            "survival_1y": round((1 - hz) * 100, 1),
            "survival_3y": round((1 - hz) ** 3 * 100, 1),
            "name": str(name_map2.get(r["stock_code"], r["stock_code"])),
        }

    # ── 저장 ──
    cox_out = ({k: v for k, v in cox_res.items() if k != "top_features"}
               if "error" not in cox_res else cox_res)
    res = {
        "version":        "v4_tabpfn_cox",
        "model":          model_label,
        "n_stocks":       int(d["stock_code"].nunique()),
        "event_rate_1yr": round(float(ev_1yr), 4),
        "event_rate_3yr": round(float(ev_3yr), 4),
        "scores": {
            "tabpfn_1yr":   {"roc": round(roc_1yr, 3), "pr_auc": round(pr_1yr, 3), "c_index": cidx_1yr},
            "tabpfn_3yr":   {"roc": round(roc_3yr, 3), "pr_auc": round(pr_3yr, 3)},
            "ensemble":     {"roc": round(roc_ens, 3), "c_index": cidx_ens},
            "3tier":        {"roc": round(roc_tier, 3), "c_index": cidx_tier},
            "altman_bench": {"roc": roc_alt, "n": n_alt},
            "cox_ph":       cox_out,
        },
        "stock_risk":  stock_risk,   # ← 종목별 위험도 (pick_kr_stocks 연동)
        "features": feats,
        "examples": out_examples,
        "threshold_analysis": threshold_rows,  # ← gate 설정 근거
    }
    os.makedirs(os.path.join(BASE, "results"), exist_ok=True)
    out_path = os.path.join(BASE, "results", "survival_pd_v4.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)

    print(f"\n저장: results/survival_pd_v4.json")
    print("\n" + "=" * 65)
    print(f"{'모델':<38} {'ROC':>6} {'C-index':>8}")
    print("-" * 65)
    print(f"{f'{hz_label} 1yr (GroupKFold)':<38} {roc_1yr:>6.3f} {cidx_1yr:>8.3f}")
    print(f"{f'{hz_label} 3yr':<38} {roc_3yr:>6.3f} {'—':>8}")
    print(f"{'앙상블 (1yr+3yr)':<38} {roc_ens:>6.3f} {cidx_ens:>8.3f}")
    print(f"{f'3-Tier (T1=Altman, T2/T3={hz_label})':<38} {roc_tier:>6.3f} {cidx_tier:>8.3f}")
    if not np.isnan(roc_alt):
        gap_ens  = roc_ens - roc_alt
        gap_tier = roc_tier - roc_alt
        best_gap = max(gap_ens, gap_tier)
        marker = "★ 앙상블 돌파!" if gap_ens > 0 else f"({gap_tier:+.3f})"
        print(f"{'Altman 벤치마크':<38} {roc_alt:>6.3f} {'—':>8}  {marker}")
    if "error" not in cox_res:
        cox_n = cox_res['n_stocks']
        print(f"{'Cox PH (lifelines)':<38} {'—':>6} {cox_res['c_index']:>8.3f}  ★ 최고 (n={cox_n})")
    print("=" * 65)

    return res


if __name__ == "__main__":
    main()

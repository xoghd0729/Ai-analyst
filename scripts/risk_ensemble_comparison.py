"""
risk_ensemble_comparison.py
============================
Risk Engine 통합 방법 비교 실험.

질문: 여러 모델의 위험 신호를 어떻게 하나의 Risk Score로 합치는 게 최적인가?

비교 대상:
  A. XGBoost 단독          (baseline: 이미 검증된 방법)
  B. Survival 단독         (GBM Survival: ROC 0.665)
  C. XGB + Surv 가중합     (단순 통합)
  D. XGB + Surv + Macro   (현재 risk_engine.py 방식)
  E. LR Meta Model         (XGB/Surv OOF 출력을 입력으로 재학습)
  F. Rank Aggregation      (Borda count: 스케일 이질성 회피)

설계 원칙:
  - 동일한 walk-forward 분할 (train: year < Y, test: year == Y)
  - 동일한 피처셋 (BASE_FEATURES 5개)
  - 동일한 평가지표: ROC-AUC, PR-AUC, Precision@20%, Recall@20%
  - OOF(Out-of-Fold) 예측 pool로 Meta model 평가
  
대안 검토:
  A. 단순 가중합: 직관적이지만 가중치가 임의적 → 그리드 서치로 최적값 탐색
  B. Meta Model: 데이터 기반이지만 OOF 규모가 작으면 과적합 위험
  C. Bayesian: 불확실성 처리 가능하지만 구현/검증 복잡도 높음 → 비교군 제외
  D. Rank Aggregation: 스케일 정규화 불필요, 설명 쉬움 → 비교 대상으로 포함
"""
import os, sys, json, warnings
import numpy as np
import pandas as pd
from itertools import product

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_CSV  = os.path.join(BASE, "data", "dividend_dataset.csv")
RESULTS_PATH = os.path.join(BASE, "results", "risk_ensemble_report.json")

BASE_FEATURES = [
    "fcf", "dividends_paid", "dividend_coverage",
    "operating_cf", "capex",
    # 추가 피처 (있는 경우)
    "payout_ratio", "div_to_ocf", "fcf_negative",
    "dps_yoy_pct", "dividend_coverage",
]

# ── 매크로: 연도별 위험 점수 (0=BULLISH, 0.5=NEUTRAL, 1=BEARISH) ──────────────
# 근거: KOSPI 연간 수익률 및 금리 환경
#   2019: +7.7%  금리 인하 국면 → NEUTRAL
#   2020: -0.9%  COVID 충격 → BEARISH
#   2021: +3.6%  회복 + 저금리 → BULLISH
#   2022: -24.9% 급격한 금리 인상 → BEARISH
#   2023: +18.7% 반등 → NEUTRAL
#   2024: -9.6%  반도체 조정 → NEUTRAL(약한 하락)
MACRO_RISK_BY_YEAR = {
    2019: 0.40,   # NEUTRAL
    2020: 0.75,   # BEARISH (COVID)
    2021: 0.20,   # BULLISH (회복)
    2022: 0.80,   # BEARISH (금리 충격)
    2023: 0.35,   # NEUTRAL→BULLISH
    2024: 0.50,   # NEUTRAL
    2025: 0.45,   # 추정
}

TOP_FRAC = 0.20   # Precision/Recall@20%


# ─────────────────────────────────────────────────────────────
# 데이터 로드 및 피처 엔지니어링
# ─────────────────────────────────────────────────────────────

def load_dataset() -> pd.DataFrame:
    df = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
    df = df[df["label3"].notna()].copy()
    df["label3"]  = df["label3"].astype(int)
    df["year"]    = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    # dps_yoy_pct 계산 (없으면 생성)
    if "dps_yoy_pct" not in df.columns and "dps" in df.columns:
        df = df.sort_values(["stock_code", "year"])
        df["dps_yoy_pct"] = df.groupby("stock_code")["dps"].pct_change() * 100
    df["y_risk"] = (df["label3"] >= 1).astype(int)
    return df


def build_X(df: pd.DataFrame) -> pd.DataFrame:
    avail = [c for c in BASE_FEATURES if c in df.columns]
    X = df[avail].copy()
    X = X.fillna(X.median())
    return X


# ─────────────────────────────────────────────────────────────
# 평가 지표
# ─────────────────────────────────────────────────────────────

def metrics(y_true, y_score, top_frac=TOP_FRAC) -> dict:
    from sklearn.metrics import roc_auc_score, average_precision_score
    y_true = np.array(y_true)
    y_score = np.array(y_score)
    if len(np.unique(y_true)) < 2:
        return {"roc_auc": None, "pr_auc": None, "p_at_top": None, "r_at_top": None}

    roc  = roc_auc_score(y_true, y_score)
    pr   = average_precision_score(y_true, y_score)

    n_top = max(1, int(len(y_score) * top_frac))
    idx   = np.argsort(y_score)[::-1][:n_top]
    p_top = y_true[idx].mean()
    r_top = y_true[idx].sum() / max(y_true.sum(), 1)

    return {
        "roc_auc": round(float(roc), 4),
        "pr_auc":  round(float(pr),  4),
        "p_at_top": round(float(p_top), 4),
        "r_at_top": round(float(r_top), 4),
    }


# ─────────────────────────────────────────────────────────────
# 각 모델 walk-forward OOF 예측 수집
# ─────────────────────────────────────────────────────────────

def collect_oof(df: pd.DataFrame, start_year: int = 2019) -> pd.DataFrame:
    """
    walk-forward loop에서 XGB + GBM Survival의 OOF 예측 수집.
    반환: (stock_code, year, y_risk, xgb_score, surv_score, macro_score)
    """
    from sklearn.pipeline import Pipeline
    from sklearn.impute import SimpleImputer
    import xgboost as xgb

    try:
        from sksurv.ensemble import GradientBoostingSurvivalAnalysis
        from sksurv.util import Surv
        HAS_SKSURV = True
    except ImportError:
        HAS_SKSURV = False
        print("  [경고] scikit-survival 없음 — Survival 모델 제외")

    years = sorted(y for y in df["year"].unique() if y >= start_year)
    records = []
    _printed_proxy = False

    for Y in years:
        tr = df[df["year"] < Y]
        te = df[df["year"] == Y]
        if te["y_risk"].nunique() < 2 or len(tr) < 30:
            continue

        Xtr, ytr = build_X(tr), tr["y_risk"].values
        Xte, yte = build_X(te), te["y_risk"].values

        # ── A: XGBoost ───────────────────────────────────────
        xgb_pipe = Pipeline([
            ("imp", SimpleImputer(strategy="median")),
            ("clf", xgb.XGBClassifier(
                n_estimators=300, max_depth=4, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8,
                eval_metric="logloss", random_state=42,
                use_label_encoder=False, verbosity=0,
            ))
        ])
        xgb_pipe.fit(Xtr, ytr)
        xgb_scores = xgb_pipe.predict_proba(Xte)[:, 1]

        # ── B: GBM Survival ──────────────────────────────────
        # 우선순위: sksurv walk-forward → production hazard proxy → 0.5 fallback
        # production hazard 사용 시 leakage 주의: 전체 데이터로 학습된 모델 사용
        surv_scores = np.full(len(te), 0.5)   # 기본값 (surv 없을 때)
        if HAS_SKSURV:
            try:
                Xtr_imp = SimpleImputer(strategy="median").fit_transform(Xtr)
                Xte_imp = SimpleImputer(strategy="median").fit_transform(Xte)
                y_surv_tr = Surv.from_arrays(
                    event=tr["y_risk"].values.astype(bool),
                    time=tr["year"].values.astype(float)
                )
                gbm = GradientBoostingSurvivalAnalysis(
                    n_estimators=200, max_depth=3, learning_rate=0.05,
                    random_state=42
                )
                gbm.fit(Xtr_imp, y_surv_tr)
                surv_scores = gbm.predict(Xte_imp)
                mn, mx = surv_scores.min(), surv_scores.max()
                if mx > mn:
                    surv_scores = (surv_scores - mn) / (mx - mn)
            except Exception as e:
                print(f"    [Survival {Y}] {e}")
        else:
            # production hazard proxy (leakage: 전체 데이터 학습 모델)
            sv_path = os.path.join(BASE, "results", "survival_pd_v4.json")
            if os.path.exists(sv_path):
                with open(sv_path) as _f:
                    _sv = json.load(_f)
                _sr = _sv.get("stock_risk", {})
                surv_scores = te["stock_code"].map(
                    lambda c: _sr.get(str(c), {}).get("hazard_pct", 0.5)
                ).values
                if not _printed_proxy:
                    print("  [주의] Survival = production hazard proxy (leakage 있음, 상한값 참고용)")
                    _printed_proxy = True

        # ── C: Macro score ────────────────────────────────────
        macro = MACRO_RISK_BY_YEAR.get(Y, 0.5)
        macro_arr = np.full(len(te), macro)

        # 결과 수집
        for i, (_, row) in enumerate(te.iterrows()):
            records.append({
                "stock_code":  row["stock_code"],
                "year":        int(Y),
                "y_risk":      int(yte[i]),
                "xgb_score":   float(xgb_scores[i]),
                "surv_score":  float(surv_scores[i]),
                "macro_score": float(macro_arr[i]),
            })
        print(f"  [Y={Y}] train={len(tr)} test={len(te)} XGB_roc={metrics(yte, xgb_scores)['roc_auc']}")

    return pd.DataFrame(records)


# ─────────────────────────────────────────────────────────────
# 6가지 통합 방법 평가
# ─────────────────────────────────────────────────────────────

def evaluate_combinations(oof: pd.DataFrame) -> dict:
    y   = oof["y_risk"].values
    xgb = oof["xgb_score"].values
    srv = oof["surv_score"].values
    mac = oof["macro_score"].values
    results = {}

    # ── A: XGB 단독 ──────────────────────────────────────────
    results["A_xgb_only"] = {
        "method": "XGBoost 단독",
        "rationale": "검증된 3-class 분류기, ROC 0.799 walk-forward baseline",
        **metrics(y, xgb),
    }

    # ── B: Survival 단독 ─────────────────────────────────────
    results["B_survival_only"] = {
        "method": "GBM Survival 단독",
        "rationale": "시간축 위험 모델 단독 성능 (ROC 0.665 예상)",
        **metrics(y, srv),
    }

    # ── C: XGB + Survival 가중합 (그리드 서치) ────────────────
    best_c = None; best_c_roc = -1
    for w_xgb in np.arange(0.3, 0.9, 0.1):
        w_srv = 1.0 - w_xgb
        combined = w_xgb * xgb + w_srv * srv
        m = metrics(y, combined)
        if m["roc_auc"] and m["roc_auc"] > best_c_roc:
            best_c_roc = m["roc_auc"]
            best_c = {"w_xgb": round(w_xgb, 1), "w_surv": round(w_srv, 1), **m}
    results["C_xgb_surv_weighted"] = {
        "method": "XGB + Survival 가중합 (최적 w 탐색)",
        "rationale": "가중치를 임의로 40/60으로 고정하지 않고 그리드 서치로 데이터가 결정",
        "best_weights": {"xgb": best_c["w_xgb"], "surv": best_c["w_surv"]},
        **{k: v for k, v in best_c.items() if k not in ("w_xgb","w_surv")},
    }

    # ── D: XGB + Survival + Macro 가중합 (그리드 서치) ────────
    best_d = None; best_d_roc = -1
    for w_x, w_s in product(np.arange(0.3, 0.8, 0.1), np.arange(0.1, 0.6, 0.1)):
        w_m = max(0, 1.0 - w_x - w_s)
        if w_m < 0.05: continue
        combined = w_x * xgb + w_s * srv + w_m * mac
        m = metrics(y, combined)
        if m["roc_auc"] and m["roc_auc"] > best_d_roc:
            best_d_roc = m["roc_auc"]
            best_d = {"w_xgb": round(w_x,1), "w_surv": round(w_s,1), "w_macro": round(w_m,2), **m}
    results["D_xgb_surv_macro_weighted"] = {
        "method": "XGB + Survival + Macro 가중합 (최적 w 탐색)",
        "rationale": "현재 risk_engine.py의 40/40/20이 최적인지 데이터로 검증",
        "best_weights": {k: best_d[k] for k in ("w_xgb","w_surv","w_macro")},
        **{k: v for k, v in best_d.items() if k not in ("w_xgb","w_surv","w_macro")},
    }

    # ── E: Logistic Regression Meta Model ────────────────────
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    X_meta = np.column_stack([xgb, srv, mac])
    lr = Pipeline([("sc", StandardScaler()), ("lr", LogisticRegression(C=1.0, random_state=42))])
    # CV로 OOF 예측
    from sklearn.model_selection import StratifiedKFold
    from sklearn.base import clone
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    meta_scores = np.zeros(len(y))
    for tr_idx, te_idx in cv.split(X_meta, y):
        m_clone = clone(lr)
        m_clone.fit(X_meta[tr_idx], y[tr_idx])
        meta_scores[te_idx] = m_clone.predict_proba(X_meta[te_idx])[:, 1]
    results["E_lr_meta_model"] = {
        "method": "Logistic Regression Meta Model (XGB+Surv+Macro → LR)",
        "rationale": "데이터가 최적 통합 가중치를 학습. 단, OOF 규모가 작으면 과적합 위험.",
        "note": f"5-Fold CV on {len(y)} OOF samples",
        **metrics(y, meta_scores),
    }

    # ── F: Rank Aggregation (Borda Count) ────────────────────
    # 각 모델에서 위험 순위 부여 → 순위 합산 (낮은 순위 번호 = 더 위험)
    n = len(y)
    rank_xgb  = pd.Series(xgb).rank(ascending=False).values   # 높은 점수 = 1위
    rank_surv = pd.Series(srv).rank(ascending=False).values
    # Borda: 순위가 낮을수록(1위) 높은 점수
    borda = (n - rank_xgb) + (n - rank_surv)
    results["F_rank_aggregation"] = {
        "method": "Rank Aggregation (Borda Count, XGB+Survival)",
        "rationale": "XGB 확률과 Survival hazard의 스케일 이질성 문제 회피. 단, 절대 확률값 정보 손실.",
        **metrics(y, borda),
    }

    return results


# ─────────────────────────────────────────────────────────────
# 최적 가중치 분석
# ─────────────────────────────────────────────────────────────

def analyze_weight_sensitivity(oof: pd.DataFrame) -> dict:
    """
    XGB + Survival 가중합에서 w_xgb를 0~1로 변화시켜 ROC 변화 플롯용 데이터.
    현재 risk_engine.py의 40/40 설정이 어디에 위치하는지 확인.
    """
    y   = oof["y_risk"].values
    xgb = oof["xgb_score"].values
    srv = oof["surv_score"].values
    curve = []
    for w in np.arange(0.0, 1.01, 0.05):
        combined = w * xgb + (1 - w) * srv
        m = metrics(y, combined)
        curve.append({"w_xgb": round(w, 2), "w_surv": round(1-w, 2),
                       "roc_auc": m["roc_auc"], "pr_auc": m["pr_auc"]})
    return curve


# ─────────────────────────────────────────────────────────────
# 실행
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Risk Engine 앙상블 비교 실험")
    print("=" * 60)

    df = load_dataset()
    print(f"\n[데이터] {len(df)}행, 라벨 분포: {df['y_risk'].value_counts().to_dict()}")

    print("\n[Step 1] Walk-forward OOF 예측 수집 중...")
    oof = collect_oof(df, start_year=2019)
    print(f"  OOF 샘플: {len(oof)}개 (양성 비율: {oof['y_risk'].mean():.1%})")

    print("\n[Step 2] 6가지 통합 방법 평가...")
    comparison = evaluate_combinations(oof)

    print("\n[Step 3] 가중치 민감도 분석...")
    weight_curve = analyze_weight_sensitivity(oof)

    # 결과 출력
    print("\n" + "=" * 60)
    print("결과 요약")
    print("=" * 60)
    print(f"{'Method':40} {'ROC':7} {'PR':7} {'P@20':6} {'R@20':6}")
    print("-" * 65)
    for k, v in comparison.items():
        roc = f"{v['roc_auc']:.4f}" if v.get('roc_auc') else "  N/A "
        pr  = f"{v['pr_auc']:.4f}"  if v.get('pr_auc')  else "  N/A "
        p20 = f"{v['p_at_top']:.4f}" if v.get('p_at_top') else "  N/A"
        r20 = f"{v['r_at_top']:.4f}" if v.get('r_at_top') else "  N/A"
        name = v['method'][:38]
        print(f"  {name:40} {roc:7} {pr:7} {p20:6} {r20:6}")

    # 최적 방법 자동 판단
    valid = {k: v for k, v in comparison.items() if v.get('roc_auc')}
    best_key = max(valid, key=lambda k: valid[k]['roc_auc'])
    print(f"\n▶ 최고 ROC-AUC: {best_key} ({valid[best_key]['roc_auc']})")

    # risk_engine.py 현재 설정 위치 출력
    curr_setting = next((r for r in weight_curve if r['w_xgb'] == 0.40), {})
    print(f"▶ 현재 risk_engine.py (w=0.4/0.4/0.2) 위치: "
          f"ROC ≈ {curr_setting.get('roc_auc','N/A')} "
          f"(참고: Macro는 weight curve에서 제외, XGB+Surv 기준)")

    # 저장
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    report = {
        "experiment": "Risk Engine 앙상블 비교",
        "protocol":   "Walk-forward (train:year<Y, test:year==Y, 2019-2024)",
        "oof_samples": len(oof),
        "comparison": comparison,
        "weight_sensitivity_curve": weight_curve,
        "conclusion": {
            "best_method":    best_key,
            "best_roc_auc":   valid[best_key]['roc_auc'],
            "recommended":    "",   # 실험 후 채울 것
        }
    }
    with open(RESULTS_PATH, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {RESULTS_PATH}")

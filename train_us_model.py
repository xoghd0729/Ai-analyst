"""
train_us_model.py — 미국 배당주 XGBoost 배당 삭감 예측 모델 학습

■ 한국 모델(train_model.py)과 완전 분리된 이유
  - 한국: payout 30~40% 정상 / 미국: 30~70% 정상 → 임계값 다름
  - 한국: DART 억원 단위 / 미국: yfinance USD 원화 단위 → 스케일 90,000x 차이
  - 한국: 10년 이상 데이터 / 미국: yfinance 4년 제한 → 피처 전략 다름
  - 분리 후 공통 인터페이스(get_ml_risk)로 통합

■ 데이터
  data/us_dividend_dataset.csv — build_us_dataset.py 생성 (87종목 × 4년)

■ 피처 전략
  - 절대금액(fcf, dividends_paid 등) 제외 → 미국/한국 스케일 혼용 방지
  - 비율/상대 지표만 사용: payout_ratio, dividend_coverage, dps_yoy_pct,
    div_to_ocf, shareholder_yield, fcf_negative, net_debt_ebitda

■ 라벨
  dividend_cut = 1 (dps_yoy_pct < -5%)

■ 학습 흐름
  1. 데이터 로드 / 전처리
  2. 피처 엔지니어링 (파생 피처)
  3. TimeSeriesSplit 교차검증
  4. Optuna 하이퍼파라미터 최적화
  5. 최종 모델 학습 + 저장
  6. SHAP 피처 중요도 출력
"""

import os
import warnings
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score,
    confusion_matrix, ConfusionMatrixDisplay, classification_report,
)
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
import xgboost as xgb
import joblib

warnings.filterwarnings("ignore")

# ── 한글 폰트 ─────────────────────────────────────────────────
plt.rcParams["axes.unicode_minus"] = False
for _fp in ["/System/Library/Fonts/Supplemental/AppleGothic.ttf", "/Library/Fonts/NanumGothic.ttf"]:
    if os.path.exists(_fp):
        fm.fontManager.addfont(_fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=_fp).get_name()
        break

# ── 경로 설정 ────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(BASE_DIR, "data", "us_dividend_dataset.csv")
MODEL_DIR  = os.path.join(BASE_DIR, "models");  os.makedirs(MODEL_DIR,  exist_ok=True)
RESULT_DIR = os.path.join(BASE_DIR, "results"); os.makedirs(RESULT_DIR, exist_ok=True)
MODEL_PATH = os.path.join(MODEL_DIR, "us_dividend_cut_model.pkl")

# ── 미국 모델 피처 (비율/상대 지표만 사용, 절대금액 제외) ────
# 절대금액(fcf, dividends_paid 등)은 USD 단위라 KR 모델과 충돌 → 제외
FEATURES = [
    "payout_ratio",       # 배당성향 % (핵심: 100% 초과면 위험)
    "dividend_coverage",  # FCF / 배당지급액 (2배 이상 안전)
    "dps_yoy_pct",        # 주당배당금 전년 대비 증감률 (음수 = 위험 신호)
    "div_to_ocf",         # 배당 / 영업현금흐름 비율
    "fcf_negative",       # FCF 음수 여부 (0/1 binary)
    "shareholder_yield",  # 배당수익률 + 자사주수익률
    "net_debt_ebitda",    # 부채 레버리지 (높을수록 위험)
    "consecutive_years",  # 연속 배당 지급 연수 (배당귀족 판별)
]

TARGET = "dividend_cut"

# ─────────────────────────────────────────────────────────────
print("=" * 65)
print("  US XGBoost 배당 삭감 예측 모델 학습")
print("=" * 65)

# ─────────────────────────────────────────────────────────────
# 1. 데이터 로드
# ─────────────────────────────────────────────────────────────
df = pd.read_csv(DATA_PATH)
df = df.dropna(subset=[TARGET])

n_tickers = df["ticker"].nunique()
n_rows    = len(df)
n_cut     = int(df[TARGET].sum())

print(f"\n[1] 데이터 로드")
print(f"    {n_rows}행 / {n_tickers}종목 / {df['year'].min()}~{df['year'].max()}년")
print(f"    배당 삭감: {n_cut}건 / 배당 유지: {n_rows - n_cut}건 ({n_cut/n_rows*100:.1f}%)")

# ─────────────────────────────────────────────────────────────
# 2. 피처 정제
# ─────────────────────────────────────────────────────────────
# 사용 가능한 피처만 추출 (데이터에 없는 컬럼 제외)
available = [f for f in FEATURES if f in df.columns]
missing_cols = set(FEATURES) - set(available)
if missing_cols:
    print(f"\n[2] 피처 준비 — 누락 컬럼 제외: {missing_cols}")
else:
    print(f"\n[2] 피처 준비 — {len(available)}개 피처 사용")

# 결측 비율 출력
print("    결측 현황:")
for col in available:
    miss_n = df[col].isna().sum()
    miss_pct = miss_n / len(df) * 100
    flag = "⚠️ " if miss_pct > 30 else "✅"
    print(f"    {flag} {col:<25}: {miss_pct:.0f}%")

X = df[available].copy()
y = df[TARGET].astype(int)

# net_debt_ebitda: 이상치 클리핑 (REIT/자본잠식 등 극단값 방지)
if "net_debt_ebitda" in X.columns:
    X["net_debt_ebitda"] = X["net_debt_ebitda"].clip(-5, 20)

# payout_ratio: 100% 초과 = 위험 구간 binary 피처 추가
if "payout_ratio" in X.columns:
    X["payout_over_100"] = (X["payout_ratio"] > 100).astype(int)
    X["payout_over_80"]  = (X["payout_ratio"] > 80).astype(int)

# dps_yoy 음수 여부 binary
if "dps_yoy_pct" in X.columns:
    X["dps_declining"] = (X["dps_yoy_pct"] < 0).astype(int)

print(f"    → 파생 피처 추가 후 총 {X.shape[1]}개")

# ─────────────────────────────────────────────────────────────
# 3. 시계열 교차검증 (TimeSeriesSplit)
# ─────────────────────────────────────────────────────────────
# 미래 데이터로 과거 예측하는 leakage 방지
# n_splits=3: 4년 데이터 한계 (5 이상은 fold당 데이터 부족)
print(f"\n[3] TimeSeriesSplit 교차검증 (n_splits=3)")

tscv = TimeSeriesSplit(n_splits=3)

# 클래스 불균형 보정 (삭감 3.7% vs 유지 96.3%)
# → scale_pos_weight = 유지수/삭감수
pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)
print(f"    클래스 불균형 — 삭감:{(y==1).sum()} / 유지:{(y==0).sum()} → scale_pos_weight={pos_weight:.1f}")

base_params = {
    "n_estimators":     200,
    "max_depth":        3,       # 과적합 방지 (데이터 적음)
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "scale_pos_weight": pos_weight,
    "eval_metric":      "logloss",
    "random_state":     42,
    "verbosity":        0,
}

cv_aucs, cv_f1s = [], []
imputer = SimpleImputer(strategy="median")
X_imp = imputer.fit_transform(X)

for fold, (train_idx, val_idx) in enumerate(tscv.split(X_imp), 1):
    X_tr, X_val = X_imp[train_idx], X_imp[val_idx]
    y_tr, y_val = y.iloc[train_idx], y.iloc[val_idx]

    model = xgb.XGBClassifier(**base_params)
    model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)

    prob = model.predict_proba(X_val)[:, 1]
    pred = (prob >= 0.3).astype(int)  # threshold 0.3: 삭감 recall 중시

    auc = roc_auc_score(y_val, prob) if y_val.nunique() > 1 else float("nan")
    f1  = f1_score(y_val, pred, zero_division=0)
    cv_aucs.append(auc)
    cv_f1s.append(f1)
    n_cut_val = int(y_val.sum())
    print(f"    Fold {fold}: AUC={auc:.3f}  F1={f1:.3f}  (val 삭감:{n_cut_val}건)")

mean_auc = np.nanmean(cv_aucs)
mean_f1  = np.nanmean(cv_f1s)
print(f"    평균 AUC={mean_auc:.3f}  F1={mean_f1:.3f}")

# ─────────────────────────────────────────────────────────────
# 4. Optuna 하이퍼파라미터 최적화
# ─────────────────────────────────────────────────────────────
print(f"\n[4] Optuna 하이퍼파라미터 최적화 (30 trials)")

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    def objective(trial):
        params = {
            "n_estimators":     trial.suggest_int("n_estimators", 100, 500),
            "max_depth":        trial.suggest_int("max_depth", 2, 5),
            "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "gamma":            trial.suggest_float("gamma", 0.0, 1.0),
            "scale_pos_weight": pos_weight,
            "eval_metric":      "logloss",
            "random_state":     42,
            "verbosity":        0,
        }
        fold_aucs = []
        for tr_idx, val_idx in tscv.split(X_imp):
            X_tr, X_val = X_imp[tr_idx], X_imp[val_idx]
            y_tr, y_val = y.iloc[tr_idx], y.iloc[val_idx]
            if y_val.nunique() < 2:
                continue
            m = xgb.XGBClassifier(**params)
            m.fit(X_tr, y_tr, verbose=False)
            prob = m.predict_proba(X_val)[:, 1]
            fold_aucs.append(roc_auc_score(y_val, prob))
        return np.mean(fold_aucs) if fold_aucs else 0.5

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=30, show_progress_bar=False)
    best_params = {**base_params, **study.best_params}
    print(f"    최적 AUC: {study.best_value:.4f}")
    print(f"    best_params: {study.best_params}")

except ImportError:
    print("    Optuna 미설치 → 기본 파라미터 사용")
    best_params = base_params

# ─────────────────────────────────────────────────────────────
# 5. 최종 모델 학습 (전체 데이터)
# ─────────────────────────────────────────────────────────────
print(f"\n[5] 최종 모델 학습 (전체 {len(X_imp)}행)")

final_model = xgb.XGBClassifier(**{**best_params, "verbosity": 0})
final_model.fit(X_imp, y)

# 파이프라인으로 묶어서 저장 (imputer + model)
pipeline = Pipeline([
    ("imputer", imputer),
    ("model",   final_model),
])

# 전체 데이터 성능 (훈련셋 기준 — 참고용)
prob_all = final_model.predict_proba(X_imp)[:, 1]
pred_all = (prob_all >= 0.3).astype(int)
print(f"\n    훈련셋 성능 (과적합 참고용):")
print(f"    {classification_report(y, pred_all, target_names=['유지','삭감'], zero_division=0)}")

# 저장 — pipeline + 피처 순서 함께 저장 (추론 시 컬럼 순서 보장)
feature_names_final = list(X.columns)
save_bundle = {
    "pipeline":      pipeline,
    "feature_names": feature_names_final,
    "threshold":     0.3,   # 배당 삭감 판정 임계값 (recall 중시)
}
joblib.dump(save_bundle, MODEL_PATH)
print(f"    ✅ 모델 저장: {MODEL_PATH}")
print(f"    피처 순서:   {feature_names_final}")

# ─────────────────────────────────────────────────────────────
# 6. 피처 중요도 저장 (SHAP 없으면 XGBoost built-in)
# ─────────────────────────────────────────────────────────────
print(f"\n[6] 피처 중요도 분석")

feature_names = list(X.columns)
importance_dict = dict(zip(feature_names, final_model.feature_importances_))
importance_sorted = sorted(importance_dict.items(), key=lambda x: x[1], reverse=True)

print("    피처 중요도:")
for feat, imp in importance_sorted:
    bar = "█" * int(imp * 40)
    print(f"    {feat:<30} {imp:.4f}  {bar}")

# results/ 에 저장
fi_path = os.path.join(RESULT_DIR, "us_feature_importance.json")
with open(fi_path, "w", encoding="utf-8") as f:
    # numpy float32 → Python float 변환 (json 직렬화 가능하게)
    json.dump({k: float(v) for k, v in importance_dict.items()}, f, ensure_ascii=False, indent=2)
print(f"\n    피처 중요도 저장: {fi_path}")

# 시각화
fig, ax = plt.subplots(figsize=(10, 6))
feats = [x[0] for x in importance_sorted]
imps  = [x[1] for x in importance_sorted]
colors = ["#EF4444" if i < 3 else "#3B82F6" for i in range(len(feats))]
ax.barh(feats[::-1], imps[::-1], color=colors[::-1])
ax.set_xlabel("Feature Importance (gain)")
ax.set_title("US 배당 삭감 예측 — 피처 중요도")
plt.tight_layout()
fig_path = os.path.join(RESULT_DIR, "us_model_feature_importance.png")
plt.savefig(fig_path, dpi=150, bbox_inches="tight")
plt.close()
print(f"    시각화 저장: {fig_path}")

# ─────────────────────────────────────────────────────────────
# 7. 요약
# ─────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  학습 완료 요약")
print("=" * 65)
print(f"  모델 경로:  {MODEL_PATH}")
print(f"  CV AUC:     {mean_auc:.3f}  (TimeSeriesSplit 3-fold)")
print(f"  CV F1:      {mean_f1:.3f}")
print(f"  피처 수:    {len(feature_names)}개")
print(f"  학습 샘플:  {len(X_imp)}행 / {n_tickers}종목")
print()
print("  다음 단계:")
print("  1. run_thesis_batch.py에서 US 모델 연동")
print("     → get_ml_risk()의 _get_us_rule_risk() 대신 us_dividend_cut_model.pkl 사용")
print("  2. python run_thesis_batch.py --us-only --top 20")
print("=" * 65)

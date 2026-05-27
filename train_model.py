"""
XGBoost 배당 삭감 예측 모델 학습 (v2 — 대용량 데이터셋 대응)

■ 목적
  과거 재무 지표(FCF, 배당지급액, 커버리지 등)로
  다음 연도 배당 삭감 여부(dividend_cut=1)를 예측한다.

■ 데이터 규모
  46종목 × 10년 ≈ 460행  (v1: 5종목 50행 → 과적합)

■ 학습 흐름
  1. 데이터 로드 및 전처리 (결측값 중앙값 대체)
  2. 파생 피처 생성 (payout 비율, FCF 부호 등)
  3. 시계열 고려 TimeSeriesSplit 교차검증
  4. Optuna 하이퍼파라미터 최적화 (50 trials)
  5. 최적 모델로 최종 학습 후 저장
  6. SHAP 값으로 피처 중요도 설명

■ 왜 XGBoost인가
  - 결측값에 강함
  - 소규모 정형 데이터에서 Neural Net보다 안정적
  - Feature Importance / SHAP 으로 투자자에게 설명 가능한 AI
"""

import os
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from sklearn.model_selection import TimeSeriesSplit, cross_validate, train_test_split
from sklearn.metrics import (
    accuracy_score, f1_score, roc_auc_score,
    confusion_matrix, ConfusionMatrixDisplay, classification_report,
)
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import xgboost as xgb
import joblib

warnings.filterwarnings("ignore")

# ── 한글 폰트 ─────────────────────────────────────────────────
plt.rcParams["axes.unicode_minus"] = False
for fp in ["/System/Library/Fonts/Supplemental/AppleGothic.ttf", "/Library/Fonts/NanumGothic.ttf"]:
    if os.path.exists(fp):
        fm.fontManager.addfont(fp)
        plt.rcParams["font.family"] = fm.FontProperties(fname=fp).get_name()
        break

# ── 경로 ─────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
MODEL_DIR  = os.path.join(BASE_DIR, "models");  os.makedirs(MODEL_DIR,  exist_ok=True)
RESULT_DIR = os.path.join(BASE_DIR, "results"); os.makedirs(RESULT_DIR, exist_ok=True)
MODEL_PATH = os.path.join(MODEL_DIR, "dividend_cut_model.pkl")

# ─────────────────────────────────────────────────────────────
# 1. 데이터 로드
# ─────────────────────────────────────────────────────────────
print("=" * 65)
print("  XGBoost 배당 삭감 예측 모델 학습 v2")
print("=" * 65)

df = pd.read_csv(DATA_PATH)
df = df.dropna(subset=["dividend_cut"])
n_stocks = df["stock_code"].nunique()
n_rows   = len(df)
print(f"\n[1] 데이터: {n_rows}행 / {n_stocks}종목")
print(f"    배당 삭감: {int(df['dividend_cut'].sum())}건 / 유지: {int((df['dividend_cut']==0).sum())}건")

# ─────────────────────────────────────────────────────────────
# 2. 피처 엔지니어링
# ─────────────────────────────────────────────────────────────
FEATURES_BASE = [
    "fcf",               # 잉여현금흐름
    "dividends_paid",    # 실제 배당 지급액
    "dividend_coverage", # FCF / 배당지급액
    "operating_cf",      # 영업현금흐름
    "capex",             # 자본지출
]

df_feat = df[FEATURES_BASE].copy()

# 파생 피처
df_feat["div_to_ocf"]   = df["dividends_paid"] / (df["operating_cf"].abs() + 1)
df_feat["fcf_negative"] = (df["fcf"] < 0).astype(int)
df_feat["ocf_to_capex"] = df["operating_cf"] / (df["capex"].abs() + 1)

# payout_ratio가 있으면 추가
if "payout_ratio" in df.columns:
    df_feat["payout_ratio"] = df["payout_ratio"]

# dps_yoy_pct가 있으면 추가 (전년 대비 DPS 변화율)
if "dps_yoy_pct" in df.columns:
    df_feat["dps_yoy_pct"] = df["dps_yoy_pct"]

FEATURES = df_feat.columns.tolist()
X = df_feat.copy()
y = df["dividend_cut"].astype(int)

print(f"\n[2] 피처 목록 ({len(FEATURES)}개):")
for f in FEATURES:
    missing = X[f].isnull().sum()
    pct = missing / len(X) * 100
    print(f"    {f:25s}: 결측 {pct:4.0f}%")

# ─────────────────────────────────────────────────────────────
# 3. 하이퍼파라미터 최적화 (Optuna)
# ─────────────────────────────────────────────────────────────
print("\n[3] 하이퍼파라미터 최적화...")

pos_weight = (y == 0).sum() / max((y == 1).sum(), 1)

def make_pipeline(params: dict) -> Pipeline:
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler",  StandardScaler()),
        ("model",   xgb.XGBClassifier(
            **params,
            scale_pos_weight=pos_weight,
            random_state=42,
            eval_metric="logloss",
            verbosity=0,
        )),
    ])

# 데이터가 충분하면 Optuna로 최적화, 적으면 기본값 사용
best_params = {
    "n_estimators":     200,
    "max_depth":        4,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "gamma":            0.1,
}

if n_rows >= 200:
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def objective(trial):
            params = {
                "n_estimators":     trial.suggest_int("n_estimators", 100, 500),
                "max_depth":        trial.suggest_int("max_depth", 2, 6),
                "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
                "gamma":            trial.suggest_float("gamma", 0, 1.0),
            }
            pipe = make_pipeline(params)
            # 시계열 특성 고려: TimeSeriesSplit
            tscv = TimeSeriesSplit(n_splits=5)
            scores = cross_validate(pipe, X, y, cv=tscv, scoring="roc_auc")
            return scores["test_score"].mean()

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=50, show_progress_bar=False)
        best_params = study.best_params
        print(f"    ✅ Optuna 최적화 완료: ROC-AUC {study.best_value:.3f}")
        print(f"    최적 파라미터: {best_params}")
    except ImportError:
        print("    ⚠️ Optuna 없음 → pip install optuna 후 재실행하면 자동 최적화됩니다")
        print("    → 기본 파라미터로 진행")
else:
    print(f"    ℹ️ 데이터 {n_rows}행 (200행 미만) → 기본 파라미터 사용")
    best_params["max_depth"] = 3  # 소량 데이터는 얕은 트리

# ─────────────────────────────────────────────────────────────
# 4. 교차검증 (TimeSeriesSplit — 시계열 누수 방지)
# ─────────────────────────────────────────────────────────────
print("\n[4] 교차검증 중...")

pipeline = make_pipeline(best_params)

# 데이터 크기에 따라 CV 방법 결정
if n_rows >= 100:
    # 시계열 구조 고려: 미래 데이터로 과거 예측 방지
    cv = TimeSeriesSplit(n_splits=5)
    cv_name = "TimeSeriesSplit 5-Fold"
else:
    from sklearn.model_selection import StratifiedKFold
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_name = "StratifiedKFold 5-Fold"

cv_results = cross_validate(
    pipeline, X, y, cv=cv,
    scoring=["accuracy", "f1", "roc_auc"],
    return_train_score=True,
)

print(f"\n  [{cv_name} 결과]")
print(f"  Accuracy : {cv_results['test_accuracy'].mean():.3f} ± {cv_results['test_accuracy'].std():.3f}")
print(f"  F1 Score : {cv_results['test_f1'].mean():.3f} ± {cv_results['test_f1'].std():.3f}")
print(f"  ROC-AUC  : {cv_results['test_roc_auc'].mean():.3f} ± {cv_results['test_roc_auc'].std():.3f}")
train_acc = cv_results['train_accuracy'].mean()
test_acc  = cv_results['test_accuracy'].mean()
overfit   = train_acc - test_acc
print(f"\n  Train Accuracy: {train_acc:.3f} | Test: {test_acc:.3f}")
if overfit > 0.15:
    print(f"  ⚠️ 과적합 의심 (차이: {overfit:.3f}) — 데이터 추가 수집 권장")
else:
    print(f"  ✅ 과적합 없음 (차이: {overfit:.3f})")

# ─────────────────────────────────────────────────────────────
# 5. Hold-out 테스트 (최종 성능 검증)
# ─────────────────────────────────────────────────────────────
if n_rows >= 100:
    print("\n[5] Hold-out 테스트 (80:20)...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]
    print(f"  Test Accuracy : {accuracy_score(y_test, y_pred):.3f}")
    print(f"  Test F1       : {f1_score(y_test, y_pred, zero_division=0):.3f}")
    print(f"  Test ROC-AUC  : {roc_auc_score(y_test, y_prob):.3f}")

# ─────────────────────────────────────────────────────────────
# 6. 전체 데이터로 최종 학습 & 저장
# ─────────────────────────────────────────────────────────────
print("\n[6] 전체 데이터로 최종 모델 학습...")
pipeline.fit(X, y)
joblib.dump({
    "pipeline": pipeline,
    "features":  FEATURES,
    "n_rows":    n_rows,
    "n_stocks":  n_stocks,
    "params":    best_params,
}, MODEL_PATH)
print(f"  ✅ 저장: {MODEL_PATH}")

# ─────────────────────────────────────────────────────────────
# 7. Feature Importance & SHAP
# ─────────────────────────────────────────────────────────────
print("\n[7] Feature Importance...")

xgb_model    = pipeline.named_steps["model"]
importances  = xgb_model.feature_importances_
sorted_idx   = np.argsort(importances)[::-1]
sorted_names = [FEATURES[i] for i in sorted_idx]
sorted_vals  = importances[sorted_idx]

for name, val in zip(sorted_names, sorted_vals):
    bar = "█" * int(val * 40)
    print(f"  {name:25s}: {val:.3f}  {bar}")

# Feature Importance JSON 저장 (API /explain 에서 사용)
FEATURE_LABEL_KO = {
    "fcf":               "잉여현금흐름 (FCF)",
    "dividends_paid":    "배당금 지급액",
    "dividend_coverage": "배당 커버리지",
    "operating_cf":      "영업현금흐름",
    "capex":             "설비투자 (CapEx)",
    "div_to_ocf":        "배당/영업현금흐름 비율",
    "fcf_negative":      "FCF 마이너스 여부",
    "ocf_to_capex":      "영업현금흐름/설비투자 비율",
    "payout_ratio":      "배당성향",
    "dps_yoy_pct":       "배당금 전년 대비 증감률",
}
importance_data = {
    "features": [
        {
            "name":       name,
            "label_ko":   FEATURE_LABEL_KO.get(name, name),
            "importance": round(float(val), 4),
            "rank":       rank + 1,
        }
        for rank, (name, val) in enumerate(zip(sorted_names, sorted_vals))
    ]
}
importance_path = os.path.join(RESULT_DIR, "feature_importance.json")
import json as _json
with open(importance_path, "w", encoding="utf-8") as f:
    _json.dump(importance_data, f, ensure_ascii=False, indent=2)
print(f"  ✅ Feature Importance 저장: {importance_path}")

# SHAP (있으면)
shap_ok = False
try:
    import shap
    imputer = pipeline.named_steps["imputer"]
    scaler  = pipeline.named_steps["scaler"]
    X_proc  = scaler.transform(imputer.transform(X))
    explainer   = shap.TreeExplainer(xgb_model)
    shap_values = explainer.shap_values(X_proc)
    shap_ok = True
    print("  ✅ SHAP 계산 완료")
except ImportError:
    print("  ℹ️ SHAP 없음 → pip install shap 후 SHAP 시각화 가능")

# ─────────────────────────────────────────────────────────────
# 8. 시각화 저장
# ─────────────────────────────────────────────────────────────
y_pred_all = pipeline.predict(X)
y_prob_all = pipeline.predict_proba(X)[:, 1]

n_plots = 3 if shap_ok else 2
fig, axes = plt.subplots(1, n_plots, figsize=(6 * n_plots, 5))

# Feature Importance
axes[0].barh(sorted_names[::-1], sorted_vals[::-1], color="#4C72B0")
axes[0].set_title("Feature Importance (XGBoost)", fontsize=12)
axes[0].set_xlabel("Importance Score")

# Confusion Matrix
cm = confusion_matrix(y, y_pred_all)
disp = ConfusionMatrixDisplay(cm, display_labels=["배당 유지", "배당 삭감"])
disp.plot(ax=axes[1], colorbar=False, cmap="Blues")
axes[1].set_title(f"Confusion Matrix ({n_rows}행)", fontsize=12)

# SHAP
if shap_ok:
    shap.summary_plot(shap_values, X, feature_names=FEATURES,
                      show=False, plot_type="bar")
    plt.sca(axes[2])
    axes[2].set_title("SHAP Feature Importance", fontsize=12)

plt.tight_layout()
chart_path = os.path.join(RESULT_DIR, "model_evaluation.png")
plt.savefig(chart_path, dpi=150, bbox_inches="tight")
print(f"\n  ✅ 차트 저장: {chart_path}")

# 예측 결과 CSV
df_result = df[["stock_code", "name", "year", "dividend_cut"]].copy()
df_result["predicted"] = y_pred_all
df_result["cut_prob"]  = (y_prob_all * 100).round(1)
df_result["correct"]   = (y_pred_all == y).astype(int)
df_result.to_csv(os.path.join(RESULT_DIR, "prediction_result.csv"), index=False, encoding="utf-8-sig")

print("\n" + "=" * 65)
print("  학습 완료!")
print(f"  데이터: {n_rows}행 / {n_stocks}종목")
print(f"  모델 : {MODEL_PATH}")
print("=" * 65)

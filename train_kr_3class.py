"""
train_kr_3class.py — KR XGBoost 3-class 배당 상태 예측 모델

■ 기존 binary 모델 (train_model.py) 과의 차이
  기존: dividend_cut (0/1) — "이미 삭감됐냐"  → 사후 감지
  이것: label3 (0/1/2)     — "내년에 어떻게 될 것 같냐" → 사전 예측

■ label3 정의
  0 = INTACT    : 올해 유지, 내년도 유지
  1 = WEAKENING : 올해 유지, 내년 삭감 예정 (전조 상태)
  2 = BROKEN    : 올해 이미 삭감 발생

■ 왜 3-class가 더 좋은가
  - 기존: 정상 vs 사망 (중간 없음)
  - 이것: 안전 → 전조 → 붕괴 (실제 위험 진행 과정 학습 가능)
  - Thesis Agent가 "현재 유지 중이나 내년 위험" 문장을 더 자연스럽게 생성

■ leakage 방지
  - label3는 t+1 정보 기반이므로 피처에 미래 정보 절대 불가
  - dps_yoy_pct, payout 등은 모두 t년도 값 → 안전
  - 마지막 연도 행 (미래 불명) → label3=NaN → 자동 제외

■ 저장
  models/kr_3class_model.pkl — bundle {pipeline, feature_names, classes}
"""

import os
import json
import warnings
import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit, cross_validate
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
import xgboost as xgb
import joblib

warnings.filterwarnings("ignore")

# ── 경로 ─────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_PATH  = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
MODEL_DIR  = os.path.join(BASE_DIR, "models");  os.makedirs(MODEL_DIR, exist_ok=True)
RESULT_DIR = os.path.join(BASE_DIR, "results"); os.makedirs(RESULT_DIR, exist_ok=True)
MODEL_PATH = os.path.join(MODEL_DIR, "kr_3class_model.pkl")

# ── 피처 (binary 모델과 동일하게 유지 — 호환성) ─────────────
FEATURES_BASE = [
    "fcf", "dividends_paid", "dividend_coverage",
    "operating_cf", "capex",
]

CLASS_NAMES = ["INTACT", "WEAKENING", "BROKEN"]  # 0, 1, 2

print("=" * 65)
print("  KR XGBoost 3-class 배당 상태 예측 모델 학습")
print("=" * 65)

# ─────────────────────────────────────────────────────────────
# 1. 데이터 로드
# ─────────────────────────────────────────────────────────────
df = pd.read_csv(DATA_PATH)
df = df[df["label3"].notna()].copy()  # 마지막 연도(미래 불명) 제외
df["label3"] = df["label3"].astype(int)

n_stocks = df["stock_code"].nunique()
n_rows   = len(df)
print(f"\n[1] 데이터: {n_rows}행 / {n_stocks}종목")
dist = df["label3"].value_counts().rename({0:"INTACT",1:"WEAKENING",2:"BROKEN"})
for cls, cnt in dist.items():
    print(f"    {cls}: {cnt}건 ({cnt/n_rows*100:.1f}%)")

# ─────────────────────────────────────────────────────────────
# 2. 피처 엔지니어링
# ─────────────────────────────────────────────────────────────
df_feat = df[FEATURES_BASE].copy()
df_feat["div_to_ocf"]   = df["dividends_paid"] / (df["operating_cf"].abs() + 1)
df_feat["fcf_negative"] = (df["fcf"] < 0).astype(int)
df_feat["ocf_to_capex"] = df["operating_cf"] / (df["capex"].abs() + 1)
if "payout_ratio" in df.columns:
    df_feat["payout_ratio"] = df["payout_ratio"]
if "dps_yoy_pct" in df.columns:
    df_feat["dps_yoy_pct"] = df["dps_yoy_pct"]

FEATURES = df_feat.columns.tolist()
X = df_feat.copy()
y = df["label3"]

print(f"\n[2] 피처 {len(FEATURES)}개:")
for f in FEATURES:
    pct = X[f].isnull().mean() * 100
    flag = "⚠️" if pct > 30 else "✅"
    print(f"    {flag} {f:<25}: 결측 {pct:.0f}%")

# ─────────────────────────────────────────────────────────────
# 3. 모델 구성 (multi:softprob → 클래스별 확률 반환)
# ─────────────────────────────────────────────────────────────
# WEAKENING(1)이 48건으로 적음 → sample_weight로 보완
sample_weight = np.ones(len(y))
sample_weight[y == 1] = 3.0   # WEAKENING 3배 가중치
sample_weight[y == 2] = 2.0   # BROKEN 2배 가중치

imputer = SimpleImputer(strategy="median")
scaler  = StandardScaler()

params = {
    "n_estimators":     300,
    "max_depth":        4,
    "learning_rate":    0.05,
    "subsample":        0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 3,
    "objective":        "multi:softprob",
    "num_class":        3,
    "eval_metric":      "mlogloss",
    "random_state":     42,
    "verbosity":        0,
}

# ─────────────────────────────────────────────────────────────
# 4. Optuna 최적화
# ─────────────────────────────────────────────────────────────
print("\n[3] Optuna 최적화 (30 trials)...")

X_imp = imputer.fit_transform(X)
X_sc  = scaler.fit_transform(X_imp)
tscv  = TimeSeriesSplit(n_splits=5)

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from sklearn.metrics import log_loss

    def objective(trial):
        p = {
            "n_estimators":     trial.suggest_int("n_estimators", 100, 500),
            "max_depth":        trial.suggest_int("max_depth", 2, 5),
            "learning_rate":    trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            "subsample":        trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "objective": "multi:softprob", "num_class": 3,
            "eval_metric": "mlogloss", "random_state": 42, "verbosity": 0,
        }
        fold_losses = []
        for tr, val in tscv.split(X_sc):
            m = xgb.XGBClassifier(**p)
            m.fit(X_sc[tr], y.iloc[tr], sample_weight=sample_weight[tr])
            prob = m.predict_proba(X_sc[val])
            fold_losses.append(log_loss(y.iloc[val], prob))
        return np.mean(fold_losses)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=30, show_progress_bar=False)
    params.update(study.best_params)
    print(f"    최적 log-loss: {study.best_value:.4f}")
except ImportError:
    print("    Optuna 없음 → 기본 파라미터 사용")

# ─────────────────────────────────────────────────────────────
# 5. 교차검증
# ─────────────────────────────────────────────────────────────
print("\n[4] TimeSeriesSplit 5-fold 교차검증...")

fold_reports = []
for fold, (tr, val) in enumerate(tscv.split(X_sc), 1):
    m = xgb.XGBClassifier(**params)
    m.fit(X_sc[tr], y.iloc[tr], sample_weight=sample_weight[tr])
    pred = m.predict(X_sc[val])
    report = classification_report(
        y.iloc[val], pred,
        target_names=CLASS_NAMES,
        output_dict=True,
        zero_division=0
    )
    acc = report["accuracy"]
    w_f1 = report["weighted avg"]["f1-score"]
    weak_f1 = report.get("WEAKENING", {}).get("f1-score", 0)
    print(f"    Fold {fold}: Acc={acc:.3f}  F1(avg)={w_f1:.3f}  F1(WEAKENING)={weak_f1:.3f}")
    fold_reports.append(report)

avg_weak_f1 = np.mean([r.get("WEAKENING", {}).get("f1-score", 0) for r in fold_reports])
print(f"\n    WEAKENING F1 평균: {avg_weak_f1:.3f}  (핵심 지표)")

# ─────────────────────────────────────────────────────────────
# 6. 전체 데이터 최종 학습 & 저장
# ─────────────────────────────────────────────────────────────
print("\n[5] 전체 데이터 최종 학습...")

final_model = xgb.XGBClassifier(**params)
final_model.fit(X_sc, y, sample_weight=sample_weight)

# Pipeline으로 묶기
pipeline = Pipeline([
    ("imputer", imputer),
    ("scaler",  scaler),
    ("model",   final_model),
])

# bundle 저장 (feature_names + classes 포함 → 추론 시 안전한 컬럼 정렬)
bundle = {
    "pipeline":      pipeline,
    "feature_names": FEATURES,
    "classes":       CLASS_NAMES,   # [INTACT, WEAKENING, BROKEN]
    "threshold":     {              # predict_proba 해석 기준
        "WEAKENING": 0.25,          # P(WEAKENING) > 0.25 → WEAKENING 표시
        "BROKEN":    0.40,          # P(BROKEN) > 0.40 → BROKEN 표시
    },
}
joblib.dump(bundle, MODEL_PATH)
print(f"    ✅ 저장: {MODEL_PATH}")
print(f"    피처 순서: {FEATURES}")

# ─────────────────────────────────────────────────────────────
# 7. 피처 중요도
# ─────────────────────────────────────────────────────────────
print("\n[6] 피처 중요도:")
fi = dict(zip(FEATURES, final_model.feature_importances_))
fi_sorted = sorted(fi.items(), key=lambda x: x[1], reverse=True)
for feat, imp in fi_sorted:
    bar = "█" * int(imp * 40)
    print(f"    {feat:<25} {imp:.4f}  {bar}")

fi_path = os.path.join(RESULT_DIR, "kr_3class_feature_importance.json")
with open(fi_path, "w") as f:
    json.dump({k: float(v) for k, v in fi.items()}, f, indent=2)

# ─────────────────────────────────────────────────────────────
# 8. 요약
# ─────────────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  학습 완료")
print("=" * 65)
print(f"  모델: {MODEL_PATH}")
print(f"  라벨: INTACT(0)={int((y==0).sum())} / WEAKENING(1)={int((y==1).sum())} / BROKEN(2)={int((y==2).sum())}")
print(f"  WEAKENING F1 (CV 평균): {avg_weak_f1:.3f}")
print()
print("  다음 단계:")
print("  → run_thesis_batch.py에서 kr_3class_model.pkl 우선 사용")
print("  → Thesis Agent: P(WEAKENING)·P(BROKEN) 두 확률 모두 활용")
print("=" * 65)

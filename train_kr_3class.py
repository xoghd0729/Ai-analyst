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
from sklearn.model_selection import TimeSeriesSplit, GroupKFold, cross_validate
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
# 신규 피처 (데이터셋에 있을 때만 — 하위 호환)
for _col in ("debt_ratio", "interest_coverage", "revenue_yoy_pct"):
    if _col in df.columns:
        df_feat[_col] = pd.to_numeric(df[_col], errors="coerce")

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
# WEAKENING(1)·BROKEN(2)이 소수 클래스 → sample_weight로 보완
# 가중치는 Optuna가 튜닝 (아래) → 위험 클래스 F1 직접 최적화
def make_weights(y_arr, w_weak: float = 3.0, w_broken: float = 2.0):
    sw = np.ones(len(y_arr))
    sw[np.asarray(y_arr) == 1] = w_weak
    sw[np.asarray(y_arr) == 2] = w_broken
    return sw

sample_weight = make_weights(y)

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
print("\n[3] Optuna 최적화 (50 trials, 3클래스 균형 macro-F1)...")

X_imp = imputer.fit_transform(X)
X_sc  = scaler.fit_transform(X_imp)

# 종목 단위 GroupKFold — 같은 종목이 train/test에 동시에 들어가는 누수 차단.
# (기존 TimeSeriesSplit은 종목코드 정렬 데이터에선 시간 분할이 아니라 종목군 분할이 됨)
groups = df["stock_code"].astype(str).values
gkf = GroupKFold(n_splits=5)
_splits = list(gkf.split(X_sc, y, groups=groups))

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    from sklearn.metrics import f1_score

    # 목적함수: 위험 클래스(WEAKENING+BROKEN) macro-F1 최대화.
    # log-loss 대신 실제 핵심 지표를 직접 최적화 + 클래스 가중치도 튜닝.
    WEIGHT_KEYS = ("w_weak", "w_broken")

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
        # 가중치 범위를 좁혀 폭주 방지 (이전 1~8 → 정확도 붕괴 원인)
        w_weak   = trial.suggest_float("w_weak", 1.0, 4.0)
        w_broken = trial.suggest_float("w_broken", 1.0, 3.0)
        fold_f1 = []
        for tr, val in _splits:
            sw = make_weights(y.iloc[tr], w_weak, w_broken)
            m = xgb.XGBClassifier(**p)
            m.fit(X_sc[tr], y.iloc[tr], sample_weight=sw)
            pred = m.predict(X_sc[val])
            # 3클래스 전체 macro-F1 → INTACT 정확도와 소수클래스 재현율 균형
            fold_f1.append(f1_score(y.iloc[val], pred, labels=[0, 1, 2],
                                    average="macro", zero_division=0))
        return float(np.mean(fold_f1))

    study = optuna.create_study(direction="maximize")

    def _cb(st, tr):
        if (tr.number + 1) % 5 == 0:
            print(f"      trial {tr.number+1}/50  best F1={st.best_value:.4f}", flush=True)

    study.optimize(objective, n_trials=50, show_progress_bar=True, callbacks=[_cb])
    best = dict(study.best_params)
    # 가중치 파라미터는 xgb params가 아니므로 분리해 sample_weight에 반영
    sample_weight = make_weights(y, best.pop("w_weak", 3.0), best.pop("w_broken", 2.0))
    params.update(best)
    print(f"    최적 3클래스 macro-F1: {study.best_value:.4f}")
    print(f"    최적 가중치: WEAKENING={study.best_params.get('w_weak'):.2f} "
          f"BROKEN={study.best_params.get('w_broken'):.2f}")
except ImportError:
    print("    Optuna 없음 → 기본 파라미터 사용")

# ─────────────────────────────────────────────────────────────
# 5. 교차검증
# ─────────────────────────────────────────────────────────────
print("\n[4] GroupKFold(종목 단위) 5-fold 교차검증...")

fold_reports = []
oof_risk = np.full(len(y), np.nan)   # out-of-fold P(위험)=P(WEAKENING)+P(BROKEN)
for fold, (tr, val) in enumerate(_splits, 1):
    m = xgb.XGBClassifier(**params)
    m.fit(X_sc[tr], y.iloc[tr], sample_weight=sample_weight[tr])
    pred = m.predict(X_sc[val])
    proba = m.predict_proba(X_sc[val])
    oof_risk[val] = proba[:, 1] + proba[:, 2]   # WEAKENING + BROKEN 확률 합
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
avg_acc_cv  = float(np.mean([r["accuracy"] for r in fold_reports]))
print(f"\n    WEAKENING F1 평균: {avg_weak_f1:.3f}  (argmax 기준)")

# ── 위험 확률 랭킹 평가 (실사용 지표) ─────────────────────────
# "위험 상위 K%에 실제 삭감 위험(label3∈{1,2})이 얼마나 잡히는가"
from sklearn.metrics import average_precision_score, roc_auc_score
mask = ~np.isnan(oof_risk)
y_risk = (y.values[mask] >= 1).astype(int)     # 1=WEAKENING or BROKEN(위험), 0=INTACT
scores = oof_risk[mask]
pr_auc = average_precision_score(y_risk, scores)
roc    = roc_auc_score(y_risk, scores)
order  = np.argsort(-scores)
base_rate = y_risk.mean()
print(f"\n    [위험 확률 랭킹 — 경고 시스템 실사용 지표]")
print(f"    PR-AUC {pr_auc:.3f} (기준선 {base_rate:.3f}) | ROC-AUC {roc:.3f}")
for k in (0.10, 0.20, 0.30):
    topn = max(1, int(len(scores) * k))
    caught = y_risk[order[:topn]].sum()
    total_pos = y_risk.sum()
    prec = caught / topn
    rec  = caught / total_pos if total_pos else 0
    print(f"    상위 {int(k*100)}%: 정밀도 {prec:.2f} · 재현율 {rec:.2f} "
          f"({caught}/{topn}건이 실제 위험)")

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

# 운영 임계값: OOF 위험확률 분포에서 상위 10%/20% 컷 지점 (실사용 경고 기준)
_valid_risk = oof_risk[~np.isnan(oof_risk)]
risk_top10_cut = float(np.quantile(_valid_risk, 0.90))
risk_top20_cut = float(np.quantile(_valid_risk, 0.80))

# bundle 저장 (feature_names + classes 포함 → 추론 시 안전한 컬럼 정렬)
bundle = {
    "pipeline":      pipeline,
    "feature_names": FEATURES,
    "classes":       CLASS_NAMES,   # [INTACT, WEAKENING, BROKEN]
    "threshold":     {              # predict_proba 해석 기준
        "WEAKENING": 0.25,          # P(WEAKENING) > 0.25 → WEAKENING 표시
        "BROKEN":    0.40,          # P(BROKEN) > 0.40 → BROKEN 표시
    },
    # 위험 확률 = P(WEAKENING)+P(BROKEN). 아래 컷 이상이면 경고.
    "risk_alert": {
        "score": "p_weakening + p_broken",
        "top10_cut":   round(risk_top10_cut, 4),   # 정밀도≈1.00 구간
        "top20_cut":   round(risk_top20_cut, 4),   # 정밀도≈0.96 구간 (권장 알림 기준)
        "pr_auc":      round(float(pr_auc), 4),
        "roc_auc":     round(float(roc), 4),
        "validated":   "GroupKFold(stock) OOF",
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
# 7-b. 모델 성능 추적 (history 누적 + 회귀 감지)
# ─────────────────────────────────────────────────────────────
from datetime import datetime, timezone
HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "model_history.json")
avg_acc = float(np.mean([r["accuracy"] for r in fold_reports]))
avg_w_f1 = float(np.mean([r["weighted avg"]["f1-score"] for r in fold_reports]))
record = {
    "timestamp":      datetime.now(timezone.utc).isoformat(),
    "n_rows":         int(len(y)),
    "n_stocks":       int(df["stock_code"].nunique()),
    "class_dist":     {"INTACT": int((y==0).sum()),
                       "WEAKENING": int((y==1).sum()),
                       "BROKEN": int((y==2).sum())},
    "weakening_f1":   round(avg_weak_f1, 4),
    "weighted_f1":    round(avg_w_f1, 4),
    "accuracy":       round(avg_acc, 4),
    "risk_pr_auc":    round(float(pr_auc), 4),   # 실사용 핵심 지표
    "risk_roc_auc":   round(float(roc), 4),
    "n_features":     len(FEATURES),
    "top_feature":    fi_sorted[0][0],
    "cv_method":      "GroupKFold(stock)",   # 검증 방식 태깅 — 같은 방식끼리만 비교
}
history = []
if os.path.exists(HISTORY_PATH):
    try:
        history = json.load(open(HISTORY_PATH, encoding="utf-8"))
    except Exception:
        history = []

print("\n[7] 성능 추적 (회귀 감지):")
# 동일 검증 방식 기록만 비교 (누수 있던 TimeSeriesSplit 기록과 혼동 방지)
same = [r for r in history if r.get("cv_method") == record["cv_method"]]
if same:
    prev = same[-1]
    best = max(same, key=lambda r: r.get("weakening_f1", 0))
    d = record["weakening_f1"] - prev.get("weakening_f1", 0)
    arrow = "▲" if d > 0 else ("▼" if d < 0 else "=")
    print(f"    직전 WEAKENING F1 {prev.get('weakening_f1'):.3f} → 이번 {record['weakening_f1']:.3f}  {arrow}{abs(d):.3f}")
    print(f"    역대 최고 {best.get('weakening_f1'):.3f} (행 {best.get('n_rows')})")
    if d < -0.03:
        print(f"    ⚠️ 회귀 경고: WEAKENING F1이 {abs(d):.3f} 하락했습니다. 데이터/피처 변경을 점검하세요.")
else:
    print(f"    (검증방식 '{record['cv_method']}' 첫 기록 — 정직한 기준선 저장)")

history.append(record)
with open(HISTORY_PATH, "w", encoding="utf-8") as f:
    json.dump(history, f, ensure_ascii=False, indent=2)
print(f"    기록 누적: {len(history)}회  →  {HISTORY_PATH}")

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

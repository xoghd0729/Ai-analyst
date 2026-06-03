"""
scripts/forward_backtest.py — Out-of-Time(워크포워드) 검증
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가
  GroupKFold는 '처음 보는 종목'에는 강하지만 '처음 보는 미래'는
  증명하지 못한다. 금융에서 가장 중요한 질문은:
      "과거 데이터만 보고 그 다음 해의 배당 위험을 실제로 미리 잡았는가?"
  이 스크립트는 연도별 워크포워드로 그걸 증명한다.

방식 (엄격한 시간 분할 — 미래 누수 0)
  테스트 연도 Y 마다:
    train = year <  Y 인 행 (label3 확정분)
    test  = year == Y 인 행
    → Y 시점 재무로 학습된 모델이 Y의 위험을 얼마나 맞췄나 평가
  Y = 2019 … (가능한 최근 연도) 반복.

평가 지표 (경고 시스템 실사용 관점)
  - PR-AUC / ROC-AUC
  - 위험 상위 20%의 정밀도·재현율
  - "그 해 실제 위험종목 중 상위 20% 경고로 몇 % 미리 잡았나"

실행
  python scripts/forward_backtest.py
  python scripts/forward_backtest.py --start 2018 --top 0.2

결과는 data/forward_backtest_report.json 에도 저장.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import average_precision_score, roc_auc_score
import xgboost as xgb

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
REPORT = os.path.join(BASE_DIR, "data", "forward_backtest_report.json")

BASE_FEATURES = ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex"]
EXTRA = ["payout_ratio", "dps_yoy_pct", "debt_ratio", "interest_coverage", "revenue_yoy_pct"]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    X = df[BASE_FEATURES].copy()
    X["div_to_ocf"]   = df["dividends_paid"] / (df["operating_cf"].abs() + 1)
    X["fcf_negative"] = (df["fcf"] < 0).astype(int)
    X["ocf_to_capex"] = df["operating_cf"] / (df["capex"].abs() + 1)
    for c in EXTRA:
        if c in df.columns:
            X[c] = pd.to_numeric(df[c], errors="coerce")
    return X


def make_weights(y, w_weak=3.0, w_broken=1.3):
    sw = np.ones(len(y))
    sw[np.asarray(y) == 1] = w_weak
    sw[np.asarray(y) == 2] = w_broken
    return sw


def model():
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc",  StandardScaler()),
        ("clf", xgb.XGBClassifier(
            n_estimators=300, max_depth=4, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=3,
            objective="multi:softprob", num_class=3,
            eval_metric="mlogloss", random_state=42, verbosity=0)),
    ])


def run(start_year: int, top_frac: float) -> None:
    df = pd.read_csv(DATA)
    df = df[df["label3"].notna()].copy()
    df["label3"] = df["label3"].astype(int)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)

    years = sorted(y for y in df["year"].unique() if y >= start_year)
    print("=" * 64)
    print("  Forward Backtest (Out-of-Time 워크포워드 검증)")
    print("=" * 64)
    print(f"  테스트 연도: {years}")
    print(f"  {'연도':<6}{'학습행':>7}{'평가행':>7}{'위험실제':>8}"
          f"{'PR-AUC':>8}{'ROC':>7}{'상위%P':>8}{'상위%R':>8}")
    print("-" * 64)

    rows_out = []
    all_scores, all_truth = [], []
    for Y in years:
        tr = df[df["year"] < Y]
        te = df[df["year"] == Y]
        if len(tr) < 100 or len(te) < 10:
            continue
        if te["label3"].nunique() < 2:
            continue   # 평가 연도에 위험/정상 둘 다 있어야 지표 계산 가능

        Xtr, ytr = build_features(tr), tr["label3"]
        Xte, yte = build_features(te), te["label3"]
        y_risk = (yte.values >= 1).astype(int)

        m = model()
        m.fit(Xtr, ytr, clf__sample_weight=make_weights(ytr))
        proba = m.predict_proba(Xte)
        risk = proba[:, 1] + proba[:, 2]

        pr = average_precision_score(y_risk, risk) if y_risk.sum() else float("nan")
        roc = roc_auc_score(y_risk, risk) if 0 < y_risk.sum() < len(y_risk) else float("nan")
        order = np.argsort(-risk)
        topn = max(1, int(len(risk) * top_frac))
        caught = int(y_risk[order[:topn]].sum())
        prec = caught / topn
        rec = caught / y_risk.sum() if y_risk.sum() else float("nan")

        print(f"  {Y:<6}{len(tr):>7}{len(te):>7}{int(y_risk.sum()):>8}"
              f"{pr:>8.3f}{roc:>7.3f}{prec:>8.2f}{rec:>8.2f}")
        rows_out.append({"year": int(Y), "n_train": int(len(tr)), "n_test": int(len(te)),
                         "n_risk": int(y_risk.sum()), "pr_auc": round(float(pr), 4),
                         "roc_auc": round(float(roc), 4),
                         "top_precision": round(prec, 4), "top_recall": round(rec, 4)})
        all_scores.append(risk); all_truth.append(y_risk)

    print("-" * 64)
    if all_truth:
        S = np.concatenate(all_scores); T = np.concatenate(all_truth)
        pooled_pr = average_precision_score(T, S)
        pooled_roc = roc_auc_score(T, S)
        mean_prec = float(np.nanmean([r["top_precision"] for r in rows_out]))
        mean_rec  = float(np.nanmean([r["top_recall"] for r in rows_out]))
        print(f"  전체(pooled) PR-AUC {pooled_pr:.3f} | ROC-AUC {pooled_roc:.3f}")
        print(f"  연도평균 상위{int(top_frac*100)}% 정밀도 {mean_prec:.2f} · 재현율 {mean_rec:.2f}")
        summary = {"years": rows_out, "pooled_pr_auc": round(float(pooled_pr), 4),
                   "pooled_roc_auc": round(float(pooled_roc), 4),
                   "mean_top_precision": round(mean_prec, 4),
                   "mean_top_recall": round(mean_rec, 4), "top_frac": top_frac}
        json.dump(summary, open(REPORT, "w"), ensure_ascii=False, indent=2)
        print(f"\n  저장: {REPORT}")
        print("\n  해석: 각 연도는 '그 이전 데이터만'으로 학습 → 그 해를 처음 보고 예측.")
        print("        PR-AUC가 연도별로 무너지지 않으면 = 미래에도 통하는 모델.")
    print("=" * 64)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Out-of-Time 워크포워드 검증")
    ap.add_argument("--start", type=int, default=2019, help="평가 시작 연도, 기본 2019")
    ap.add_argument("--top", type=float, default=0.2, help="상위 위험 비율, 기본 0.2")
    args = ap.parse_args()
    run(args.start, args.top)

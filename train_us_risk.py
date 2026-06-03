"""
train_us_risk.py — US 전용 배당위험 모델 (KR과 완전 분리)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 KR과 분리하는가
  - US 배당주(귀족/왕)는 payout 60~70%가 정상. KR(30~40%) 임계값을 쓰면 안 됨.
  - US 데이터엔 US 고유 신호가 있음: shareholder_yield, net_debt_ebitda,
    consecutive_years(연속 증배). 이걸 써야 한다.
  - US는 삭감이 드물어(≈4%) 3-class가 불가능 → '내년 삭감 여부' 이진 위험 모델.

타깃
  forward_cut = 다음 해(year+1) dividend_cut == 1  (선제 경고)
  → 같은 티커의 dividend_cut 을 한 해 당겨 라벨링. 마지막 해는 미래 불명 → 제외.

검증 (KR과 동일한 엄격함)
  - 티커 단위 GroupKFold (같은 기업 누수 차단)
  - Forward Backtest (연도별 워크포워드, 미래 누수 0)
  - 위험확률 랭킹 지표(PR-AUC / 상위 K% 정밀도·재현율) 출력

주의(정직)
  현재 US 데이터는 삭감 positive 가 매우 적다. 지표가 불안정하면
  그것이 'US 데이터(삭감 사례) 보강이 필요하다'는 증거다.

실행
  python train_us_risk.py
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import GroupKFold
from sklearn.metrics import average_precision_score, roc_auc_score
import xgboost as xgb
import joblib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE_DIR, "data", "us_dividend_dataset.csv")
MODEL_PATH = os.path.join(BASE_DIR, "models", "us_risk_model.pkl")
HISTORY = os.path.join(BASE_DIR, "data", "us_model_history.json")

# US 고유 피처 (KR과 다름 — shareholder_yield, net_debt_ebitda, consecutive_years)
FEATURES = [
    "payout_ratio", "dps_yoy_pct", "dividend_coverage", "div_to_ocf",
    "fcf_negative", "fcf", "operating_cf", "buyback", "shareholder_yield",
    "net_debt_ebitda", "consecutive_years",
]


def load() -> pd.DataFrame:
    df = pd.read_csv(DATA)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"]).copy()
    df["year"] = df["year"].astype(int)
    df = df.sort_values(["ticker", "year"])
    # forward 타깃: 다음 해 삭감 여부
    df["forward_cut"] = df.groupby("ticker")["dividend_cut"].shift(-1)
    df = df.dropna(subset=["forward_cut"]).copy()
    df["forward_cut"] = df["forward_cut"].astype(int)
    return df


def feats(df: pd.DataFrame) -> pd.DataFrame:
    X = pd.DataFrame(index=df.index)
    for c in FEATURES:
        X[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    return X


def model(pos_weight: float):
    return Pipeline([
        ("imp", SimpleImputer(strategy="median")),
        ("sc", StandardScaler()),
        ("clf", xgb.XGBClassifier(
            n_estimators=200, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, min_child_weight=2,
            scale_pos_weight=pos_weight, eval_metric="logloss",
            random_state=42, verbosity=0)),
    ])


def main():
    df = load()
    X, y = feats(df), df["forward_cut"]
    n_pos = int(y.sum())
    print("=" * 60)
    print("  US 전용 배당위험 모델 (이진: 내년 삭감 예측)")
    print("=" * 60)
    print(f"  행 {len(df)} | 티커 {df['ticker'].nunique()} | 내년삭감 positive {n_pos} ({y.mean()*100:.1f}%)")
    if n_pos < 10:
        print(f"  ⚠️ positive {n_pos}건 — ML 신뢰 어려움. 삭감 종목 데이터 보강 필요.")
    pos_weight = max(1.0, (len(y) - n_pos) / max(1, n_pos))

    # 티커 단위 GroupKFold
    groups = df["ticker"].values
    n_splits = min(5, df["ticker"].nunique(), max(2, n_pos))
    gkf = GroupKFold(n_splits=n_splits)
    oof = np.full(len(y), np.nan)
    print(f"\n[CV] 티커 단위 GroupKFold {n_splits}-fold")
    for tr, va in gkf.split(X, y, groups=groups):
        m = model(pos_weight)
        m.fit(X.iloc[tr], y.iloc[tr])
        oof[va] = m.predict_proba(X.iloc[va])[:, 1]
    mask = ~np.isnan(oof)
    yv, sv = y.values[mask], oof[mask]
    if yv.sum() and yv.sum() < len(yv):
        pr = average_precision_score(yv, sv); roc = roc_auc_score(yv, sv)
        order = np.argsort(-sv); topn = max(1, int(len(sv) * 0.2))
        caught = int(yv[order[:topn]].sum())
        print(f"  PR-AUC {pr:.3f} (기준선 {yv.mean():.3f}) | ROC-AUC {roc:.3f}")
        print(f"  상위20%: 정밀도 {caught/topn:.2f} · 재현율 {caught/yv.sum():.2f}")
    else:
        pr = roc = float("nan")
        print("  ⚠️ 평가 불가 (positive 부족)")

    # Forward backtest
    print("\n[Forward Backtest] 연도별 워크포워드")
    years = sorted(df["year"].unique())
    for Y in years:
        tr = df[df["year"] < Y]; te = df[df["year"] == Y]
        if len(tr) < 50 or te["forward_cut"].nunique() < 2:
            continue
        m = model(pos_weight); m.fit(feats(tr), tr["forward_cut"])
        s = m.predict_proba(feats(te))[:, 1]; t = te["forward_cut"].values
        try:
            p = average_precision_score(t, s)
        except Exception:
            p = float("nan")
        print(f"  {Y}: 학습 {len(tr)} 평가 {len(te)} 내년삭감 {int(t.sum())}  PR-AUC {p:.3f}")

    # 전체 학습 + 저장 (US 전용 위험 임계값)
    final = model(pos_weight); final.fit(X, y)
    cut20 = float(np.nanquantile(oof[mask], 0.80)) if mask.sum() else 0.5
    bundle = {
        "pipeline": final, "feature_names": FEATURES, "market": "US",
        "target": "forward_cut(next-year dividend cut)",
        "risk_alert": {"score": "p_cut", "top20_cut": round(cut20, 4),
                       "pr_auc": round(float(pr), 4) if pr == pr else None,
                       "validated": "GroupKFold(ticker) OOF"},
    }
    joblib.dump(bundle, MODEL_PATH)
    print(f"\n✅ 저장: {MODEL_PATH}")
    print("   (US 전용 — KR 모델과 완전 분리. payout/threshold 모두 US 기준)")


if __name__ == "__main__":
    main()

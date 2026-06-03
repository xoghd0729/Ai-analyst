"""
scripts/verify_shap.py — SHAP 설명력 검증 (신규 13피처 공급 확인)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

목적
  피처를 5→13개로 늘린 뒤, SHAP 설명이 실제로 신규 피처
  (debt_ratio·interest_coverage·revenue_yoy_pct)를 반영하는지 검증한다.

방식
  학습 데이터의 위험 종목(label3∈{1,2}) 샘플에 explain_prediction 실행 →
  top factor 피처를 집계. 신규 피처가 상위에 등장하는 빈도를 보고한다.

실행
  python scripts/verify_shap.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.shap_explainer import explain_prediction, _load_latest_features

NEW = {"debt_ratio", "interest_coverage", "revenue_yoy_pct"}


def main():
    feats = _load_latest_features()
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = pd.read_csv(os.path.join(base, "data", "dividend_dataset.csv"),
                     dtype={"stock_code": str})
    df = df[df["label3"].isin([1, 2])]
    codes = [str(c).zfill(6) for c in df["stock_code"].unique() if str(c).zfill(6) in feats]

    print("=" * 60)
    print("  SHAP 설명력 검증 (신규 피처 반영 확인)")
    print("=" * 60)
    print(f"  위험 종목 {len(codes)}개에 SHAP 실행")

    top_counter: Counter = Counter()
    new_in_top = 0
    shown = 0
    for code in codes:
        exp = explain_prediction(feats[code], n_top=3)
        factors = exp.get("top_factors", [])
        names = [f.get("feature") for f in factors]
        top_counter.update(names)
        if NEW & set(names):
            new_in_top += 1
        if shown < 3 and factors:
            print(f"\n  [{code}] 예측={exp.get('prediction')} 신뢰={exp.get('confidence')}")
            for f in factors:
                print(f"     {f.get('feature'):<18} 기여 {f.get('shap_value'):+.3f}  {f.get('label_ko','')}")
            shown += 1

    print("\n" + "-" * 60)
    print(f"  신규 피처가 top3에 든 종목: {new_in_top}/{len(codes)} "
          f"({new_in_top/max(1,len(codes))*100:.0f}%)")
    print("  전체 top factor 등장 빈도:")
    for feat, cnt in top_counter.most_common():
        tag = " ← 신규" if feat in NEW else ""
        print(f"     {feat:<18} {cnt}회{tag}")
    print("=" * 60)
    print("  해석: 신규 피처가 상위에 충분히 등장하면 = 피처 확장이 설명력에 기여.")
    print("        엉뚱한 노이즈 피처만 상위면 = 다음 튜닝 포인트.")


if __name__ == "__main__":
    main()

"""
scripts/validate_survival.py — 생존확률 검증 (실제 과거로 검증)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

질문
  "생존확률이 높다고 한 포트폴리오가 실제 과거에 더 잘 버텼나?"
  → 교수/면접관의 "그 숫자 믿어도 됩니까?"에 답한다.

방법
  - 예측: utils.survival.run_survival 의 survival_probability (20년 전방 확률)
  - 실제: dividend_dataset.csv 의 '실제 DPS 이력'으로 과거 소득 유지율 계산
          (2015~2025, 2020 코로나 삭감 포함). 각 종목 dps(t)/dps(시작) 가중합.
  - 둘의 '순위'가 일치하는가 (Spearman). 예측 생존이 높을수록 실제 유지율↑이면 타당.
  - 추가: 금융 몰빵 vs 분산 포트폴리오 직접 비교.

실행
  python scripts/validate_survival.py
"""
from __future__ import annotations

import os
import random
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.survival import run_survival

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(BASE, "data", "dividend_dataset.csv")
ML   = os.path.join(BASE, "data", "ml_scoring_results.csv")
START, END = 2015, 2024


def load():
    d = pd.read_csv(DATA, dtype={"stock_code": str})
    d["stock_code"] = d["stock_code"].str.zfill(6)
    d = d[(d["year"] >= START) & (d["year"] <= END)]
    # 종목별 dps 시계열
    dps = {}
    name = {}
    for code, g in d.groupby("stock_code"):
        s = g.set_index("year")["dps"].dropna()
        if len(s) >= 6 and s.iloc[0] > 0:
            dps[code] = s
            name[code] = g["name"].iloc[0]
    # ML 점수
    ml = {}
    if os.path.exists(ML):
        m = pd.read_csv(ML, dtype={"stock_code": str})
        if "stock_code" in m.columns:
            m["stock_code"] = m["stock_code"].str.zfill(6)
            for _, r in m.iterrows():
                ml[r["stock_code"]] = (float(r.get("P_WEAKENING", 0) or 0),
                                       float(r.get("P_BROKEN", 0) or 0))
    return dps, name, ml


def actual_min_retention(codes, dps) -> float:
    """포트폴리오 실제 소득의 '러닝 피크 대비 최대 낙폭' 후 잔존율.
    배당 성장 속에서도 실제 삭감(예: 2020) 구간의 소득 하락을 포착한다.
    1.0=한 번도 안 깎임, 낮을수록 과거에 소득이 크게 흔들림."""
    series = [dps[c] for c in codes if c in dps]
    if not series:
        return float("nan")
    income = []
    for t in range(START, END + 1):
        vals = [float(s.loc[t]) / float(s.iloc[0])
                for s in series if t in s.index and s.iloc[0] > 0]
        if vals:
            income.append(sum(vals) / len(vals))
    if not income:
        return float("nan")
    peak = income[0]
    worst = 1.0
    for v in income:
        peak = max(peak, v)
        worst = min(worst, v / peak)      # 러닝 피크 대비 잔존율
    return round(worst, 3)


def predicted_survival(codes, name, ml) -> float:
    recs = []
    for c in codes:
        pw, pb = ml.get(c, (0.10, 0.05))
        recs.append({
            "name": name.get(c, c), "asset_class": "kr_stock",
            "invest_amount_만원": 1000, "dividend_yield": 4.5,
            "P_WEAKENING": pw, "P_BROKEN": pb,
        })
    r = run_survival(recs, years=20, n_simulations=1500, monthly_target=0, seed=7)
    return r["survival_probability"]


def spearman(xs, ys) -> float:
    def rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0] * len(v)
        for pos, i in enumerate(order):
            rk[i] = pos
        return rk
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    d2 = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return round(1 - 6 * d2 / (n * (n * n - 1)), 3)


def main():
    dps, name, ml = load()
    codes = list(dps.keys())
    print("=" * 64)
    print("  생존확률 검증 — 예측 vs 실제 과거 소득 유지율")
    print("=" * 64)
    print(f"  대상 종목 {len(codes)}개 | 기간 {START}~{END} (2020 코로나 포함)")

    # 1) 무작위 포트폴리오 sweep → 순위상관
    rng = random.Random(0)
    pred, actual = [], []
    for _ in range(40):
        port = rng.sample(codes, 6)
        p = predicted_survival(port, name, ml)
        a = actual_min_retention(port, dps)
        if a == a:
            pred.append(p); actual.append(a)
    rho = spearman(pred, actual)
    print(f"\n  [무작위 40개 포트폴리오] 예측 생존확률 vs 실제 최악연도 유지율")
    print(f"  Spearman 순위상관 ρ = {rho}  (양수·클수록 '예측이 현실과 일치')")

    # 2) 금융 몰빵 vs 분산 직접 비교
    def pick(keys, n):
        out = []
        for c in codes:
            if any(k in name[c] for k in keys):
                out.append(c)
            if len(out) >= n:
                break
        return out

    fin = pick(["금융", "은행", "보험", "지주"], 5)
    diverse = (pick(["금융"], 1) + pick(["전자"], 1) + pick(["화학"], 1)
               + pick(["통신", "KT"], 1) + pick(["제약", "바이오"], 1))
    diverse = [c for i, c in enumerate(diverse) if c and c not in diverse[:i]]

    print("\n  [집중 vs 분산 직접 비교]")
    for label, port in (("금융 몰빵", fin), ("분산", diverse)):
        if not port:
            continue
        p = predicted_survival(port, name, ml)
        a = actual_min_retention(port, dps)
        nm = ", ".join(name[c] for c in port)
        print(f"  {label:<8} 예측생존 {p:>5.1f}% | 실제 최악연도 유지율 {a:.2f}")
        print(f"           구성: {nm}")

    print("\n" + "-" * 64)
    print("  해석: ρ가 충분히 양수면 = 생존확률이 실제 과거 생존을 잘 예측.")
    print("        금융몰빵의 실제 유지율이 분산보다 낮으면 = 상관충격 모델 타당.")
    print("=" * 64)


if __name__ == "__main__":
    main()

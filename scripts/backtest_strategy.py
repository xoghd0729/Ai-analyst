"""
scripts/backtest_strategy.py — 전략 백테스트 (ML 위험 신호의 가치 검증)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

질문
  "ML이 위험하다고 한 종목(AT_RISK)을 걸러내면, 실제 과거 성과가 좋아졌나?"
  → 시스템의 핵심 가치(위험경고)가 돈을 지켰는지/벌었는지 증명.

방법
  - 유니버스: ml_scoring_results.csv(P_BROKEN/P_WEAKENING) ∩ 실제 수익률 보유 종목
  - 전체 포트폴리오 vs 'AT_RISK 제외' 포트폴리오를 run_backtest로 비교
  - 지표: CAGR · MDD · Sharpe · KOSPI 대비 초과수익 (2015~2024)
  - 위험점수 = P_WEAKENING + P_BROKEN, 상위 구간 제외 시 효과 측정

실행
  python scripts/backtest_strategy.py
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.backtesting import run_backtest

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
START, END = 2015, 2024


def load_universe():
    ml = pd.read_csv(os.path.join(BASE, "data", "ml_scoring_results.csv"),
                     dtype={"stock_code": str})
    ml["stock_code"] = ml["stock_code"].str.zfill(6)
    hist = json.load(open(os.path.join(BASE, "data", "kr_historical_returns.json")))
    hist_codes = set(hist.keys())
    rows = []
    for _, r in ml.iterrows():
        code = r["stock_code"]
        if code not in hist_codes:
            continue
        risk = float(r.get("P_WEAKENING", 0) or 0) + float(r.get("P_BROKEN", 0) or 0)
        rows.append({"stock_code": code, "name": r.get("name", code), "risk": risk})
    return rows


def to_recs(stocks):
    w = 100.0 / len(stocks)
    return [{"ticker": s["stock_code"], "asset_class": "kr_stock", "weight_pct": w}
            for s in stocks]


def show(label, res):
    print(f"  {label:<22} CAGR {res['cagr_pct']:>6.2f}% | MDD {res['mdd_pct']:>6.2f}% | "
          f"Sharpe {res['sharpe_ratio']:>5.2f} | 총수익 {res.get('total_return_pct',0):>6.1f}%")


def main():
    uni = load_universe()
    if len(uni) < 6:
        print(f"⚠️ 유니버스 부족({len(uni)}). ml_scoring_results 와 kr_historical_returns 교집합 확인.")
        return
    uni.sort(key=lambda x: x["risk"])
    risks = [s["risk"] for s in uni]
    q75 = sorted(risks)[int(len(risks) * 0.75)]

    full     = uni
    screened = [s for s in uni if s["risk"] < q75]      # 위험 상위 25% 제외

    print("=" * 74)
    print("  전략 백테스트 — ML 위험 신호의 가치 (2015~2024)")
    print("=" * 74)
    print(f"  유니버스 {len(full)}종목 | AT_RISK 제외 후 {len(screened)}종목 "
          f"(위험점수 ≥ {q75:.2f} 제외)")
    print(f"  제외된 고위험 종목: {', '.join(s['name'] for s in uni if s['risk'] >= q75)}")
    print("-" * 74)

    r_full = run_backtest(to_recs(full), START, END, investable=1000.0)
    r_scr  = run_backtest(to_recs(screened), START, END, investable=1000.0)
    show("전체 포트폴리오", r_full)
    show("AT_RISK 제외 (ML 적용)", r_scr)

    # KOSPI 벤치마크 (yearly vs_kospi 합산 근사)
    kospi_cagr = None
    if r_full.get("yearly_returns"):
        ks = [y.get("kospi_ret", 0) for y in r_full["yearly_returns"]]
        if ks:
            val = 1.0
            for k in ks:
                val *= (1 + k / 100)
            kospi_cagr = (val ** (1 / len(ks)) - 1) * 100

    print("-" * 74)
    d_cagr = r_scr["cagr_pct"] - r_full["cagr_pct"]
    d_mdd  = r_scr["mdd_pct"] - r_full["mdd_pct"]      # 음수(덜 빠짐)면 개선
    d_shp  = r_scr["sharpe_ratio"] - r_full["sharpe_ratio"]
    print(f"  ML 적용 효과:  CAGR {d_cagr:+.2f}%p | MDD {d_mdd:+.2f}%p "
          f"| Sharpe {d_shp:+.2f}")
    if kospi_cagr is not None:
        print(f"  KOSPI CAGR(근사) {kospi_cagr:.2f}%  → 전략 초과수익 "
              f"{r_scr['cagr_pct'] - kospi_cagr:+.2f}%p")
    print("\n  해석:")
    print("   - MDD가 줄고 Sharpe가 오르면 = ML 위험경고가 하락을 막아 '돈을 지켰다'.")
    print("   - CAGR까지 오르면 = 위험종목 제외가 수익도 개선.")
    print("   - 한계: 유니버스·기간이 제한적이라 방향성 증거. 표본 늘리면 강해짐.")
    print("=" * 74)


if __name__ == "__main__":
    main()

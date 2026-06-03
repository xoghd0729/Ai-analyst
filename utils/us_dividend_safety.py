"""
utils/us_dividend_safety.py — US 전용 배당안전성 점수 (KR과 분리)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 ML이 아니라 룰베이스인가 (캡스톤 핵심 논리)
  US 배당주는 삭감이 드물어(≈4%) ML 학습이 불가능함을 train_us_risk.py로
  실측(PR-AUC 0.05)했다. 표본이 희소할 땐 ML보다 '투명한 안전성 지표'가
  더 적절하다 — 업계 표준(Simply Safe Dividends)도 동일 접근.

KR과 무엇이 다른가
  - payout 임계값: KR은 15~50%가 이상. US 배당귀족은 60~70%가 정상.
  - REIT/유틸리티는 구조적으로 payout이 높음 → 섹터별 밴드 조정.
  - consecutive_years(연속 증배 연수)가 US에선 가장 강력한 안전 신호.

산출
  score_us_dividend_safety(...) -> {
      safety_score(0~100), tier(SAFE/BORDERLINE/AT_RISK), breakdown{...}
  }
  breakdown 으로 '왜 이 점수인지' 설명 가능 (US판 설명가능성).

검증
  python utils/us_dividend_safety.py
  → us_dividend_dataset.csv의 실제 '내년 삭감'을 AT_RISK 티어가
    얼마나 잡는지 정밀도·재현율 출력.
"""
from __future__ import annotations

import os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _payout_penalty(payout: Optional[float], is_reit: bool, is_utility: bool) -> tuple[float, str]:
    """US 섹터별 payout 밴드. payout = 배당/영업현금흐름(%) 근사."""
    if payout is None or payout != payout:
        return 5.0, "payout 데이터 없음(-5)"
    # 섹터별 허용 상향 (REIT/유틸은 구조적 고배당)
    shift = 25.0 if is_reit else (15.0 if is_utility else 0.0)
    p = payout - shift
    if p <= 60:   return 0.0,  f"payout {payout:.0f}% 안전(0)"
    if p <= 75:   return 10.0, f"payout {payout:.0f}% 다소 높음(-10)"
    if p <= 90:   return 25.0, f"payout {payout:.0f}% 위험 수위(-25)"
    if p <= 110:  return 40.0, f"payout {payout:.0f}% 과다(-40)"
    return 55.0, f"payout {payout:.0f}% 지속불가/음수(-55)"


def _coverage_penalty(cov: Optional[float]) -> tuple[float, str]:
    if cov is None or cov != cov:
        return 5.0, "coverage 없음(-5)"
    if cov >= 2.0: return 0.0,  f"FCF커버리지 {cov:.1f}배 충분(0)"
    if cov >= 1.0: return 12.0, f"FCF커버리지 {cov:.1f}배 빠듯(-12)"
    return 25.0, f"FCF커버리지 {cov:.1f}배 미달(-25)"


def _leverage_penalty(nde: Optional[float]) -> tuple[float, str]:
    if nde is None or nde != nde:
        return 4.0, "순부채/EBITDA 없음(-4)"
    if nde <= 2.0: return 0.0,  f"순부채/EBITDA {nde:.1f}배 건전(0)"
    if nde <= 3.5: return 8.0,  f"순부채/EBITDA {nde:.1f}배 보통(-8)"
    if nde <= 5.0: return 18.0, f"순부채/EBITDA {nde:.1f}배 높음(-18)"
    return 30.0, f"순부채/EBITDA {nde:.1f}배 과다(-30)"


def _track_record(consec: Optional[float]) -> tuple[float, str]:
    """연속 증배 연수 — US 안전성의 핵심 신호. 보너스(음수=가점)."""
    if consec is None or consec != consec:
        return 6.0, "증배이력 없음(-6)"
    if consec >= 25: return -10.0, f"{int(consec)}년 연속증배=배당귀족(+10)"
    if consec >= 10: return -3.0,  f"{int(consec)}년 연속증배(+3)"
    if consec >= 5:  return 5.0,   f"{int(consec)}년 증배(-5)"
    return 12.0, f"증배이력 {int(consec)}년뿐(-12)"


def score_us_dividend_safety(
    payout_ratio: Optional[float] = None,
    dividend_coverage: Optional[float] = None,
    net_debt_ebitda: Optional[float] = None,
    consecutive_years: Optional[float] = None,
    dps_yoy_pct: Optional[float] = None,
    fcf_negative: Optional[int] = 0,
    is_reit: bool = False,
    sector: str = "",
) -> dict:
    is_utility = "util" in (sector or "").lower() or "유틸" in (sector or "")
    score = 100.0
    bd = []
    for pen, msg in (
        _payout_penalty(payout_ratio, is_reit, is_utility),
        _coverage_penalty(dividend_coverage),
        _leverage_penalty(net_debt_ebitda),
        _track_record(consecutive_years),
    ):
        score -= pen
        bd.append(msg)

    if dps_yoy_pct is not None and dps_yoy_pct == dps_yoy_pct and dps_yoy_pct < 0:
        score -= 15.0; bd.append(f"최근 배당 {dps_yoy_pct:.0f}% 감소/동결(-15)")
    if fcf_negative:
        score -= 20.0; bd.append("FCF 적자(-20)")

    score = max(0.0, min(100.0, score))
    tier = "SAFE" if score >= 70 else ("BORDERLINE" if score >= 45 else "AT_RISK")
    return {"safety_score": round(score, 1), "tier": tier, "breakdown": bd}


# ─────────────────────────────────────────────────────────────
# 검증: 실제 '내년 삭감'을 AT_RISK 티어가 얼마나 잡는가
# ─────────────────────────────────────────────────────────────
def _validate() -> None:
    import pandas as pd
    path = os.path.join(BASE_DIR, "data", "us_dividend_dataset.csv")
    df = pd.read_csv(path).sort_values(["ticker", "year"])
    df["forward_cut"] = df.groupby("ticker")["dividend_cut"].shift(-1)
    df = df.dropna(subset=["forward_cut"]).copy()
    df["forward_cut"] = df["forward_cut"].astype(int)

    scores, tiers = [], []
    for _, r in df.iterrows():
        out = score_us_dividend_safety(
            payout_ratio=r.get("payout_ratio"),
            dividend_coverage=r.get("dividend_coverage"),
            net_debt_ebitda=r.get("net_debt_ebitda"),
            consecutive_years=r.get("consecutive_years"),
            dps_yoy_pct=r.get("dps_yoy_pct"),
            fcf_negative=int(r.get("fcf_negative") or 0),
            is_reit=bool(r.get("is_reit")),
            sector=str(r.get("sector", "")),
        )
        scores.append(out["safety_score"]); tiers.append(out["tier"])
    df["safety_score"] = scores
    df["tier"] = tiers

    print("=" * 60)
    print("  US 배당안전성 점수 — 검증 (룰베이스, US 기준)")
    print("=" * 60)
    n = len(df); pos = int(df["forward_cut"].sum())
    print(f"  행 {n} | 내년삭감 {pos}건 ({pos/n*100:.1f}%)")
    print(f"  티어 분포: {df['tier'].value_counts().to_dict()}")

    # AT_RISK 또는 BORDERLINE 을 '경고'로 보고 평가
    for label, flag in (("AT_RISK만", df["tier"] == "AT_RISK"),
                        ("AT_RISK+BORDERLINE", df["tier"].isin(["AT_RISK", "BORDERLINE"]))):
        alerted = int(flag.sum())
        caught = int(df.loc[flag, "forward_cut"].sum())
        prec = caught / alerted if alerted else 0
        rec = caught / pos if pos else 0
        print(f"  [{label}] 경고 {alerted}건 → 실제삭감 {caught}건  "
              f"정밀도 {prec:.2f} · 재현율 {rec:.2f}")

    # 점수 낮은 종목이 실제로 더 잘 깎이는가 (랭킹 타당성)
    from statistics import mean
    cut_score = mean(df.loc[df["forward_cut"] == 1, "safety_score"])
    safe_score = mean(df.loc[df["forward_cut"] == 0, "safety_score"])
    print(f"  평균 안전점수 — 삭감군 {cut_score:.1f} vs 유지군 {safe_score:.1f} "
          f"(차이 클수록 타당)")
    print("=" * 60)


if __name__ == "__main__":
    _validate()

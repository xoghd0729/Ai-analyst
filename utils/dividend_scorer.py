"""
배당 포트폴리오 전용 스코어링 엔진

■ 설계 원칙
  일반 재무건전성 스코어가 아닌 '배당 투자자 관점'의 점수.
  같은 삼성전자라도 배당 포트폴리오에선 yield 0.5%면 낮은 점수여야 한다.

■ 4차원 평가 (총 100점)
  yield_score     (35pt): 현재 배당수익률 — 너무 낮으면 의미 없고, 너무 높으면 trap
  stability_score (35pt): ML 상태 + 배당 삭감 이력 — 배당이 지속될 것인가
  financial_score (20pt): payout ratio + coverage — 재무적으로 배당이 가능한가
  growth_score    (10pt): DPS YoY 성장률 — 배당이 늘고 있는가

■ 하드 필터 (점수 계산 전 자동 제외)
  1. ML BROKEN → 즉시 제외 (AI가 배당삭감 고위험 판정)
  2. yield < 1.5% → 배당 포트폴리오 의미 없음
  3. WEAKENING + dps_cuts >= 2 → 악화 중 + 반복 삭감

■ 등급
  80+: 🟢 우량  (핵심 편입)
  65+: 🟡 보통  (비중 조절 편입)
  50+: 🟠 주의  (소량 편입 가능)
  50미만: ❌ 제외
"""

from __future__ import annotations
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ── 1. yield_score (35점) ─────────────────────────────────────
# 한국 시장 기준: 3~5% 가 sweet spot
# 너무 낮으면 배당 포트폴리오 의미 없음
# 너무 높으면 yield trap (주가 폭락 + 배당 삭감 동반 위험)
def _score_yield(yield_pct: float) -> float:
    if yield_pct < 1.5:   return 0.0   # 하드컷
    if yield_pct < 2.0:   return 12.0
    if yield_pct < 2.5:   return 18.0
    if yield_pct < 3.0:   return 23.0
    if yield_pct < 4.0:   return 30.0
    if yield_pct < 5.0:   return 35.0  # sweet spot
    if yield_pct < 6.0:   return 30.0  # 좀 높아서 trap 주의
    if yield_pct < 8.0:   return 20.0  # yield trap 위험
    return 8.0                          # 8% 이상 = 거의 대부분 trap


# ── 2. stability_score (35점) ────────────────────────────────
# ML 상태 × 배당 삭감 이력으로 배당 지속가능성 판단
def _score_stability(
    ml_status: str,
    dps_cuts: int,       # 최근 3년 배당 삭감 횟수
    latest_yoy: float,   # 최근 DPS YoY 변화율
) -> float:
    if ml_status == "BROKEN":
        return 0.0  # 하드컷

    base = 35.0 if ml_status == "INTACT" else 20.0  # WEAKENING

    # 배당 삭감 이력 패널티
    if dps_cuts == 0:
        cut_penalty = 0.0
    elif dps_cuts == 1:
        cut_penalty = 7.0
    else:
        cut_penalty = 15.0

    # 최근 DPS 변화 보정
    if latest_yoy is None or (isinstance(latest_yoy, float) and latest_yoy != latest_yoy):
        yoy_adj = 0.0
    elif latest_yoy >= 5.0:
        yoy_adj = 3.0   # 성장 중
    elif latest_yoy >= 0.0:
        yoy_adj = 0.0
    else:
        yoy_adj = -5.0  # 최근 삭감

    return min(35.0, max(0.0, base - cut_penalty + yoy_adj))  # 35점 캡


# ── 3. financial_score (20점) ────────────────────────────────
# payout ratio: 너무 낮으면 배당 의지 없음, 너무 높으면 지속 불가
# dividend coverage: 이익 대비 배당 여유
def _score_financial(
    payout_ratio: Optional[float],
    div_coverage: Optional[float],
) -> float:
    score = 10.0  # 데이터 없을 때 중립

    if payout_ratio is not None and payout_ratio == payout_ratio:
        if 15.0 <= payout_ratio <= 50.0:
            score = 20.0   # 이상적 구간
        elif 10.0 <= payout_ratio < 15.0:
            score = 14.0   # 배당 성향 낮음
        elif 50.0 < payout_ratio <= 70.0:
            score = 13.0   # 좀 타이트
        elif 70.0 < payout_ratio <= 90.0:
            score = 6.0    # 위험 수위
        else:
            score = 2.0    # 90% 초과 or 음수

    # coverage 보너스 (현금흐름이 배당의 몇 배인가)
    if div_coverage is not None and div_coverage == div_coverage:
        if div_coverage >= 3.0:
            score = min(20.0, score + 3.0)
        elif div_coverage >= 2.0:
            score = min(20.0, score + 1.5)
        elif div_coverage < 1.0:
            score = max(0.0, score - 4.0)

    return score


# ── 4. growth_score (10점) ───────────────────────────────────
# 배당이 꾸준히 늘고 있는지 — 배당성장주의 핵심
def _score_growth(latest_yoy: Optional[float], dps_cuts: int) -> float:
    if latest_yoy is None or (isinstance(latest_yoy, float) and latest_yoy != latest_yoy):
        return 4.0  # 데이터 없으면 중립

    if dps_cuts == 0 and latest_yoy >= 10.0:  return 10.0
    if dps_cuts == 0 and latest_yoy >= 5.0:   return 8.0
    if dps_cuts == 0 and latest_yoy >= 0.0:   return 5.0
    if latest_yoy < 0.0:                       return 0.0
    return 3.0


# ── 메인 스코어링 함수 ────────────────────────────────────────
def score_dividend_stock(
    stock_code:   str,
    name:         str,
    yield_pct:    float,
    ml_status:    str       = "INTACT",
    dps_cuts:     int       = 0,
    latest_yoy:   float     = 0.0,
    payout_ratio: Optional[float] = None,
    div_coverage: Optional[float] = None,
    p_broken:     float     = 0.0,
) -> dict:
    """
    배당 포트폴리오 전용 점수 계산.

    반환:
    {
        "stock_code", "name",
        "overall_score",          # 0~100
        "grade",                  # 🟢 우량 / 🟡 보통 / 🟠 주의 / ❌ 제외
        "trap_level",             # SAFE / WATCH / DANGER
        "yield_score",
        "stability_score",
        "financial_score",
        "growth_score",
        "exclude_reason",         # 제외 이유 (제외 종목만)
    }
    """
    # ── 하드 필터 ──────────────────────────────────────────────
    if ml_status == "BROKEN":
        return _excluded(stock_code, name, "ML BROKEN — AI 배당삭감 고위험 판정")
    if yield_pct < 1.5:
        return _excluded(stock_code, name, f"배당수익률 {yield_pct:.2f}% — 1.5% 미만")
    if ml_status == "WEAKENING" and dps_cuts >= 2:
        return _excluded(stock_code, name, "WEAKENING + 최근 3년 배당삭감 2회 이상")

    # ── 점수 계산 ──────────────────────────────────────────────
    ys = _score_yield(yield_pct)
    ss = _score_stability(ml_status, dps_cuts, latest_yoy)
    fs = _score_financial(payout_ratio, div_coverage)
    gs = _score_growth(latest_yoy, dps_cuts)

    total = round(ys + ss + fs + gs, 1)

    # ── 등급 ───────────────────────────────────────────────────
    if total >= 80:   grade = "🟢 우량"
    elif total >= 65: grade = "🟡 보통"
    elif total >= 50: grade = "🟠 주의"
    else:
        return _excluded(stock_code, name, f"종합점수 {total}점 미달 (최소 50점)")

    # ── yield trap 감지 ────────────────────────────────────────
    if yield_pct >= 8.0:
        trap_level = "DANGER"
    elif yield_pct >= 6.0 or p_broken >= 0.4:
        trap_level = "WATCH"
    else:
        trap_level = "SAFE"

    return {
        "stock_code":      stock_code,
        "name":            name,
        "overall_score":   total,
        "grade":           grade,
        "trap_level":      trap_level,
        "yield_score":     round(ys, 1),
        "stability_score": round(ss, 1),
        "financial_score": round(fs, 1),
        "growth_score":    round(gs, 1),
        "exclude_reason":  None,
    }


def score_us_dividend_stock(
    ticker:            str,
    name:              str,
    yield_pct:         float,
    dividend_cut:      int   = 0,       # 최근 1년 배당삭감 여부 (0/1)
    dps_yoy_pct:       float = 0.0,     # 최근 DPS YoY
    payout_ratio:      Optional[float] = None,
    div_coverage:      Optional[float] = None,
    consecutive_years: int   = 0,       # 연속 배당성장 연수 (배당귀족 지표)
) -> dict:
    """
    미국 배당 개별주 전용 스코어링.

    한국 버전과 다른 점:
    - ML 상태 대신 consecutive_years (연속 배당성장 연수) 사용
    - 25년+ → Dividend Aristocrat, 50년+ → Dividend King
    - yield sweet spot이 한국과 다름 (미국은 2~4%가 우량)
    """
    # ── 하드 필터 ──────────────────────────────────────────────
    if yield_pct < 1.5:
        return _excluded(ticker, name, f"배당수익률 {yield_pct:.2f}% — 1.5% 미만")
    if dividend_cut == 1 and consecutive_years < 10:
        return _excluded(ticker, name, "최근 배당삭감 + 배당성장 이력 부족")

    # ── 1. yield_score ─────────────────────────────────────────
    # 미국은 2~4%가 우량 (성장주 비중 높아 한국보다 yield 낮음)
    if yield_pct < 1.5:   ys = 0.0
    elif yield_pct < 2.0: ys = 14.0
    elif yield_pct < 2.5: ys = 20.0
    elif yield_pct < 3.0: ys = 27.0
    elif yield_pct < 4.0: ys = 35.0   # sweet spot
    elif yield_pct < 5.0: ys = 30.0
    elif yield_pct < 7.0: ys = 20.0   # 미국에서 5%+는 trap 주의
    else:                  ys = 8.0

    # ── 2. stability_score ────────────────────────────────────
    # consecutive_years로 배당 신뢰성 판단
    if consecutive_years >= 50:   ss_base = 35.0   # Dividend King
    elif consecutive_years >= 25: ss_base = 32.0   # Dividend Aristocrat
    elif consecutive_years >= 10: ss_base = 25.0   # Dividend Challenger
    elif consecutive_years >= 5:  ss_base = 18.0
    else:                         ss_base = 10.0

    # 최근 삭감 패널티
    cut_pen = 8.0 if dividend_cut == 1 else 0.0

    # 최근 YoY 보정
    if dps_yoy_pct >= 5.0:   yoy_adj = 3.0
    elif dps_yoy_pct >= 0.0: yoy_adj = 0.0
    else:                    yoy_adj = -4.0

    ss = min(35.0, max(0.0, ss_base - cut_pen + yoy_adj))

    # ── 3. financial_score ────────────────────────────────────
    fs = _score_financial(payout_ratio, div_coverage)

    # ── 4. growth_score ───────────────────────────────────────
    if dps_yoy_pct >= 10.0 and dividend_cut == 0: gs = 10.0
    elif dps_yoy_pct >= 5.0 and dividend_cut == 0: gs = 8.0
    elif dps_yoy_pct >= 0.0:                       gs = 5.0
    else:                                          gs = 0.0

    total = round(ys + ss + fs + gs, 1)

    # ── 등급 & trap ───────────────────────────────────────────
    if total >= 80:   grade = "🟢 우량"
    elif total >= 65: grade = "🟡 보통"
    elif total >= 50: grade = "🟠 주의"
    else:
        return _excluded(ticker, name, f"종합점수 {total}점 미달")

    if yield_pct >= 7.0:   trap_level = "DANGER"
    elif yield_pct >= 5.0: trap_level = "WATCH"
    else:                  trap_level = "SAFE"

    # 배당귀족 여부
    if consecutive_years >= 50:   asset_type = "DIVIDEND_KING"
    elif consecutive_years >= 25: asset_type = "DIVIDEND_ARISTOCRAT"
    elif consecutive_years >= 10: asset_type = "DIVIDEND_CHALLENGER"
    else:                         asset_type = "HIGH_YIELD"

    return {
        "stock_code":          ticker,
        "name":                name,
        "overall_score":       total,
        "grade":               grade,
        "trap_level":          trap_level,
        "asset_type":          asset_type,
        "consecutive_years":   consecutive_years,
        "yield_score":         round(ys, 1),
        "stability_score":     round(ss, 1),
        "financial_score":     round(fs, 1),
        "growth_score":        round(gs, 1),
        "exclude_reason":      None,
    }


def _excluded(code: str, name: str, reason: str) -> dict:
    return {
        "stock_code":      code,
        "name":            name,
        "overall_score":   0,
        "grade":           "❌ 제외",
        "trap_level":      "DANGER",
        "yield_score":     0,
        "stability_score": 0,
        "financial_score": 0,
        "growth_score":    0,
        "exclude_reason":  reason,
    }

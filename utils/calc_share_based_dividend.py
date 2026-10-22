"""
주수(株數) 기반 배당 계산 엔진
================================
기존: 투자금 × 배당수익률% → 연간 배당
신규: 투자금 ÷ 주가 → 보유 주수 × 주당 배당금(DPS) → 연간 배당

왜 바꾸는가?
  - 주가가 오르면 같은 돈으로 주수가 줄어드는 걸 수익률% 방식은 반영 못 함
  - 사용자가 "몇 주를 사면 얼마를 받는지" 직접 확인 가능
  - PRU $5.60/주처럼 공시 배당금과 직접 대조 가능

데이터 기준일 원칙:
  - 주가와 DPS는 fetched_at 기준 — 계산 결과에 반드시 명시
  - 과거 시점 계산 시 해당 시점의 주가를 별도 조회해야 함 (현재 미지원 → WARNING)
"""
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

# ── 상수 ─────────────────────────────────────────────────────────
DEFAULT_USD_KRW    = 1_380.0   # 환율 기본값 (반드시 명시)
DEFAULT_COMMISSION = 0.0025    # 해외주식 매수 수수료 0.25%
TAX_RATE_DIVIDEND  = 0.154     # 배당소득세 15.4% (원천징수)

# 지급 주기별 연간 지급 횟수
FREQ_MAP = {
    "monthly":   12,
    "quarterly":  4,
    "semiannual": 2,
    "annual":     1,
}


@dataclass
class ShareCalcResult:
    """주수 기반 계산 결과 단위"""
    ticker:             str
    name:               str
    investment_manwon:  float   # 투자금 (만원)
    price_usd:          float   # 주가 (USD)
    usd_krw:            float   # 적용 환율
    price_krw:          float   # 주가 (원)
    shares:             float   # 매수 주수 (소수점 허용)
    annual_dps_usd:     float   # 연간 주당 배당금 (USD)
    annual_div_usd:     float   # 연간 배당금 합계 (USD)
    annual_div_krw:     float   # 연간 배당금 (원)
    annual_div_after_tax_krw: float  # 세후 연간 배당금 (원)
    monthly_div_after_tax_manwon: float  # 세후 월 평균 배당 (만원)
    dividend_yield_pct: float   # 실효 배당수익률 (%)
    data_date:          str     # 데이터 기준일
    frequency:          str     # 지급 주기
    warning:            str = ""


@dataclass
class PortfolioShareCalc:
    """포트폴리오 전체 주수 기반 계산 결과"""
    total_investment_manwon: float
    total_annual_div_after_tax_manwon: float
    total_monthly_div_after_tax_manwon: float
    effective_yield_pct: float
    data_date: str
    usd_krw: float
    holdings: list = field(default_factory=list)  # List[ShareCalcResult]
    warnings: list = field(default_factory=list)


def _load_cache(cache_path: Optional[str] = None) -> dict:
    if cache_path is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cache_path = os.path.join(base, "data", "us_dividend_cache.json")
    with open(cache_path, encoding="utf-8") as f:
        return json.load(f)


def calc_shares(
    investment_manwon: float,
    price_usd: float,
    usd_krw: float = DEFAULT_USD_KRW,
    commission_rate: float = DEFAULT_COMMISSION,
    allow_fractional: bool = True,
) -> float:
    """
    투자금(만원) → 매수 가능 주수

    Args:
        investment_manwon: 투자금 (만원)
        price_usd: 주당 가격 (USD)
        usd_krw: 환율 (원/달러)
        commission_rate: 매수 수수료율 (예: 0.0025 = 0.25%)
        allow_fractional: True면 소수점 주수 허용 (ETF 소수점 매수)
    """
    if price_usd <= 0 or usd_krw <= 0:
        return 0.0
    investment_won = investment_manwon * 10_000
    price_krw = price_usd * usd_krw * (1 + commission_rate)
    shares = investment_won / price_krw
    return shares if allow_fractional else int(shares)


def calc_annual_dps(price_usd: float, div_yield_pct: float) -> float:
    """주가 × 배당수익률 → 연간 주당 배당금(DPS) 역산"""
    return price_usd * div_yield_pct / 100.0


def calc_share_based_for_ticker(
    ticker: str,
    investment_manwon: float,
    usd_krw: float = DEFAULT_USD_KRW,
    commission_rate: float = DEFAULT_COMMISSION,
    tax_rate: float = TAX_RATE_DIVIDEND,
    cache: Optional[dict] = None,
    frequency: str = "quarterly",
) -> Optional[ShareCalcResult]:
    """
    단일 종목 주수 기반 배당 계산.

    Returns None if ticker not found in cache.
    """
    if cache is None:
        cache = _load_cache()

    data = cache.get(ticker)
    if not data:
        return None

    price_usd   = float(data.get("price_usd") or 0)
    div_yield   = float(data.get("div_yield") or 0)
    name        = data.get("name", ticker)
    fetched_at  = data.get("fetched_at", "unknown")

    if price_usd <= 0:
        return ShareCalcResult(
            ticker=ticker, name=name,
            investment_manwon=investment_manwon,
            price_usd=0, usd_krw=usd_krw, price_krw=0,
            shares=0, annual_dps_usd=0,
            annual_div_usd=0, annual_div_krw=0,
            annual_div_after_tax_krw=0,
            monthly_div_after_tax_manwon=0,
            dividend_yield_pct=0,
            data_date=fetched_at, frequency=frequency,
            warning="주가 데이터 없음",
        )

    annual_dps = calc_annual_dps(price_usd, div_yield)
    shares     = calc_shares(investment_manwon, price_usd, usd_krw, commission_rate)
    price_krw  = price_usd * usd_krw

    annual_div_usd          = shares * annual_dps
    annual_div_krw          = annual_div_usd * usd_krw
    annual_div_after_tax    = annual_div_krw * (1 - tax_rate)
    monthly_div_manwon      = annual_div_after_tax / 12 / 10_000
    eff_yield               = div_yield * (1 - tax_rate)

    # 데이터 기준일 경고
    warning = ""
    try:
        dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
        days_old = (datetime.now() - dt.replace(tzinfo=None)).days
        if days_old > 30:
            warning = f"데이터 {days_old}일 경과 — 주가 재확인 권장"
    except Exception:
        warning = "기준일 파싱 불가"

    return ShareCalcResult(
        ticker=ticker, name=name,
        investment_manwon=investment_manwon,
        price_usd=price_usd,
        usd_krw=usd_krw,
        price_krw=price_krw,
        shares=round(shares, 4),
        annual_dps_usd=round(annual_dps, 4),
        annual_div_usd=round(annual_div_usd, 2),
        annual_div_krw=round(annual_div_krw),
        annual_div_after_tax_krw=round(annual_div_after_tax),
        monthly_div_after_tax_manwon=round(monthly_div_manwon, 2),
        dividend_yield_pct=round(div_yield, 2),
        data_date=fetched_at[:10],
        frequency=frequency,
        warning=warning,
    )


def calc_portfolio_share_based(
    holdings: list,          # [{"ticker": "PRU", "weight_pct": 24.58, ...}]
    total_investment_manwon: float,
    usd_krw: float = DEFAULT_USD_KRW,
    commission_rate: float = DEFAULT_COMMISSION,
    tax_rate: float = TAX_RATE_DIVIDEND,
    cache: Optional[dict] = None,
) -> PortfolioShareCalc:
    """
    포트폴리오 전체 주수 기반 계산.

    Args:
        holdings: 추천 종목 리스트 (weight_pct 필드 필요)
        total_investment_manwon: 총 투자금 (만원)
    """
    if cache is None:
        cache = _load_cache()

    results = []
    warnings = []
    data_dates = []

    for h in holdings:
        ticker     = h.get("ticker", "")
        weight_pct = float(h.get("weight_pct") or 0)
        invest     = total_investment_manwon * weight_pct / 100.0

        # 국내 ETF (한국어 티커 등)는 현재 미지원
        if not ticker or not ticker.replace("-", "").isalnum():
            warnings.append(f"{ticker}: 비정형 티커 — 주수 계산 건너뜀")
            continue

        r = calc_share_based_for_ticker(
            ticker, invest, usd_krw, commission_rate, tax_rate, cache
        )
        if r is None:
            warnings.append(f"{ticker}: 캐시 없음 — yield% 방식 폴백 필요")
        else:
            if r.warning:
                warnings.append(f"{ticker}: {r.warning}")
            results.append(r)
            data_dates.append(r.data_date)

    total_annual  = sum(r.annual_div_after_tax_krw for r in results)
    total_monthly = sum(r.monthly_div_after_tax_manwon for r in results)
    eff_yield     = (total_annual / (total_investment_manwon * 10_000) * 100
                     if total_investment_manwon > 0 else 0)
    data_date     = max(data_dates) if data_dates else "unknown"

    return PortfolioShareCalc(
        total_investment_manwon=total_investment_manwon,
        total_annual_div_after_tax_manwon=round(total_annual / 10_000, 1),
        total_monthly_div_after_tax_manwon=round(total_monthly, 2),
        effective_yield_pct=round(eff_yield, 2),
        data_date=data_date,
        usd_krw=usd_krw,
        holdings=results,
        warnings=warnings,
    )


# ── 기존 yield% 방식과 비교 ───────────────────────────────────────
def compare_methods(
    ticker: str,
    investment_manwon: float,
    div_yield_pct: float,        # 기존 방식의 입력값
    usd_krw: float = DEFAULT_USD_KRW,
    cache: Optional[dict] = None,
) -> dict:
    """
    기존 배당률% 방식 vs 주수 기반 방식 비교.
    두 방식의 차이가 크면 계산 근거를 재확인해야 함.
    """
    # 기존 방식
    annual_old = investment_manwon * 10_000 * div_yield_pct / 100 * (1 - TAX_RATE_DIVIDEND)
    monthly_old_manwon = annual_old / 12 / 10_000

    # 주수 기반
    r = calc_share_based_for_ticker(ticker, investment_manwon, usd_krw, cache=cache)
    if r is None:
        return {"error": f"{ticker} 캐시 없음"}

    diff_pct = ((r.monthly_div_after_tax_manwon - monthly_old_manwon)
                / monthly_old_manwon * 100) if monthly_old_manwon else 0

    return {
        "ticker": ticker,
        "investment_manwon": investment_manwon,
        "method_yield_pct": {
            "input_yield_pct": div_yield_pct,
            "monthly_div_manwon": round(monthly_old_manwon, 2),
        },
        "method_share_based": {
            "price_usd": r.price_usd,
            "shares": r.shares,
            "annual_dps_usd": r.annual_dps_usd,
            "monthly_div_manwon": r.monthly_div_after_tax_manwon,
            "data_date": r.data_date,
        },
        "diff_pct": round(diff_pct, 1),
        "note": (
            "두 방식 일치" if abs(diff_pct) < 5
            else f"⚠️ {abs(diff_pct):.1f}% 차이 — 입력 수익률 재확인 필요"
        ),
    }

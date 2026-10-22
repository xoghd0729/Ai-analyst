"""
주수 기반 배당 계산 검증 테스트
================================
과거 캐시 데이터(2026-10-12 기준)로 계산 정확성 확인.
"""
import pytest
from utils.calc_share_based_dividend import (
    calc_share_based_for_ticker,
    calc_portfolio_share_based,
    compare_methods,
    calc_shares,
    calc_annual_dps,
    DEFAULT_USD_KRW,
)

# ── 픽스처: 테스트용 미니 캐시 (실제 캐시 없이 단위테스트) ──────────
MOCK_CACHE = {
    "PRU": {
        "ticker": "PRU", "name": "Prudential Financial",
        "price_usd": 113.09, "div_yield": 4.95,
        "fetched_at": "2026-10-12T20:21:16.538447",
    },
    "SCHD": {
        "ticker": "SCHD", "name": "Schwab US Dividend Equity ETF",
        "price_usd": 33.04, "div_yield": 3.24,
        "fetched_at": "2026-10-12T20:21:16.538447",
    },
    "PEP": {
        "ticker": "PEP", "name": "PepsiCo",
        "price_usd": 125.97, "div_yield": 4.70,
        "fetched_at": "2026-10-12T20:21:16.538447",
    },
}


class TestCalcShares:
    """매수 주수 계산 단위 테스트"""

    def test_basic(self):
        """1380만원 ÷ ($100 × 1380원 × 1.0025) = 약 99.75주"""
        shares = calc_shares(1380, 100.0, usd_krw=1380, commission_rate=0.0025)
        assert 99 < shares < 101

    def test_zero_price(self):
        assert calc_shares(100, 0, usd_krw=1380) == 0.0

    def test_no_fractional(self):
        shares = calc_shares(100, 50.0, usd_krw=1380, allow_fractional=False)
        assert isinstance(shares, int)


class TestCalcAnnualDPS:
    """연간 DPS 역산 테스트"""

    def test_pru(self):
        """PRU: $113.09 × 4.95% ≈ $5.60"""
        dps = calc_annual_dps(113.09, 4.95)
        assert 5.50 < dps < 5.70, f"PRU DPS 기대값 ~$5.60, 실제 {dps:.4f}"

    def test_zero_yield(self):
        assert calc_annual_dps(100.0, 0.0) == 0.0


class TestShareBasedTicker:
    """단일 종목 주수 기반 계산"""

    def test_pru_shares_and_dps(self):
        r = calc_share_based_for_ticker("PRU", 245.8, usd_krw=1380, cache=MOCK_CACHE)
        assert r is not None
        # 245.8만원 ÷ ($113.09 × 1380 × 1.0025) ≈ 15.7주
        assert 15.0 < r.shares < 16.5
        # DPS ≈ $5.60
        assert 5.50 < r.annual_dps_usd < 5.70
        # 월 세후 배당 > 0
        assert r.monthly_div_after_tax_manwon > 0

    def test_not_in_cache(self):
        r = calc_share_based_for_ticker("QYLD", 100, cache=MOCK_CACHE)
        assert r is None

    def test_data_date_recorded(self):
        r = calc_share_based_for_ticker("SCHD", 100, cache=MOCK_CACHE)
        assert r.data_date == "2026-10-12"


class TestPortfolioShareCalc:
    """포트폴리오 전체 계산"""

    def test_total_div_positive(self):
        holdings = [
            {"ticker": "PRU",  "weight_pct": 50},
            {"ticker": "SCHD", "weight_pct": 50},
        ]
        port = calc_portfolio_share_based(holdings, 1000, usd_krw=1380, cache=MOCK_CACHE)
        assert port.total_monthly_div_after_tax_manwon > 0
        assert port.effective_yield_pct > 0
        assert len(port.holdings) == 2

    def test_unknown_ticker_warned(self):
        holdings = [
            {"ticker": "UNKNOWN_XYZ", "weight_pct": 100},
        ]
        port = calc_portfolio_share_based(holdings, 1000, cache=MOCK_CACHE)
        assert len(port.warnings) > 0

    def test_weights_sum_100(self):
        """비중 합 100%일 때 합산 투자금이 총 투자금과 같아야 함"""
        holdings = [
            {"ticker": "PRU",  "weight_pct": 40},
            {"ticker": "SCHD", "weight_pct": 60},
        ]
        port = calc_portfolio_share_based(holdings, 500, usd_krw=1380, cache=MOCK_CACHE)
        total_invested = sum(h.investment_manwon for h in port.holdings)
        assert abs(total_invested - 500) < 1  # 1만원 오차 허용


class TestCompareMethods:
    """기존 방식 vs 주수 기반 비교"""

    def test_pru_diff_under_5pct(self):
        """같은 데이터 소스에서 두 방식 차이는 수수료 반영분 이내"""
        c = compare_methods("PRU", 245.8, 4.95, usd_krw=1380, cache=MOCK_CACHE)
        assert abs(c["diff_pct"]) < 5.0, f"5% 초과 차이: {c['diff_pct']}%"

    def test_schd_diff_under_5pct(self):
        c = compare_methods("SCHD", 255.7, 3.24, usd_krw=1380, cache=MOCK_CACHE)
        assert abs(c["diff_pct"]) < 5.0

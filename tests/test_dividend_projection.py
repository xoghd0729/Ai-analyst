"""
tests/test_dividend_projection.py
===================================
utils/dividend_projection.py — simulate_asset(), simulate_portfolio() 단위 테스트
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.dividend_projection import simulate_asset, simulate_portfolio


# ─── 공통 픽스처 ──────────────────────────────────────────────

def _make_recs(investable=5000):
    # simulate_portfolio는 invest_amount_만원 필드 필요
    return [
        {
            "ticker": "SCHD", "name": "SCHD ETF",
            "asset_class": "us_div_etf",
            "weight_pct": 60,
            "invest_amount_만원": investable * 0.6,
            "dividend_yield": 3.5,
            "net_yield_pct": 3.0,
            "div_growth_5y": 10.0,
        },
        {
            "ticker": "JEPI", "name": "JEPI ETF",
            "asset_class": "us_div_etf",
            "weight_pct": 40,
            "invest_amount_만원": investable * 0.4,
            "dividend_yield": 8.0,
            "net_yield_pct": 6.8,
            "div_growth_5y": 2.0,
        },
    ]


# ─── TestSimulateAsset ────────────────────────────────────────

class TestSimulateAsset:
    def setup_method(self):
        self.result = simulate_asset(
            name="SCHD ETF",
            asset_class="us_div_etf",
            invest_amount=3000,
            initial_yield=3.5,
            div_growth_rate=10.0,
            net_tax_rate=0.154,
            years=20,
            reinvest=False,
        )

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_required_keys_present(self):
        required = {
            "name", "asset_class", "initial_invest",
            "years", "annual_div", "annual_div_net",
            "monthly_div_net", "yield_on_cost",
        }
        assert required <= self.result.keys()

    def test_years_length(self):
        assert len(self.result["years"]) == 20
        assert self.result["years"][0] == 1
        assert self.result["years"][-1] == 20

    def test_annual_div_grows_over_time(self):
        divs = self.result["annual_div"]
        # 성장률 10% → 마지막 해가 첫 해보다 커야 함
        assert divs[-1] > divs[0]

    def test_annual_div_net_less_than_gross(self):
        gross = self.result["annual_div"]
        net   = self.result["annual_div_net"]
        for g, n in zip(gross, net):
            assert n <= g

    def test_monthly_div_is_annual_div_over_12(self):
        for month_net, annual_net in zip(
            self.result["monthly_div_net"],
            self.result["annual_div_net"]
        ):
            assert abs(month_net - annual_net / 12) < 0.1

    def test_yield_on_cost_grows_with_growth_rate(self):
        yoc = self.result["yield_on_cost"]
        assert yoc[-1] > yoc[0]

    def test_initial_invest_stored(self):
        assert self.result["initial_invest"] == 3000


# ─── TestSimulateAssetReinvest ────────────────────────────────

class TestSimulateAssetReinvest:
    def test_reinvest_increases_total_invested(self):
        no_reinvest = simulate_asset(
            "SCHD", "us_div_etf", 3000, 3.5, 10.0, 0.154, 20, reinvest=False
        )
        with_reinvest = simulate_asset(
            "SCHD", "us_div_etf", 3000, 3.5, 10.0, 0.154, 20, reinvest=True
        )
        assert with_reinvest["total_invested"] > no_reinvest["total_invested"]

    def test_reinvest_higher_final_div(self):
        no_reinvest = simulate_asset(
            "SCHD", "us_div_etf", 3000, 3.5, 10.0, 0.154, 20, reinvest=False
        )
        with_reinvest = simulate_asset(
            "SCHD", "us_div_etf", 3000, 3.5, 10.0, 0.154, 20, reinvest=True
        )
        assert with_reinvest["annual_div"][-1] > no_reinvest["annual_div"][-1]


# ─── TestSimulateAssetEdgeCases ───────────────────────────────

class TestSimulateAssetEdgeCases:
    def test_zero_growth_rate_flat(self):
        result = simulate_asset("X", "kr_stock", 1000, 5.0, 0.0, 0.154, 10, False)
        divs = result["annual_div"]
        # 성장률 0 → 모든 해 동일
        assert abs(divs[0] - divs[-1]) < 0.01

    def test_1_year_projection(self):
        result = simulate_asset("X", "kr_stock", 1000, 5.0, 5.0, 0.154, 1, False)
        assert len(result["years"]) == 1

    def test_zero_invest_raises(self):
        # invest_amount=0 이면 yoc 계산 시 ZeroDivisionError — 소스 코드 미guard
        import pytest
        with pytest.raises(ZeroDivisionError):
            simulate_asset("X", "us_div_etf", 0, 3.5, 5.0, 0.154, 10, False)


# ─── TestSimulatePortfolio ────────────────────────────────────

class TestSimulatePortfolio:
    def setup_method(self):
        self.recs = _make_recs()
        self.result = simulate_portfolio(
            recommendations=self.recs,
            investable_amount=5000,
            years=20,
            reinvest=False,
            monthly_target=30.0,
        )

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_required_keys(self):
        required = {
            "years", "monthly_div_gross", "monthly_div_net",
            "cumulative_div_net", "milestones",
        }
        assert required <= self.result.keys()

    def test_years_length(self):
        assert len(self.result["years"]) == 20

    def test_monthly_div_net_positive(self):
        for v in self.result["monthly_div_net"]:
            assert v >= 0

    def test_cumulative_div_increasing(self):
        cum = self.result["cumulative_div_net"]
        for i in range(1, len(cum)):
            assert cum[i] >= cum[i - 1]

    def test_milestones_has_target_key(self):
        milestones = self.result["milestones"]
        assert "target_achieved_year" in milestones or "target_만원" in milestones

    def test_asset_breakdown_present(self):
        assert "asset_breakdown" in self.result

    def test_portfolio_div_grows_over_time(self):
        net = self.result["monthly_div_net"]
        # 배당성장률 > 0이면 마지막 해가 첫 해보다 커야 함
        assert net[-1] > net[0]


# ─── TestSimulatePortfolioEdgeCases ──────────────────────────

class TestSimulatePortfolioEdgeCases:
    def test_empty_recs_no_crash(self):
        result = simulate_portfolio([], 5000, 20)
        assert isinstance(result, dict)

    def test_zero_investable(self):
        # invest_amount_만원=0인 recs → 자산 전부 스킵 → 빈 projection 반환
        zero_recs = [
            {"ticker": "SCHD", "asset_class": "us_div_etf",
             "invest_amount_만원": 0, "dividend_yield": 3.5, "div_growth_5y": 10.0}
        ]
        result = simulate_portfolio(zero_recs, 0, 10)
        assert isinstance(result, dict)

    def test_high_growth_rate_doubles(self):
        # 10% 성장률 → 7.2년 법칙상 20년 내 배당이 2배 이상
        recs = [
            {
                "ticker": "SCHD", "name": "SCHD",
                "asset_class": "us_div_etf",
                "weight_pct": 100,
                "invest_amount_만원": 5000,
                "dividend_yield": 3.5, "net_yield_pct": 3.0,
                "div_growth_5y": 10.0,
            }
        ]
        result = simulate_portfolio(recs, 5000, 20)
        net = result["monthly_div_net"]
        if len(net) >= 20:
            assert net[-1] >= net[0] * 2

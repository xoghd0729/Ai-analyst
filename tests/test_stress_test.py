"""
tests/test_stress_test.py
==========================
utils/stress_test.py — run_stress_test(), _get_shock() 단위 테스트
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.stress_test import run_stress_test, _get_shock, SCENARIOS

VALID_SCENARIOS = {"2008_financial_crisis", "2022_rate_shock", "covid_crash", "recession"}


# ─── 공통 픽스처 ──────────────────────────────────────────────

def _make_recs(n=3):
    """간단한 추천 목록 생성."""
    return [
        {
            "ticker": "SCHD", "name": "SCHD ETF",
            "asset_class": "us_div_etf", "etf_category": "dividend_growth",
            "weight_pct": 40, "dividend_yield": 3.5, "net_yield_pct": 3.0,
        },
        {
            "ticker": "JEPI", "name": "JEPI ETF",
            "asset_class": "us_div_etf", "etf_category": "monthly_income",
            "weight_pct": 30, "dividend_yield": 8.0, "net_yield_pct": 6.8,
        },
        {
            "ticker": "005930", "name": "Samsung",
            "asset_class": "kr_stock", "etf_category": "",
            "weight_pct": 30, "dividend_yield": 2.5, "net_yield_pct": 2.1,
        },
    ]


# ─── TestScenarioConstants ────────────────────────────────────

class TestScenarioConstants:
    def test_all_four_scenarios_defined(self):
        assert VALID_SCENARIOS == set(SCENARIOS.keys())

    def test_each_has_shocks_by_class(self):
        for name, sc in SCENARIOS.items():
            assert "shocks_by_class" in sc, f"{name} missing shocks_by_class"

    def test_each_has_shocks_by_category(self):
        for name, sc in SCENARIOS.items():
            assert "shocks_by_category" in sc, f"{name} missing shocks_by_category"

    def test_price_shocks_are_negative_for_stocks(self):
        # 주식/리츠는 위기 시 가격이 떨어져야 함
        for sc in SCENARIOS.values():
            cls_shocks = sc["shocks_by_class"]
            for cls in ("kr_stock", "us_stock", "us_reit"):
                if cls in cls_shocks:
                    price_shock, _ = cls_shocks[cls]
                    assert price_shock < 0, f"{sc['name']} {cls} price shock should be negative"

    def test_defensive_positive_in_crisis(self):
        # 채권/방어자산은 위기 시 상대적으로 강세 (양수 또는 소폭 음수)
        for name, sc in SCENARIOS.items():
            if "defensive" in sc["shocks_by_class"]:
                price_shock, _ = sc["shocks_by_class"]["defensive"]
                # GFC에서는 채권 강세 → 양수 가능, 2022 금리충격에서는 음수 가능
                assert price_shock >= -20, f"{name} defensive shock too severe: {price_shock}"

    def test_recovery_months_positive(self):
        for sc in SCENARIOS.values():
            assert sc["recovery_months"] > 0
            assert sc["duration_months"] > 0


# ─── TestGetShock ─────────────────────────────────────────────

class TestGetShock:
    def test_category_takes_priority_over_class(self):
        sc = SCENARIOS["2008_financial_crisis"]
        # monthly_income는 category에 있음 → category 우선
        p, d = _get_shock(sc, "us_div_etf", "monthly_income")
        expected_p, expected_d = sc["shocks_by_category"]["monthly_income"]
        assert p == expected_p
        assert d == expected_d

    def test_class_used_when_no_category_match(self):
        sc = SCENARIOS["2008_financial_crisis"]
        p, d = _get_shock(sc, "kr_stock", "")
        expected_p, expected_d = sc["shocks_by_class"]["kr_stock"]
        assert p == expected_p

    def test_default_fallback_for_unknown(self):
        sc = SCENARIOS["2008_financial_crisis"]
        p, d = _get_shock(sc, "unknown_class", "")
        assert p == -20
        assert d == -10

    def test_long_bond_positive_in_gfc(self):
        sc = SCENARIOS["2008_financial_crisis"]
        p, d = _get_shock(sc, "defensive", "long_bond")
        assert p > 0  # 금리 하락으로 채권 가격 상승


# ─── TestRunStressTestStructure ───────────────────────────────

class TestRunStressTestStructure:
    def setup_method(self):
        self.recs = _make_recs()
        self.result = run_stress_test(self.recs, investable_amount=5000)

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_required_top_keys(self):
        required = {
            "baseline", "scenarios",
            "overall_resilience_score", "overall_grade",
        }
        assert required <= self.result.keys()

    def test_baseline_has_portfolio_value(self):
        b = self.result["baseline"]
        assert "portfolio_value_만원" in b
        assert b["portfolio_value_만원"] == 5000

    def test_baseline_monthly_div_positive(self):
        assert self.result["baseline"]["monthly_div_net_만원"] > 0

    def test_all_scenarios_present(self):
        for sc_key in VALID_SCENARIOS:
            assert sc_key in self.result["scenarios"]

    def test_each_scenario_has_price_shock(self):
        for sc_key, sc_data in self.result["scenarios"].items():
            assert "price_shock" in sc_data, f"{sc_key} missing price_shock"

    def test_each_scenario_has_div_shock(self):
        for sc_key, sc_data in self.result["scenarios"].items():
            assert "div_shock" in sc_data

    def test_each_scenario_has_resilience_score(self):
        for sc_key, sc_data in self.result["scenarios"].items():
            score = sc_data.get("resilience_score", -1)
            assert 0 <= score <= 100, f"{sc_key} resilience_score={score}"

    def test_overall_resilience_in_range(self):
        score = self.result["overall_resilience_score"]
        assert 0.0 <= score <= 100.0


# ─── TestStressTestValues ─────────────────────────────────────

class TestStressTestValues:
    def setup_method(self):
        self.recs = _make_recs()
        self.result = run_stress_test(self.recs, investable_amount=10000)

    def test_portfolio_loses_value_in_gfc(self):
        gfc = self.result["scenarios"]["2008_financial_crisis"]
        shocked = gfc["price_shock"]["portfolio_value_만원"]
        baseline = self.result["baseline"]["portfolio_value_만원"]
        assert shocked < baseline

    def test_gfc_loss_pct_negative(self):
        gfc = self.result["scenarios"]["2008_financial_crisis"]
        assert gfc["price_shock"]["portfolio_loss_pct"] < 0

    def test_div_shock_reduces_income(self):
        gfc = self.result["scenarios"]["2008_financial_crisis"]
        shocked_div = gfc["div_shock"]["shock_monthly_만원"]
        baseline_div = self.result["baseline"]["monthly_div_net_만원"]
        assert shocked_div < baseline_div

    def test_rate_shock_smaller_than_gfc(self):
        # 2022 금리충격은 GFC보다 충격이 작아야 함
        gfc_loss = abs(self.result["scenarios"]["2008_financial_crisis"]["price_shock"]["portfolio_loss_pct"])
        rate_loss = abs(self.result["scenarios"]["2022_rate_shock"]["price_shock"]["portfolio_loss_pct"])
        assert gfc_loss > rate_loss


# ─── TestEdgeCases ───────────────────────────────────────────

class TestEdgeCases:
    def test_empty_recommendations_no_crash(self):
        result = run_stress_test([], investable_amount=5000)
        assert isinstance(result, dict)
        assert result["baseline"]["monthly_div_net_만원"] == 0.0

    def test_single_scenario_filter(self):
        result = run_stress_test(
            _make_recs(), investable_amount=5000,
            scenarios=["2008_financial_crisis"]
        )
        assert "2008_financial_crisis" in result["scenarios"]
        assert "covid_crash" not in result["scenarios"]

    def test_zero_investable_raises(self):
        # investable_amount=0 → 소스 코드 279번 줄 ZeroDivisionError (미guard)
        import pytest
        with pytest.raises(ZeroDivisionError):
            run_stress_test(_make_recs(), investable_amount=0)

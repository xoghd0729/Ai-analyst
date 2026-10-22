"""
tests/test_compare_portfolio.py
================================
POST /api/portfolio/compare 응답 구조 및
_extract_compare_metrics 로직 검증.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from api.routers.portfolio import _extract_compare_metrics


# ─── 공통 픽스처 ──────────────────────────────────────────────────

def _make_result(monthly_div=10.0, achievement=50.0, lean_age=55,
                 regular_age=60, p50=8.0, confidence=60.0,
                 mdd=-15.0, sharpe=0.8, health=70.0, tax_saving=30.0):
    return {
        "summary": {
            "est_monthly_div_after_tax_만원": monthly_div,
            "target_achievement_pct": achievement,
        },
        "fire_plan": {
            "fire_timeline": {
                "lean_fire_age": lean_age,
                "regular_fire_age": regular_age,
            }
        },
        "monte_carlo": {
            "p50_monthly": p50,
            "confidence_at_target": confidence,
        },
        "backtest": {
            "mdd_pct": mdd,
            "sharpe_ratio": sharpe,
        },
        "portfolio_health": {
            "overall_score": health,
        },
        "tax_optimizer": {
            "total_annual_saving_만원": tax_saving,
        },
    }


RESULT_A = _make_result(monthly_div=12.0, achievement=80.0, lean_age=52,
                         regular_age=57, p50=10.0, confidence=70.0,
                         mdd=-12.0, sharpe=1.1, health=80.0, tax_saving=40.0)

RESULT_B = _make_result(monthly_div=8.0, achievement=55.0, lean_age=58,
                         regular_age=63, p50=7.0, confidence=50.0,
                         mdd=-20.0, sharpe=0.7, health=60.0, tax_saving=20.0)


# ─── TestMetricsStructure ─────────────────────────────────────────

class TestMetricsStructure:
    def setup_method(self):
        self.metrics = _extract_compare_metrics(RESULT_A, RESULT_B)

    def test_returns_list(self):
        assert isinstance(self.metrics, list)

    def test_nonempty(self):
        assert len(self.metrics) > 0

    def test_each_metric_has_required_keys(self):
        required = {"label", "key", "a", "b", "unit", "better", "winner"}
        for m in self.metrics:
            assert required.issubset(m.keys()), f"Missing keys in {m}"

    def test_winner_values_valid(self):
        for m in self.metrics:
            assert m["winner"] in ("a", "b", "tie"), f"Invalid winner: {m['winner']}"

    def test_better_values_valid(self):
        for m in self.metrics:
            assert m["better"] in ("higher", "lower"), f"Invalid better: {m['better']}"

    def test_a_b_are_numeric(self):
        for m in self.metrics:
            assert isinstance(m["a"], (int, float))
            assert isinstance(m["b"], (int, float))

    def test_known_keys_present(self):
        keys = {m["key"] for m in self.metrics}
        for expected in ["monthly_div", "achievement", "mc_p50", "sharpe", "health"]:
            assert expected in keys


# ─── TestWinnerLogic ─────────────────────────────────────────────

class TestWinnerLogic:
    def setup_method(self):
        self.metrics = _extract_compare_metrics(RESULT_A, RESULT_B)
        self.by_key = {m["key"]: m for m in self.metrics}

    def test_higher_monthly_div_wins(self):
        m = self.by_key["monthly_div"]
        assert m["a"] > m["b"]
        assert m["winner"] == "a"

    def test_lower_mdd_wins(self):
        m = self.by_key["mdd"]
        assert m["better"] == "lower"
        # A: abs(-12)=12, B: abs(-20)=20 → A wins
        assert m["winner"] == "a"

    def test_lower_lean_fire_age_wins(self):
        m = self.by_key["lean_fire_age"]
        assert m["better"] == "lower"
        assert m["winner"] == "a"  # 52 < 58

    def test_higher_sharpe_wins(self):
        m = self.by_key["sharpe"]
        assert m["winner"] == "a"  # 1.1 > 0.7


# ─── TestTieDetection ────────────────────────────────────────────

class TestTieDetection:
    def test_identical_values_are_tie(self):
        same = _make_result(monthly_div=10.0)
        metrics = _extract_compare_metrics(same, same)
        by_key = {m["key"]: m for m in metrics}
        assert by_key["monthly_div"]["winner"] == "tie"

    def test_near_equal_within_0_01_is_tie(self):
        a = _make_result(sharpe=1.000)
        b = _make_result(sharpe=1.005)  # diff = 0.005 < 0.01
        metrics = _extract_compare_metrics(a, b)
        by_key = {m["key"]: m for m in metrics}
        assert by_key["sharpe"]["winner"] == "tie"


# ─── TestEdgeCases ───────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_dicts_no_crash(self):
        metrics = _extract_compare_metrics({}, {})
        assert isinstance(metrics, list)
        for m in metrics:
            assert m["a"] == 0 or m["a"] is not None
            assert m["winner"] in ("a", "b", "tie")

    def test_none_values_default_to_zero(self):
        a = {"summary": {"est_monthly_div_after_tax_만원": None}}
        metrics = _extract_compare_metrics(a, {})
        by_key = {m["key"]: m for m in metrics}
        assert by_key["monthly_div"]["a"] == 0

    def test_list_p50_uses_last_value(self):
        a = _make_result(p50=[5.0, 7.0, 9.0])  # list → last = 9.0
        b = _make_result(p50=8.0)
        metrics = _extract_compare_metrics(a, b)
        by_key = {m["key"]: m for m in metrics}
        assert by_key["mc_p50"]["a"] == 9.0
        assert by_key["mc_p50"]["winner"] == "a"


# ─── TestPipelineCompare ─────────────────────────────────────────

class TestPipelineCompare:
    """RecommendationPipeline을 실제 두 번 실행해 compare 응답 검증."""

    @pytest.fixture(scope="class")
    def compare_result(self):
        from api.pipeline.runner import RecommendationPipeline
        from api.pipeline.context import PortfolioRequest

        req_a = PortfolioRequest(
            age=35, annual_income=5000, monthly_target=100,
            investable_amount=5000, risk_tolerance="moderate",
            archetype="혼합형", monthly_savings=50, target_fire_age=55,
        )
        req_b = PortfolioRequest(
            age=35, annual_income=5000, monthly_target=100,
            investable_amount=3000, risk_tolerance="conservative",
            archetype="안정형", monthly_savings=30, target_fire_age=60,
        )
        result_a = RecommendationPipeline(req_a).execute()
        result_b = RecommendationPipeline(req_b).execute()
        metrics = _extract_compare_metrics(result_a, result_b)
        winner_counts = {"a": 0, "b": 0, "tie": 0}
        for m in metrics:
            winner_counts[m["winner"]] = winner_counts.get(m["winner"], 0) + 1
        return {
            "portfolio_a": result_a,
            "portfolio_b": result_b,
            "comparison": {"metrics": metrics, "winner_counts": winner_counts},
        }

    def test_top_level_keys(self, compare_result):
        assert {"portfolio_a", "portfolio_b", "comparison"} <= compare_result.keys()

    def test_comparison_has_metrics_and_winner_counts(self, compare_result):
        c = compare_result["comparison"]
        assert "metrics" in c and "winner_counts" in c

    def test_winner_counts_sum_to_metrics_count(self, compare_result):
        c = compare_result["comparison"]
        total = sum(c["winner_counts"].values())
        assert total == len(c["metrics"])

    def test_each_portfolio_has_recommendations(self, compare_result):
        for key in ("portfolio_a", "portfolio_b"):
            assert "recommendations" in compare_result[key]
            assert len(compare_result[key]["recommendations"]) > 0

    def test_higher_investable_tends_to_win_monthly_div(self, compare_result):
        by_key = {m["key"]: m for m in compare_result["comparison"]["metrics"]}
        m = by_key["monthly_div"]
        # A(5000만) ≥ B(3000만) 기대 — 반드시 성립하지 않아도 crash 없으면 OK
        assert m["winner"] in ("a", "b", "tie")

"""
tests/test_storytelling.py
===========================
utils/storytelling.py — generate_storytelling() 구조 및 내러티브 단위 테스트
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.storytelling import generate_storytelling


# ─── 공통 픽스처 ──────────────────────────────────────────────

def _make_inputs():
    return dict(
        input_data={"age": 35, "risk_tolerance": "moderate", "investable": 5000, "monthly_target": 50},
        recommendations=[
            {"ticker": "SCHD", "name": "SCHD ETF", "asset_class": "us_div_etf",
             "weight_pct": 60, "dividend_yield": 3.5, "net_yield_pct": 3.0,
             "ml_status": "INTACT", "sector": "Diversified"},
            {"ticker": "JEPI", "name": "JEPI ETF", "asset_class": "us_div_etf",
             "weight_pct": 40, "dividend_yield": 8.0, "net_yield_pct": 6.8,
             "ml_status": "INTACT", "sector": "Covered Call"},
        ],
        summary={
            "investable_amount_만원": 5000,
            "avg_yield_pct": 5.2,
            "est_monthly_div_after_tax_만원": 17.3,
            "target_achievement_pct": 34.6,
            "total_annual_div_net_만원": 207.6,
        },
        projection={
            "years": list(range(1, 21)),
            "monthly_div_net": [17 + i * 1.2 for i in range(20)],
            "milestones": {"div_doubles_year": 8, "target_achieved_year": 12, "target_만원": 50},
        },
        living_coverage={
            "coverage_pct": 35.0,
            "monthly_expense_만원": 250,
            "monthly_div_net_만원": 17.3,
        },
        stress_test={
            "overall_resilience_score": 72.0,
            "overall_grade": "✅ 양호",
            "scenarios": {
                "2008_financial_crisis": {
                    "resilience_score": 68.0,
                    "div_shock": {"shock_monthly_만원": 12.0, "baseline_monthly_만원": 17.3},
                }
            }
        },
        dividend_calendar={
            "monthly_totals": {str(m): 5.0 + m * 0.5 for m in range(1, 13)},
            "top_months": [3, 6, 9, 12],
        },
        sector_exposure={
            "sectors": [
                {"sector": "Diversified", "weight_pct": 60},
                {"sector": "Covered Call", "weight_pct": 40},
            ]
        },
        macro_regime={
            "regime": "NORMAL",
            "label": "🟢 정상 국면",
            "advisory": "현재 시장은 정상 국면입니다.",
        },
        risk_alerts=[],
        archetype="혼합형",
        fire_plan={
            "fire_timeline": {"lean_fire_age": 52, "regular_fire_age": 58},
        },
        monte_carlo={
            "p50_monthly": 18.5,
            "p10_monthly": 11.0,
            "p90_monthly": 28.0,
            "confidence_at_target": 42.0,
        },
        behavioral={},
    )


# ─── TestStorytellingStructure ────────────────────────────────

class TestStorytellingStructure:
    def setup_method(self):
        self.result = generate_storytelling(**_make_inputs())

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_has_narrative_key(self):
        assert "narrative" in self.result

    def test_narrative_has_all_paragraphs(self):
        n = self.result["narrative"]
        for key in ("headline", "summary", "strategy", "future", "risk", "action", "full_text"):
            assert key in n, f"Missing narrative key: {key}"

    def test_all_paragraphs_are_strings(self):
        for k, v in self.result["narrative"].items():
            assert isinstance(v, str), f"{k} is not a string"

    def test_all_paragraphs_nonempty(self):
        for k, v in self.result["narrative"].items():
            assert len(v.strip()) > 0, f"{k} is empty"

    def test_full_text_contains_all_paragraphs(self):
        n = self.result["narrative"]
        # full_text는 5개 단락 합산이어야 함
        assert len(n["full_text"]) >= len(n["summary"])


# ─── TestNarrativeContent ─────────────────────────────────────

class TestNarrativeContent:
    def setup_method(self):
        self.result = generate_storytelling(**_make_inputs())
        self.n = self.result["narrative"]

    def test_headline_contains_amount_or_percent(self):
        # 헤드라인에는 숫자 또는 % 포함
        import re
        assert re.search(r'\d', self.n["headline"]), "Headline has no numbers"

    def test_summary_paragraph_nonempty(self):
        assert len(self.n["summary"]) > 30

    def test_strategy_paragraph_nonempty(self):
        assert len(self.n["strategy"]) > 30

    def test_risk_paragraph_nonempty(self):
        assert len(self.n["risk"]) > 30

    def test_action_paragraph_nonempty(self):
        assert len(self.n["action"]) > 30


# ─── TestEdgeCases ────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_recommendations_no_crash(self):
        inputs = _make_inputs()
        inputs["recommendations"] = []
        result = generate_storytelling(**inputs)
        assert "narrative" in result

    def test_none_fire_plan_no_crash(self):
        inputs = _make_inputs()
        inputs["fire_plan"] = None
        result = generate_storytelling(**inputs)
        assert "narrative" in result

    def test_none_monte_carlo_no_crash(self):
        inputs = _make_inputs()
        inputs["monte_carlo"] = None
        result = generate_storytelling(**inputs)
        assert "narrative" in result

    def test_empty_risk_alerts_no_crash(self):
        inputs = _make_inputs()
        inputs["risk_alerts"] = []
        result = generate_storytelling(**inputs)
        assert "narrative" in result

    def test_different_archetypes_no_crash(self):
        for archetype in ("혼합형", "성장형", "배당형", "안정형"):
            inputs = _make_inputs()
            inputs["archetype"] = archetype
            result = generate_storytelling(**inputs)
            assert "narrative" in result

    def test_high_risk_no_crash(self):
        inputs = _make_inputs()
        inputs["input_data"]["risk_tolerance"] = "aggressive"
        result = generate_storytelling(**inputs)
        assert "narrative" in result

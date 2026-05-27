"""
tests/test_monte_carlo.py — Monte Carlo 시뮬레이션 단위 테스트

왜 이 테스트가 필요한가?
  run_monte_carlo()의 핵심 보장:
  1. P10 < P50 < P90 순서가 항상 유지되어야 한다 (분위수 단조성)
  2. macro_regime이 "경기침체기"면 P10이 낮아져야 한다 (레짐 연동 효과)
  3. 빈 포트폴리오 입력에도 폭발 없이 빈 결과 반환
  4. seed 고정 시 재현성 보장

실행:
  pytest tests/test_monte_carlo.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.monte_carlo import run_monte_carlo


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 데이터
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_RECS = [
    {
        "ticker": "SCHD",
        "asset_class": "us_etf",
        "etf_category": "dividend_etf",
        "dividend_yield": 3.5,
        "invest_amount_만원": 3_000,
        "tax_rate_eff_pct": 15.4,
        "div_growth_5y": 9.0,
    },
    {
        "ticker": "JEPI",
        "asset_class": "us_etf",
        "etf_category": "covered_call_etf",
        "dividend_yield": 7.2,
        "invest_amount_만원": 2_000,
        "tax_rate_eff_pct": 15.4,
        "div_growth_5y": 2.0,
    },
]

RECESSION_MACRO = {
    "regime": "경기침체기",
    "confidence": 0.8,
}

GROWTH_MACRO = {
    "regime": "안정성장기",
    "confidence": 0.8,
}


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base_mc():
    return run_monte_carlo(
        recommendations=SAMPLE_RECS,
        investable_amount=5_000,
        years=20,
        n_simulations=500,
        monthly_target=15.0,
        seed=42,
    )

@pytest.fixture
def recession_mc():
    return run_monte_carlo(
        recommendations=SAMPLE_RECS,
        investable_amount=5_000,
        years=20,
        n_simulations=500,
        seed=42,
        macro_regime=RECESSION_MACRO,
    )

@pytest.fixture
def growth_mc():
    return run_monte_carlo(
        recommendations=SAMPLE_RECS,
        investable_amount=5_000,
        years=20,
        n_simulations=500,
        seed=42,
        macro_regime=GROWTH_MACRO,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 반환 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestReturnStructure:
    def test_required_keys_present(self, base_mc):
        required = {
            "p10_monthly", "p50_monthly", "p90_monthly", "years",
            "p50_final", "p10_final", "p90_final",
            "confidence_at_target", "prob_doubles",
            "expected_cut_events", "summary_message", "n_simulations",
        }
        missing = required - set(base_mc.keys())
        assert not missing, f"누락 키: {missing}"

    def test_years_list_length(self, base_mc):
        """years 리스트 길이 == 시뮬레이션 기간"""
        assert len(base_mc["years"]) == 20

    def test_p_series_length_matches_years(self, base_mc):
        """P10/P50/P90 시리즈 길이 == years"""
        assert len(base_mc["p10_monthly"]) == 20
        assert len(base_mc["p50_monthly"]) == 20
        assert len(base_mc["p90_monthly"]) == 20

    def test_n_simulations_recorded(self, base_mc):
        assert base_mc["n_simulations"] == 500

    def test_summary_message_is_string(self, base_mc):
        assert isinstance(base_mc["summary_message"], str)
        assert len(base_mc["summary_message"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 분위수 단조성 (핵심 불변식)
# ─────────────────────────────────────────────────────────────────────────────

class TestQuantileOrdering:
    def test_p10_less_than_p50_every_year(self, base_mc):
        """P10 ≤ P50 이 모든 연도에서 성립해야 한다"""
        for yr, (p10, p50) in enumerate(zip(base_mc["p10_monthly"], base_mc["p50_monthly"]), 1):
            assert p10 <= p50 + 0.01, \
                f"Year {yr}: P10({p10:.2f}) > P50({p50:.2f}) — 분위수 역전"

    def test_p50_less_than_p90_every_year(self, base_mc):
        """P50 ≤ P90 이 모든 연도에서 성립해야 한다"""
        for yr, (p50, p90) in enumerate(zip(base_mc["p50_monthly"], base_mc["p90_monthly"]), 1):
            assert p50 <= p90 + 0.01, \
                f"Year {yr}: P50({p50:.2f}) > P90({p90:.2f}) — 분위수 역전"

    def test_final_values_ordering(self, base_mc):
        """최종값도 P10 ≤ P50 ≤ P90"""
        assert base_mc["p10_final"] <= base_mc["p50_final"] + 0.01
        assert base_mc["p50_final"] <= base_mc["p90_final"] + 0.01

    def test_all_monthly_values_positive(self, base_mc):
        """모든 월 배당값은 0 이상"""
        for v in base_mc["p10_monthly"] + base_mc["p50_monthly"] + base_mc["p90_monthly"]:
            assert v >= 0, f"음수 월 배당 발생: {v}"


# ─────────────────────────────────────────────────────────────────────────────
# 확률값 범위 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestProbabilityBounds:
    def test_confidence_at_target_in_range(self, base_mc):
        """달성 확률은 0~100% 사이"""
        c = base_mc["confidence_at_target"]
        assert 0.0 <= c <= 1.0 or 0.0 <= c <= 100.0, \
            f"달성 확률이 범위 초과: {c}"

    def test_prob_doubles_in_range(self, base_mc):
        """2배 달성 확률은 0~1 또는 0~100 사이"""
        p = base_mc["prob_doubles"]
        assert 0.0 <= p <= 100.0, f"prob_doubles 범위 초과: {p}"

    def test_expected_cut_events_non_negative(self, base_mc):
        """배당컷 예상 횟수는 0 이상"""
        assert base_mc["expected_cut_events"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Macro Regime 연동 효과
# ─────────────────────────────────────────────────────────────────────────────

class TestMacroRegimeEffect:
    def test_recession_increases_cut_events(self, base_mc, recession_mc):
        """경기침체기에서는 배당컷 발생 횟수가 더 많아야 한다"""
        assert recession_mc["expected_cut_events"] >= base_mc["expected_cut_events"], \
            f"경기침체기 컷이 기본보다 적음: {recession_mc['expected_cut_events']} < {base_mc['expected_cut_events']}"

    def test_recession_lowers_p10_vs_growth(self, recession_mc, growth_mc):
        """경기침체기 P10이 안정성장기 P10보다 낮거나 같아야 한다 (20년 평균 기준)"""
        avg_p10_recession = sum(recession_mc["p10_monthly"]) / len(recession_mc["p10_monthly"])
        avg_p10_growth    = sum(growth_mc["p10_monthly"])    / len(growth_mc["p10_monthly"])
        assert avg_p10_recession <= avg_p10_growth + 0.5, \
            f"경기침체기 P10 평균({avg_p10_recession:.2f})이 안정성장기({avg_p10_growth:.2f})보다 높음"

    def test_macro_none_still_works(self):
        """macro_regime=None이어도 정상 동작 (기본값 사용)"""
        result = run_monte_carlo(
            recommendations=SAMPLE_RECS,
            investable_amount=5_000,
            years=10,
            n_simulations=100,
            seed=0,
            macro_regime=None,
        )
        assert "p50_monthly" in result
        assert len(result["p50_monthly"]) == 10

    def test_high_confidence_amplifies_regime_effect(self):
        """confidence=1.0이면 레짐 효과 최대"""
        low_conf_mc = run_monte_carlo(
            SAMPLE_RECS, 5_000, years=20, n_simulations=300, seed=42,
            macro_regime={"regime": "경기침체기", "confidence": 0.1},
        )
        high_conf_mc = run_monte_carlo(
            SAMPLE_RECS, 5_000, years=20, n_simulations=300, seed=42,
            macro_regime={"regime": "경기침체기", "confidence": 1.0},
        )
        # 높은 confidence → 더 많은 배당컷
        assert high_conf_mc["expected_cut_events"] >= low_conf_mc["expected_cut_events"]


# ─────────────────────────────────────────────────────────────────────────────
# 재현성 및 엣지 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestReproducibilityAndEdgeCases:
    def test_same_seed_produces_same_result(self):
        """동일한 seed → 동일한 결과 (재현성)"""
        r1 = run_monte_carlo(SAMPLE_RECS, 5_000, years=10, n_simulations=200, seed=99)
        r2 = run_monte_carlo(SAMPLE_RECS, 5_000, years=10, n_simulations=200, seed=99)
        assert r1["p50_final"] == r2["p50_final"], "seed 동일한데 결과 불일치"

    def test_different_seed_different_result(self):
        """다른 seed → 결과가 달라야 한다 (확률적 성질)"""
        r1 = run_monte_carlo(SAMPLE_RECS, 5_000, years=20, n_simulations=500, seed=1)
        r2 = run_monte_carlo(SAMPLE_RECS, 5_000, years=20, n_simulations=500, seed=9999)
        # 정확히 같을 확률은 극히 낮다
        assert r1["p50_final"] != r2["p50_final"]

    def test_empty_recommendations_returns_empty(self):
        """빈 추천 목록 → 빈 결과 (예외 없이)"""
        result = run_monte_carlo([], 5_000, years=20, n_simulations=100, seed=42)
        assert "p50_monthly" in result
        # 빈 결과이므로 모두 0
        assert all(v == 0 for v in result.get("p50_monthly", [0]))

    def test_zero_invest_amount_no_crash(self):
        """모든 invest_amount=0 → 빈 결과 (예외 없이)"""
        zero_recs = [{**r, "invest_amount_만원": 0} for r in SAMPLE_RECS]
        result = run_monte_carlo(zero_recs, 5_000, years=10, n_simulations=50, seed=0)
        assert "p50_monthly" in result

    def test_longer_horizon_higher_p90(self, base_mc):
        """더 긴 기간일수록 P90 최종값이 높아야 한다 (성장 복리 효과)"""
        short_mc = run_monte_carlo(SAMPLE_RECS, 5_000, years=5,  n_simulations=300, seed=42)
        long_mc  = run_monte_carlo(SAMPLE_RECS, 5_000, years=30, n_simulations=300, seed=42)
        assert long_mc["p90_final"] > short_mc["p90_final"], \
            "장기 시뮬레이션 P90이 단기보다 낮음"

    def test_single_asset_no_crash(self):
        """자산 1개 포트폴리오도 정상 동작"""
        result = run_monte_carlo(
            [SAMPLE_RECS[0]], 3_000, years=10, n_simulations=100, seed=7
        )
        assert len(result["p50_monthly"]) == 10

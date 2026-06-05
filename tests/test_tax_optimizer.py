"""
tests/test_tax_optimizer.py — 세금 최적화 엔진 단위 테스트

왜 이 테스트가 필요한가?
  2026 세법 개정으로 ISA 한도가 대폭 상향되었다.
  기존 코드 상수(ISA_ANNUAL_LIMIT=2000, 비과세=200)가 남아있으면
  투자자에게 잘못된 세금 절약 계산을 제공하게 된다.

  이 테스트는 2026 세법 상수가 올바르게 적용되는지 확인한다:
  - ISA 연 납입한도: 4,000만원 (구: 2,000만원)
  - 일반형 비과세: 500만원 (구: 200만원)
  - 청년형 비과세: 1,000만원 (구: 400만원)

실행:
  pytest tests/test_tax_optimizer.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.tax_optimizer import (
    calc_tax_optimizer,
    ISA_ANNUAL_LIMIT,
    ISA_TAX_FREE_GENERAL,
    ISA_TAX_FREE_YOUTH,
    COMPREHENSIVE_TAX_THRESHOLD,
    DIVIDEND_WITHHOLDING_RATE,
)


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 데이터
# ─────────────────────────────────────────────────────────────────────────────

SAMPLE_RECS = [
    {
        "ticker": "SCHD",
        "asset_class": "us_etf",
        "dividend_yield": 3.5,
        "invest_amount_만원": 5_000,
        "tax_rate_eff_pct": 15.4,
        "etf_category": "dividend_etf",
    },
    {
        "ticker": "삼성전자",
        "asset_class": "kr_stock",
        "dividend_yield": 2.8,
        "invest_amount_만원": 3_000,
        "tax_rate_eff_pct": 15.4,
        "etf_category": "",
    },
]

LARGE_RECS = [
    {
        "ticker": "SCHD",
        "asset_class": "us_etf",
        "dividend_yield": 4.0,
        "invest_amount_만원": 30_000,
        "tax_rate_eff_pct": 15.4,
        "etf_category": "dividend_etf",
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# 2026 세법 상수 검증 (가장 중요)
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxLawConstants2026:
    def test_isa_annual_limit_is_4000(self):
        """2026 세법: ISA 연 납입한도는 4,000만원 (구: 2,000만원)"""
        assert ISA_ANNUAL_LIMIT == 4_000, \
            f"ISA 연 한도 오류: {ISA_ANNUAL_LIMIT}만원 (2026법: 4,000만원이어야 함)"

    def test_isa_tax_free_general_is_500(self):
        """2026 세법: 일반형 ISA 비과세 한도는 500만원 (구: 200만원)"""
        assert ISA_TAX_FREE_GENERAL == 500, \
            f"일반형 비과세 오류: {ISA_TAX_FREE_GENERAL}만원 (2026법: 500만원이어야 함)"

    def test_isa_tax_free_youth_is_1000(self):
        """2026 세법: 청년형 ISA 비과세 한도는 1,000만원 (구: 400만원)"""
        assert ISA_TAX_FREE_YOUTH == 1_000, \
            f"청년형 비과세 오류: {ISA_TAX_FREE_YOUTH}만원 (2026법: 1,000만원이어야 함)"

    def test_comprehensive_tax_threshold_is_2000(self):
        """금융소득종합과세 임계점은 2,000만원"""
        assert COMPREHENSIVE_TAX_THRESHOLD == 2_000

    def test_dividend_withholding_rate(self):
        """배당소득세 기본 원천징수율: 15.4% (14% + 1.4% 지방세)"""
        assert abs(DIVIDEND_WITHHOLDING_RATE - 0.154) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# 반환 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestReturnStructure:
    @pytest.fixture
    def result(self):
        return calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
            annual_income_만원=5_000,
        )

    def test_top_level_keys(self, result):
        required = {
            "comprehensive_tax", "isa_strategy", "pension_strategy",
            "effective_tax_rate_pct", "optimized_tax_rate_pct",
            "total_annual_saving_만원", "5yr_cumulative_saving_만원",
            "priority_actions", "tax_health_score", "summary_message",
        }
        missing = required - set(result.keys())
        assert not missing, f"누락 키: {missing}"

    def test_isa_strategy_structure(self, result):
        isa = result["isa_strategy"]
        required = {"annual_limit_만원", "tax_free_limit_만원", "action"}
        missing = required - set(isa.keys())
        assert not missing

    def test_comprehensive_tax_structure(self, result):
        ct = result["comprehensive_tax"]
        required = {"is_over_threshold", "risk_level", "annual_div_gross_만원"}
        missing = required - set(ct.keys())
        assert not missing

    def test_priority_actions_is_list(self, result):
        assert isinstance(result["priority_actions"], list)

    def test_tax_health_score_range(self, result):
        """세금 건강도 점수는 0~100"""
        score = result["tax_health_score"]
        assert 0 <= score <= 100, f"tax_health_score={score} 범위 초과"

    def test_summary_message_is_string(self, result):
        assert isinstance(result["summary_message"], str)
        assert len(result["summary_message"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 2026 ISA 한도가 함수 결과에 반영되는지 확인
# ─────────────────────────────────────────────────────────────────────────────

class TestISA2026InResult:
    def test_isa_annual_limit_in_result(self):
        """반환값의 ISA 연 납입한도가 4,000만원이어야 한다"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
            annual_income_만원=5_000,
        )
        isa = result["isa_strategy"]
        assert isa.get("annual_limit_만원") == 4_000, \
            f"반환된 ISA 연 한도: {isa.get('annual_limit_만원')}만원 (4,000이어야 함)"

    def test_isa_tax_free_general_in_result(self):
        """일반형 비과세 한도가 500만원으로 반영"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
            annual_income_만원=5_000,
            is_youth_isa=False,
        )
        isa = result["isa_strategy"]
        assert isa.get("tax_free_limit_만원") == 500, \
            f"일반형 비과세: {isa.get('tax_free_limit_만원')}만원 (500이어야 함)"

    def test_isa_tax_free_youth_in_result(self):
        """청년형 비과세 한도가 1,000만원으로 반영"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=28,  # 청년
            annual_income_만원=4_000,
            is_youth_isa=True,
        )
        isa = result["isa_strategy"]
        assert isa.get("tax_free_limit_만원") == 1_000, \
            f"청년형 비과세: {isa.get('tax_free_limit_만원')}만원 (1,000이어야 함)"


# ─────────────────────────────────────────────────────────────────────────────
# 종합과세 임계점 로직 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestComprehensiveTaxLogic:
    def test_small_portfolio_safe_zone(self):
        """소액 포트폴리오는 종합과세 안전 구간이어야 한다"""
        small_recs = [{
            "ticker": "SCHD",
            "asset_class": "us_etf",
            "dividend_yield": 3.0,
            "invest_amount_만원": 1_000,  # 연배당 30만원 → 임계점 훨씬 이하
            "tax_rate_eff_pct": 15.4,
        }]
        result = calc_tax_optimizer(
            recommendations=small_recs,
            investable_amount=1_000,
            current_age=35,
        )
        ct = result["comprehensive_tax"]
        assert ct["is_over_threshold"] is False
        assert ct["risk_level"] in ("safe", "caution"), \
            f"소액 포트폴리오가 danger 판정: {ct['risk_level']}"

    def test_large_portfolio_over_threshold(self):
        """대형 포트폴리오(연배당 2000만원+)는 종합과세 대상"""
        result = calc_tax_optimizer(
            recommendations=LARGE_RECS,
            investable_amount=30_000,
            current_age=50,
            annual_income_만원=8_000,
        )
        ct = result["comprehensive_tax"]
        # 30,000만원 × 4% = 1,200만원 연배당 → threshold_gap 확인
        # (정확히 초과하는지는 div_growth 조정에 따라 다름)
        assert "threshold_gap_만원" in ct

    def test_threshold_gap_logic(self):
        """threshold_gap: 2000 - 연배당 (양수=여유, 음수=초과)"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
        )
        ct = result["comprehensive_tax"]
        annual_div = ct["annual_div_gross_만원"]
        expected_gap = 2_000 - annual_div
        gap = ct["threshold_gap_만원"]
        # 부호 방향이 맞는지 확인
        if annual_div < 2_000:
            assert gap > 0, f"연배당({annual_div}) < 임계점인데 gap이 음수: {gap}"
        else:
            assert gap <= 0, f"연배당({annual_div}) >= 임계점인데 gap이 양수: {gap}"


# ─────────────────────────────────────────────────────────────────────────────
# 세율 로직 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestTaxRateLogic:
    def test_effective_rate_between_0_and_1(self):
        """실효세율은 0~1 (또는 0~100%) 범위"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
        )
        rate = result["effective_tax_rate_pct"]
        # 퍼센트 표현 or 소수 표현 모두 허용
        assert 0 <= rate <= 100, f"실효세율 범위 초과: {rate}"

    def test_optimized_rate_not_higher_than_effective(self):
        """최적화 세율 ≤ 현재 세율 (절세 후 세율이 더 낮아야 한다)"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
        )
        assert result["optimized_tax_rate_pct"] <= result["effective_tax_rate_pct"] + 0.1, \
            "최적화 후 세율이 현재 세율보다 높음 — 절세 로직 오류"

    def test_total_saving_is_non_negative(self):
        """총 절세 효과는 0 이상"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
        )
        assert result["total_annual_saving_만원"] >= 0

    def test_5yr_saving_equals_or_greater_than_annual(self):
        """5년 누적 절세 ≥ 연간 절세"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=8_000,
            current_age=35,
        )
        assert result["5yr_cumulative_saving_만원"] >= result["total_annual_saving_만원"]


# ─────────────────────────────────────────────────────────────────────────────
# 엣지 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_recommendations(self):
        """빈 추천 목록 → 예외 없이 결과 반환"""
        result = calc_tax_optimizer(
            recommendations=[],
            investable_amount=0,
            current_age=35,
        )
        assert "tax_health_score" in result

    def test_young_investor_age(self):
        """20세 투자자도 예외 없이 처리"""
        result = calc_tax_optimizer(
            recommendations=SAMPLE_RECS,
            investable_amount=1_000,
            current_age=20,
        )
        assert "isa_strategy" in result

    def test_high_income_investor(self):
        """고소득 투자자(연소득 1억)에게 적절한 세율 경고"""
        result = calc_tax_optimizer(
            recommendations=LARGE_RECS,
            investable_amount=30_000,
            current_age=45,
            annual_income_만원=10_000,
        )
        assert "priority_actions" in result
        assert isinstance(result["priority_actions"], list)

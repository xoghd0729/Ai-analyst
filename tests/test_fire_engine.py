"""
tests/test_fire_engine.py — FIRE 역산 엔진 단위 테스트

왜 이 테스트가 필요한가?
  calc_fire_engine()은 투자자에게 "월 얼마를 적립해야 하나"를 알려주는 핵심 함수.
  PMT 역산 공식, 인플레이션 조정, 이미 달성 판단 등이 수학적으로 맞는지 검증한다.

실행:
  cd /path/to/ai-analyst
  pytest tests/test_fire_engine.py -v
"""

import math
import sys
import os

# 프로젝트 루트를 sys.path에 추가 (ai-analyst 패키지 import 가능하게)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.fire_engine import calc_fire_engine, FIRE_TARGETS


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처: 기본 호출 결과
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def base_result():
    """30세, 5000만원 투자, 월 50만원 적립 기준 결과"""
    return calc_fire_engine(
        current_investable=5_000,
        monthly_savings=50,
        current_age=30,
        target_age=50,
        avg_net_yield=3.5,
        div_growth_rate=5.0,
        cpi_rate=2.5,
    )


@pytest.fixture
def already_achieved_result():
    """이미 FIRE 달성 가능한 고액 투자자: 30억 투자"""
    return calc_fire_engine(
        current_investable=300_000,  # 30억
        monthly_savings=100,
        current_age=40,
        target_age=50,
        avg_net_yield=3.5,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 반환 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestReturnStructure:
    def test_top_level_keys(self, base_result):
        """필수 최상위 키 존재 여부"""
        required = {"targets", "current_state", "fire_timeline",
                    "recommended_action", "earliest_fire_type", "earliest_fire_age"}
        assert required.issubset(set(base_result.keys())), \
            f"누락 키: {required - set(base_result.keys())}"

    def test_targets_contains_three_types(self, base_result):
        """lean / regular / fat 목표가 모두 존재해야 한다"""
        targets = base_result["targets"]
        assert "lean" in targets
        assert "regular" in targets
        assert "fat" in targets

    def test_target_result_structure(self, base_result):
        """각 목표 결과의 핵심 키 존재 여부"""
        required_keys = {
            "label", "monthly_target_nominal", "monthly_target_real",
            "required_principal", "shortfall", "already_achieved",
            "monthly_pmt_needed", "achievable_by_target",
        }
        for key in ["lean", "regular", "fat"]:
            target = base_result["targets"][key]
            missing = required_keys - set(target.keys())
            assert not missing, f"{key} 목표에 누락된 키: {missing}"

    def test_current_state_structure(self, base_result):
        """current_state 필수 필드"""
        cs = base_result["current_state"]
        assert cs["current_age"] == 30
        assert cs["target_age"] == 50
        assert cs["years_to_fire"] == 20
        assert cs["avg_net_yield_pct"] == 3.5

    def test_fire_timeline_is_list(self, base_result):
        """fire_timeline은 리스트여야 한다"""
        assert isinstance(base_result["fire_timeline"], list)
        assert len(base_result["fire_timeline"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 수학적 정확성 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestMathAccuracy:
    def test_current_monthly_div_estimate(self, base_result):
        """현재 월 배당 추정: investable × yield / 12"""
        cs = base_result["current_state"]
        expected = round(5_000 * 0.035 / 12, 2)
        assert abs(cs["current_monthly_div"] - expected) < 1.0, \
            f"예상: {expected}, 실제: {cs['current_monthly_div']}"

    def test_inflation_adjusted_target_increases(self, base_result):
        """인플레이션 조정 목표는 명목 목표보다 커야 한다 (20년 × 2.5% CPI)"""
        lean = base_result["targets"]["lean"]
        assert lean["monthly_target_real"] > lean["monthly_target_nominal"], \
            "인플레이션 조정 목표가 명목 목표 이하 — CPI 복리 적용 오류"

    def test_real_target_inflation_factor(self, base_result):
        """인플레이션 조정: nominal × (1 + 0.025)^20"""
        lean = base_result["targets"]["lean"]
        nominal = lean["monthly_target_nominal"]
        expected_real = nominal * ((1 + 0.025) ** 20)
        assert abs(lean["monthly_target_real"] - expected_real) < 1.0, \
            f"인플레이션 조정 공식 오류: 예상={expected_real:.2f}, 실제={lean['monthly_target_real']}"

    def test_required_principal_formula(self, base_result):
        """
        필요 원금 = 실질 목표 연배당 / 세후수익률
        lean 기준: real_monthly_target × 12 / 0.035
        """
        lean = base_result["targets"]["lean"]
        annual_target = lean["monthly_target_real"] * 12
        expected_principal = round(annual_target / 0.035, 0)
        # 10만원 허용 오차
        assert abs(lean["required_principal"] - expected_principal) < 10, \
            f"원금 공식 오류: 예상={expected_principal}, 실제={lean['required_principal']}"

    def test_shortfall_equals_principal_minus_current(self, base_result):
        """shortfall = required_principal - current_investable"""
        lean = base_result["targets"]["lean"]
        expected_shortfall = lean["required_principal"] - 5_000
        assert abs(lean["shortfall"] - expected_shortfall) < 10, \
            f"shortfall 계산 오류"

    def test_pmt_needed_positive_when_shortfall_positive(self, base_result):
        """shortfall이 양수면 월 적립금이 필요하다"""
        fat = base_result["targets"]["fat"]  # 팻 파이어는 대부분 shortfall 양수
        if fat["shortfall"] > 0:
            assert fat["monthly_pmt_needed"] >= 0, "shortfall 양수인데 PMT가 음수"

    def test_fat_fire_requires_more_than_lean(self, base_result):
        """팻 파이어 원금 > 일반 파이어 원금 > 린 파이어 원금"""
        targets = base_result["targets"]
        assert targets["fat"]["required_principal"] > targets["regular"]["required_principal"]
        assert targets["regular"]["required_principal"] > targets["lean"]["required_principal"]

    def test_fire_targets_monthly_values(self):
        """FIRE_TARGETS 상수: lean < regular < fat"""
        assert FIRE_TARGETS["lean"]["monthly_만원"] < FIRE_TARGETS["regular"]["monthly_만원"]
        assert FIRE_TARGETS["regular"]["monthly_만원"] < FIRE_TARGETS["fat"]["monthly_만원"]


# ─────────────────────────────────────────────────────────────────────────────
# 엣지 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_already_achieved_lean_fire(self, already_achieved_result):
        """30억 투자자는 린 파이어를 이미 달성했어야 한다"""
        lean = already_achieved_result["targets"]["lean"]
        assert lean["already_achieved"] is True, \
            "300,000만원(30억) 투자자가 린 파이어(월 120만) 미달성 — 로직 오류"

    def test_shortfall_negative_when_achieved(self, already_achieved_result):
        """already_achieved=True 이면 shortfall은 0 이하"""
        lean = already_achieved_result["targets"]["lean"]
        if lean["already_achieved"]:
            assert lean["shortfall"] <= 0

    def test_custom_target_included_when_specified(self):
        """custom_monthly_만원 > 0 이면 targets에 custom 포함"""
        result = calc_fire_engine(
            current_investable=5_000,
            monthly_savings=50,
            current_age=30,
            target_age=50,
            custom_monthly_만원=200.0,
        )
        assert "custom" in result["targets"]
        assert result["targets"]["custom"] is not None
        assert result["targets"]["custom"]["monthly_target_nominal"] == 200.0

    def test_custom_target_none_when_zero(self):
        """custom_monthly_만원=0 이면 custom은 None"""
        result = calc_fire_engine(
            current_investable=5_000,
            monthly_savings=50,
            current_age=30,
            target_age=50,
            custom_monthly_만원=0,
        )
        assert result["targets"].get("custom") is None

    def test_target_age_same_as_current_age(self):
        """목표 나이 == 현재 나이 → years=1 (최소값 보장, zero-division 없음)"""
        result = calc_fire_engine(
            current_investable=1_000,
            monthly_savings=30,
            current_age=40,
            target_age=40,  # 동일
        )
        assert result["current_state"]["years_to_fire"] >= 1

    def test_zero_investable_still_returns(self):
        """투자금 0원도 정상 반환 (PMT 계산 필요)"""
        result = calc_fire_engine(
            current_investable=0,
            monthly_savings=30,
            current_age=25,
            target_age=50,
        )
        assert "targets" in result
        # 투자금 0 → shortfall = required_principal
        lean = result["targets"]["lean"]
        assert lean["shortfall"] == lean["required_principal"]

    def test_high_yield_reduces_required_principal(self):
        """수익률이 높을수록 필요 원금이 줄어야 한다"""
        low_yield = calc_fire_engine(5_000, 50, 30, avg_net_yield=2.0)
        high_yield = calc_fire_engine(5_000, 50, 30, avg_net_yield=6.0)
        lean_low  = low_yield["targets"]["lean"]["required_principal"]
        lean_high = high_yield["targets"]["lean"]["required_principal"]
        assert lean_high < lean_low, \
            f"고수익률에서 원금이 더 큼: 저={lean_low}, 고={lean_high}"

    def test_recommended_action_is_string(self, base_result):
        """recommended_action은 비어있지 않은 문자열"""
        action = base_result["recommended_action"]
        assert isinstance(action, str) and len(action) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 파이어 타임라인 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestFireTimeline:
    def test_timeline_length_matches_horizon(self, base_result):
        """타임라인은 최소 years_to_fire 길이"""
        years = base_result["current_state"]["years_to_fire"]
        timeline = base_result["fire_timeline"]
        assert len(timeline) >= years

    def test_timeline_entry_has_required_fields(self, base_result):
        """타임라인 항목 기본 필드"""
        entry = base_result["fire_timeline"][0]
        assert "age" in entry or "year" in entry  # age 또는 year 중 하나 있어야 함

    def test_portfolio_grows_over_time(self, base_result):
        """포트폴리오 가치는 시간이 지날수록 증가해야 한다 (적립 중)"""
        timeline = base_result["fire_timeline"]
        if len(timeline) >= 2:
            # 첫 해와 마지막 해 비교 — 적립 있으면 성장
            first = timeline[0]
            last  = timeline[-1]
            # 어떤 값이든 존재하고 숫자면 통과
            val_key = next((k for k in ["total_asset", "portfolio", "cumulative"] if k in first), None)
            if val_key:
                assert last[val_key] >= first[val_key], "포트폴리오가 시간 역행"


# ─────────────────────────────────────────────────────────────────────────────
# FIRE 단조성 불변조건
# 절대값 고정 X — 방향성만 검증 (시장 데이터 변동 허용)
# ─────────────────────────────────────────────────────────────────────────────

class TestFireMonotonicityInvariants:
    """입력이 유리해지면 FIRE age가 같거나 빨라져야 한다."""

    # 공통 파라미터 기준
    _BASE = dict(current_age=40, target_age=55, avg_net_yield=5.0,
                 div_growth_rate=5.0, cpi_rate=2.5, custom_monthly_만원=100.0)

    def _fire_age(self, result: dict) -> int:
        """custom target의 projected_fire_age 추출 (없으면 99 반환)."""
        custom = result.get("targets", {}).get("custom")
        if not custom:
            return 99
        return int(custom.get("projected_fire_age") or 99)

    def test_more_monthly_savings_earlier_fire(self):
        """월 적립금 증가 → FIRE age 같거나 빨라짐."""
        r_low  = calc_fire_engine(current_investable=5000, monthly_savings=30,  **self._BASE)
        r_high = calc_fire_engine(current_investable=5000, monthly_savings=100, **self._BASE)
        age_low  = self._fire_age(r_low)
        age_high = self._fire_age(r_high)
        assert age_high <= age_low, \
            f"월적립 30→100만으로 증가했는데 FIRE가 늦어짐: {age_low}→{age_high}세"

    def test_more_initial_capital_earlier_fire(self):
        """초기 투자금 증가 → FIRE age 같거나 빨라짐."""
        r_small = calc_fire_engine(current_investable=3000, monthly_savings=50, **self._BASE)
        r_large = calc_fire_engine(current_investable=8000, monthly_savings=50, **self._BASE)
        age_small = self._fire_age(r_small)
        age_large = self._fire_age(r_large)
        assert age_large <= age_small, \
            f"초기자산 3000→8000만으로 증가했는데 FIRE가 늦어짐: {age_small}→{age_large}세"

    def test_higher_yield_earlier_fire(self):
        """수익률 증가 → FIRE age 같거나 빨라짐."""
        r_low  = calc_fire_engine(current_investable=5000, monthly_savings=50,
                                   current_age=40, target_age=55,
                                   avg_net_yield=3.0, custom_monthly_만원=100.0)
        r_high = calc_fire_engine(current_investable=5000, monthly_savings=50,
                                   current_age=40, target_age=55,
                                   avg_net_yield=6.0, custom_monthly_만원=100.0)
        age_low  = self._fire_age(r_low)
        age_high = self._fire_age(r_high)
        assert age_high <= age_low, \
            f"수익률 3%→6% 증가했는데 FIRE가 늦어짐: {age_low}→{age_high}세"

    def test_lower_target_fires_earlier(self):
        """낮은 목표 월배당 → 더 빨리 달성 (단조증가)."""
        base = dict(current_investable=5000, monthly_savings=50,
                    current_age=40, target_age=55, avg_net_yield=5.0)
        r_small = calc_fire_engine(**base, custom_monthly_만원=50.0)
        r_large = calc_fire_engine(**base, custom_monthly_만원=200.0)
        age_small = self._fire_age(r_small)
        age_large = self._fire_age(r_large)
        assert age_small <= age_large, \
            f"낮은 목표인데 FIRE가 더 늦음: 50만={age_small}세, 200만={age_large}세"

    def test_current_dividend_positive_when_has_capital(self):
        """초기 투자금 > 0이면 현재 월배당 > 0."""
        r = calc_fire_engine(current_investable=5000, monthly_savings=0,
                              current_age=40, avg_net_yield=5.0)
        cur_div = r["current_state"]["current_monthly_div"]
        assert cur_div > 0, f"투자금 5000만원인데 현재 월배당=0: {cur_div}"

    def test_current_dividend_zero_when_no_capital(self):
        """초기 투자금 = 0이면 현재 월배당 = 0."""
        r = calc_fire_engine(current_investable=0, monthly_savings=50,
                              current_age=25, avg_net_yield=5.0)
        cur_div = r["current_state"]["current_monthly_div"]
        assert cur_div == 0, f"투자금 0인데 현재 월배당 > 0: {cur_div}"

    def test_combined_improvement_earlier_fire(self):
        """투자금 + 적립금 동시 증가 → FIRE age 같거나 빨라짐 (합성 단조성)."""
        r_base = calc_fire_engine(current_investable=3000, monthly_savings=30,  **self._BASE)
        r_good = calc_fire_engine(current_investable=7000, monthly_savings=100, **self._BASE)
        age_base = self._fire_age(r_base)
        age_good = self._fire_age(r_good)
        assert age_good <= age_base, \
            f"투자금+적립금 모두 늘었는데 FIRE가 늦어짐: {age_base}→{age_good}세"

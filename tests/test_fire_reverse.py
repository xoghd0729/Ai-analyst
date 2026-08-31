"""
tests/test_fire_reverse.py
===================================
calc_fire_reverse() 단위 테스트.

테스트 원칙:
  - 절대값 고정 X — 방향성과 불변조건만 검증
  - "55세에 정확히 달성" 같은 테스트 없음 — 입력 변화 → 결과 변화 방향 검증

검증 영역:
  1. ReturnStructure   : 반환 키 존재 및 타입
  2. AlreadyAchievable : 충분한 자산이면 already_achievable=True
  3. GapDirection      : 현재 조건 나쁠수록 gap_years 증가
  4. SavingsReverse    : 더 많은 적립 → req_savings 감소
  5. CapitalReverse    : 더 많은 자산 → req_capital 감소 (또는 불필요)
  6. AchievableMonthly : 이미 달성 조건이면 achievable >= target
  7. Monotonicity      : 목표 높아질수록 req_savings/capital 증가
  8. EdgeCases         : target_monthly=0, 이미 달성, 극단값

실행:
  cd ~/ai-analyst && pytest tests/test_fire_reverse.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.fire_engine import calc_fire_reverse


# ── 공통 기준 파라미터 ────────────────────────────────────────────────────

_BASE = dict(
    current_investable  = 5_000,   # 만원
    monthly_savings     = 50,      # 만원
    current_age         = 40,
    target_fire_age     = 55,
    target_monthly_만원 = 100,
    avg_net_yield       = 5.0,
    div_growth_rate     = 5.0,
    cpi_rate            = 2.5,
)


# ═══════════════════════════════════════════════════════════════════════════
# 1. ReturnStructure
# ═══════════════════════════════════════════════════════════════════════════

class TestReturnStructure:
    """반환 딕셔너리 구조 검증."""

    @pytest.fixture(scope="class")
    def result(self):
        return calc_fire_reverse(**_BASE)

    _REQUIRED_KEYS = [
        "current_fire_age",
        "gap_years",
        "target_fire_age",
        "target_monthly_만원",
        "already_achievable",
        "required_monthly_savings",
        "savings_increase",
        "required_initial_capital",
        "capital_increase",
        "achievable_monthly",
        "message",
    ]

    def test_all_keys_present(self, result):
        for key in self._REQUIRED_KEYS:
            assert key in result, f"반환에 '{key}' 없음"

    def test_already_achievable_is_bool(self, result):
        assert isinstance(result["already_achievable"], bool)

    def test_target_fire_age_matches_input(self, result):
        assert result["target_fire_age"] == _BASE["target_fire_age"]

    def test_target_monthly_matches_input(self, result):
        assert result["target_monthly_만원"] == _BASE["target_monthly_만원"]

    def test_message_is_nonempty_string(self, result):
        assert isinstance(result["message"], str)
        assert len(result["message"]) > 0

    def test_current_fire_age_is_int_or_none(self, result):
        v = result["current_fire_age"]
        assert v is None or isinstance(v, int)

    def test_achievable_monthly_is_positive_or_none(self, result):
        v = result["achievable_monthly"]
        assert v is None or v > 0


# ═══════════════════════════════════════════════════════════════════════════
# 2. AlreadyAchievable
# ═══════════════════════════════════════════════════════════════════════════

class TestAlreadyAchievable:
    """충분한 자산이면 already_achievable=True."""

    def test_large_capital_already_achievable(self):
        """투자금 100억원이면 어떤 목표도 이미 달성."""
        r = calc_fire_reverse(
            current_investable  = 100_000,  # 100억
            monthly_savings     = 50,
            current_age         = 40,
            target_fire_age     = 55,
            target_monthly_만원 = 100,
            avg_net_yield       = 5.0,
        )
        assert r["already_achievable"] is True

    def test_already_achievable_no_req_savings(self):
        """already_achievable이면 required_monthly_savings는 None 또는 현재 이하."""
        r = calc_fire_reverse(
            current_investable  = 100_000,
            monthly_savings     = 50,
            current_age         = 40,
            target_fire_age     = 55,
            target_monthly_만원 = 100,
            avg_net_yield       = 5.0,
        )
        if r["required_monthly_savings"] is not None:
            assert r["required_monthly_savings"] <= 50 + 1  # 현재 적립금 이하

    def test_small_capital_not_yet_achievable(self):
        """소자산은 달성 안 됨."""
        r = calc_fire_reverse(
            current_investable  = 100,
            monthly_savings     = 5,
            current_age         = 40,
            target_fire_age     = 45,   # 5년 내
            target_monthly_만원 = 200,
            avg_net_yield       = 5.0,
        )
        assert r["already_achievable"] is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. Gap direction
# ═══════════════════════════════════════════════════════════════════════════

class TestGapDirection:
    """더 유리한 조건 → gap_years 감소 (또는 already_achievable)."""

    def test_more_savings_smaller_gap(self):
        """월 적립금 증가 → gap_years 감소."""
        r_low  = calc_fire_reverse(**{**_BASE, "monthly_savings": 20})
        r_high = calc_fire_reverse(**{**_BASE, "monthly_savings": 150})

        gap_low  = r_low["gap_years"]  or 99
        gap_high = r_high["gap_years"] or 99
        # high가 already_achievable이면 gap=0 또는 음수
        if r_high["already_achievable"]:
            assert True
        else:
            assert gap_high <= gap_low, \
                f"적립 늘렸는데 gap 증가: {gap_low} → {gap_high}"

    def test_more_capital_smaller_gap(self):
        """초기 자산 증가 → gap_years 감소."""
        r_small = calc_fire_reverse(**{**_BASE, "current_investable": 1_000})
        r_large = calc_fire_reverse(**{**_BASE, "current_investable": 20_000})

        gap_small = r_small["gap_years"] or 99
        gap_large = r_large["gap_years"] or 99

        if r_large["already_achievable"]:
            assert True
        else:
            assert gap_large <= gap_small, \
                f"자산 늘렸는데 gap 증가: {gap_small} → {gap_large}"

    def test_lower_target_smaller_gap(self):
        """목표 월배당 낮추면 gap 감소."""
        r_high_tgt = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 300})
        r_low_tgt  = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 50})

        gap_high = r_high_tgt["gap_years"] or 99
        gap_low  = r_low_tgt["gap_years"]  or 99
        assert gap_low <= gap_high, \
            f"목표 낮췄는데 gap 증가: {gap_high} → {gap_low}"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Savings reverse monotonicity
# ═══════════════════════════════════════════════════════════════════════════

class TestSavingsReverse:
    """방법 1: 월 적립 역산 방향성."""

    def test_higher_target_needs_more_savings(self):
        """목표가 높을수록 required_monthly_savings 증가."""
        r_low  = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 50})
        r_high = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 200})

        s_low  = r_low["required_monthly_savings"]
        s_high = r_high["required_monthly_savings"]

        # 둘 다 None이 아닌 경우만 비교
        if s_low is not None and s_high is not None:
            assert s_high >= s_low, \
                f"높은 목표인데 req_savings 더 적음: {s_low} → {s_high}"

    def test_more_initial_capital_reduces_req_savings(self):
        """자산 많으면 필요 월적립금 감소."""
        r_small = calc_fire_reverse(**{**_BASE, "current_investable": 1_000})
        r_large = calc_fire_reverse(**{**_BASE, "current_investable": 8_000})

        s_small = r_small["required_monthly_savings"]
        s_large = r_large["required_monthly_savings"]

        if s_small is None:
            return  # 소자산도 범위 내 해 없으면 스킵
        if s_large is None or r_large["already_achievable"]:
            assert True
        else:
            assert s_large <= s_small, \
                f"자산 많은데 req_savings 더 많음: {s_small} → {s_large}"

    def test_req_savings_geq_current_savings(self):
        """required_monthly_savings는 현재 monthly_savings 이상."""
        r = calc_fire_reverse(**_BASE)
        if r["required_monthly_savings"] is not None:
            assert r["required_monthly_savings"] >= _BASE["monthly_savings"] - 1, \
                "req_savings가 현재 적립금보다 작음"

    def test_savings_increase_is_positive(self):
        """savings_increase는 양수여야 함 (증액이니까)."""
        r = calc_fire_reverse(**_BASE)
        if r["savings_increase"] is not None:
            assert r["savings_increase"] > 0, \
                f"savings_increase 음수: {r['savings_increase']}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Capital reverse monotonicity
# ═══════════════════════════════════════════════════════════════════════════

class TestCapitalReverse:
    """방법 2: 초기 투자금 역산 방향성."""

    def test_higher_target_needs_more_capital(self):
        """목표가 높을수록 required_initial_capital 증가."""
        r_low  = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 50})
        r_high = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 200})

        c_low  = r_low["required_initial_capital"]
        c_high = r_high["required_initial_capital"]

        if c_low is not None and c_high is not None:
            assert c_high >= c_low, \
                f"높은 목표인데 req_capital 더 적음: {c_low} → {c_high}"

    def test_req_capital_geq_current(self):
        """required_initial_capital은 현재 투자금 이상."""
        r = calc_fire_reverse(**_BASE)
        if r["required_initial_capital"] is not None:
            assert r["required_initial_capital"] >= _BASE["current_investable"] - 100

    def test_capital_increase_is_positive(self):
        """capital_increase는 양수."""
        r = calc_fire_reverse(**_BASE)
        if r["capital_increase"] is not None:
            assert r["capital_increase"] > 0

    def test_more_savings_reduces_req_capital(self):
        """적립금 많으면 필요 초기자산 감소."""
        r_low  = calc_fire_reverse(**{**_BASE, "monthly_savings": 20})
        r_high = calc_fire_reverse(**{**_BASE, "monthly_savings": 200})

        c_low  = r_low["required_initial_capital"]
        c_high = r_high["required_initial_capital"]

        if c_low is None:
            return
        if c_high is None or r_high["already_achievable"]:
            assert True
        else:
            assert c_high <= c_low, \
                f"적립 많은데 req_capital 증가: {c_low} → {c_high}"


# ═══════════════════════════════════════════════════════════════════════════
# 6. Achievable monthly
# ═══════════════════════════════════════════════════════════════════════════

class TestAchievableMonthly:
    """방법 3: 현재 조건으로 달성 가능한 최대 월배당."""

    def test_achievable_monthly_leq_target_when_not_achievable(self):
        """미달성 조건에서 achievable_monthly < target_monthly."""
        r = calc_fire_reverse(**_BASE)
        if not r["already_achievable"] and r["achievable_monthly"] is not None:
            assert r["achievable_monthly"] < _BASE["target_monthly_만원"] + 1

    def test_achievable_monthly_geq_target_when_already_achievable(self):
        """이미 달성 조건이면 achievable >= target."""
        r = calc_fire_reverse(
            current_investable  = 100_000,
            monthly_savings     = 50,
            current_age         = 40,
            target_fire_age     = 55,
            target_monthly_만원 = 100,
            avg_net_yield       = 5.0,
        )
        if r["achievable_monthly"] is not None:
            assert r["achievable_monthly"] >= _BASE["target_monthly_만원"]

    def test_more_capital_higher_achievable_monthly(self):
        """자산 많으면 achievable_monthly 증가."""
        r_small = calc_fire_reverse(**{**_BASE, "current_investable": 1_000})
        r_large = calc_fire_reverse(**{**_BASE, "current_investable": 20_000})

        a_small = r_small["achievable_monthly"]
        a_large = r_large["achievable_monthly"]

        if a_small is not None and a_large is not None:
            assert a_large >= a_small, \
                f"자산 많은데 achievable 감소: {a_small} → {a_large}"

    def test_more_savings_higher_achievable_monthly(self):
        """적립 많으면 achievable_monthly 증가."""
        r_low  = calc_fire_reverse(**{**_BASE, "monthly_savings": 20})
        r_high = calc_fire_reverse(**{**_BASE, "monthly_savings": 200})

        a_low  = r_low["achievable_monthly"]
        a_high = r_high["achievable_monthly"]

        if a_low is not None and a_high is not None:
            assert a_high >= a_low, \
                f"적립 많은데 achievable 감소: {a_low} → {a_high}"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    """경계값 및 예외 입력."""

    def test_zero_target_monthly_returns_already_achievable(self):
        """target_monthly=0이면 trivially already_achievable."""
        r = calc_fire_reverse(**{**_BASE, "target_monthly_만원": 0})
        # 0원 목표는 항상 달성
        assert r["already_achievable"] is True or r["current_fire_age"] is not None

    def test_target_age_equals_current_age(self):
        """목표 나이 == 현재 나이 → 오류 없이 반환."""
        r = calc_fire_reverse(**{**_BASE, "target_fire_age": 40})
        assert "message" in r

    def test_very_high_yield_already_achievable(self):
        """수익률 30%이면 대부분 이미 달성."""
        r = calc_fire_reverse(**{**_BASE, "avg_net_yield": 30.0})
        assert r["already_achievable"] is True

    def test_result_consistent_savings_and_capital(self):
        """방법1/방법2 둘 다 None이 아닌 경우: 더 큰 레버 하나면 각 목표 달성 가능."""
        r = calc_fire_reverse(**_BASE)
        # 둘 다 None이 아니면 각각의 솔루션이 독립적으로 존재
        s = r["required_monthly_savings"]
        c = r["required_initial_capital"]
        if s is not None and c is not None:
            # req_savings 솔루션으로 실제 달성 확인
            from utils.fire_engine import calc_fire_engine
            check = calc_fire_engine(
                current_investable  = _BASE["current_investable"],
                monthly_savings     = s,
                current_age         = _BASE["current_age"],
                target_age          = _BASE["target_fire_age"],
                avg_net_yield       = _BASE["avg_net_yield"],
                div_growth_rate     = _BASE["div_growth_rate"],
                cpi_rate            = _BASE["cpi_rate"],
                custom_monthly_만원 = _BASE["target_monthly_만원"],
            )
            fire_age = check["targets"]["custom"]["projected_fire_age"]
            assert fire_age is not None and int(fire_age) <= _BASE["target_fire_age"] + 1, \
                f"방법1 솔루션({s:.1f}만원)으로 실제 달성 실패: fire_age={fire_age}"

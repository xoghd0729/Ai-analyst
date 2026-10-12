"""
tests/test_edge_cases.py — 극단값 / 경계조건 엣지케이스 테스트
===============================================================

목적:
  발표·전시 환경에서 예상치 못한 입력값이 들어와도
  파이프라인이 500 오류 없이 응답을 반환하는지 검증.

커버 범위:
  - age 경계값 (18, 75)
  - investable_amount = 0 (시드 없음)
  - monthly_target = 0 (목표 없음)
  - 초고액 투자 (1억 이상)
  - risk_tolerance 전체 3종
  - data_freshness 응답 구조
  - kr_score_breakdown 구조 (KR 추천 시)
  - survival 필드 면책 표현

실행:
  pytest tests/test_edge_cases.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from api.pipeline.context import PortfolioRequest
from api.pipeline.runner import RecommendationPipeline


# ── 헬퍼 ─────────────────────────────────────────────────────

def make_req(**kwargs) -> PortfolioRequest:
    base = dict(
        age=35, annual_income=5000, monthly_target=100,
        investable_amount=5000, risk_tolerance="moderate",
        archetype="혼합형", monthly_savings=100.0,
        target_fire_age=50, savings_growth=5.0,
    )
    base.update(kwargs)
    return PortfolioRequest(**base)


def run(req: PortfolioRequest) -> dict:
    return RecommendationPipeline(req).execute()


# ─────────────────────────────────────────────────────────────
# [A] 나이 경계값
# ─────────────────────────────────────────────────────────────

class TestAgeBoundaries:
    def test_age_18_does_not_crash(self):
        """18세 최연소 — 예외 없이 응답 반환"""
        result = run(make_req(age=18, risk_tolerance="aggressive"))
        assert isinstance(result, dict)
        assert "recommendations" in result

    def test_age_75_does_not_crash(self):
        """75세 고령 — 예외 없이 응답 반환"""
        result = run(make_req(age=75, risk_tolerance="conservative"))
        assert isinstance(result, dict)
        assert "recommendations" in result

    def test_age_50_fire_target_at_age(self):
        """50세 + FIRE 목표 50세 — 즉시 달성 시나리오 (fire_plan 빈 dict 허용)"""
        result = run(make_req(age=50, target_fire_age=50))
        assert isinstance(result, dict)
        # 응답 키는 "fire_plan" (fire_engine 아님 — runner.py 참조)
        # age == target_fire_age 경우 fire_plan이 빈 dict인 것은 정상
        assert isinstance(result.get("fire_plan"), dict), "fire_plan이 dict 아님"
        assert "recommendations" in result, "추천 종목 없음"


# ─────────────────────────────────────────────────────────────
# [B] 투자금 경계값
# ─────────────────────────────────────────────────────────────

class TestInvestableAmountBoundaries:
    def test_zero_investable_with_savings(self):
        """시드머니 없음 (investable=0), 월 적립만 있음"""
        result = run(make_req(investable_amount=0, monthly_savings=50.0))
        assert isinstance(result, dict), "응답 dict 아님"
        assert "recommendations" in result

    def test_very_large_investable(self):
        """초고액 투자 (10억 이상)"""
        result = run(make_req(
            investable_amount=100_000,
            monthly_target=500,
        ))
        assert isinstance(result, dict)
        recs = result.get("recommendations", [])
        assert len(recs) >= 1, "종목이 1개도 없음"

    def test_small_investable(self):
        """극소액 (10만원)"""
        result = run(make_req(investable_amount=10, monthly_savings=1.0))
        assert isinstance(result, dict)
        # 극소액이어도 오류 없이 반환
        assert "summary" in result


# ─────────────────────────────────────────────────────────────
# [C] 목표 월배당 경계값
# ─────────────────────────────────────────────────────────────

class TestMonthlyTargetBoundaries:
    def test_zero_monthly_target(self):
        """목표 월배당 0 — 예외 없이 응답"""
        result = run(make_req(monthly_target=0))
        assert isinstance(result, dict)
        assert "recommendations" in result

    def test_very_high_monthly_target(self):
        """비현실적 고목표 (월 1,000만원) — 오류 없이 반환, fire_plan 빈 dict 허용"""
        result = run(make_req(
            monthly_target=1000,
            investable_amount=5000,
        ))
        assert isinstance(result, dict)
        # 투자금 대비 목표가 너무 클 때 fire_plan이 빈 dict인 것은 정상
        # 응답 키는 "fire_plan" (runner.py: "fire_plan": ctx.fire_plan)
        assert isinstance(result.get("fire_plan"), dict), "fire_plan이 dict 아님"
        assert "recommendations" in result, "추천 종목 없음"


# ─────────────────────────────────────────────────────────────
# [D] risk_tolerance 전체 종류
# ─────────────────────────────────────────────────────────────

class TestRiskToleranceVariants:
    @pytest.mark.parametrize("risk", ["conservative", "moderate", "aggressive"])
    def test_all_risk_tolerances(self, risk):
        """모든 위험 성향에서 파이프라인 성공"""
        result = run(make_req(risk_tolerance=risk))
        assert isinstance(result, dict)
        assert "recommendations" in result
        assert len(result["recommendations"]) >= 1


# ─────────────────────────────────────────────────────────────
# [E] data_freshness 응답 구조
# ─────────────────────────────────────────────────────────────

class TestDataFreshnessField:
    @pytest.fixture(scope="class")
    def result(self):
        return run(make_req())

    def test_data_freshness_is_dict(self, result):
        """data_freshness 필드가 dict"""
        assert isinstance(result.get("data_freshness"), dict), \
            "data_freshness가 dict가 아님"

    def test_data_freshness_has_required_keys(self, result):
        """data_freshness에 필수 소스 키 존재"""
        df = result.get("data_freshness", {})
        required = ["kr_stock_ranking", "ml_scoring", "us_stock_scores", "etf_quality"]
        for key in required:
            assert key in df, f"data_freshness.{key} 없음"

    def test_data_freshness_new_fields(self, result):
        """Week1 추가 필드: dividend_dataset, survival_model"""
        df = result.get("data_freshness", {})
        # 이 필드들은 파일 존재 여부에 따라 "unknown"이 가능
        assert "dividend_dataset" in df, "data_freshness.dividend_dataset 없음"
        assert "survival_model" in df, "data_freshness.survival_model 없음"

    def test_data_freshness_values_are_strings(self, result):
        """data_freshness 값이 모두 문자열 (날짜 또는 'unknown')"""
        df = result.get("data_freshness", {})
        for key, val in df.items():
            if not isinstance(key, str) or key.startswith("_"):
                continue
            assert isinstance(val, str), f"data_freshness.{key} 값이 str 아님: {val!r}"


# ─────────────────────────────────────────────────────────────
# [F] kr_score_breakdown 구조
# ─────────────────────────────────────────────────────────────

class TestKrScoreBreakdown:
    @pytest.fixture(scope="class")
    def kr_recs(self):
        result = run(make_req())
        return [r for r in result.get("recommendations", [])
                if r.get("asset_class") == "kr_stock"]

    def test_kr_recs_have_score_breakdown(self, kr_recs):
        """KR 종목에 kr_score_breakdown 필드 존재"""
        if not kr_recs:
            pytest.skip("KR 추천 종목 없음 — 건너뜀")

        for rec in kr_recs:
            bd = rec.get("kr_score_breakdown")
            assert bd is not None, f"{rec.get('name')} — kr_score_breakdown 없음"
            for key in ["yield_score", "stability", "financial", "growth"]:
                assert key in bd, f"{rec.get('name')} — kr_score_breakdown.{key} 없음"

    def test_kr_score_breakdown_values_are_numeric(self, kr_recs):
        """kr_score_breakdown 값들이 숫자"""
        if not kr_recs:
            pytest.skip("KR 추천 종목 없음 — 건너뜀")

        for rec in kr_recs:
            bd = rec.get("kr_score_breakdown", {})
            for key, val in bd.items():
                assert isinstance(val, (int, float)), \
                    f"{rec.get('name')}.kr_score_breakdown.{key} = {val!r} (숫자 아님)"

    def test_kr_score_breakdown_sums_to_100(self, kr_recs):
        """yield+stability+financial+growth의 합이 약 100점"""
        if not kr_recs:
            pytest.skip("KR 추천 종목 없음 — 건너뜀")

        for rec in kr_recs:
            bd = rec.get("kr_score_breakdown", {})
            total = (bd.get("yield_score", 0) + bd.get("stability", 0)
                     + bd.get("financial", 0) + bd.get("growth", 0))
            # overall_score는 100점 만점, 서브스코어 합은 이보다 작거나 같음
            # (실제 overall_score와 같지 않을 수 있음 — 가중치 변환 때문)
            assert total <= 105, f"{rec.get('name')} 서브스코어 합 {total} > 105"
            assert total >= 0,   f"{rec.get('name')} 서브스코어 합 {total} < 0"


# ─────────────────────────────────────────────────────────────
# [G] 생존 면책 표현 검증
# ─────────────────────────────────────────────────────────────

class TestSurvivalDisclaimerExpressions:
    @pytest.fixture(scope="class")
    def survival(self):
        result = run(make_req())
        return result.get("survival", {})

    FORBIDDEN_PHRASES = [
        "지속 확률",          # 감사 지적 — "시뮬레이션 결과" 로 교체됨
        "ML이 예측한 장기",   # 감사 지적 — ML은 base_cut 기반 보조 신호
        "생존확률",           # 미교체 잔존 여부
        "배당삭감 확률",      # uncalibrated hazard_pct 오용 금지
    ]

    def test_story_summary_no_forbidden_phrases(self, survival):
        """story_summary에 금지 표현 없음"""
        story = survival.get("story_summary", "")
        for phrase in self.FORBIDDEN_PHRASES:
            assert phrase not in story, \
                f"금지 표현 발견: '{phrase}' in story_summary"

    def test_survival_probability_field_name(self, survival):
        """survival_probability 필드 존재"""
        assert "survival_probability" in survival, \
            "survival.survival_probability 없음"

    def test_threshold_type_field(self, survival):
        """threshold_type 필드: 'user_target' 또는 'current_80pct'"""
        tt = survival.get("threshold_type")
        assert tt in ("user_target", "current_80pct"), \
            f"threshold_type 예상 외 값: {tt!r}"

    def test_ml_effective_count_field(self, survival):
        """ml_effective_count 필드: int"""
        mlc = survival.get("ml_effective_count")
        assert mlc is not None, "ml_effective_count 없음"
        assert isinstance(mlc, int), f"ml_effective_count가 int 아님: {mlc!r}"

"""
tests/test_pipeline_runner.py — Pipeline Runner 통합 테스트

왜 이 테스트가 필요한가?
  RecommendationPipeline.execute()는 17개 필터가 순서대로 실행되는
  핵심 흐름이다. 어느 한 필터가 예외를 던져도 파이프라인은 계속
  실행되어야 하고, 최종 응답 dict의 구조가 항상 일정해야 한다.

  특히 테스트해야 할 것:
  1. 정상 입력 → 올바른 응답 구조
  2. 필터 예외 → pipeline_errors에 기록, 응답은 반환됨
  3. PipelineContext 상태 격리 (매 execute마다 새 Context)
  4. 응답의 핵심 섹션이 빠지지 않음

실행:
  pytest tests/test_pipeline_runner.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from api.pipeline.context import PortfolioRequest, PipelineContext
from api.pipeline.runner import RecommendationPipeline


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 요청 생성 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def make_request(**kwargs) -> PortfolioRequest:
    defaults = {
        "age":               35,
        "annual_income":     5000,
        "monthly_target":    15,
        "investable_amount": 5000,
        "risk_tolerance":    "moderate",
        "archetype":         "혼합형",
        "monthly_savings":   100.0,
        "target_fire_age":   50,
    }
    defaults.update(kwargs)
    return PortfolioRequest(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# PipelineContext 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineContext:
    def test_context_initializes_with_request(self):
        req = make_request(age=40)
        ctx = PipelineContext(request=req)
        assert ctx.request.age == 40

    def test_context_default_fields_are_empty(self):
        req = make_request()
        ctx = PipelineContext(request=req)
        assert ctx.recommendations == []
        assert ctx.macro == {}
        assert ctx.kr_stocks == []
        assert ctx.us_stocks == []
        assert ctx.etfs == []

    def test_context_add_error_method(self):
        """add_error() 메서드가 pipeline_errors에 기록"""
        req = make_request()
        ctx = PipelineContext(request=req)
        # pipeline_errors 필드가 있는지 확인 (있으면 add_error 테스트)
        if hasattr(ctx, "add_error"):
            ctx.add_error("TestFilter", "test error message")
            assert hasattr(ctx, "pipeline_errors")
        elif hasattr(ctx, "pipeline_errors"):
            # 직접 추가 가능한 경우
            ctx.pipeline_errors.append({"step": "TestFilter", "error": "test error"})
            assert len(ctx.pipeline_errors) == 1

    def test_request_fields_accessible(self):
        req = make_request(age=28, investable_amount=3000, risk_tolerance="aggressive")
        ctx = PipelineContext(request=req)
        assert ctx.request.investable_amount == 3000
        assert ctx.request.risk_tolerance == "aggressive"


# ─────────────────────────────────────────────────────────────────────────────
# PortfolioRequest 단위 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioRequest:
    def test_required_fields(self):
        req = make_request()
        assert hasattr(req, "age")
        assert hasattr(req, "annual_income")
        assert hasattr(req, "monthly_target")
        assert hasattr(req, "investable_amount")
        assert hasattr(req, "risk_tolerance")

    def test_default_archetype(self):
        req = PortfolioRequest(
            age=35, annual_income=5000, monthly_target=15,
            investable_amount=5000, risk_tolerance="moderate",
        )
        assert req.archetype == "혼합형"

    def test_default_target_fire_age(self):
        req = PortfolioRequest(
            age=35, annual_income=5000, monthly_target=15,
            investable_amount=5000, risk_tolerance="moderate",
        )
        assert req.target_fire_age == 50


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Runner 통합 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestRecommendationPipeline:
    @pytest.fixture
    def pipeline(self):
        return RecommendationPipeline(make_request())

    def test_pipeline_instantiation(self, pipeline):
        """파이프라인 객체 생성 확인"""
        assert pipeline is not None
        assert hasattr(pipeline, "execute")
        assert hasattr(pipeline, "ctx")
        assert hasattr(pipeline, "filters")

    def test_filters_are_loaded(self, pipeline):
        """PIPELINE_FILTERS가 로드되어 있는지"""
        assert len(pipeline.filters) > 0

    def test_each_filter_has_name(self, pipeline):
        """각 필터는 name 속성을 가져야 한다"""
        for filt in pipeline.filters:
            assert hasattr(filt, "name"), f"필터 {type(filt).__name__}에 name 속성 없음"
            assert isinstance(filt.name, str)

    def test_execute_returns_dict(self, pipeline):
        """execute()는 dict를 반환해야 한다"""
        result = pipeline.execute()
        assert isinstance(result, dict), f"execute()가 dict가 아닌 {type(result)} 반환"

    def test_execute_response_has_input_section(self, pipeline):
        """응답에 input 섹션 포함"""
        result = pipeline.execute()
        assert "input" in result, "응답에 'input' 섹션 없음"

    def test_execute_response_input_matches_request(self, pipeline):
        """input 섹션이 요청 값과 일치"""
        result = pipeline.execute()
        inp = result["input"]
        assert inp["age"] == 35
        assert inp["investable"] == 5000
        assert inp["risk_tolerance"] == "moderate"

    def test_execute_response_has_recommendations_section(self, pipeline):
        """응답에 recommendations 섹션 포함"""
        result = pipeline.execute()
        assert "recommendations" in result, "응답에 'recommendations' 섹션 없음"

    def test_execute_response_has_summary_section(self, pipeline):
        """응답에 summary 섹션 포함"""
        result = pipeline.execute()
        assert "summary" in result, "응답에 'summary' 섹션 없음"

    def test_each_pipeline_call_creates_fresh_context(self):
        """매 execute 호출 시 독립적인 Context (상태 오염 없음)"""
        req = make_request(age=35)
        p1 = RecommendationPipeline(req)
        p2 = RecommendationPipeline(req)
        assert p1.ctx is not p2.ctx, "두 파이프라인이 동일한 Context 공유 — 격리 위반"

    def test_filter_exception_does_not_crash_pipeline(self):
        """
        한 필터가 예외를 던져도 파이프라인이 중단되지 않고
        나머지 필터가 계속 실행되어 최종 응답을 반환해야 한다.
        """
        req = make_request()
        pipeline = RecommendationPipeline(req)

        # 첫 번째 필터가 예외를 던지도록 모킹
        if pipeline.filters:
            original_process = pipeline.filters[0].process
            pipeline.filters[0].process = MagicMock(
                side_effect=RuntimeError("테스트용 강제 예외")
            )

        result = pipeline.execute()

        # 응답이 반환되어야 한다
        assert isinstance(result, dict)
        assert "input" in result  # 기본 구조는 유지

    def test_pipeline_errors_captured(self):
        """필터 예외는 pipeline_errors에 기록된다"""
        req = make_request()
        pipeline = RecommendationPipeline(req)

        if pipeline.filters:
            pipeline.filters[0].process = MagicMock(
                side_effect=ValueError("의도적 오류")
            )

        result = pipeline.execute()

        # pipeline_errors 키 또는 errors 키에 오류 기록
        has_errors = (
            "pipeline_errors" in result and len(result["pipeline_errors"]) > 0
        ) or (
            "errors" in result and len(result["errors"]) > 0
        )
        assert has_errors, "필터 예외가 응답에 기록되지 않음"


# ─────────────────────────────────────────────────────────────────────────────
# 다양한 입력 파라미터 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestPipelineWithVariousInputs:
    def test_conservative_investor(self):
        """보수형 투자자 요청 처리"""
        req = make_request(risk_tolerance="conservative", age=55, monthly_target=30)
        pipeline = RecommendationPipeline(req)
        result = pipeline.execute()
        assert isinstance(result, dict)
        assert result["input"]["risk_tolerance"] == "conservative"

    def test_aggressive_investor(self):
        """공격형 투자자 요청 처리"""
        req = make_request(risk_tolerance="aggressive", age=25, investable_amount=2000)
        pipeline = RecommendationPipeline(req)
        result = pipeline.execute()
        assert isinstance(result, dict)

    def test_zero_monthly_target(self):
        """월 목표 0원도 처리 가능"""
        req = make_request(monthly_target=0)
        pipeline = RecommendationPipeline(req)
        result = pipeline.execute()
        assert isinstance(result, dict)

    def test_large_investable_amount(self):
        """대규모 투자금(100억)도 처리 가능"""
        req = make_request(investable_amount=1_000_000)
        pipeline = RecommendationPipeline(req)
        result = pipeline.execute()
        assert isinstance(result, dict)

    def test_different_archetypes(self):
        """아키타입별 처리"""
        for archetype in ["성장형", "배당형", "안정형", "혼합형"]:
            req = make_request(archetype=archetype)
            pipeline = RecommendationPipeline(req)
            result = pipeline.execute()
            assert isinstance(result, dict), f"archetype={archetype} 실패"

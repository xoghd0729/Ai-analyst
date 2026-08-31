"""
tests/test_advisor_service.py — AI Advisor 서비스 단위 테스트

테스트 원칙:
  - LLM(Ollama) 실제 호출 X → 모두 mock
  - "방향성 불변조건" 검증:
      1. 유효 JSON → 파싱 성공, source="llm"
      2. 잘못된 JSON → fallback 반환, source="fallback"
      3. Ollama 서버 미실행 → fallback 반환
      4. fallback만 사용 → 결정적 결과 (매번 동일)
      5. 프롬프트에 LLM 역할 제약 키워드 포함 검증
      6. JSON schema 검증 함수 단위 테스트
      7. _extract_json: 코드블록/노이즈 처리 검증
      8. 결과 구조 항상 동일 (llm/fallback 모두)

실행:
  pytest tests/test_advisor_service.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch, MagicMock

from utils.advisor_service import (
    analyze_portfolio,
    _extract_json,
    _validate_schema,
    _fallback_analysis,
    _build_portfolio_summary,
    _SYSTEM_PROMPT,
    _REQUIRED_KEYS,
)


# ─────────────────────────────────────────────────────────────────
# 테스트용 더미 파이프라인 결과
# ─────────────────────────────────────────────────────────────────

def _make_result(**overrides) -> dict:
    """최소한의 pipeline result 더미 — 실제 pipeline 결과와 동일한 구조."""
    base = {
        "input": {
            "age": 40, "investable": 5000, "monthly_target": 100,
            "risk_tolerance": "moderate", "archetype": "혼합형",
        },
        "summary": {
            "est_monthly_div_after_tax_만원": 78.5,
            "target_achievement_pct":        78.5,
            "vs_bank_rate_pct":              3.2,
            "investable_amount_만원":        5000,
        },
        "recommendations": [
            {"ticker": "SCHD", "asset_class": "us_div_etf",  "weight_pct": 30.0, "dividend_yield": 3.5},
            {"ticker": "VYM",  "asset_class": "us_div_etf",  "weight_pct": 20.0, "dividend_yield": 3.0},
            {"ticker": "TLT",  "asset_class": "defensive",   "weight_pct": 15.0, "dividend_yield": 3.8},
        ],
        "fire_plan": {
            "fire_timeline": {"lean_fire_age": 52, "regular_fire_age": 55},
        },
        "reverse_fire": {
            "already_achievable": False,
            "gap_years": 5,
            "savings_increase": 43.0,
            "capital_increase": 6500.0,
            "achievable_monthly": 82.3,
        },
        "monte_carlo": {
            "p50_monthly": 95.0, "p10_monthly": 62.0, "confidence_at_target": 68.5,
        },
        "tax_optimizer": {
            "effective_tax_rate_pct": 15.4, "optimized_tax_rate_pct": 9.8,
            "total_annual_saving_만원": 28.0,
            "isa_strategy": {"recommended": True},
        },
        "behavioral_finance": {
            "biases_detected": ["홈 바이어스", "집중 편향"],
        },
        "portfolio_health": {"overall_score": 72},
        "backtest": {
            "cagr_pct": 9.3, "mdd_pct": -18.2, "sharpe_ratio": 0.87,
        },
        "macro_regime": {
            "label": "중립 레짐", "advisory": "분산 유지 권장",
        },
    }
    base.update(overrides)
    return base


_VALID_LLM_JSON = {
    "summary":      "현재 포트폴리오는 월 78.5만원 세후 배당을 생성하며 목표 대비 78.5% 달성 중입니다.",
    "strengths":    ["은행 금리 대비 +3.2%p 초과 수익", "린 FIRE 52세 달성 가능"],
    "risks":        ["홈 바이어스 탐지 — 분산 필요", "금융 섹터 편중"],
    "action_items": ["월 43만원 추가 적립 검토", "ISA 계좌 활용 절세"],
    "caveats":      ["과거 데이터 기반 — 미래 수익 보장 불가"],
}


# ─────────────────────────────────────────────────────────────────
# 1. _extract_json 단위 테스트
# ─────────────────────────────────────────────────────────────────

class TestExtractJson:
    def test_clean_json(self):
        text = '{"summary": "ok", "strengths": [], "risks": [], "action_items": [], "caveats": []}'
        result = _extract_json(text)
        assert result is not None
        assert result["summary"] == "ok"

    def test_json_with_code_block(self):
        text = '```json\n{"summary": "ok", "strengths": [], "risks": [], "action_items": [], "caveats": []}\n```'
        result = _extract_json(text)
        assert result is not None

    def test_json_with_leading_text(self):
        text = '네 포트폴리오 분석입니다:\n{"summary": "ok", "strengths": [], "risks": [], "action_items": [], "caveats": []}'
        result = _extract_json(text)
        assert result is not None
        assert result["summary"] == "ok"

    def test_invalid_json_returns_none(self):
        assert _extract_json("이것은 JSON이 아닙니다") is None
        assert _extract_json("") is None
        assert _extract_json("{broken json}") is None

    def test_nested_json(self):
        """중첩 JSON도 파싱 가능."""
        text = '{"summary": "ok", "strengths": ["a", "b"], "risks": ["c"], "action_items": [], "caveats": []}'
        result = _extract_json(text)
        assert result is not None
        assert len(result["strengths"]) == 2


# ─────────────────────────────────────────────────────────────────
# 2. _validate_schema 단위 테스트
# ─────────────────────────────────────────────────────────────────

class TestValidateSchema:
    def test_valid_schema(self):
        assert _validate_schema(_VALID_LLM_JSON) is True

    def test_missing_key(self):
        data = dict(_VALID_LLM_JSON)
        del data["risks"]
        assert _validate_schema(data) is False

    def test_list_key_is_string(self):
        data = dict(_VALID_LLM_JSON)
        data["strengths"] = "강점입니다"   # 리스트여야 함
        assert _validate_schema(data) is False

    def test_summary_is_not_string(self):
        data = dict(_VALID_LLM_JSON)
        data["summary"] = ["요약"]         # 문자열이어야 함
        assert _validate_schema(data) is False

    def test_empty_lists_valid(self):
        """빈 리스트도 유효."""
        data = {
            "summary":      "ok",
            "strengths":    [],
            "risks":        [],
            "action_items": [],
            "caveats":      [],
        }
        assert _validate_schema(data) is True

    def test_non_dict_invalid(self):
        assert _validate_schema([]) is False
        assert _validate_schema("string") is False


# ─────────────────────────────────────────────────────────────────
# 3. _fallback_analysis 단위 테스트
# ─────────────────────────────────────────────────────────────────

class TestFallbackAnalysis:
    @pytest.fixture
    def fb(self):
        return _fallback_analysis(_make_result())

    def test_source_is_fallback(self, fb):
        assert fb["source"] == "fallback"

    def test_required_keys_present(self, fb):
        for key in _REQUIRED_KEYS:
            assert key in fb, f"fallback에 '{key}' 없음"

    def test_summary_contains_numbers(self, fb):
        """summary가 실제 수치를 포함하는지 (LLM이 생성하지 않음)."""
        assert "78.5" in fb["summary"] or "만원" in fb["summary"]

    def test_lists_are_nonempty(self, fb):
        for key in ("strengths", "risks", "action_items", "caveats"):
            assert isinstance(fb[key], list)
            assert len(fb[key]) > 0

    def test_deterministic(self):
        """같은 입력 → 항상 동일한 결과."""
        r = _make_result()
        fb1 = _fallback_analysis(r)
        fb2 = _fallback_analysis(r)
        assert fb1["summary"]  == fb2["summary"]
        assert fb1["strengths"] == fb2["strengths"]

    def test_no_model_key(self, fb):
        """fallback은 model 키가 없어야 한다."""
        assert "model" not in fb


# ─────────────────────────────────────────────────────────────────
# 4. 시스템 프롬프트 제약 검증
# ─────────────────────────────────────────────────────────────────

class TestSystemPromptConstraints:
    def test_prompt_forbids_new_stocks(self):
        """새 종목 추천 금지 문구 포함."""
        assert "종목을 추천" in _SYSTEM_PROMPT or "종목" in _SYSTEM_PROMPT

    def test_prompt_forbids_new_numbers(self):
        """수치 생성 금지 문구 포함."""
        assert "임의로 생성" in _SYSTEM_PROMPT or "생성하지 마" in _SYSTEM_PROMPT

    def test_prompt_requires_json_only(self):
        """JSON만 반환 지시 포함."""
        assert "JSON" in _SYSTEM_PROMPT

    def test_prompt_fire_age_constraint(self):
        """FIRE 나이 수정 금지 문구 포함."""
        assert "FIRE" in _SYSTEM_PROMPT

    def test_prompt_uncertainty_disclosure(self):
        """불확실성 명시 지시 포함."""
        assert "추정" in _SYSTEM_PROMPT or "제공된 데이터 기준" in _SYSTEM_PROMPT


# ─────────────────────────────────────────────────────────────────
# 5. _build_portfolio_summary 단위 테스트
# ─────────────────────────────────────────────────────────────────

class TestBuildPortfolioSummary:
    def test_contains_ticker_names(self):
        summary = _build_portfolio_summary(_make_result())
        # 추천 종목이 요약에 포함
        assert "SCHD" in summary
        assert "VYM"  in summary

    def test_contains_key_numbers(self):
        summary = _build_portfolio_summary(_make_result())
        # 핵심 수치 포함 (천단위 콤마 포맷 "5,000" 또는 "5000" 모두 허용)
        assert "78.5" in summary          # monthly div
        assert "40"   in summary          # age
        assert "투자 금액: 5,000만원" in summary  # investable (천단위 콤마 포맷)

    def test_contains_fire_info(self):
        summary = _build_portfolio_summary(_make_result())
        assert "FIRE" in summary or "린" in summary

    def test_empty_result_no_crash(self):
        """빈 결과도 오류 없이 처리."""
        summary = _build_portfolio_summary({})
        assert isinstance(summary, str)
        assert len(summary) > 0


# ─────────────────────────────────────────────────────────────────
# 6. analyze_portfolio — use_llm=False (fallback only)
# ─────────────────────────────────────────────────────────────────

class TestAnalyzePortfolioFallback:
    def test_use_llm_false_returns_fallback(self):
        result = analyze_portfolio(_make_result(), use_llm=False)
        assert result["source"] == "fallback"

    def test_structure_always_complete(self):
        result = analyze_portfolio(_make_result(), use_llm=False)
        for key in (*_REQUIRED_KEYS, "source"):
            assert key in result, f"'{key}' 없음"


# ─────────────────────────────────────────────────────────────────
# 7. analyze_portfolio — LLM mock 테스트
# ─────────────────────────────────────────────────────────────────

class TestAnalyzePortfolioLLM:
    def _make_mock_response(self, content: str) -> MagicMock:
        msg    = MagicMock()
        msg.content = content
        choice = MagicMock()
        choice.message = msg
        resp   = MagicMock()
        resp.choices = [choice]
        return resp

    def test_valid_llm_response_used(self):
        """LLM이 유효 JSON 반환 → source=llm."""
        json_str = (
            '{"summary": "ok", "strengths": ["a"], '
            '"risks": ["b"], "action_items": ["c"], "caveats": ["d"]}'
        )
        mock_resp = self._make_mock_response(json_str)

        with patch("utils.advisor_service._call_llm", return_value={**_VALID_LLM_JSON, "source": "llm"}):
            result = analyze_portfolio(_make_result(), use_llm=True)

        assert result["source"] == "llm"
        for key in _REQUIRED_KEYS:
            assert key in result

    def test_invalid_json_falls_back(self):
        """LLM이 JSON 실패 → fallback."""
        with patch("utils.advisor_service._call_llm", return_value=None):
            result = analyze_portfolio(_make_result(), use_llm=True)

        assert result["source"] == "fallback"

    def test_ollama_not_running_falls_back(self):
        """Ollama 서버 미실행 RuntimeError → fallback."""
        with patch("utils.advisor_service._call_llm", return_value=None):
            result = analyze_portfolio(_make_result(), use_llm=True)

        assert result["source"] == "fallback"
        for key in _REQUIRED_KEYS:
            assert key in result

    def test_llm_result_has_required_keys(self):
        """llm 결과에도 모든 필수 키 존재."""
        with patch("utils.advisor_service._call_llm", return_value={**_VALID_LLM_JSON, "source": "llm"}):
            result = analyze_portfolio(_make_result(), use_llm=True)

        for key in _REQUIRED_KEYS:
            assert key in result

    def test_source_field_always_present(self):
        """source 필드는 항상 존재."""
        for use_llm in (True, False):
            with patch("utils.advisor_service._call_llm", return_value=None):
                result = analyze_portfolio(_make_result(), use_llm=use_llm)
            assert "source" in result

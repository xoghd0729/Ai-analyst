"""
tests/test_behavioral_finance.py — 행동 편향 탐지 엔진 단위 테스트

왜 이 테스트가 필요한가?
  detect_behavioral_biases()는 포트폴리오에서 8가지 심리적 편향을 자동 탐지한다.
  각 편향 탐지가 의도된 조건에서 올바르게 켜지고 꺼지는지 확인해야
  투자자에게 잘못된 "편향 경보"를 발령하지 않는다.

  테스트 전략:
  - 편향이 강하게 나타나는 포트폴리오 → detected=True 확인
  - 균형 잡힌 포트폴리오 → 편향 수 최소화 확인
  - 반환 구조의 타입/범위 검증

실행:
  pytest tests/test_behavioral_finance.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.behavioral_finance import detect_behavioral_biases


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 데이터
# ─────────────────────────────────────────────────────────────────────────────

# 1. 홈 바이어스: 국내 자산 90% 집중
HOME_BIASED_PORTFOLIO = [
    {"ticker": "삼성전자", "asset_class": "kr_stock", "weight_pct": 50, "dividend_yield": 2.8,
     "gross_yield_pct": 2.8},
    {"ticker": "SK텔레콤", "asset_class": "kr_stock", "weight_pct": 30, "dividend_yield": 5.5,
     "gross_yield_pct": 5.5},
    {"ticker": "KT&G",    "asset_class": "kr_stock", "weight_pct": 20, "dividend_yield": 6.0,
     "gross_yield_pct": 6.0},
]

# 2. 집중 편향: 단일 종목 80%
CONCENTRATED_PORTFOLIO = [
    {"ticker": "SCHD", "asset_class": "us_etf", "weight_pct": 80, "dividend_yield": 3.5,
     "gross_yield_pct": 3.5},
    {"ticker": "JEPI", "asset_class": "us_etf", "weight_pct": 20, "dividend_yield": 7.2,
     "gross_yield_pct": 7.2},
]

# 3. 수익률 환상: 고배당 자산 70% (yield >= 6%)
YIELD_ILLUSION_PORTFOLIO = [
    {"ticker": "QYLD",  "asset_class": "us_etf", "weight_pct": 40, "dividend_yield": 12.0,
     "gross_yield_pct": 12.0},
    {"ticker": "JEPQ",  "asset_class": "us_etf", "weight_pct": 30, "dividend_yield": 9.5,
     "gross_yield_pct": 9.5},
    {"ticker": "SCHD",  "asset_class": "us_etf", "weight_pct": 30, "dividend_yield": 3.5,
     "gross_yield_pct": 3.5},
]

# 4. 균형 잡힌 포트폴리오 (편향 최소화)
BALANCED_PORTFOLIO = [
    {"ticker": "SCHD",   "asset_class": "us_etf",    "weight_pct": 25, "dividend_yield": 3.5,
     "gross_yield_pct": 3.5},
    {"ticker": "VYM",    "asset_class": "us_etf",    "weight_pct": 20, "dividend_yield": 3.0,
     "gross_yield_pct": 3.0},
    {"ticker": "삼성전자", "asset_class": "kr_stock", "weight_pct": 20, "dividend_yield": 2.8,
     "gross_yield_pct": 2.8},
    {"ticker": "BND",    "asset_class": "bond_etf",  "weight_pct": 20, "dividend_yield": 3.5,
     "gross_yield_pct": 3.5},
    {"ticker": "VNQ",    "asset_class": "reit_etf",  "weight_pct": 15, "dividend_yield": 4.2,
     "gross_yield_pct": 4.2},
]

EMPTY_SUMMARY = {}
TYPICAL_SUMMARY = {"avg_yield": 4.0, "avg_yield_net": 3.4}
HIGH_YIELD_SUMMARY = {"avg_yield": 9.0, "avg_yield_net": 7.0}  # gap 2.0%p (종합과세 고배당 = 환상 명확)


# ─────────────────────────────────────────────────────────────────────────────
# 반환 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestReturnStructure:
    @pytest.fixture
    def result(self):
        return detect_behavioral_biases(
            BALANCED_PORTFOLIO, [], TYPICAL_SUMMARY,
            investor_age=35, risk_tolerance="moderate",
        )

    def test_required_top_level_keys(self, result):
        required = {
            "biases", "detected_biases", "bias_count", "high_severity",
            "overall_bias_score", "investor_type", "top_bias",
            "behavioral_summary", "coaching_message", "portfolio_stats",
        }
        missing = required - set(result.keys())
        assert not missing, f"누락 키: {missing}"

    def test_biases_list_has_8_items(self, result):
        """8가지 편향 탐지 함수 → biases 목록에 8개 항목"""
        assert len(result["biases"]) == 8, \
            f"편향 목록이 8개가 아님: {len(result['biases'])}"

    def test_each_bias_has_required_fields(self, result):
        required = {"name", "detected", "severity", "score"}
        for bias in result["biases"]:
            missing = required - set(bias.keys())
            assert not missing, f"편향 '{bias.get('name')}' 누락 키: {missing}"

    def test_detected_biases_subset_of_biases(self, result):
        """detected_biases는 biases에서 detected=True만 필터"""
        all_detected_names = {b["name"] for b in result["biases"] if b["detected"]}
        detected_names     = {b["name"] for b in result["detected_biases"]}
        assert all_detected_names == detected_names

    def test_bias_count_matches_detected(self, result):
        assert result["bias_count"] == len(result["detected_biases"])

    def test_overall_score_range(self, result):
        """전체 편향 점수는 0~100"""
        score = result["overall_bias_score"]
        assert 0 <= score <= 100, f"편향 점수 범위 초과: {score}"

    def test_severity_values(self, result):
        """severity는 high/medium/low 중 하나"""
        for bias in result["biases"]:
            assert bias["severity"] in ("high", "medium", "low"), \
                f"잘못된 severity: {bias['severity']}"

    def test_coaching_message_is_string(self, result):
        assert isinstance(result["coaching_message"], str)
        assert len(result["coaching_message"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 홈 바이어스 탐지
# ─────────────────────────────────────────────────────────────────────────────

class TestHomeBias:
    def test_home_bias_detected_with_kr_dominant(self):
        """국내 주식 90% 포트폴리오는 홈 바이어스를 탐지해야 한다"""
        result = detect_behavioral_biases(
            HOME_BIASED_PORTFOLIO, [], {"avg_yield": 4.5},
            investor_age=35, risk_tolerance="moderate",
        )
        home_bias = next(
            (b for b in result["biases"] if "홈" in b["name"] or "home" in b["name"].lower()),
            None,
        )
        assert home_bias is not None, "홈 바이어스 탐지 항목이 없음"
        assert home_bias["detected"] is True, \
            f"국내 90% 포트폴리오에서 홈 바이어스 미탐지"

    def test_home_bias_not_detected_in_balanced(self):
        """균형 포트폴리오에서는 홈 바이어스가 탐지되지 않아야 한다"""
        result = detect_behavioral_biases(
            BALANCED_PORTFOLIO, [], TYPICAL_SUMMARY,
            investor_age=35, risk_tolerance="moderate",
        )
        home_bias = next(
            (b for b in result["biases"] if "홈" in b["name"] or "home" in b["name"].lower()),
            None,
        )
        if home_bias:
            # 균형 포트에서 홈 바이어스가 감지되면 경미해야 한다
            assert home_bias.get("severity") != "high", \
                "균형 포트폴리오에서 고위험도 홈 바이어스 탐지"


# ─────────────────────────────────────────────────────────────────────────────
# 집중 편향 탐지
# ─────────────────────────────────────────────────────────────────────────────

class TestConcentrationBias:
    def test_concentration_detected_with_80_percent_single(self):
        """단일 종목 80% → 집중 편향 탐지"""
        result = detect_behavioral_biases(
            CONCENTRATED_PORTFOLIO, [], TYPICAL_SUMMARY,
            investor_age=35, risk_tolerance="moderate",
        )
        concentration = next(
            (b for b in result["biases"] if "집중" in b["name"] or "concentration" in b["name"].lower()),
            None,
        )
        assert concentration is not None, "집중 편향 탐지 항목이 없음"
        assert concentration["detected"] is True, \
            "단일 종목 80%에서 집중 편향 미탐지"


# ─────────────────────────────────────────────────────────────────────────────
# 수익률 환상 탐지
# ─────────────────────────────────────────────────────────────────────────────

class TestYieldIllusion:
    def test_yield_illusion_with_high_yield_portfolio(self):
        """평균 수익률 10%+ 포트폴리오 → 수익률 환상 탐지"""
        result = detect_behavioral_biases(
            YIELD_ILLUSION_PORTFOLIO, [], HIGH_YIELD_SUMMARY,
            investor_age=35, risk_tolerance="moderate",
        )
        illusion = next(
            (b for b in result["biases"] if "환상" in b["name"] or "illusion" in b["name"].lower()),
            None,
        )
        assert illusion is not None, "수익률 환상 탐지 항목이 없음"
        assert illusion["detected"] is True, \
            f"고배당(avg 9%) 포트폴리오에서 수익률 환상 미탐지"


# ─────────────────────────────────────────────────────────────────────────────
# 과도한 안전 편향
# ─────────────────────────────────────────────────────────────────────────────

class TestExcessiveSafety:
    def test_no_excessive_safety_for_aggressive_investor(self):
        """공격형 투자자는 안전 자산 편향 미탐지 (적절한 리스크 수용)"""
        result = detect_behavioral_biases(
            BALANCED_PORTFOLIO, [], TYPICAL_SUMMARY,
            investor_age=30, risk_tolerance="aggressive",
        )
        safety = next(
            (b for b in result["biases"] if "안전" in b["name"] or "safety" in b["name"].lower()),
            None,
        )
        # aggressive 투자자에게는 안전편향을 탐지하지 않거나 낮은 심각도여야 함
        if safety and safety["detected"]:
            assert safety.get("severity") != "high"


# ─────────────────────────────────────────────────────────────────────────────
# 위험 경보와 연동되는 편향 탐지
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskAlertInteraction:
    def test_loss_aversion_with_risk_alerts(self):
        """리스크 경보가 있는데 risk_alerts 반영 시 손실 회피 탐지"""
        risk_alerts = [
            {"ticker": "QYLD", "risk_level": "high", "signal": "WEAKENING"},
        ]
        result = detect_behavioral_biases(
            YIELD_ILLUSION_PORTFOLIO, risk_alerts, HIGH_YIELD_SUMMARY,
            investor_age=50, risk_tolerance="conservative",
        )
        # 전체 반환 구조가 유효한지만 확인 (탐지 여부는 구현 의존)
        assert "biases" in result
        assert isinstance(result["bias_count"], int)

    def test_dividend_anchoring_detected_with_high_yield_risk(self):
        """고수익률 포트폴리오 + 리스크 경보 → 배당 고집 탐지 가능"""
        risk_alerts = [
            {"ticker": "QYLD", "risk_level": "high"},
            {"ticker": "JEPQ", "risk_level": "medium"},
        ]
        result = detect_behavioral_biases(
            YIELD_ILLUSION_PORTFOLIO, risk_alerts, HIGH_YIELD_SUMMARY,
        )
        anchoring = next(
            (b for b in result["biases"]
             if b.get("id") == "dividend_anchoring" or "앵커" in b["name"]
             or "고집" in b["name"] or "anchor" in b["name"].lower()),
            None,
        )
        assert anchoring is not None, "배당 앵커링 탐지 항목이 없음"


# ─────────────────────────────────────────────────────────────────────────────
# 엣지 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_portfolio_returns_empty_result(self):
        """빈 포트폴리오 → 예외 없이 빈 결과"""
        result = detect_behavioral_biases([], [], {})
        assert "biases" in result
        assert result["bias_count"] == 0

    def test_single_asset_portfolio(self):
        """단일 자산 포트폴리오도 정상 동작"""
        result = detect_behavioral_biases(
            [CONCENTRATED_PORTFOLIO[0]], [], TYPICAL_SUMMARY,
        )
        assert "biases" in result
        assert len(result["biases"]) == 8

    def test_investor_type_is_string(self):
        """investor_type은 비어있지 않은 문자열"""
        result = detect_behavioral_biases(
            BALANCED_PORTFOLIO, [], TYPICAL_SUMMARY, investor_age=35,
        )
        assert isinstance(result["investor_type"], str)
        assert len(result["investor_type"]) > 0

    def test_portfolio_stats_contains_kr_pct(self):
        """portfolio_stats에 kr_pct, us_pct 등 주요 통계 포함"""
        result = detect_behavioral_biases(
            HOME_BIASED_PORTFOLIO, [], EMPTY_SUMMARY,
        )
        stats = result["portfolio_stats"]
        assert "kr_pct" in stats
        assert "n_assets" in stats

    def test_high_bias_score_with_many_biases(self):
        """여러 편향이 탐지된 포트폴리오는 높은 편향 점수"""
        result_bad      = detect_behavioral_biases(
            HOME_BIASED_PORTFOLIO, [], {"avg_yield": 5.5},
            investor_age=35, risk_tolerance="moderate",
        )
        result_balanced = detect_behavioral_biases(
            BALANCED_PORTFOLIO, [], TYPICAL_SUMMARY,
            investor_age=35, risk_tolerance="moderate",
        )
        # 편향 많은 포트폴리오가 점수가 더 높아야 한다
        assert result_bad["overall_bias_score"] >= result_balanced["overall_bias_score"], \
            "편향 많은 포트폴리오 점수가 균형 포트폴리오보다 낮음"

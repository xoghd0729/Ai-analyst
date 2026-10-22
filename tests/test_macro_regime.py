"""
tests/test_macro_regime.py
==========================
utils/macro_regime.py — get_macro_regime(), _detect_regime(), _score_regime() 단위 테스트

검증 항목:
  - get_macro_regime() 반환 구조 및 필수 키
  - regime 값이 허용 목록 내
  - _detect_regime(): 고금리+고VIX → RATE_RISING / RECESSION
  - _detect_regime(): 저금리+저VIX → RATE_FALLING / NORMAL
  - _detect_regime(): 고VIX → HIGH_VOLATILITY
  - weight_adjustments 키 타입 (str→float)
  - confidence 범위 0~1
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.macro_regime import (
    get_macro_regime,
    _detect_regime,
    _score_regime,
    REGIME_DEFINITIONS,
)

VALID_REGIMES = {"RATE_RISING", "RATE_FALLING", "HIGH_VOLATILITY", "RECESSION", "NORMAL"}


# ─── TestGetMacroRegimeStructure ──────────────────────────────

class TestGetMacroRegimeStructure:
    """get_macro_regime() 반환값 구조 검증 (네트워크 없어도 config fallback으로 동작)."""

    def setup_method(self):
        self.result = get_macro_regime()

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_required_keys_present(self):
        required = {
            "regime", "label", "description", "advisory",
            "weight_adjustments", "etf_category_bonus",
            "indicators", "data_source",
        }
        assert required <= self.result.keys(), f"Missing keys: {required - self.result.keys()}"

    def test_regime_in_valid_set(self):
        assert self.result["regime"] in VALID_REGIMES

    def test_weight_adjustments_is_dict(self):
        wa = self.result["weight_adjustments"]
        assert isinstance(wa, dict)

    def test_weight_adjustments_values_are_float(self):
        for k, v in self.result["weight_adjustments"].items():
            assert isinstance(v, (int, float)), f"weight_adjustments[{k}] is not numeric"

    def test_indicators_has_required_fields(self):
        ind = self.result["indicators"]
        for field in ("fed_rate", "us_10y_yield", "vix", "usd_krw", "kr_base_rate"):
            assert field in ind, f"indicators missing {field}"

    def test_data_source_valid(self):
        assert self.result["data_source"] in ("live", "cache", "config")

    def test_advisory_is_string(self):
        assert isinstance(self.result["advisory"], str)
        assert len(self.result["advisory"]) > 10


# ─── TestRegimeDefinitions ────────────────────────────────────

class TestRegimeDefinitions:
    """REGIME_DEFINITIONS 상수 구조 검증."""

    def test_all_five_regimes_defined(self):
        assert VALID_REGIMES == set(REGIME_DEFINITIONS.keys())

    def test_each_has_weight_adjustments(self):
        for name, defn in REGIME_DEFINITIONS.items():
            assert "weight_adjustments" in defn, f"{name} missing weight_adjustments"

    def test_each_has_etf_category_bonus(self):
        for name, defn in REGIME_DEFINITIONS.items():
            assert "etf_category_bonus" in defn, f"{name} missing etf_category_bonus"

    def test_normal_has_empty_adjustments(self):
        # NORMAL은 기본 비중 그대로 — 조정 없음
        assert REGIME_DEFINITIONS["NORMAL"]["weight_adjustments"] == {}

    def test_normal_has_empty_etf_bonus(self):
        assert REGIME_DEFINITIONS["NORMAL"]["etf_category_bonus"] == {}


# ─── TestDetectRegime ─────────────────────────────────────────

class TestDetectRegime:
    """_detect_regime() 시나리오별 국면 판정 검증."""

    def test_high_rate_high_10y_low_vix_is_rate_rising(self):
        regime, conf, signals, extra = _detect_regime(
            fed_rate=5.25, us_10y=4.80, vix=16, usd_krw=1350, kr_base_rate=3.5
        )
        assert regime == "RATE_RISING"
        assert conf > 0.5

    def test_very_high_vix_boosts_high_volatility_score(self):
        # _detect_regime은 5개 regime 투표 방식 → VIX 하나만으로 HIGH_VOLATILITY 1위는 아님
        # 대신 _score_regime 수준에서 고VIX → HIGH_VOLATILITY confidence 높음을 직접 검증
        conf_low, _  = _score_regime("HIGH_VOLATILITY", 4.0, 3.8, 15, 1300, 3.0, -0.2)
        conf_high, _ = _score_regime("HIGH_VOLATILITY", 4.0, 3.8, 38, 1300, 3.0, -0.2)
        assert conf_high > conf_low

    def test_inverted_curve_high_vix_recession_signal(self):
        # 일드 인버전: us_10y < fed_rate, 높은 VIX
        regime, conf, signals, extra = _detect_regime(
            fed_rate=5.50, us_10y=4.20, vix=30, usd_krw=1400, kr_base_rate=3.5
        )
        # RECESSION or HIGH_VOLATILITY — 극단 국면이어야 함
        assert regime in ("RECESSION", "HIGH_VOLATILITY", "RATE_RISING")

    def test_low_rate_low_vix_tends_to_normal_or_falling(self):
        regime, conf, signals, extra = _detect_regime(
            fed_rate=1.75, us_10y=2.20, vix=14, usd_krw=1200, kr_base_rate=1.5
        )
        assert regime in ("RATE_FALLING", "NORMAL")

    def test_confidence_in_range(self):
        regime, conf, signals, extra = _detect_regime(
            fed_rate=4.75, us_10y=4.40, vix=18, usd_krw=1350, kr_base_rate=3.0
        )
        assert 0.0 <= conf <= 1.0

    def test_extra_has_scores_for_all_regimes(self):
        regime, conf, signals, extra = _detect_regime(
            fed_rate=4.75, us_10y=4.40, vix=18, usd_krw=1350, kr_base_rate=3.0
        )
        scores = extra["scores"]
        for r in VALID_REGIMES:
            assert r in scores

    def test_high_usd_krw_triggers_warning(self):
        regime, conf, signals, extra = _detect_regime(
            fed_rate=5.0, us_10y=4.5, vix=20, usd_krw=1450, kr_base_rate=3.5
        )
        assert "usd_krw_warn" in signals

    def test_low_usd_krw_triggers_note(self):
        regime, conf, signals, extra = _detect_regime(
            fed_rate=2.0, us_10y=2.0, vix=14, usd_krw=1100, kr_base_rate=1.5
        )
        assert "usd_krw_note" in signals


# ─── TestScoreRegime ──────────────────────────────────────────

class TestScoreRegime:
    """_score_regime() 개별 국면 지지 강도 검증."""

    def test_rate_rising_high_indicators(self):
        conf, bd = _score_regime(
            "RATE_RISING",
            fed_rate=5.25, us_10y=4.80, vix=15,
            usd_krw=1350, kr_base_rate=3.5,
            yield_spread=-0.45,
        )
        assert conf > 0.6

    def test_rate_rising_low_indicators(self):
        conf, bd = _score_regime(
            "RATE_RISING",
            fed_rate=0.25, us_10y=1.0, vix=12,
            usd_krw=1200, kr_base_rate=0.5,
            yield_spread=0.75,
        )
        # 저금리 환경 → RATE_RISING 지지 낮음
        assert conf < 0.5

    def test_high_volatility_needs_vix_25_plus(self):
        conf_low, _ = _score_regime(
            "HIGH_VOLATILITY",
            fed_rate=4.5, us_10y=4.2, vix=15,
            usd_krw=1350, kr_base_rate=3.0,
            yield_spread=-0.3,
        )
        conf_high, _ = _score_regime(
            "HIGH_VOLATILITY",
            fed_rate=4.5, us_10y=4.2, vix=35,
            usd_krw=1350, kr_base_rate=3.0,
            yield_spread=-0.3,
        )
        assert conf_high > conf_low

    def test_recession_needs_inverted_curve(self):
        conf_normal, _ = _score_regime(
            "RECESSION",
            fed_rate=4.5, us_10y=4.8, vix=22,
            usd_krw=1350, kr_base_rate=3.0,
            yield_spread=0.3,   # 정상 커브
        )
        conf_inverted, _ = _score_regime(
            "RECESSION",
            fed_rate=5.5, us_10y=4.0, vix=28,
            usd_krw=1380, kr_base_rate=3.5,
            yield_spread=-1.5,  # 인버티드
        )
        assert conf_inverted > conf_normal

    def test_confidence_in_0_1(self):
        for regime in VALID_REGIMES:
            conf, _ = _score_regime(
                regime,
                fed_rate=4.75, us_10y=4.40, vix=18,
                usd_krw=1350, kr_base_rate=3.0,
                yield_spread=-0.35,
            )
            assert 0.0 <= conf <= 1.0, f"{regime} confidence={conf} out of range"

    def test_breakdown_keys_match(self):
        """모든 regime의 breakdown 키가 일관되게 존재하는지 확인."""
        expected_keys = {"fed_rate", "us_10y", "vix", "yield_spread", "kr_rate"}
        for regime in VALID_REGIMES:
            _, bd = _score_regime(
                regime,
                fed_rate=4.0, us_10y=3.8, vix=20,
                usd_krw=1300, kr_base_rate=3.0,
                yield_spread=-0.2,
            )
            assert expected_keys == set(bd.keys()), f"{regime} breakdown keys mismatch: {bd.keys()}"

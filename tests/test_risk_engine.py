"""
tests/test_risk_engine.py
=========================
utils/risk_engine.py — score_asset(), score_portfolio() 단위 테스트

검증 항목:
  - composite_risk_score 범위 (0~100)
  - risk_gate 분류 정확성 (PASS/WARN/BLOCK)
  - 70:30 가중치 (_W_STATUS=0.70, _W_SURVIVAL=0.30) 유지 확인
  - _ML_SCORE 매핑 (INTACT=15, WEAKENING=55, BROKEN=90)
  - ETF 자산 hazard 고정 (0.2)
  - conservative 임계값 엄격성 (50에서 BLOCK)
  - score_portfolio() 구조 및 필드 부착
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.risk_engine import (
    score_asset,
    score_portfolio,
    _W_STATUS,
    _W_SURVIVAL,
    _ML_SCORE,
    _GATE_BY_RISK,
    _hazard_to_score,
)


# ─── TestConstants ────────────────────────────────────────────

class TestConstants:
    """70:30 가중치 및 ML_SCORE 매핑이 변경되지 않았는지 확인."""

    def test_w_status_is_0_70(self):
        assert _W_STATUS == 0.70, "70:30 가중치 플레이스홀더 — 변경 금지"

    def test_w_survival_is_0_30(self):
        assert _W_SURVIVAL == 0.30

    def test_w_sum_is_1(self):
        assert abs(_W_STATUS + _W_SURVIVAL - 1.0) < 1e-9

    def test_ml_score_intact(self):
        assert _ML_SCORE["INTACT"] == 15.0

    def test_ml_score_weakening(self):
        assert _ML_SCORE["WEAKENING"] == 55.0

    def test_ml_score_broken(self):
        assert _ML_SCORE["BROKEN"] == 90.0

    def test_conservative_gate_strictest(self):
        # conservative < moderate < aggressive
        assert _GATE_BY_RISK["conservative"] < _GATE_BY_RISK["moderate"]
        assert _GATE_BY_RISK["moderate"] < _GATE_BY_RISK["aggressive"]


# ─── TestHazardToScore ────────────────────────────────────────

class TestHazardToScore:
    def test_zero_hazard(self):
        assert _hazard_to_score(0.0) == 0.0

    def test_full_hazard(self):
        assert _hazard_to_score(1.0) == 100.0

    def test_half_hazard(self):
        assert _hazard_to_score(0.5) == 50.0

    def test_none_returns_midpoint(self):
        assert _hazard_to_score(None) == 50.0

    def test_clamp_above_1(self):
        assert _hazard_to_score(2.0) == 100.0


# ─── TestScoreAssetReturnStructure ───────────────────────────

class TestScoreAssetReturnStructure:
    def setup_method(self):
        self.result = score_asset(
            ticker="005930",
            asset_class="kr_stock",
            ml_status="INTACT",
            survival_hazard=0.3,
            macro=None,
            risk_tolerance="moderate",
        )

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_required_keys_present(self):
        required = {
            "composite_risk_score",
            "risk_gate",
            "status_score",
            "layer2_survival",
            "layer3_macro",
            "hazard",
        }
        assert required <= self.result.keys()

    def test_composite_score_in_range(self):
        assert 0.0 <= self.result["composite_risk_score"] <= 100.0

    def test_risk_gate_valid(self):
        assert self.result["risk_gate"] in ("PASS", "WARN", "BLOCK")

    def test_layer3_macro_is_zero(self):
        # Macro는 composite에서 제외 (_W_MACRO = 0.0)
        assert self.result["layer3_macro"] == 0.0


# ─── TestCompositeScoreMath ───────────────────────────────────

class TestCompositeScoreMath:
    """70:30 가중치 공식 직접 검증."""

    def test_intact_known_hazard(self):
        # status_score = 15.0, surv_score = 0.3*100=30.0
        # composite = 15*0.70 + 30*0.30 = 10.5 + 9.0 = 19.5
        r = score_asset("KO", "us_stock", "INTACT", 0.30, None, "moderate")
        assert abs(r["composite_risk_score"] - 19.5) < 0.5

    def test_weakening_known_hazard(self):
        # status_score = 55.0, surv_score = 0.55*100=55.0
        # composite = 55*0.70 + 55*0.30 = 38.5 + 16.5 = 55.0
        r = score_asset("035420", "kr_stock", "WEAKENING", 0.55, None, "moderate")
        assert abs(r["composite_risk_score"] - 55.0) < 0.5

    def test_broken_high_hazard(self):
        # status_score = 90.0, surv_score = 0.8*100=80.0
        # composite = 90*0.70 + 80*0.30 = 63.0 + 24.0 = 87.0
        r = score_asset("009150", "kr_stock", "BROKEN", 0.80, None, "moderate")
        assert abs(r["composite_risk_score"] - 87.0) < 0.5


# ─── TestRiskGate ─────────────────────────────────────────────

class TestRiskGate:
    """risk_gate 임계값별 PASS/WARN/BLOCK 분기."""

    def test_intact_low_hazard_passes(self):
        r = score_asset("SCHD", "us_div_etf", "INTACT", 0.1, None, "moderate")
        assert r["risk_gate"] == "PASS"

    def test_conservative_blocks_at_50(self):
        # WEAKENING + hazard=0.55 → composite=55.0 → conservative gate=50 → BLOCK
        r = score_asset("035420", "kr_stock", "WEAKENING", 0.55, None, "conservative")
        assert r["risk_gate"] == "BLOCK"

    def test_moderate_warns_between_50_and_65(self):
        # composite ~55 → moderate gate=65 → WARN
        r = score_asset("035420", "kr_stock", "WEAKENING", 0.55, None, "moderate")
        assert r["risk_gate"] == "WARN"

    def test_aggressive_allows_warn_zone(self):
        # composite ~55 → aggressive gate=75 → WARN (not BLOCK)
        r = score_asset("035420", "kr_stock", "WEAKENING", 0.55, None, "aggressive")
        assert r["risk_gate"] in ("WARN", "PASS")

    def test_broken_blocks_on_aggressive(self):
        # BROKEN + high hazard → composite ~87 → aggressive gate=75 → BLOCK
        r = score_asset("009150", "kr_stock", "BROKEN", 0.80, None, "aggressive")
        assert r["risk_gate"] == "BLOCK"


# ─── TestETFHandling ──────────────────────────────────────────

class TestETFHandling:
    """ETF 자산은 Survival 모델 미적용 → hazard=0.2 고정."""

    def test_etf_hazard_fixed(self):
        r = score_asset("SCHD", "us_div_etf", "INTACT", None, None, "moderate")
        assert r["hazard"] == 0.2

    def test_us_etf_class_also_fixed(self):
        r = score_asset("JEPI", "us_etf", "INTACT", None, None, "moderate")
        assert r["hazard"] == 0.2

    def test_etf_score_lower_than_broken_stock(self):
        etf = score_asset("SCHD", "us_div_etf", "INTACT", None, None, "moderate")
        stock = score_asset("009150", "kr_stock", "BROKEN", 0.80, None, "moderate")
        assert etf["composite_risk_score"] < stock["composite_risk_score"]


# ─── TestMacroRegime ──────────────────────────────────────────

class TestMacroRegime:
    """Macro는 composite에서 제외, macro_regime 필드 반환은 유지."""

    def test_macro_regime_field_present(self):
        r = score_asset("KO", "us_stock", "INTACT", 0.2, {"regime": "BEARISH"}, "moderate")
        assert "macro_regime" in r

    def test_bearish_macro_does_not_change_score(self):
        r_neutral = score_asset("KO", "us_stock", "INTACT", 0.2, {"regime": "NEUTRAL"}, "moderate")
        r_bearish  = score_asset("KO", "us_stock", "INTACT", 0.2, {"regime": "BEARISH"}, "moderate")
        # W_MACRO=0.0 이므로 점수 동일해야 함
        assert r_neutral["composite_risk_score"] == r_bearish["composite_risk_score"]

    def test_none_macro_is_neutral(self):
        r = score_asset("KO", "us_stock", "INTACT", 0.2, None, "moderate")
        assert r["macro_regime"] == "NEUTRAL"


# ─── TestScorePortfolio ───────────────────────────────────────

class TestScorePortfolio:
    def setup_method(self):
        self.recs = [
            {"ticker": "005930", "asset_class": "kr_stock",  "ml_status": "INTACT",    "survival_risk_score": 0.2},
            {"ticker": "035420", "asset_class": "kr_stock",  "ml_status": "WEAKENING", "survival_risk_score": 0.55},
            {"ticker": "SCHD",   "asset_class": "us_div_etf","ml_status": "INTACT",    "survival_risk_score": None},
        ]
        self.scored = score_portfolio(self.recs, macro=None, risk_tolerance="moderate")

    def test_returns_list_same_length(self):
        assert isinstance(self.scored, list)
        assert len(self.scored) == len(self.recs)

    def test_each_item_has_composite_score(self):
        for item in self.scored:
            assert "composite_risk_score" in item

    def test_does_not_mutate_original(self):
        # 원본 recs에 composite_risk_score 없어야 함
        for rec in self.recs:
            assert "composite_risk_score" not in rec

    def test_broken_stock_highest_score(self):
        broken_recs = [
            {"ticker": "INTACT_STOCK",  "asset_class": "kr_stock", "ml_status": "INTACT",    "survival_risk_score": 0.2},
            {"ticker": "BROKEN_STOCK",  "asset_class": "kr_stock", "ml_status": "BROKEN",    "survival_risk_score": 0.9},
        ]
        scored = score_portfolio(broken_recs, None, "moderate")
        by_ticker = {s["ticker"]: s for s in scored}
        assert by_ticker["BROKEN_STOCK"]["composite_risk_score"] > by_ticker["INTACT_STOCK"]["composite_risk_score"]

    def test_empty_list_returns_empty(self):
        result = score_portfolio([], None, "moderate")
        assert result == []

"""
tests/test_rebalancer.py
========================
utils/rebalancer.py — generate_rebalancing_plan() 단위 테스트

검증 항목:
  - 반환 구조 (drift_alerts, tactical_shifts, signal_swaps, summary)
  - 비중 이탈 5%p 이상 → drift_alert 생성
  - BROKEN 종목 → signal_swap "긴급"
  - WEAKENING + weight>5 → signal_swap "권장"
  - RATE_RISING 매크로 → long_bond→cash_equivalent swap 제안
  - urgency 결정 로직
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.rebalancer import generate_rebalancing_plan, DRIFT_THRESHOLD_PCT, MACRO_TACTICAL_SHIFTS


def _make_recs(**overrides):
    recs = [
        {"ticker": "SCHD",   "asset_class": "us_div_etf",  "etf_category": "dividend_growth",
         "weight_pct": 40, "ml_status": "INTACT",    "trap_level": "SAFE"},
        {"ticker": "JEPI",   "asset_class": "us_div_etf",  "etf_category": "monthly_income",
         "weight_pct": 30, "ml_status": "INTACT",    "trap_level": "SAFE"},
        {"ticker": "005930", "asset_class": "kr_stock",     "etf_category": "",
         "weight_pct": 30, "ml_status": "INTACT",    "trap_level": "SAFE"},
    ]
    for rec in recs:
        rec.update(overrides.get(rec["ticker"], {}))
    return recs


# ─── TestConstants ─────────────────────────────────────────────

class TestConstants:
    def test_drift_threshold_is_5(self):
        assert DRIFT_THRESHOLD_PCT == 5.0

    def test_all_five_regimes_in_tactical(self):
        required = {"RATE_RISING", "RATE_FALLING", "HIGH_VOLATILITY", "RECESSION", "NORMAL"}
        assert required == set(MACRO_TACTICAL_SHIFTS.keys())

    def test_normal_has_no_swaps(self):
        assert MACRO_TACTICAL_SHIFTS["NORMAL"]["swap_suggestions"] == []


# ─── TestReturnStructure ───────────────────────────────────────

class TestReturnStructure:
    def setup_method(self):
        self.result = generate_rebalancing_plan(
            current_recs=_make_recs(),
            target_axis_w={"kr_stock": 0.30, "us_etf": 0.40, "us_stock": 0.10, "reit": 0.10, "defensive": 0.10},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )

    def test_returns_dict(self):
        assert isinstance(self.result, dict)

    def test_required_keys(self):
        required = {"drift_alerts", "tactical_shifts", "signal_swaps", "summary"}
        assert required <= self.result.keys()

    def test_summary_has_urgency(self):
        assert "urgency" in self.result["summary"]
        assert self.result["summary"]["urgency"] in ("긴급", "권장", "정기")

    def test_summary_has_total_actions(self):
        assert "total_actions" in self.result["summary"]

    def test_drift_alerts_is_list(self):
        assert isinstance(self.result["drift_alerts"], list)

    def test_signal_swaps_is_list(self):
        assert isinstance(self.result["signal_swaps"], list)


# ─── TestDriftAlerts ───────────────────────────────────────────

class TestDriftAlerts:
    def test_over_drift_triggers_alert(self):
        # kr_stock: current=30%, target=10% → drift=20%p > 5% → alert
        result = generate_rebalancing_plan(
            current_recs=_make_recs(),
            target_axis_w={"kr_stock": 0.10, "us_etf": 0.60, "us_stock": 0.10, "reit": 0.10, "defensive": 0.10},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        tickers = [a["asset_class"] for a in result["drift_alerts"]]
        assert "kr_stock" in tickers

    def test_no_drift_no_alerts(self):
        # current = target 거의 일치 → drift alert 없음
        result = generate_rebalancing_plan(
            current_recs=_make_recs(),
            target_axis_w={"kr_stock": 0.30, "us_etf": 0.70},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        # kr_stock 30%/30% → drift 0
        kr_alerts = [a for a in result["drift_alerts"] if a["asset_class"] == "kr_stock"]
        assert len(kr_alerts) == 0

    def test_drift_alert_has_required_keys(self):
        result = generate_rebalancing_plan(
            current_recs=_make_recs(),
            target_axis_w={"kr_stock": 0.05},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        if result["drift_alerts"]:
            alert = result["drift_alerts"][0]
            for k in ("asset_class", "current_pct", "target_pct", "drift_pct", "action", "amount_만원"):
                assert k in alert

    def test_drift_action_direction(self):
        # kr_stock current=30% > target=5% → "매도 축소"
        result = generate_rebalancing_plan(
            current_recs=_make_recs(),
            target_axis_w={"kr_stock": 0.05},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        kr_alerts = [a for a in result["drift_alerts"] if a["asset_class"] == "kr_stock"]
        if kr_alerts:
            assert kr_alerts[0]["action"] == "매도 축소"


# ─── TestSignalSwaps ────────────────────────────────────────────

class TestSignalSwaps:
    def test_broken_triggers_urgent_swap(self):
        recs = _make_recs()
        recs[2]["ml_status"] = "BROKEN"
        recs[2]["weight_pct"] = 15  # >2% 조건 충족
        result = generate_rebalancing_plan(
            recs,
            target_axis_w={"kr_stock": 0.30, "us_etf": 0.70},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        broken_swaps = [s for s in result["signal_swaps"] if s.get("urgency") == "긴급"]
        assert len(broken_swaps) >= 1
        assert result["summary"]["urgency"] == "긴급"

    def test_broken_below_weight_threshold_ignored(self):
        # weight_pct=1 (<2%) → BROKEN이어도 signal_swap 안 생성
        recs = _make_recs()
        recs[2]["ml_status"] = "BROKEN"
        recs[2]["weight_pct"] = 1
        result = generate_rebalancing_plan(
            recs,
            target_axis_w={"kr_stock": 0.30, "us_etf": 0.70},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        broken_swaps = [s for s in result["signal_swaps"] if "BROKEN" in s.get("signal", "")]
        assert len(broken_swaps) == 0

    def test_weakening_high_weight_triggers_swap(self):
        recs = _make_recs()
        recs[2]["ml_status"] = "WEAKENING"
        recs[2]["weight_pct"] = 10  # >5% 조건 충족
        result = generate_rebalancing_plan(
            recs,
            target_axis_w={"kr_stock": 0.30, "us_etf": 0.70},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        weakening = [s for s in result["signal_swaps"] if "WEAKENING" in s.get("signal", "")]
        assert len(weakening) >= 1

    def test_yield_trap_danger_triggers_swap(self):
        recs = _make_recs()
        recs[1]["trap_level"] = "DANGER"
        recs[1]["weight_pct"] = 10  # >3%
        result = generate_rebalancing_plan(
            recs,
            target_axis_w={"kr_stock": 0.30, "us_etf": 0.70},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        trap_swaps = [s for s in result["signal_swaps"] if "YIELD_TRAP" in s.get("signal", "")]
        assert len(trap_swaps) >= 1


# ─── TestTacticalShifts ────────────────────────────────────────

class TestTacticalShifts:
    def test_rate_rising_suggests_long_bond_to_cash(self):
        recs = _make_recs()
        # JEPI를 long_bond category로 변경
        recs[1]["etf_category"] = "long_bond"
        recs[1]["weight_pct"] = 20  # >3%
        result = generate_rebalancing_plan(
            recs,
            target_axis_w={"us_etf": 0.70, "kr_stock": 0.30},
            macro_regime={"regime": "RATE_RISING"},
            investable_amount=5000,
        )
        # long_bond→cash_equivalent swap이 있어야 함
        shifts = result["tactical_shifts"]
        from_cats = [s["from_category"] for s in shifts]
        assert "long_bond" in from_cats

    def test_normal_no_tactical_shifts(self):
        result = generate_rebalancing_plan(
            _make_recs(),
            target_axis_w={"us_etf": 0.70, "kr_stock": 0.30},
            macro_regime={"regime": "NORMAL"},
            investable_amount=5000,
        )
        # NORMAL → swap_suggestions=[] → tactical_shifts 없음
        assert result["tactical_shifts"] == []


# ─── TestEdgeCases ─────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_recs_no_crash(self):
        result = generate_rebalancing_plan([], {}, None, 5000)
        assert isinstance(result, dict)
        assert result["signal_swaps"] == []

    def test_none_macro_no_crash(self):
        result = generate_rebalancing_plan(_make_recs(), {"us_etf": 0.70}, None, 5000)
        assert isinstance(result, dict)

    def test_total_actions_counts_all_three(self):
        recs = _make_recs()
        recs[2]["ml_status"] = "BROKEN"
        recs[2]["weight_pct"] = 15
        recs[1]["etf_category"] = "long_bond"
        recs[1]["weight_pct"] = 20
        result = generate_rebalancing_plan(
            recs,
            target_axis_w={"kr_stock": 0.05},   # drift 발생
            macro_regime={"regime": "RATE_RISING"},
            investable_amount=5000,
        )
        expected = len(result["drift_alerts"]) + len(result["tactical_shifts"]) + len(result["signal_swaps"])
        assert result["summary"]["total_actions"] == expected

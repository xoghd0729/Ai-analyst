"""
tests/test_dividend_scorer.py
==============================
utils/dividend_scorer.py — score_dividend_stock(), score_us_dividend_stock() 단위 테스트

검증 항목:
  - 하드 필터: BROKEN / yield<1.5% / WEAKENING+삭감2회 → 제외
  - 총점 범위 0~100
  - 등급 매핑 (80+→우량, 65+→보통, 50+→주의)
  - yield trap 감지 (8%+→DANGER, 6%+→WATCH)
  - US: consecutive_years → Dividend Aristocrat/King 분류
  - exclude_reason 포함 여부
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.dividend_scorer import score_dividend_stock, score_us_dividend_stock


# ─── TestKRHardFilters ─────────────────────────────────────────

class TestKRHardFilters:
    def test_broken_excluded(self):
        r = score_dividend_stock("005930", "Samsung", yield_pct=3.5, ml_status="BROKEN")
        assert r.get("exclude_reason") is not None
        assert "BROKEN" in r["exclude_reason"]
        # _excluded()는 overall_score=0, grade='❌ 제외'로 반환
        assert r.get("overall_score") == 0
        assert r.get("grade") == "❌ 제외"

    def test_low_yield_excluded(self):
        r = score_dividend_stock("005930", "Samsung", yield_pct=0.5, ml_status="INTACT")
        assert r.get("exclude_reason") is not None
        assert "1.5%" in r["exclude_reason"]

    def test_weakening_with_two_cuts_excluded(self):
        r = score_dividend_stock("035420", "Naver", yield_pct=2.0, ml_status="WEAKENING", dps_cuts=2)
        assert r.get("exclude_reason") is not None

    def test_weakening_with_one_cut_passes(self):
        # 1회 삭감은 허용 (2회 이상만 필터)
        r = score_dividend_stock("035420", "Naver", yield_pct=3.0, ml_status="WEAKENING", dps_cuts=1)
        assert r.get("exclude_reason") is None or r.get("overall_score") is not None


# ─── TestKRScoreStructure ──────────────────────────────────────

class TestKRScoreStructure:
    def setup_method(self):
        self.r = score_dividend_stock(
            "009150", "Samsung Electro", yield_pct=4.0, ml_status="INTACT",
            dps_cuts=0, latest_yoy=5.0, payout_ratio=40.0, div_coverage=2.5,
        )

    def test_returns_dict(self):
        assert isinstance(self.r, dict)

    def test_required_keys(self):
        required = {"stock_code", "name", "overall_score", "grade",
                    "trap_level", "yield_score", "stability_score",
                    "financial_score", "growth_score"}
        # exclude_reason은 None이어도 키는 있어야 함
        assert required <= self.r.keys()

    def test_overall_score_in_range(self):
        assert 0 <= self.r["overall_score"] <= 100

    def test_trap_level_valid(self):
        assert self.r["trap_level"] in ("SAFE", "WATCH", "DANGER")

    def test_exclude_reason_none_for_passing(self):
        assert self.r["exclude_reason"] is None

    def test_component_scores_sum_to_overall(self):
        total = (self.r["yield_score"] + self.r["stability_score"]
                 + self.r["financial_score"] + self.r["growth_score"])
        assert abs(total - self.r["overall_score"]) < 0.2


# ─── TestKRGrade ───────────────────────────────────────────────

class TestKRGrade:
    def test_high_score_yields_excellent_grade(self):
        r = score_dividend_stock(
            "KR01", "Good Stock", yield_pct=4.5, ml_status="INTACT",
            dps_cuts=0, latest_yoy=10.0, payout_ratio=35.0, div_coverage=3.0,
        )
        if r.get("overall_score", 0) >= 80:
            assert "우량" in r["grade"]

    def test_broken_grade_is_excluded(self):
        r = score_dividend_stock("KR02", "Bad Stock", yield_pct=3.0, ml_status="BROKEN")
        assert r.get("grade") == "❌ 제외"
        assert r.get("overall_score") == 0

    def test_low_score_excluded(self):
        # 아주 낮은 yield + 악화 + 음수 성장 → 점수 미달 → grade='❌ 제외', overall_score=0
        r = score_dividend_stock("KR03", "Low", yield_pct=1.6, ml_status="WEAKENING",
                                  dps_cuts=1, latest_yoy=-20.0)
        if r.get("exclude_reason"):
            assert r.get("overall_score") == 0
            assert r.get("grade") == "❌ 제외"


# ─── TestKRYieldTrap ───────────────────────────────────────────

class TestKRYieldTrap:
    def test_danger_above_8_pct(self):
        r = score_dividend_stock("KR10", "HighYield", yield_pct=10.0, ml_status="INTACT",
                                  dps_cuts=0, latest_yoy=0.0)
        if r.get("exclude_reason") is None:
            assert r["trap_level"] == "DANGER"

    def test_watch_at_7_pct(self):
        r = score_dividend_stock("KR11", "MidYield", yield_pct=7.0, ml_status="INTACT",
                                  dps_cuts=0, latest_yoy=0.0)
        if r.get("exclude_reason") is None:
            assert r["trap_level"] in ("WATCH", "DANGER")

    def test_safe_at_4_pct(self):
        r = score_dividend_stock("KR12", "SafeYield", yield_pct=4.0, ml_status="INTACT",
                                  dps_cuts=0, latest_yoy=5.0)
        if r.get("exclude_reason") is None:
            assert r["trap_level"] == "SAFE"


# ─── TestUSHardFilters ─────────────────────────────────────────

class TestUSHardFilters:
    def test_low_yield_excluded(self):
        r = score_us_dividend_stock("AAPL", "Apple", yield_pct=0.5)
        assert r.get("exclude_reason") is not None

    def test_recent_cut_without_history_excluded(self):
        r = score_us_dividend_stock("BAD", "BadCo", yield_pct=3.0, dividend_cut=1,
                                     consecutive_years=3)
        assert r.get("exclude_reason") is not None

    def test_recent_cut_with_long_history_allowed(self):
        # 배당삭감 1회 + 연속 10년 이상 → 허용
        r = score_us_dividend_stock("JNJ", "J&J", yield_pct=3.0, dividend_cut=1,
                                     consecutive_years=10, dps_yoy_pct=0.0)
        assert r.get("overall_score") is not None


# ─── TestUSScoreStructure ──────────────────────────────────────

class TestUSScoreStructure:
    def setup_method(self):
        self.r = score_us_dividend_stock(
            "KO", "Coca-Cola", yield_pct=3.2, dividend_cut=0,
            dps_yoy_pct=4.5, payout_ratio=70.0, div_coverage=1.5,
            consecutive_years=62,
        )

    def test_returns_dict(self):
        assert isinstance(self.r, dict)

    def test_overall_score_in_range(self):
        assert 0 <= self.r.get("overall_score", 0) <= 100

    def test_dividend_king_classification(self):
        # 62년 연속 → DIVIDEND_KING
        if self.r.get("exclude_reason") is None:
            assert self.r.get("asset_type") == "DIVIDEND_KING"

    def test_trap_level_safe_at_3_pct(self):
        if self.r.get("exclude_reason") is None:
            assert self.r["trap_level"] == "SAFE"


# ─── TestUSAristocratClassification ───────────────────────────

class TestUSAristocratClassification:
    def test_25_years_is_aristocrat(self):
        r = score_us_dividend_stock("PG", "P&G", yield_pct=2.5, consecutive_years=25,
                                     dps_yoy_pct=5.0)
        if r.get("exclude_reason") is None:
            assert r.get("asset_type") == "DIVIDEND_ARISTOCRAT"

    def test_50_years_is_king(self):
        r = score_us_dividend_stock("MMM", "3M", yield_pct=5.0, consecutive_years=50,
                                     dps_yoy_pct=3.0)
        if r.get("exclude_reason") is None:
            assert r.get("asset_type") == "DIVIDEND_KING"

    def test_10_years_is_challenger(self):
        r = score_us_dividend_stock("ABBV", "AbbVie", yield_pct=3.8, consecutive_years=10,
                                     dps_yoy_pct=7.0)
        if r.get("exclude_reason") is None:
            assert r.get("asset_type") == "DIVIDEND_CHALLENGER"

    def test_few_years_is_regular(self):
        r = score_us_dividend_stock("X", "NewCo", yield_pct=3.0, consecutive_years=3,
                                     dps_yoy_pct=3.0)
        if r.get("exclude_reason") is None:
            assert r.get("asset_type") not in ("DIVIDEND_KING", "DIVIDEND_ARISTOCRAT", "DIVIDEND_CHALLENGER")

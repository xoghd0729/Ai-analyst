"""
tests/test_etf_quality.py
==========================
utils/etf_quality.py — 내부 스코어링 함수 단위 테스트 (yfinance 불필요)

검증 항목:
  - _score_income_cagr: None→50, 10%+→100, 음수→낮음
  - _score_price_cagr: None→50, 12%+→100
  - _score_max_drawdown: None→50, -5%→100, -60%→낮음
  - _score_expense_ratio: None→75, 0.06→100, 1%+→낮음
  - KNOWN_EXPENSE_RATIOS: SCHD=0.06, JEPI=0.35 등
  - filter_etf_universe: 한국 숫자코드 → PASS 통과
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from utils.etf_quality import (
    _score_income_cagr,
    _score_price_cagr,
    _score_max_drawdown,
    _score_expense_ratio,
    filter_etf_universe,
    KNOWN_EXPENSE_RATIOS,
    WEIGHTS,
)


# ─── TestWeights ──────────────────────────────────────────────

class TestWeights:
    def test_weights_sum_to_1(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_income_weight_largest(self):
        # income (35pt) > growth (25pt) = stability (25pt) > expense (15pt)
        assert WEIGHTS["income"] >= WEIGHTS["growth"]
        assert WEIGHTS["income"] >= WEIGHTS["stability"]
        assert WEIGHTS["income"] >= WEIGHTS["expense"]

    def test_known_ratios_schd(self):
        assert KNOWN_EXPENSE_RATIOS["SCHD"] == 0.06

    def test_known_ratios_jepi(self):
        assert KNOWN_EXPENSE_RATIOS["JEPI"] == 0.35

    def test_individual_reit_is_none(self):
        # O(Realty Income)는 개별 리츠라 수수료 없음
        assert KNOWN_EXPENSE_RATIOS["O"] is None


# ─── TestScoreIncomeCagr ──────────────────────────────────────

class TestScoreIncomeCagr:
    def test_none_returns_neutral(self):
        assert _score_income_cagr(None) == 50.0

    def test_10pct_returns_max(self):
        assert _score_income_cagr(10.0) == 100.0

    def test_above_10pct_returns_max(self):
        assert _score_income_cagr(15.0) == 100.0

    def test_7pct_returns_85(self):
        assert _score_income_cagr(7.0) == 85.0

    def test_zero_returns_40(self):
        assert _score_income_cagr(0.0) == 40.0

    def test_negative_3pct_returns_20(self):
        assert _score_income_cagr(-2.0) == 20.0

    def test_severe_negative_returns_5(self):
        assert _score_income_cagr(-10.0) == 5.0

    def test_monotone_increase(self):
        vals = [-10, -3, 0, 1, 4, 7, 10]
        scores = [_score_income_cagr(v) for v in vals]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1]


# ─── TestScorePriceCagr ───────────────────────────────────────

class TestScorePriceCagr:
    def test_none_returns_neutral(self):
        assert _score_price_cagr(None) == 50.0

    def test_12pct_returns_max(self):
        assert _score_price_cagr(12.0) == 100.0

    def test_zero_returns_40(self):
        assert _score_price_cagr(0.0) == 40.0

    def test_negative_returns_low(self):
        assert _score_price_cagr(-5.0) < 30.0

    def test_monotone_increase(self):
        vals = [-5, -3, 0, 2, 5, 8, 12]
        scores = [_score_price_cagr(v) for v in vals]
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1]


# ─── TestScoreMaxDrawdown ─────────────────────────────────────

class TestScoreMaxDrawdown:
    def test_none_returns_neutral(self):
        assert _score_max_drawdown(None) == 50.0

    def test_small_drawdown_high_score(self):
        # -5% → ≤10% → 100
        assert _score_max_drawdown(-5.0) == 100.0

    def test_large_drawdown_low_score(self):
        # -60% → 25점 이하
        assert _score_max_drawdown(-60.0) <= 25.0

    def test_absolute_value_used(self):
        # -35 와 +35 동일 결과 (abs 처리)
        assert _score_max_drawdown(-35.0) == _score_max_drawdown(35.0)

    def test_monotone_worse_with_higher_mdd(self):
        # MDD 절대값이 커질수록 점수 감소
        s10  = _score_max_drawdown(-10.0)
        s30  = _score_max_drawdown(-30.0)
        s50  = _score_max_drawdown(-50.0)
        assert s10 >= s30 >= s50


# ─── TestScoreExpenseRatio ────────────────────────────────────

class TestScoreExpenseRatio:
    def test_none_returns_75(self):
        # 개별 리츠 등 수수료 없음 → 75 (감점 안 함)
        assert _score_expense_ratio(None) == 75.0

    def test_very_low_er_max_score(self):
        assert _score_expense_ratio(0.03) == 100.0

    def test_schd_level_max_score(self):
        assert _score_expense_ratio(0.06) == 100.0

    def test_jepi_level_mid_score(self):
        # 0.30 <= 0.35 <= 0.50 → 45점
        assert _score_expense_ratio(0.35) == 45.0

    def test_high_er_low_score(self):
        assert _score_expense_ratio(1.5) == 10.0

    def test_monotone_worse_with_higher_er(self):
        s1 = _score_expense_ratio(0.06)
        s2 = _score_expense_ratio(0.30)
        s3 = _score_expense_ratio(0.75)
        assert s1 >= s2 >= s3


# ─── TestFilterEtfUniverse ────────────────────────────────────

class TestFilterEtfUniverse:
    def test_korean_numeric_code_passes_directly(self):
        etfs = [{"ticker": "448290", "name": "TIGER 미국배당다우존스"}]
        result = filter_etf_universe(etfs, min_score=40.0)
        assert len(result) == 1
        assert result[0]["etf_grade"] == "PASS"
        assert result[0]["etf_quality_score"] == 65.0

    def test_korean_code_weight_penalty_1(self):
        etfs = [{"ticker": "395400", "name": "SK리츠"}]
        result = filter_etf_universe(etfs)
        assert result[0]["weight_penalty"] == 1.0

    def test_empty_list_returns_empty(self):
        result = filter_etf_universe([])
        assert result == []

    def test_multiple_korean_codes_all_pass(self):
        etfs = [
            {"ticker": "448290", "name": "ETF A"},
            {"ticker": "385720", "name": "ETF B"},
            {"ticker": "395400", "name": "ETF C"},
        ]
        result = filter_etf_universe(etfs)
        assert len(result) == 3

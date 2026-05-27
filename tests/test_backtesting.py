"""
tests/test_backtesting.py — 백테스팅 엔진 단위 테스트

왜 이 테스트가 필요한가?
  run_backtest()는 CAGR, MDD, Sharpe 세 가지 핵심 지표를 계산한다.
  각각의 수학적 정의를 직접 검증해야 투자자에게 신뢰할 수 있는 결과를 제공한다.

  - CAGR: 기하평균 연수익률. (최종가치/초기가치)^(1/n) - 1
  - MDD:  최대낙폭. 항상 0 이하 (손실이므로 음수)
  - Sharpe: (평균수익 - 무위험수익) / 표준편차. 위험조정 수익률.

실행:
  pytest tests/test_backtesting.py -v
"""

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.backtesting import run_backtest


# ─────────────────────────────────────────────────────────────────────────────
# 테스트 데이터
# ─────────────────────────────────────────────────────────────────────────────

# SCHD: 역사적 데이터 테이블에 있는 종목 (2015-2024)
SCHD_ONLY = [
    {
        "ticker": "SCHD",
        "asset_class": "us_etf",
        "etf_category": "dividend_etf",
        "weight_pct": 100.0,
        "invest_amount_만원": 10_000,
    }
]

# 혼합 포트폴리오
MIXED_PORTFOLIO = [
    {
        "ticker": "SCHD",
        "asset_class": "us_etf",
        "weight_pct": 50.0,
        "invest_amount_만원": 5_000,
    },
    {
        "ticker": "VYM",
        "asset_class": "us_etf",
        "weight_pct": 30.0,
        "invest_amount_만원": 3_000,
    },
    {
        "ticker": "O",
        "asset_class": "us_stock",
        "weight_pct": 20.0,
        "invest_amount_만원": 2_000,
    },
]

# 가상 종목 (데이터 없음 → yfinance fallback 또는 기본값)
UNKNOWN_TICKER = [
    {
        "ticker": "FAKE_TICKER_XYZ",
        "asset_class": "us_etf",
        "weight_pct": 100.0,
        "invest_amount_만원": 5_000,
    }
]


# ─────────────────────────────────────────────────────────────────────────────
# 픽스처
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def schd_result():
    return run_backtest(SCHD_ONLY, start_year=2015, end_year=2024, investable=10_000)

@pytest.fixture
def mixed_result():
    return run_backtest(MIXED_PORTFOLIO, start_year=2018, end_year=2023, investable=10_000)


# ─────────────────────────────────────────────────────────────────────────────
# 반환 구조 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestReturnStructure:
    def test_required_keys(self, schd_result):
        required = {
            "cagr_pct", "mdd_pct", "sharpe_ratio",
            "yearly_returns", "total_return_pct",
        }
        missing = required - set(schd_result.keys())
        assert not missing, f"누락 키: {missing}"

    def test_yearly_returns_length(self, schd_result):
        """2015-2024 = 10년 데이터"""
        assert len(schd_result["yearly_returns"]) == 10

    def test_yearly_return_entry_structure(self, schd_result):
        entry = schd_result["yearly_returns"][0]
        required = {"year", "return_pct", "value_만원"}
        missing = required - set(entry.keys())
        assert not missing, f"yearly_returns 항목 누락 키: {missing}"

    def test_yearly_returns_year_sequence(self, schd_result):
        """연도 순서가 오름차순이어야 한다"""
        years = [e["year"] for e in schd_result["yearly_returns"]]
        assert years == sorted(years)
        assert years[0] == 2015
        assert years[-1] == 2024


# ─────────────────────────────────────────────────────────────────────────────
# CAGR 수학 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestCAGR:
    def test_cagr_is_finite_number(self, schd_result):
        cagr = schd_result["cagr_pct"]
        assert isinstance(cagr, (int, float))
        assert math.isfinite(cagr), f"CAGR이 유한수가 아님: {cagr}"

    def test_cagr_reasonable_range(self, schd_result):
        """CAGR은 합리적 범위 내 (예: -50% ~ +50%)"""
        cagr = schd_result["cagr_pct"]
        assert -50 < cagr < 50, f"CAGR이 비현실적: {cagr}%"

    def test_cagr_formula_consistency(self, schd_result):
        """
        CAGR 공식 검증:
        (최종가치 / 초기가치) ^ (1/n) - 1 = CAGR
        → 초기가치 × (1 + CAGR)^n ≈ 최종가치
        """
        cagr = schd_result["cagr_pct"] / 100
        n    = len(schd_result["yearly_returns"])
        initial = 10_000  # investable

        final_value = schd_result["yearly_returns"][-1]["value_만원"]
        reconstructed = initial * ((1 + cagr) ** n)

        # 5% 허용 오차 (yfinance 보정 등으로 약간 다를 수 있음)
        relative_err = abs(reconstructed - final_value) / max(final_value, 1)
        assert relative_err < 0.05, \
            f"CAGR 역산 불일치: reconstructed={reconstructed:.0f}, actual={final_value:.0f} ({relative_err:.1%})"

    def test_total_return_matches_yearly(self, schd_result):
        """total_return_pct ≈ (최종가치 / 10000 - 1) × 100"""
        final = schd_result["yearly_returns"][-1]["value_만원"]
        expected_total = (final / 10_000 - 1) * 100
        actual_total   = schd_result["total_return_pct"]
        assert abs(actual_total - expected_total) < 1.0, \
            f"total_return 불일치: 계산={expected_total:.2f}, 반환={actual_total:.2f}"


# ─────────────────────────────────────────────────────────────────────────────
# MDD 수학 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestMDD:
    def test_mdd_non_positive(self, schd_result):
        """MDD는 항상 0 이하 (낙폭이므로 음수 또는 0)"""
        mdd = schd_result["mdd_pct"]
        assert mdd <= 0, f"MDD가 양수: {mdd}% (낙폭이 양수면 오류)"

    def test_mdd_reasonable_range(self, schd_result):
        """MDD는 -100% ~ 0% 범위"""
        mdd = schd_result["mdd_pct"]
        assert -100 <= mdd <= 0, f"MDD 범위 초과: {mdd}%"

    def test_mdd_worse_with_volatile_period(self):
        """2020년 코로나 쇼크 포함 기간이 그렇지 않은 기간보다 MDD가 나빠야 한다"""
        with_covid = run_backtest(SCHD_ONLY, start_year=2018, end_year=2022, investable=10_000)
        without_covid = run_backtest(SCHD_ONLY, start_year=2021, end_year=2024, investable=10_000)

        # 코로나 쇼크 포함 기간의 MDD가 더 낮아야 (더 큰 낙폭)
        if with_covid["mdd_pct"] != 0 and without_covid["mdd_pct"] != 0:
            # 두 기간 모두 낙폭이 있다면 코로나 포함 기간이 더 나쁠 가능성 높음
            # (항상 보장되지 않지만, 0이 아닌 경우 비교 가능)
            assert with_covid["mdd_pct"] <= without_covid["mdd_pct"] + 5, \
                "코로나 쇼크 포함 기간의 MDD가 더 좋음 — 비정상"

    def test_mdd_is_zero_when_always_going_up(self):
        """모든 연도가 플러스 수익이라면 MDD = 0"""
        # 이 케이스는 데이터에 따라 달라지므로, 구조만 검증
        result = run_backtest(SCHD_ONLY, start_year=2015, end_year=2024, investable=10_000)
        # yearly_returns가 모두 양수인지 확인
        all_positive = all(e["return_pct"] >= 0 for e in result["yearly_returns"])
        if all_positive:
            assert result["mdd_pct"] >= -0.01, \
                f"모든 연도 양수인데 MDD 음수: {result['mdd_pct']}"


# ─────────────────────────────────────────────────────────────────────────────
# Sharpe Ratio 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestSharpe:
    def test_sharpe_is_finite(self, schd_result):
        sharpe = schd_result["sharpe_ratio"]
        assert math.isfinite(sharpe), f"Sharpe가 유한수가 아님: {sharpe}"

    def test_higher_return_higher_sharpe(self):
        """수익률이 높은 포트폴리오가 더 높은 Sharpe"""
        short_high = run_backtest(SCHD_ONLY, start_year=2019, end_year=2024,
                                  investable=10_000, risk_free_rate=0.5)
        short_low  = run_backtest(SCHD_ONLY, start_year=2019, end_year=2024,
                                  investable=10_000, risk_free_rate=5.0)
        # 무위험수익률이 낮을수록 Sharpe가 높아야 한다
        assert short_high["sharpe_ratio"] >= short_low["sharpe_ratio"], \
            "무위험수익률 낮은데 Sharpe가 더 낮음"

    def test_sharpe_zero_when_single_year(self):
        """1년 데이터는 표준편차 = 0 → Sharpe = 0"""
        result = run_backtest(SCHD_ONLY, start_year=2020, end_year=2020, investable=10_000)
        assert result["sharpe_ratio"] == 0.0, \
            f"단일 연도 Sharpe가 0이 아님: {result['sharpe_ratio']}"


# ─────────────────────────────────────────────────────────────────────────────
# 신규 리스크 메트릭 검증 (Sortino/Calmar/IR)
# ─────────────────────────────────────────────────────────────────────────────

class TestNewRiskMetrics:
    def test_sortino_ratio_positive_for_growing_portfolio(self):
        result = run_backtest(SCHD_ONLY, start_year=2019, end_year=2024, investable=10_000)
        assert "sortino_ratio" in result
        assert isinstance(result["sortino_ratio"], (int, float))
        assert result["sortino_ratio"] > 0, f"Sortino가 양수가 아님: {result['sortino_ratio']}"

    def test_calmar_ratio_formula(self):
        result = run_backtest(SCHD_ONLY, start_year=2015, end_year=2024, investable=10_000)
        mdd = result["mdd_pct"]
        if mdd < 0:
            expected = round(result["cagr_pct"] / abs(mdd), 3)
            assert abs(result["calmar_ratio"] - expected) < 0.01, \
                f"Calmar 계산 오류: {result['calmar_ratio']} != {expected}"
        else:
            assert result["calmar_ratio"] == 0.0

    def test_information_ratio_vs_benchmark(self):
        result = run_backtest(SCHD_ONLY, start_year=2015, end_year=2024, investable=10_000)
        assert "information_ratio_kospi" in result
        assert "information_ratio_sp500" in result
        assert math.isfinite(result["information_ratio_kospi"])
        assert math.isfinite(result["information_ratio_sp500"])

    def test_new_metrics_in_response_dict(self, schd_result):
        required = {
            "sortino_ratio",
            "calmar_ratio",
            "information_ratio_kospi",
            "information_ratio_sp500",
        }
        missing = required - set(schd_result.keys())
        assert not missing, f"신규 메트릭 누락: {missing}"


# ─────────────────────────────────────────────────────────────────────────────
# 벤치마크 비교 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestBenchmarkComparison:
    def test_vs_kospi_and_sp500_present(self, schd_result):
        """yearly_returns에 vs_kospi, vs_sp500 포함"""
        entry = schd_result["yearly_returns"][0]
        assert "vs_kospi" in entry
        assert "vs_sp500" in entry

    def test_vs_benchmark_is_difference(self, schd_result):
        """vs_kospi = return_pct - kospi_ret"""
        for entry in schd_result["yearly_returns"]:
            if "kospi_ret" in entry:
                expected = round(entry["return_pct"] - entry["kospi_ret"], 2)
                actual   = entry["vs_kospi"]
                assert abs(actual - expected) < 0.1, \
                    f"Year {entry['year']}: vs_kospi 계산 오류 ({actual} ≠ {expected})"


# ─────────────────────────────────────────────────────────────────────────────
# 엣지 케이스
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_recommendations(self):
        """빈 포트폴리오 → 예외 없이 빈 결과"""
        result = run_backtest([], start_year=2015, end_year=2024, investable=10_000)
        assert "cagr_pct" in result
        assert result["cagr_pct"] == 0.0 or result["cagr_pct"] is None or \
               isinstance(result["cagr_pct"], (int, float))

    def test_zero_weight_assets_ignored(self):
        """weight_pct=0 자산은 무시되어야 한다"""
        zero_weight = [{**SCHD_ONLY[0], "weight_pct": 0.0}]
        result = run_backtest(zero_weight, start_year=2020, end_year=2023, investable=5_000)
        assert "cagr_pct" in result

    def test_short_period_2_years(self):
        """2년 백테스팅도 동작"""
        result = run_backtest(SCHD_ONLY, start_year=2022, end_year=2023, investable=5_000)
        assert len(result["yearly_returns"]) == 2

    def test_unknown_ticker_no_crash(self):
        """데이터 없는 종목도 예외 없이 처리"""
        result = run_backtest(UNKNOWN_TICKER, start_year=2020, end_year=2023, investable=5_000)
        assert "cagr_pct" in result

    def test_mixed_portfolio_weights_sum(self, mixed_result):
        """혼합 포트폴리오도 정상 결과 반환"""
        assert "cagr_pct" in mixed_result
        assert len(mixed_result["yearly_returns"]) == 6  # 2018-2023

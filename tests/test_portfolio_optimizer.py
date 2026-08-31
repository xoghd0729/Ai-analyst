"""
tests/test_portfolio_optimizer.py — MPT 효율적 프론티어 단위 테스트

왜 이 테스트가 필요한가?
  optimize_portfolio()는 numpy 난수 + 행렬 연산으로 동작하므로
  절댓값을 고정하기 어렵다. seed=42로 재현성을 확보하되,
  "방향성 불변조건"을 검증한다:

  1. 반환 구조 — 필수 키 존재
  2. 수학적 불변조건 — max_sharpe.sharpe >= min_vol.sharpe
  3. 재현성 — seed=42 두 번 실행 → 동일 결과
  4. NaN/부족 데이터 — 유효 종목 2개 미만 시 error 키 반환
  5. 다운샘플링 — frontier points 수가 n_points_returned 이하
  6. 가중치 합 = 1.0 (±0.001)
  7. 공분산 행렬 대칭성
  8. Sharpe 부호 방향성 — 수익률 높은 포트폴리오가 낮은 rf보다 큰 sharpe

실행:
  pytest tests/test_portfolio_optimizer.py -v
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import pytest
from utils.portfolio_optimizer import optimize_portfolio, _build_returns_matrix


# ─────────────────────────────────────────────────────────────────
# 공통 픽스처
# ─────────────────────────────────────────────────────────────────

WELL_KNOWN_TICKERS = ["SCHD", "VYM", "TLT", "BND"]   # 2015–2024 full data


@pytest.fixture(scope="module")
def result_4tickers():
    """4개 티커, 기본 파라미터로 최적화한 결과."""
    return optimize_portfolio(
        tickers        = WELL_KNOWN_TICKERS,
        risk_free_rate = 2.0,
        n_portfolios   = 500,   # 테스트 속도를 위해 축소
        seed           = 42,
    )


@pytest.fixture(scope="module")
def frontier(result_4tickers):
    """efficient_frontier 딕셔너리."""
    return result_4tickers["efficient_frontier"]


# ─────────────────────────────────────────────────────────────────
# 1. 반환 구조 테스트
# ─────────────────────────────────────────────────────────────────

class TestReturnStructure:
    def test_top_level_key(self, result_4tickers):
        assert "efficient_frontier" in result_4tickers

    def test_efficient_frontier_required_keys(self, frontier):
        for key in ("points", "max_sharpe", "min_volatility", "valid_tickers",
                    "n_simulated", "years", "risk_free_rate"):
            assert key in frontier, f"frontier에 '{key}' 없음"

    def test_max_sharpe_required_keys(self, frontier):
        ms = frontier["max_sharpe"]
        for key in ("tickers", "weights", "weight_pct",
                    "expected_return", "volatility", "sharpe"):
            assert key in ms, f"max_sharpe에 '{key}' 없음"

    def test_min_vol_required_keys(self, frontier):
        mv = frontier["min_volatility"]
        for key in ("tickers", "weights", "weight_pct",
                    "expected_return", "volatility", "sharpe"):
            assert key in mv, f"min_volatility에 '{key}' 없음"

    def test_points_is_nonempty_list(self, frontier):
        assert isinstance(frontier["points"], list)
        assert len(frontier["points"]) > 0

    def test_each_point_has_fields(self, frontier):
        pt = frontier["points"][0]
        for key in ("volatility", "return", "sharpe"):
            assert key in pt, f"point에 '{key}' 없음"

    def test_valid_tickers_subset_of_input(self, frontier):
        for t in frontier["valid_tickers"]:
            assert t in WELL_KNOWN_TICKERS

    def test_n_simulated_matches(self, frontier):
        assert frontier["n_simulated"] == 500

    def test_years_string_format(self, frontier):
        assert "–" in frontier["years"] or "-" in frontier["years"]


# ─────────────────────────────────────────────────────────────────
# 2. 수학적 불변조건
# ─────────────────────────────────────────────────────────────────

class TestMathInvariants:
    def test_max_sharpe_ge_min_vol_sharpe(self, frontier):
        """max_sharpe의 Sharpe가 min_vol의 Sharpe 이상."""
        assert frontier["max_sharpe"]["sharpe"] >= frontier["min_volatility"]["sharpe"], (
            "max_sharpe의 sharpe가 min_vol의 sharpe보다 작음 — 알고리즘 오류"
        )

    def test_min_vol_vol_le_max_sharpe_vol(self, frontier):
        """min_volatility의 변동성이 max_sharpe의 변동성 이하."""
        assert frontier["min_volatility"]["volatility"] <= frontier["max_sharpe"]["volatility"], (
            "min_vol의 변동성이 max_sharpe보다 큼 — 알고리즘 오류"
        )

    def test_max_sharpe_weights_sum_to_one(self, frontier):
        w_sum = sum(frontier["max_sharpe"]["weights"])
        assert abs(w_sum - 1.0) < 0.001, f"max_sharpe 가중치 합 = {w_sum} (1.0이어야 함)"

    def test_min_vol_weights_sum_to_one(self, frontier):
        w_sum = sum(frontier["min_volatility"]["weights"])
        assert abs(w_sum - 1.0) < 0.001, f"min_vol 가중치 합 = {w_sum} (1.0이어야 함)"

    def test_weights_all_nonnegative(self, frontier):
        """롱온리 포트폴리오 — 모든 가중치 >= 0."""
        for w in frontier["max_sharpe"]["weights"]:
            assert w >= -1e-9, f"음수 가중치 발견: {w}"
        for w in frontier["min_volatility"]["weights"]:
            assert w >= -1e-9

    def test_volatility_positive(self, frontier):
        assert frontier["max_sharpe"]["volatility"] > 0
        assert frontier["min_volatility"]["volatility"] > 0

    def test_cov_matrix_symmetric(self, frontier):
        """공분산 행렬 대칭성 검증."""
        cov = frontier.get("cov_matrix")
        if cov is None:
            return
        n = len(cov)
        for i in range(n):
            for j in range(i + 1, n):
                assert abs(cov[i][j] - cov[j][i]) < 0.001, \
                    f"cov[{i}][{j}] = {cov[i][j]}, cov[{j}][{i}] = {cov[j][i]}"

    def test_weight_pct_sums_to_100(self, frontier):
        for key in ("max_sharpe", "min_volatility"):
            total = sum(frontier[key]["weight_pct"])
            assert abs(total - 100.0) < 0.5, \
                f"{key} weight_pct 합 = {total} (100이어야 함)"


# ─────────────────────────────────────────────────────────────────
# 3. 재현성 (seed 고정)
# ─────────────────────────────────────────────────────────────────

class TestReproducibility:
    def test_same_seed_same_result(self):
        """seed=42로 두 번 실행 → 동일한 max_sharpe."""
        kwargs = dict(tickers=WELL_KNOWN_TICKERS, n_portfolios=200, seed=42)
        r1 = optimize_portfolio(**kwargs)
        r2 = optimize_portfolio(**kwargs)
        ms1 = r1["efficient_frontier"]["max_sharpe"]
        ms2 = r2["efficient_frontier"]["max_sharpe"]
        assert ms1["sharpe"]    == ms2["sharpe"],    "sharpe 불일치"
        assert ms1["volatility"] == ms2["volatility"],"volatility 불일치"
        assert ms1["weights"]   == ms2["weights"],   "weights 불일치"

    def test_different_seed_different_result(self):
        """seed가 다르면 결과가 달라야 한다 (확률적 테스트)."""
        r42 = optimize_portfolio(tickers=WELL_KNOWN_TICKERS, n_portfolios=200, seed=42)
        r99 = optimize_portfolio(tickers=WELL_KNOWN_TICKERS, n_portfolios=200, seed=99)
        # max_sharpe weights가 완전히 같을 확률은 0에 가까움
        w42 = r42["efficient_frontier"]["max_sharpe"]["weights"]
        w99 = r99["efficient_frontier"]["max_sharpe"]["weights"]
        assert w42 != w99, "서로 다른 seed인데 동일한 결과 — 재현성 버그 가능성"


# ─────────────────────────────────────────────────────────────────
# 4. 다운샘플링 / 포인트 수
# ─────────────────────────────────────────────────────────────────

class TestDownsampling:
    def test_points_count_le_n_points_returned(self):
        """반환된 frontier 점의 수가 n_points_returned 이하."""
        r = optimize_portfolio(
            tickers          = WELL_KNOWN_TICKERS,
            n_portfolios     = 1000,
            n_points_returned = 100,
            seed             = 42,
        )
        pts = r["efficient_frontier"]["points"]
        # +2 여유 (max_sharpe, min_vol 점이 추가로 붙을 수 있음)
        assert len(pts) <= 100 + 2, f"points 수 = {len(pts)} > 102"

    def test_points_count_with_default_settings(self, frontier):
        """기본 설정에서 점 수가 합리적인 범위."""
        pts = frontier["points"]
        assert 10 <= len(pts) <= 510, f"points 수 = {len(pts)} 비정상"


# ─────────────────────────────────────────────────────────────────
# 5. 엣지 케이스
# ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_single_ticker_returns_error(self):
        """티커 1개 → 유효 종목 < 2 → error 반환."""
        result = optimize_portfolio(tickers=["SCHD"], n_portfolios=100)
        assert "error" in result, "1개 티커인데 error가 반환되지 않음"

    def test_empty_tickers_returns_error(self):
        """빈 리스트 → error 반환."""
        result = optimize_portfolio(tickers=[], n_portfolios=100)
        assert "error" in result

    def test_all_nan_ticker_excluded(self):
        """
        _build_returns_matrix에서 유효 연도 < 3인 종목 제외 검증.
        (optimize_portfolio 레벨에서는 _get_asset_yearly_returns가
        알 수 없는 티커에 섹터 기본값을 폴백으로 제공하므로,
        제외 로직은 _build_returns_matrix 단위에서 직접 검증한다.)
        """
        import math as m
        returns_lookup = {
            "SCHD": {yr: 10.0 for yr in range(2015, 2025)},
            "EMPTY": {yr: m.nan for yr in range(2015, 2025)},  # 전부 NaN
        }
        years = list(range(2015, 2025))
        _, valid = _build_returns_matrix(["SCHD", "EMPTY"], returns_lookup, years)
        assert "EMPTY" not in valid, "전부 NaN인 종목이 valid_tickers에 포함됨"
        assert "SCHD"  in valid

    def test_small_n_portfolios(self):
        """n_portfolios=10처럼 극소 값도 오류 없이 처리."""
        result = optimize_portfolio(
            tickers=["SCHD", "VYM"],
            n_portfolios=10,
            seed=42,
        )
        assert "efficient_frontier" in result

    def test_two_tickers_minimum(self):
        """2개 티커 — 정상 동작."""
        result = optimize_portfolio(
            tickers=["SCHD", "TLT"],
            n_portfolios=200,
            seed=42,
        )
        assert "efficient_frontier" in result
        ef = result["efficient_frontier"]
        assert len(ef["valid_tickers"]) == 2


# ─────────────────────────────────────────────────────────────────
# 6. Sharpe 방향성 (rf 변경 효과)
# ─────────────────────────────────────────────────────────────────

class TestSharpeDirection:
    def test_higher_rf_lower_sharpe(self):
        """무위험 수익률이 높으면 Sharpe가 낮아진다."""
        r_low_rf  = optimize_portfolio(
            tickers=["SCHD", "VYM", "TLT"],
            n_portfolios=300, seed=42, risk_free_rate=1.0)
        r_high_rf = optimize_portfolio(
            tickers=["SCHD", "VYM", "TLT"],
            n_portfolios=300, seed=42, risk_free_rate=8.0)

        sharpe_low  = r_low_rf["efficient_frontier"]["max_sharpe"]["sharpe"]
        sharpe_high = r_high_rf["efficient_frontier"]["max_sharpe"]["sharpe"]
        assert sharpe_low >= sharpe_high, (
            f"rf=1% Sharpe({sharpe_low}) < rf=8% Sharpe({sharpe_high}) — 비정상"
        )


# ─────────────────────────────────────────────────────────────────
# 7. _build_returns_matrix 단위 테스트
# ─────────────────────────────────────────────────────────────────

class TestBuildReturnsMatrix:
    def test_nan_years_filled_with_mean(self):
        """NaN 연도가 해당 종목 평균으로 채워지는지 확인."""
        import math as m
        returns_lookup = {
            "A": {2015: 10.0, 2016: 20.0, 2017: m.nan, 2018: 30.0},
            "B": {2015: 5.0,  2016: 5.0,  2017: 5.0,  2018: 5.0},
        }
        years = [2015, 2016, 2017, 2018]
        matrix, valid = _build_returns_matrix(["A", "B"], returns_lookup, years)

        assert "A" in valid
        assert "B" in valid

        a_idx = valid.index("A")
        # A의 유효값: 10, 20, 30 → 평균 20.0
        # 2017(NaN) → 20.0으로 채워야 함
        assert abs(matrix[a_idx, 2] - 20.0) < 0.001

    def test_too_few_data_years_excluded(self):
        """유효 연도 < 3인 종목은 제외."""
        import math as m
        returns_lookup = {
            "SPARSE": {2015: m.nan, 2016: m.nan, 2017: m.nan,
                       2018: m.nan, 2019: m.nan, 2020: m.nan,
                       2021: m.nan, 2022: m.nan, 2023: 5.0, 2024: 6.0},
            "RICH":   {yr: 10.0 for yr in range(2015, 2025)},
        }
        years = list(range(2015, 2025))
        _, valid = _build_returns_matrix(["SPARSE", "RICH"], returns_lookup, years)

        assert "RICH" in valid
        assert "SPARSE" not in valid, "데이터 2개뿐인 종목이 포함됨"

    def test_all_nan_returns_empty_matrix(self):
        """모든 종목이 데이터 부족이면 빈 행렬."""
        import math as m
        returns_lookup = {
            "X": {2015: m.nan, 2016: m.nan},
        }
        years = [2015, 2016]
        matrix, valid = _build_returns_matrix(["X"], returns_lookup, years)
        assert len(valid) == 0

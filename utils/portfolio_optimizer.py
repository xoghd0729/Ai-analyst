"""
utils/portfolio_optimizer.py — MPT 효율적 프론티어 (평균-분산 최적화)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  Ranker는 "어떤 종목이 좋은가", FIRE Engine은 "언제 달성하는가"를 답한다.
  그런데 "어떻게 섞어야 위험 대비 수익이 최대인가"는 다른 질문이다.
  MPT(Modern Portfolio Theory)는 이 질문에 수학적으로 답한다:
  n개 종목을 가중치 w로 섞을 때, Sharpe가 최대인 조합은 무엇인가?

■ 방법: 5,000개 랜덤 포트폴리오 몬테카를로 샘플링
  - scipy.optimize 없이 numpy만으로 구현 (의존성 최소화)
  - Dirichlet(1,...,1) 분포로 심플렉스 위의 균일한 가중치 생성
  - seed=42 고정 → 테스트/재현성 보장

■ 데이터 소스
  backtesting.py의 _get_asset_yearly_returns() 재사용 (2015–2024)
  - 동일한 데이터 소스 → Backtest 결과와 일관성 유지
  - NaN(상장 전 연도)은 해당 종목의 기간 내 평균으로 대체

■ 역할 분리 원칙
  MPT   : 연도별 total return → expected return / volatility / Sharpe
  FIRE  : 목표 월배당 → 필요 자본 역산 (dividend yield 기반)
  Ranker: 개인화된 종목 점수 (abs_yield, growth, risk, age)
  → MPT 수익률 계산에 dividend yield / DPS 성장률을 혼합하지 않는다

■ 반환 구조
  {
    "efficient_frontier": {
      "points":         [{volatility, return, sharpe}, ...],  # 다운샘플
      "max_sharpe":     {tickers, weights, weight_pct,
                         expected_return, volatility, sharpe},
      "min_volatility": {...},
      "valid_tickers":  [str, ...],
      "n_simulated":    int,
      "years":          "2015–2024",
      "risk_free_rate": float,
    }
  }
"""
from __future__ import annotations

import math
import logging
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────
_DEFAULT_START  = 2015
_DEFAULT_END    = 2024
_MIN_DATA_YEARS = 3        # 유효 수익률 연도가 이것보다 적으면 제외
_DOWNSAMPLE_N   = 500      # API 응답에 포함할 frontier 점 수 (상한)


# ── 데이터 접근 헬퍼 ──────────────────────────────────────────────

def _get_yearly_returns(
    ticker: str,
    asset_class: str = "us_div_etf",
) -> dict[int, float]:
    """
    backtesting.py의 _get_asset_yearly_returns() 재사용.
    같은 정적 테이블을 쓰므로 두 모듈의 결과가 일관된다.
    """
    try:
        from utils.backtesting import _get_asset_yearly_returns
        return _get_asset_yearly_returns(ticker, asset_class)
    except Exception as exc:
        log.warning("_get_asset_yearly_returns(%s) failed: %s", ticker, exc)
        return {}


def _asset_class_for(ticker: str, recommendations: list[dict]) -> str:
    """추천 목록에서 해당 티커의 asset_class를 찾는다. 없으면 'us_div_etf'."""
    for r in recommendations:
        if r.get("ticker") == ticker:
            return r.get("asset_class", "us_div_etf")
    return "us_div_etf"


# ── 수익률 행렬 구성 ──────────────────────────────────────────────

def _build_returns_matrix(
    tickers: list[str],
    returns_lookup: dict[str, dict[int, float]],
    years: list[int],
) -> tuple[np.ndarray, list[str]]:
    """
    티커 × 연도 수익률 행렬을 구성.

    처리 방식:
      - 유효 연도가 _MIN_DATA_YEARS 미만인 종목 제외
      - NaN 연도 → 해당 종목 유효값들의 평균으로 대체
        (상장 전 연도를 0%로 두면 변동성이 왜곡되므로 평균 대체)

    반환:
      (matrix: ndarray shape (n_valid, T), valid_tickers: list[str])
    """
    rows: list[list[float]] = []
    valid_tickers: list[str] = []

    for ticker in tickers:
        hist = returns_lookup.get(ticker, {})

        # 유효한 값 수집
        valid_vals = [
            hist[yr]
            for yr in years
            if yr in hist and not math.isnan(hist[yr])
        ]

        if len(valid_vals) < _MIN_DATA_YEARS:
            log.debug("MPT: %s 제외 (유효 연도 %d개 < %d)", ticker, len(valid_vals), _MIN_DATA_YEARS)
            continue

        mean_fill = float(np.mean(valid_vals))

        row = [
            hist.get(yr, math.nan) if (yr in hist and not math.isnan(hist.get(yr, math.nan)))
            else mean_fill
            for yr in years
        ]

        rows.append(row)
        valid_tickers.append(ticker)

    if not rows:
        return np.empty((0, len(years))), []

    return np.array(rows, dtype=float), valid_tickers


# ── 포트폴리오 통계 계산 ──────────────────────────────────────────

def _port_stats(
    weights: np.ndarray,
    mu: np.ndarray,
    cov: np.ndarray,
    rf: float,
) -> tuple[float, float, float]:
    """
    포트폴리오 (기대수익률, 변동성, Sharpe) 계산.

    반환: (return_pct, vol_pct, sharpe)
    """
    ret = float(np.dot(weights, mu))
    var = float(weights @ cov @ weights)
    vol = math.sqrt(max(var, 0.0))
    sharpe = (ret - rf) / vol if vol > 1e-9 else -999.0
    return ret, vol, sharpe


# ── 핵심 퍼블릭 함수 ─────────────────────────────────────────────

def optimize_portfolio(
    tickers: list[str],
    recommendations: Optional[list[dict]] = None,
    risk_free_rate: float = 2.0,
    n_portfolios: int = 5000,
    n_points_returned: int = _DOWNSAMPLE_N,
    start_year: int = _DEFAULT_START,
    end_year:   int = _DEFAULT_END,
    seed: int = 42,
) -> dict:
    """
    MPT 효율적 프론티어 계산.

    파라미터:
      tickers          : 분석할 티커 목록
      recommendations  : pipeline recommendations (asset_class 조회용, 선택)
      risk_free_rate   : 무위험 수익률 (%, 기본 2.0 = 한국 기준금리 근사)
      n_portfolios     : 몬테카를로 샘플 수 (기본 5,000)
      n_points_returned: API 응답에 반환할 frontier 점 수 (기본 500)
      start_year/end_year: 수익률 데이터 기간
      seed             : 재현성을 위한 난수 시드

    반환:
      { "efficient_frontier": { points, max_sharpe, min_volatility, ... } }
      에러 시 { "error": str }
    """
    recs = recommendations or []
    years = list(range(start_year, end_year + 1))

    # ── 1. 수익률 데이터 수집 ──
    returns_lookup: dict[str, dict[int, float]] = {}
    for ticker in tickers:
        ac = _asset_class_for(ticker, recs)
        returns_lookup[ticker] = _get_yearly_returns(ticker, ac)

    # ── 2. 수익률 행렬 구성 + NaN 처리 ──
    matrix, valid_tickers = _build_returns_matrix(tickers, returns_lookup, years)

    if len(valid_tickers) < 2:
        return {
            "error": (
                f"MPT 계산에 유효한 종목이 {len(valid_tickers)}개뿐입니다 "
                f"(최소 2개 필요). 데이터 기간: {start_year}–{end_year}"
            )
        }

    n = len(valid_tickers)

    # ── 3. 통계량 계산 ──
    # mu: 연평균 수익률 (%), shape (n,)
    # cov: 연간 수익률 공분산 행렬, shape (n, n)
    mu  = matrix.mean(axis=1)
    cov = np.cov(matrix)     # ddof=1 (기본값)

    if n == 1:
        cov = np.array([[cov]])

    # ── 4. 랜덤 포트폴리오 샘플링 ──
    rng = np.random.default_rng(seed)

    all_rets    = np.empty(n_portfolios)
    all_vols    = np.empty(n_portfolios)
    all_sharpes = np.empty(n_portfolios)
    all_weights = np.empty((n_portfolios, n))

    for i in range(n_portfolios):
        # Dirichlet(1,...,1) → 심플렉스 위 균일 분포
        w = rng.dirichlet(np.ones(n))
        ret, vol, sharpe = _port_stats(w, mu, cov, risk_free_rate)
        all_rets[i]      = ret
        all_vols[i]      = vol
        all_sharpes[i]   = sharpe
        all_weights[i]   = w

    # ── 5. 최적 포트폴리오 찾기 ──
    max_sharpe_idx = int(np.argmax(all_sharpes))
    min_vol_idx    = int(np.argmin(all_vols))

    def _summary(idx: int) -> dict:
        w = all_weights[idx]
        return {
            "tickers":         valid_tickers,
            "weights":         [round(float(x), 4) for x in w],
            "weight_pct":      [round(float(x) * 100, 1) for x in w],
            "expected_return": round(float(all_rets[idx]),    2),
            "volatility":      round(float(all_vols[idx]),    2),
            "sharpe":          round(float(all_sharpes[idx]), 3),
        }

    # ── 6. frontier points 다운샘플링 ──
    # 5,000개 전부를 프론트에 보내면 JSON이 너무 크다.
    # n_points_returned 개만 균등 간격으로 선택.
    step = max(1, n_portfolios // n_points_returned)
    frontier_points = [
        {
            "volatility": round(float(all_vols[i]),    2),
            "return":     round(float(all_rets[i]),    2),
            "sharpe":     round(float(all_sharpes[i]), 3),
        }
        for i in range(0, n_portfolios, step)
    ]

    # max_sharpe / min_vol 점도 frontier_points에 명시적으로 포함
    for special_idx in (max_sharpe_idx, min_vol_idx):
        pt = {
            "volatility": round(float(all_vols[special_idx]),    2),
            "return":     round(float(all_rets[special_idx]),    2),
            "sharpe":     round(float(all_sharpes[special_idx]), 3),
        }
        if pt not in frontier_points:
            frontier_points.append(pt)

    return {
        "efficient_frontier": {
            "points":          frontier_points,
            "max_sharpe":      _summary(max_sharpe_idx),
            "min_volatility":  _summary(min_vol_idx),
            "valid_tickers":   valid_tickers,
            "n_tickers":       n,
            "n_simulated":     n_portfolios,
            "years":           f"{start_year}–2024" if end_year == 2024 else f"{start_year}–{end_year}",
            "risk_free_rate":  risk_free_rate,
            "cov_matrix":      [[round(float(v), 4) for v in row] for row in cov.tolist()],
            "mean_returns":    [round(float(v), 2) for v in mu.tolist()],
        }
    }

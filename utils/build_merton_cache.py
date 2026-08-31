"""
utils/build_merton_cache.py
─────────────────────────────────────────────────────────────────
로컬에서 한 번 실행 → data/merton_cache.csv 생성

사용법:
    python3 utils/build_merton_cache.py

결과:
    data/merton_cache.csv  (stock_code, year, sigma_annual, market_cap, merton_dtd)

이후 merton_dtd.add_merton_feature()가 캐시를 자동으로 읽음.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from scipy.stats import norm
from scipy.optimize import fsolve
import warnings
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError:
    raise ImportError("pip3 install yfinance")

DATA_DIR  = Path(__file__).parent.parent / "data"
CACHE_FILE = DATA_DIR / "merton_cache.csv"


def _calc_dtd(equity, sigma_equity, debt, r=0.03, T=1.0):
    if any(v is None or (isinstance(v, float) and np.isnan(v)) or v <= 0
           for v in [equity, sigma_equity, debt]):
        return np.nan
    def eqs(params):
        V, sv = params
        if V <= 0 or sv <= 0:
            return [1e10, 1e10]
        d1 = (np.log(V/debt) + (r + 0.5*sv**2)*T) / (sv*np.sqrt(T))
        d2 = d1 - sv*np.sqrt(T)
        return [V*norm.cdf(d1) - debt*np.exp(-r*T)*norm.cdf(d2) - equity,
                sigma_equity*equity - V*norm.cdf(d1)*sv]
    try:
        V, sv = fsolve(eqs, [equity+debt, sigma_equity])
        if V <= 0 or sv <= 0:
            return np.nan
        d2 = (np.log(V/debt) + (r - 0.5*sv**2)*T) / (sv*np.sqrt(T))
        return float(d2)
    except Exception:
        return np.nan


def build_cache():
    df = pd.read_csv(DATA_DIR / "dividend_dataset.csv")
    tickers_raw = df['stock_code'].unique()

    # KR 6자리 코드 → yfinance 포맷 (KOSPI: .KS, KOSDAQ: .KQ)
    # 일단 .KS 먼저 시도, 실패 시 .KQ
    def to_yf(code):
        return f"{int(code):06d}.KS"

    years = sorted(df['year'].unique())
    rows  = []

    print(f"총 {len(tickers_raw)}개 종목 × {len(years)}년 = {len(tickers_raw)*len(years)}행")
    print("yfinance 다운로드 시작...\n")

    for i, code in enumerate(tickers_raw):
        ticker_str = to_yf(code)
        try:
            stock = yf.Ticker(ticker_str)
            hist  = stock.history(start="2012-01-01", end="2026-01-01",
                                  auto_adjust=True)

            if hist.empty:
                # KOSDAQ 시도
                ticker_str = f"{int(code):06d}.KQ"
                stock = yf.Ticker(ticker_str)
                hist  = stock.history(start="2012-01-01", end="2026-01-01",
                                      auto_adjust=True)

            if hist.empty:
                print(f"  [{i+1}/{len(tickers_raw)}] {code}: 데이터 없음 SKIP")
                continue

            # 발행주식수
            try:
                shares = stock.info.get("sharesOutstanding", None)
            except Exception:
                shares = None

            # 부채: dividend_dataset에서 가져옴
            debt_map = df[df['stock_code'] == code].set_index('year')['total_liab'].to_dict()

            # 연도별 sigma 계산
            hist["ret"] = hist["Close"].pct_change()
            hist.index  = hist.index.tz_localize(None)

            for yr in years:
                # 해당 연도 1월~12월 데이터
                yr_hist = hist[hist.index.year == yr]
                if len(yr_hist) < 50:
                    continue

                sigma = yr_hist["ret"].std() * np.sqrt(252)
                if np.isnan(sigma) or sigma <= 0:
                    continue

                close_last = float(yr_hist["Close"].iloc[-1])
                mcap = close_last * shares if shares else np.nan
                debt = debt_map.get(yr, np.nan)

                dtd = _calc_dtd(mcap, sigma, debt) if (mcap and not np.isnan(debt)) else np.nan

                rows.append({
                    "stock_code": code,
                    "year": yr,
                    "sigma_annual": round(sigma, 4),
                    "market_cap": mcap,
                    "merton_dtd": round(dtd, 4) if not np.isnan(dtd) else np.nan,
                })

            print(f"  [{i+1}/{len(tickers_raw)}] {code} ({ticker_str}): OK")

        except Exception as e:
            print(f"  [{i+1}/{len(tickers_raw)}] {code}: ERROR {e}")

    cache = pd.DataFrame(rows)
    cache.to_csv(CACHE_FILE, index=False)
    print(f"\n저장: {CACHE_FILE}")
    print(f"행수: {len(cache)}, DtD 계산 성공: {cache['merton_dtd'].notna().sum()}")

    # 통계 요약
    print("\nDtD 분포:")
    print(cache["merton_dtd"].describe().round(3))
    return cache


if __name__ == "__main__":
    build_cache()

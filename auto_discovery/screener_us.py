"""
미국 ETF / 배당귀족주 자동 발굴 스크리너

■ 동작 방식
  1. Watchlist (배당귀족 + 주요 ETF) 정의
  2. yfinance로 각 종목 데이터 수집:
     - dividendYield, 52주 가격, 5Y 성장률 추정
  3. 기준 필터 적용:
     - 배당수익률 >= MIN_YIELD_PCT
     - AUM / 시총 >= MIN_SIZE
     - 기존 유니버스에 없는 신규만 반환
  4. 결과: 후보 종목 리스트 (evaluator.py로 전달)

■ Watchlist 구성 원칙
  "배당과 현금흐름을 만드는 자산만"
  - 밈주식, 테마주, 레버리지 ETF 절대 포함 안 함
  - 배당 귀족 (25년+ 배당 증가), 배당 ETF, 리츠, 채권 ETF만
"""

import time
from typing import Any

# ── Watchlist: 검토 대상 후보군 ────────────────────────────────
# 여기에 추가하면 자동으로 평가 대상이 됨

# 미국 배당귀족 개별주 (25년+ 배당 증가, ML 학습용으로도 사용)
DIVIDEND_ARISTOCRATS: list[dict] = [
    # 소비재 — 경기 방어적, 배당 매우 안정적
    {"ticker": "KO",  "name": "Coca-Cola",            "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 4.0},
    {"ticker": "PG",  "name": "Procter & Gamble",      "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 5.0},
    {"ticker": "CL",  "name": "Colgate-Palmolive",     "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 4.0},
    {"ticker": "JNJ", "name": "Johnson & Johnson",     "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 3.5},
    # 금융
    {"ticker": "AFL", "name": "Aflac",                 "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 6.0},
    {"ticker": "ADP", "name": "ADP",                   "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 8.0},
    # 에너지 / 유틸리티
    {"ticker": "XOM", "name": "Exxon Mobil",           "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 5.0},
    {"ticker": "CVX", "name": "Chevron",               "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 5.0},
    {"ticker": "SO",  "name": "Southern Company",      "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 3.0},
    # 통신 (배당 삭감 이력 있음 → ML Label=1 확보용)
    {"ticker": "T",   "name": "AT&T",                  "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 1.0},
    {"ticker": "VZ",  "name": "Verizon",               "asset_class": "us_stock", "account": "일반", "expected_cap_gain": 1.5},
]

# 미국 배당 ETF 후보군
US_DIV_ETF_WATCHLIST: list[dict] = [
    # 안정형 배당 ETF
    {"ticker": "SCHD",  "name": "Schwab US Dividend",     "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 8.0},
    {"ticker": "VYM",   "name": "Vanguard High Dividend",  "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 6.0},
    {"ticker": "DGRO",  "name": "iShares Dividend Growth", "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 9.0},
    {"ticker": "DGRW",  "name": "WisdomTree US Dividend",  "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 10.0},
    {"ticker": "DVY",   "name": "iShares Select Dividend", "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 3.0},
    {"ticker": "SPYD",  "name": "SPDR Portfolio S&P Div",  "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 4.0},
    # 월배당 커버드콜
    {"ticker": "JEPI",  "name": "JPMorgan Equity Premium", "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 2.0},
    {"ticker": "JEPQ",  "name": "JPMorgan Nasdaq Premium", "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 3.0},
    {"ticker": "QYLD",  "name": "Global X NASDAQ Covered", "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 0.0},
    # 성장+배당 균형
    {"ticker": "VIG",   "name": "Vanguard Div Appreciation","asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 8.5},
    {"ticker": "SDY",   "name": "SPDR S&P Dividend ETF",   "asset_class": "us_div_etf", "account": "일반/연금", "expected_cap_gain": 4.5},
]

# 미국 리츠 ETF / 개별 리츠
US_REIT_WATCHLIST: list[dict] = [
    {"ticker": "O",    "name": "Realty Income",         "asset_class": "us_reit", "account": "일반/연금", "expected_cap_gain": 2.0},
    {"ticker": "STAG", "name": "STAG Industrial",       "asset_class": "us_reit", "account": "일반/연금", "expected_cap_gain": 3.0},
    {"ticker": "MAIN", "name": "Main Street Capital",   "asset_class": "us_reit", "account": "일반/연금", "expected_cap_gain": 5.0},
    {"ticker": "VNQ",  "name": "Vanguard Real Estate",  "asset_class": "us_reit", "account": "일반/연금", "expected_cap_gain": 3.5},
    {"ticker": "REIT", "name": "ALPS Active REIT ETF",  "asset_class": "us_reit", "account": "일반/연금", "expected_cap_gain": 3.0},
]

# 방어형 채권 ETF
DEFENSIVE_WATCHLIST: list[dict] = [
    {"ticker": "TLT",  "name": "iShares 20Y Treasury",  "asset_class": "defensive", "account": "일반/연금", "expected_cap_gain": 0.0},
    {"ticker": "IEF",  "name": "iShares 7-10Y Treasury","asset_class": "defensive", "account": "일반/연금", "expected_cap_gain": 0.5},
    {"ticker": "BND",  "name": "Vanguard Total Bond",   "asset_class": "defensive", "account": "일반/연금", "expected_cap_gain": 0.0},
    {"ticker": "SHY",  "name": "iShares 1-3Y Treasury", "asset_class": "defensive", "account": "일반/연금", "expected_cap_gain": 0.0},
    {"ticker": "AGG",  "name": "iShares Core US Agg",   "asset_class": "defensive", "account": "일반/연금", "expected_cap_gain": 0.5},
]

# 전체 워치리스트
ALL_WATCHLIST = (
    DIVIDEND_ARISTOCRATS
    + US_DIV_ETF_WATCHLIST
    + US_REIT_WATCHLIST
    + DEFENSIVE_WATCHLIST
)

# ── 스크리닝 기준 ──────────────────────────────────────────────
MIN_YIELD_PCT       = 1.5    # 최소 배당수익률 (방어형 채권 포함 위해 낮게)
MIN_TOTAL_RETURN    = 4.0    # 최소 Total Return (은행 금리 이상)
MIN_MARKET_CAP_B    = 1.0    # 최소 시총 (십억 달러)


def fetch_yfinance_data(ticker: str) -> dict[str, Any]:
    """yfinance로 ETF/주식 데이터 수집. 실패 시 빈 dict 반환."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return {
            "dividendYield":     info.get("dividendYield") or 0,
            "marketCap":         info.get("marketCap") or info.get("totalAssets") or 0,
            "trailingPE":        info.get("trailingPE"),
            "payoutRatio":       info.get("payoutRatio") or 0,
            "fiveYearAvgDividendYield": info.get("fiveYearAvgDividendYield") or 0,
            "shortName":         info.get("shortName", ticker),
        }
    except ImportError:
        return {}
    except Exception:
        return {}


def screen_us_assets(existing_tickers: set[str] | None = None) -> list[dict]:
    """
    미국 ETF / 배당귀족주 자동 발굴 메인 함수.

    Parameters
    ----------
    existing_tickers : 이미 유니버스에 있는 티커 집합 (중복 제거)

    Returns
    -------
    list[dict] : 평가 통과 후보 리스트
    """
    existing_tickers = existing_tickers or set()
    results = []

    print("  [US] 미국 자산 스크리닝 시작...")

    for item in ALL_WATCHLIST:
        ticker = item["ticker"]

        # 이미 유니버스에 있으면 건너뜀 (재평가는 orchestrator가 담당)
        if ticker in existing_tickers:
            continue

        # yfinance 데이터 수집
        yf_data = fetch_yfinance_data(ticker)
        time.sleep(0.2)

        div_yield = yf_data.get("dividendYield", 0) * 100  # 소수 → %
        cap_gain  = item.get("expected_cap_gain", 0)
        total_return = div_yield + cap_gain

        # 기준 필터
        if div_yield < MIN_YIELD_PCT:
            # yfinance 실패 시 워치리스트 기본값으로 폴백
            # (네트워크 차단 환경에서도 동작하도록)
            div_yield    = item.get("expected_yield", 0) or 0
            total_return = div_yield + cap_gain
            if div_yield < MIN_YIELD_PCT:
                print(f"    SKIP {ticker}: yield {div_yield:.1f}% < {MIN_YIELD_PCT}%")
                continue

        if total_return < MIN_TOTAL_RETURN:
            print(f"    SKIP {ticker}: TR {total_return:.1f}% < {MIN_TOTAL_RETURN}%")
            continue

        results.append({
            "ticker":            ticker,
            "name":              yf_data.get("shortName") or item["name"],
            "asset_class":       item["asset_class"],
            "account":           item["account"],
            "risk_profile":      _infer_risk(item["asset_class"], div_yield),
            "expected_yield":    round(div_yield, 2),
            "capital_gain_rate": cap_gain,
            "total_return_est":  round(total_return, 2),
            "source":            "WATCHLIST_AUTO",
            "description":       _build_desc(item, div_yield, cap_gain, total_return),
        })
        print(f"    ✅ {ticker}: 배당 {div_yield:.1f}% + 성장 {cap_gain}% = TR {total_return:.1f}%")

    print(f"  [US] 최종 후보: {len(results)}개")
    return results


def _infer_risk(asset_class: str, div_yield: float) -> str:
    if asset_class == "defensive":
        return "defensive"
    if div_yield >= 7:
        return "moderate"   # 고배당 = 커버드콜 전략 → 변동성 있음
    return "stable"


def _build_desc(item: dict, dy: float, cg: float, tr: float) -> str:
    base = item["name"]
    if dy > 0 and tr > 0:
        return f"{base} — 배당 {dy:.1f}% + 자본차익 {cg}% = 기대 TR {tr:.1f}%. 자동 스크리닝 통과"
    return f"{base} — 자동 발굴 후보"


def get_all_watchlist_tickers() -> list[str]:
    """전체 워치리스트 티커 목록 반환 (중복 제거용)."""
    return list({item["ticker"] for item in ALL_WATCHLIST})

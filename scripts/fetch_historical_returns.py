"""
scripts/fetch_historical_returns.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

선행 ETF (proxy)의 실제 연간 수익률을 yfinance로 받아서
utils/backtesting.py 의 _ASSET_HIST_RETURNS 의 합성 부분을
실제 데이터로 보강하는 스크립트.

목적:
  현재 _ASSET_HIST_RETURNS 의 합성 데이터(예: SCHD 2005~2010)는
  팩트시트 추정치다. 이를 실제 선행 ETF(SCHX, SDY, DVY) 데이터로
  교체하여 학술적 정직성과 데이터 정확도를 모두 확보한다.

실행 (사용자 mac에서):
  cd ~/ai-analyst
  source venv/bin/activate
  python scripts/fetch_historical_returns.py

  # 또는 일부 종목만:
  python scripts/fetch_historical_returns.py --proxies SCHX,SDY,DVY

산출물:
  data/proxy_historical_returns.json
    예: {"SCHX": {2009: 8.2, 2010: 14.1, ...}, "SDY": {...}}

다음 단계:
  utils/backtesting.py 의 _ASSET_HIST_RETURNS 합성 부분을
  proxy_historical_returns.json 데이터로 자동 갱신
  (별도 함수 update_synthetic_from_proxies()).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("fetch_proxies")

# ─────────────────────────────────────────────────────────────
# 선행 ETF 정의 — utils/backtesting.py _SYNTHETIC_PROXY_MAP 와 일치
# ─────────────────────────────────────────────────────────────
PROXY_TICKERS: dict[str, dict] = {
    # 미국 대형주·배당 인덱스 — SCHD/DGRO/HDV/NOBL 합성용
    "SCHX": {"name": "Schwab US Large-Cap",            "inception": 2009},
    "SDY":  {"name": "SPDR S&P Dividend",               "inception": 2005},
    "DVY":  {"name": "iShares Select Dividend",         "inception": 2003},
    "VIG":  {"name": "Vanguard Dividend Appreciation",  "inception": 2006},
    "SPY":  {"name": "SPDR S&P 500 (벤치마크)",         "inception": 1993},
    "IWM":  {"name": "iShares Russell 2000",            "inception": 2000},
}


def fetch_yearly_returns(ticker: str, start: str = "2005-01-01") -> dict[int, float]:
    """
    yfinance 로 일별 가격 → 연도별 총수익률(%) 계산.

    반환: {2005: 6.2, 2006: 13.5, ...}

    가격이 없는 연도는 키 자체 없음 (스파스 dict).
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance 미설치. `pip install yfinance` 후 재시도.")
        return {}

    log.info("Fetching %s (start=%s)...", ticker, start)
    try:
        hist = yf.Ticker(ticker).history(start=start, auto_adjust=True)
    except Exception as e:
        log.error("%s 조회 실패: %s", ticker, e)
        return {}

    if hist.empty:
        log.warning("%s 데이터 없음 (delisted?)", ticker)
        return {}

    # 일별 → 연도별 첫/마지막 가격으로 수익률 계산
    yearly: dict[int, float] = {}
    by_year = hist.groupby(hist.index.year)
    for year, group in by_year:
        if len(group) < 100:  # 1년치 데이터가 너무 적으면 skip
            continue
        try:
            first_price = float(group["Close"].iloc[0])
            last_price  = float(group["Close"].iloc[-1])
            if first_price > 0:
                ret_pct = (last_price / first_price - 1) * 100
                yearly[int(year)] = round(ret_pct, 2)
        except (IndexError, KeyError, ValueError):
            continue

    log.info("  → %s: %d개 연도 (%s~%s)",
             ticker,
             len(yearly),
             min(yearly) if yearly else "?",
             max(yearly) if yearly else "?")
    return yearly


def main():
    parser = argparse.ArgumentParser(description="선행 ETF 실데이터 수집")
    parser.add_argument(
        "--proxies",
        type=str,
        default=None,
        help="쉼표 구분 티커 (예: SCHX,SDY). 미지정 시 전체.",
    )
    parser.add_argument("--start", type=str, default="2005-01-01")
    parser.add_argument("--sleep", type=float, default=1.5, help="rate limit")
    parser.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "data" / "proxy_historical_returns.json"),
    )
    args = parser.parse_args()

    targets = (
        [t.strip().upper() for t in args.proxies.split(",")]
        if args.proxies
        else list(PROXY_TICKERS.keys())
    )

    log.info("━" * 60)
    log.info("선행 ETF 실데이터 수집 (yfinance)")
    log.info("대상: %s", targets)
    log.info("━" * 60)

    results: dict[str, dict] = {}
    for i, ticker in enumerate(targets, 1):
        meta = PROXY_TICKERS.get(ticker, {})
        log.info("[%d/%d] %s (%s)", i, len(targets),
                 ticker, meta.get("name", "?"))

        yearly = fetch_yearly_returns(ticker, start=args.start)
        if yearly:
            results[ticker] = {
                "name":      meta.get("name", ticker),
                "inception": meta.get("inception"),
                "returns":   yearly,
                "fetched_at": datetime.now().isoformat(timespec="seconds"),
            }
        else:
            log.warning("  → %s 빈 결과, 스킵", ticker)

        if i < len(targets):
            time.sleep(args.sleep)

    # 저장
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("━" * 60)
    log.info("✓ 저장 완료: %s", output_path)
    log.info("총 %d/%d 티커 수집 성공", len(results), len(targets))
    log.info("━" * 60)
    log.info("다음 단계:")
    log.info("  utils/backtesting.py 의 _ASSET_HIST_RETURNS 의")
    log.info("  합성 부분(SCHD 2005~2010 등)을 이 데이터로 교체:")
    log.info("    SCHD 2005~2008 → SDY 또는 DVY 데이터")
    log.info("    SCHD 2009~2010 → SCHX 데이터")
    log.info("    DGRO 2005~2013 → VIG 데이터")


if __name__ == "__main__":
    main()

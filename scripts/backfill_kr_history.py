"""
scripts/backfill_kr_history.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

approved_universe_kr_v2.json 의 한국 종목들에 대해
pykrx로 연도별 가격 수익률·배당수익률을 백필.

목적:
  현재 _KR_SECTOR_RETURNS는 섹터 평균 추정치다.
  종목별 개별 실데이터로 교체해 백테스팅 정확도 향상.

실행 (사용자 mac에서):
  cd ~/ai-analyst
  source venv/bin/activate
  python scripts/backfill_kr_history.py

  # 일부만 시험:
  python scripts/backfill_kr_history.py --limit 5

산출물:
  data/kr_historical_returns.json
    {
      "005930": {
        "name": "삼성전자",
        "yearly_returns": {2015: 41.3, 2016: 41.7, ...},
        "yearly_dividends": {2015: 1.6, 2016: 1.9, ...},
        "data_start_year": 2005,
        "missing_years": []
      },
      ...
    }
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
log = logging.getLogger("backfill_kr")

# pykrx 내부 로깅 억제 (알려진 버그: logging.info() 호출 시 string formatting 오류)
logging.getLogger("pykrx").setLevel(logging.CRITICAL)
logging.getLogger("pykrx.website").setLevel(logging.CRITICAL)
logging.getLogger("pykrx.website.comm").setLevel(logging.CRITICAL)
logging.getLogger("pykrx.website.comm.util").setLevel(logging.CRITICAL)
# requests 경고도 억제
import warnings
warnings.filterwarnings("ignore")


def fetch_yearly_price_return(ticker: str, year: int) -> float | None:
    """
    pykrx로 특정 종목의 특정 연도 시작가/종가 비교 → 가격 수익률.

    반환: 수익률(%) 또는 None (데이터 없음)
    """
    try:
        from pykrx import stock
    except ImportError:
        log.error("pykrx 미설치. `pip install pykrx`")
        return None

    try:
        df = stock.get_market_ohlcv(
            f"{year}0101", f"{year}1231", ticker
        )
        if df.empty:
            return None
        first_close = float(df.iloc[0]["종가"])
        last_close = float(df.iloc[-1]["종가"])
        if first_close <= 0:
            return None
        return round((last_close / first_close - 1) * 100, 2)
    except Exception as e:
        log.debug("  %s %d 가격 조회 실패: %s", ticker, year, e)
        return None


def fetch_yearly_dividend_yield(ticker: str, year: int) -> float | None:
    """
    pykrx로 특정 종목의 특정 연도 배당수익률.

    주의 (2026.05 기준):
      KRX get_market_fundamental API가 빈 JSON 반환하여
      실질적으로 동작 안 함. None 반환.
      배당 데이터는 dividend_dataset.csv (DART 기반) 사용 권장.
    """
    try:
        from pykrx import stock
    except ImportError:
        return None

    try:
        # KRX API 직접 호출 — 실패 시 silent
        df = stock.get_market_fundamental(
            f"{year}1231", f"{year}1231", ticker
        )
        if df is None or df.empty or "DIV" not in df.columns:
            return None
        val = float(df.iloc[0]["DIV"])
        return round(val, 2) if val > 0 else None
    except Exception:
        # KRX 서버 응답 형식 오류·rate limit·종목 누락 등 모두 조용히 패스
        return None


def backfill_ticker(
    ticker: str, name: str,
    start_year: int = 2005, end_year: int = 2024,
    sleep_sec: float = 0.3,
    fetch_div: bool = False,
) -> dict:
    """
    단일 종목에 대해 start_year~end_year 연도별 데이터 수집.

    Args:
        fetch_div: KRX 배당 API 호출 여부. 기본 False (2026.05 기준 동작 안 함).
                   배당 데이터는 dividend_dataset.csv 사용 권장.
    """
    yearly_returns: dict[int, float] = {}
    yearly_divs: dict[int, float] = {}
    missing: list[int] = []

    for year in range(start_year, end_year + 1):
        ret = fetch_yearly_price_return(ticker, year)
        div = fetch_yearly_dividend_yield(ticker, year) if fetch_div else None

        if ret is not None:
            yearly_returns[year] = ret
        if div is not None:
            yearly_divs[year] = div

        if ret is None and div is None:
            missing.append(year)

        time.sleep(sleep_sec)

    actual_years = sorted(yearly_returns.keys())
    data_start = actual_years[0] if actual_years else None
    coverage_pct = (
        round(100 * len(yearly_returns) / (end_year - start_year + 1), 1)
        if (end_year - start_year + 1) > 0 else 0
    )

    return {
        "name":             name,
        "yearly_returns":   yearly_returns,
        "yearly_dividends": yearly_divs,
        "data_start_year":  data_start,
        "data_end_year":    actual_years[-1] if actual_years else None,
        "missing_years":    missing,
        "coverage_pct":     coverage_pct,
        "fetched_at":       datetime.now().isoformat(timespec="seconds"),
    }


def main():
    parser = argparse.ArgumentParser(description="한국 종목 pykrx 백필")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start", type=int, default=2005)
    parser.add_argument("--end",   type=int, default=2024)
    parser.add_argument("--sleep", type=float, default=0.3)
    parser.add_argument(
        "--with-divs", action="store_true",
        help="KRX 배당 API 호출 (기본 OFF, 2026.05 기준 서버 불안정)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=str(ROOT / "data" / "approved_universe_kr_v2.json"),
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "data" / "kr_historical_returns.json"),
    )
    args = parser.parse_args()

    # 1. 유니버스 로드
    with open(args.input, encoding="utf-8") as f:
        universe_data = json.load(f)

    tickers = universe_data.get("universe", [])
    if args.limit:
        tickers = tickers[: args.limit]

    log.info("━" * 60)
    log.info("한국 종목 백필 — %d개 종목 × %d년 (%d~%d)",
             len(tickers), args.end - args.start + 1, args.start, args.end)
    log.info("예상 소요: 약 %d초 (%.1f분)",
             len(tickers) * (args.end - args.start + 1) * args.sleep * 2,
             len(tickers) * (args.end - args.start + 1) * args.sleep * 2 / 60)
    log.info("━" * 60)

    results: dict[str, dict] = {}
    for i, profile in enumerate(tickers, 1):
        ticker = profile["ticker"]
        name   = profile["name"]
        log.info("[%d/%d] %s %s", i, len(tickers), ticker, name)

        try:
            info = backfill_ticker(
                ticker, name,
                start_year=args.start, end_year=args.end,
                sleep_sec=args.sleep,
                fetch_div=args.with_divs,
            )
            results[ticker] = info
            log.info("  → 가격 %d년 / 배당 %d년 / 누락 %d년 / 커버리지 %.1f%%",
                     len(info["yearly_returns"]),
                     len(info["yearly_dividends"]),
                     len(info["missing_years"]),
                     info["coverage_pct"])
        except Exception as e:
            log.error("  → 실패: %s", e)

    # 저장
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    log.info("━" * 60)
    log.info("✓ 저장 완료: %s", output)

    # 요약 통계
    if results:
        coverages = [r["coverage_pct"] for r in results.values()]
        avg_cov = sum(coverages) / len(coverages)
        log.info("평균 커버리지: %.1f%%", avg_cov)
        log.info("100%% 종목: %d개 / 90%%+ 종목: %d개",
                 sum(1 for c in coverages if c >= 100),
                 sum(1 for c in coverages if c >= 90))


if __name__ == "__main__":
    main()

"""
data_updater.py — 데이터 자동 갱신 파이프라인

왜 필요한가?
  yfinance는 가끔 실패하고, 한국 ETF는 yfinance 지원이 불완전하다.
  이 모듈은 3단계 우선순위로 수익률·성장률을 갱신한다:
    1. yfinance 실시간 조회 (US 자산)
    2. KRX/네이버 파싱 (한국 ETF)
    3. yield_cache.json 읽기 (캐시 HIT)
    4. asset_metadata.json fallback (정적 기준값)

실행 방법:
  python utils/data_updater.py             # 전체 갱신
  python utils/data_updater.py --ticker SCHD  # 특정 종목만
  python utils/data_updater.py --dry-run   # 조회만 하고 저장 안 함

스케줄링 (매일 오전 7시):
  cron: 0 7 * * * cd /path/to/ai-analyst && python utils/data_updater.py
"""

import json
import pathlib
import argparse
import logging
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ── 경로 설정 ────────────────────────────────────────────────────
BASE     = pathlib.Path(__file__).parent.parent
YIELD_C  = BASE / "data" / "yield_cache.json"
META_P   = BASE / "data" / "asset_metadata.json"
MACRO_P  = BASE / "data" / "macro_config.json"
ETF_QC   = BASE / "data" / "etf_quality_cache.json"

TTL_HOURS = 24   # 캐시 유효 시간

# ── 한국 ETF 목록 (yfinance 대신 KRX 사용) ───────────────────────
KR_ETF_CODES = {
    "448290": "TIGER 미국배당다우존스",
    "385720": "TIGER 리츠부동산인프라",
    "279530": "KODEX 고배당",
    "211560": "TIGER 배당성장",
    "441680": "KODEX 배당성장채권혼합",
    "456680": "TIGER 미국MSCI리츠",
}

# ── Tier 1: yfinance 실시간 조회 ─────────────────────────────────
def _fetch_yfinance(tickers: list[str]) -> dict[str, dict]:
    """
    yfinance로 배당수익률 조회.
    반환: {ticker: {"yield_pct": float, "div_growth_rate_pct": float}}

    yfinance의 dividendYield가 None이면 trailing 12개월 배당 합계/현재가로 직접 계산.
    """
    results: dict[str, dict] = {}
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance 미설치 — pip install yfinance")
        return results

    log.info(f"[yfinance] {len(tickers)}개 조회 중...")

    for ticker in tickers:
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            # 배당수익률
            raw_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield")
            if raw_yield and raw_yield > 0:
                yield_pct = round(raw_yield * 100, 2)
            else:
                # 직접 계산: 최근 12개월 배당 합계 / 현재가
                divs = t.dividends
                if divs is not None and len(divs) > 0:
                    recent = divs[divs.index >= (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")]
                    annual_div = float(recent.sum()) if len(recent) > 0 else 0.0
                    price = info.get("regularMarketPrice") or info.get("currentPrice") or 0
                    yield_pct = round(annual_div / price * 100, 2) if price > 0 else 0.0
                else:
                    yield_pct = 0.0

            if yield_pct <= 0:
                log.debug(f"  {ticker}: yield=0 (배당 없음 또는 조회 실패)")
                continue

            # 배당 5년 성장률 (CAGR) — 있으면 계산, 없으면 None
            div_cagr = None
            try:
                divs = t.dividends
                if divs is not None and len(divs) >= 8:
                    recent_1y = float(divs[divs.index >= (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")].sum())
                    past_5y   = float(divs[divs.index <= (datetime.now() - timedelta(days=365*5)).strftime("%Y-%m-%d")].tail(4).sum())
                    if past_5y > 0 and recent_1y > 0:
                        div_cagr = round(((recent_1y / past_5y) ** (1/5) - 1) * 100, 2)
            except Exception:
                pass

            results[ticker] = {
                "yield_pct":           yield_pct,
                "div_growth_rate_pct": div_cagr,   # None이면 캐시값 유지
                "source":              "yfinance",
            }
            log.info(f"  ✅ {ticker}: yield={yield_pct}%  growth={div_cagr}%")

        except Exception as e:
            log.warning(f"  ❌ {ticker}: {e}")

    return results


# ── Tier 2: 한국 ETF — 네이버 금융 파싱 ──────────────────────────
def _fetch_kr_etf(codes: list[str]) -> dict[str, dict]:
    """
    네이버 금융에서 한국 ETF 배당수익률 파싱.
    반환: {code: {"yield_pct": float, "source": str}}
    """
    results: dict[str, dict] = {}
    try:
        import urllib.request, re
    except ImportError:
        return results

    for code in codes:
        url = f"https://finance.naver.com/item/main.naver?code={code}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                html = resp.read().decode("euc-kr", errors="replace")

            # 배당수익률 파싱 (네이버 금융 패턴)
            m = re.search(r'배당수익률.*?(\d+\.\d+)\s*%', html)
            if m:
                yield_pct = float(m.group(1))
                results[code] = {"yield_pct": yield_pct, "div_growth_rate_pct": None, "source": "naver"}
                log.info(f"  ✅ KR {code}: yield={yield_pct}%")
            else:
                log.debug(f"  KR {code}: 파싱 실패 (패턴 없음)")
        except Exception as e:
            log.debug(f"  KR {code}: {e}")

    return results


# ── Tier 3: 캐시 읽기 ───────────────────────────────────────────
def _load_cache() -> dict:
    if not YIELD_C.exists():
        return {}
    with open(YIELD_C) as f:
        data = json.load(f)
    # v2.0 구조: {"assets": {ticker: {...}}}
    return data.get("assets", data.get("yields", {}))


def _is_stale(entry: dict, ttl_hours: int = TTL_HOURS) -> bool:
    updated_str = entry.get("updated_at", "")
    if not updated_str:
        return True
    try:
        updated = datetime.strptime(updated_str, "%Y-%m-%d")
        return (datetime.now() - updated) > timedelta(hours=ttl_hours)
    except ValueError:
        return True


# ── Tier 4: asset_metadata.json fallback ────────────────────────
def _load_metadata_fallback() -> dict[str, dict]:
    if not META_P.exists():
        return {}
    with open(META_P) as f:
        meta = json.load(f)
    result = {}
    for section_key in ("us_div_etf", "us_reit", "kr_reit", "defensive", "us_stock", "kr_etf"):
        section = meta.get(section_key, {})
        for ticker, asset in section.items():
            if not isinstance(asset, dict):
                continue
            result[ticker] = {
                "yield_pct":           asset.get("yield_pct", 0.0),
                "div_growth_rate_pct": asset.get("div_growth_rate_pct", 0.0),
                "source":              "metadata_fallback",
            }
    return result


# ── 매크로 지표 갱신 ─────────────────────────────────────────────
def _update_macro() -> Optional[dict]:
    """
    VIX, US10Y, Fed Rate를 yfinance로 갱신.
    실패 시 기존 macro_config.json 유지.
    """
    try:
        import yfinance as yf

        vix_data    = yf.Ticker("^VIX").history(period="1d")
        tnx_data    = yf.Ticker("^TNX").history(period="1d")   # 10Y yield
        irx_data    = yf.Ticker("^IRX").history(period="1d")   # 3M T-Bill (≈ Fed Rate proxy)

        vix      = round(float(vix_data["Close"].iloc[-1]), 2) if len(vix_data) > 0 else None
        us_10y   = round(float(tnx_data["Close"].iloc[-1]) / 10, 2) if len(tnx_data) > 0 else None  # ^TNX는 10배 스케일
        fed_prxy = round(float(irx_data["Close"].iloc[-1]) / 100, 2) if len(irx_data) > 0 else None

        # USD/KRW
        usd_krw_data = yf.Ticker("KRW=X").history(period="1d")
        usd_krw = round(float(usd_krw_data["Close"].iloc[-1]), 0) if len(usd_krw_data) > 0 else None

        result = {}
        if vix:    result["vix"]       = vix
        if us_10y: result["us_10y_yield"] = us_10y
        if usd_krw: result["usd_krw"]  = usd_krw

        if result:
            # 기존 파일 읽어서 갱신된 값만 덮어쓰기
            existing = {}
            if MACRO_P.exists():
                with open(MACRO_P) as f:
                    existing = json.load(f)
            existing.update(result)
            existing["_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            log.info(f"[macro] 갱신: {result}")
            return existing
    except Exception as e:
        log.warning(f"[macro] 갱신 실패: {e}")
    return None


# ── 메인 갱신 함수 ───────────────────────────────────────────────
def update_all(
    tickers: Optional[list[str]] = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    전체 데이터 갱신 파이프라인.

    우선순위:
      1. yfinance (US 자산, 신선도 우선)
      2. 네이버 금융 (KR ETF)
      3. yield_cache.json (TTL 이내)
      4. asset_metadata.json (정적 fallback)

    Args:
        tickers: 특정 티커만 갱신 (None=전체)
        dry_run: True면 저장 안 함
        force:   True면 TTL 무시하고 강제 재조회

    반환:
        {"updated": int, "skipped": int, "failed": int, "assets": dict}
    """
    log.info("=== 데이터 갱신 파이프라인 시작 ===")

    # 현재 캐시 로드
    cache = _load_cache()
    metadata_fb = _load_metadata_fallback()

    # 갱신 대상 결정
    if tickers:
        target_us  = [t for t in tickers if not t.isdigit()]
        target_kr  = [t for t in tickers if t.isdigit()]
    else:
        all_known  = set(cache.keys()) | set(metadata_fb.keys())
        target_us  = [t for t in all_known if not t.isdigit() and not t.startswith("_")]
        target_kr  = list(KR_ETF_CODES.keys())

    # 스테일 여부 필터링 (force=False면 TTL 이내 항목 스킵)
    if not force:
        target_us = [t for t in target_us
                     if t not in cache or _is_stale(cache.get(t, {}), TTL_HOURS)]
        target_kr = [t for t in target_kr
                     if t not in cache or _is_stale(cache.get(t, {}), TTL_HOURS)]

    log.info(f"  갱신 대상: US {len(target_us)}개, KR {len(target_kr)}개")

    stats = {"updated": 0, "skipped": 0, "failed": 0}
    today = datetime.now().strftime("%Y-%m-%d")

    # ── Tier 1: yfinance ────────────────────────────────────────
    yf_results = _fetch_yfinance(target_us) if target_us else {}

    # ── Tier 2: 네이버 (KR ETF) ─────────────────────────────────
    kr_results = _fetch_kr_etf(target_kr) if target_kr else {}

    # ── 캐시 병합 ────────────────────────────────────────────────
    # 갱신 대상 전체를 순회하며 최종값 결정
    for ticker in set(target_us + target_kr) | set(cache.keys()):
        if ticker.startswith("_"):
            continue

        # 소스 우선순위 결정
        live = yf_results.get(ticker) or kr_results.get(ticker)
        cached = cache.get(ticker, {})
        fallback = metadata_fb.get(ticker, {})

        if live:
            # yfinance/naver 성공 → 갱신
            new_entry = {
                "yield_pct":           live["yield_pct"],
                "div_growth_rate_pct": live["div_growth_rate_pct"]
                                       if live["div_growth_rate_pct"] is not None
                                       else cached.get("div_growth_rate_pct",
                                            fallback.get("div_growth_rate_pct", 0.0)),
                "updated_at":          today,
                "source":              live["source"],
                "stale":               False,
            }
            # name_kr 보존
            if "name_kr" in cached:
                new_entry["name_kr"] = cached["name_kr"]
            elif ticker in KR_ETF_CODES:
                new_entry["name_kr"] = KR_ETF_CODES[ticker]

            cache[ticker] = new_entry
            stats["updated"] += 1

        elif cached and not _is_stale(cached, TTL_HOURS * 7):
            # 캐시 HIT (7일 이내) → 스킵
            stats["skipped"] += 1

        elif fallback:
            # metadata fallback 사용
            cache[ticker] = {
                "yield_pct":           fallback["yield_pct"],
                "div_growth_rate_pct": fallback["div_growth_rate_pct"],
                "updated_at":          today,
                "source":              "metadata_fallback",
                "stale":               True,
            }
            stats["failed"] += 1
            log.debug(f"  {ticker}: fallback 사용")

    # ── 매크로 지표 갱신 ─────────────────────────────────────────
    macro_new = _update_macro()

    # ── 저장 ─────────────────────────────────────────────────────
    if not dry_run:
        new_cache = {
            "_comment": "수익률·성장률 캐시. source=yfinance 항목은 TTL 초과 시 재조회.",
            "_schema_version": "2.0",
            "_updated": today,
            "_ttl_hours": TTL_HOURS,
            "_total_assets": len([k for k in cache if not k.startswith("_")]),
            "assets": cache,
        }
        with open(YIELD_C, "w", encoding="utf-8") as f:
            json.dump(new_cache, f, indent=2, ensure_ascii=False)
        log.info(f"yield_cache.json 저장: {len(cache)}개")

        if macro_new:
            with open(MACRO_P, "w", encoding="utf-8") as f:
                json.dump(macro_new, f, indent=2, ensure_ascii=False)
            log.info("macro_config.json 저장")

    log.info(f"=== 완료: 갱신 {stats['updated']}개 / 스킵 {stats['skipped']}개 / fallback {stats['failed']}개 ===")
    return {"stats": stats, "assets": cache}


# ── portfolio.py에서 임포트하는 헬퍼 함수 ────────────────────────
def get_yield(ticker: str) -> float:
    """
    단일 종목 수익률 반환.
    캐시 → metadata → 0.0 순서.
    """
    cache = _load_cache()
    entry = cache.get(ticker, {})
    if isinstance(entry, dict):
        return float(entry.get("yield_pct", 0.0))
    return float(entry) if entry else 0.0  # v1 캐시 호환


def get_div_growth(ticker: str) -> float:
    """단일 종목 배당성장률 반환."""
    cache = _load_cache()
    entry = cache.get(ticker, {})
    if isinstance(entry, dict):
        return float(entry.get("div_growth_rate_pct", 0.0))
    # metadata fallback
    fb = _load_metadata_fallback()
    return float(fb.get(ticker, {}).get("div_growth_rate_pct", 0.0))


def get_all_yields() -> dict[str, float]:
    """
    {ticker: yield_pct} 딕셔너리 반환.
    portfolio.py의 fetch_etf_yields() 대체 가능.
    """
    cache = _load_cache()
    result = {}
    for ticker, entry in cache.items():
        if ticker.startswith("_"):
            continue
        if isinstance(entry, dict):
            result[ticker] = float(entry.get("yield_pct", 0.0))
        else:
            result[ticker] = float(entry)  # v1 호환
    return result


# ── CLI 진입점 ────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="데이터 자동 갱신 파이프라인")
    parser.add_argument("--ticker", nargs="+", help="특정 티커만 갱신")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 조회만")
    parser.add_argument("--force",   action="store_true", help="TTL 무시하고 강제 재조회")
    args = parser.parse_args()

    result = update_all(
        tickers = args.ticker,
        dry_run = args.dry_run,
        force   = args.force,
    )
    s = result["stats"]
    print(f"\n결과: 갱신 {s['updated']}개 / 스킵 {s['skipped']}개 / fallback {s['failed']}개")

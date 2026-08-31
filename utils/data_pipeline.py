"""
utils/data_pipeline.py — 실시간 데이터 자동 갱신 파이프라인
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  현재: yfinance 수동 캐시(JSON 파일) → API 서버가 파일 읽음
  문제:
    1. 언제 갱신됐는지 모름 → "기준일" 표시 불신뢰
    2. 동시 Write 시 파일 오염 가능
    3. 서버 재시작 없이 데이터 갱신 불가

  해결:
    APScheduler로 주기적으로 yfinance 데이터 수집 → DB UPSERT
    API 서버는 항상 최신 DB에서 읽음

■ 갱신 주기
  ETF 수익률:     매일 장 마감 후 (17:00 KST)
  US 주식 점수:   매주 토요일 새벽 (00:00 KST)
  KR 배당 수익률: 매주 일요일 새벽 (00:00 KST) — pykrx 사용

■ 실행 방법
  1. 단독 실행:
     python utils/data_pipeline.py

  2. FastAPI 시작 시 자동 백그라운드 실행:
     app.py에서 import 후 start_scheduler() 호출

  3. 수동 1회 실행:
     from utils.data_pipeline import run_all_updates
     run_all_updates()
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── ETF 유니버스 (수익률 갱신 대상) ──────────────────────────
ETF_TICKERS = [
    "SCHD", "VYM", "DGRO", "JEPI", "JEPQ", "SPYD",
    "HDV",  "NOBL", "SPHD", "QYLD",
    "TLT",  "BND",  "AGG",  "SCHP",
    "O",    "VNQ",
]

US_STOCK_TICKERS = [
    "KO", "JNJ", "PG", "XOM", "CVX", "ABBV",
    "MCD", "T",  "VZ", "IBM", "MO",  "PFE",
]


# ─────────────────────────────────────────────────────────────
# 1. ETF 수익률 갱신
# ─────────────────────────────────────────────────────────────
def update_etf_yields(to_db: bool = True, to_file: bool = True) -> dict:
    """
    yfinance로 ETF 배당수익률 갱신.
    DB UPSERT + JSON 파일 동시 갱신 (fallback 보존).
    """
    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance 미설치. pip install yfinance --break-system-packages")
        return {}

    results = {}
    updated_at = datetime.now(timezone.utc).isoformat()

    for ticker in ETF_TICKERS:
        try:
            info = yf.Ticker(ticker).info
            dy   = info.get("dividendYield") or info.get("yield") or 0
            dy_pct = round(float(dy) * 100, 2) if dy else 0

            results[ticker] = {
                "div_yield":    dy_pct,
                "updated_at":  updated_at,
                "name":        info.get("shortName", ticker),
                "expense_ratio": round(float(info.get("annualReportExpenseRatio", 0) or 0) * 100, 3),
                "aum_billion": round(float(info.get("totalAssets", 0) or 0) / 1e9, 2),
            }
        except Exception as e:
            log.warning("ETF %s 갱신 실패: %s", ticker, e)

    if not results:
        return results

    # DB UPSERT
    if to_db:
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            from sqlalchemy.orm import Session
            from db.models import ETFQuality

            engine = create_engine(
                os.environ.get("DATABASE_URL", "postgresql://localhost/ai_analyst"),
                pool_pre_ping=True
            )
            rows = [{"ticker": t, "div_yield": d["div_yield"],
                     "name": d.get("name"), "aum_billion": d.get("aum_billion", 0),
                     "expense_ratio": d.get("expense_ratio", 0),
                     "quality_score": 50.0, "pass_filter": True}
                    for t, d in results.items()]
            with Session(engine) as sess:
                stmt = pg_insert(ETFQuality).values(rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["ticker"],
                    set_={"div_yield": stmt.excluded.div_yield,
                          "aum_billion": stmt.excluded.aum_billion,
                          "expense_ratio": stmt.excluded.expense_ratio}
                )
                sess.execute(stmt)
                sess.commit()
            log.info("ETF yields DB UPSERT 완료: %d건", len(rows))
        except Exception as e:
            log.error("ETF DB UPSERT 실패: %s", e)

    # 파일 fallback 갱신
    if to_file:
        cache_path = os.path.join(BASE_DIR, "data", "etf_quality_cache.json")
        try:
            existing = {}
            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    existing = json.load(f)
            for ticker, data in results.items():
                existing.setdefault(ticker, {}).update(data)
            existing["_updated"] = updated_at
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            log.info("ETF yields 파일 갱신 완료: %s", cache_path)
        except Exception as e:
            log.error("ETF 파일 갱신 실패: %s", e)

    return results


# ─────────────────────────────────────────────────────────────
# 2. US 주식 수익률 갱신
# ─────────────────────────────────────────────────────────────
def update_us_stock_scores(to_file: bool = True) -> dict:
    """
    yfinance로 미국 배당주 핵심 지표 갱신.
    dividend_yield, trailing_pe, 52w_ratio 등.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {}

    results = {}
    for ticker in US_STOCK_TICKERS:
        try:
            info = yf.Ticker(ticker).info
            dy   = info.get("dividendYield") or 0
            dy_pct = round(float(dy) * 100, 2)
            week52_high = info.get("fiftyTwoWeekHigh") or 1
            current     = info.get("currentPrice") or info.get("regularMarketPrice") or 0
            ratio_52w   = round(current / week52_high, 3) if week52_high else 0.9

            results[ticker] = {
                "ticker":           ticker,
                "dividend_yield":   dy_pct,
                "pe_ratio":         round(float(info.get("trailingPE") or 0), 1),
                "payout_ratio":     round(float(info.get("payoutRatio") or 0) * 100, 1),
                "price_52w_ratio":  ratio_52w,
                "market_cap_b":     round(float(info.get("marketCap") or 0) / 1e9, 1),
                "name":             info.get("shortName", ticker),
                "updated_at":       datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            log.warning("US stock %s 갱신 실패: %s", ticker, e)

    if to_file and results:
        csv_path = os.path.join(BASE_DIR, "data", "us_stock_scores.csv")
        try:
            import pandas as pd
            df_new = pd.DataFrame(list(results.values()))
            # 기존 파일과 merge (ticker 기준)
            if os.path.exists(csv_path):
                df_old = pd.read_csv(csv_path)
                df_old = df_old[~df_old["ticker"].isin(df_new["ticker"])]
                df_all = pd.concat([df_old, df_new], ignore_index=True)
            else:
                df_all = df_new
            df_all.to_csv(csv_path, index=False)
            log.info("US stock scores 파일 갱신: %s", csv_path)
        except Exception as e:
            log.error("US stock CSV 갱신 실패: %s", e)

    return results


# ─────────────────────────────────────────────────────────────
# 3. KR 배당 수익률 갱신 (pykrx)
# ─────────────────────────────────────────────────────────────
def update_kr_yields(to_db: bool = True, to_file: bool = True) -> dict:
    """
    pykrx로 KRX 배당수익률 갱신.
    ranking.csv 종목코드 기준으로 최신 배당수익률 업데이트.
    """
    try:
        from pykrx import stock as pkrx
    except ImportError:
        log.warning("pykrx 미설치. pip install pykrx --break-system-packages")
        return {}

    ranking_csv = os.path.join(BASE_DIR, "data", "ranking.csv")
    if not os.path.exists(ranking_csv):
        return {}

    try:
        import pandas as pd
        df = pd.read_csv(ranking_csv, dtype={"stock_code": str})
        codes = df["stock_code"].str.zfill(6).tolist()[:30]  # 상위 30개만
    except Exception:
        return {}

    results = {}
    today = datetime.now().strftime("%Y%m%d")

    for code in codes:
        try:
            info = pkrx.get_market_fundamental(today, today, code)
            if info.empty:
                continue
            dy = float(info.iloc[-1].get("DIV", 0) or 0)
            results[code] = {
                "stock_code": code,
                "yield_pct":  round(dy, 2),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            log.debug("KR %s 갱신 실패: %s", code, e)

    if to_file and results:
        cache_path = os.path.join(BASE_DIR, "data", "kr_yield_cache.json")
        try:
            existing = {}
            if os.path.exists(cache_path):
                with open(cache_path, encoding="utf-8") as f:
                    existing = json.load(f)
            for code, data in results.items():
                existing[code] = data
            existing["_updated"] = datetime.now(timezone.utc).isoformat()
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            log.info("KR yield cache 갱신: %d건", len(results))
        except Exception as e:
            log.error("KR 파일 갱신 실패: %s", e)

    return results


# ─────────────────────────────────────────────────────────────
# 4. 전체 일괄 갱신
# ─────────────────────────────────────────────────────────────
def run_all_updates() -> dict:
    """모든 데이터 소스를 순서대로 갱신. 수동 1회 실행용."""
    log.info("=== 데이터 파이프라인 시작 ===")
    start = datetime.now()

    etf_result = update_etf_yields()
    log.info("ETF 갱신: %d종목", len(etf_result))

    us_result = update_us_stock_scores()
    log.info("US 주식 갱신: %d종목", len(us_result))

    kr_result = update_kr_yields()
    log.info("KR 배당 갱신: %d종목", len(kr_result))

    elapsed = (datetime.now() - start).total_seconds()
    log.info("=== 파이프라인 완료 (%.1fs) ===", elapsed)

    return {
        "etf_updated":      len(etf_result),
        "us_stock_updated": len(us_result),
        "kr_yield_updated": len(kr_result),
        "elapsed_sec":      round(elapsed, 1),
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# 5. APScheduler 기반 자동 스케줄링
# ─────────────────────────────────────────────────────────────
def start_scheduler():
    """
    FastAPI 앱 시작 시 호출해 백그라운드 스케줄러 실행.

    사용법 (main.py 또는 app.py):
        from utils.data_pipeline import start_scheduler
        app = FastAPI()

        @app.on_event("startup")
        async def startup():
            start_scheduler()
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        log.warning("APScheduler 미설치. pip install apscheduler --break-system-packages")
        log.warning("스케줄러 없이 시작. 수동으로 python utils/data_pipeline.py 실행.")
        return None

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")

    # ETF 수익률: 매일 17시 (장 마감 후)
    scheduler.add_job(
        update_etf_yields,
        CronTrigger(hour=17, minute=0),
        id="etf_yields",
        name="ETF 수익률 갱신",
        replace_existing=True,
    )

    # US 주식: 매주 토요일 00시
    scheduler.add_job(
        update_us_stock_scores,
        CronTrigger(day_of_week="sat", hour=0, minute=0),
        id="us_scores",
        name="US 주식 점수 갱신",
        replace_existing=True,
    )

    # KR 배당: 매주 일요일 01시 (pykrx 부하 분산)
    scheduler.add_job(
        update_kr_yields,
        CronTrigger(day_of_week="sun", hour=1, minute=0),
        id="kr_yields",
        name="KR 배당수익률 갱신",
        replace_existing=True,
    )

    # DART 신규 공시 감지: 매일 오전 6시 (장 시작 전)
    try:
        from utils.dart_watcher import scheduled_dart_watch
        scheduler.add_job(
            scheduled_dart_watch,
            CronTrigger(hour=6, minute=0),
            id="dart_watch",
            name="DART 신규 공시 감지",
            replace_existing=True,
        )
        log.info("  DART watcher: 매일 06:00 (KST)")
    except ImportError:
        log.warning("dart_watcher 없음 → DART 실시간 감지 비활성")

    scheduler.start()
    log.info("데이터 파이프라인 스케줄러 시작 완료")
    log.info("  ETF: 매일 17:00 / US: 토 00:00 / KR: 일 01:00 / DART: 매일 06:00 (KST)")
    return scheduler


# ─────────────────────────────────────────────────────────────
# 단독 실행
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    result = run_all_updates()
    print(f"\n갱신 완료: {result}")

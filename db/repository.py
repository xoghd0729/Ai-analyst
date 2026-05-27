"""
Repository — 데이터 접근 레이어
─────────────────────────────────
API 코드가 DB 또는 파일 캐시를 직접 알 필요 없도록 추상화.

왜 Repository 패턴인가?
  - DB 연결 실패 시 파일 fallback 자동 전환
  - 테스트에서 DB 없이 파일로 돌릴 수 있음
  - 나중에 Redis 캐시 레이어 추가 시 이 파일만 수정

사용 예:
    from db.repository import get_ml_scores, get_etf_quality

    ml = get_ml_scores()          # {stock_code: {...}}
    etf = get_etf_quality("SCHD") # dict or None
"""
from __future__ import annotations

import json
import logging
import os

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_URL   = os.environ.get("DATABASE_URL", "postgresql://localhost/ai_analyst")

# 파일 경로 (DB 없을 때 fallback)
_ML_CSV   = os.path.join(BASE_DIR, "data", "ml_scoring_results.csv")
_ETF_JSON = os.path.join(BASE_DIR, "data", "etf_quality_cache.json")
_META_JSON= os.path.join(BASE_DIR, "data", "asset_metadata.json")
_KR_YIELD = os.path.join(BASE_DIR, "data", "kr_yield_cache.json")

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        try:
            _engine = create_engine(DB_URL, pool_pre_ping=True)
            _engine.connect()
        except Exception as e:
            log.warning("DB 연결 실패, 파일 캐시로 fallback: %s", e)
            _engine = None
    return _engine


# ─────────────────────────────────────────────────────────────
# ML 예측 결과 로드
# ─────────────────────────────────────────────────────────────
def get_ml_scores() -> dict[str, dict]:
    """
    {stock_code: {ml_status, P_WEAKENING, P_BROKEN, ml_score, dps_yoy_pct}}
    DB 우선, 실패 시 CSV fallback.
    """
    engine = _get_engine()
    if engine:
        try:
            with Session(engine) as sess:
                rows = sess.execute(
                    text("SELECT stock_code, ml_status, p_weakening, p_broken, "
                         "       ml_score, dps_yoy_pct FROM ml_predictions")
                ).fetchall()
            return {
                r.stock_code: {
                    "ml_status":   r.ml_status,
                    "P_WEAKENING": round(float(r.p_weakening or 0), 3),
                    "P_BROKEN":    round(float(r.p_broken or 0), 3),
                    "ml_score":    round(float(r.ml_score or 0), 3),
                    "dps_yoy_pct": r.dps_yoy_pct,
                }
                for r in rows
            }
        except Exception as e:
            log.warning("ml_predictions DB 조회 실패: %s", e)

    # ── CSV fallback ──────────────────────────────────────────
    if not os.path.exists(_ML_CSV):
        return {}
    try:
        df = pd.read_csv(_ML_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        return {
            row["stock_code"]: {
                "ml_status":   row.get("ml_status", "INTACT"),
                "P_WEAKENING": round(float(row.get("P_WEAKENING", 0)), 3),
                "P_BROKEN":    round(float(row.get("P_BROKEN", 0)), 3),
                "ml_score":    round(float(row.get("ml_score", 0)), 3),
                "dps_yoy_pct": row.get("dps_yoy_pct"),
            }
            for _, row in df.iterrows()
        }
    except Exception as e:
        log.error("CSV fallback 실패: %s", e)
        return {}


# ─────────────────────────────────────────────────────────────
# ETF 품질 지표 로드
# ─────────────────────────────────────────────────────────────
def get_etf_quality(ticker: str | None = None) -> dict:
    """
    ticker 지정 시 단일 자산 반환, None 이면 전체 dict.
    DB 우선, 실패 시 JSON fallback.
    """
    engine = _get_engine()
    if engine:
        try:
            with Session(engine) as sess:
                query = text(
                    "SELECT ticker, div_yield, div_growth_5y, monthly_pay, "
                    "       quality_score, pass_filter, aum_billion, expense_ratio "
                    "FROM etf_quality" +
                    (" WHERE ticker = :t" if ticker else "")
                )
                rows = sess.execute(query, {"t": ticker} if ticker else {}).fetchall()
            result = {
                r.ticker: {
                    "div_yield":      r.div_yield,
                    "div_growth_5y":  r.div_growth_5y,
                    "monthly_pay":    r.monthly_pay,
                    "quality_score":  r.quality_score,
                    "pass_filter":    r.pass_filter,
                    "aum_billion":    r.aum_billion,
                    "expense_ratio":  r.expense_ratio,
                }
                for r in rows
            }
            return result.get(ticker) if ticker else result
        except Exception as e:
            log.warning("etf_quality DB 조회 실패: %s", e)

    # ── JSON fallback ─────────────────────────────────────────
    if not os.path.exists(_ETF_JSON):
        return {} if ticker is None else None
    try:
        with open(_ETF_JSON, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(ticker) if ticker else data
    except Exception:
        return {} if ticker is None else None


# ─────────────────────────────────────────────────────────────
# 자산 메타데이터 로드
# ─────────────────────────────────────────────────────────────
def get_asset_metadata(ticker: str | None = None) -> dict:
    """
    {ticker: {pay_months, div_growth_rate_pct, volatility_annual_pct, mdd, ...}}
    """
    engine = _get_engine()
    if engine:
        try:
            with Session(engine) as sess:
                query = text(
                    "SELECT ticker, asset_class, pay_months, div_growth_rate_pct, "
                    "       div_growth_5y, volatility_annual_pct, max_drawdown_pct, "
                    "       consecutive_years, monthly_pay, sector, extra_data "
                    "FROM asset_metadata" +
                    (" WHERE ticker = :t" if ticker else "")
                )
                rows = sess.execute(query, {"t": ticker} if ticker else {}).fetchall()
            result = {}
            for r in rows:
                result[r.ticker] = {
                    "asset_class":          r.asset_class,
                    "pay_months":           r.pay_months or [],
                    "div_growth_rate_pct":  r.div_growth_rate_pct,
                    "div_growth_5y":        r.div_growth_5y,
                    "volatility_annual_pct":r.volatility_annual_pct,
                    "max_drawdown_pct":     r.max_drawdown_pct,
                    "consecutive_years":    r.consecutive_years,
                    "monthly_pay":          r.monthly_pay,
                    "sector":               r.sector,
                    **(r.extra_data or {}),
                }
            return result.get(ticker) if ticker else result
        except Exception as e:
            log.warning("asset_metadata DB 조회 실패: %s", e)

    # ── JSON fallback ─────────────────────────────────────────
    if not os.path.exists(_META_JSON):
        return {} if ticker is None else {}
    try:
        with open(_META_JSON, encoding="utf-8") as f:
            raw = json.load(f)
        flat = {}
        for cat, assets in raw.items():
            if cat.startswith("_"):
                continue
            for t, data in assets.items():
                flat[t] = data
        return flat.get(ticker, {}) if ticker else flat
    except Exception:
        return {} if ticker is None else {}


# ─────────────────────────────────────────────────────────────
# KR 수익률 캐시 로드
# ─────────────────────────────────────────────────────────────
def get_kr_yield(stock_code: str | None = None) -> dict:
    engine = _get_engine()
    if engine:
        try:
            with Session(engine) as sess:
                query = text(
                    "SELECT stock_code, name, yield_pct, price, updated_at "
                    "FROM kr_yield_cache" +
                    (" WHERE stock_code = :c" if stock_code else "")
                )
                rows = sess.execute(query, {"c": stock_code} if stock_code else {}).fetchall()
            result = {
                r.stock_code: {"name": r.name, "yield_pct": r.yield_pct,
                               "price": r.price, "updated_at": str(r.updated_at)}
                for r in rows
            }
            return result.get(stock_code) if stock_code else result
        except Exception as e:
            log.warning("kr_yield_cache DB 조회 실패: %s", e)

    # ── JSON fallback ─────────────────────────────────────────
    if not os.path.exists(_KR_YIELD):
        return {} if stock_code is None else {}
    try:
        with open(_KR_YIELD, encoding="utf-8") as f:
            data = json.load(f)
        return data.get(stock_code, {}) if stock_code else data
    except Exception:
        return {} if stock_code is None else {}

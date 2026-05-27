"""
DB Models — SQLAlchemy ORM
───────────────────────────
왜 파일 캐시(JSON/CSV) 대신 DB 인가?

  파일 캐시 문제점:
    1. 동시 Write 시 파일 락(File Lock) → 데이터 오염 가능
    2. 복수 서버(수평 확장) 환경에서 캐시 동기화 불가
    3. 쿼리·인덱싱 불가 — 전체 파일 로드 후 pandas로 필터링

  DB 해결:
    1. PostgreSQL UPSERT (ON CONFLICT DO UPDATE) → 원자적 업데이트
    2. ticker 인덱스 → O(log n) 조회
    3. 배치(스케줄러)가 데이터 갱신, API 서버는 읽기만

테이블 목록:
  kr_yield_cache   ← kr_yield_cache.json
  ml_predictions   ← ml_scoring_results.csv
  etf_quality      ← etf_quality_cache.json
  asset_metadata   ← asset_metadata.json (flatten)
"""
from __future__ import annotations
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, Text, JSON,
    UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────
# 1. KR 배당수익률 캐시
#    pykrx 또는 수동 갱신 스크립트가 UPSERT
# ─────────────────────────────────────────────────────────────
class KrYieldCache(Base):
    __tablename__ = "kr_yield_cache"
    __table_args__ = (
        UniqueConstraint("stock_code", name="uq_kr_yield_code"),
        Index("ix_kr_yield_code", "stock_code"),
    )

    id          = Column(Integer, primary_key=True, autoincrement=True)
    stock_code  = Column(String(10),  nullable=False, comment="6자리 종목코드")
    name        = Column(String(100), nullable=True)
    yield_pct   = Column(Float,       nullable=True,  comment="배당수익률 (%)")
    price       = Column(Integer,     nullable=True,  comment="현재가 (원)")
    market_cap  = Column(Float,       nullable=True,  comment="시가총액 (억원)")
    updated_at  = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# 2. ML 배당 삭감 예측 결과
#    XGBoost 재학습 시 UPSERT
# ─────────────────────────────────────────────────────────────
class MLPrediction(Base):
    __tablename__ = "ml_predictions"
    __table_args__ = (
        UniqueConstraint("stock_code", name="uq_ml_code"),
        Index("ix_ml_code", "stock_code"),
        Index("ix_ml_status", "ml_status"),
    )

    id           = Column(Integer, primary_key=True, autoincrement=True)
    stock_code   = Column(String(10),  nullable=False, comment="6자리 종목코드")
    ml_status    = Column(String(20),  nullable=False, default="INTACT",
                          comment="INTACT | WEAKENING | BROKEN")
    p_weakening  = Column(Float,       nullable=True,  comment="배당 약화 확률 (0~1)")
    p_broken     = Column(Float,       nullable=True,  comment="배당 삭감 확률 (0~1)")
    ml_score     = Column(Float,       nullable=True,  comment="종합 위험 점수")
    dps_yoy_pct  = Column(Float,       nullable=True,  comment="DPS 전년비 증가율 (%)")
    model_version= Column(String(20),  nullable=True,  comment="XGBoost 모델 버전")
    predicted_at = Column(DateTime,    default=datetime.utcnow)
    updated_at   = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# 3. ETF 품질 지표
#    etf_quality_cache.json 대체
# ─────────────────────────────────────────────────────────────
class ETFQuality(Base):
    __tablename__ = "etf_quality"
    __table_args__ = (
        UniqueConstraint("ticker", name="uq_etf_ticker"),
        Index("ix_etf_ticker", "ticker"),
    )

    id               = Column(Integer, primary_key=True, autoincrement=True)
    ticker           = Column(String(20),  nullable=False)
    name             = Column(String(100), nullable=True)
    aum_billion      = Column(Float,       nullable=True, comment="AUM (억달러)")
    expense_ratio    = Column(Float,       nullable=True, comment="운용보수 (%)")
    div_yield        = Column(Float,       nullable=True, comment="배당수익률 (%)")
    div_growth_5y    = Column(Float,       nullable=True, comment="5년 배당성장률 (%)")
    monthly_pay      = Column(Boolean,     default=False, comment="월배당 여부")
    quality_score    = Column(Float,       nullable=True, comment="ETF 품질 점수 (0~100)")
    pass_filter      = Column(Boolean,     default=True,  comment="품질 필터 통과 여부")
    reject_reason    = Column(Text,        nullable=True)
    updated_at       = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)


# ─────────────────────────────────────────────────────────────
# 4. 자산 메타데이터 (배당성장률·지급월·MDD·변동성)
#    asset_metadata.json flatten 대체
# ─────────────────────────────────────────────────────────────
class AssetMetadata(Base):
    __tablename__ = "asset_metadata"
    __table_args__ = (
        UniqueConstraint("ticker", name="uq_asset_ticker"),
        Index("ix_asset_ticker", "ticker"),
        Index("ix_asset_class", "asset_class"),
    )

    id                   = Column(Integer, primary_key=True, autoincrement=True)
    ticker               = Column(String(20),  nullable=False, comment="종목코드 또는 ETF ticker")
    asset_class          = Column(String(30),  nullable=True,
                                  comment="kr_stock|us_stock|us_div_etf|kr_etf|us_reit|kr_reit|defensive")
    pay_months           = Column(JSON,        nullable=True,  comment="배당 지급월 리스트 [3,6,9,12]")
    div_growth_rate_pct  = Column(Float,       nullable=True,  comment="연평균 배당성장률 (%)")
    div_growth_5y        = Column(Float,       nullable=True,  comment="5년 배당성장률 (%)")
    volatility_annual_pct= Column(Float,       nullable=True,  comment="연간 변동성 (%)")
    max_drawdown_pct     = Column(Float,       nullable=True,  comment="최대낙폭 (%)")
    consecutive_years    = Column(Integer,     nullable=True,  comment="연속 배당성장 연수")
    monthly_pay          = Column(Boolean,     default=False)
    sector               = Column(String(50),  nullable=True)
    extra_data           = Column(JSON,        nullable=True,  comment="기타 메타데이터")
    updated_at           = Column(DateTime,    default=datetime.utcnow, onupdate=datetime.utcnow)

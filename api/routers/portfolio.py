"""
포트폴리오 추천 API — 5축 유니버스 + Total Return 기반

철학: "은행보다 높은 실질 수익률을 위험 관리와 함께 달성하는 현금흐름 설계"
  → 배당수익률만 보는 것이 아니라 Total Return (배당 + 자본차익) 으로 평가

축 구조:
  축 1: 한국 배당주       (KRX 고배당 50 랭킹 기반)
  축 2: 미국 배당 개별주  (KO, JNJ, PG, XOM, CVX, ABBV, MCD, T, VZ, IBM, MO, PFE)
  축 3: 미국 배당 ETF     (SCHD, VYM, DGRO, JEPI, JEPQ, SPYD, HDV, NOBL, SPHD, QYLD)
  축 4: 리츠              (O, VNQ, SK리츠, 롯데리츠)
  축 5: 방어형 ETF        (TLT, BND, AGG, SCHP)
"""

import os
import sys
import pandas as pd
import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import create_engine

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.universe import (
    ETF_UNIVERSE,
    get_axis_weights,
    fetch_etf_yields,
    load_approved_universe,
    ASSET_CLASS_LABEL,
)
from utils.etf_quality import filter_etf_universe
from utils.macro_regime import (
    get_macro_regime,
    apply_macro_to_weights,
    apply_macro_to_etf_scores,
)
from utils.dividend_projection import (
    simulate_portfolio,
    calc_living_coverage,
)
from utils.stress_test import run_stress_test, run_fx_stress_test
from utils.rebalancer import generate_rebalancing_plan
from utils.dividend_calendar import build_dividend_calendar
from utils.storytelling import generate_storytelling
from utils.fire_engine import calc_fire_engine, calc_fire_reverse
from utils.monte_carlo import run_monte_carlo
from utils.tax_optimizer import calc_tax_optimizer
from utils.behavioral_finance import detect_behavioral_biases
from utils.ai_advisor import ask_advisor
from utils.backtesting import run_backtest
# ── Pipeline 아키텍처 임포트 ───────────────────────────────────
# 기존 1,960줄 God-Function recommend_portfolio 를
# Pipe-and-Filter 패턴으로 분리한 파이프라인 오케스트레이터.
from api.pipeline import RecommendationPipeline
from api.pipeline.context import PortfolioRequest as PipelinePortfolioRequest


router = APIRouter()
engine = create_engine("postgresql://localhost/ai_analyst")
RANKING_CSV      = os.path.join(BASE_DIR, "data", "ranking.csv")
ML_SCORES_CSV    = os.path.join(BASE_DIR, "data", "ml_scoring_results.csv")
ASSET_META_JSON  = os.path.join(BASE_DIR, "data", "asset_metadata.json")
US_SCORES_CSV    = os.path.join(BASE_DIR, "data", "us_stock_scores.csv")
KR_YIELD_CACHE   = os.path.join(BASE_DIR, "data", "kr_yield_cache.json")
ETF_QUALITY_CACHE= os.path.join(BASE_DIR, "data", "etf_quality_cache.json")

# 현재 기준금리 (은행 예금 대비 비교 기준)
BANK_RATE_PCT = 3.5


# ── 데이터 신선도 추적 ─────────────────────────────────────────
def _get_data_freshness() -> dict:
    """
    각 데이터 파일의 최종 갱신 시각을 반환.
    프론트엔드에서 '데이터 기준일' 표시에 활용.
    """
    import json as _json
    from datetime import datetime as _dt

    def _file_mtime(path: str) -> str:
        try:
            return _dt.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d")
        except Exception:
            return "unknown"

    # kr_yield_cache에서 pykrx 갱신 날짜 조회
    kr_yield_date = "static"
    try:
        with open(KR_YIELD_CACHE, encoding="utf-8") as f:
            kr_cache = _json.load(f)
        kr_yield_date = kr_cache.get("_updated", "static")
    except Exception:
        pass

    return {
        "kr_stock_ranking":   _file_mtime(RANKING_CSV),
        "kr_yield_live":      kr_yield_date,
        "ml_scoring":         _file_mtime(ML_SCORES_CSV),
        "us_stock_scores":    _file_mtime(US_SCORES_CSV),
        "etf_quality":        _file_mtime(ETF_QUALITY_CACHE),
        "note": (
            "kr_yield_live=static이면 pykrx 미갱신 상태."
            " `python scripts/rebuild_ranking.py` 실행 시 실시간 데이터로 갱신."
        ),
    }


# ── 자산 메타데이터 로드 (배당 성장률·지급월·변동성·MDD) ───────
def _load_asset_metadata() -> dict:
    """
    asset_metadata.json → 카테고리별 평탄화 딕셔너리.
    {ticker: {pay_months, div_growth_rate_pct, volatility_annual_pct, ...}}

    ETF(ticker 기준)와 KR주식(stock_code 기준) 모두 포함.
    _default 키는 한국 주식 기본값으로 사용.
    """
    if not os.path.exists(ASSET_META_JSON):
        return {}
    try:
        import json
        with open(ASSET_META_JSON, encoding="utf-8") as f:
            raw = json.load(f)

        flat = {}
        for category, assets in raw.items():
            if category.startswith("_"):
                continue
            for ticker, data in assets.items():
                flat[ticker] = data
        return flat
    except Exception:
        return {}

ASSET_META: dict = _load_asset_metadata()
if ASSET_META:
    print(f"[init] 자산 메타데이터: {len(ASSET_META)}개 자산 로드 완료")


# ── ML 리스크 점수 로드 (배당 삭감 감지 엔진) ──────────────────
def _load_ml_scores() -> dict:
    """
    ml_scoring_results.csv → {stock_code: {ml_status, P_WEAKENING, P_BROKEN, ml_score}}

    이 데이터는 XGBoost 3-class 모델로 채점한 결과.
    - INTACT:    배당 지속 안정
    - WEAKENING: 내년 배당 삭감 가능성 감지 (P_WEAKENING ≥ 0.25)
    - BROKEN:    이미 배당 삭감 발생 또는 구조적 위험 (P_BROKEN ≥ 0.40)
    """
    if not os.path.exists(ML_SCORES_CSV):
        return {}
    try:
        df = pd.read_csv(ML_SCORES_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        result = {}
        for _, row in df.iterrows():
            result[row["stock_code"]] = {
                "ml_status":   row.get("ml_status", "INTACT"),
                "P_WEAKENING": round(float(row.get("P_WEAKENING", 0)), 3),
                "P_BROKEN":    round(float(row.get("P_BROKEN", 0)), 3),
                "ml_score":    round(float(row.get("ml_score", 0)), 3),
                "dps_yoy_pct": row.get("dps_yoy_pct"),
            }
        return result
    except Exception:
        return {}

ML_SCORES: dict = _load_ml_scores()


# ── 입력 스키마 ────────────────────────────────────────────────

class PortfolioRequest(BaseModel):
    age:               int
    annual_income:     int    # 만원 — ISA 유형 판단
    monthly_target:    int    # 목표 월 배당금 (만원)
    investable_amount: int    # 투자 가능 금액 (만원)
    risk_tolerance:    str = ""         # conservative | moderate | aggressive (빈값→자동결정)
    archetype:         str = ""         # 성장형 | 혼합형 | 안정형 (빈값→자동결정)
    monthly_savings:   float = 0.0      # 월 적립액 (만원) — FIRE 계산용
    savings_growth:    float = 0.0      # 적립 연 증가율 (%) — 소득 상승 반영
    target_fire_age:   int   = 50       # 목표 FIRE 나이
    savings_stages:    list  = []       # 생애주기 적립 스테이지
    # 예: [{"from_age":25,"to_age":27,"monthly_savings":20},
    #       {"from_age":27,"to_age":30,"monthly_savings":100}]


# ─────────────────────────────────────────────────────────────
# 포트폴리오 아키타입 시스템
# ─────────────────────────────────────────────────────────────
# 각 아키타입은 3가지를 결정한다:
#   1. etf_categories_priority: 어떤 카테고리 ETF를 우선 편입할지
#   2. axis_overrides: 5축 비중을 어떻게 조정할지 (아키타입 전용 override)
#   3. description: 아키타입 설명 (API 반환값)
#
# 왜 아키타입이 필요한가?
#   나이·성향만으로는 "나는 매달 현금흐름이 필요한 은퇴자"와
#   "나는 30년 후를 보는 복리 성장 투자자"를 구분할 수 없다.
#   아키타입은 투자 목적에 따라 ETF 구성을 완전히 다르게 만든다.

ARCHETYPE_CONFIG: dict[str, dict] = {
    "성장형": {
        "etf_categories_priority": ["dividend_growth"],   # SCHD·DGRO·VIG·NOBL 계열
        "excluded_categories":     ["monthly_income"],     # 커버드콜 배제 (성장 캡 걸림)
        "defensive_categories":    [],    # 성장형은 방어 채권 없이 100% 주식+성장 ETF
        "axis_overrides": {
            "us_etf":      +0.05,   # ETF 성장 비중 ↑
            "kr_stock":    +0.03,
            "defensive":   -0.05,
            "reit":        -0.03,
        },
        "description": "장기 배당성장 복리 전략. 배당 자체보다 배당성장률을 우선. 10~20년 후 배당 극대화 설계.",
        "label": "📈 성장형",
    },
    "월배당형": {
        "etf_categories_priority": ["monthly_income", "high_yield"],  # JEPI·JEPQ·SPYI·SPHD
        "excluded_categories":     [],
        "defensive_categories":    ["cash_equivalent", "agg_bond"],   # SGOV·BND
        "axis_overrides": {
            "us_etf":      +0.07,   # ETF 비중 최대화 (월배당 ETF 중심)
            "reit":        +0.03,   # 리츠도 월배당 많음
            "kr_stock":    -0.05,
            "defensive":   -0.05,
        },
        "description": "매달 안정적인 현금흐름 최우선. 커버드콜 ETF + 고배당 리츠 조합. 월급처럼 받는 배당 설계.",
        "label": "💵 월배당형",
    },
    "안정형": {
        "etf_categories_priority": ["dividend_growth", "high_yield"],
        "excluded_categories":     ["monthly_income"],  # 커버드콜 고위험 제외
        "defensive_categories":    ["agg_bond", "tips", "cash_equivalent"],  # 방어 풀 활용
        "axis_overrides": {
            "defensive":   +0.08,   # 방어 비중 최대화
            "kr_stock":    +0.03,
            "us_stock":    -0.05,
            "us_etf":      -0.06,
        },
        "description": "원금 보존 + 안정적 배당. MDD 최소화. 하락장에서도 버티는 포트폴리오. 변동성이 낮은 자산만 편입.",
        "label": "🛡️ 안정형",
    },
    "은퇴형": {
        "etf_categories_priority": ["monthly_income", "high_yield", "dividend_growth"],
        "excluded_categories":     [],
        "defensive_categories":    ["cash_equivalent", "agg_bond"],  # SGOV + BND
        "axis_overrides": {
            "reit":        +0.05,   # 리츠 (월세 대체)
            "us_etf":      +0.05,   # 월배당 ETF
            "defensive":   +0.03,
            "us_stock":    -0.07,   # 개별주 리스크 축소
            "kr_stock":    -0.06,
        },
        "description": "은퇴 후 생활비 조달. 월배당 현금흐름 + 리츠(월세 대체) + 방어층 삼각 구조. 원금 소진 없이 배당만으로 생활.",
        "label": "🏖️ 은퇴형",
    },
    "혼합형": {
        "etf_categories_priority": ["dividend_growth", "high_yield", "monthly_income"],
        "excluded_categories":     [],
        "defensive_categories":    ["agg_bond", "long_bond", "tips"],
        "axis_overrides": {},   # 기본 비중 유지
        "description": "성장 + 현금흐름 균형. 특정 목적 없이 전방위 최적화된 배당 포트폴리오.",
        "label": "⚖️ 혼합형",
    },
    "배당형": {
        # 안정적 고배당 + 커버드콜 배제. 60세 보수형 투자자 타겟.
        "etf_categories_priority": ["high_yield", "dividend_growth"],
        "excluded_categories":     ["monthly_income"],  # 커버드콜 배제 (자본 침식 위험)
        "defensive_categories":    ["agg_bond", "tips", "cash_equivalent"],
        "axis_overrides": {
            "defensive":   +0.05,
            "reit":        +0.03,
            "us_etf":      +0.02,
            "kr_stock":    +0.02,
            "us_stock":    -0.07,
        },
        "description": "안정적 배당 현금흐름 우선. 커버드콜 없이 순수 배당수익. 고배당 ETF + 우량 배당주로 구성.",
        "label": "💰 배당형",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# ARCHETYPE_RATIONALE
# ─────────────────────────────────────────────────────────────────────────────
# 각 아키타입의 설계 근거를 명시한다.
#
# 구조:  [투자 목표 정의]
#          ↓
#        [외부 금융기관 참고]  (Morningstar / Vanguard / CFA Institute)
#          ↓
#        [우리 시스템의 설계 방향]
#          ↓
#        [axis_overrides 수치]  ← 외부 기관이 이 숫자를 직접 제시한 것이 아님.
#                                  외부 원칙을 코드 상에서 정규화한 조정값임.
#
# 교수님 피드백 대응: "기준이 명확해야 한다"
#   → 아키타입마다 '왜 이 축을 올리고 내렸는가'를 투자 목적 + 외부 원칙으로 설명
#   → 이후 실제 데이터 기반 calibration 예정
# ─────────────────────────────────────────────────────────────────────────────
ARCHETYPE_RATIONALE: dict[str, dict] = {
    # ─────────────────────────────────────────────────────────────────────────
    # 각 아키타입 rationale 구조:
    #   external_benchmark   - 인용 가능한 외부 기관의 실제 기준점/데이터
    #   design_interpretation - 그 원칙을 우리 시스템에 어떻게 해석·적용했는가
    #   internal_value_note   - axis_overrides 숫자가 외부 기관 수치가 아님을 명시
    #   axis_overrides_rationale - 각 축 방향 설명
    #   pending_calibration   - 향후 데이터 기반 검증 계획
    # ─────────────────────────────────────────────────────────────────────────

    "성장형": {
        "investment_goal": (
            "배당 자체보다 배당성장률을 우선시하는 장기 복리 전략. "
            "10~20년 뒤 배당 규모를 극대화하는 것이 핵심 목적."
        ),
        "external_benchmark": {
            "source": "Morningstar — Dividend Growth Category 기준",
            "data": (
                "Morningstar는 배당성장 전략에서 현재 배당수익률보다 "
                "배당 지속성·성장성·재무건전성을 더 중요한 평가 기준으로 다룬다. "
                "단순 고배당보다 장기 성장 가능성이 높은 종목을 선호하는 방향."
            ),
        },
        "design_interpretation": (
            "이 원칙을 참고하여 성장형 아키타입은 "
            "배당성장 ETF(us_etf) 비중을 높이고 방어자산(defensive)·리츠(reit) 비중을 낮췄다. "
            "'지금 당장 높은 수익률'보다 '10년 뒤 성장한 배당'을 우선하는 설계."
        ),
        "internal_value_note": (
            "axis_overrides 수치(us_etf +0.05 등)는 Morningstar가 제시한 숫자가 아니라 "
            "5축 가중치 체계 내에서 정규화한 시스템 내부 조정값이다."
        ),
        "axis_overrides_rationale": {
            "us_etf":    "+0.05 — 배당성장 ETF 비중 상향. 성장 방향 핵심축.",
            "kr_stock":  "+0.03 — 국내 성장 배당주 소량 추가. 환율 분산 겸 국내 접근.",
            "defensive": "-0.05 — 성장형은 채권·방어자산 없이 주식+성장ETF 집중.",
            "reit":      "-0.03 — 리츠는 성장보다 현금흐름 중심 → 성장형에서 축소.",
        },
        "pending_calibration": "axis_overrides 수치는 향후 백테스트 수익률 기반으로 재검증 예정.",
    },

    "월배당형": {
        "investment_goal": (
            "매월 안정적인 현금흐름 최우선. "
            "'월급처럼 받는 배당'을 목표로 월분배 ETF + 고배당 리츠 조합."
        ),
        "external_benchmark": {
            "source": "CFA Institute — Basics of Portfolio Planning and Construction (2026)",
            "data": (
                "CFA 포트폴리오 관리 원칙은 투자자의 목표(regular income, capital growth 등)와 "
                "제약조건을 먼저 파악한 뒤 그에 맞는 전략적 자산배분을 설계하도록 명시한다. "
                "정기적인 현금흐름 필요가 명확한 투자자에게는 이를 포트폴리오 목적으로 반영."
            ),
        },
        "design_interpretation": (
            "월 현금흐름을 목적으로 하는 투자자를 위해 "
            "월분배 ETF(us_etf)·리츠(reit) 비중을 높이고, "
            "방어자산보다 인컴 자산을 우선 배치했다. "
            "JEPI/JEPQ/SPHD 등 활용은 시스템의 구체적 상품 선택."
        ),
        "internal_value_note": (
            "axis_overrides 수치(us_etf +0.07 등)는 CFA가 제시한 숫자가 아니라 "
            "인컴 목적 달성을 위한 시스템 내부 정규화값이다."
        ),
        "axis_overrides_rationale": {
            "us_etf":    "+0.07 — 월배당 ETF 중심 구성. 가장 높은 ETF 비중 상향.",
            "reit":      "+0.03 — 리츠 월배당 활용. 부동산 인컴 소스 추가.",
            "kr_stock":  "-0.05 — 개별 국내 배당주는 월배당 빈도 낮아 비중 축소.",
            "defensive": "-0.05 — 월배당 목적상 방어자산보다 인컴 자산 우선.",
        },
        "pending_calibration": "커버드콜 ETF 자본 침식 리스크 측정 후 threshold 재검토 예정.",
    },

    "안정형": {
        "investment_goal": (
            "원금 보존 + 안정적 배당. MDD 최소화. "
            "하락장에서도 포트폴리오를 유지하는 것이 최우선."
        ),
        "external_benchmark": {
            "source": "Vanguard — LifeStrategy Conservative Growth Fund / 자산배분 가이드",
            "data": (
                "Vanguard는 위험 수준에 따른 대표 자산배분 기준점을 공개한다: "
                "Aggressive 80% 주식 / 20% 채권, "
                "Moderate 60% 주식 / 40% 채권, "
                "Conservative 40% 주식 / 60% 채권(LifeStrategy Conservative Growth Fund). "
                "위험수용도가 낮을수록 방어자산(채권·TIPS·현금성) 비중을 높인다."
            ),
        },
        "design_interpretation": (
            "Vanguard Conservative Allocation(40/60) 원칙을 참고해 "
            "안정형의 defensive 자산 비중을 상향하고 "
            "변동성이 큰 us_stock·us_etf 비중을 낮췄다. "
            "5축 시스템 특성상 채권 비중을 직접 사용하지 않고 "
            "defensive 축(채권·TIPS·현금성)으로 변환하여 적용."
        ),
        "internal_value_note": (
            "defensive +0.08은 Vanguard가 제시한 숫자가 아니라 "
            "40/60 방향성을 5축 체계 내에서 정규화한 시스템 내부 조정값이다."
        ),
        "axis_overrides_rationale": {
            "defensive":   "+0.08 — 방어자산 비중 최대화. 안정형 설계 핵심 조정.",
            "kr_stock":    "+0.03 — 국내 우량 배당주(저변동성) 소량 추가.",
            "us_stock":    "-0.05 — 개별 미국주 변동성 제어 위해 비중 축소.",
            "us_etf":      "-0.06 — 성장 중심 ETF 비중 축소. 방어 ETF만 허용.",
        },
        "pending_calibration": (
            "defensive +0.08은 내부 정규화값. "
            "실제 MDD 데이터 및 Vanguard 40/60 성과 비교로 재검증 예정."
        ),
    },

    "은퇴형": {
        "investment_goal": (
            "은퇴 후 생활비 조달. 방어자산 + 월배당 + 리츠 삼각 구조. "
            "원금 소진 없이 배당만으로 생활비 충당."
        ),
        "external_benchmark": {
            "source": "Vanguard — Target Date Fund Glide Path",
            "data": (
                "Vanguard TDF는 나이가 올라갈수록 주식 비중을 줄이고 채권·TIPS 비중을 늘리는 "
                "glide path 원칙을 적용한다. "
                "은퇴 시점(65세 기준) 약 30% 주식 / 70% 채권·TIPS 구조로 수렴. "
                "은퇴 접근 시 자본성장보다 안정적 인컴·원금 보호를 우선."
            ),
        },
        "design_interpretation": (
            "Vanguard glide path의 핵심 원칙(은퇴 접근 → 방어자산 비중 확대·개별주 리스크 축소)을 참고했다. "
            "현금흐름 중심 시스템 특성상 채권 직접 편입 대신 "
            "리츠(월세 대체 인컴) + 월배당ETF + 방어자산 삼각 구조로 적용했다. "
            "이 삼각 구조는 시스템 자체의 설계 — Vanguard가 이 구조를 직접 제시하지는 않는다."
        ),
        "internal_value_note": (
            "axis_overrides 수치(reit +0.05 등)는 Vanguard glide path 수치가 아니라 "
            "해당 원칙을 5축 체계로 변환한 시스템 내부 조정값이다."
        ),
        "axis_overrides_rationale": {
            "reit":      "+0.05 — 리츠: 월세 대체 인컴. 은퇴형 핵심 현금흐름 축.",
            "us_etf":    "+0.05 — 월배당 ETF로 정기 현금흐름 확보.",
            "defensive": "+0.03 — 방어층 추가로 하락장 보호.",
            "us_stock":  "-0.07 — 개별 미국주 리스크 대폭 축소.",
            "kr_stock":  "-0.06 — 개별 국내주도 축소. 리츠/ETF로 대체.",
        },
        "pending_calibration": "Vanguard TDF glide path 성과 비교 및 SWR(안전 인출률) 기반 검증 예정.",
    },

    "혼합형": {
        "investment_goal": (
            "성장 + 현금흐름 균형. 특정 편향 없이 전방위 최적화된 배당 포트폴리오."
        ),
        "external_benchmark": {
            "source": "CFA Institute — Basics of Portfolio Planning and Construction (2026)",
            "data": (
                "CFA 포트폴리오 관리 원칙에서 전략적 자산배분(SAA)은 "
                "투자자의 목적과 제약조건이 명확하지 않은 경우 "
                "편향 없는 기본 자산배분 비중(baseline)을 출발점으로 삼는다."
            ),
        },
        "design_interpretation": (
            "혼합형은 특정 목적 편향 없이 기본 5축 비중을 유지한다. "
            "axis_overrides = {} (모든 축 조정 없음)으로 설정해 "
            "다른 아키타입의 베이스라인 역할을 하도록 설계."
        ),
        "internal_value_note": (
            "axis_overrides 없음 = 의도적 설계 선택. "
            "기본 비중(get_axis_weights)이 시스템의 중립 기준점."
        ),
        "axis_overrides_rationale": {
            "(없음)": "혼합형은 의도적으로 override를 적용하지 않음. 기본 비중이 균형 기준점.",
        },
        "pending_calibration": "베이스라인 역할이므로 수치 변경 없음. 기본 비중 자체의 최적화는 MPT 기반 재검토 예정.",
    },

    "배당형": {
        "investment_goal": (
            "안정적 배당 현금흐름 우선. 커버드콜(자본 침식 위험) 배제. "
            "순수 배당수익: 고배당 ETF + 우량 배당주 중심."
        ),
        "external_benchmark": {
            "source": "Morningstar — Dividend Sustainability 분석 방법론",
            "data": (
                "Morningstar는 배당 지속가능성 평가에서 "
                "실질 영업이익·FCF(잉여현금흐름) 기반의 배당을 "
                "커버드콜처럼 미래 수익을 선매도하는 구조보다 "
                "더 안정적인 장기 인컴 소스로 평가한다."
            ),
        },
        "design_interpretation": (
            "이 원칙을 참고해 배당형은 커버드콜 ETF(monthly_income 카테고리)를 전면 배제하고, "
            "FCF 기반 실질 배당종목·고배당 ETF 중심으로 구성한다. "
            "방어자산 비중도 소폭 높여 배당 안정성을 보호."
        ),
        "internal_value_note": (
            "axis_overrides 수치(defensive +0.05 등)는 Morningstar 수치가 아니라 "
            "배당 지속가능성 원칙을 5축 체계로 정규화한 시스템 내부 조정값이다."
        ),
        "axis_overrides_rationale": {
            "defensive": "+0.05 — 방어자산으로 배당 안정성 보호.",
            "reit":      "+0.03 — 고배당 리츠 추가 (커버드콜 아닌 실질 배당).",
            "us_etf":    "+0.02 — 고배당·배당성장 ETF 소량 추가.",
            "kr_stock":  "+0.02 — 국내 우량 배당주 편입.",
            "us_stock":  "-0.07 — 개별 미국주 비중 축소. 배당 안정성 불확실 종목 제어.",
        },
        "pending_calibration": "커버드콜 배제 효과 백테스트 검증 예정 (MDD 및 수익률 비교).",
    },
}
# ─────────────────────────────────────────────────────────────────────────────
# SCORING_RATIONALE
# ─────────────────────────────────────────────────────────────────────────────
# growth_score, overall_score, 건강도 threshold의 설계 근거를 명시.
# 이 threshold들은 외부 기관이 직접 제시한 숫자가 아니라
# 시스템 내부 설계값이며, 향후 데이터 분포 및 백테스트로 검증 예정.
# ─────────────────────────────────────────────────────────────────────────────
SCORING_RATIONALE: dict[str, dict] = {
    # ─────────────────────────────────────────────────────────────────────────
    # 3층 구조:
    #   why_this_metric   - 이 지표를 평가축으로 삼는 외부/학술 근거
    #   internal_design   - 우리 시스템에서 어떻게 설계했는가
    #   internal_value_note - threshold 수치는 외부 기관 공식 기준이 아님을 명시
    # ─────────────────────────────────────────────────────────────────────────

    "growth_score": {
        "description": "포트폴리오 가중 배당성장률(portfolio_div_cagr) 기반 20점 만점 점수",
        "why_this_metric": {
            "source": "Morningstar — Dividend Growth Category 분석 방법론",
            "rationale": (
                "Morningstar 배당성장 분석에서 배당성장률은 단순 수익률보다 "
                "배당의 지속가능성과 기업 재무건전성을 반영하는 핵심 평가 변수다. "
                "따라서 포트폴리오 건강도에서 growth_score를 독립 평가축으로 채택."
            ),
        },
        "internal_design": (
            "포트폴리오 가중 배당성장률(CAGR)을 0~20점 구간으로 변환. "
            "상위 기준 8%는 SCHD의 실제 10년 배당성장률(약 10~12%) 수준을 참고해 "
            "'최우수' 기준점으로 설정한 내부 scoring 구간. "
            "하위 구간 6/4/2/%는 등간격에 가깝게 설계."
        ),
        "internal_value_note": (
            "8%/6%/4%/2% threshold는 Morningstar가 공식적으로 제시한 기준이 아니라 "
            "시스템 내부 scoring 설계값이다. "
            "외부 근거는 '배당성장률을 평가 변수로 사용하는 이유'를 뒷받침하며, "
            "구체적 구간은 실제 ETF CAGR 분포를 참고한 내부 설계."
        ),
        "thresholds": {
            ">=8%": "20점 — 최우수 (SCHD 실제 10Y CAGR 참고 기준)",
            ">=6%": "16점 — 우수",
            ">=4%": "12점 — 양호",
            ">=2%": "8점  — 보통",
            "<2%":  "4점  — 미흡",
        },
        "pending_calibration": (
            "실제 포트폴리오 배당성장률 분포 데이터 수집 후 "
            "구간 경계 및 점수 배분 재조정 예정."
        ),
    },

    "overall_score_cutoff": {
        "description": "종목 선별 기준: overall_score >= 50만 포트폴리오 편입 허용",
        "why_this_metric": {
            "source": "CFA Institute — 다차원 종목 평가 접근법 / Morningstar 종목 스크리닝",
            "rationale": (
                "단일 지표(예: 배당수익률)만으로 종목을 선별하면 yield trap 등 함정에 빠질 수 있다. "
                "CFA 포트폴리오 관리 원칙 및 Morningstar 스크리닝 방법론은 "
                "수익성·성장성·재무건전성 등 다차원 지표를 종합한 점수로 후보를 필터링하는 방식을 지지한다."
            ),
        },
        "internal_design": (
            "overall_score = yield + stability + financial + growth 4축 가중 합산 (0~100점). "
            "50점 미만 = 4개 평가축 평균이 절반 이하인 종목 → 최소 품질 기준 미달로 판단해 제외. "
            "커트라인 50은 '절반 이상의 평가 기준을 통과'라는 직관적 설계 기준."
        ),
        "internal_value_note": (
            "cutoff 50은 외부 기관의 공식 기준이 아니라 시스템 내부 설계값이다. "
            "이 숫자 자체가 최적이라고 주장하지 않으며, "
            "향후 실제 배당 컷 이력 데이터와 백테스트로 최적 cutoff를 검증할 예정."
        ),
        "pending_calibration": (
            "실제 배당 삭감 종목의 overall_score 분포 분석 후 "
            "precision/recall 기반 최적 cutoff 도출 예정."
        ),
    },

    "health_grade_threshold": {
        "description": "포트폴리오 건강도 5단계 등급 (100점 만점, 5축 합산)",
        "why_this_metric": {
            "source": (
                "CFA Institute — Portfolio Planning and Construction / "
                "Vanguard 포트폴리오 평가 프레임워크"
            ),
            "rationale": (
                "CFA 포트폴리오 관리 원칙은 포트폴리오를 단일 수익률이 아닌 "
                "안정성·성장성·현금흐름·세금효율·분산도 등 복수의 차원으로 평가한다. "
                "Vanguard도 포트폴리오 품질 평가 시 분산도·비용·세금효율 등을 종합적으로 고려한다. "
                "이를 참고해 5개 독립 평가축(stability/growth/cashflow/tax_eff/diversification)을 설계."
            ),
        },
        "internal_design": (
            "5축 구성: stability 25점 + growth 20점 + cashflow 20점 + "
            "tax_efficiency 20점 + diversification 15점 = 100점 만점. "
            "5등급(매우건강/건강/보통/주의/긴급)은 직관적 전달력을 위한 내부 설계. "
            "85/72/58/44 threshold는 각 축 평균 점수 분포를 근거로 "
            "대략 80%/70%/55%/40% 달성 수준에 맞춰 설정한 내부값."
        ),
        "internal_value_note": (
            "85/72/58/44 threshold는 외부 금융기관의 공식 등급 기준이 아니라 "
            "시스템 내부 설계값이다. "
            "5개 평가축을 사용하는 '이유'는 CFA/Vanguard 원칙으로 뒷받침되지만, "
            "구체적 경계값은 향후 데이터 분포 기반 calibration 대상."
        ),
        "thresholds": {
            ">=85": "🟢 매우 건강 — 5축 평균 약 80% 이상 달성",
            ">=72": "🟡 건강     — 5축 평균 약 70% 이상 달성",
            ">=58": "🟠 보통     — 5축 평균 약 55% 이상 달성",
            ">=44": "🔴 주의 필요 — 5축 평균 약 40% 이상 달성",
            "<44":  "🚨 개선 긴급 — 5축 평균 40% 미만",
        },
        "pending_calibration": (
            "실제 사용자 포트폴리오 점수 분포 수집 후 "
            "상위 20%/50%/70%/90% 백분위 기반 threshold 전환 예정. "
            "각 축 가중치(25/20/20/20/15)도 백테스트 성과 기반 재검토 예정."
        ),
    },
}


def apply_archetype_weights(axis_w: dict, archetype: str) -> dict:
    """
    아키타입별 5축 비중 조정 적용.

    get_axis_weights()로 나온 기본 비중에
    아키타입 고유 override를 더하거나 뺀 후 재정규화.
    음수 방지 후 합계가 1.0이 되도록 정규화.
    """
    config = ARCHETYPE_CONFIG.get(archetype, ARCHETYPE_CONFIG["혼합형"])
    overrides = config.get("axis_overrides", {})

    adjusted = dict(axis_w)
    for k, delta in overrides.items():
        adjusted[k] = max(0.0, adjusted.get(k, 0.0) + delta)

    # 정규화
    total = sum(adjusted.values()) or 1.0
    return {k: round(v / total, 3) for k, v in adjusted.items()}


# ─────────────────────────────────────────────────────────────
# 세금 엔진
# ─────────────────────────────────────────────────────────────
# 왜 세금 엔진이 중요한가?
#   배당수익률 6%처럼 보여도 미국 주식은 15% 원천징수 → 실수령 5.1%
#   ISA 편입 시 9.9% 분리과세 → 실수령이 달라짐
#   세후 수익률 없이는 진짜 포트폴리오 설계가 불가능하다

def calc_after_tax_yield(
    gross_yield:  float,   # 세전 배당수익률 (%)
    asset_class:  str,     # us_stock | us_div_etf | us_reit | kr_stock | kr_etf | kr_reit | defensive
    account:      str,     # ISA/연금 | 일반 | 일반/연금
    annual_income: int,    # 연소득 (만원) — ISA 서민형 여부 판단
) -> dict:
    """
    자산 유형 + 계좌 유형에 따라 세후 배당수익률 계산.

    한국-미국 조세조약: 미국 주식/ETF 배당 → 15% 원천징수 (미국에서 선제 공제)
    국내 배당소득세: 15.4% (소득세 14% + 지방소득세 1.4%)

    ISA 계좌:
      - 비과세 한도 이내: 실효세율 0%
      - 초과분: 9.9% 분리과세 (금융소득종합과세 면제)
      - 서민·청년형: 비과세 한도 400만원 / 일반형: 200만원

    연금저축/IRP:
      - 운용 중 과세이연 (세금 없음)
      - 수령 시 3.3~5.5% 연금소득세 (65세 이후 3.3%)
    """
    is_isa     = "ISA" in account
    # 연금 여부: "ISA/연금" 같은 문자열에서 연금 포함이라도
    # 미국 직접매매 종목은 한국 연금저축/IRP에서 불가. 국내 종목만 가능.
    is_pension = "연금" in account and asset_class not in ("us_stock", "us_div_etf", "us_reit", "defensive")

    # ── 미국 자산 (us_stock / us_div_etf / us_reit) ──────────
    # 한국 투자자는 미국 배당을 받을 때 미국에서 15% 원천징수 (한미 조세조약).
    # 국내 추가 과세 없음. ISA/연금에 미국 직접 ticker 편입 불가.
    if asset_class in ("us_stock", "us_div_etf", "us_reit"):
        tax_rate_eff = 0.15
        net_yield    = gross_yield * (1 - tax_rate_eff)
        note = "미국 원천징수 15% (한미 조세조약). 국내 추가 세금 없음. ISA·연금 계좌 직접 편입 불가."

    # ── 한국 주식/리츠 ────────────────────────────────────────
    elif asset_class in ("kr_stock", "kr_reit"):
        if is_isa:
            tax_rate_eff = 0.099
            net_yield    = gross_yield * (1 - tax_rate_eff)
            note = "ISA 9.9% 분리과세 (일반 15.4% 대비 5.5%p 절세)."
        elif is_pension:
            net_yield    = gross_yield
            tax_rate_eff = 0.0
            note = "연금저축/IRP 과세이연. 수령 시 연금소득세 3.3~5.5% 적용."
        else:
            tax_rate_eff = 0.154
            net_yield    = gross_yield * (1 - tax_rate_eff)
            note = "국내 배당소득세 15.4%."

    # ── 한국 상장 ETF (kr_etf) ────────────────────────────────
    # 국내 상장 해외 ETF는 ISA/연금저축 편입 가능 — 절세 핵심 경로
    elif asset_class == "kr_etf":
        if is_isa:
            tax_rate_eff = 0.099
            net_yield    = gross_yield * (1 - tax_rate_eff)
            note = "ISA 9.9% 분리과세. 국내 상장으로 해외ETF 절세 최적 경로."
        elif is_pension:
            net_yield    = gross_yield
            tax_rate_eff = 0.0
            note = "연금저축/IRP 과세이연. 수령 시 연금소득세 적용."
        else:
            tax_rate_eff = 0.154
            net_yield    = gross_yield * (1 - tax_rate_eff)
            note = "국내 상장 ETF 배당소득세 15.4%. ISA 편입 시 절세 가능."

    # ── 방어형 채권 ETF (미국 상장) ──────────────────────────
    # TLT, BND, AGG, SCHP, SGOV = 미국 상장 → 이자소득 원천징수 15%
    else:  # defensive
        tax_rate_eff = 0.15
        net_yield    = gross_yield * (1 - tax_rate_eff)
        note = "미국 채권 이자 원천징수 15% (한미 조세조약)."

    return {
        "gross_yield":    round(gross_yield, 2),
        "net_yield":      round(net_yield, 2),
        "tax_rate_eff":   round(tax_rate_eff * 100, 1),   # % 단위
        "tax_saved_vs_general": round(
            gross_yield * 0.154 - gross_yield * tax_rate_eff, 2
        ) if is_isa else 0.0,
        "note": note,
    }


# ─────────────────────────────────────────────────────────────
# 추천 이유 Generator
# ─────────────────────────────────────────────────────────────
# "왜 이 자산을 추천했나"를 사람이 이해할 수 있게 설명.
# 점수 숫자만 던지지 않고, 어떤 기준에서 어떤 특성이 매치됐는지 설명.

def generate_recommendation_reason(
    item:       dict,   # 자산 딕셔너리
    archetype:  str,    # 포트폴리오 아키타입
    axis_w:     dict,   # 최종 5축 비중
    req_age:    int,
    req_risk:   str,
) -> str:
    """
    각 자산에 대해 "왜 이 포트폴리오에 편입됐는지"를 설명하는 이유 문장 생성.

    생성 로직:
    1. 개인화 적합도 (fit_score / 목표수익률 달성 여부)
    2. 아키타입 매칭 이유 (왜 이 아키타입에 적합한가)
    3. 핵심 지표 강점 (yield, grade, 연속배당연수 등)
    4. 세금 최적화 포인트 (ISA/일반 계좌)
    5. 리스크 주의사항 (있는 경우만)
    """
    parts = []
    cls   = item.get("asset_class", "")
    cat   = item.get("etf_category", "")
    at    = item.get("asset_type", "")
    dy    = item.get("expected_yield", item.get("dividend_yield", 0))
    cap   = item.get("capital_gain_rate", 0)
    score = item.get("overall_score", 0)
    grade = item.get("grade", "")
    ml    = item.get("ml_status", "INTACT")
    cuts  = item.get("dps_cuts_3y", 0)
    cons  = item.get("consecutive_years", 0)
    monthly = item.get("monthly_pay", False)
    mdd   = item.get("max_drawdown_pct", item.get("mdd", None))
    account = item.get("account", "")
    trap  = item.get("trap_level", "SAFE")
    div_grow = item.get("div_growth_5y", item.get("div_growth_rate_pct", 0))

    # ── 개인화 적합도 (PersonalizedRankingFilter 결과) ──────────
    fit_score    = item.get("fit_score")
    target_yield = item.get("target_yield")
    yield_fit    = item.get("yield_fit")
    risk_fit     = item.get("risk_fit")
    age_fit      = item.get("age_fit")
    cold_start   = item.get("cold_start", False)

    if cold_start:
        parts.append("ML 분석 데이터 부족 — 섹터 기준 rule-based 선별 적용")
    elif fit_score is not None:
        fit_pct = int(fit_score)       # fit_score는 0-100 스케일
        fit_label = "최적" if fit_score >= 75 else ("적합" if fit_score >= 50 else "보통")
        # yield 매칭
        if target_yield and dy > 0:
            yield_gap = dy - target_yield
            yield_str = (
                f"목표수익률 {target_yield:.1f}% 대비 {yield_gap:+.1f}%p"
                if abs(yield_gap) > 0.3 else f"목표수익률 {target_yield:.1f}% 정확히 부합"
            )
        else:
            yield_str = ""
        # 나이 적합도
        age_label = ""
        if age_fit is not None:
            if req_age < 35 and age_fit >= 70:
                age_label = "성장기 투자자 최적화"
            elif req_age >= 55 and age_fit >= 70:
                age_label = "은퇴 준비 투자자 최적화"
            elif age_fit < 40:
                age_label = "나이 프로파일 부분 불일치"
        reason_parts = [f"개인화 적합도 {fit_pct}점({fit_label})"]
        if yield_str:
            reason_parts.append(yield_str)
        if age_label:
            reason_parts.append(age_label)
        parts.append(" · ".join(reason_parts))

    # ── 아키타입 매칭 이유 ────────────────────────────────────
    if archetype == "성장형":
        if cat == "dividend_growth":
            parts.append(f"성장형 포트폴리오 핵심 자산 — 배당성장률 {div_grow:.1f}%/년으로 장기 복리 효과 최대화")
        elif cls == "kr_stock" and ml == "INTACT" and cuts == 0:
            parts.append("배당 삭감 이력 없는 안정 한국주 — 성장형에서 국내 배당 기반 역할")
        elif cls == "us_stock" and cons >= 25:
            parts.append(f"미국 배당귀족({cons}년 연속 성장) — 성장형의 신뢰할 수 있는 장기 anchor")

    elif archetype == "월배당형":
        if monthly:
            parts.append("월배당 지급 자산 — 매달 정기적인 현금흐름 제공")
        if cat == "monthly_income":
            parts.append(f"커버드콜 전략으로 배당 {dy:.1f}% 현금흐름 극대화")
        if cls in ("us_reit", "kr_reit"):
            parts.append("리츠 — 임대료 기반 월세 대체 소득")

    elif archetype == "안정형":
        if mdd is not None and mdd > -25.0:
            parts.append(f"MDD {mdd:.0f}% — 하락장에서도 손실 제한, 안정형 최우선 선별")
        if cls == "defensive":
            parts.append("방어형 채권 자산 — 주식 폭락 시 포트폴리오 쿠션 역할")
        if ml == "INTACT" and cuts == 0 and "우량" in grade:
            parts.append("AI 배당 안정 판정 + 삭감 이력 없음 — 안정형 기준 최상위 통과")

    elif archetype == "은퇴형":
        if monthly:
            parts.append("월배당 — 은퇴 후 생활비를 매달 안정적으로 충당")
        if cls in ("us_reit", "kr_reit"):
            parts.append(f"리츠 배당 {dy:.1f}% — 임대 수익 대체 은퇴 소득원")
        if cls == "defensive" and cat == "cash_equivalent":
            parts.append("초단기 국채(CMA 대체) — 필요시 즉시 출금 가능한 은퇴 현금 버퍼")

    # ── 핵심 지표 강점 ────────────────────────────────────────
    total_return = round(dy + cap, 1)
    if cls == "kr_stock":
        if "우량" in grade:
            parts.append(f"배당 종합점수 {score:.0f}점 🟢 우량 — 수익률 {dy:.1f}% + 자본차익 {cap:.1f}% = 총 {total_return}%")
        elif score >= 65:
            parts.append(f"배당 종합점수 {score:.0f}점 — 배당 {dy:.1f}% 안정 수준")
        if cuts == 0 and ml == "INTACT":
            parts.append("최근 3년 배당 삭감 없음. AI 배당지속 판정")
        elif cuts > 0:
            parts.append(f"최근 3년 배당삭감 {cuts}회 — 비중 축소 적용")
    elif cls == "us_stock":
        if cons >= 50:
            parts.append(f"배당킹 ({cons}년 연속 성장) — 세계 최고 수준 배당 신뢰성")
        elif cons >= 25:
            parts.append(f"배당귀족 ({cons}년 연속 성장) — 경기침체에도 배당 유지한 역사적 검증")
        elif cons >= 10:
            parts.append(f"배당챌린저 ({cons}년 연속 성장) — 10년+ 배당 성장 트랙레코드")
        parts.append(f"배당 {dy:.1f}% + 자본차익 {cap:.1f}% = 총 {total_return}%")
    elif cls in ("us_div_etf", "kr_etf"):
        if cat == "dividend_growth" and div_grow >= 8.0:
            parts.append(f"5년 배당성장률 {div_grow:.1f}% — 복리로 10년 후 배당 2.6배")
        elif cat == "monthly_income":
            parts.append(f"월배당 ETF — 배당 {dy:.1f}%, 매달 현금흐름 제공")
        elif cat == "high_yield":
            parts.append(f"고배당 ETF — 현재 {dy:.1f}% 배당 수익, 넓은 분산")
        if mdd is not None:
            parts.append(f"MDD {mdd:.0f}%, 분산투자로 개별주 리스크 제거")
    elif cls in ("us_reit", "kr_reit"):
        parts.append(f"리츠 배당 {dy:.1f}% — 부동산 임대 수익의 주식 형태")
    elif cls == "defensive":
        if cat == "cash_equivalent":
            parts.append(f"초단기 미국채 {dy:.1f}% — 사실상 무위험 수익, CMA 대체")
        elif cat == "long_bond":
            parts.append(f"장기국채 {dy:.1f}% — 주식 하락 시 헤지 효과 (역상관)")
        else:
            parts.append(f"채권 {dy:.1f}% — 변동성 완충재, 포트폴리오 안정화")

    # ── 세금 최적화 포인트 ────────────────────────────────────
    if "ISA" in account:
        if cls in ("kr_etf", "kr_reit", "kr_stock"):
            parts.append("ISA 편입 → 9.9% 분리과세 (일반 15.4% 대비 절세)")
        elif cls in ("us_div_etf", "us_stock", "us_reit"):
            parts.append("ISA 편입 가능 → 미국 원천징수 15%만 (국내 배당세 면제)")

    # ── 리스크 경고 ───────────────────────────────────────────
    if trap == "WATCH":
        parts.append(f"⚠️ Yield {dy:.1f}% 높음 — Trap 가능성 모니터링 권장")
    if trap == "DANGER":
        parts.append(f"🚨 고배당 Trap 위험 — 비중 최소화 또는 제외 권장")
    if ml == "WEAKENING":
        parts.append("⚠️ AI 배당 약화 신호 — 비중 축소 적용됨")

    if not parts:
        return item.get("description", "배당 전용 AI 스코어링 기반 선별")

    return ". ".join(parts[:4])  # 너무 길어지지 않도록 최대 4개 포인트


# ── ISA 절세 전략 ──────────────────────────────────────────────

def get_isa_strategy(annual_income: int, investable: int) -> dict:
    # 2026 개정 세법: 연 납입한도 4,000만 / 비과세 서민·청년형 1,000만·일반형 500만
    from utils.tax_optimizer import (
        ISA_ANNUAL_LIMIT, ISA_TAX_FREE_GENERAL, ISA_TAX_FREE_YOUTH,
    )
    is_low = annual_income <= 5000
    isa_annual = min(max(investable // 3, 0), ISA_ANNUAL_LIMIT)
    tax_free   = ISA_TAX_FREE_YOUTH if is_low else ISA_TAX_FREE_GENERAL
    est_div    = investable * 0.035
    tax_saved  = round(est_div * 0.055, 1)
    return {
        "isa_type":           "서민·청년형" if is_low else "일반형",
        "annual_limit":       ISA_ANNUAL_LIMIT,
        "recommended_annual": isa_annual,
        "tax_free_limit":     tax_free,
        "tax_rate":           "9.9% 분리과세 (일반 15.4% 대비 5.5%p 절세)",
        "estimated_tax_saved_만원": tax_saved,
        "holding_period":     "3년 의무 보유",
        "tip": (
            f"서민·청년형 ISA — 비과세 한도 {ISA_TAX_FREE_YOUTH}만원(2026 세법). "
            "TIGER 미국배당다우존스, SK리츠 등 국내상장ETF·리츠를 ISA에 우선 편입."
            if is_low else
            f"일반형 ISA — 비과세 한도 {ISA_TAX_FREE_GENERAL}만원(2026 세법). "
            "국내 배당주·국내상장ETF를 ISA에 담아 절세 효과 극대화."
        ),
    }


# ── 한국 배당주 선별 ───────────────────────────────────────────

def pick_kr_stocks(risk: str, n: int, age: int | None = None) -> list[dict]:
    """
    ranking.csv (dividend_scorer 기반 재구성)에서 한국 배당주 선별.

    ranking.csv 컬럼 활용:
      - overall_score: 배당 전용 종합 점수 (yield+stability+financial+growth)
      - grade: 🟢 우량 / 🟡 보통 / 🟠 주의
      - trap_level: SAFE / WATCH / DANGER
      - ml_status: INTACT / WEAKENING / BROKEN
      - dps_cuts_3y: 최근 3년 배당 삭감 횟수
    """
    if not os.path.exists(RANKING_CSV):
        return []

    df = pd.read_csv(RANKING_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)

    # ── 방어 필터 ──────────────────────────────────────────────
    # 1. 한국 6자리 코드만
    df = df[df["stock_code"].str.match(r"^\d{6}$")]
    # 2. DANGER trap 항상 제외
    if "trap_level" in df.columns:
        df = df[df["trap_level"] != "DANGER"]
    # 3. 점수 50점 미만 제외
    if "overall_score" in df.columns:
        # 커트라인 50: 4축(yield+stability+financial+growth) 합산 절반 이하 종목 제외
        # (내부 설계 기준 — SCORING_RATIONALE["overall_score_cutoff"] 참조)
        df = df[pd.to_numeric(df["overall_score"], errors="coerce").fillna(0) >= 50]

    # ── TabPFN Survival Hard Gate ──────────────────────────────
    # risk score 기반 고위험군 제거 (threshold별 Precision/Recall 실험 결과 적용)
    # 근거: threshold_analysis (survival_pd_v4.json 내 실험 결과)
    #   conservative → 0.35: Recall=50.0%, F1=0.442 (위험 종목 최대 포착)
    #   moderate     → 0.50: Recall=35.2%, F1=0.378 (균형)
    #   aggressive   → 0.65: Precision=47.6%, F1=0.308 (안전 종목 오제거 최소화)
    # * "hazard_pct=0.XX = XX% 배당삭감 확률"이 아님.
    #   uncalibrated risk score 기준 고위험군 분류임 (ROC-AUC 0.583 기준)
    _SURVIVAL_GATE = {
        "conservative": 0.35,
        "moderate":     0.50,
        "aggressive":   0.65,
    }
    _gate_threshold = _SURVIVAL_GATE.get(risk, 0.50)

    _survival_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "results", "survival_pd_v4.json")
    if os.path.exists(_survival_path):
        try:
            import json as _json
            with open(_survival_path) as _f:
                _sv = _json.load(_f)
            _stock_risk = _sv.get("stock_risk", {})
            if _stock_risk:
                def _get_hz(code):
                    return _stock_risk.get(str(code), {}).get("hazard_pct", 0.5)
                df["_hazard"] = df["stock_code"].apply(_get_hz)
                df = df[df["_hazard"] <= _gate_threshold]
                df = df.drop(columns=["_hazard"])
        except Exception:
            pass

    # ── 성향별 추가 필터링 ─────────────────────────────────────
    if risk == "conservative":
        # 🟢 우량 + ML INTACT + 삭감 이력 없는 종목 우선
        if "grade" in df.columns:
            df = df[df["grade"].str.contains("우량", na=False)]
        if "ml_status" in df.columns:
            df = df[df["ml_status"] == "INTACT"]
    elif risk == "aggressive":
        # 🟠 주의까지 허용, yield 높은 순
        if "yield" in df.columns:
            df = df.sort_values("yield", ascending=False)
    # moderate: overall_score 기본 정렬 유지

    # ── 나이 기반 정렬 틸트 — 같은 점수 풀에서도 나이대별로 다른 종목이 뽑히도록 ──
    if age is not None and "growth" in df.columns and "stability" in df.columns:
        _o = pd.to_numeric(df["overall_score"], errors="coerce").fillna(0)
        _g = pd.to_numeric(df["growth"], errors="coerce").fillna(0)
        _s = pd.to_numeric(df["stability"], errors="coerce").fillna(0)
        if age < 35:
            df = df.assign(_rank=_o + 0.5 * _g)   # 젊을수록 성장 가점
        elif age >= 55:
            df = df.assign(_rank=_o + 0.5 * _s)   # 나이들수록 안정 가점
        else:
            df = df.assign(_rank=_o)
        df = df.sort_values("_rank", ascending=False)
    else:
        df = df.sort_values("overall_score", ascending=False)

    stocks = []
    for _, row in df.head(n).iterrows():
        dy       = float(row.get("yield", 0) or 0)
        grade    = str(row.get("grade", ""))
        ml_st    = str(row.get("ml_status", "INTACT"))
        cuts     = int(row.get("dps_cuts_3y", 0) or 0)

        # 자본차익: ML INTACT + 삭감 없으면 3.5%, 그 외 2.0%
        if ml_st == "INTACT" and cuts == 0:
            cap_gain = 3.5
        elif "우량" in grade:
            cap_gain = 3.0
        else:
            cap_gain = 2.0

        stocks.append({
            "ticker":            str(row.get("stock_code", "")),
            "name":              str(row.get("name", "")),
            "asset_class":       "kr_stock",
            "account":           "ISA/일반",
            "risk_profile":      "stable"   if ml_st == "INTACT" and cuts == 0 else "moderate",
            "expected_yield":    dy,
            "capital_gain_rate": cap_gain,
            "description":       str(row.get("score_reason", "KRX 배당 전용 AI 스코어링")),
            "overall_score":     float(row.get("overall_score", 50) or 50),
            "grade":             grade,
            "trap_level":        str(row.get("trap_level", "SAFE")),
            "ml_status":         ml_st,
            "dps_cuts_3y":       cuts,
            "latest_yoy_pct":    float(row.get("latest_yoy_pct", 0) or 0),
        })
    return stocks


# ── ETF 선별 ───────────────────────────────────────────────────

def pick_etfs(risk: str, etf_yields: dict, archetype: str = "혼합형",
              macro_regime: dict = None) -> list[dict]:
    """
    아키타입 + 성향 기반 ETF 선별.

    아키타입이 etf_category 우선순위를 결정:
      성장형  → dividend_growth ETF 우선
      월배당형 → monthly_income ETF 우선
      안정형  → high_yield + defensive 우선
      은퇴형  → monthly_income + reit + cash_equivalent 우선
      혼합형  → 품질점수 우선 (기존 방식)

    선별 우선순위:
      1. 아키타입 우선 카테고리 ETF
      2. 나머지 카테고리 ETF (보완적 편입)
      3. 방어형 (아키타입별 defensive_categories만)
    """
    arch_cfg = ARCHETYPE_CONFIG.get(archetype, ARCHETYPE_CONFIG["혼합형"])
    cat_priority   = arch_cfg["etf_categories_priority"]
    cat_excluded   = arch_cfg["excluded_categories"]
    def_categories = arch_cfg["defensive_categories"]

    # 성향별 ticker 제외
    excluded_tickers: set[str] = set()
    if risk == "conservative":
        # 커버드콜 계열 (자본 침식 위험) + 고위험 고배당 전체 제외
        excluded_tickers = {"JEPQ", "DGRW", "QYLD", "SPYI", "XYLD", "RYLD", "MO", "PFE"}
    elif risk == "moderate":
        excluded_tickers = {"QYLD", "XYLD", "RYLD", "MO"}

    # 유니버스 로드 + 품질 QC
    universe = load_approved_universe()
    universe = filter_etf_universe(universe, min_score=40.0)

    # Macro Regime ETF 품질스코어 보너스 적용 (있으면)
    if macro_regime:
        universe = apply_macro_to_etf_scores(universe, macro_regime)

    picks: list[dict] = []
    seen_tickers: set[str] = set()

    def _sort_key(e: dict) -> tuple:
        """
        아키타입별 정렬 기준.
        1차: 아키타입 우선 카테고리에 속하는지 여부
        2차: 성향별 정렬 기준
        """
        in_priority = 0 if e.get("etf_category", "") in cat_priority else 1
        if risk == "aggressive":
            score = -(e.get("capital_gain_rate", 0) + e.get("expected_yield", 0))
        elif risk == "conservative":
            score = (0 if e.get("risk_profile") == "stable" else 1, -e.get("expected_yield", 0))[1]
        else:
            score = -e.get("etf_quality_score", 60)
        return (in_priority, score)

    def _add(cls_list: list[str], max_count: int, force_categories: list[str] = None):
        """
        지정 asset_class에서 최대 max_count개 선별.
        force_categories가 있으면 해당 etf_category만 허용.
        """
        pool = [
            e for e in universe
            if (
                e["asset_class"] in cls_list
                and e["ticker"] not in excluded_tickers
                and e["ticker"] not in seen_tickers
                and e.get("etf_category", "") not in cat_excluded
                and (force_categories is None or e.get("etf_category", "") in force_categories)
            )
        ]
        pool.sort(key=_sort_key)
        for etf in pool[:max_count]:
            entry = dict(etf)
            entry["expected_yield"] = etf_yields.get(etf["ticker"], etf["expected_yield"])
            entry["overall_score"]  = entry.get("etf_quality_score", 70.0)
            entry["grade"]          = "🟢 우량"
            entry["trap_level"]     = "SAFE"
            seen_tickers.add(entry["ticker"])
            picks.append(entry)

    # _sort_key가 이미 아키타입 우선 카테고리를 1순위로 정렬하므로
    # 단순히 클래스별로 한 번만 _add 호출 — 자동으로 우선 카테고리 먼저 편입됨

    def _pin(ticker):
        """특정 ETF를 점수와 무관하게 우선 편입 (예: SCHD 배당투자 기준점)."""
        for e in universe:
            if (e["ticker"] == ticker and ticker not in seen_tickers
                    and ticker not in excluded_tickers):
                entry = dict(e)
                entry["expected_yield"] = etf_yields.get(ticker, e["expected_yield"])
                entry["overall_score"]  = entry.get("etf_quality_score", 70.0)
                entry["grade"]      = "🟢 우량"
                entry["trap_level"] = "SAFE"
                seen_tickers.add(ticker)
                picks.append(entry)
                return True
        return False

    # SCHD = 배당투자의 기준점 — 항상 편입하고 나머지 슬롯을 점수순으로 채움
    _schd_pinned = _pin("SCHD")
    _add(["us_div_etf"], max_count=4 - (1 if _schd_pinned else 0))

    # 한국 ETF (최대 3개)
    _add(["kr_etf"], max_count=3)

    # 리츠 (월배당형·은퇴형은 3개, 그 외 2개)
    reit_count = 3 if archetype in ("월배당형", "은퇴형") else 2
    _add(["us_reit", "kr_reit"], max_count=reit_count)

    # 방어형 (최대 2개, 아키타입별 defensive_categories만 허용)
    # 성장형: def_categories=[] → 방어 ETF 없음
    if def_categories:  # 빈 리스트면 방어 ETF 완전 제외
        _add(["defensive"], max_count=2, force_categories=def_categories)

    return picks


US_SCORES_CSV = os.path.join(BASE_DIR, "data", "us_stock_scores.csv")

def _load_us_scores() -> pd.DataFrame:
    """
    us_stock_scores.csv 로드.
    dividend_scorer.py가 us_dividend_dataset.csv로 계산한 실제 스코어.
    파일 없으면 빈 DataFrame 반환 → universe.py 하드코딩 fallback.
    """
    if not os.path.exists(US_SCORES_CSV):
        return pd.DataFrame()
    try:
        df = pd.read_csv(US_SCORES_CSV)
        return df
    except Exception:
        return pd.DataFrame()


def pick_us_stocks(risk: str, etf_yields: dict, n: int = 4) -> list[dict]:
    """
    미국 배당 개별주 픽업.

    데이터 우선순위:
      1. us_stock_scores.csv (dividend_scorer 실제 점수)
         - Dividend King/Aristocrat/Challenger 등급 반영
         - payout ratio, coverage, YoY 성장률 반영
      2. 파일 없을 때 → ETF_UNIVERSE 하드코딩 fallback
    """
    df_scores = _load_us_scores()

    if df_scores.empty:
        # fallback: 기존 하드코딩 방식
        universe = [e for e in load_approved_universe() if e["asset_class"] == "us_stock"]
        pool = universe
    else:
        # ❌ 제외 등급 제거
        df_scores = df_scores[df_scores["grade"] != "❌ 제외"].copy()

        # 성향별 필터링
        if risk == "conservative":
            # DANGER trap 제외, Dividend Aristocrat/King만
            df_scores = df_scores[df_scores["trap_level"] != "DANGER"]
            df_scores = df_scores[df_scores["asset_type"].isin(["DIVIDEND_KING", "DIVIDEND_ARISTOCRAT"])]
            df_scores = df_scores.sort_values("overall_score", ascending=False)
        elif risk == "aggressive":
            # 총수익률(배당+자본차익) 기준 — 고yield도 허용
            df_scores["_total_return"] = df_scores["yield_pct"] + df_scores.get("capital_gain_rate", 4.0)
            df_scores = df_scores.sort_values("_total_return", ascending=False)
        else:
            # moderate: 종합점수 우선, DANGER trap 제외
            df_scores = df_scores[df_scores["trap_level"] != "DANGER"]
            df_scores = df_scores.sort_values("overall_score", ascending=False)

        pool = df_scores.head(n * 2).to_dict("records")  # 여유분 확보
        universe = [e for e in load_approved_universe() if e["asset_class"] == "us_stock"]
        universe_map = {e["ticker"]: e for e in universe}

    picks = []
    seen = set()

    for row in pool:
        if len(picks) >= n:
            break
        ticker = row.get("ticker", "")
        if ticker in seen:
            continue
        seen.add(ticker)

        # universe.py에서 계좌, 설명 등 보완
        uni = universe_map.get(ticker, {}) if not df_scores.empty else {}
        live_yield = etf_yields.get(ticker, row.get("yield_pct", row.get("expected_yield", 3.0)))

        picks.append({
            "ticker":            ticker,
            "name":              row.get("name", uni.get("name", ticker)),
            "asset_class":       "us_stock",
            "asset_type":        row.get("asset_type", uni.get("asset_type", "DIVIDEND_ARISTOCRAT")),
            "account":           uni.get("account", row.get("account", "일반")),
            "risk_profile":      row.get("risk_profile", uni.get("risk_profile", "stable")),
            "expected_yield":    live_yield,
            "capital_gain_rate": row.get("capital_gain_rate", uni.get("capital_gain_rate", 4.0)),
            "description":       row.get("description", uni.get("description", "")),
            "overall_score":     float(row.get("overall_score", 70.0)),
            "grade":             row.get("grade", "🟢 우량"),
            "trap_level":        row.get("trap_level", "SAFE"),
            "consecutive_years": int(row.get("consecutive_years", 0) or 0),
        })
    return picks


# ── 비중 & 항목 계산 ───────────────────────────────────────────

def assign_weights(
    kr_stocks:      list[dict],
    us_stocks:      list[dict],
    etfs:           list[dict],
    axis_w:         dict,
    investable:     int,
    monthly_target: int,
    annual_income:  int  = 5000,
    archetype:      str  = "혼합형",
    req_age:        int  = 40,
    req_risk:       str  = "moderate",
) -> list[dict]:
    result: list[dict] = []

    kwargs = dict(
        investable=investable,
        annual_income=annual_income,
        archetype=archetype,
        axis_w=axis_w,
        req_age=req_age,
        req_risk=req_risk,
    )

    # 한국 배당주 — overall_score 비례
    total_kr_w = axis_w["kr_stock"]
    if kr_stocks:
        scores  = [s["overall_score"] for s in kr_stocks]
        s_total = sum(scores) or 1
        for s, sc in zip(kr_stocks, scores):
            _append(result, s, total_kr_w * sc / s_total, **kwargs)

    # 미국 배당 개별주 — overall_score 비례
    total_us_stock_w = axis_w.get("us_stock", 0.0)
    if us_stocks:
        scores  = [s["overall_score"] for s in us_stocks]
        s_total = sum(scores) or 1
        for s, sc in zip(us_stocks, scores):
            _append(result, s, total_us_stock_w * sc / s_total, **kwargs)

    # ETF — 그룹별 yield 비례
    # us_div_etf + kr_etf 합산해서 us_etf 비중 배분
    etf_classes  = ["us_div_etf", "kr_etf"]
    reit_classes = ["us_reit", "kr_reit"]

    def _add_group(cls_list: list[str], total_w: float):
        items = [e for e in etfs if e["asset_class"] in cls_list]
        if not items:
            return
        yields = [i["expected_yield"] for i in items]
        y_tot  = sum(yields) or 1
        for item, y in zip(items, yields):
            _append(result, item, total_w * y / y_tot, **kwargs)

    _add_group(etf_classes,  axis_w["us_etf"])
    _add_group(reit_classes, axis_w["reit"])
    _add_group(["defensive"], axis_w["defensive"])

    # ── ticker 중복 제거 ──────────────────────────────────────
    # 예: SPG가 us_stock_scores(주식)·ETF_UNIVERSE(리츠) 양쪽 소스에 존재.
    # 같은 종목이 두 카드로 보이는 버그 → REIT 분류를 우선 유지하고 하나만 남김.
    _seen: dict[str, int] = {}
    _dedup: list[dict] = []
    for r in result:
        t = str(r.get("ticker", ""))
        if t in _seen:
            idx = _seen[t]
            cur_is_reit = "reit" in r.get("asset_class", "")
            kept_is_reit = "reit" in _dedup[idx].get("asset_class", "")
            # REIT 분류를 더 정확한 것으로 보고, 비중은 둘 합산
            merged_w = _dedup[idx].get("weight_pct", 0) + r.get("weight_pct", 0)
            if cur_is_reit and not kept_is_reit:
                _dedup[idx] = r
            _dedup[idx]["weight_pct"] = merged_w
            continue
        _seen[t] = len(_dedup)
        _dedup.append(r)
    result = _dedup

    # 1차 정규화 → 100%
    total_w = sum(r["weight_pct"] for r in result) or 100
    for r in result:
        r["weight_pct"] = r["weight_pct"] / total_w * 100

    # 단일 종목 비중 상한 8% — 초과분을 여유 있는 종목에 비례 재분배
    # (예: SPG 단일 리츠 13% → 8%로 제한, 심사 시 '왜 한 종목 13%?' 방지)
    MAX_SINGLE = 8.0
    for _ in range(6):
        excess = sum(max(0.0, r["weight_pct"] - MAX_SINGLE) for r in result)
        if excess < 0.05:
            break
        for r in result:
            if r["weight_pct"] > MAX_SINGLE:
                r["weight_pct"] = MAX_SINGLE
        under = [r for r in result if r["weight_pct"] < MAX_SINGLE - 0.01]
        room = sum(MAX_SINGLE - r["weight_pct"] for r in under) or 1.0
        for r in under:
            r["weight_pct"] += excess * (MAX_SINGLE - r["weight_pct"]) / room

    # 최종 정규화 + 금액 산출
    total_w = sum(r["weight_pct"] for r in result) or 100
    for r in result:
        r["weight_pct"]           = round(r["weight_pct"] / total_w * 100, 1)
        r["invest_amount_만원"]   = round(investable * r["weight_pct"] / 100, 0)
        annual                    = r["invest_amount_만원"] * r["dividend_yield"] / 100
        r["est_annual_div_만원"]  = round(annual, 1)
        r["est_monthly_div_만원"] = round(annual / 12, 2)
        net_annual = r["invest_amount_만원"] * r.get("net_yield_pct", r["dividend_yield"]) / 100
        r["est_annual_div_after_tax"]  = round(net_annual, 1)
        r["est_monthly_div_after_tax"] = round(net_annual / 12, 2)
        r["total_return_pct"] = round(r["dividend_yield"] + r.get("capital_gain_rate", 0), 2)

    # 반올림 잔차 보정 — 합계를 정확히 100.0%로 (심사 시 합산 검증 대비)
    if result:
        diff = round(100.0 - sum(r["weight_pct"] for r in result), 1)
        if abs(diff) >= 0.1:
            top = max(result, key=lambda r: r["weight_pct"])
            top["weight_pct"] = round(top["weight_pct"] + diff, 1)
            top["invest_amount_만원"]   = round(investable * top["weight_pct"] / 100, 0)
            _ann = top["invest_amount_만원"] * top["dividend_yield"] / 100
            top["est_annual_div_만원"]  = round(_ann, 1)
            top["est_monthly_div_만원"] = round(_ann / 12, 2)
            _net = top["invest_amount_만원"] * top.get("net_yield_pct", top["dividend_yield"]) / 100
            top["est_annual_div_after_tax"]  = round(_net, 1)
            top["est_monthly_div_after_tax"] = round(_net / 12, 2)

    return result


def _append(result, item, weight, investable, annual_income=5000,
            archetype="혼합형", axis_w=None, req_age=40, req_risk="moderate"):
    dy       = item.get("expected_yield", 0) or 0
    cap_gain = item.get("capital_gain_rate", 0) or 0
    invest   = round(investable * weight)
    annual   = invest * dy / 100

    # ── ML 리스크 붙이기 (한국 주식 전용) ────────────────────────
    ticker     = str(item.get("ticker", ""))
    asset_cls  = item.get("asset_class", "")
    ml_data    = ML_SCORES.get(ticker, {}) if asset_cls == "kr_stock" else {}
    ml_status  = ml_data.get("ml_status", item.get("ml_status", "INTACT"))
    p_wkn      = ml_data.get("P_WEAKENING", 0.0)
    p_brk      = ml_data.get("P_BROKEN", 0.0)
    ml_score   = ml_data.get("ml_score", 0.0)
    dps_yoy    = ml_data.get("dps_yoy_pct", None)

    # ML 상태에 따른 리스크 아이콘
    ml_icon = {"INTACT": "🟢", "WEAKENING": "🟡", "BROKEN": "🔴"}.get(ml_status, "⚪")

    # ── 자산 메타데이터 붙이기 ──────────────────────────────────
    meta_key = ticker
    meta = ASSET_META.get(meta_key, {})
    if not meta and asset_cls == "kr_stock":
        meta = ASSET_META.get("_default", {})

    pay_months      = meta.get("pay_months", [4])
    div_growth_rate = meta.get("div_growth_rate_pct", item.get("div_growth_5y", 3.0))
    volatility      = meta.get("volatility_annual_pct", item.get("volatility", 20.0))
    mdd             = meta.get("max_drawdown_pct", item.get("mdd", -40.0))
    pay_frequency   = "monthly" if item.get("monthly_pay") else meta.get("pay_frequency", "annual")
    type_label_meta = meta.get("type_label", "")
    expense_ratio   = item.get("expense_ratio", meta.get("expense_ratio_pct"))

    # ── 세후 수익률 계산 ──────────────────────────────────────
    account_str = item.get("account", "일반")
    tax_info = calc_after_tax_yield(
        gross_yield=dy,
        asset_class=asset_cls,
        account=account_str,
        annual_income=annual_income,
    )
    net_yield = tax_info["net_yield"]
    net_annual = invest * net_yield / 100

    # ── 추천 이유 생성 ────────────────────────────────────────
    # item에 mdd/div_growth_5y 필드가 universe.py에 있으면 바로 사용
    item_for_reason = {**item, "max_drawdown_pct": mdd, "ml_status": ml_status,
                       "dps_cuts_3y": item.get("dps_cuts_3y", 0)}
    reason = generate_recommendation_reason(
        item=item_for_reason,
        archetype=archetype,
        axis_w=axis_w or {},
        req_age=req_age,
        req_risk=req_risk,
    )

    result.append({
        "ticker":              ticker,
        "stock_code":          ticker,
        "name":                item["name"],
        "asset_class":         asset_cls,
        "asset_class_label":   ASSET_CLASS_LABEL.get(asset_cls, asset_cls),
        "etf_category":        item.get("etf_category", ""),
        "account":             account_str,
        "risk_profile":        item.get("risk_profile", "stable"),
        "grade":               item.get("grade", "🟢 우량"),
        "trap_level":          item.get("trap_level", "SAFE"),
        "overall_score":       item.get("overall_score", 65.0),
        "dividend_yield":      dy,
        "capital_gain_rate":   cap_gain,
        "total_return_pct":    round(dy + cap_gain, 2),
        "weight_pct":          round(weight * 100, 1),
        "invest_amount_만원":  invest,
        "est_annual_div_만원": round(annual, 1),
        "est_monthly_div_만원": round(annual / 12, 2),
        # ── 세후 수익률 ──
        "net_yield_pct":           net_yield,
        "tax_rate_eff_pct":        tax_info["tax_rate_eff"],
        "est_annual_div_after_tax": round(net_annual, 1),
        "est_monthly_div_after_tax": round(net_annual / 12, 2),
        "tax_note":                tax_info["note"],
        # ── 추천 이유 ──
        "recommendation_reason":   reason,
        "description":             item.get("description", ""),
        # ── ML 리스크 필드 ──
        "ml_status":           ml_status,
        "ml_icon":             ml_icon,
        "ml_score":            ml_score,
        "P_WEAKENING":         p_wkn,
        "P_BROKEN":            p_brk,
        "dps_yoy_pct":         dps_yoy,
        # ── 자산 메타데이터 ──
        "pay_months":          pay_months,
        "monthly_pay":         item.get("monthly_pay", pay_frequency == "monthly"),
        "pay_frequency":       pay_frequency,
        "div_growth_rate_pct": div_growth_rate,
        "volatility_annual":   volatility,
        "max_drawdown_pct":    mdd,
        "expense_ratio_pct":   expense_ratio,
        "type_label_meta":     type_label_meta,
        "consecutive_years":   item.get("consecutive_years", 0),
        # ── 개인화 랭킹 필드 (PersonalizedRankingFilter 보존) ──
        "fit_score":           item.get("fit_score"),
        "target_yield":        item.get("target_yield"),
        "yield_fit":           item.get("yield_fit"),
        "risk_fit":            item.get("risk_fit"),
        "age_fit":             item.get("age_fit"),
        "growth_fit":          item.get("growth_fit"),
        # ── Cold Start 필드 (cold_start.py 보존) ──────────────
        "cold_start":          item.get("cold_start", False),
        "cold_start_warn":     item.get("cold_start_warn"),
        "data_years":          item.get("data_years"),
    })


# ── 메인 추천 ─────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Portfolio Health Score
# ─────────────────────────────────────────────────────────────
# 포트폴리오를 5가지 축으로 평가 → 종합 건강도 점수 (0~100)
#
# 왜 필요한가?
#   숫자만 늘어놓으면 사용자는 "내 포트폴리오가 좋은지 나쁜지" 모른다.
#   Health Score는 한 줄로 현황을 전달: "84점 — 매우 건강"
#
# 5개 축:
#   stability    (25점): ML 상태·trap·배당삭감 이력 기반
#   growth       (20점): 포트폴리오 배당성장률 CAGR 기반
#   cashflow     (20점): 월배당 비중·현금흐름 분산도 기반
#   tax_efficiency(20점): ISA/연금 비중·실효세율 기반
#   diversification(15점): 자산 클래스·섹터 분산 기반

def calc_portfolio_health(
    recommendations: list[dict],
    projection:       dict = None,
    dividend_calendar: dict = None,
    monte_carlo:      dict = None,
) -> dict:
    """
    포트폴리오 건강도 종합 점수 — Level 2: 6축 시스템.

    축 구성 (총 110점 → 100점 정규화):
      stability         25점: ML 상태·Trap·배당삭감 이력
      growth            20점: 배당 CAGR·YoC 성장 경로
      cashflow          15점: 월배당 비중·현금흐름 다각화
      cashflow_smooth   10점: 월별 균등도 (dividend_calendar smoothness)
      inflation_defense 15점: 배당성장률 vs CPI, TIPS/SCHP 비중
      tax_efficiency    10점: ISA 활용·실효세율
      diversification   15점: 자산군·섹터 분산도

    각 축에 구체적 개선 액션 포함.
    """
    if not recommendations:
        return {"score": 0, "grade": "❌ 데이터 없음", "components": {}, "tips": []}

    tips = []
    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100

    # ── 1. stability_score (25점) ──────────────────────────────
    # ML 상태·trap_level·배당삭감 이력을 비중 가중평균으로 계산
    stability_raw = 0.0
    for r in recommendations:
        w       = r.get("weight_pct", 0) / total_w
        ml      = r.get("ml_status", "INTACT")
        trap    = r.get("trap_level", "SAFE")
        cuts    = int(r.get("dps_cuts_3y", 0) or 0)
        cls     = r.get("asset_class", "")

        # ETF·방어형은 ML 스코어 대신 grade/etf_quality로 평가
        if cls in ("us_div_etf", "kr_etf", "defensive", "us_reit", "kr_reit", "us_stock"):
            asset_stability = 1.0  # 기본 안정
            if trap == "DANGER":  asset_stability = 0.3
            elif trap == "WATCH": asset_stability = 0.7
        else:
            if ml == "BROKEN":     asset_stability = 0.0
            elif ml == "WEAKENING": asset_stability = 0.5
            else:                  asset_stability = 1.0

            if trap == "DANGER": asset_stability *= 0.5
            if cuts >= 2:        asset_stability *= 0.8

        stability_raw += w * asset_stability

    stability_score = round(stability_raw * 25, 1)

    broken_pct  = sum(r.get("weight_pct",0) for r in recommendations if r.get("ml_status")=="BROKEN") / total_w
    weakening_pct = sum(r.get("weight_pct",0) for r in recommendations if r.get("ml_status")=="WEAKENING") / total_w
    danger_pct  = sum(r.get("weight_pct",0) for r in recommendations if r.get("trap_level")=="DANGER") / total_w

    if broken_pct > 0.1:
        tips.append(f"⚠️ BROKEN 배당 종목이 비중 {broken_pct*100:.0f}%를 차지합니다. 즉시 점검 권장.")
    if weakening_pct > 0.2:
        tips.append(f"📉 배당 약화(WEAKENING) 신호 비중 {weakening_pct*100:.0f}%. 대체 종목 검토하세요.")
    if danger_pct > 0.1:
        tips.append(f"🚨 Yield Trap 위험 종목 비중 {danger_pct*100:.0f}%. 비중 축소 권장.")

    # ── 2. growth_score (20점) ────────────────────────────────
    # 포트폴리오 가중 배당성장률
    port_cagr = float((projection or {}).get("portfolio_div_cagr", 0) or 0)

    # 배당성장률 구간: Morningstar 배당성장 전략 자료를 참고해 배당성장률을 핵심 평가 변수로 채택.
    # 8%/6%/4%/2% 기준은 실제 배당성장 ETF(SCHD 등) 역사적 CAGR 분포 기반 내부 설계값.
    # (SCORING_RATIONALE["growth_score"] 참조)
    if port_cagr >= 8.0:   growth_score = 20.0
    elif port_cagr >= 6.0: growth_score = 16.0
    elif port_cagr >= 4.0: growth_score = 12.0
    elif port_cagr >= 2.0: growth_score = 8.0
    else:                  growth_score = 4.0

    if port_cagr < 3.0:
        tips.append(f"📊 포트폴리오 배당성장률 {port_cagr:.1f}%. SCHD·VIG 같은 성장형 ETF 비중을 높이면 장기 복리가 강해집니다.")

    # ── 3. cashflow_score (20점) ──────────────────────────────
    # 월배당 비중 + 배당 다각화 (자산 수·클래스 수)
    monthly_w = sum(r.get("weight_pct",0) for r in recommendations if r.get("monthly_pay")) / total_w
    n_classes  = len(set(r.get("asset_class","") for r in recommendations))
    n_assets   = len(recommendations)

    monthly_score = min(10.0, monthly_w * 10 / 0.3)  # 30% 비중에서 만점
    divers_score  = min(10.0, n_classes * 1.5 + (n_assets / 3))
    cashflow_score = round(min(15.0, monthly_score + divers_score), 1)

    if monthly_w < 0.15 and any(r.get("archetype","") in ("월배당형","은퇴형")
                                  for r in recommendations[:1]):
        tips.append("💵 월배당 자산 비중이 낮습니다. JEPI·SPHD·SGOV 편입으로 현금흐름을 강화하세요.")

    # ── 4. tax_efficiency_score (20점) ────────────────────────
    # ISA/연금 비중 + 평균 실효세율
    isa_w  = sum(r.get("weight_pct",0) for r in recommendations
                  if "ISA" in r.get("account","")) / total_w
    avg_tax = sum(r.get("tax_rate_eff_pct",15) * r.get("weight_pct",0)
                  for r in recommendations) / total_w

    isa_score   = min(12.0, isa_w * 12 / 0.35)    # 35% ISA = 만점
    tax_score   = max(0.0, 8.0 - (avg_tax - 10) * 0.5)  # 세율 낮을수록 높은 점수
    tax_eff_score = round(min(20.0, isa_score + tax_score), 1)

    if isa_w < 0.15:
        tips.append("🏦 ISA 계좌 활용도가 낮습니다. TIGER 미국배당다우존스, SK리츠 등 국내 상장 상품을 ISA로 이동하면 세금 절감 효과가 큽니다.")

    # ── 5. diversification_score (15점) ───��──────────────────
    # 자산 클래스 수 + 특정 클래스 집중 페널티
    class_weights: dict[str, float] = {}
    for r in recommendations:
        cls = r.get("asset_class","")
        class_weights[cls] = class_weights.get(cls,0) + r.get("weight_pct",0)
    class_weights = {k: v/total_w for k,v in class_weights.items()}

    n_cls    = len(class_weights)
    max_conc = max(class_weights.values()) if class_weights else 1.0
    base     = min(10.0, n_cls * 1.8)
    penalty  = max(0.0, (max_conc - 0.45) * 15)  # 45% 초과 집중 시 패널티
    divers_score2 = round(max(0.0, min(15.0, base - penalty)), 1)

    conc_cls = max(class_weights, key=class_weights.get) if class_weights else ""
    if max_conc > 0.50:
        tips.append(f"🎯 {ASSET_CLASS_LABEL.get(conc_cls,conc_cls)} 비중이 {max_conc*100:.0f}%로 높습니다. 다른 자산군 추가로 분산을 강화하세요.")

    # ── 종합 점수 ─────────────────────────────────────────────
    total = round(stability_score + growth_score + cashflow_score + tax_eff_score + divers_score2, 1)

    # 건강도 threshold: 내부 설계값 (외부 기관 직접 인용 없음)
    # 향후 사용자 점수 분포 백분위 기반으로 calibration 예정
    # (SCORING_RATIONALE["health_grade_threshold"] 참조)
    if total >= 85:   grade = "🟢 매우 건강"
    elif total >= 72: grade = "🟡 건강"
    elif total >= 58: grade = "🟠 보통"
    elif total >= 44: grade = "🔴 주의 필요"
    else:             grade = "🚨 개선 긴급"

    # ── 5. cashflow_smoothness (10점) — Level 2 신규 축 ─────
    smoothness_raw  = (dividend_calendar or {}).get("smoothness_score", 0)
    dry_count       = len((dividend_calendar or {}).get("dry_months", []))
    coverage_months = (dividend_calendar or {}).get("coverage_months", 0)
    # smoothness 0~100 → 0~7점, coverage 12개월 → +3점 보너스
    smooth_score    = round(min(10.0, smoothness_raw * 0.07 + min(3.0, coverage_months * 0.25)), 1)
    if smoothness_raw < 40:
        tips.append("📅 배당 집중 분기 쏠림이 심합니다. JEPI·SGOV·O 같은 월배당 자산 추가로 현금흐름 균등화.")
    elif dry_count > 2:
        names = ", ".join((dividend_calendar or {}).get("dry_month_names", [])[:3])
        tips.append(f"📅 {names} 배당 공백. 월배당 ETF 추가로 12개월 완전 커버를 목표로 하세요.")

    # ── 6. inflation_defense (15점) — Level 2 신규 축 ────────
    # 배당성장률이 CPI(2.5%)를 얼마나 상회하는지 + TIPS/SCHP 비중
    tips_w    = sum(r.get("weight_pct",0) for r in recommendations
                    if r.get("etf_category") in ("tips",) or r.get("ticker") in ("SCHP","TIP")) / total_w
    inf_loss  = float((monte_carlo or {}).get("p50_final", 0) or 0)
    pp_loss   = float(((projection or {}).get("inflation") or {}).get("purchasing_power_loss_pct", 39.0))

    # 배당성장률 vs CPI 갭
    growth_vs_cpi = port_cagr - 2.5   # 양수면 CPI 상회
    if growth_vs_cpi >= 4.0:   inf_grow_score = 10.0
    elif growth_vs_cpi >= 2.0: inf_grow_score = 7.0
    elif growth_vs_cpi >= 0.5: inf_grow_score = 4.0
    elif growth_vs_cpi >= 0:   inf_grow_score = 2.0
    else:                      inf_grow_score = 0.0

    tips_bonus     = min(5.0, tips_w * 20)  # TIPS/SCHP 25% = 5점 만점
    inf_def_score  = round(min(15.0, inf_grow_score + tips_bonus), 1)

    if growth_vs_cpi < 0:
        tips.append(f"📉 배당성장률({port_cagr:.1f}%)이 인플레이션(2.5%)을 하회합니다. SCHD·VIG 비중 확대로 실질 구매력을 방어하세요.")
    elif growth_vs_cpi < 2.0:
        tips.append(f"⚠️ 배당성장률이 CPI를 {growth_vs_cpi:.1f}%p 상회 — 양호하나 SCHP(물가연동채) 5% 편입으로 방어력을 강화할 수 있습니다.")

    # ── 세금 효율 재산정 (10점으로 조정) ──────────────────────
    tax_eff_score = round(min(10.0, tax_eff_score / 2.0), 1)   # 20점 → 10점 스케일

    # ── 종합 점수 (110점 만점 → 100점 정규화) ────────────────
    raw_total = (stability_score + growth_score + cashflow_score
                 + smooth_score + inf_def_score + tax_eff_score + divers_score2)
    total = round(raw_total / 1.10, 1)   # 110 → 100 정규화

    if total >= 85:   grade = "🟢 매우 건강"
    elif total >= 72: grade = "🟡 건강"
    elif total >= 58: grade = "🟠 보통"
    elif total >= 44: grade = "🔴 주의 필요"
    else:             grade = "🚨 개선 긴급"

    # 각 축 개선 액션 (axis_actions)
    axis_actions = {
        "stability":         "배당삭감·ML 신호 약화 종목 즉시 점검 및 교체",
        "growth":            "SCHD·VIG 배당성장 ETF 비중 확대, 배당 재투자 활성화",
        "cashflow":          "월배당 자산(JEPI·SGOV·O) 편입으로 현금흐름 다각화",
        "cashflow_smooth":   "JEPI·448290(TIGER미국배당다우존스) 추가로 월별 균등 입금",
        "inflation_defense": "SCHD·SCHP·VIG 비중 확대, 배당성장률 CPI 상회 유지",
        "tax_efficiency":    "ISA 한도(4,000만원) 우선 채우기, 연금저축 배당 ETF 활용",
        "diversification":   "집중된 자산군 비중 축소, 섹터·지역 분산 강화",
    }

    return {
        "score":  total,
        "max":    100,
        "grade":  grade,
        "level":  "Level 2 — 6축",
        "components": {
            "stability": {
                "score": stability_score, "max": 25,
                "label": "배당 안정성 (ML·Trap·삭감 이력)",
                "action": axis_actions["stability"],
            },
            "growth": {
                "score": growth_score, "max": 20,
                "label": f"배당 성장성 (CAGR {port_cagr:.1f}%)",
                "action": axis_actions["growth"],
            },
            "cashflow": {
                "score": cashflow_score, "max": 15,
                "label": f"현금흐름 ({monthly_w*100:.0f}% 월배당·{n_classes}개 자산군)",
                "action": axis_actions["cashflow"],
            },
            "cashflow_smooth": {
                "score": smooth_score, "max": 10,
                "label": f"배당 균등도 (smoothness {smoothness_raw:.0f}점·dry {dry_count}개월)",
                "action": axis_actions["cashflow_smooth"],
            },
            "inflation_defense": {
                "score": inf_def_score, "max": 15,
                "label": f"인플레이션 방어 (성장 vs CPI {growth_vs_cpi:+.1f}%p)",
                "action": axis_actions["inflation_defense"],
            },
            "tax_efficiency": {
                "score": tax_eff_score, "max": 10,
                "label": f"세금 효율 (ISA {isa_w*100:.0f}%·실효세율 {avg_tax:.1f}%)",
                "action": axis_actions["tax_efficiency"],
            },
            "diversification": {
                "score": divers_score2, "max": 15,
                "label": f"분산도 ({n_cls}개 자산군·최대집중 {max_conc*100:.0f}%)",
                "action": axis_actions["diversification"],
            },
        },
        "radar_data": [
            {"axis": k, "score": v["score"], "max": v["max"],
             "pct": round(v["score"]/v["max"]*100, 1)}
            for k, v in {
                "stability": {"score": stability_score, "max": 25},
                "growth": {"score": growth_score, "max": 20},
                "cashflow": {"score": cashflow_score, "max": 15},
                "cashflow_smooth": {"score": smooth_score, "max": 10},
                "inflation_defense": {"score": inf_def_score, "max": 15},
                "tax_efficiency": {"score": tax_eff_score, "max": 10},
                "diversification": {"score": divers_score2, "max": 15},
            }.items()
        ],
        "tips": tips[:5],
        "raw_score": round(raw_total, 1),
    }


@router.post("/recommend")
def recommend_portfolio(req: PortfolioRequest):
    """
    AI 현금흐름 운영체제 — 메인 포트폴리오 추천 엔드포인트.

    기존 1,960줄 God-Function 에서 Pipe-and-Filter 파이프라인으로 리팩토링.
    각 분석 단계는 api/pipeline/filters.py 의 독립 Filter 클래스로 구현.

    실행 순서 (api/pipeline/filters.py 참조):
      MacroRegime → AxisWeight → AssetPicker → WeightAllocator
      → Summarize → Projection → Rebalancing → StressTest
      → SectorExposure → Calendar → RiskAlert → FireEngine
      → MonteCarlo → TaxOptimizer → BehavioralFinance
      → PortfolioHealth → Storytelling
    """
    # PortfolioRequest → PipelinePortfolioRequest 변환
    pipe_req = PipelinePortfolioRequest(
        age               = req.age,
        annual_income     = req.annual_income,
        monthly_target    = req.monthly_target,
        investable_amount = req.investable_amount,
        risk_tolerance    = req.risk_tolerance,
        archetype         = req.archetype,
        monthly_savings   = req.monthly_savings,
        savings_growth    = req.savings_growth,
        target_fire_age   = req.target_fire_age,
        savings_stages    = req.savings_stages or [],
    )
    pipeline = RecommendationPipeline(pipe_req)
    return pipeline.execute()

# ── ML 리스크 경보 생성 ────────────────────────────────────────
# 대체 종목 후보: 섹터별 안정적인 대안
_ALTERNATIVES = {
    # 통신
    "017670": {"name": "KT", "code": "030200", "reason": "KT는 통신 섹터 내 상대적으로 안정적인 배당 이력"},
    "032640": {"name": "SK텔레콤", "code": "017670", "reason": "SK텔레콤 대신 배당 안정성 높은 통신주 검토"},
    # 에너지
    "010950": {"name": "SCHD (미국 배당 ETF)", "code": "SCHD", "reason": "S-Oil 변동성 대신 미국 배당귀족 ETF로 분산"},
    "036460": {"name": "SCHD/VYM", "code": "SCHD", "reason": "가스공사 배당 불안정 — 미국 배당 ETF로 대체 권장"},
    # 기본 fallback
    "_default_broken":   {"name": "SCHD (미국 배당 ETF)", "code": "SCHD",
                           "reason": "배당 구조가 불안정한 종목은 미국 배당귀족 ETF로 일부 대체 검토"},
    "_default_weakening": {"name": "KB금융 또는 신한지주", "code": "105560",
                            "reason": "배당 약화 신호 — 같은 금융 섹터 내 더 안정적인 종목으로 비중 조정 검토"},
}

def _calc_sector_exposure(recommendations: list[dict]) -> dict:
    """
    포트폴리오 전체의 섹터 익스포저 분석.
    asset_metadata.json의 sector_exposure 필드를 포트폴리오 비중으로 가중합산.
    반환: sectors(비중%), top_sector, hhi_score, concentration_risk, warnings
    """
    import json as _json
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    meta_path = os.path.join(BASE_DIR, "data", "asset_metadata.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = _json.load(f)
    except Exception:
        meta = {}

    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0
    sector_totals: dict[str, float] = {}

    for rec in recommendations:
        ticker = rec.get("ticker", "")
        cls    = rec.get("asset_class", "")
        weight = rec.get("weight_pct", 0) / total_w

        sector_map: dict[str, float] = {}
        for sec_key in ("us_div_etf", "kr_etf", "us_reit", "kr_reit", "defensive", "us_stock"):
            section = meta.get(sec_key, {})
            if isinstance(section, dict) and ticker in section:
                asset = section[ticker]
                if isinstance(asset, dict):
                    sector_map = asset.get("sector_exposure", {})
                break

        if not sector_map:
            etf_cat = rec.get("etf_category", "")
            if etf_cat == "cash_equivalent":
                sector_map = {"단기국채": 100}
            elif etf_cat == "long_bond":
                sector_map = {"장기채권": 100}
            elif etf_cat == "reit":
                sector_map = {"리츠": 100}
            elif cls == "kr_stock":
                sector_map = {"국내주식": 100}
            elif cls == "us_stock":
                sector_map = {"미국주식": 100}
            elif "reit" in cls:
                sector_map = {"리츠": 100}
            elif cls == "defensive":
                sector_map = {"채권": 100}
            else:
                sector_map = {"기타": 100}

        for sector, pct in sector_map.items():
            sector_totals[sector] = sector_totals.get(sector, 0.0) + weight * pct / 100

    total_s = sum(sector_totals.values()) or 1.0
    sectors_pct = {k: round(v / total_s * 100, 1)
                   for k, v in sorted(sector_totals.items(), key=lambda x: -x[1])}

    hhi = round(sum((v / 100) ** 2 for v in sectors_pct.values()), 4)
    top_sector = next(iter(sectors_pct), "") if sectors_pct else ""
    top_pct    = sectors_pct.get(top_sector, 0)

    if hhi < 0.10:
        conc_risk = "낮음"
    elif hhi < 0.20:
        conc_risk = "보통"
    else:
        conc_risk = "높음"

    warnings = []
    if top_pct > 35:
        warnings.append(f"{top_sector} 섹터 {top_pct:.0f}% 집중 — 분산 강화 권장.")
    if sectors_pct.get("에너지", 0) > 20:
        warnings.append("에너지 비중 높음 — 유가 변동성 노출 주의.")
    if sectors_pct.get("통신", 0) > 20:
        warnings.append("통신 비중 높음 — 성장성 제한적 섹터 과다 노출.")

    return {
        "sectors":            sectors_pct,
        "top_sector":         top_sector,
        "top_sector_pct":     top_pct,
        "hhi_score":          hhi,
        "concentration_risk": conc_risk,
        "warnings":           warnings,
    }


_RISK_CUT_CACHE: dict = {}

def _get_risk_cut() -> float:
    """학습된 모델 bundle의 risk_alert.top20_cut 로드 (GroupKFold 검증, 정밀도≈96%).
    위험점수 = P_WEAKENING + P_BROKEN 가 이 값 이상이면 경고. 실패 시 기본 0.5."""
    if "cut" in _RISK_CUT_CACHE:
        return _RISK_CUT_CACHE["cut"]
    cut = 0.5  # Survival 기반 전환 후 고정값 사용
    _RISK_CUT_CACHE["cut"] = cut
    return cut


def _build_risk_alerts(recommendations: list[dict]) -> list[dict]:
    """
    추천 포트폴리오 내 WEAKENING/BROKEN 한국 주식을 찾아 경보를 생성한다.

    각 경보에는:
    - 종목명, 위험 등급, ML 확률
    - 왜 위험한지 (배당 추이, 재무 신호)
    - 어떤 종목/ETF로 교체할 수 있는지
    가 담긴다.

    추가로, argmax 상태가 INTACT여도 위험점수(P_WEAKENING+P_BROKEN)가
    학습된 top20_cut 이상이면 '랭킹 경고'를 생성한다 (검증된 96% 정밀도 기준).
    """
    risk_cut = _get_risk_cut()
    alerts = []
    for rec in recommendations:
        status = rec.get("ml_status", "INTACT")

        # 랭킹 기반 보강: argmax INTACT 이지만 합산 위험이 큰 종목
        if status == "INTACT":
            rscore = rec.get("P_WEAKENING", 0) + rec.get("P_BROKEN", 0)
            if rscore >= risk_cut and rec.get("stock_code"):
                alerts.append({
                    "stock_code":  rec.get("stock_code", ""),
                    "name":        rec.get("name", ""),
                    "status":      "AT_RISK",
                    "severity":    "medium",
                    "ml_score":    rec.get("ml_score", 0),
                    "P_WEAKENING": rec.get("P_WEAKENING", 0),
                    "P_BROKEN":    rec.get("P_BROKEN", 0),
                    "risk_score":  round(rscore, 3),
                    "message":     (
                        f"{rec.get('name','')}은(는) 개별 분류상 정상이나, "
                        f"AI 종합 위험점수 {rscore*100:.0f}%로 상위 위험군에 속합니다. "
                        "(검증 기준 이 구간 경고의 96%가 실제 배당 위험) 비중 점검 권장."
                    ),
                    "weight_pct":  rec.get("weight_pct", 0),
                    "alternative": _ALTERNATIVES.get(rec.get("stock_code", ""),
                                                     _ALTERNATIVES["_default_weakening"]),
                })
            continue

        if status not in ("WEAKENING", "BROKEN"):
            continue

        code    = rec.get("stock_code", "")
        name    = rec.get("name", "")
        p_wkn   = rec.get("P_WEAKENING", 0)
        p_brk   = rec.get("P_BROKEN", 0)
        dps_yoy = rec.get("dps_yoy_pct")

        # 위험 설명 생성
        if status == "BROKEN":
            dps_str = f"배당 {dps_yoy:+.1f}%" if dps_yoy is not None else "배당 데이터 부족"
            severity = "high"
            message = (
                f"{name}의 배당 지속성에 적신호. {dps_str}, "
                f"AI 모델이 배당 삭감 확률 {p_brk*100:.0f}%로 감지. "
                "이 비중을 방어형 자산으로 분산하는 것을 권장."
            )
        else:  # WEAKENING
            dps_str = f"최근 배당 {dps_yoy:+.1f}% 증가" if dps_yoy and dps_yoy > 0 else "배당 정체"
            severity = "medium"
            message = (
                f"{name}은 현재 {dps_str}이나 "
                f"AI 모델이 내년 배당 약화 가능성 {p_wkn*100:.0f}%로 감지. "
                "비중을 줄이거나 대체 종목 편입 검토."
            )

        # 대체 종목 제안
        alt = _ALTERNATIVES.get(code)
        if not alt:
            alt = _ALTERNATIVES["_default_broken" if status == "BROKEN" else "_default_weakening"]

        alerts.append({
            "stock_code":  code,
            "name":        name,
            "status":      status,
            "severity":    severity,
            "ml_score":    rec.get("ml_score", 0),
            "P_WEAKENING": p_wkn,
            "P_BROKEN":    p_brk,
            "message":     message,
            "weight_pct":  rec.get("weight_pct", 0),
            "alternative": alt,
        })

    # 위험도 높은 순 정렬
    alerts.sort(key=lambda x: -x["ml_score"])
    return alerts


def _axis_summary(recs: list[dict]) -> list[dict]:
    agg: dict[str, dict] = {}
    for r in recs:
        cls = r["asset_class"]
        if cls not in agg:
            agg[cls] = {"label": r["asset_class_label"], "pct": 0, "dyields": [], "tr": [], "count": 0}
        agg[cls]["pct"]    += r["weight_pct"]
        agg[cls]["dyields"].append(r["dividend_yield"])
        agg[cls]["tr"].append(r["total_return_pct"])
        agg[cls]["count"]  += 1

    result = []
    for cls, d in agg.items():
        if d["count"] == 0:
            continue
        result.append({
            "asset_class":       cls,
            "label":             d["label"],
            "weight_pct":        round(d["pct"], 1),
            "avg_div_yield":     round(sum(d["dyields"]) / len(d["dyields"]), 2),
            "avg_total_return":  round(sum(d["tr"]) / len(d["tr"]), 2),
            "count":             d["count"],
        })
    return result


@router.get("/calc")
def calc_needed_investment(monthly_target: int, avg_yield: float = 3.5):
    annual_target = monthly_target * 12
    needed        = round(annual_target / (avg_yield / 100))
    return {
        "monthly_target_만원":    monthly_target,
        "annual_target_만원":     annual_target,
        "avg_yield_pct":          avg_yield,
        "needed_investment_만원": needed,
        "note": f"배당수익률 {avg_yield}% 가정 시 약 {needed:,}만원 필요",
    }


# ── 포트폴리오 레벨 Thesis ─────────────────────────────────────

# 섹터 분류 (KRX 고배당 종목 기준)
SECTOR_MAP = {
    "000810": "보험",    "001450": "보험",    "005830": "보험",    "082640": "보험",
    "105560": "은행/금융", "055550": "은행/금융", "086790": "은행/금융", "316140": "은행/금융",
    "138930": "은행/금융", "139130": "은행/금융", "175330": "은행/금융", "024110": "은행/금융",
    "071050": "증권",    "016360": "증권",    "006800": "증권",    "039490": "증권",
    "005940": "증권",
    "005930": "전자/IT",  "018260": "전자/IT",  "068270": "전자/IT",
    "000270": "자동차",   "005380": "자동차",
    "017670": "통신",    "032640": "통신",    "030200": "통신",
    "010950": "정유/에너지", "009830": "정유/에너지", "096770": "정유/에너지",
    "036460": "에너지/공기업", "015760": "에너지/공기업",
    "011200": "해운",
    "000150": "지주/복합", "078930": "지주/복합", "001040": "지주/복합",
    "004800": "지주/복합",
    "006360": "건설",    "000720": "건설",
    "114090": "카지노",   "035250": "카지노",
    "002960": "정유",    "033780": "담배",
    "021240": "생활용품", "002030": "다각화",
    "326030": "바이오",   "298020": "화학섬유", "005490": "철강",
}

STATUS_WEIGHT = {"INTACT": 0, "WEAKENING": 0.5, "BROKEN": 1.0}
HEALTH_LABEL  = [
    (0.20, "🟢 매우 건강", "포트폴리오 대부분 안정적. 현 전략 유지 권장."),
    (0.35, "🟡 양호",     "일부 종목 모니터링 필요하나 전반적으로 안정."),
    (0.50, "🟠 주의",     "WEAKENING 종목 다수. 리밸런싱 검토 시점."),
    (0.65, "🔴 위험",     "BROKEN 종목 비중 높음. 즉각적인 포트폴리오 점검 필요."),
    (1.01, "🚨 위기",     "포트폴리오 전반 배당 지속성 위협. 대규모 교체 검토."),
]


@router.get("/thesis")
def portfolio_thesis():
    """
    포트폴리오 레벨 Thesis 종합 분석.

    thesis_history에서 종목별 최신 thesis를 가져와 포트폴리오 건강도를 평가.

    반환:
    - health_score: 0~1 (낮을수록 좋음)
    - health_label: 직관적 평가 문구
    - status_breakdown: INTACT/WEAKENING/BROKEN 비율
    - sector_risk: 섹터별 평균 리스크
    - danger_stocks: 즉시 주의 필요 종목
    - safe_stocks: 안정적 종목 (Top 5)
    - contradiction_count: 신호 괴리 감지 수
    """
    from sqlalchemy import text as sql_text

    # ── 종목별 최신 thesis 조회 ───────────────────────────────
    with engine.connect() as conn:
        rows = conn.execute(sql_text("""
            SELECT DISTINCT ON (stock_code)
                stock_code, name, thesis_status,
                composite_risk, ml_risk, news_risk,
                dominant_event, explanation, action,
                contradiction, contradiction_detail,
                created_at
            FROM thesis_history
            ORDER BY stock_code, created_at DESC
        """)).fetchall()

    if not rows:
        return {"error": "thesis_history 데이터 없음. run_thesis_batch.py를 먼저 실행하세요."}

    stocks = [
        {
            "stock_code":          r[0],
            "name":                r[1],
            "thesis_status":       r[2],
            "composite_risk":      float(r[3]),
            "ml_risk":             float(r[4]),
            "news_risk":           float(r[5]),
            "dominant_event":      r[6],
            "explanation":         r[7],
            "action":              r[8],
            "contradiction":       r[9],
            "contradiction_detail": r[10],
            "sector":              SECTOR_MAP.get(r[0], "기타"),
            "created_at":          r[11].strftime("%Y-%m-%d %H:%M") if r[11] else "",
        }
        for r in rows
    ]

    total = len(stocks)

    # ── 상태 집계 ─────────────────────────────────────────────
    status_counts = {"INTACT": 0, "WEAKENING": 0, "BROKEN": 0}
    for s in stocks:
        status_counts[s["thesis_status"]] = status_counts.get(s["thesis_status"], 0) + 1

    # ── 건강도 점수 (weighted average) ────────────────────────
    # INTACT=0, WEAKENING=0.5, BROKEN=1.0 → 낮을수록 좋음
    health_score = round(
        sum(STATUS_WEIGHT.get(s["thesis_status"], 0.5) for s in stocks) / total, 3
    )

    # 건강도 라벨
    health_label, health_tip = "🟢 매우 건강", ""
    for threshold, label, tip in HEALTH_LABEL:
        if health_score < threshold:
            health_label, health_tip = label, tip
            break

    # ── 섹터별 리스크 집계 ────────────────────────────────────
    sector_data: dict[str, list] = {}
    for s in stocks:
        sector_data.setdefault(s["sector"], []).append(s["composite_risk"])

    sector_risk = sorted(
        [
            {
                "sector":       sector,
                "avg_risk":     round(sum(risks) / len(risks), 3),
                "stock_count":  len(risks),
                "risk_label":   "🔴 고위험" if sum(risks)/len(risks) >= 0.55
                                else "🟡 주의" if sum(risks)/len(risks) >= 0.30
                                else "🟢 안전",
            }
            for sector, risks in sector_data.items()
        ],
        key=lambda x: -x["avg_risk"],
    )

    # ── 위험 종목 & 안전 종목 ─────────────────────────────────
    danger = sorted(
        [s for s in stocks if s["thesis_status"] in ("WEAKENING", "BROKEN")],
        key=lambda x: -x["composite_risk"],
    )
    safe = sorted(
        [s for s in stocks if s["thesis_status"] == "INTACT"],
        key=lambda x: x["composite_risk"],
    )[:5]

    contradiction_stocks = [s for s in stocks if s["contradiction"]]

    # ── 포트폴리오 평균 리스크 ────────────────────────────────
    avg_composite = round(sum(s["composite_risk"] for s in stocks) / total, 3)
    avg_ml        = round(sum(s["ml_risk"]        for s in stocks) / total, 3)
    avg_news      = round(sum(s["news_risk"]      for s in stocks) / total, 3)

    return {
        "generated_at":    stocks[0]["created_at"] if stocks else "",
        "total_stocks":    total,

        # 포트폴리오 건강도
        "health_score":    health_score,       # 0~1 (낮을수록 좋음)
        "health_label":    health_label,
        "health_tip":      health_tip,

        # 상태 분포
        "status_breakdown": {
            "intact":    {"count": status_counts["INTACT"],    "pct": round(status_counts["INTACT"]    / total * 100, 1)},
            "weakening": {"count": status_counts["WEAKENING"], "pct": round(status_counts["WEAKENING"] / total * 100, 1)},
            "broken":    {"count": status_counts.get("BROKEN", 0),   "pct": round(status_counts.get("BROKEN", 0) / total * 100, 1)},
        },

        # 평균 리스크
        "avg_risk": {
            "composite": avg_composite,
            "ml":        avg_ml,
            "news":      avg_news,
        },

        # 섹터별 리스크 (높은 순)
        "sector_risk": sector_risk,

        # 위험 종목
        "danger_stocks": [
            {
                "stock_code":      s["stock_code"],
                "name":            s["name"],
                "sector":          s["sector"],
                "thesis_status":   s["thesis_status"],
                "composite_risk":  s["composite_risk"],
                "dominant_event":  s["dominant_event"],
                "action":          s["action"],
                "contradiction":   s["contradiction"],
            }
            for s in danger
        ],

        # 안전 종목 Top 5
        "safe_stocks": [
            {
                "stock_code":     s["stock_code"],
                "name":           s["name"],
                "sector":         s["sector"],
                "composite_risk": s["composite_risk"],
                "action":         s["action"],
            }
            for s in safe
        ],

        # 신호 괴리 감지
        "contradiction_count": len(contradiction_stocks),
        "contradiction_stocks": [
            {
                "name":   s["name"],
                "detail": s["contradiction_detail"],
            }
            for s in contradiction_stocks
        ],

        # 전체 상세
        "all_stocks": stocks,
    }


# ─────────────────────────────────────────────────────────────────────────────
# AI Advisor Q&A 엔드포인트
# ─────────────────────────────────────────────────────────────────────────────

class AdvisorRequest(BaseModel):
    question:  str
    portfolio: dict          # recommend_portfolio() 결과 전체
    use_llm:   bool = False  # ollama LLM 강화 사용 여부


def ask_portfolio_advisor(req: AdvisorRequest) -> dict:
    """
    자연어 질문 → 포트폴리오 데이터 기반 즉답 엔드포인트.

    POST /portfolio/advisor
    {
        "question":  "지금 배당 얼마야?",
        "portfolio": { ...recommend_portfolio() 반환값... },
        "use_llm":   false
    }
    """
    result = ask_advisor(
        question         = req.question,
        portfolio_result = req.portfolio,
        use_llm          = req.use_llm,
    )
    return {
        "question":     req.question,
        "intent":       result["intent"],
        "intent_label": result["intent_label"],
        "confidence":   result["confidence"],
        "headline":     result["headline"],
        "answer":       result["answer"],
        "data_points":  result["data_points"],
        "action":       result["action"],
        "follow_up":    result["follow_up"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 백테스팅 엔드포인트
# ─────────────────────────────────────────────────────────────────────────────

class FireReverseRequest(BaseModel):
    """
    POST /api/portfolio/fire-reverse

    현재 조건에서 목표(target_fire_age / target_monthly_만원) 달성을 위해
    무엇을 얼마나 바꿔야 하는지 역산한다.

    E_v2 계약:
      - target_monthly_만원 / target_fire_age → FIRE/Reverse FIRE 전용
      - Ranker 점수(fit_score)에는 영향 없음
    """
    current_investable:    float         # 현재 투자금 (만원)
    monthly_savings:       float         # 현재 월 적립금 (만원)
    current_age:           int
    target_fire_age:       int   = 55    # 달성하고 싶은 나이
    target_monthly_만원:   float = 100   # 달성하고 싶은 월배당 (만원)
    avg_net_yield:         float = 5.0   # [역할A] 세후 배당수익률 (%)
    asset_growth_yield:    float | None = None  # [역할B] 자산 누적 성장률 (None이면 avg_net_yield 사용)
    div_growth_rate:       float = 5.0   # 연 배당성장률 (%)
    cpi_rate:              float = 2.5   # 인플레이션 (%)
    annual_savings_growth: float = 0.0   # 연 적립금 증가율 (%, 0=고정)


@router.post("/fire-reverse")
def fire_reverse(req: FireReverseRequest) -> dict:
    """
    FIRE 역산 — 단독 호출용 엔드포인트.

    POST /api/portfolio/fire-reverse
    {
        "current_investable":  5000,
        "monthly_savings":     50,
        "current_age":         40,
        "target_fire_age":     55,
        "target_monthly_만원": 100,
        "avg_net_yield":       5.0,
        "div_growth_rate":     5.0,
        "cpi_rate":            2.5
    }

    응답:
    {
        "current_fire_age":          int | null,
        "gap_years":                 int | null,
        "target_fire_age":           int,
        "target_monthly_만원":       float,
        "already_achievable":        bool,
        "required_monthly_savings":  float | null,  // 방법 1
        "savings_increase":          float | null,
        "required_initial_capital":  float | null,  // 방법 2
        "capital_increase":          float | null,
        "achievable_monthly":        float | null,  // 방법 3
        "message":                   str
    }
    """
    return calc_fire_reverse(
        current_investable    = req.current_investable,
        monthly_savings       = req.monthly_savings,
        current_age           = req.current_age,
        target_fire_age       = req.target_fire_age,
        target_monthly_만원   = req.target_monthly_만원,
        avg_net_yield         = req.avg_net_yield,
        asset_growth_yield    = req.asset_growth_yield,   # 역할B: 총수익률 (None이면 avg_net_yield)
        div_growth_rate       = req.div_growth_rate,
        cpi_rate              = req.cpi_rate,
        annual_savings_growth = req.annual_savings_growth,
    )


# ─────────────────────────────────────────────────────────────
# POST /api/portfolio/fire-lifecycle  — 생애주기 FIRE 계산
# ─────────────────────────────────────────────────────────────
class FireLifecycleRequest(BaseModel):
    current_investable:   float
    savings_stages:       list   # [{"from_age":25,"to_age":27,"monthly_savings":20}, ...]
    current_age:          int
    target_fire_age:      int    = 50
    target_monthly_만원:  float  = 100.0
    avg_net_yield:        float  = 5.0
    div_growth_rate:      float  = 5.0
    cpi_rate:             float  = 2.5


@router.post("/fire-lifecycle")
def fire_lifecycle(req: FireLifecycleRequest) -> dict:
    """
    생애주기 기반 FIRE 계산.
    savings_stages = [{"from_age": 25, "to_age": 27, "monthly_savings": 20}, ...]
    """
    from utils.fire_engine import calc_fire_engine_lifecycle
    return calc_fire_engine_lifecycle(
        current_investable     = req.current_investable,
        savings_stages         = req.savings_stages,
        current_age            = req.current_age,
        target_age             = req.target_fire_age,
        avg_net_yield          = req.avg_net_yield,
        div_growth_rate        = req.div_growth_rate,
        cpi_rate               = req.cpi_rate,
        custom_monthly_man_won = req.target_monthly_만원,
    )


class BacktestRequest(BaseModel):
    portfolio: dict       # recommend_portfolio() 결과 (recommendations 포함)
    start_year: int = 2015
    end_year:   int = 2024


@router.post("/backtest")
def backtest_portfolio(req: BacktestRequest) -> dict:
    """
    포트폴리오 역사적 성과 검증.

    POST /portfolio/backtest
    {
        "portfolio": { ...recommend_portfolio() 반환값... },
        "start_year": 2015,
        "end_year": 2024
    }

    반환: cagr_pct, mdd_pct, sharpe_ratio, yearly_returns, vs_kospi, vs_sp500 등
    """
    recs      = req.portfolio.get("recommendations", [])
    investable = req.portfolio.get("summary", {}).get("investable_amount_만원", 1000)

    result = run_backtest(
        recommendations = recs,
        start_year      = req.start_year,
        end_year        = req.end_year,
        investable      = float(investable),
    )
    return result


# ── MPT 효율적 프론티어 ───────────────────────────────────────────

class OptimizeRequest(BaseModel):
    recommendations: list[dict]
    risk_free_rate:  float = 2.0
    n_portfolios:    int   = 5000
    start_year:      int   = 2015
    end_year:        int   = 2024
    seed:            int   = 42


@router.post("/optimize")
def optimize_portfolio_endpoint(req: OptimizeRequest) -> dict:
    """
    MPT 효율적 프론티어 계산.

    POST /api/portfolio/optimize
    {
        "recommendations": [...],   # POST /recommend 결과의 recommendations
        "risk_free_rate": 2.0,
        "n_portfolios": 5000
    }

    반환:
    {
        "efficient_frontier": {
            "points":         [{volatility, return, sharpe}, ...],
            "max_sharpe":     {tickers, weights, weight_pct, expected_return, volatility, sharpe},
            "min_volatility": {...},
            "valid_tickers":  [...],
            "n_simulated":    5000,
            "years":          "2015-2024",
            "risk_free_rate": 2.0
        }
    }
    """
    from utils.portfolio_optimizer import optimize_portfolio

    tickers = [r.get("ticker", "") for r in req.recommendations if r.get("ticker")]

    return optimize_portfolio(
        tickers          = tickers,
        recommendations  = req.recommendations,
        risk_free_rate   = req.risk_free_rate,
        n_portfolios     = req.n_portfolios,
        start_year       = req.start_year,
        end_year         = req.end_year,
        seed             = req.seed,
    )


# ── AI Portfolio Advisor ──────────────────────────────────────────

class AdvisorRequest(BaseModel):
    portfolio: dict        # POST /recommend 응답 전체
    use_llm:   bool = True # False = fallback only (테스트/오프라인)


@router.post("/advisor")
def portfolio_advisor(req: AdvisorRequest) -> dict:
    """
    AI Portfolio Advisor — 이미 계산된 분석 결과를 LLM이 해석.

    POST /api/portfolio/advisor
    {
        "portfolio": { ...POST /recommend 응답 전체... },
        "use_llm": true
    }

    반환:
    {
        "summary":      str,           # 핵심 2~3문장 요약
        "strengths":    list[str],     # 강점 2~4개
        "risks":        list[str],     # 위험 요소 2~4개
        "action_items": list[str],     # 즉시 행동 2~3개
        "caveats":      list[str],     # 주의사항
        "source":       "llm"|"fallback",
        "model":        str            # 사용 모델 (llm일 때만)
    }

    LLM 역할 제약:
      - 새 종목 추천 금지
      - 입력 데이터 없는 수치 생성 금지
      - FIRE 나이 수정 금지
    """
    from utils.advisor_service import analyze_portfolio
    return analyze_portfolio(req.portfolio, use_llm=req.use_llm)


# ── Portfolio Comparison ──────────────────────────────────────────

class CompareRequest(BaseModel):
    req_a: PortfolioRequest
    req_b: PortfolioRequest


def _extract_compare_metrics(a: dict, b: dict) -> list[dict]:
    """두 파이프라인 결과에서 비교 지표를 추출한다."""
    def _g(d: dict, *keys, default=None):
        """중첩 dict에서 안전하게 값 조회."""
        cur = d
        for k in keys:
            if not isinstance(cur, dict):
                return default
            cur = cur.get(k, default)
        return cur if cur is not None else default

    metrics = [
        {
            "label":  "예상 월배당 (세후)",
            "key":    "monthly_div",
            "a":      _g(a, "summary", "est_monthly_div_after_tax_만원", default=0),
            "b":      _g(b, "summary", "est_monthly_div_after_tax_만원", default=0),
            "unit":   "만원",
            "better": "higher",
        },
        {
            "label":  "목표 달성률",
            "key":    "achievement",
            "a":      _g(a, "summary", "target_achievement_pct", default=0),
            "b":      _g(b, "summary", "target_achievement_pct", default=0),
            "unit":   "%",
            "better": "higher",
        },
        {
            "label":  "린 FIRE 예상 나이",
            "key":    "lean_fire_age",
            "a":      _g(a, "fire_plan", "fire_timeline", "lean_fire_age", default=99),
            "b":      _g(b, "fire_plan", "fire_timeline", "lean_fire_age", default=99),
            "unit":   "세",
            "better": "lower",
        },
        {
            "label":  "일반 FIRE 예상 나이",
            "key":    "regular_fire_age",
            "a":      _g(a, "fire_plan", "fire_timeline", "regular_fire_age", default=99),
            "b":      _g(b, "fire_plan", "fire_timeline", "regular_fire_age", default=99),
            "unit":   "세",
            "better": "lower",
        },
        {
            "label":  "Monte Carlo P50",
            "key":    "mc_p50",
            "a":      _g(a, "monte_carlo", "p50_monthly", default=0),
            "b":      _g(b, "monte_carlo", "p50_monthly", default=0),
            "unit":   "만원/월",
            "better": "higher",
        },
        {
            "label":  "목표 달성 신뢰도",
            "key":    "mc_confidence",
            "a":      _g(a, "monte_carlo", "confidence_at_target", default=0),
            "b":      _g(b, "monte_carlo", "confidence_at_target", default=0),
            "unit":   "%",
            "better": "higher",
        },
        {
            "label":  "최대낙폭 (MDD)",
            "key":    "mdd",
            "a":      abs(_g(a, "backtest", "mdd_pct", default=0)),
            "b":      abs(_g(b, "backtest", "mdd_pct", default=0)),
            "unit":   "%",
            "better": "lower",
        },
        {
            "label":  "Sharpe Ratio",
            "key":    "sharpe",
            "a":      _g(a, "backtest", "sharpe_ratio", default=0),
            "b":      _g(b, "backtest", "sharpe_ratio", default=0),
            "unit":   "",
            "better": "higher",
        },
        {
            "label":  "포트폴리오 건강도",
            "key":    "health",
            "a":      _g(a, "portfolio_health", "score", default=_g(a, "portfolio_health", "overall_score", default=0)),
            "b":      _g(b, "portfolio_health", "score", default=_g(b, "portfolio_health", "overall_score", default=0)),
            "unit":   "/100",
            "better": "higher",
        },
        {
            "label":  "절세 효과",
            "key":    "tax_saving",
            "a":      _g(a, "tax_optimizer", "total_annual_saving_만원", default=0),
            "b":      _g(b, "tax_optimizer", "total_annual_saving_만원", default=0),
            "unit":   "만원/년",
            "better": "higher",
        },
    ]

    # 리스트 값(시계열) → 스칼라 변환
    def _scalar(v):
        if isinstance(v, (list, tuple)):
            return v[-1] if v else 0
        return v if v is not None else 0

    for m in metrics:
        m["a"] = _scalar(m["a"])
        m["b"] = _scalar(m["b"])

    # 각 지표에 winner 결정
    for m in metrics:
        va, vb = float(m["a"] or 0), float(m["b"] or 0)
        if abs(va - vb) < 0.01:
            m["winner"] = "tie"
        elif m["better"] == "higher":
            m["winner"] = "a" if va > vb else "b"
        else:
            m["winner"] = "a" if va < vb else "b"

    return metrics


@router.post("/compare")
def compare_portfolios(req: CompareRequest) -> dict:
    """
    두 포트폴리오 설정을 비교 분석.

    POST /api/portfolio/compare
    {
        "req_a": { ...PortfolioRequest A... },
        "req_b": { ...PortfolioRequest B... }
    }

    반환:
    {
        "portfolio_a":  { ...full pipeline result A... },
        "portfolio_b":  { ...full pipeline result B... },
        "comparison": {
            "metrics": [
                { "label", "key", "a", "b", "unit", "better", "winner" }, ...
            ],
            "winner_counts": { "a": int, "b": int, "tie": int }
        }
    }
    """
    # 두 파이프라인 독립 실행
    pipe_a = RecommendationPipeline(PipelinePortfolioRequest(
        age               = req.req_a.age,
        annual_income     = req.req_a.annual_income,
        monthly_target    = req.req_a.monthly_target,
        investable_amount = req.req_a.investable_amount,
        risk_tolerance    = req.req_a.risk_tolerance,
        archetype         = req.req_a.archetype,
        monthly_savings   = req.req_a.monthly_savings,
        savings_growth    = req.req_a.savings_growth,
        target_fire_age   = req.req_a.target_fire_age,
    ))
    pipe_b = RecommendationPipeline(PipelinePortfolioRequest(
        age               = req.req_b.age,
        annual_income     = req.req_b.annual_income,
        monthly_target    = req.req_b.monthly_target,
        investable_amount = req.req_b.investable_amount,
        risk_tolerance    = req.req_b.risk_tolerance,
        archetype         = req.req_b.archetype,
        monthly_savings   = req.req_b.monthly_savings,
        savings_growth    = req.req_b.savings_growth,
        target_fire_age   = req.req_b.target_fire_age,
    ))

    result_a = pipe_a.execute()
    result_b = pipe_b.execute()

    metrics = _extract_compare_metrics(result_a, result_b)
    winner_counts = {"a": 0, "b": 0, "tie": 0}
    for m in metrics:
        winner_counts[m["winner"]] = winner_counts.get(m["winner"], 0) + 1

    return {
        "portfolio_a": result_a,
        "portfolio_b": result_b,
        "comparison": {
            "metrics":       metrics,
            "winner_counts": winner_counts,
        },
    }

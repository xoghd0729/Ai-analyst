"""
utils/macro_regime.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
시장 국면(Macro Regime) 감지 엔진

■ 설계 철학
  포트폴리오 추천이 항상 같으면 advisor가 아니라 calculator다.
  시장 국면이 달라지면 추천 비중도 달라져야 한다.
  "지금 금리 환경에서는 SGOV 비중 확대를 권장합니다" — 이게 advisor다.

■ 5가지 Regime
  RATE_RISING   : 금리 상승 국면 → 단기채/현금성 선호, 장기채 축소
  RATE_FALLING  : 금리 하락 국면 → 장기채/리츠 강세
  HIGH_VOLATILITY: 변동성 폭발 → JEPI형 커버드콜 유리, 개별주 리스크 ↑
  RECESSION     : 경기침체 우려 → 방어자산 집중, 경기민감 리츠/고배당 경고
  NORMAL        : 정상 국면 → 기본 archetype 비중 그대로

■ 데이터 소스 우선순위
  1. yfinance 실시간 (VIX: ^VIX, 미국10Y: ^TNX, 달러/원: KRW=X)
  2. data/macro_cache.json (TTL 6시간 디스크 캐시)
  3. data/macro_config.json (수동 업데이트 기준값) ← 항상 fallback 존재

■ 사용법
  from utils.macro_regime import get_macro_regime
  regime = get_macro_regime()
  # regime["name"], regime["weight_adjustments"], regime["advisory"]
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH  = os.path.join(BASE_DIR, "data", "macro_cache.json")
CONFIG_PATH = os.path.join(BASE_DIR, "data", "macro_config.json")

# ─────────────────────────────────────────────────────────────
# 기준값 설정 (macro_config.json 없을 때 fallback)
# ─────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "_comment": "수동으로 업데이트 가능. get_macro_regime()은 이 값 + yfinance 실시간으로 국면 판단.",
    "fed_rate":     4.75,   # 미국 기준금리 (%)
    "us_10y_yield": 4.40,   # 미국 10년 국채 수익률 (%)
    "vix":          18.0,   # VIX 지수
    "usd_krw":      1350.0, # 달러/원 환율
    "kr_base_rate": 3.00,   # 한국 기준금리 (%)
    "_updated":     "2026-05-23",
}

# ─────────────────────────────────────────────────────────────
# Regime 정의
# ─────────────────────────────────────────────────────────────
# weight_adjustments: 5축(kr_stock/us_stock/us_etf/reit/defensive)
# + etf_category_bonus: 특정 카테고리 가중치 조정 (pick_etfs 정렬에 반영)

REGIME_DEFINITIONS = {
    "RATE_RISING": {
        "label":       "📈 금리상승 국면",
        "description": "금리 상승 사이클. 장기채 손실 위험, 단기채·현금 유리. 리츠 밸류에이션 압박.",
        "weight_adjustments": {
            "defensive": +0.05,   # 단기채(SGOV) 비중 강화
            "reit":      -0.04,   # 리츠 부담 (부채비용 ↑)
            "us_etf":    -0.01,
        },
        "etf_category_bonus": {
            "cash_equivalent": +20,   # SGOV 품질스코어 보너스 → 우선 선택
            "long_bond":       -15,   # TLT 패널티
            "dividend_growth": +5,
        },
        "advisory": (
            "현재 금리 상승 환경입니다. "
            "SGOV(초단기국채) 비중 확대로 무위험 수익 5%+를 확보하고, "
            "장기채(TLT) 비중은 최소화하세요. "
            "리츠는 금리 부담으로 밸류에이션 하락 압박을 받고 있습니다."
        ),
        "usd_krw_note": None,
    },
    "RATE_FALLING": {
        "label":       "📉 금리하락 국면",
        "description": "금리 하락 사이클. 장기채 자본차익 기회, 리츠 강세. 배당주 매력 증가.",
        "weight_adjustments": {
            "reit":      +0.04,   # 리츠 강세
            "defensive": +0.02,   # 장기채 자본차익
            "us_etf":    +0.02,
            "kr_stock":  +0.02,
            "us_stock":  -0.05,  # 성장주 조정
            "defensive": -0.03,   # 현금성 축소 (금리 매력 감소)
        },
        "etf_category_bonus": {
            "long_bond":   +15,   # TLT 매력 ↑
            "reit":        +10,   # 리츠 ETF ↑
            "cash_equivalent": -10,  # SGOV 매력 ↓
        },
        "advisory": (
            "금리 하락 전환 국면입니다. "
            "장기채(TLT) 자본차익 기회를 노리고, "
            "리츠는 금리 하락 수혜로 강세 예상됩니다. "
            "배당주의 상대적 매력도 증가 구간입니다."
        ),
        "usd_krw_note": None,
    },
    "HIGH_VOLATILITY": {
        "label":       "⚡ 고변동성 국면",
        "description": "VIX 25+. 시장 불안. 커버드콜 ETF 유리, 개별주 단기 리스크 높음.",
        "weight_adjustments": {
            "defensive": +0.06,
            "us_stock":  -0.04,
            "kr_stock":  -0.02,
        },
        "etf_category_bonus": {
            "monthly_income": +15,   # JEPI/JEPQ — 변동성에서 커버드콜 프리미엄 ↑
            "cash_equivalent": +10,
            "long_bond":       +8,   # 안전자산
            "dividend_growth": -5,   # 성장형 단기 조정 위험
        },
        "advisory": (
            "VIX 25 이상의 고변동성 국면입니다. "
            "JEPI/JEPQ 커버드콜 ETF는 이 국면에서 옵션 프리미엄이 상승해 배당이 증가합니다. "
            "개별주 비중을 일시적으로 줄이고 방어형 자산으로 대기하는 전략을 권장합니다."
        ),
        "usd_krw_note": None,
    },
    "RECESSION": {
        "label":       "���� 경기침체 경고",
        "description": "경기침체 우려. 고배당 함정 주의, 방어적 업종 집중, 현금 비중 극대화.",
        "weight_adjustments": {
            "defensive": +0.10,
            "reit":      -0.05,   # 상업용 리츠 임대료 리스크
            "us_stock":  -0.03,
            "kr_stock":  -0.02,
        },
        "etf_category_bonus": {
            "cash_equivalent": +20,
            "agg_bond":        +15,
            "tips":            +10,   # 인플레 방어
            "high_yield":      -10,   # 경기침체 시 고배당 함정 ↑
            "monthly_income":  -5,
        },
        "advisory": (
            "경기침체 우려 국면입니다. "
            "고배당 함정 위험이 증가합니다 — 경기민감 섹터의 고배당주는 배당삭감 가능성이 높아집니다. "
            "SGOV·BND 등 안전자산 비중을 높이고, "
            "생활필수재(PG·KO)·방어형 ETF(SCHP) 위주로 재편하는 것을 권장합니다."
        ),
        "usd_krw_note": None,
    },
    "NORMAL": {
        "label":       "🟢 정상 국면",
        "description": "특별한 시장 이벤트 없음. Archetype 기본 비중 유지.",
        "weight_adjustments": {},   # override 없음 — archetype 순수 비중 그대로
        "etf_category_bonus": {},
        "advisory": (
            "현재 시장은 정상 국면입니다. "
            "선택하신 포트폴리오 전략(Archetype)을 그대로 유지하는 것을 권장합니다. "
            "배당삭감 신호가 포착된 종목만 선택적으로 점검하세요."
        ),
        "usd_krw_note": None,
    },
}


# ─────────────────────────────────────────────────────────────
# 시장 지표 캐시 관리
# ─────────────────────────────────────────────────────────────

def _load_macro_config() -> dict:
    """macro_config.json (수동 설정값) 로드."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def _load_macro_cache() -> Optional[dict]:
    """macro_cache.json (yfinance 결과 캐시, TTL 6시간) 로드."""
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        updated = datetime.strptime(data.get("_updated", "2000-01-01T00:00"), "%Y-%m-%dT%H:%M")
        if datetime.now() - updated < timedelta(hours=6):
            return data
    except Exception:
        pass
    return None


def _save_macro_cache(indicators: dict) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "_updated": datetime.now().strftime("%Y-%m-%dT%H:%M"),
                **indicators
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"[macro] 캐시 저장 실패: {e}")


def _fetch_live_indicators() -> Optional[dict]:
    """
    yfinance로 실시간 시장 지표 조회.
    VIX, 미국 10년채, 달러/원 환율.
    실패하면 None 반환 → config 기본값으로 fallback.
    """
    try:
        import yfinance as yf

        # VIX
        vix_val = None
        try:
            vix_info = yf.Ticker("^VIX").fast_info
            vix_val  = float(vix_info.get("last_price") or 0) or None
        except Exception:
            pass

        # 미국 10년 국채 수익률
        tnx_val = None
        try:
            tnx_info = yf.Ticker("^TNX").fast_info
            tnx_val  = float(tnx_info.get("last_price") or 0) or None
        except Exception:
            pass

        # 달러/원 환율
        krw_val = None
        try:
            krw_info = yf.Ticker("KRW=X").fast_info
            krw_val  = float(krw_info.get("last_price") or 0) or None
        except Exception:
            pass

        if not any([vix_val, tnx_val, krw_val]):
            return None

        result = {}
        if vix_val:   result["vix"]          = round(vix_val, 2)
        if tnx_val:   result["us_10y_yield"]  = round(tnx_val, 2)
        if krw_val:   result["usd_krw"]       = round(krw_val, 1)

        log.info(f"[macro] 실시간 지표: VIX={vix_val}, 10Y={tnx_val}, KRW={krw_val}")
        _save_macro_cache(result)
        return result

    except ImportError:
        log.warning("[macro] yfinance 없음")
        return None
    except Exception as e:
        log.warning(f"[macro] 실시간 지표 조회 실패: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 국면 판정 로직
# ─────────────────────────────────────────────────────────────

def _score_regime(
    regime_name: str,
    fed_rate: float,
    us_10y: float,
    vix: float,
    usd_krw: float,
    kr_base_rate: float,
    yield_spread: float,   # us_10y - fed_rate
) -> tuple[float, dict]:
    """
    특정 Regime을 지지하는 지표 강도를 0~1로 스코어링.

    반환: (confidence_0_to_1, indicator_breakdown_dict)
    각 지표마다 [0, 0.5, 1.0] 의 지지 강도 부여:
      - 1.0: 강하게 지지
      - 0.5: 약하게/부분적으로 지지
      - 0.0: 지지하지 않음 or 반증
    """
    breakdown: dict[str, float] = {}

    if regime_name == "RATE_RISING":
        # 지지 조건: 높은 Fed rate, 높은 10Y, 일드커브 정상, VIX 안정
        breakdown["fed_rate"]     = 1.0 if fed_rate >= 4.5 else (0.5 if fed_rate >= 3.5 else 0.0)
        breakdown["us_10y"]       = 1.0 if us_10y >= 4.2  else (0.5 if us_10y >= 3.5  else 0.0)
        breakdown["yield_spread"] = 1.0 if yield_spread >= -0.2 else (0.5 if yield_spread >= -0.5 else 0.0)
        breakdown["vix"]          = 1.0 if vix < 20 else (0.5 if vix < 28 else 0.0)
        breakdown["kr_rate"]      = 1.0 if kr_base_rate >= 3.0 else (0.5 if kr_base_rate >= 2.0 else 0.0)

    elif regime_name == "RATE_FALLING":
        breakdown["fed_rate"]     = 1.0 if fed_rate <= 2.5 else (0.5 if fed_rate <= 3.5 else 0.0)
        breakdown["us_10y"]       = 1.0 if us_10y <= 3.0  else (0.5 if us_10y <= 3.8  else 0.0)
        breakdown["yield_spread"] = 1.0 if yield_spread >= 0.3 else (0.5 if yield_spread >= 0.0 else 0.0)
        breakdown["vix"]          = 1.0 if vix < 20 else (0.5 if vix < 28 else 0.0)
        breakdown["kr_rate"]      = 1.0 if kr_base_rate <= 2.0 else (0.5 if kr_base_rate <= 3.0 else 0.0)

    elif regime_name == "HIGH_VOLATILITY":
        breakdown["vix"]          = 1.0 if vix >= 30 else (0.7 if vix >= 25 else (0.3 if vix >= 20 else 0.0))
        breakdown["fed_rate"]     = 0.5  # 금리는 변동성과 직접 연관 약함 — 중립
        breakdown["us_10y"]       = 0.5 if us_10y >= 3.5 else 0.5  # 중립
        breakdown["yield_spread"] = 0.5 if yield_spread < 0 else 0.3
        breakdown["kr_rate"]      = 0.5

    elif regime_name == "RECESSION":
        # 지지 조건: 인버티드 커브, VIX 상승, 높은 Fed rate vs 낮은 10Y
        breakdown["yield_spread"] = 1.0 if yield_spread <= -0.5 else (0.7 if yield_spread <= -0.2 else 0.0)
        breakdown["vix"]          = 1.0 if vix >= 25 else (0.5 if vix >= 18 else 0.0)
        breakdown["fed_rate"]     = 1.0 if fed_rate >= 4.0 else (0.5 if fed_rate >= 2.5 else 0.0)
        breakdown["us_10y"]       = 1.0 if us_10y <= (fed_rate - 0.3) else 0.0
        breakdown["kr_rate"]      = 0.5  # 중립

    elif regime_name == "NORMAL":
        # 정상 = 모든 지표가 "정상 범위" 안에 있어야 함
        # 범위 벗어나면 페널티 (0.5 아니라 0.2) → NORMAL이 이상 국면과 공동 1위 방지
        breakdown["vix"]          = 1.0 if 12 <= vix <= 22 else (0.3 if vix < 28 else 0.0)
        breakdown["fed_rate"]     = 1.0 if 2.0 <= fed_rate <= 4.0 else (0.2 if fed_rate <= 5.0 else 0.0)
        breakdown["us_10y"]       = 1.0 if 2.0 <= us_10y <= 4.0  else (0.2 if us_10y <= 5.0 else 0.0)
        breakdown["yield_spread"] = 1.0 if 0.1 <= yield_spread <= 1.5 else (0.2 if yield_spread >= -0.2 else 0.0)
        breakdown["kr_rate"]      = 1.0 if 1.5 <= kr_base_rate <= 3.5 else (0.3 if kr_base_rate <= 4.5 else 0.0)

    confidence = round(sum(breakdown.values()) / len(breakdown), 3)
    return confidence, breakdown


def _detect_regime(
    fed_rate:     float,
    us_10y:       float,
    vix:          float,
    usd_krw:      float,
    kr_base_rate: float,
) -> tuple[str, float, dict, dict]:
    """
    지표별 Regime 지지 강도 투표 방식으로 국면 판정.

    Level 2 업그레이드:
      - 단순 if/elif 대신 5개 지표가 각 regime을 독립 채점
      - 최고 confidence 국면이 채택
      - confidence < 0.65면 "혼�� 국면" 경고
      - runner_up (2위 regime)도 반환

    반환: (regime_name, confidence, signals, indicator_scores)
    """
    import math

    signals: dict[str, str] = {}
    yield_spread = round(us_10y - fed_rate, 3)   # 장단기 스프레드

    # 환율 주석
    if usd_krw >= 1400:
        signals["usd_krw_warn"] = (
            f"달러 강세 ({usd_krw:.0f}원). "
            "미국 자산 신규 매수 비용 증가. 기존 보유 자산은 원화 환산 가치 상승."
        )
    elif usd_krw <= 1150:
        signals["usd_krw_note"] = (
            f"원화 강세 ({usd_krw:.0f}원). "
            "달러 환전·미국 자산 신규 매수에 유리한 시점."
        )

    # 모든 Regime에 대해 confidence 스코어 계산
    all_regimes = ["RATE_RISING", "RATE_FALLING", "HIGH_VOLATILITY", "RECESSION", "NORMAL"]
    scores: dict[str, float] = {}
    breakdowns: dict[str, dict] = {}

    for r in all_regimes:
        conf, bd = _score_regime(r, fed_rate, us_10y, vix, usd_krw, kr_base_rate, yield_spread)
        scores[r]     = conf
        breakdowns[r] = bd

    # 1위, 2위 regime
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_regime, top_conf   = ranked[0]
    runner_up, runner_conf = ranked[1]

    # 혼재 국면 감지: 1위 confidence가 낮거나 1/2위 격차가 좁은 경우
    gap = top_conf - runner_conf
    if top_conf < 0.60 or gap < 0.10:
        signals["mixed_regime"] = (
            f"시장 신호가 혼재됩니다 ({top_regime} {top_conf:.0%} vs {runner_up} {runner_conf:.0%}). "
            "단정적 판단보다 분산 전략을 유지하세요."
        )

    return top_regime, round(top_conf, 3), signals, {
        "scores":       {k: round(v, 3) for k, v in scores.items()},
        "breakdowns":   breakdowns,
        "yield_spread": yield_spread,
        "runner_up":    runner_up,
        "runner_up_conf": round(runner_conf, 3),
    }


# ─────────────────────────────────────────────────────────────
# 메인 함수
# ─────────────────────────────────────────────────────────────

def get_macro_regime(force_refresh: bool = False) -> dict:
    """
    현재 시장 국면(Macro Regime) 반환.

    반환:
    {
        "regime":            str,         # RATE_RISING | RATE_FALLING | HIGH_VOLATILITY | RECESSION | NORMAL
        "label":             str,         # 사람이 읽기 쉬운 레이블
        "description":       str,         # 국면 설명
        "advisory":          str,         # 투자자에게 전달할 조언
        "weight_adjustments": dict,       # 5축 비중 delta
        "etf_category_bonus": dict,       # ETF 카테고리별 품질스코어 보너스
        "indicators": {                   # 판정에 사용된 지표값
            "fed_rate", "us_10y_yield", "vix", "usd_krw", "kr_base_rate"
        },
        "signals":           dict,        # 환율 경고 등 부가 신호
        "data_source":       str,         # "live" | "cache" | "config"
        "updated_at":        str,
    }
    """
    # ── 지표 로드 우선순위 ─────────────────────────────────────
    # 1. yfinance 실시간 (force_refresh 또는 캐시 만료 시)
    # 2. 디스크 캐시 (6시간 이내)
    # 3. macro_config.json (수동 설정)

    config     = _load_macro_config()
    indicators = dict(config)  # config를 기본값으로
    source     = "config"

    # 캐시 또는 실시간 오버라이드
    if not force_refresh:
        cached = _load_macro_cache()
        if cached:
            indicators.update({k: v for k, v in cached.items() if not k.startswith("_")})
            source = "cache"

    if force_refresh or source == "config":
        live = _fetch_live_indicators()
        if live:
            indicators.update(live)
            source = "live"

    # 지표 추출
    fed_rate     = float(indicators.get("fed_rate",     4.75))
    us_10y       = float(indicators.get("us_10y_yield", 4.40))
    vix          = float(indicators.get("vix",          18.0))
    usd_krw      = float(indicators.get("usd_krw",      1350.0))
    kr_base_rate = float(indicators.get("kr_base_rate", 3.00))

    # 국면 판정 — Level 2: confidence 점수 + runner_up 포함
    regime_name, confidence, signals, indicator_meta = _detect_regime(
        fed_rate, us_10y, vix, usd_krw, kr_base_rate
    )
    regime_def = REGIME_DEFINITIONS[regime_name]

    # 환율 주석을 regime_def에 병합
    regime_result = dict(regime_def)
    usd_note = signals.get("usd_krw_warn") or signals.get("usd_krw_note")
    if usd_note:
        regime_result["usd_krw_note"] = usd_note

    # confidence 등급 레이블
    if confidence >= 0.80:
        conf_label = "🟢 확신 (High)"
    elif confidence >= 0.65:
        conf_label = "🟡 보통 (Medium)"
    else:
        conf_label = "🔴 혼재 (Low — mixed signals)"

    return {
        "regime":             regime_name,
        "label":              regime_result["label"],
        "description":        regime_result["description"],
        "advisory":           regime_result["advisory"],
        "weight_adjustments": regime_result["weight_adjustments"],
        "etf_category_bonus": regime_result["etf_category_bonus"],
        "usd_krw_note":       regime_result.get("usd_krw_note"),
        # ── Level 2 추가 필드 ──────────────────────────────────
        "confidence":         confidence,           # 0.0 ~ 1.0
        "confidence_label":   conf_label,
        "runner_up":          indicator_meta["runner_up"],
        "runner_up_conf":     indicator_meta["runner_up_conf"],
        "regime_scores":      indicator_meta["scores"],       # 5개 regime 각각의 confidence
        "indicator_breakdown": indicator_meta["breakdowns"][regime_name],  # 채택된 regime의 지표 기여도
        "yield_spread":       indicator_meta["yield_spread"],
        # ──────────────────────────────────────────────────────
        "indicators": {
            "fed_rate":     fed_rate,
            "us_10y_yield": us_10y,
            "vix":          vix,
            "usd_krw":      usd_krw,
            "kr_base_rate": kr_base_rate,
            "yield_spread": indicator_meta["yield_spread"],
        },
        "signals":    signals,
        "data_source": source,
        "updated_at":  datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def apply_macro_to_weights(axis_w: dict, regime: dict) -> dict:
    """
    Macro Regime의 weight_adjustments를 5축 비중에 적용.

    get_axis_weights() → apply_archetype_weights() → apply_macro_to_weights()
    순서로 호출. 음수 방지 + 합계 1.0 정규화.
    """
    adjustments = regime.get("weight_adjustments", {})
    if not adjustments:
        return axis_w

    adjusted = dict(axis_w)
    for k, delta in adjustments.items():
        adjusted[k] = max(0.0, adjusted.get(k, 0.0) + delta)

    # 정규화
    total = sum(adjusted.values()) or 1.0
    return {k: round(v / total, 3) for k, v in adjusted.items()}


def apply_macro_to_etf_scores(
    universe: list[dict],
    regime: dict,
) -> list[dict]:
    """
    ETF 유니버스의 etf_quality_score에 Macro Regime 보너스 적용.
    pick_etfs()의 _sort_key가 이 값을 사용하므로 자동으로 우선순위 변경.

    원본 리스트를 수정하지 않고 복사본 반환.
    """
    bonuses = regime.get("etf_category_bonus", {})
    if not bonuses:
        return universe

    result = []
    for item in universe:
        entry = dict(item)
        cat   = entry.get("etf_category", "")
        bonus = bonuses.get(cat, 0)
        if bonus != 0:
            base_score = entry.get("etf_quality_score", 70.0)
            entry["etf_quality_score"] = max(0.0, min(100.0, base_score + bonus))
        result.append(entry)

    return result

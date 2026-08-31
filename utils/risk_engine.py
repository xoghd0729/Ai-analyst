"""
risk_engine.py  v1
==================
KR / US / ETF 자산별 위험 점수를 통합해 단일 composite_risk_score를 산출.

Layer 1 (현재 상태): XGBoost ml_status   — INTACT/WEAKENING/BROKEN
Layer 2 (시간 위험):  Survival hazard     — 0.0~1.0 (uncalibrated risk score)
Layer 3 (시장 환경):  Macro regime        — BULLISH/NEUTRAL/BEARISH

composite_risk_score: 0~100 (높을수록 위험)
risk_gate: PASS(<50) / WARN(50~74) / BLOCK(>=75)
"""
from __future__ import annotations
import os, json, logging
from functools import lru_cache

log = logging.getLogger(__name__)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ──────────────────────────────────────────────
# 가중치: 실험 근거 (risk_ensemble_comparison.py, walk-forward 2019-2024)
#
# 실험 결과 요약:
#   XGB 단독:              ROC 0.7803, P@20 0.9420
#   XGB+Surv 70/30:        ROC 0.7824, P@20 0.9509  ← 최적
#   XGB+Surv+Macro 70/20/10: ROC 0.7727              ← Macro 추가 시 저하
#   LR Meta Model:         ROC 0.7831 (OOF 1123개, 차이 미미)
#
# 결론:
#   - Survival hazard는 현재연도 위험 예측에 직접 사용 부적합 (단독 ROC 0.51)
#     → Survival의 역할은 "시간축(언제 위험해지는가)", XGB는 "현재 상태"
#   - Macro는 composite score에 포함 시 노이즈 (성능 저하)
#     → Macro는 ETF 선호도/비중 조정에만 사용 (risk_engine 제외)
#   - Rank Aggregation은 확률값 정보 손실로 최악 (ROC 0.7609)
# ──────────────────────────────────────────────
_W_XGB      = 0.70   # Layer 1 (dominant: 데이터로 검증)
_W_SURVIVAL = 0.30   # Layer 2 (P@20 보완)
_W_MACRO    = 0.00   # Layer 3 (composite에서 제외 — 성능 저하 확인)

# ML Status → risk score 변환
_ML_SCORE = {
    "INTACT":    15.0,
    "WEAKENING": 55.0,
    "BROKEN":    90.0,
}

# Macro regime → risk adder
_MACRO_ADDER = {
    "BULLISH": -5.0,
    "NEUTRAL":  0.0,
    "BEARISH": +15.0,
}

# risk_gate 경계
_GATE_WARN  = 50.0
_GATE_BLOCK = 75.0

# 성향별 BLOCK 임계값 오버라이드
_GATE_BY_RISK = {
    "conservative": 50.0,   # 더 엄격
    "moderate":     65.0,
    "aggressive":   75.0,
}


@lru_cache(maxsize=1)
def _load_survival_data() -> dict:
    path = os.path.join(BASE, "results", "survival_pd_v4.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f).get("stock_risk", {})
    except Exception as e:
        log.warning("survival_pd_v4.json 로드 실패: %s", e)
        return {}


def _hazard_to_score(hazard: float | None) -> float:
    """Survival hazard(0~1) → risk score(0~100)."""
    if hazard is None:
        return 50.0   # 데이터 없음 → 중간값
    return round(min(100.0, hazard * 100.0), 1)


def _macro_regime(macro: dict | None) -> str:
    """macro dict에서 regime 문자열 추출."""
    if not macro:
        return "NEUTRAL"
    regime = str(macro.get("regime") or macro.get("label") or "NEUTRAL").upper()
    if "BULL" in regime or "EXPANSION" in regime:
        return "BULLISH"
    if "BEAR" in regime or "RECESSION" in regime or "CONTRACTION" in regime:
        return "BEARISH"
    return "NEUTRAL"


def score_asset(
    ticker: str,
    asset_class: str,               # "kr_stock" / "us_stock" / "us_etf" / "kr_reit" 등
    ml_status: str = "INTACT",      # XGBoost 예측 (KR) or safety tier (US)
    survival_hazard: float | None = None,   # 직접 전달 시 (없으면 JSON에서 조회)
    macro: dict | None = None,
    risk_tolerance: str = "moderate",
) -> dict:
    """
    단일 자산의 composite_risk_score 계산.

    Returns:
        {
            composite_risk_score: float,   # 0~100
            risk_gate: str,                # PASS / WARN / BLOCK
            layer1_xgb: float,
            layer2_survival: float,
            layer3_macro: float,
            hazard: float | None,
        }
    """
    is_etf = "etf" in asset_class.lower() or asset_class in ("us_div_etf", "defensive")

    # ── Layer 1: XGBoost / 안전성 점수 ──────────────────────
    xgb_score = _ML_SCORE.get(ml_status.upper(), _ML_SCORE["WEAKENING"])

    # ── Layer 2: Survival hazard ─────────────────────────────
    if is_etf:
        # ETF는 Survival 모델 미적용 → 낮은 위험값 고정
        hazard = 0.2
    elif survival_hazard is not None:
        hazard = float(survival_hazard)
    elif asset_class == "kr_stock":
        sv = _load_survival_data()
        hazard = float(sv.get(ticker, {}).get("hazard_pct", 0.5))
    else:
        # US 주식: 안전성 tier로 대리 측정
        _tier_map = {"INTACT": 0.2, "WEAKENING": 0.5, "BROKEN": 0.8}
        hazard = _tier_map.get(ml_status.upper(), 0.5)
    surv_score = _hazard_to_score(hazard)

    # ── Layer 3: Macro (composite score에서 제외, context 전달만) ──
    # 실험 결과: Macro 추가 시 ROC 0.7824→0.7727 저하
    # Macro는 ETF 선호도/비중 조정(AxisWeightFilter)에서만 사용
    regime = _macro_regime(macro)
    macro_adder = 0.0   # _W_MACRO = 0.0

    # ── 복합 점수 계산 ────────────────────────────────────────
    raw = (xgb_score * _W_XGB) + (surv_score * _W_SURVIVAL) + macro_adder
    composite = round(max(0.0, min(100.0, raw)), 1)

    # ── Risk Gate ─────────────────────────────────────────────
    block_threshold = _GATE_BY_RISK.get(risk_tolerance, _GATE_BLOCK)
    if composite >= block_threshold:
        gate = "BLOCK"
    elif composite >= _GATE_WARN:
        gate = "WARN"
    else:
        gate = "PASS"

    return {
        "composite_risk_score": composite,
        "risk_gate":            gate,
        "layer1_xgb":           round(xgb_score, 1),
        "layer2_survival":      round(surv_score, 1),
        "layer3_macro":         round(macro_adder, 1),
        "hazard":               round(hazard, 4),
        "macro_regime":         regime,
    }


def score_portfolio(
    recommendations: list[dict],
    macro: dict | None = None,
    risk_tolerance: str = "moderate",
) -> list[dict]:
    """
    포트폴리오 전체에 composite_risk_score 부착.
    기존 recommendations 리스트를 수정하지 않고 복사본 반환.
    """
    result = []
    for rec in recommendations:
        rec = dict(rec)   # shallow copy
        ticker      = str(rec.get("ticker") or rec.get("stock_code", ""))
        asset_class = str(rec.get("asset_class", "kr_stock"))
        ml_status   = str(rec.get("ml_status", "INTACT"))
        survival_hz = rec.get("survival_risk_score")   # SurvivalWeightFilter가 붙인 값

        risk_result = score_asset(
            ticker        = ticker,
            asset_class   = asset_class,
            ml_status     = ml_status,
            survival_hazard = survival_hz,
            macro         = macro,
            risk_tolerance = risk_tolerance,
        )
        rec.update(risk_result)
        result.append(rec)
    return result


# ── CLI 테스트 ────────────────────────────────────────────────
if __name__ == "__main__":
    import sys; sys.path.insert(0, BASE)
    test_cases = [
        ("005930", "kr_stock",  "INTACT",    0.25, "BULLISH",  "moderate"),
        ("035420", "kr_stock",  "WEAKENING", 0.55, "BEARISH",  "conservative"),
        ("KO",     "us_stock",  "WEAKENING", None, "NEUTRAL",  "moderate"),
        ("SCHD",   "us_div_etf","INTACT",    None, "NEUTRAL",  "conservative"),
        ("009150", "kr_stock",  "BROKEN",    0.80, "BEARISH",  "aggressive"),
    ]
    print(f"{'Ticker':10} {'Class':12} {'ML':10} {'Gate':6} {'Score':7} {'H':6} {'Regime':8}")
    print("-"*65)
    for t, ac, ml, hz, reg, risk in test_cases:
        macro_dict = {"regime": reg}
        r = score_asset(t, ac, ml, hz, macro_dict, risk)
        print(f"{t:10} {ac:12} {ml:10} {r['risk_gate']:6} {r['composite_risk_score']:7.1f}"
              f" {r['hazard']:6.2f} {r['macro_regime']:8}")

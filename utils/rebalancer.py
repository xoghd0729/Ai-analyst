"""
rebalancer.py — 동적 리밸런싱 제안 엔진

왜 필요한가?
  포트폴리오는 시장이 움직이면 비중이 틀어진다.
  리츠가 폭락하면 리츠 비중이 줄고, 채권이 오르면 채권 비중이 늘어난다.
  이 모듈은 "지금 포트폴리오를 어떻게 바꿔야 하는가"를 3가지 관점에서 제안한다:

  1. 비중 이탈 감지 (Drift 리밸런싱)
     목표 비중 대비 ±5%p 이상 이탈한 자산 감지 → 매수/매도 제안

  2. 매크로 기반 전술적 조정 (Tactical Rebalancing)
     현재 시장 국면(Macro Regime)에 맞게 비중 조정 제안
     예: RATE_RISING → SGOV ↑, TLT ↓

  3. 신호 기반 교체 (Signal-based Swap)
     배당삭감 신호(BROKEN/WEAKENING), Yield Trap(DANGER) 자산 교체 제안

사용 예:
    from utils.rebalancer import generate_rebalancing_plan
    plan = generate_rebalancing_plan(
        current_recs=recommendations,
        target_axis_w=axis_w,
        macro_regime=macro,
        investable_amount=5000,
    )
"""

from __future__ import annotations
from typing import Optional

# ── 임계값 설정 ───────────────────────────────────────────────────
DRIFT_THRESHOLD_PCT  = 5.0   # 이탈 감지 임계값 (비중 %p)
REBAL_BAND_PCT       = 3.0   # 리밸런싱 실행 밴드 (이보다 작으면 무시)
MAX_SUGGESTIONS      = 6     # 최대 제안 항목 수

# ── 매크로 국면별 권장 비중 조정 ─────────────────────────────────
MACRO_TACTICAL_SHIFTS: dict[str, dict] = {
    "RATE_RISING": {
        "message": "📈 금리상승 국면 — 단기채·현금성 비중 확대, 장기채·리츠 축소",
        "increase": ["cash_equivalent", "tips"],
        "decrease": ["long_bond", "reit"],
        "swap_suggestions": [
            {"from_cat": "long_bond",  "to_cat": "cash_equivalent", "reason": "TLT → SGOV: 금리 상승 시 장기채 손실 회피"},
            {"from_cat": "reit",       "to_cat": "dividend_growth", "reason": "리츠 → SCHD: 금리 상승 압박 회피"},
        ],
    },
    "RATE_FALLING": {
        "message": "📉 금리하락 국면 — 장기채·리츠 비중 확대, 단기채 축소",
        "increase": ["long_bond", "reit", "dividend_growth"],
        "decrease": ["cash_equivalent"],
        "swap_suggestions": [
            {"from_cat": "cash_equivalent", "to_cat": "long_bond", "reason": "SGOV → TLT: 금리 하락 시 장기채 가격 상승 수혜"},
            {"from_cat": "cash_equivalent", "to_cat": "reit",      "reason": "SGOV → VNQ: 금리 하락 시 리츠 배당 매력 증가"},
        ],
    },
    "HIGH_VOLATILITY": {
        "message": "⚡ 고변동성 국면 — 월배당·현금성 확대, 고배당 단일주 축소",
        "increase": ["monthly_income", "cash_equivalent", "agg_bond"],
        "decrease": ["high_yield"],
        "swap_suggestions": [
            {"from_cat": "high_yield", "to_cat": "monthly_income", "reason": "고배당주 → JEPI: 변동성 높을 때 커버드콜 프리미엄 극대화"},
            {"from_cat": "high_yield", "to_cat": "cash_equivalent","reason": "고배당주 → SGOV: 안전자산으로 일시 대피"},
        ],
    },
    "RECESSION": {
        "message": "��� 경기침체 국면 — 현금성·채권 강화, 리츠·고배당 축소",
        "increase": ["cash_equivalent", "agg_bond", "dividend_growth"],
        "decrease": ["reit", "high_yield", "monthly_income"],
        "swap_suggestions": [
            {"from_cat": "high_yield",      "to_cat": "cash_equivalent",  "reason": "고배당 → SGOV: 침체 시 배당삭감 위험 회피"},
            {"from_cat": "reit",            "to_cat": "dividend_growth",   "reason": "리츠 → SCHD: 침체 내성 우량 배당성장으로 교체"},
            {"from_cat": "monthly_income",  "to_cat": "agg_bond",          "reason": "커버드콜 → BND: 침체 시 커버드콜 프리미엄 급감"},
        ],
    },
    "NORMAL": {
        "message": "✅ 정상 국면 — 목표 비중 유지, 정기 드리프트 점검 권장",
        "increase": [],
        "decrease": [],
        "swap_suggestions": [],
    },
}


# ── 핵심 함수 ─────────────────────────────────────────────────────
def generate_rebalancing_plan(
    current_recs: list[dict],
    target_axis_w: dict,
    macro_regime: Optional[dict] = None,
    investable_amount: float = 5000.0,
) -> dict:
    """
    3가지 관점에서 리밸런싱 제안 생성.

    Args:
        current_recs:     현재 포트폴리오 (weight_pct, asset_class, etf_category 포함)
        target_axis_w:    목표 5축 비중 (macro 반영 후 final axis_w)
        macro_regime:     get_macro_regime() 반환값
        investable_amount: 총 투자금 (만원)

    반환:
    {
        "drift_alerts":   [...],   # 비중 이탈 자산
        "tactical_shifts":[...],   # 매크로 기반 조정
        "signal_swaps":   [...],   # 신호 기반 교체
        "summary": {
            "total_actions": int,
            "urgency":       str,   # "긴급" / "권장" / "정기"
            "next_rebal_date": str,
        },
        "macro_message": str,
    }
    """
    regime = (macro_regime or {}).get("regime", "NORMAL")
    total_w = sum(r.get("weight_pct", 0) for r in current_recs) or 100.0

    # ── 1. 현재 자산군별 실제 비중 집계 ─────────────────────────
    current_axis: dict[str, float] = {}
    for r in current_recs:
        cls = r.get("asset_class", "other")
        current_axis[cls] = current_axis.get(cls, 0.0) + r.get("weight_pct", 0) / total_w

    # ── 2. Drift 감지 ─────────────────────────────────────────────
    drift_alerts = []
    # asset_class → axis key 매핑
    axis_map = {
        "kr_stock":  "kr_stock",
        "us_stock":  "us_stock",
        "us_div_etf":"us_etf",
        "kr_etf":    "kr_stock",   # 한국 ETF는 kr_stock 축으로 합산
        "us_reit":   "reit",
        "kr_reit":   "reit",
        "defensive": "defensive",
    }
    for cls, target_key in axis_map.items():
        current_pct = current_axis.get(cls, 0.0) * 100
        target_pct  = target_axis_w.get(target_key, 0.0) * 100
        drift       = current_pct - target_pct

        if abs(drift) >= DRIFT_THRESHOLD_PCT:
            action = "매도 축소" if drift > 0 else "매수 확대"
            amount = round(abs(drift) / 100 * investable_amount, 0)
            drift_alerts.append({
                "asset_class":    cls,
                "current_pct":    round(current_pct, 1),
                "target_pct":     round(target_pct, 1),
                "drift_pct":      round(drift, 1),
                "action":         action,
                "amount_만원":    amount,
                "message":        f"{cls} 비중 {current_pct:.1f}% → 목표 {target_pct:.1f}% ({drift:+.1f}%p 이탈) — {action} {amount:.0f}만원",
            })

    # ── 3. 매크로 기반 전술적 조정 ───────────────────────────────
    macro_config = MACRO_TACTICAL_SHIFTS.get(regime, MACRO_TACTICAL_SHIFTS["NORMAL"])

    # 현재 포트폴리오의 etf_category 비중 집계
    cat_weights: dict[str, float] = {}
    for r in current_recs:
        cat = r.get("etf_category", "")
        if cat:
            cat_weights[cat] = cat_weights.get(cat, 0.0) + r.get("weight_pct", 0)

    tactical_shifts = []
    for swap in macro_config.get("swap_suggestions", []):
        from_cat = swap["from_cat"]
        to_cat   = swap["to_cat"]
        from_w   = cat_weights.get(from_cat, 0)
        if from_w > 3:  # 3% 이상 보유 시에만 제안
            shift_amt = round(from_w * 0.4 * investable_amount / 100, 0)  # 40% 이전 제안
            tactical_shifts.append({
                "from_category": from_cat,
                "to_category":   to_cat,
                "from_weight_pct": round(from_w, 1),
                "suggested_shift_만원": shift_amt,
                "reason":        swap["reason"],
                "urgency":       "권장" if regime != "RECESSION" else "긴급",
            })

    # ── 4. 신호 기반 교체 ─────────────────────────────────────────
    signal_swaps = []
    for r in current_recs:
        ticker    = r.get("ticker", "")
        ml_status = r.get("ml_status", "INTACT")
        trap      = r.get("trap_level", "SAFE")
        weight    = r.get("weight_pct", 0)
        cls       = r.get("asset_class", "")
        cat       = r.get("etf_category", "")

        if ml_status == "BROKEN" and weight > 2:
            signal_swaps.append({
                "ticker":   ticker,
                "signal":   "🔴 BROKEN",
                "weight_pct": weight,
                "action":   "즉시 매도",
                "reason":   f"{ticker}: 배당 붕괴 신호 — 즉시 매도 후 동일 섹터 ETF 대체 권장",
                "urgency":  "긴급",
            })
        elif ml_status == "WEAKENING" and weight > 5:
            signal_swaps.append({
                "ticker":   ticker,
                "signal":   "🟠 WEAKENING",
                "weight_pct": weight,
                "action":   "비중 축소",
                "reason":   f"{ticker}: 배당 약화 신호 — 비중 절반으로 축소하고 관찰 유지",
                "urgency":  "권장",
            })
        elif trap == "DANGER" and weight > 3:
            signal_swaps.append({
                "ticker":   ticker,
                "signal":   "🚨 YIELD_TRAP",
                "weight_pct": weight,
                "action":   "교체 검토",
                "reason":   f"{ticker}: Yield Trap 위험 — 고수익률이 주가 하락 반영일 수 있음. 교체 검토",
                "urgency":  "권장",
            })

    # ── 5. 종합 요약 ──────────────────────────────────────────────
    urgent_count  = sum(1 for s in signal_swaps if s.get("urgency") == "긴급")
    total_actions = len(drift_alerts) + len(tactical_shifts) + len(signal_swaps)

    if urgent_count > 0:
        urgency = "긴급"
    elif total_actions > 3:
        urgency = "권장"
    else:
        urgency = "정기"

    from datetime import datetime, timedelta
    today = datetime.now()
    if urgency == "긴급":
        next_date = today.strftime("%Y-%m-%d")   # 즉시
    elif urgency == "권장":
        next_date = (today + timedelta(days=30)).strftime("%Y-%m-%d")
    else:
        next_date = (today + timedelta(days=90)).strftime("%Y-%m-%d")

    return {
        "drift_alerts":    drift_alerts[:MAX_SUGGESTIONS],
        "tactical_shifts": tactical_shifts[:MAX_SUGGESTIONS],
        "signal_swaps":    signal_swaps[:MAX_SUGGESTIONS],
        "summary": {
            "total_actions":   total_actions,
            "urgent_count":    urgent_count,
            "urgency":         urgency,
            "next_rebal_date": next_date,
            "regime":          regime,
        },
        "macro_message": macro_config["message"],
    }

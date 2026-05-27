"""
utils/ai_advisor.py — AI 포트폴리오 어드바이저 (자연어 Q&A 엔진)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  24개의 분석 키를 반환해도 투자자는 여전히 묻는다:
  "그래서 지금 뭘 사야 해?", "세금 얼마나 내?", "FIRE 언제 돼?"
  이 모듈은 자연어 질문을 의도(intent)로 파싱하고,
  포트폴리오 데이터에서 정확한 수치를 꺼내 PB 어조로 즉답한다.

  LLM 없이 동작하는 규칙 기반 라우터 + 템플릿 엔진.
  (ollama 연결 시 답변 품질 강화 옵션 제공)

지원 의도(14가지):
  current_income     — 지금 배당 얼마야?
  target_gap         — 목표 달성 얼마나 남았어?
  fire_status        — FIRE 언제 가능해?
  worst_risk         — 가장 위험한 종목/시나리오?
  tax_impact         — 세금 얼마나 내?
  inflation_defense  — 인플레이션 이기나?
  rebalance_action   — 지금 뭘 사고 팔아야 해?
  behavioral_check   — 내 투자 심리 괜찮아?
  bank_comparison    — 은행 예금이랑 비교하면?
  future_projection  — N년 후 배당은?
  isa_pension        — ISA/연금저축 어떻게 해?
  health_score       — 포트폴리오 건강해?
  add_investment     — 얼마 더 투자해야 해?
  macro_impact       — 지금 시장 국면은?

반환:
{
    "intent":         str,
    "intent_label":   str,
    "confidence":     float,   # 0~1 (의도 탐지 신뢰도)
    "headline":       str,     # 핵심 답변 한 줄
    "answer":         str,     # 상세 답변
    "data_points":    list[dict],  # 근거 수치 [{label, value, unit}]
    "action":         str,     # 권고 행동
    "follow_up":      list[str],   # 후속 추천 질문 2~3개
}
"""

from __future__ import annotations
import re

# ── 의도별 한국어 레이블 ─────────────────────────────────────────────────────
_INTENT_LABELS = {
    "current_income":    "현재 배당 수입",
    "target_gap":        "목표 달성 현황",
    "fire_status":       "FIRE 달성 시뮬레이션",
    "worst_risk":        "최대 리스크 진단",
    "tax_impact":        "세금 영향 분석",
    "inflation_defense": "인플레이션 방어력",
    "rebalance_action":  "리밸런싱 액션",
    "behavioral_check":  "행동 편향 진단",
    "bank_comparison":   "은행 금리 비교",
    "future_projection": "미래 배당 예측",
    "isa_pension":       "ISA·연금저축 전략",
    "health_score":      "포트폴리오 건강도",
    "add_investment":    "추가 투자 계산",
    "macro_impact":      "매크로 시장 진단",
    "unknown":           "기타 문의",
}

# ── 의도 탐지 키워드 맵 ──────────────────────────────────────────────────────
_INTENT_KEYWORDS: dict[str, list[str]] = {
    "current_income":    ["배당 얼마", "월 배당", "월배당", "지금 배당", "현재 배당",
                          "얼마 받", "입금", "수익 얼마", "세후 배당", "연간 배당"],
    "target_gap":        ["목표", "달성", "얼마나 남", "언제 달성", "목표까지", "부족",
                          "몇 만원 더", "목표 배당"],
    "fire_status":       ["파이어", "fire", "은퇴", "경제적 자유", "몇 살", "언제 은퇴",
                          "파이어 가능", "은퇴 가능", "조기 은퇴"],
    "worst_risk":        ["위험", "리스크", "위기", "최악", "손실", "위험한 종목",
                          "배당컷", "붕괴", "폭락", "스트레스", "얼마나 잃"],
    "tax_impact":        ["세금", "세후", "과세", "종합과세", "얼마 내야", "세율",
                          "절세", "원천징수", "금융소득", "세금 얼마"],
    "inflation_defense": ["인플레이션", "물가", "실질", "구매력", "인플레", "물가 상승",
                          "이길", "방어"],
    "rebalance_action":  ["팔아야", "사야", "리밸런싱", "교체", "비중", "어떤 종목",
                          "조정", "매도", "매수", "바꿔야"],
    "behavioral_check":  ["편향", "심리", "행동", "습관", "실수", "내 투자 성향",
                          "괜찮아", "문제없어", "잘 하고 있"],
    "bank_comparison":   ["은행", "예금", "예적금", "적금", "금리 비교", "은행이랑",
                          "정기예금", "vs 은행"],
    "future_projection": ["년 후", "미래", "나중에", "10년", "20년", "앞으로",
                          "성장하면", "커지면", "복리"],
    "isa_pension":       ["isa", "연금저축", "irp", "이사", "연금", "개인형", "세액공제",
                          "절세 계좌"],
    "health_score":      ["건강", "점수", "등급", "몇 점", "상태", "괜찮은지",
                          "잘 구성", "안전한지", "좋은 포트폴리오"],
    "add_investment":    ["추가 투자", "더 넣", "얼마 더", "투자 얼마", "추가로",
                          "증액", "더 사면", "납입"],
    "macro_impact":      ["시장", "국면", "매크로", "금리", "환율", "경기", "지금 시장",
                          "요즘 시장", "상황"],
}

# ── 후속 질문 추천 맵 ────────────────────────────────────────────────────────
_FOLLOW_UPS: dict[str, list[str]] = {
    "current_income":    ["목표 배당까지 얼마나 남았어?", "인플레이션 이기고 있어?", "20년 후 배당은 얼마야?"],
    "target_gap":        ["얼마 더 투자하면 목표 달성해?", "FIRE는 언제 가능해?", "지금 가장 위험한 종목은?"],
    "fire_status":       ["린 파이어 달성하려면 얼마 더 저축해야 해?", "세금 얼마나 내야 해?", "ISA 어떻게 써야 해?"],
    "worst_risk":        ["리밸런싱 지금 해야 해?", "스트레스 테스트 결과는?", "배당컷 날 가능성은?"],
    "tax_impact":        ["ISA 계좌 어떻게 써야 해?", "연금저축 얼마 넣어야 해?", "종합과세 언제 걸려?"],
    "inflation_defense": ["20년 후 실질 배당은?", "배당성장 ETF 어떤 거 사야 해?", "포트폴리오 건강점수는?"],
    "rebalance_action":  ["교체 후 배당은 얼마가 돼?", "리밸런싱하면 세금 어떻게 돼?", "가장 위험한 종목은?"],
    "behavioral_check":  ["내 포트폴리오 건강점수는?", "지금 사고 팔아야 할 게 있어?", "목표 달성 얼마나 남았어?"],
    "bank_comparison":   ["20년 후 배당은 얼마야?", "인플레이션 이기고 있어?", "포트폴리오 더 개선할 수 있어?"],
    "future_projection": ["20년 후 실질 구매력은?", "FIRE 언제 가능해?", "목표 달성 확률은?"],
    "isa_pension":       ["세금 얼마나 아낄 수 있어?", "연금저축 넣으면 이익이야?", "종합과세 걸리나?"],
    "health_score":      ["어떤 축이 가장 약해?", "지금 리밸런싱 필요해?", "가장 위험한 종목은?"],
    "add_investment":    ["추가 투자하면 FIRE 빨라져?", "어떤 자산에 넣어야 해?", "세금 어떻게 돼?"],
    "macro_impact":      ["지금 어떤 자산 사야 해?", "리밸런싱 필요해?", "환율 리스크는?"],
}


# ─────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ─────────────────────────────────────────────────────────────────────────────

def ask_advisor(
    question:         str,
    portfolio_result: dict,
    use_llm:          bool = False,
) -> dict:
    """
    자연어 질문 → 포트폴리오 데이터 기반 즉답.

    Args:
        question:         사용자 자연어 질문 (한국어)
        portfolio_result: recommend_portfolio() 반환값
        use_llm:          ollama LLM 강화 답변 사용 여부 (기본 False)

    Returns: 상단 docstring 참조
    """
    q_norm = question.strip().lower().replace(" ", "")

    # ── 의도 탐지 ─────────────────────────────────────────────────────────────
    intent, confidence = _detect_intent(q_norm, question)

    # ── 의도별 답변 생성 ──────────────────────────────────────────────────────
    handler = _HANDLERS.get(intent, _handle_unknown)
    result  = handler(question, portfolio_result)

    result["intent"]       = intent
    result["intent_label"] = _INTENT_LABELS.get(intent, "기타")
    result["confidence"]   = round(confidence, 2)
    result["follow_up"]    = _FOLLOW_UPS.get(intent, [
        "지금 배당 얼마야?", "가장 위험한 종목은?", "FIRE 언제 가능해?"
    ])

    # ── LLM 강화 (선택적) ─────────────────────────────────────────────────────
    if use_llm:
        result = _enhance_with_llm(question, result, portfolio_result)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 의도 탐지
# ─────────────────────────────────────────────────────────────────────────────

def _detect_intent(q_norm: str, q_raw: str) -> tuple[str, float]:
    """키워드 점수 기반 의도 탐지."""
    scores: dict[str, float] = {}

    for intent, keywords in _INTENT_KEYWORDS.items():
        score = 0.0
        for kw in keywords:
            kw_norm = kw.replace(" ", "")
            if kw_norm in q_norm:
                # 긴 키워드일수록 높은 점수
                score += 1.0 + len(kw_norm) * 0.1
        if score > 0:
            scores[intent] = score

    if not scores:
        return "unknown", 0.3

    best_intent = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    confidence = min(0.99, scores[best_intent] / total + 0.3)
    return best_intent, confidence


# ─────────────────────────────────────────────────────────────────────────────
# 의도별 핸들러
# ─────────────────────────────────────────────────────────────────────────────

def _handle_current_income(q: str, r: dict) -> dict:
    """① 현재 배당 수입"""
    s     = r.get("summary", {})
    cal   = r.get("dividend_calendar", {})
    inv   = r.get("input", {}).get("investable", s.get("investable_amount_만원", 0))
    mo_net = s.get("est_monthly_div_after_tax_만원", cal.get("avg_monthly_net_만원", 0))
    yr_net = s.get("est_annual_div_after_tax_만원", round(mo_net * 12, 1))
    yield_net = s.get("avg_dividend_yield_net", 0)
    smooth = cal.get("smoothness_score", 0)
    dry    = cal.get("dry_month_names", [])
    coverage = r.get("living_coverage", {}).get("current_coverage_pct", 0)
    bench    = r.get("living_coverage", {}).get("benchmark_만원", 250)

    headline = f"세후 월 {mo_net:,.1f}만원 · 연 {yr_net:,.0f}만원 배당 중"

    answer = (
        f"현재 {int(inv):,}만원 투자 기준으로 세후 연간 {yr_net:,.0f}만원(월 평균 {mo_net:,.1f}만원)이 "
        f"배당으로 입금됩니다. 포트폴리오 세후 평균 배당수익률은 {yield_net}%입니다. "
    )
    if dry:
        answer += f"{', '.join(dry[:3])}는 배당 공백월이며, "
    if smooth >= 70:
        answer += "월별 배당이 고르게 분산되어 있습니다."
    else:
        peak = cal.get("peak_month_name", "")
        peak_amt = cal.get("peak_amount_만원", 0)
        answer += f"분기 집중(최대 {peak} {round(peak_amt)}만원)이므로 월배당 ETF 추가를 고려하세요."

    if coverage > 0:
        answer += f" 서울 1인 생활비({bench:,}만원)의 {coverage}%를 배당으로 커버 중입니다."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "세후 월 배당",   "value": mo_net,    "unit": "만원"},
            {"label": "세후 연 배당",   "value": yr_net,    "unit": "만원"},
            {"label": "세후 수익률",    "value": yield_net, "unit": "%"},
            {"label": "생활비 커버율",  "value": coverage,  "unit": "%"},
            {"label": "캘린더 균등도",  "value": smooth,    "unit": "점"},
        ],
        "action": (
            "현금흐름을 더 균등하게 만들려면 SGOV(월배당) 또는 JEPI를 추가하세요."
            if smooth < 60 else
            "현재 현금흐름 구조는 양호합니다. 분기 1회 리밸런싱을 유지하세요."
        ),
    }


def _handle_target_gap(q: str, r: dict) -> dict:
    """② 목표 달성 현황"""
    inp  = r.get("input", {})
    s    = r.get("summary", {})
    mc   = r.get("monte_carlo", {})
    proj = r.get("projection", {})

    target  = inp.get("monthly_target", 0)
    mo_net  = s.get("est_monthly_div_after_tax_만원", 0)
    gap     = round(target - mo_net, 1)
    ach_pct = s.get("target_achievement_pct", 0)
    conf    = mc.get("confidence_at_target", 0) if mc else 0
    target_yr = (proj.get("milestones") or {}).get("target_achieved_year")

    if target <= 0:
        return {
            "headline": "목표 월 배당이 설정되지 않았습니다",
            "answer":   "목표 월 배당금(monthly_target)을 설정하면 달성 현황을 분석해 드립니다.",
            "data_points": [],
            "action":  "목표 금액을 설정한 후 다시 분석해 보세요.",
        }

    if gap <= 0:
        headline = f"✅ 목표 {target}만원 달성! 현재 {mo_net:.1f}만원으로 {abs(gap):.1f}만원 초과"
        answer = f"축하합니다! 이미 월 배당 {mo_net:.1f}만원으로 목표 {target}만원을 {abs(gap):.1f}만원 초과 달성했습니다."
        action = "목표를 상향 조정하거나 배당성장형 자산으로 구조를 개선하세요."
    else:
        needed_invest = round(gap * 12 / 0.035)  # 3.5% 기준
        headline = f"목표까지 월 {gap:.1f}만원 부족 — 약 {needed_invest:,}만원 추가 투자 필요"
        answer = (
            f"현재 월 배당 {mo_net:.1f}만원으로, 목표 {target}만원까지 {gap:.1f}만원이 부족합니다 "
            f"(달성률 {ach_pct}%). "
        )
        if target_yr:
            answer += f"현재 성장률 유지 시 {target_yr}년 차에 자연 달성이 예상됩니다. "
        else:
            answer += f"세후 수익률 3.5% 기준으로 약 {needed_invest:,}만원 추가 투자가 필요합니다. "
        if conf > 0:
            emoji = "✅" if conf >= 70 else ("🟡" if conf >= 40 else "⚠️")
            answer += f"{emoji} Monte Carlo 기준 20년 내 목표 달성 확률: {conf}%."
        action = (
            f"배당성장 ETF(SCHD·VIG) 비중을 높이거나, ISA 계좌로 세후 수익률을 개선해 "
            f"목표 달성을 앞당기세요."
        )

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "현재 월 배당",    "value": mo_net,   "unit": "만원"},
            {"label": "목표 월 배당",    "value": target,   "unit": "만원"},
            {"label": "부족액",          "value": gap,      "unit": "만원"},
            {"label": "달성률",          "value": ach_pct,  "unit": "%"},
            {"label": "MC 목표 달성 확률","value": conf,    "unit": "%"},
        ],
        "action": action,
    }


def _handle_fire_status(q: str, r: dict) -> dict:
    """③ FIRE 달성 시뮬레이션"""
    fire = r.get("fire_plan", {})
    if not fire:
        return _no_data("FIRE 엔진", "fire_plan")

    cs    = fire.get("current_state", {})
    tgts  = fire.get("targets", {})
    lean  = tgts.get("lean", {})
    reg   = tgts.get("regular", {})
    fat   = tgts.get("fat", {})
    rec   = fire.get("recommended_action", "")
    e_type = fire.get("earliest_fire_type", "")
    e_age  = fire.get("earliest_fire_age")
    t_age  = cs.get("target_age", 50)

    lean_age = lean.get("projected_fire_age")
    reg_age  = reg.get("projected_fire_age")

    if e_age and e_age <= t_age:
        headline = f"🎯 {e_age}세에 {_FIRE_KR.get(e_type, e_type)} 달성 가능 — 목표보다 {t_age - e_age}년 빨라요"
    elif lean_age:
        headline = f"린 파이어 {lean_age}세 예상 (목표 {t_age}세보다 {lean_age - t_age}년 늦음)"
    else:
        headline = "현재 경로에서 FIRE 달성 시뮬레이션 결과"

    answer = ""
    if lean_age:
        gap_yr = lean_age - t_age
        sign   = "빠릅니다" if gap_yr <= 0 else f"{abs(gap_yr)}년 늦습니다"
        answer += f"린 파이어(월 {lean.get('monthly_target_nominal', 120)}만원 기준): {lean_age}세 달성 예상 — 목표보다 {sign}. "
    if reg_age:
        answer += f"일반 파이어(월 {reg.get('monthly_target_nominal', 250)}만원): {reg_age}세 예상. "
    elif reg.get("monthly_pmt_needed", 0) > 0:
        pmt = reg["monthly_pmt_needed"]
        answer += f"일반 파이어 달성을 위해 월 {pmt:,.0f}만원 추가 저축이 필요합니다. "
    if rec:
        answer += f"권고: {rec}"

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "린 파이어 예상 나이",    "value": lean_age,  "unit": "세"},
            {"label": "일반 파이어 예상 나이",   "value": reg_age,   "unit": "세"},
            {"label": "가장 빠른 FIRE",         "value": e_age,     "unit": f"세 ({_FIRE_KR.get(e_type, '')})"},
            {"label": "목표 나이",              "value": t_age,     "unit": "세"},
            {"label": "린 파이어 필요 원금",     "value": lean.get("required_principal"), "unit": "만원"},
        ],
        "action": rec or "ISA·연금저축 납입을 늘려 세후 수익률을 높이면 FIRE 달성 시기를 앞당길 수 있습니다.",
    }


def _handle_worst_risk(q: str, r: dict) -> dict:
    """④ 최대 리스크 진단"""
    alerts  = r.get("risk_alerts", [])
    stress  = r.get("stress_test", {})
    mc      = r.get("monte_carlo", {})
    beh     = r.get("behavioral_finance", {})

    broken  = [a for a in alerts if a.get("signal") == "BROKEN"]
    danger  = [a for a in alerts if a.get("signal") == "DANGER"]

    # 최악 스트레스 시나리오
    scenarios = stress.get("scenarios", {})
    worst_name, worst_loss = "", 0.0
    for sc in scenarios.values():
        loss = sc.get("portfolio_loss_pct", 0)
        if abs(loss) > abs(worst_loss):
            worst_loss = loss
            worst_name = sc.get("name", "")

    resilience = stress.get("overall_resilience_score", 0)
    grade      = stress.get("overall_grade", "?")
    exp_cuts   = mc.get("expected_cut_events", 0) if mc else 0
    p10        = mc.get("p10_final", 0) if mc else 0

    if broken:
        tickers  = ", ".join(a.get("ticker", "") for a in broken[:2])
        headline = f"⚠️ {tickers} ML 신호 붕괴 — 즉시 교체 필요"
    elif danger:
        tickers  = ", ".join(a.get("ticker", "") for a in danger[:2])
        headline = f"💡 {tickers} 배당함정 위험 감지"
    elif worst_loss < -20:
        headline = f"최악 시나리오 '{worst_name}'에서 최대 {abs(round(worst_loss))}% 손실 가능"
    else:
        headline = f"포트폴리오 복원력 {resilience}점 ({grade}등급) — 주요 리스크 없음"

    answer = f"스트레스 테스트 복원력 {resilience}점({grade}등급). "
    if worst_name:
        answer += f"가장 큰 위협은 '{worst_name}' 시나리오({abs(round(worst_loss))}% 손실). "
    if broken:
        names = ", ".join(a.get("ticker","") for a in broken[:3])
        answer += f"ML 신호 붕괴 종목: {names}. 즉시 교체 권고. "
    if exp_cuts > 5:
        answer += f"Monte Carlo 상 20년간 배당컷 예상 {exp_cuts}회 — 분산 강화 필요. "
    if p10 > 0:
        answer += f"비관 시나리오(P10) 기준 20년 후 월배당: {round(p10)}만원."
    if beh.get("high_severity", 0) > 0:
        answer += f" 행동 편향(심각 {beh['high_severity']}개)이 리스크를 키우고 있습니다."

    top_alert = broken[0] if broken else (danger[0] if danger else None)
    action = (
        f"{top_alert['ticker']} 즉시 매도 후 동일 자산군 ETF로 교체하세요."
        if top_alert else
        "현재 포트폴리오는 주요 경보 없음. 분기 1회 리밸런싱을 유지하세요."
    )

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "복원력 점수",       "value": resilience,          "unit": "점"},
            {"label": "최악 시나리오 손실", "value": round(abs(worst_loss)),"unit": "%"},
            {"label": "ML 붕괴 종목",      "value": len(broken),         "unit": "개"},
            {"label": "예상 배당컷",       "value": exp_cuts,            "unit": "회/20년"},
            {"label": "비관 P10 배당",     "value": round(p10),          "unit": "만원/월"},
        ],
        "action": action,
    }


def _handle_tax_impact(q: str, r: dict) -> dict:
    """⑤ 세금 영향 분석"""
    tax = r.get("tax_optimizer", {})
    if not tax:
        return _no_data("세금 최적화", "tax_optimizer")

    ct        = tax.get("comprehensive_tax", {})
    isa       = tax.get("isa_strategy", {})
    pen       = tax.get("pension_strategy", {})
    eff_rate  = tax.get("effective_tax_rate_pct", 15.4)
    opt_rate  = tax.get("optimized_tax_rate_pct", eff_rate)
    saving    = tax.get("total_annual_saving_만원", 0)
    cum5      = tax.get("5yr_cumulative_saving_만원", 0)
    health    = tax.get("tax_health_score", 0)
    gross     = ct.get("annual_div_gross_만원", 0)
    gap       = ct.get("threshold_gap_만원", 0)
    risk_lbl  = ct.get("risk_label", "")

    headline = (
        f"⚠️ 종합과세 대상 — ISA·연금저축으로 연 {saving:.0f}만원 절세 가능"
        if ct.get("is_over_threshold") else
        f"세금 건강 {health}점 — 최적화 시 연 {saving:.0f}만원 절세"
    )

    answer = (
        f"현재 연 배당(세전) {gross:.0f}만원에 실효 배당세율 {eff_rate}% 적용 중. "
        f"종합과세(2,000만원) 여유: {gap:.0f}만원 ({risk_lbl}). "
    )
    if saving > 0:
        answer += (
            f"ISA({isa.get('annual_tax_saving_만원', 0):.1f}만원) + "
            f"연금저축({pen.get('annual_tax_saving_만원', 0):.1f}만원) 활용 시 "
            f"연 {saving:.1f}만원, 5년 누적 {cum5:.0f}만원 절세 가능. "
        )
        answer += f"최적화 후 실효세율 {eff_rate}% → {opt_rate}%로 개선됩니다."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "연 배당(세전)",   "value": gross,      "unit": "만원"},
            {"label": "실효세율",        "value": eff_rate,   "unit": "%"},
            {"label": "최적화 후 세율",  "value": opt_rate,   "unit": "%"},
            {"label": "연간 절세",       "value": saving,     "unit": "만원"},
            {"label": "5년 누적 절세",   "value": cum5,       "unit": "만원"},
            {"label": "세금 건강 점수",  "value": health,     "unit": "점"},
        ],
        "action": tax.get("priority_actions", [{}])[0].get("action", "ISA 계좌를 개설하고 고배당 자산을 우선 편입하세요.") if tax.get("priority_actions") else "ISA 계좌를 개설하세요.",
    }


def _handle_inflation_defense(q: str, r: dict) -> dict:
    """⑥ 인플레이션 방어력"""
    proj = r.get("projection", {})
    inf  = proj.get("inflation", {})
    health = r.get("portfolio_health", {})
    cagr = proj.get("portfolio_div_cagr", 0)

    loss_pct  = inf.get("purchasing_power_loss_pct", 0)
    real_fin  = inf.get("real_final_monthly", 0)
    nom_fin   = proj.get("final_monthly_net", 0)
    inf_axis  = next((a for a in health.get("radar_data", []) if a["axis"] == "inflation_defense"), {})
    inf_score = inf_axis.get("pct", 0)

    is_winning = cagr >= 2.5  # CPI 기준

    headline = (
        f"✅ 배당성장률({cagr}%) > 인플레(2.5%) — 실질 구매력 유지 중"
        if is_winning else
        f"⚠️ 20년 후 실질 구매력 {loss_pct}% 감소 예상 — 배당성장 강화 필요"
    )

    answer = (
        f"현재 포트폴리오 배당 CAGR {cagr}% vs 인플레이션 2.5% 기준으로 "
    )
    if is_winning:
        answer += f"실질 구매력이 유지됩니다. "
    else:
        answer += f"장기적으로 실질 가치가 하락합니다. "

    answer += (
        f"20년 후 명목 배당 {round(nom_fin)}만원의 실질 구매력은 약 {round(real_fin)}만원 "
        f"(구매력 {loss_pct}% 감소). "
        f"인플레이션 방어 점수: {inf_score}%."
    )

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "배당 CAGR",          "value": cagr,       "unit": "%"},
            {"label": "인플레이션 기준",     "value": 2.5,        "unit": "%"},
            {"label": "20년 후 명목 배당",   "value": round(nom_fin), "unit": "만원/월"},
            {"label": "20년 후 실질 배당",   "value": round(real_fin),"unit": "만원/월"},
            {"label": "구매력 감소",         "value": loss_pct,   "unit": "%"},
            {"label": "인플레 방어 점수",    "value": inf_score,  "unit": "%"},
        ],
        "action": (
            "SCHD·VIG 같은 배당성장 ETF 비중을 30% 이상으로 높여 "
            "배당 CAGR을 물가상승률 이상으로 유지하세요."
            if not is_winning else
            "현재 배당성장 속도가 인플레이션을 앞서고 있습니다. 구조를 유지하세요."
        ),
    }


def _handle_rebalance_action(q: str, r: dict) -> dict:
    """⑦ 리밸런싱 액션"""
    rebal  = r.get("rebalancing_plan", {})
    alerts = r.get("risk_alerts", [])
    health = r.get("portfolio_health", {})

    actions_list = rebal.get("actions", [])
    urgency      = rebal.get("urgency", "normal")
    broken       = [a for a in alerts if a.get("signal") == "BROKEN"]

    if broken:
        tickers  = ", ".join(a.get("ticker", "") for a in broken[:2])
        headline = f"🚨 즉시 행동: {tickers} ML 신호 붕괴 — 매도 권고"
    elif actions_list:
        first = actions_list[0]
        headline = f"리밸런싱 {len(actions_list)}건 — {first.get('ticker','')} {first.get('action','조정')} 우선"
    else:
        headline = f"포트폴리오 구조 양호 — 정기 리밸런싱만 필요"

    answer = f"총 {len(actions_list)}건의 리밸런싱 액션이 있습니다. "
    if broken:
        names = ", ".join(a.get("ticker","") for a in broken[:3])
        answer += f"최우선: ML 신호 붕괴 종목 {names} 즉시 매도. "
    if actions_list:
        for act in actions_list[:3]:
            ticker  = act.get("ticker", "")
            action  = act.get("action", "조정")
            current = act.get("current_pct", 0)
            target  = act.get("target_pct", 0)
            answer += f"{ticker}: {current}% → {target}% ({action}). "

    health_score = health.get("score", 0)
    answer += f"포트폴리오 건강 점수: {health_score}점."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "리밸런싱 건수",   "value": len(actions_list), "unit": "건"},
            {"label": "긴급도",          "value": urgency,           "unit": ""},
            {"label": "ML 붕괴 종목",    "value": len(broken),       "unit": "개"},
            {"label": "포트폴리오 건강", "value": health_score,      "unit": "점"},
        ],
        "action": (
            f"ML 신호 붕괴 종목부터 즉시 교체하고, 나머지 리밸런싱은 분기 내 실행하세요."
            if broken else
            "분기 1회 리밸런싱 스케줄을 유지하고, 배당 컷 발생 시 즉시 대응하세요."
        ),
    }


def _handle_behavioral_check(q: str, r: dict) -> dict:
    """⑧ 행동 편향 진단"""
    beh = r.get("behavioral_finance", {})
    if not beh:
        return _no_data("행동 편향 진단", "behavioral_finance")

    cnt      = beh.get("bias_count", 0)
    high_sev = beh.get("high_severity", 0)
    score    = beh.get("overall_bias_score", 0)
    inv_type = beh.get("investor_type", "")
    top_bias = beh.get("top_bias", "없음")
    coaching = beh.get("coaching_message", "")
    detected = beh.get("detected_biases", [])

    headline = (
        f"⚠️ 행동 편향 {cnt}가지 탐지 (심각 {high_sev}개) — {inv_type}"
        if cnt > 0 else
        f"✅ 행동 편향 없음 — {inv_type}"
    )

    answer = f"투자자 행동 유형: {inv_type} (편향 점수 {score}점). "
    if detected:
        for b in detected[:3]:
            answer += f"[{b['severity_label']}] {b['name']}: {b['evidence'][:40]}... "
    else:
        answer += "주요 행동 편향이 탐지되지 않았습니다. "
    answer += coaching[:80] + "..."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "편향 수",      "value": cnt,      "unit": "개"},
            {"label": "심각 편향",    "value": high_sev, "unit": "개"},
            {"label": "편향 점수",    "value": score,    "unit": "점"},
            {"label": "가장 큰 편향", "value": top_bias, "unit": ""},
        ],
        "action": (
            beh.get("detected_biases", [{}])[0].get("debiasing_action", "포트폴리오 점검을 권장합니다.")
            if beh.get("detected_biases") else
            "현재 행동 편향 없음. 규칙 기반 리밸런싱으로 편향을 예방하세요."
        ),
    }


def _handle_bank_comparison(q: str, r: dict) -> dict:
    """⑨ 은행 금리 비교"""
    s       = r.get("summary", {})
    proj    = r.get("projection", {})
    mc      = r.get("monte_carlo", {})

    yield_net   = s.get("avg_dividend_yield_net", 0)
    bank_rate   = s.get("bank_rate_pct", 3.5)
    vs_bank     = s.get("vs_bank_rate_pct", round(yield_net - bank_rate, 2))
    cagr        = proj.get("portfolio_div_cagr", 0)
    p50_final   = mc.get("p50_final", 0) if mc else 0

    is_better = vs_bank > 0
    headline = (
        f"✅ 은행 예금({bank_rate}%) 대비 +{vs_bank}%p 초과수익"
        if is_better else
        f"⚠️ 은행 예금({bank_rate}%)보다 {abs(vs_bank)}%p 낮음"
    )

    answer = (
        f"현재 포트폴리오 세후 배당수익률 {yield_net}% vs 은행 정기예금 {bank_rate}%. "
        f"초과수익 {'+' if vs_bank >= 0 else ''}{vs_bank}%p. "
    )
    if is_better:
        answer += (
            f"배당성장 CAGR {cagr}%를 고려하면 복리 효과로 장기 격차는 더 벌어집니다. "
            f"20년 후 P50 기준 월 {round(p50_final)}만원 배당 예상 "
            f"(은행 예금은 원금만 유지)."
        )
    else:
        answer += "배당 성장 여력이 있는 ETF 비중을 늘려 수익률을 개선하세요."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "포트폴리오 세후 수익률", "value": yield_net,   "unit": "%"},
            {"label": "은행 금리",              "value": bank_rate,   "unit": "%"},
            {"label": "초과수익",               "value": vs_bank,     "unit": "%p"},
            {"label": "배당 CAGR",              "value": cagr,        "unit": "%"},
            {"label": "20년 후 P50 배당",       "value": round(p50_final),"unit": "만원/월"},
        ],
        "action": (
            "배당성장 ETF 비중을 유지하고 배당을 재투자하면 은행 예금과의 격차가 복리로 확대됩니다."
            if is_better else
            "배당성장 ETF(SCHD·VIG)를 추가해 수익률을 은행 금리 이상으로 끌어올리세요."
        ),
    }


def _handle_future_projection(q: str, r: dict) -> dict:
    """⑩ 미래 배당 예측"""
    proj = r.get("projection", {})
    mc   = r.get("monte_carlo", {})
    inf  = proj.get("inflation", {})

    # 질문에서 연도 추출 시도
    match = re.search(r"(\d+)\s*년", q)
    years = int(match.group(1)) if match else 20

    nom_final  = proj.get("final_monthly_net", 0)
    real_final = inf.get("real_final_monthly", 0)
    loss_pct   = inf.get("purchasing_power_loss_pct", 0)
    cagr       = proj.get("portfolio_div_cagr", 0)
    snapshots  = mc.get("snapshots", []) if mc else []
    p10 = mc.get("p10_final", 0) if mc else 0
    p50 = mc.get("p50_final", 0) if mc else 0
    p90 = mc.get("p90_final", 0) if mc else 0

    # 특정 연도 스냅샷 찾기
    snap = next((s for s in snapshots if s.get("year") == years), None)
    if snap:
        yr_p50 = snap.get("p50", p50)
        yr_p10 = snap.get("p10", p10)
        yr_p90 = snap.get("p90", p90)
        headline = f"{years}년 후 월배당 중앙값 {round(yr_p50)}만원 (P10 {round(yr_p10)} ~ P90 {round(yr_p90)})"
        answer = (
            f"Monte Carlo 1,000회 시뮬레이션 결과, {years}년 후 월 배당은 "
            f"중앙값 {round(yr_p50)}만원 (비관 {round(yr_p10)}만원 ~ 낙관 {round(yr_p90)}만원). "
        )
    else:
        headline = f"20년 후 월배당 중앙값 {round(p50)}만원 (P10 {round(p10)} ~ P90 {round(p90)})"
        answer = (
            f"20년 후 월 배당 예측: 중앙값 {round(p50)}만원 "
            f"(비관 {round(p10)}만원 ~ 낙관 {round(p90)}만원, 80% 신뢰구간). "
        )

    answer += (
        f"명목 기준 {round(nom_final)}만원이지만, 2.5% 인플레이션 반영 시 "
        f"실질 구매력은 {round(real_final)}만원({loss_pct}% 감소). "
        f"배당 CAGR {cagr}%가 핵심 변수입니다."
    )

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": f"{years}년 후 P10", "value": round(p10), "unit": "만원/월"},
            {"label": f"{years}년 후 P50", "value": round(p50), "unit": "만원/월"},
            {"label": f"{years}년 후 P90", "value": round(p90), "unit": "만원/월"},
            {"label": "실질 구매력",        "value": round(real_final), "unit": "만원"},
            {"label": "배당 CAGR",          "value": cagr, "unit": "%"},
        ],
        "action": (
            "배당 CAGR을 높이는 것이 가장 중요합니다. "
            "SCHD·VIG 비중을 늘리고 배당을 재투자하면 P90 시나리오에 가까워집니다."
        ),
    }


def _handle_isa_pension(q: str, r: dict) -> dict:
    """⑪ ISA·연금저축 전략"""
    tax = r.get("tax_optimizer", {})
    if not tax:
        return _no_data("세금 최적화", "tax_optimizer")

    isa   = tax.get("isa_strategy", {})
    pen   = tax.get("pension_strategy", {})
    total = tax.get("total_annual_saving_만원", 0)
    cum5  = tax.get("5yr_cumulative_saving_만원", 0)

    isa_saving = isa.get("annual_tax_saving_만원", 0)
    pen_saving = pen.get("annual_tax_saving_만원", 0)
    rec_assets = isa.get("recommended_assets", [])

    headline = f"ISA+연금저축 최적화 시 연 {total:.0f}만원 절세 · 5년 누적 {cum5:.0f}만원"

    answer = (
        f"ISA 계좌: {isa.get('action', '')} "
        f"(연 {isa_saving:.1f}만원 절세). "
        f"연금저축·IRP: {pen.get('action', '')} "
        f"(연 {pen_saving:.1f}만원 세액공제). "
    )
    if rec_assets:
        names = ", ".join(f"{a['ticker']}" for a in rec_assets[:3])
        answer += f"ISA 우선 편입 종목: {names}."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "ISA 절세",           "value": isa_saving,  "unit": "만원/년"},
            {"label": "연금저축 세액공제",   "value": pen_saving,  "unit": "만원/년"},
            {"label": "합산 연간 절세",      "value": total,       "unit": "만원"},
            {"label": "5년 누적 절세",       "value": cum5,        "unit": "만원"},
            {"label": "ISA 잔여 한도",       "value": isa.get("remaining_capacity_만원", 0), "unit": "만원"},
        ],
        "action": pen.get("action", "연금저축 계좌를 개설해 세액공제를 받으세요."),
    }


def _handle_health_score(q: str, r: dict) -> dict:
    """⑫ 포트폴리오 건강도"""
    health = r.get("portfolio_health", {})
    if not health:
        return _no_data("포트폴리오 건강", "portfolio_health")

    score  = health.get("score", 0)
    grade  = health.get("grade", "")
    tips   = health.get("tips", [])
    radar  = health.get("radar_data", [])
    axis_a = health.get("axis_actions", {})

    # 가장 약한 축 찾기
    weakest = min(radar, key=lambda a: a.get("pct", 100)) if radar else {}
    w_axis  = weakest.get("axis", "")
    w_pct   = weakest.get("pct", 0)

    headline = f"포트폴리오 건강 {score}점 {grade} — 최약 축: {w_axis} ({w_pct}%)"

    answer = f"포트폴리오 6축 건강 점수 {score}점 ({grade}). "
    for ax in radar:
        bar = "█" * int(ax["pct"] / 10) + "░" * (10 - int(ax["pct"] / 10))
        answer += f"{ax['axis']}:{ax['pct']}% "
    if tips:
        answer += f" 개선 팁: {tips[0]}"

    weak_action = axis_a.get(w_axis, f"{w_axis} 축 개선이 우선입니다.")

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [{"label": a["axis"], "value": a["pct"], "unit": "%"} for a in radar] + [
            {"label": "종합 점수", "value": score, "unit": "점"}
        ],
        "action": weak_action,
    }


def _handle_add_investment(q: str, r: dict) -> dict:
    """⑬ 추가 투자 계산"""
    inp  = r.get("input", {})
    s    = r.get("summary", {})
    fire = r.get("fire_plan", {})
    mc   = r.get("monte_carlo", {})

    target   = inp.get("monthly_target", 0)
    mo_net   = s.get("est_monthly_div_after_tax_만원", 0)
    yield_net = s.get("avg_dividend_yield_net", 3.5) or 3.5
    gap      = max(0, target - mo_net)

    # 추가 투자 필요액 역산
    needed_add = round(gap * 12 / (yield_net / 100)) if gap > 0 and yield_net > 0 else 0

    # FIRE 추가 저축
    tgts    = fire.get("targets", {}) if fire else {}
    lean    = tgts.get("lean", {})
    lean_pmt = lean.get("monthly_pmt_needed", 0)

    if gap > 0:
        headline = f"목표 달성에 약 {needed_add:,}만원 추가 투자 필요"
        answer = (
            f"현재 세후 수익률 {yield_net}% 기준으로, "
            f"월 배당 {gap:.1f}만원 추가를 위해 약 {needed_add:,}만원 추가 투자가 필요합니다. "
        )
    else:
        headline = "이미 목표 달성 — 추가 투자로 FIRE를 앞당기세요"
        answer = "현재 목표 월 배당을 초과 달성했습니다. "

    if lean_pmt > 0:
        answer += f"린 파이어 목표 달성을 위해 월 {lean_pmt:,.0f}만원 추가 저축을 권고합니다."
    elif fire and fire.get("earliest_fire_age"):
        answer += f"현재 저축 속도를 유지하면 {fire.get('earliest_fire_age')}세에 최단 FIRE가 가능합니다."

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "현재 월 배당",      "value": mo_net,       "unit": "만원"},
            {"label": "목표 월 배당",      "value": target,       "unit": "만원"},
            {"label": "추가 필요 투자금",  "value": needed_add,   "unit": "만원"},
            {"label": "현재 세후 수익률",  "value": yield_net,    "unit": "%"},
            {"label": "FIRE 추가 저축",    "value": lean_pmt,     "unit": "만원/월"},
        ],
        "action": (
            f"ISA 계좌로 {needed_add:,}만원을 투자하면 세후 수익률이 개선되어 "
            "실제 필요 금액이 줄어듭니다."
            if needed_add > 0 else
            "배당을 재투자하면 복리로 자산이 성장해 FIRE를 앞당길 수 있습니다."
        ),
    }


def _handle_macro_impact(q: str, r: dict) -> dict:
    """⑭ 매크로 시장 진단"""
    macro = r.get("macro_regime", {})
    if not macro:
        return _no_data("매크로 국면", "macro_regime")

    regime   = macro.get("label", "")
    advisory = macro.get("advisory", "")
    conf     = macro.get("confidence", 0)
    conf_lbl = macro.get("confidence_label", "")
    runner   = macro.get("runner_up", "")
    runner_c = macro.get("runner_up_conf", 0)
    spread   = macro.get("yield_spread", 0)
    inds     = macro.get("indicators", {})

    headline = f"현재 시장 국면: {regime} ({conf_lbl})"

    answer = (
        f"현재 매크로 국면은 '{regime}'으로, 신뢰도 {conf:.0%}. "
        f"2위 국면: {runner}({runner_c:.0%}). "
        f"금리 스프레드(10년-정책금리): {spread:.2f}%p. "
        f"투자 어드바이스: {advisory}"
    )

    return {
        "headline": headline,
        "answer":   answer,
        "data_points": [
            {"label": "시장 국면",      "value": regime,        "unit": ""},
            {"label": "국면 신뢰도",    "value": round(conf*100,1), "unit": "%"},
            {"label": "2위 국면",       "value": runner,        "unit": ""},
            {"label": "금리 스프레드",  "value": round(spread,2), "unit": "%p"},
        ],
        "action": advisory,
    }


def _handle_unknown(q: str, r: dict) -> dict:
    """알 수 없는 의도"""
    return {
        "headline": "질문을 더 구체적으로 해주세요",
        "answer": (
            f"'{q[:30]}...'에 대한 분석을 찾지 못했습니다. "
            "아래 예시 질문을 참고해 주세요: "
            "지금 배당 얼마야? / FIRE 언제 돼? / 세금 얼마야? / 가장 위험한 종목은?"
        ),
        "data_points": [],
        "action": "구체적인 질문으로 다시 시도해 보세요.",
    }


def _no_data(module_name: str, key: str) -> dict:
    return {
        "headline": f"{module_name} 데이터 없음",
        "answer":   f"'{key}' 데이터가 포트폴리오 결과에 없습니다. 최신 분석을 실행해 주세요.",
        "data_points": [],
        "action": "recommend_portfolio()를 다시 실행하세요.",
    }


def _enhance_with_llm(question: str, result: dict, portfolio_result: dict) -> dict:
    """ollama LLM으로 답변 품질 강화 (선택적)."""
    try:
        from utils.ollama_client import ask_ollama
        context = (
            f"질문: {question}\n"
            f"핵심 답변: {result['headline']}\n"
            f"데이터: {result['data_points']}\n"
            "위 데이터를 바탕으로 한국어 PB(Private Banker) 어조로 2~3문장으로 답변하세요."
        )
        enhanced = ask_ollama(context)
        if enhanced:
            result["answer_llm"] = enhanced
    except Exception:
        pass
    return result


# ── 핸들러 맵 ────────────────────────────────────────────────────────────────
_HANDLERS = {
    "current_income":    _handle_current_income,
    "target_gap":        _handle_target_gap,
    "fire_status":       _handle_fire_status,
    "worst_risk":        _handle_worst_risk,
    "tax_impact":        _handle_tax_impact,
    "inflation_defense": _handle_inflation_defense,
    "rebalance_action":  _handle_rebalance_action,
    "behavioral_check":  _handle_behavioral_check,
    "bank_comparison":   _handle_bank_comparison,
    "future_projection": _handle_future_projection,
    "isa_pension":       _handle_isa_pension,
    "health_score":      _handle_health_score,
    "add_investment":    _handle_add_investment,
    "macro_impact":      _handle_macro_impact,
    "unknown":           _handle_unknown,
}

_FIRE_KR = {"lean": "린 파이어", "regular": "일반 파이어",
            "fat": "팻 파이어", "custom": "커스텀 파이어"}

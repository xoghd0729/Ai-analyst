"""
utils/storytelling.py — 포트폴리오 스토리텔링
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  AI 배당 자산관리 서비스는 19개의 분석 결과 키를 반환한다.
  숫자와 표로만 제시하면 투자자는 "그래서 내가 뭘 해야 하지?"를 모른다.
  전체 포트폴리오를 하나의 일관된 한국어 내러티브로 엮어주는 것이
  AI 서비스의 핵심 부가가치다.

  설계 원칙:
  - 실제 계산값을 문장 안에 녹여라 ("배당 수익률 3.4%"가 아니라
    "5,000만원 투자 시 매월 약 14만원, 연 172만원이 입금됩니다")
  - 5개 단락: 현황 → 전략 → 미래 → 리스크 → 행동
  - 전문 PB(Private Banker) 어조: 정중하되 구체적, 추상적 조언 금지

반환:
{
    "narrative": {
        "summary":    str,   # 1단락: 현황 요약 (투자자 프로필 + 현재 배당)
        "strategy":   str,   # 2단락: 자산 배분 전략 설명
        "future":     str,   # 3단락: 20년 미래 시나리오 (인플레이션 포함)
        "risk":       str,   # 4단락: 리스크 경보 + 스트레스 테스트 결과
        "action":     str,   # 5단락: 구체적 다음 행동 권고
        "full_text":  str,   # 5단락 합본 (줄바꿈 구분)
        "headline":   str,   # 한 줄 요약 헤드라인
    }
}
"""

from __future__ import annotations


# ─── 자산군 한국어 이름 ───────────────────────────────────────
_CLASS_KR = {
    "kr_stock":   "국내 배당주",
    "us_stock":   "미국 배당주",
    "us_div_etf": "미국 배당 ETF",
    "kr_etf":     "국내 ETF",
    "us_reit":    "미국 리츠",
    "kr_reit":    "국내 리츠",
    "defensive":  "안전자산",
}

_ARCHETYPE_KR = {
    "income_seeker":   "배당 수익 추구형",
    "growth_dividend": "배당 성장 추구형",
    "balanced":        "균형 배당형",
    "혼합형":          "혼합형",
    "conservative":    "안정 추구형",
    "aggressive":      "공격 성장형",
}

_RISK_KR = {
    "conservative": "안정형",
    "moderate":     "중립형",
    "aggressive":   "공격형",
}

_MACRO_LABEL_EMOJI = {
    "risk_on":      "📈 위험선호",
    "risk_off":     "🛡️ 위험회피",
    "rate_pressure":"⚠️ 금리 압박",
    "neutral":      "⚖️ 중립",
    "unknown":      "❓ 불명확",
}


def generate_storytelling(
    input_data:      dict,
    recommendations: list[dict],
    summary:         dict,
    projection:      dict,
    living_coverage: dict,
    stress_test:     dict,
    dividend_calendar: dict,
    sector_exposure: dict,
    macro_regime:    dict,
    risk_alerts:     list[dict],
    archetype:        str  = "혼합형",
    fire_plan:        dict = None,
    monte_carlo:      dict = None,
    behavioral:       dict = None,
) -> dict:
    """
    포트폴리오 전체 분석 결과를 5단락 한국어 내러티브로 변환.

    Args:
        input_data:       req.age, req.risk_tolerance 등
        recommendations:  assign_weights() 결과
        summary:          포트폴리오 요약 (avg_yield, total_annual 등)
        projection:       simulate_portfolio() 결과 (inflation 포함)
        living_coverage:  calc_living_coverage() 결과
        stress_test:      run_stress_test() 결과
        dividend_calendar: build_dividend_calendar() 결과
        sector_exposure:  _calc_sector_exposure() 결과
        macro_regime:     현재 매크로 국면
        risk_alerts:      ML 리스크 경보 목록
        archetype:        투자자 아키타입

    반환:
    {
        "narrative": {
            "headline":  str,
            "summary":   str,
            "strategy":  str,
            "future":    str,
            "risk":      str,
            "action":    str,
            "full_text": str,
        }
    }
    """
    age         = input_data.get("age", 35)
    risk        = input_data.get("risk_tolerance", "moderate")
    investable  = input_data.get("investable", summary.get("investable_amount_만원", 0))
    monthly_t   = input_data.get("monthly_target", 0)

    para1 = _para_summary(age, risk, archetype, investable, summary, dividend_calendar, living_coverage)
    para2 = _para_strategy(recommendations, summary, macro_regime, archetype)
    para3 = _para_future(projection, investable, monthly_t, monte_carlo=monte_carlo, fire_plan=fire_plan)
    para4 = _para_risk(stress_test, risk_alerts, sector_exposure, macro_regime,
                       monte_carlo=monte_carlo, behavioral=behavioral)
    para5 = _para_action(risk_alerts, dividend_calendar, projection, monthly_t, investable, age, fire_plan=fire_plan)

    headline = _make_headline(summary, living_coverage, projection, age)

    full_text = "\n\n".join([para1, para2, para3, para4, para5])

    return {
        "narrative": {
            "headline":  headline,
            "summary":   para1,
            "strategy":  para2,
            "future":    para3,
            "risk":      para4,
            "action":    para5,
            "full_text": full_text,
        }
    }


# ─── 단락 1: 현황 요약 ───────────────────────────────────────

def _para_summary(
    age, risk, archetype, investable, summary, calendar, living
) -> str:
    risk_kr     = _RISK_KR.get(risk, "중립형")
    arch_kr     = _ARCHETYPE_KR.get(archetype, archetype)
    avg_yield   = summary.get("avg_yield_net", summary.get("avg_yield", 0))
    annual_net  = summary.get("total_annual_net", summary.get("total_annual", 0))
    monthly_net = round(annual_net / 12, 1) if annual_net else 0

    # 생활비 커버율
    coverage    = living.get("current_coverage_pct", 0)
    milestone   = living.get("current_label", "")
    bench       = living.get("benchmark_만원", 0)

    # 캘린더 데이터
    cal_annual  = calendar.get("annual_total_net_만원", annual_net / 10000 if annual_net else 0)
    smooth      = calendar.get("smoothness_score", 0)
    dry_names   = calendar.get("dry_month_names", [])
    peak_name   = calendar.get("peak_month_name", "")
    peak_amt    = calendar.get("peak_amount_만원", 0)

    sentences = [
        f"현재 {age}세 {risk_kr} 투자자로서, {arch_kr} 전략에 맞춘 포트폴리오가 구성되었습니다.",
        f"총 {int(investable):,}만원 투자 기준으로 세후 연간 배당 예상액은 약 {round(cal_annual):,}만원, "
        f"월평균 {round(cal_annual/12, 1):,}만원입니다.",
    ]

    # 생활비 커버
    if coverage > 0:
        sentences.append(
            f"이는 서울 1인 기준 생활비({bench:,}만원/월)의 {coverage}% 수준으로, "
            f"현재 달성 단계는 '{milestone}'입니다."
        )

    # 캘린더 품질
    if smooth >= 70:
        sentences.append("월별 배당 분포가 고르게 설계되어 매달 안정적인 현금흐름을 기대할 수 있습니다.")
    elif not dry_names:
        sentences.append(
            f"12개월 모두 배당이 지급되지만, {peak_name}({round(peak_amt)}만원)에 집중 입금됩니다."
        )
    else:
        sentences.append(
            f"{', '.join(dry_names)}에는 배당 입금이 없으며, {peak_name}({round(peak_amt)}만원)에 집중됩니다."
        )

    return " ".join(sentences)


# ─── 단락 2: 자산 배분 전략 ─────────────────────────────────

def _para_strategy(recommendations, summary, macro, archetype) -> str:
    # 자산군별 비중 집계
    class_weights: dict[str, float] = {}
    for rec in recommendations:
        cls = rec.get("asset_class", "기타")
        class_weights[cls] = class_weights.get(cls, 0) + rec.get("weight_pct", 0)

    # 상위 3 자산군
    top_classes = sorted(class_weights.items(), key=lambda x: -x[1])[:3]
    top_str = ", ".join(
        f"{_CLASS_KR.get(c, c)} {round(w)}%"
        for c, w in top_classes
    )

    # 매크로 국면 — regime은 코드키(rate_pressure 등), label은 한국어 설명문
    macro_label = macro.get("regime", macro.get("label", "neutral"))
    macro_emoji = _MACRO_LABEL_EMOJI.get(macro_label, "")
    macro_desc  = macro.get("label", macro.get("description", ""))

    # 배당수익률
    avg_yield = summary.get("avg_yield", 0)
    avg_net   = summary.get("avg_yield_net", round(avg_yield * 0.85, 2))

    sentences = [
        f"포트폴리오는 {top_str}으로 구성되며, "
        f"포트폴리오 세전 평균 배당수익률 {avg_yield}%, 세후 {avg_net}%입니다.",
    ]

    # 아키타입 설명
    arch_descriptions = {
        "income_seeker":
            "현금흐름 극대화를 위해 고배당 자산 비중을 높이고, "
            "배당 컷 리스크를 분산하기 위한 ETF를 병행 편입했습니다.",
        "growth_dividend":
            "단기 배당보다 장기 배당성장에 초점을 맞춰, "
            "연평균 7~9% 배당성장이 가능한 ETF와 배당귀족주를 핵심으로 구성했습니다.",
        "balanced":
            "안정적 현금흐름과 배당성장을 균형 있게 배분하여, "
            "단기 수입과 장기 자산 증식을 동시에 추구합니다.",
    }
    arch_desc = arch_descriptions.get(archetype, "투자자의 위험성향에 맞게 자산이 배분되었습니다.")
    sentences.append(arch_desc)

    # 매크로 국면 반영 설명
    if macro_label != "neutral" and macro_label != "unknown":
        sentences.append(
            f"현재 시장 국면은 {macro_emoji}({macro_desc})으로, "
            "이에 맞춰 자산 비중이 전술적으로 조정되었습니다."
        )

    return " ".join(sentences)


# ─── 단락 3: 미래 시나리오 (인플레이션 포함) ────────────────

def _para_future(projection, investable, monthly_target,
                  monte_carlo=None, fire_plan=None) -> str:
    inf         = projection.get("inflation", {})
    nom_final   = projection.get("final_monthly_net", 0)
    real_final  = inf.get("real_final_monthly", 0)
    loss_pct    = inf.get("purchasing_power_loss_pct", 0)
    cagr        = projection.get("portfolio_div_cagr", 0)
    doubles_yr  = projection.get("milestones", {}).get("div_doubles_year")
    target_yr   = projection.get("milestones", {}).get("target_achieved_year")

    sentences = []

    # Monte Carlo 신뢰구간 우선 사용 (있을 때)
    if monte_carlo:
        p10 = monte_carlo.get("p10_final", 0)
        p50 = monte_carlo.get("p50_final", 0)
        p90 = monte_carlo.get("p90_final", 0)
        prob_2x  = monte_carlo.get("prob_doubles", 0)
        conf_tgt = monte_carlo.get("confidence_at_target", 0)
        exp_cuts = monte_carlo.get("expected_cut_events", 0)

        sentences.append(
            f"1,000회 Monte Carlo 시뮬레이션 결과, 20년 후 월 배당은 "
            f"중앙값 {round(p50)}만원 (비관 {round(p10)}만원 ~ 낙관 {round(p90)}만원, 80% 신뢰구간)입니다."
        )

        if prob_2x >= 70:
            sentences.append(f"✅ 현재 월배당 2배 달성 확률: {prob_2x}% — 높은 성장 신뢰도.")
        elif prob_2x >= 40:
            sentences.append(f"🟡 현재 월배당 2배 달성 확률: {prob_2x}%.")
        else:
            sentences.append(f"⚠️ 현재 월배당 2배 달성 확률 {prob_2x}% — 배당성장 자산 강화가 필요합니다.")

        if monthly_target > 0:
            emoji = "✅" if conf_tgt >= 70 else ("⚠️" if conf_tgt >= 30 else "❌")
            sentences.append(
                f"{emoji} 목표 월배당 {round(monthly_target)}만원 달성 확률: {conf_tgt}%."
            )

        if exp_cuts > 5:
            sentences.append(f"⚠️ 배당컷 예상 횟수 {exp_cuts}회 — 포트폴리오 분산으로 충격을 최소화하세요.")
    else:
        # Monte Carlo 없을 때 기존 단일 시나리오
        sentences.append(
            f"현재 배당성장률을 유지할 경우, 20년 후 월 배당은 명목 기준 약 {round(nom_final):,}만원으로 성장합니다."
        )
        if cagr > 0:
            sentences.append(f"포트폴리오 배당 CAGR은 연 {cagr}%로 추정됩니다.")
        if doubles_yr:
            sentences.append(f"현재 월배당의 2배 달성은 {doubles_yr}년 차가 예상됩니다.")

    # 인플레이션 — 항상 포함
    sentences.append(
        f"연 2.5% 인플레이션을 반영하면 20년 후 실질 구매력은 약 {round(real_final)}만원으로, "
        f"구매력이 {loss_pct}% 감소합니다."
    )

    # FIRE 역산 결과 통합
    if fire_plan:
        cs   = fire_plan.get("current_state", {})
        tgt  = fire_plan.get("targets", {})
        lean = tgt.get("lean", {})
        reg  = tgt.get("regular", {})
        fire_age = fire_plan.get("earliest_fire_age")
        target_age = cs.get("target_age", 50)

        if lean and lean.get("projected_fire_age"):
            la = lean["projected_fire_age"]
            if la <= target_age:
                sentences.append(
                    f"🎯 FIRE 분석: 린 파이어(월 {lean['monthly_target_nominal']}만원) "
                    f"{la}세 달성 가능 — 목표보다 {target_age - la}년 빠릅니다."
                )
            else:
                sentences.append(
                    f"🎯 FIRE 분석: 현재 속도로 {la}세에 린 파이어(월 {lean['monthly_target_nominal']}만원) 달성 예상 "
                    f"(목표 {target_age}세보다 {la - target_age}년 늦음)."
                )
        if reg and reg.get("monthly_pmt_needed", 0) > 0:
            pmt = reg["monthly_pmt_needed"]
            sentences.append(
                f"일반 파이어(월 {reg['monthly_target_nominal']}만원) 달성을 위해 "
                f"월 {pmt:,.0f}만원 추가 적립이 필요합니다."
            )

    return " ".join(sentences)


# ─── 단락 4: 리스크 ─────────────────────────────────────────

def _para_risk(stress_test, risk_alerts, sector_exposure, macro,
               monte_carlo=None, behavioral=None) -> str:
    """
    4단락: 리스크 경보 + 스트레스 테스트 + Monte Carlo 신뢰도 통합.

    monte_carlo 있을 때:
      - confidence_at_target: 목표 달성 신뢰도
      - expected_cut_events: 예상 배당컷 횟수
      - p10_final: 비관 시나리오 최종값
    """
    # 스트레스 테스트
    resilience  = stress_test.get("overall_resilience_score", 0)
    grade       = stress_test.get("overall_grade", "C")
    port_type   = stress_test.get("portfolio_type", "")
    scenarios   = stress_test.get("scenarios", {})

    # 최악 시나리오
    worst_scenario = None
    worst_loss = 0.0
    for sc_name, sc_data in scenarios.items():
        loss = sc_data.get("portfolio_loss_pct", 0)
        if abs(loss) > abs(worst_loss):
            worst_loss = loss
            worst_scenario = sc_data.get("name", sc_name)

    # 리스크 경보 종목
    broken   = [r for r in risk_alerts if r.get("signal") == "BROKEN"]
    danger   = [r for r in risk_alerts if r.get("signal") == "DANGER"]
    weak     = [r for r in risk_alerts if r.get("signal") == "WEAKENING"]

    # 섹터 집중도
    hhi = sector_exposure.get("hhi", 0)

    sentences = [
        f"스트레스 테스트 결과 포트폴리오 복원력 점수는 {resilience}점({grade}등급)으로, "
        f"{port_type} 특성을 보입니다.",
    ]

    if worst_scenario and worst_loss:
        sentences.append(
            f"역사적 위기 시나리오 중 '{worst_scenario}'에서 "
            f"최대 {round(abs(worst_loss))}% 자산 손실이 예상됩니다."
        )

    # ── Monte Carlo 리스크 보강 ──────────────────────────────────────
    if monte_carlo:
        conf_tgt  = monte_carlo.get("confidence_at_target", 0)
        exp_cuts  = monte_carlo.get("expected_cut_events", 0)
        p10_final = monte_carlo.get("p10_final", 0)
        p50_final = monte_carlo.get("p50_final", 0)

        # 비관 시나리오 하방 리스크
        if p50_final > 0 and p10_final > 0:
            downside_pct = round((1 - p10_final / p50_final) * 100, 1)
            sentences.append(
                f"Monte Carlo 비관 시나리오(P10) 기준, 20년 후 월배당은 중앙값 대비 "
                f"{downside_pct}% 낮을 수 있습니다 — 하방 리스크로 인식하세요."
            )

        # 배당 컷 경고
        if exp_cuts > 8:
            sentences.append(
                f"⚠️ 시뮬레이션상 20년간 예상 배당컷 {exp_cuts}회 — "
                "고배당주 비중 축소와 ETF 분산이 시급합니다."
            )
        elif exp_cuts > 4:
            sentences.append(
                f"💡 시뮬레이션상 배당컷 예상 {exp_cuts}회. "
                "ETF 비중 확대로 개별 종목 컷 충격을 분산하세요."
            )

    # ML 리스크 경보
    alert_parts = []
    if broken:
        names = ", ".join(r.get("ticker", "") for r in broken[:2])
        alert_parts.append(f"신호 붕괴 종목({names})")
    if danger:
        names = ", ".join(r.get("ticker", "") for r in danger[:2])
        alert_parts.append(f"배당 함정 위험 종목({names})")
    if weak:
        names = ", ".join(r.get("ticker", "") for r in weak[:2])
        alert_parts.append(f"신호 약화 종목({names})")

    if alert_parts:
        sentences.append(f"ML 분석에서 주의 종목이 감지되었습니다: {', '.join(alert_parts)}.")
    else:
        sentences.append("현재 포트폴리오 내 주요 리스크 경보는 없습니다.")

    # 섹터 집중도
    if hhi >= 3000:
        top_sector = sector_exposure.get("top_sector", "")
        top_pct    = sector_exposure.get("top_sector_pct", 0)
        sentences.append(
            f"섹터 집중도(HHI {hhi})가 높습니다. "
            f"{top_sector}에 {round(top_pct)}% 집중되어 있어 분산 검토가 필요합니다."
        )
    elif hhi > 0:
        sentences.append(f"섹터 분산도(HHI {hhi})는 양호한 수준입니다.")

    # 행동 편향 진단 결과 통합
    if behavioral:
        bias_cnt  = behavioral.get("bias_count", 0)
        high_sev  = behavioral.get("high_severity", 0)
        top_bias  = behavioral.get("top_bias", "")
        inv_type  = behavioral.get("investor_type", "")
        if high_sev >= 2:
            sentences.append(
                f"⚠️ 행동 편향 진단: {bias_cnt}가지 편향 탐지 (심각 {high_sev}개). "
                f"주요 편향 '{top_bias}'이 포트폴리오 수익률을 훼손할 수 있습니다."
            )
        elif bias_cnt >= 1:
            sentences.append(
                f"💡 행동 편향 진단 ({inv_type}): '{top_bias}' 경향 감지. 하단 행동 권고를 참고하세요."
            )

    return " ".join(sentences)


# ─── 단락 5: 행동 권고 ──────────────────────────────────────

def _para_action(risk_alerts, calendar, projection, monthly_target,
                investable, age, fire_plan=None) -> str:
    """
    5단락: 구체적 행동 권고.

    fire_plan 있을 때:
      - recommended_action: FIRE 엔진의 핵심 권고
      - targets.lean.monthly_pmt_needed: 린 파이어 달성 필요 월저축
      - earliest_fire_type: 현실적으로 가장 빨리 달성 가능한 FIRE 유형
    """
    broken   = [r for r in risk_alerts if r.get("signal") == "BROKEN"]
    danger   = [r for r in risk_alerts if r.get("signal") == "DANGER"]

    inf      = projection.get("inflation", {})
    loss_pct = inf.get("purchasing_power_loss_pct", 0)
    smooth   = calendar.get("smoothness_score", 0)
    dry      = calendar.get("dry_month_names", [])
    target_yr = projection.get("milestones", {}).get("target_achieved_year")

    actions = []
    step_num = 1

    # 즉시 교체 필요 종목
    if broken:
        tickers = ", ".join(r.get("ticker", "") for r in broken[:3])
        actions.append(f"① {tickers}는 ML 신호가 붕괴된 종목입니다. 즉시 교체를 권고합니다.")
        step_num = 2
    elif danger:
        tickers = ", ".join(r.get("ticker", "") for r in danger[:2])
        actions.append(f"① {tickers}는 배당 함정 위험이 있습니다. 비중 축소를 검토하세요.")
        step_num = 2

    # ── FIRE 엔진 행동 권고 통합 ────────────────────────────────────────
    if fire_plan:
        rec_action    = fire_plan.get("recommended_action", "")
        earliest_type = fire_plan.get("earliest_fire_type", "")
        earliest_age  = fire_plan.get("earliest_fire_age")
        tgts          = fire_plan.get("targets", {})
        lean          = tgts.get("lean", {})
        lean_pmt      = lean.get("monthly_pmt_needed", 0)
        lean_shortfall = lean.get("shortfall_만원", 0)

        nums = ["①", "②", "③", "④", "⑤", "⑥"]
        n = nums[min(step_num - 1, len(nums) - 1)]
        step_num += 1

        if earliest_type and earliest_age:
            type_kr = {"lean": "린 파이어", "regular": "일반 파이어", "fat": "팻 파이어"}.get(earliest_type, earliest_type)
            actions.append(
                f"{n} FIRE 목표: {type_kr}({earliest_age}세) 달성이 현재 경로에서 가장 빠릅니다. "
                + (f"월 {lean_pmt:,.0f}만원 추가 저축이 목표를 앞당깁니다." if lean_pmt > 0
                   else f"현재 저축 속도를 유지하면 목표 달성이 가능합니다.")
            )
        elif lean_shortfall > 0:
            n2 = nums[min(step_num - 1, len(nums) - 1)]
            step_num += 1
            actions.append(
                f"{n} 린 파이어 달성까지 원금 {lean_shortfall:,.0f}만원이 부족합니다. "
                "ISA 계좌를 활용한 추가 납입으로 세후 수익률을 높이세요."
            )

        if rec_action:
            actions.append(f"💡 FIRE 엔진 핵심 권고: {rec_action}")

    # 목표 달성 가속화 (FIRE 없을 때만)
    if not fire_plan and monthly_target > 0 and not target_yr:
        additional = round(monthly_target * 12 / 0.035)
        nums = ["①", "②", "③", "④", "⑤", "⑥"]
        n = nums[min(step_num - 1, len(nums) - 1)]
        step_num += 1
        actions.append(
            f"{n} 월 배당 목표 {round(monthly_target):,}만원 달성을 위해 "
            f"약 {additional:,}만원 추가 투자 또는 배당성장 ETF 비중 확대를 권장합니다."
        )

    # 인플레이션 방어
    if loss_pct >= 35:
        nums = ["①", "②", "③", "④", "⑤", "⑥"]
        n = nums[min(step_num - 1, len(nums) - 1)]
        step_num += 1
        actions.append(
            f"{n} 인플레이션 방어를 위해 SCHD, VIG 같은 배당성장형 ETF 비중을 "
            "전체의 30% 이상으로 유지하세요."
        )

    # 배당 공백 해소
    if dry:
        dry_str = ", ".join(dry[:3])
        nums = ["①", "②", "③", "④", "⑤", "⑥"]
        n = nums[min(step_num - 1, len(nums) - 1)]
        step_num += 1
        actions.append(
            f"{n} {dry_str} 배당 공백 해소를 위해 O(리얼티인컴) 또는 SGOV(월배당 채권 ETF) 추가를 검토하세요."
        )
    elif smooth < 50:
        nums = ["①", "②", "③", "④", "⑤", "⑥"]
        n = nums[min(step_num - 1, len(nums) - 1)]
        step_num += 1
        actions.append(
            f"{n} 분기 배당 쏠림 현상이 있습니다. JEPI 또는 448290(TIGER미국배당다우존스) "
            "편입으로 매월 균등 현금흐름을 확보하세요."
        )

    # 연령대별 리밸런싱 주기
    nums = ["①", "②", "③", "④", "⑤", "⑥"]
    n = nums[min(step_num - 1, len(nums) - 1)]
    if age >= 55:
        actions.append(f"{n} 은퇴 근접 구간입니다. 6개월마다 자산 비중을 점검하고, 안전자산 비중을 점진적으로 높이세요.")
    elif age >= 45:
        actions.append(f"{n} 반기 1회 리밸런싱을 권장합니다. 배당 컷 발생 시 즉시 교체 검토.")
    else:
        actions.append(f"{n} 분기 1회 리밸런싱으로 목표 비중을 유지하세요. 장기 복리를 위해 배당 재투자를 고려하세요.")

    if not actions:
        actions.append("현재 포트폴리오는 안정적인 상태입니다. 분기별 점검을 유지하세요.")

    return "\n".join(actions)


# ─── 헤드라인 생성 ──────────────────────────────────────────

def _make_headline(summary, living, projection, age) -> str:
    annual     = summary.get("total_annual_net", 0)
    monthly    = round(annual / 12, 0) if annual else 0
    coverage   = living.get("current_coverage_pct", 0)
    milestone  = living.get("current_label", "")
    doubles_yr = projection.get("milestones", {}).get("div_doubles_year")

    if coverage >= 100:
        return f"🎉 생활비 100% 배당 커버 달성 — 월 {int(monthly):,}만원 배당 포트폴리오"
    elif coverage >= 50:
        return (
            f"월 {int(monthly):,}만원 배당 | 생활비 {coverage}% 커버 "
            f"| {doubles_yr}년 후 2배 성장"
            if doubles_yr else
            f"월 {int(monthly):,}만원 배당 | 생활비 {coverage}% 커버 | {milestone}"
        )
    else:
        return (
            f"월 {int(monthly):,}만원 배당 시작 | {milestone} "
            f"| {doubles_yr}년 후 2배"
            if doubles_yr else
            f"월 {int(monthly):,}만원 배당 시작 — {age}세 배당 자산 구축 1단계"
        )

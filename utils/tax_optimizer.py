"""
utils/tax_optimizer.py — 세금 최적화 엔진
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  배당 투자자에게 세금은 수익률의 숨은 적이다.
  예를 들어 연 배당 2,100만원 vs 1,900만원은 단순 200만원 차이가 아니라
  금융소득종합과세 임계점(2,000만원)을 넘느냐 마느냐의 차이로,
  한계세율 최대 49.5%가 적용될 수 있다.

  이 엔진이 하는 일:
  1. 금융소득종합과세 진단 — 현재/미래 임계점 초과 여부 + 초과 세금 추정
  2. ISA 계좌 최적 배분 — 연 2,000만원 한도 내에서 최대 절세 자산 우선 편입
  3. 연금저축 + IRP 세액공제 전략 — 총급여 구간별 공제율 적용
  4. 실효세율 계산 및 절세 시뮬레이션
  5. 우선순위별 세금 최적화 액션 목록

반환:
{
    "comprehensive_tax": {
        "annual_div_gross_만원":    float,  # 현재 연 배당 세전 추정
        "threshold_gap_만원":       float,  # 2,000만원까지 남은 여유 (음수면 초과)
        "is_over_threshold":        bool,   # 종합과세 대상 여부
        "estimated_extra_tax_만원": float,  # 초과 구간 추가 세금 추정
        "risk_level":               str,    # "safe" / "caution" / "danger"
        "risk_label":               str,    # 한국어 레이블
        "projected_over_year":      int,    # 몇 년 후 임계점 초과 예상 (None=안전)
    },
    "isa_strategy": {
        "annual_limit_만원":        int,    # 1800 (일반형)
        "total_limit_만원":         int,    # 20000 (일반형/청년형 동일 — 2026년 상향)
        "tax_free_limit_만원":      int,    # 500 (일반) / 1000 (청년·서민 — 2026년 상향)
        "recommended_assets":       list,   # ISA에 넣으면 가장 절세되는 종목 목록
        "annual_tax_saving_만원":   float,  # ISA 활용 시 연간 절세 효과
        "action":                   str,    # 구체적 ISA 활용 제안
    },
    "pension_strategy": {
        "pension_savings_limit_만원": int,  # 600
        "irp_combined_limit_만원":    int,  # 900
        "deduction_rate":             float,# 0.12 or 0.15
        "max_deduction_만원":         float,# 최대 세액공제 금액
        "recommended_annual_납입":    float,# 권장 납입액
        "annual_tax_saving_만원":     float,# 연금저축 절세 효과
        "action":                     str,
    },
    "effective_tax_rate_pct":   float,  # 현재 실효 배당세율
    "optimized_tax_rate_pct":   float,  # 최적화 후 실효세율
    "total_annual_saving_만원": float,  # ISA + 연금저축 합산 연간 절세
    "5yr_cumulative_saving_만원": float,
    "priority_actions":         list[dict],  # [{rank, category, action, saving_만원}]
    "tax_health_score":         int,    # 0~100 (세금 건강도)
    "summary_message":          str,
}
"""

from __future__ import annotations

# ── 상수 ─────────────────────────────────────────────────────────────────────

# 금융소득종합과세 임계점
COMPREHENSIVE_TAX_THRESHOLD = 2_000  # 만원 (2,000만원)

# 종합소득세 구간 (2024년 기준, 과세표준)
INCOME_TAX_BRACKETS = [
    (1_400,   0.06),
    (5_000,   0.15),
    (8_800,   0.24),
    (15_000,  0.35),
    (30_000,  0.38),
    (50_000,  0.40),
    (100_000, 0.42),
    (float("inf"), 0.45),
]

# 배당소득세 기본 분리과세율
DIVIDEND_WITHHOLDING_RATE = 0.154  # 14% + 1.4% 지방소득세

# ── ISA 계좌 한도 (2026년 개정 세법 기준) ─────────────────────
# 개정 내용:
#   납입한도: 연 2,000만원 → 4,000만원 상향
#   총 한도:  일반형 1억원 → 2억원 상향
#   비과세:   일반형 200만원 → 500만원 / 청년형 400만원 → 1,000만원
#   근거: 2026 세법개정안 (금투세 폐지 + ISA 활성화 정책)
ISA_ANNUAL_LIMIT         = 4_000   # 만원 (연 납입 한도 — 2026년 상향)
ISA_TOTAL_LIMIT_GENERAL  = 20_000  # 만원 (일반형 누적 한도 — 2026년 상향)
ISA_TOTAL_LIMIT_YOUTH    = 20_000  # 만원 (청년·서민형 누적 한도)
ISA_TAX_FREE_GENERAL     = 500     # 만원 (일반형 비과세 한도 — 2026년 상향)
ISA_TAX_FREE_YOUTH       = 1_000   # 만원 (청년·서민형 비과세 한도 — 2026년 상향)
# ISA 초과분 세율: 9.9% (분리과세 9% + 지방 0.9%)
ISA_EXCESS_TAX_RATE = 0.099

# 연금저축 + IRP 세액공제 (2024년 기준)
PENSION_LIMIT_SAVINGS    = 600   # 만원 (연금저축만)
PENSION_LIMIT_WITH_IRP   = 900   # 만원 (연금저축 + IRP 합산)
PENSION_DEDUCTION_RATE_HIGH  = 0.15  # 총급여 5,500만원 이하
PENSION_DEDUCTION_RATE_LOW   = 0.12  # 총급여 5,500만원 초과
PENSION_INCOME_THRESHOLD = 5_500   # 만원 (총급여 기준)

# 자산군별 세금 효율성 (높을수록 ISA 우선 편입)
_ASSET_TAX_PRIORITY = {
    "us_reit":    10,   # REIT 배당: 세전 지급, 분리과세 대상 → ISA 최우선
    "us_div_etf": 9,    # 미국 ETF: 배당소득세 + 매매차익 과세
    "us_stock":   8,    # 미국 개별주: 배당 + 차익 모두 과세
    "kr_reit":    7,    # 국내 리츠: 배당소득세
    "defensive":  6,    # 채권 ETF: 이자소득세
    "kr_etf":     5,    # 국내 ETF: 매매차익 비과세(상장), 배당소득세
    "kr_stock":   3,    # 국내 주식: 매매차익 비과세, 배당소득세
}


# ─────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ─────────────────────────────────────────────────────────────────────────────

def calc_tax_optimizer(
    recommendations:  list[dict],
    investable_amount: float,
    annual_income_만원: float = 5_000,   # 총급여 (연금저축 공제율 결정)
    current_age:      int   = 35,
    div_cagr:         float = 5.0,       # 배당 성장률 (임계점 초과 예상 연도)
    isa_already_used_만원: float = 0,    # 기존 ISA 납입 잔액
    has_pension_savings: bool = False,   # 연금저축 계좌 보유 여부
    has_irp:          bool = False,      # IRP 계좌 보유 여부
    is_youth_isa:     bool = False,      # 청년·서민형 ISA 여부
) -> dict:
    """
    세금 최적화 엔진 메인 함수.

    Args:
        recommendations:       포트폴리오 추천 종목 리스트
        investable_amount:     총 투자금 (만원)
        annual_income_만원:    총급여 (만원, 연금저축 공제율 결정용)
        current_age:           현재 나이
        div_cagr:              배당 성장률 (%)
        isa_already_used_만원: 기존 ISA 납입액 (남은 한도 계산)
        has_pension_savings:   연금저축 계좌 보유 여부
        has_irp:               IRP 계좌 보유 여부
        is_youth_isa:          청년(만 19~34세)·서민형 ISA 해당 여부

    반환: 상단 docstring 참조
    """

    # ── Step 1: 연간 배당 세전 추정 ──────────────────────────────────────────
    annual_gross, annual_net = _calc_annual_dividend(recommendations, investable_amount)

    # ── Step 2: 금융소득종합과세 진단 ────────────────────────────────────────
    comp_tax = _calc_comprehensive_tax(annual_gross, div_cagr, current_age)

    # ── Step 3: ISA 최적 배분 전략 ───────────────────────────────────────────
    isa = _calc_isa_strategy(
        recommendations, investable_amount, annual_gross,
        isa_already_used_만원, is_youth_isa,
    )

    # ── Step 4: 연금저축 + IRP 전략 ──────────────────────────────────────────
    pension = _calc_pension_strategy(
        annual_income_만원, has_pension_savings, has_irp
    )

    # ── Step 5: 실효세율 계산 ────────────────────────────────────────────────
    eff_rate  = round(DIVIDEND_WITHHOLDING_RATE * 100, 2) if annual_gross == 0 else \
                round((annual_gross - annual_net) / annual_gross * 100, 2) if annual_gross > 0 else 14.0

    # 최적화 후 실효세율 (ISA 비과세 한도 적용)
    isa_tax_free = isa.get("tax_free_limit_만원", ISA_TAX_FREE_GENERAL)
    isa_saving   = isa.get("annual_tax_saving_만원", 0)
    pension_saving = pension.get("annual_tax_saving_만원", 0)
    total_saving   = round(isa_saving + pension_saving, 2)

    # ISA 절세분만 배당소득세 감소에 반영 (연금저축은 소득세 별도 공제)
    opt_rate  = round(
        (annual_gross * DIVIDEND_WITHHOLDING_RATE - isa_saving) / annual_gross * 100, 2
    ) if annual_gross > 0 else 14.0

    # ── Step 6: 우선순위 액션 목록 ───────────────────────────────────────────
    actions = _build_priority_actions(
        comp_tax, isa, pension,
        annual_gross, annual_income_만원,
        has_pension_savings, has_irp, current_age,
    )

    # ── Step 7: 세금 건강 점수 ───────────────────────────────────────────────
    health_score = _calc_tax_health_score(
        comp_tax, isa, pension,
        eff_rate, annual_income_만원,
    )

    # ── Step 8: 5년 누적 절세 ────────────────────────────────────────────────
    cumulative_5yr = round(total_saving * 5, 1)

    summary_msg = _build_summary_message(
        annual_gross, comp_tax, total_saving, health_score
    )

    return {
        "comprehensive_tax":        comp_tax,
        "isa_strategy":             isa,
        "pension_strategy":         pension,
        "effective_tax_rate_pct":   eff_rate,
        "optimized_tax_rate_pct":   max(0.0, opt_rate),
        "total_annual_saving_만원": total_saving,
        "5yr_cumulative_saving_만원": cumulative_5yr,
        "priority_actions":         actions,
        "tax_health_score":         health_score,
        "summary_message":          summary_msg,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 내부 헬퍼 함수
# ─────────────────────────────────────────────────────────────────────────────

def _calc_annual_dividend(
    recommendations: list[dict],
    investable: float,
) -> tuple[float, float]:
    """세전/세후 연간 배당 추정 (만원)."""
    gross = 0.0
    net   = 0.0
    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0

    for rec in recommendations:
        weight = rec.get("weight_pct", 0) / 100
        invest = investable * weight
        if "invest_amount_만원" in rec:
            invest = rec["invest_amount_만원"]

        # 수익률 fallback
        raw_y = (
            rec.get("gross_yield_pct")
            or rec.get("net_yield_pct")
            or rec.get("dividend_yield")
            or 0
        )
        gross_y = float(raw_y) / 100
        net_y   = gross_y * (1 - DIVIDEND_WITHHOLDING_RATE)

        gross += invest * gross_y
        net   += invest * net_y

    return round(gross, 2), round(net, 2)


def _calc_comprehensive_tax(
    annual_gross: float,
    div_cagr: float,
    current_age: int,
) -> dict:
    """금융소득종합과세 진단."""
    threshold    = COMPREHENSIVE_TAX_THRESHOLD
    gap          = round(threshold - annual_gross, 2)
    is_over      = annual_gross > threshold
    extra_tax    = 0.0
    risk_level   = "safe"
    risk_label   = "안전"
    projected_yr = None

    if is_over:
        # 종합과세: 초과분이 다른 소득(근로소득 등)과 합산되어 높은 한계세율 적용
        # 보수적 추정: 초과분(over_amount)이 중간 소득구간(24~35%)에 걸린다고 가정
        over_amount  = annual_gross - threshold
        # 총합산소득(근로+배당)을 고려한 한계세율 (단순 추정: 초과분 × 24% 적용)
        est_marginal = 0.24  # 일반 직장인 + 배당 종합과세 진입 시 최소 한계세율
        # 이미 원천징수된 세금(14%)과의 차액 = 추가 납부세액
        extra_tax    = round(over_amount * max(0, est_marginal - DIVIDEND_WITHHOLDING_RATE), 2)
        risk_level   = "danger"
        risk_label   = "위험 — 종합과세 대상"
    elif gap <= 200:
        risk_level = "caution"
        risk_label = "주의 — 임계점 근접 (200만원 이내)"
    elif gap <= 500:
        risk_level = "caution"
        risk_label = "주의 — 임계점 근접 (500만원 이내)"

    # 몇 년 후 임계점 초과 예상
    if not is_over and div_cagr > 0:
        y = annual_gross
        for t in range(1, 31):
            y *= (1 + div_cagr / 100)
            if y > threshold:
                projected_yr = current_age + t
                break

    return {
        "annual_div_gross_만원":    annual_gross,
        "threshold_gap_만원":       gap,
        "is_over_threshold":        is_over,
        "estimated_extra_tax_만원": extra_tax,
        "risk_level":               risk_level,
        "risk_label":               risk_label,
        "projected_over_year":      projected_yr,  # 임계점 초과 예상 나이
    }


def _calc_isa_strategy(
    recommendations: list[dict],
    investable: float,
    annual_gross: float,
    already_used_만원: float,
    is_youth: bool,
) -> dict:
    """ISA 계좌 최적 배분 전략."""
    # ISA 한도 결정
    total_limit    = ISA_TOTAL_LIMIT_YOUTH   if is_youth else ISA_TOTAL_LIMIT_GENERAL
    tax_free_limit = ISA_TAX_FREE_YOUTH      if is_youth else ISA_TAX_FREE_GENERAL
    annual_limit   = ISA_ANNUAL_LIMIT

    remaining_total = max(0, total_limit - already_used_만원)
    usable_annual   = min(annual_limit, remaining_total)

    # 세금 우선도 기준으로 자산 정렬
    sorted_recs = sorted(
        recommendations,
        key=lambda r: -_ASSET_TAX_PRIORITY.get(r.get("asset_class", ""), 0)
    )

    # ISA 우선 편입 자산 추천 (비중 기준으로 큰 것부터)
    recommended_assets = []
    isa_allocated = 0.0
    annual_saving = 0.0

    for rec in sorted_recs:
        ticker    = rec.get("ticker", "")
        name      = rec.get("name", ticker)
        cls       = rec.get("asset_class", "")
        weight    = rec.get("weight_pct", 0) / 100
        invest    = investable * weight
        priority  = _ASSET_TAX_PRIORITY.get(cls, 0)

        if priority < 5:
            continue  # 국내주식 등 세금 혜택 낮은 자산 제외

        # ISA 한도 내 편입 가능 금액
        can_put = min(invest, usable_annual - isa_allocated)
        if can_put <= 0:
            break

        isa_allocated += can_put

        # 이 자산을 ISA에 넣었을 때 절세 효과
        raw_y   = float(rec.get("gross_yield_pct") or rec.get("dividend_yield") or 0) / 100
        div_isa = can_put * raw_y
        # ISA 비과세 한도 내 세금 절감 = 원천세 전액 면제
        saving  = min(div_isa, tax_free_limit - annual_saving) * DIVIDEND_WITHHOLDING_RATE
        saving  = max(0, saving)
        annual_saving += saving

        recommended_assets.append({
            "ticker":             ticker,
            "name":               name,
            "asset_class":        cls,
            "invest_만원":        round(can_put, 1),
            "priority_score":     priority,
            "estimated_saving_만원": round(saving, 2),
        })

    annual_saving = round(annual_saving, 2)

    if usable_annual <= 0:
        action = "ISA 누적 한도를 모두 사용했습니다. 만기 후 재가입(의무보유 3년)을 계획하세요."
    elif annual_gross < 100:
        action = (
            f"현재 배당 규모({annual_gross:.1f}만원)에서는 ISA 절세 효과가 크지 않습니다. "
            "투자 규모 확대 후 ISA 편입을 우선 계획하세요."
        )
    elif recommended_assets:
        top = recommended_assets[0]
        action = (
            f"ISA 계좌에 {top['name']}({top['ticker']}) 등 고수익 자산을 우선 편입하세요. "
            f"연 {annual_saving:.1f}만원 절세 효과가 예상됩니다."
        )
    else:
        action = "세금 효율이 높은 자산을 ISA 계좌에 우선 편입하면 절세 효과를 극대화할 수 있습니다."

    return {
        "annual_limit_만원":       annual_limit,
        "total_limit_만원":        total_limit,
        "tax_free_limit_만원":     tax_free_limit,
        "remaining_capacity_만원": round(remaining_total, 1),
        "recommended_assets":      recommended_assets,
        "annual_tax_saving_만원":  annual_saving,
        "action":                  action,
    }


def _calc_pension_strategy(
    annual_income_만원: float,
    has_pension_savings: bool,
    has_irp: bool,
) -> dict:
    """연금저축 + IRP 세액공제 전략."""
    # 공제율 결정
    deduction_rate = (
        PENSION_DEDUCTION_RATE_HIGH
        if annual_income_만원 <= PENSION_INCOME_THRESHOLD
        else PENSION_DEDUCTION_RATE_LOW
    )

    # 최대 공제 한도
    if has_irp:
        max_납입 = PENSION_LIMIT_WITH_IRP    # 900만원
        limit_label = "연금저축+IRP 합산 900만원"
    else:
        max_납입 = PENSION_LIMIT_SAVINGS      # 600만원
        limit_label = "연금저축 600만원"

    max_deduction = round(max_납입 * deduction_rate, 2)

    # 권장 납입 (연소득 대비 10% or 한도 중 작은 값)
    recommended_납입 = min(max_납입, round(annual_income_만원 * 0.10))

    # 실제 세액공제
    annual_saving = round(recommended_납입 * deduction_rate, 2)

    if not has_pension_savings and not has_irp:
        action = (
            f"연금저축 계좌를 개설하면 연 최대 {max_납입:,}만원 납입으로 "
            f"{max_deduction:,.0f}만원 세액공제를 받을 수 있습니다. "
            "IRP 추가 시 절세 한도가 900만원으로 확대됩니다."
        )
    elif has_pension_savings and not has_irp:
        action = (
            f"IRP 계좌를 추가 개설하면 세액공제 한도가 600만원 → 900만원으로 늘어납니다. "
            f"추가 300만원 납입 시 {round(300 * deduction_rate):,}만원 추가 세액공제."
        )
    else:
        action = (
            f"연금저축+IRP 최적 배분: 연금저축 600만원 + IRP 300만원. "
            f"총 {max_납입:,}만원 납입으로 연 {max_deduction:,.0f}만원 세액공제 가능합니다."
        )

    return {
        "pension_savings_limit_만원": PENSION_LIMIT_SAVINGS,
        "irp_combined_limit_만원":    PENSION_LIMIT_WITH_IRP,
        "deduction_rate":             deduction_rate,
        "max_deduction_만원":         max_deduction,
        "recommended_annual_납입_만원": recommended_납입,
        "annual_tax_saving_만원":     annual_saving,
        "limit_label":                limit_label,
        "action":                     action,
    }


def _get_marginal_rate(over_amount_만원: float) -> float:
    """종합소득세 최소 한계세율 추정 (초과분만 독립 계산 시)."""
    cumulative = 0.0
    for threshold, rate in INCOME_TAX_BRACKETS:
        if over_amount_만원 <= threshold - cumulative:
            return rate
        cumulative = threshold
    return 0.45


def _build_priority_actions(
    comp_tax: dict,
    isa: dict,
    pension: dict,
    annual_gross: float,
    annual_income: float,
    has_pension: bool,
    has_irp: bool,
    current_age: int,
) -> list[dict]:
    """우선순위별 세금 최적화 액션 목록."""
    actions = []
    rank = 1

    # ① 금융소득종합과세 위기 대응
    if comp_tax["is_over_threshold"]:
        actions.append({
            "rank":          rank,
            "category":      "종합과세",
            "urgency":       "즉시",
            "action":        (
                f"연간 배당 {annual_gross:.0f}만원이 종합과세 기준(2,000만원)을 초과했습니다. "
                "ISA 계좌로 고배당 자산을 이전하거나, 가족 증여를 통한 분산을 검토하세요."
            ),
            "saving_만원":   comp_tax["estimated_extra_tax_만원"],
        })
        rank += 1
    elif comp_tax["risk_level"] == "caution":
        projected = comp_tax.get("projected_over_year")
        actions.append({
            "rank":          rank,
            "category":      "종합과세 예방",
            "urgency":       "6개월 내",
            "action":        (
                f"배당이 성장하면 {projected}세경 종합과세 대상이 됩니다. "
                "지금부터 ISA·연금저축으로 배당소득을 분산하세요."
            ),
            "saving_만원":   0,
        })
        rank += 1

    # ② ISA 미개설 시
    if isa.get("annual_tax_saving_만원", 0) > 0:
        actions.append({
            "rank":        rank,
            "category":    "ISA 계좌",
            "urgency":     "3개월 내",
            "action":      isa["action"],
            "saving_만원": isa["annual_tax_saving_만원"],
        })
        rank += 1

    # ③ 연금저축 미개설 또는 IRP 추가
    if not has_pension:
        actions.append({
            "rank":        rank,
            "category":    "연금저축",
            "urgency":     "연말 전",
            "action":      pension["action"],
            "saving_만원": pension["annual_tax_saving_만원"],
        })
        rank += 1
    elif not has_irp:
        irp_saving = round(300 * pension["deduction_rate"], 2)
        actions.append({
            "rank":        rank,
            "category":    "IRP 추가",
            "urgency":     "연말 전",
            "action":      pension["action"],
            "saving_만원": irp_saving,
        })
        rank += 1

    # ④ 연령별 연금 인출 전략 (50세 이상)
    if current_age >= 50:
        actions.append({
            "rank":        rank,
            "category":    "연금 인출 전략",
            "urgency":     "계획 수립",
            "action":      (
                "연금 수령 시 분리과세(3.3~5.5%)가 적용됩니다. "
                "연 1,500만원 이하로 분할 인출하면 저율과세 유지가 가능합니다."
            ),
            "saving_만원": 0,
        })
        rank += 1

    # ⑤ 국내주식 손익통산 (12월 전략)
    actions.append({
        "rank":        rank,
        "category":    "손익통산",
        "urgency":     "연말 12월",
        "action":      (
            "12월 전 평가손실 종목을 실현 매도하면 배당소득과 손익통산이 가능합니다. "
            "단, 금융소득 과세 방식에 따라 절세 효과가 다를 수 있습니다."
        ),
        "saving_만원": 0,
    })

    return actions


def _calc_tax_health_score(
    comp_tax: dict,
    isa: dict,
    pension: dict,
    eff_rate: float,
    annual_income: float,
) -> int:
    """세금 건강도 점수 (0~100)."""
    score = 100

    # 종합과세 패널티
    if comp_tax["is_over_threshold"]:
        score -= 30
    elif comp_tax["risk_level"] == "caution":
        score -= 15

    # ISA 미활용 패널티
    if isa.get("annual_tax_saving_만원", 0) == 0:
        score -= 15
    elif isa.get("annual_tax_saving_만원", 0) < 5:
        score -= 5

    # 연금저축 미활용 패널티
    if pension.get("annual_tax_saving_만원", 0) == 0:
        score -= 15
    elif pension.get("annual_tax_saving_만원", 0) < 36:
        score -= 5

    # 실효세율이 높을수록 감점
    if eff_rate > 20:
        score -= 10
    elif eff_rate > 15:
        score -= 5

    return max(0, min(100, score))


def _build_summary_message(
    annual_gross: float,
    comp_tax: dict,
    total_saving: float,
    health_score: int,
) -> str:
    """세금 최적화 요약 메시지."""
    if comp_tax["is_over_threshold"]:
        return (
            f"⚠️ 연 배당 {annual_gross:.0f}만원으로 금융소득 종합과세 대상입니다. "
            f"ISA·연금저축 활용 시 연 {total_saving:.1f}만원 절세 가능 (세금 건강 점수 {health_score}점)."
        )
    elif comp_tax["risk_level"] == "caution":
        return (
            f"💡 배당 성장에 따라 {comp_tax.get('projected_over_year', '?')}세경 종합과세 예상. "
            f"지금부터 절세 구조를 갖추면 연 {total_saving:.1f}만원 이상 절세됩니다 (세금 건강 {health_score}점)."
        )
    elif total_saving > 0:
        return (
            f"✅ 현재 세금 리스크 낮음. ISA + 연금저축 최적화로 연 {total_saving:.1f}만원 추가 절세 가능 "
            f"(세금 건강 {health_score}점)."
        )
    else:
        return f"✅ 세금 구조 최적화 상태 (세금 건강 {health_score}점). 연간 점검을 권장합니다."

"""
나이·월급·여유자금 기반 배당 포트폴리오 시뮬레이터.

핵심 기능
  1. 나이 입력 → 은퇴까지 남은 기간 자동 계산
  2. 월급 입력 → 배당 목표 선택지 자동 제시 (30% / 50% / 100%)
  3. 여유자금 입력 → 초기 포트폴리오로 즉시 반영
  4. 역계산 → "목표 달성하려면 월 얼마 투자해야 하나"

계산 원칙
  - 배당 재투자 (DRIP): 세후 배당금 전액 재투자
  - 배당소득세 15.4% (일반) / 0% (ISA, 단순화)
  - 배당 성장률 기본 3%/년 (보수적)
  - 여유자금은 Day 0에 포트폴리오에 투입된 것으로 가정
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


TAX_RATE_GENERAL        = 0.154
TAX_RATE_ISA            = 0.0
DIVIDEND_GROWTH_DEFAULT = 0.03
DEFAULT_RETIRE_AGE      = 65


# ─────────────────────────────────────────────────────────────
# 1. 입력 구조체
# ─────────────────────────────────────────────────────────────

@dataclass
class SimulationInput:
    # ── 필수 ──
    monthly_invest: int           # 월 투자금 (원). 역계산 모드에서는 0 입력 가능.
    target_monthly_dividend: int  # 목표 월 배당금 (원)
    initial_yield: float          # 포트폴리오 평균 배당수익률 (%)

    # ── 나이 관련 (선택) ──
    current_age: int   = 0        # 현재 나이. 0이면 나이 맥락 무시.
    retire_age:  int   = DEFAULT_RETIRE_AGE

    # ── 월급 (선택) ──
    monthly_salary: int = 0       # 세후 월 급여 (원). 0이면 생략.

    # ── 여유자금 (선택) ──
    existing_assets: float = 0    # 이미 투자 가능한 초기 자산 (원)

    # ── 시뮬레이션 파라미터 ──
    dividend_growth_rate: float = DIVIDEND_GROWTH_DEFAULT
    projection_years:     int   = 0   # 0이면 나이에서 자동 계산
    use_isa:              bool  = False

    def __post_init__(self):
        # projection_years 자동 계산
        if self.projection_years == 0:
            if self.current_age > 0 and self.current_age < self.retire_age:
                self.projection_years = self.retire_age - self.current_age
            else:
                self.projection_years = 20   # 기본값


# ─────────────────────────────────────────────────────────────
# 2. 연도별 결과 구조체
# ─────────────────────────────────────────────────────────────

@dataclass
class YearResult:
    year: int
    age: int | None               # 해당 연도 나이 (current_age=0이면 None)
    invested_cumulative: float    # 누적 투자 원금 (원, 여유자금 포함)
    portfolio_value: float        # 포트폴리오 총 가치 (원)
    annual_dividend_gross: float  # 세전 연간 배당금 (원)
    annual_dividend_net: float    # 세후 연간 배당금 (원)
    monthly_dividend_net: float   # 세후 월 평균 배당금 (원)
    effective_yield: float        # 해당 연도 유효 배당수익률 (%)
    goal_achieved: bool           # 목표 월 배당 달성 여부


# ─────────────────────────────────────────────────────────────
# 3. 순방향 시뮬레이션
# ─────────────────────────────────────────────────────────────

def simulate(inp: SimulationInput) -> list[YearResult]:
    """
    연도별 배당 시뮬레이션 (순방향).
    여유자금이 있으면 Day 0에 포트폴리오에 투입.
    """
    tax_rate   = TAX_RATE_ISA if inp.use_isa else TAX_RATE_GENERAL
    annual_inv = inp.monthly_invest * 12
    target_ann = inp.target_monthly_dividend * 12

    # 여유자금: 시작 시점에 이미 포트폴리오로 투입된 것으로 가정
    portfolio         = float(inp.existing_assets)
    cumulative_invest = float(inp.existing_assets)   # 여유자금도 원금 누계에 포함

    results = []

    for yr in range(1, inp.projection_years + 1):
        # 이 해의 배당수익률 (배당 성장 반영)
        cur_yield_pct = inp.initial_yield * ((1 + inp.dividend_growth_rate) ** (yr - 1))

        # 연초 월급에서 투자
        portfolio         += annual_inv
        cumulative_invest += annual_inv

        # 연간 배당 (세전)
        gross_div = portfolio * cur_yield_pct / 100

        # 세후 배당
        net_div = gross_div * (1 - tax_rate)

        # 배당 재투자 (DRIP)
        portfolio += net_div

        # 나이 계산
        age = (inp.current_age + yr) if inp.current_age > 0 else None

        results.append(YearResult(
            year=yr,
            age=age,
            invested_cumulative=cumulative_invest,
            portfolio_value=portfolio,
            annual_dividend_gross=gross_div,
            annual_dividend_net=net_div,
            monthly_dividend_net=net_div / 12,
            effective_yield=cur_yield_pct,
            goal_achieved=(net_div >= target_ann),
        ))

    return results


# ─────────────────────────────────────────────────────────────
# 4. 역계산: 목표 달성을 위한 필요 월 투자금
# ─────────────────────────────────────────────────────────────

def find_required_monthly_invest(
    target_monthly_div: int,
    years: int,
    initial_yield: float,
    dividend_growth_rate: float = DIVIDEND_GROWTH_DEFAULT,
    existing_assets: float = 0,
    use_isa: bool = False,
) -> int:
    """
    목표 월 배당금을 years년 안에 달성하기 위해
    매달 얼마를 투자해야 하는지 역계산.

    이진탐색으로 O(log N) 수렴.
    existing_assets: 이미 보유한 여유자금 (원).
    """
    def achieves(monthly: int) -> bool:
        inp = SimulationInput(
            monthly_invest=monthly,
            target_monthly_dividend=target_monthly_div,
            initial_yield=initial_yield,
            dividend_growth_rate=dividend_growth_rate,
            existing_assets=existing_assets,
            projection_years=years,
            use_isa=use_isa,
        )
        results = simulate(inp)
        return results[-1].goal_achieved

    # 이진탐색 범위: 1만원 ~ 5천만원/월
    lo, hi = 10_000, 50_000_000
    if not achieves(hi):
        return -1   # 5천만원으로도 불가 (수익률 자체가 너무 낮거나 기간 너무 짧음)

    while lo < hi:
        mid = (lo + hi) // 2
        if achieves(mid):
            hi = mid
        else:
            lo = mid + 1

    # 만원 단위 올림
    return math.ceil(lo / 10_000) * 10_000


# ─────────────────────────────────────────────────────────────
# 5. 목표 선택지 세트 계산
# ─────────────────────────────────────────────────────────────

def build_goal_scenarios(
    monthly_salary: int,
    years: int,
    initial_yield: float,
    dividend_growth_rate: float = DIVIDEND_GROWTH_DEFAULT,
    existing_assets: float = 0,
    use_isa: bool = False,
) -> list[dict]:
    """
    월급 기준으로 배당 목표 선택지 3개 생성 + 역계산.

    반환 예시:
      [
        {"label": "월급의 30% (90만원)", "target": 900_000, "required_monthly": 120_000},
        {"label": "월급의 50% (150만원)", "target": 1_500_000, "required_monthly": 210_000},
        {"label": "월급 전액 대체 (300만원)", "target": 3_000_000, "required_monthly": 450_000},
      ]
    """
    ratios = [
        (0.30, "월급의 30%"),
        (0.50, "월급의 50%"),
        (1.00, "월급 전액 대체"),
    ]
    scenarios = []
    for ratio, label_prefix in ratios:
        target = int(monthly_salary * ratio)
        required = find_required_monthly_invest(
            target_monthly_div=target,
            years=years,
            initial_yield=initial_yield,
            dividend_growth_rate=dividend_growth_rate,
            existing_assets=existing_assets,
            use_isa=use_isa,
        )
        scenarios.append({
            "label":    f"{label_prefix} ({target/1e4:.0f}만원/월)",
            "target":   target,
            "required_monthly": required,
        })
    return scenarios


# ─────────────────────────────────────────────────────────────
# 6. 리포트 출력
# ─────────────────────────────────────────────────────────────

def find_goal_year(results: list[YearResult]) -> int | None:
    for r in results:
        if r.goal_achieved:
            return r.year
    return None


def format_report(inp: SimulationInput, results: list[YearResult]) -> str:
    goal_year = find_goal_year(results)
    tax_label = "ISA(비과세)" if inp.use_isa else "일반(15.4%)"

    lines = ["═" * 58, " 배당 포트폴리오 성장 시뮬레이션", "═" * 58]

    # ── 기본 입력 요약 ──
    if inp.current_age > 0:
        lines.append(f"  현재 나이:      {inp.current_age}세  →  은퇴 목표: {inp.retire_age}세")
        lines.append(f"  투자 가능 기간: {inp.projection_years}년")
    if inp.monthly_salary > 0:
        ratio = inp.target_monthly_dividend / inp.monthly_salary * 100
        lines.append(f"  월 급여:        {inp.monthly_salary/1e4:,.0f}만원")
        lines.append(f"  목표 월 배당:   {inp.target_monthly_dividend/1e4:,.0f}만원  (월급의 {ratio:.0f}%)")
    else:
        lines.append(f"  목표 월 배당:   {inp.target_monthly_dividend/1e4:,.0f}만원")
    if inp.existing_assets > 0:
        lines.append(f"  초기 여유자금:  {inp.existing_assets/1e4:,.0f}만원  (즉시 투자 반영)")
    lines.append(f"  월 투자금:      {inp.monthly_invest/1e4:,.0f}만원")
    lines.append(f"  초기 배당수익률: {inp.initial_yield:.2f}%  /  배당 성장률: {inp.dividend_growth_rate*100:.1f}%/년")
    lines.append(f"  세금 구조:      {tax_label}")
    lines.append("─" * 58)

    # ── 연도별 테이블 ──
    lines.append(f"  {'연도':>4}  {'나이':>4}  {'누적원금':>12}  {'포트폴리오':>12}  {'월배당(세후)':>11}")
    lines.append("─" * 58)

    milestone_years = {1, 3, 5, 10, 15, 20, inp.projection_years}
    printed_goal = False
    for r in results:
        show = r.year in milestone_years
        # 목표 달성 첫 해는 항상 출력
        if r.goal_achieved and not printed_goal:
            show = True
            printed_goal = True

        if not show:
            continue

        age_str = f"{r.age}세" if r.age else "  -"
        goal_mark = " ← 🎯 달성!" if r.goal_achieved and r.year == (goal_year or -1) else ""
        lines.append(
            f"  {r.year:>4}년  {age_str:>5}  "
            f"{r.invested_cumulative/1e8:>8.2f}억  "
            f"{r.portfolio_value/1e8:>8.2f}억  "
            f"{r.monthly_dividend_net/1e4:>9.1f}만원"
            f"{goal_mark}"
        )

    lines.append("─" * 58)

    # ── 결론 ──
    if goal_year:
        goal_age = (inp.current_age + goal_year) if inp.current_age > 0 else None
        age_msg = f"  ({goal_age}세)" if goal_age else ""
        lines.append(f"  🎯 목표 달성: {goal_year}년 후{age_msg}")
        if inp.current_age > 0 and goal_year > inp.projection_years:
            lines.append(f"  ⚠️  목표 달성이 은퇴({inp.retire_age}세) 이후입니다.")
    else:
        last = results[-1]
        gap  = inp.target_monthly_dividend - last.monthly_dividend_net
        lines.append(f"  ⚠️  {inp.projection_years}년 후에도 목표 미달  (부족: {gap/1e4:.1f}만원/월)")

        # 역계산: 이 기간 안에 달성하려면 얼마 투자해야 하나
        required = find_required_monthly_invest(
            target_monthly_div=inp.target_monthly_dividend,
            years=inp.projection_years,
            initial_yield=inp.initial_yield,
            dividend_growth_rate=inp.dividend_growth_rate,
            existing_assets=inp.existing_assets,
            use_isa=inp.use_isa,
        )
        if required > 0:
            lines.append(f"  → 목표 달성을 위한 필요 월 투자금: {required/1e4:,.0f}만원/월")
        else:
            lines.append(f"  → 현재 배당수익률로 이 기간 내 달성 불가 (수익률 재검토 필요)")

    lines.append("═" * 58)

    # ── 월급별 선택지 (월급 입력 시) ──
    if inp.monthly_salary > 0:
        lines.append("")
        lines.append("═" * 58)
        lines.append(f" 배당 목표 선택지  ({inp.projection_years}년 기준, 여유자금 {inp.existing_assets/1e4:,.0f}만원 반영)")
        lines.append("═" * 58)
        lines.append(f"  {'목표':20}  {'월 목표배당':>10}  {'필요 월 투자금':>14}")
        lines.append("─" * 58)
        scenarios = build_goal_scenarios(
            monthly_salary=inp.monthly_salary,
            years=inp.projection_years,
            initial_yield=inp.initial_yield,
            dividend_growth_rate=inp.dividend_growth_rate,
            existing_assets=inp.existing_assets,
            use_isa=inp.use_isa,
        )
        for sc in scenarios:
            req = sc["required_monthly"]
            req_str = f"{req/1e4:,.0f}만원/월" if req > 0 else "달성 불가"
            lines.append(f"  {sc['label']:22}  {sc['target']/1e4:>8.0f}만원  {req_str:>14}")
        lines.append("═" * 58)

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 7. 테스트
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n[케이스 1] 30대 초반, 월급 300만원, 여유자금 1000만원")
    inp1 = SimulationInput(
        monthly_invest=500_000,
        target_monthly_dividend=500_000,
        initial_yield=5.0,
        current_age=32,
        retire_age=65,
        monthly_salary=3_000_000,
        existing_assets=10_000_000,
    )
    print(format_report(inp1, simulate(inp1)))

    print("\n[케이스 2] 55세, 월급 400만원, 여유자금 5000만원")
    inp2 = SimulationInput(
        monthly_invest=500_000,
        target_monthly_dividend=500_000,
        initial_yield=5.0,
        current_age=55,
        retire_age=65,
        monthly_salary=4_000_000,
        existing_assets=50_000_000,
    )
    print(format_report(inp2, simulate(inp2)))

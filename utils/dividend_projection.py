"""
utils/dividend_projection.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배당 성장 시뮬레이션 엔진

■ 설계 철학
  "현재 JEPI 배당 8%가 SCHD 3.5%보다 높아 보이지만,
   15년 후 예상 월배당은 SCHD가 더 클 수 있습니다."
  이 사실을 사용자에게 시각화해주는 게 핵심.

■ 시뮬레이션 방식
  연도별 DPS 성장 모델:
    DPS_t = DPS_0 × (1 + g)^t
    여기서 g = div_growth_5y / 100 (연 배당성장률 CAGR)

  포트폴리오 레벨:
    각 자산의 투자금 × yield_t / 100 → 연 배당
    → 재투자 효과 (reinvestment) 선택적 적용

■ 반환 구조
  {
    "years": [1, 2, ..., N],
    "monthly_div": [...],         # 월별 예상 배당 (세전, 만원)
    "monthly_div_net": [...],     # 세후
    "cumulative_div": [...],      # 누적 배당금
    "yield_on_cost": [...],       # 취득원가 대비 수익률 (Yield on Cost)
    "milestone": {                # 특정 목표 달성 연도
        "doubles": int,           # 월배당 2배 달성 연도
        "target_만원": int,       # 목표 월배당 달성 연도
    },
    "asset_breakdown": [...]      # 자산별 성장 시뮬레��션
  }
"""

from __future__ import annotations
import logging
from typing import Optional

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# 단일 자산 배당 성장 시뮬레이션
# ─────────────────────────────────────────────────────────────

def simulate_asset(
    name:            str,
    asset_class:     str,
    invest_amount:   float,    # 투자금 (만원)
    initial_yield:   float,    # 현재 배당수익률 (%)
    div_growth_rate: float,    # 연 배당성장률 CAGR (%)
    net_tax_rate:    float,    # 실효 세율 (0~1)
    years:           int = 20,
    reinvest:        bool = False,  # 배당 재투자 여부
) -> dict:
    """
    단일 자산의 N년 배당 성장 시뮬레이션.

    재투자 모드(reinvest=True):
      - 받은 배당을 동일 자산에 재투자
      - 투자원금이 매년 증가 → 복리 효과
      - 단, 세금을 내고 남은 배당만 재투자

    반환:
    {
        "name": str,
        "asset_class": str,
        "initial_invest": float,
        "years": list[int],
        "annual_div": list[float],         # 연 세전 배당 (만원)
        "annual_div_net": list[float],      # 연 세후 배당 (만원)
        "monthly_div_net": list[float],     # 월 세후 배당 (만원)
        "yield_on_cost": list[float],       # 취득원가 대비 yield (%)
        "total_invested": float,            # N년 후 총 투자금 (재투자 포함)
    }
    """
    g = div_growth_rate / 100.0
    current_invest = invest_amount
    annual_div_list     = []
    annual_div_net_list = []
    monthly_net_list    = []
    yoc_list            = []

    for t in range(1, years + 1):
        # t년 후 yield (배당성장률 복리 적용)
        yield_t = initial_yield * ((1 + g) ** t)

        # 세전 연배당
        annual_gross = current_invest * yield_t / 100.0

        # 세후 연배당
        annual_net   = annual_gross * (1 - net_tax_rate)

        # 재투자: 세후 배당으로 추가 매수
        if reinvest:
            current_invest += annual_net

        annual_div_list.append(round(annual_gross, 1))
        annual_div_net_list.append(round(annual_net, 1))
        monthly_net_list.append(round(annual_net / 12, 2))

        # Yield on Cost (취득원가 기준 수익률)
        yoc = annual_gross / invest_amount * 100.0
        yoc_list.append(round(yoc, 2))

    return {
        "name":            name,
        "asset_class":     asset_class,
        "initial_invest":  round(invest_amount, 0),
        "years":           list(range(1, years + 1)),
        "annual_div":      annual_div_list,
        "annual_div_net":  annual_div_net_list,
        "monthly_div_net": monthly_net_list,
        "yield_on_cost":   yoc_list,
        "total_invested":  round(current_invest, 0),
        "div_growth_rate": div_growth_rate,
        "initial_yield":   initial_yield,
    }


# ─────────────────────────────────────────────────────────────
# 포트폴리오 전체 시뮬레이션
# ─────────────────────────────────────────────────────────────

def simulate_portfolio(
    recommendations:  list[dict],   # assign_weights() 결과
    investable_amount: float,        # 총 투자금 (만원)
    years:             int   = 20,
    reinvest:          bool  = False,
    monthly_target:    float = 0.0,  # 목표 월배당 (만원) — milestone 계산용
) -> dict:
    """
    포트폴리오 전체의 N년 배당 성장 시뮬레이션.

    각 자산에 대해 simulate_asset()을 돌리고 합산.

    반환:
    {
        "years": [1..N],
        "monthly_div_gross": [...],          # 월 세전 배당 (만원)
        "monthly_div_net":   [...],          # 월 세후 배당 (만원)
        "cumulative_div_net": [...],         # 누적 세후 배당 (만원)
        "yield_on_cost":     [...],          # 포트폴리오 전체 취득원가 대비 yield
        "portfolio_div_cagr": float,         # 포트폴리오 배당 CAGR (%)
        "milestones": {
            "div_doubles_year":     int,      # 월배당 2배 달성 연도 (없으면 None)
            "target_achieved_year": int,      # 목표 달성 연도
            "target_만원":          float,
        },
        "asset_breakdown": [...],            # 자산별 시뮬레이션 (상위 7개)
        "top_growers": [...],                # 배당성장률 Top 3 자산
        "scenario_comparison": {            # 재투자/비재투자 비교
            "no_reinvest": { "monthly_div_net_y20": float },
            "with_reinvest": { "monthly_div_net_y20": float },
            "reinvest_bonus_pct": float,     # 재투자 시 추가 수익률 (%)
        }
    }
    """
    if not recommendations:
        return _empty_projection(years)

    year_list = list(range(1, years + 1))

    # ── 자산별 시뮬레이션 ─────────────────────────────────────
    asset_sims = []
    for rec in recommendations:
        invest = float(rec.get("invest_amount_만원", 0) or 0)
        if invest <= 0:
            continue

        dy          = float(rec.get("dividend_yield", 0) or 0)
        net_tax     = float(rec.get("tax_rate_eff_pct", 15.0) or 15.0) / 100.0
        # 배당성장률: universe 필드 우선 → metadata → 자산 클래스 기본값
        div_grow    = _get_div_growth_rate(rec)

        sim = simulate_asset(
            name            = rec.get("name", ""),
            asset_class     = rec.get("asset_class", ""),
            invest_amount   = invest,
            initial_yield   = dy,
            div_growth_rate = div_grow,
            net_tax_rate    = net_tax,
            years           = years,
            reinvest        = reinvest,
        )
        sim["weight_pct"]    = rec.get("weight_pct", 0)
        sim["etf_category"]  = rec.get("etf_category", "")
        asset_sims.append(sim)

    if not asset_sims:
        return _empty_projection(years)

    # ── 연도별 합산 ──────────────────────────────────────────
    agg_gross = [0.0] * years
    agg_net   = [0.0] * years
    for sim in asset_sims:
        for t in range(years):
            agg_gross[t] += sim["annual_div"][t]
            agg_net[t]   += sim["annual_div_net"][t]

    monthly_gross = [round(v / 12, 2) for v in agg_gross]
    monthly_net   = [round(v / 12, 2) for v in agg_net]

    # 누적 배당
    cumulative = []
    cum = 0.0
    for v in agg_net:
        cum += v
        cumulative.append(round(cum, 0))

    # 취득원가 대비 yield
    yoc_list = [round(v / investable_amount * 100, 2) if investable_amount else 0
                for v in agg_gross]

    # ── 포트폴리오 배당 CAGR ─────────────────────────────────
    y1  = agg_net[0]  if agg_net else 1
    yn  = agg_net[-1] if agg_net else 1
    n   = years
    try:
        port_cagr = round(((yn / y1) ** (1 / (n - 1)) - 1) * 100, 2) if yn > y1 else 0.0
    except Exception:
        port_cagr = 0.0

    # ── Milestones ───────────────────────────────────────────
    initial_monthly_net = monthly_net[0] if monthly_net else 0
    div_doubles_year    = None
    target_year         = None

    for idx, m in enumerate(monthly_net):
        if div_doubles_year is None and m >= initial_monthly_net * 2:
            div_doubles_year = year_list[idx]
        if monthly_target > 0 and target_year is None and m >= monthly_target:
            target_year = year_list[idx]

    # ── 재투자 비교 시뮬레이션 ────────────────────────────────
    # 재투자 없는 버전은 이미 위에서 계산됨
    # 재투자 있는 버전은 별도로 빠르게 재계산
    reinvest_y20_net = _calc_reinvest_total(recommendations, years)
    no_reinvest_y20  = monthly_net[-1] if monthly_net else 0

    if no_reinvest_y20 > 0:
        bonus_pct = round((reinvest_y20_net - no_reinvest_y20) / no_reinvest_y20 * 100, 1)
    else:
        bonus_pct = 0.0

    # ── 상위 성장 종목 ────────────────────────────────────────
    top_growers = sorted(
        asset_sims,
        key=lambda s: s.get("div_growth_rate", 0),
        reverse=True
    )[:3]

    # ── 자산별 breakdown (상위 7개, 투자금 기준) ──────────────
    breakdown = sorted(
        asset_sims,
        key=lambda s: s.get("initial_invest", 0),
        reverse=True
    )[:7]

    # 간소화 (전체 연도 리스트 보내면 너무 무거워짐 — y1/y5/y10/y20만)
    def _slim(sim: dict) -> dict:
        checkpoints = [0, 4, 9, min(19, years - 1)]  # 1, 5, 10, 20년차 인덱스
        return {
            "name":            sim["name"],
            "asset_class":     sim["asset_class"],
            "etf_category":    sim.get("etf_category", ""),
            "initial_invest":  sim["initial_invest"],
            "weight_pct":      sim.get("weight_pct", 0),
            "div_growth_rate": sim["div_growth_rate"],
            "initial_yield":   sim["initial_yield"],
            "snapshots": [
                {
                    "year":             year_list[i],
                    "monthly_div_net":  sim["monthly_div_net"][i],
                    "yield_on_cost":    sim["yield_on_cost"][i],
                }
                for i in checkpoints if i < years
            ],
        }

    result = {
        "years":             year_list,
        "monthly_div_gross": monthly_gross,
        "monthly_div_net":   monthly_net,
        "cumulative_div_net": cumulative,
        "yield_on_cost":     yoc_list,
        "portfolio_div_cagr": port_cagr,
        "initial_monthly_net": round(initial_monthly_net, 2),
        "final_monthly_net":   round(monthly_net[-1], 2) if monthly_net else 0,
        "milestones": {
            "div_doubles_year":     div_doubles_year,
            "target_achieved_year": target_year,
            "target_만원":          monthly_target,
        },
        "asset_breakdown": [_slim(s) for s in breakdown],
        "top_growers": [
            {
                "name":            s["name"],
                "div_growth_rate": s["div_growth_rate"],
                "initial_yield":   s["initial_yield"],
                "y10_monthly_net": s["monthly_div_net"][9] if len(s["monthly_div_net"]) > 9 else None,
                "y20_monthly_net": s["monthly_div_net"][-1] if s["monthly_div_net"] else None,
            }
            for s in top_growers
        ],
        "scenario_comparison": {
            "no_reinvest":   {"monthly_div_net_final": round(no_reinvest_y20, 2)},
            "with_reinvest": {"monthly_div_net_final": round(reinvest_y20_net, 2)},
            "reinvest_bonus_pct": bonus_pct,
        },
    }

    # 인플레이션 조정 레이어 자동 추가
    add_inflation_adjustment(result, cpi_rate=2.5, monthly_target=monthly_target)
    return result


# ─────────────────────────────────────────────────────────────
# 헬퍼 함수들
# ─────────────────────────────────────────────────────────────

# 자산 클래스별 배당성장률 기본값
_DEFAULT_GROWTH_BY_CLASS: dict[str, float] = {
    "kr_stock":   3.5,    # 한국주식: 평균 3.5% 배당성장
    "us_stock":   5.0,    # 미국개별주: 평균 5%
    "us_div_etf": 4.0,    # 미국 배당ETF 평균
    "kr_etf":     3.5,
    "us_reit":    3.0,
    "kr_reit":    2.5,
    "defensive":  0.5,    # 채권: 거의 안 오름
}

# etf_category별 배당성장률 기본값 (자산 클래스보다 더 정확)
_DEFAULT_GROWTH_BY_CATEGORY: dict[str, float] = {
    "dividend_growth":  9.0,   # SCHD·VIG — 배당성장 전략 ETF
    "monthly_income":   0.5,   # JEPI·JEPQ — 커버드콜, 성장 거의 없음
    "high_yield":       3.5,   # VYM·HDV — 중간 수준
    "reit":             3.0,   # 리츠 평균
    "cash_equivalent":  0.0,   # SGOV — 금리 연동, 성장 없음
    "long_bond":        0.0,
    "agg_bond":         0.5,
    "tips":             1.0,
}


def _get_div_growth_rate(rec: dict) -> float:
    """
    자산의 배당성장률 결정 우선순위:
    1. universe.py의 div_growth_5y (ETF 전용)
    2. asset_metadata의 div_growth_rate_pct
    3. etf_category 기본값
    4. asset_class 기본값
    """
    # 1. universe.py div_growth_5y (ETF에서 옴)
    val = rec.get("div_growth_rate_pct")
    if val is not None and float(val) != 0:
        return float(val)

    # 2. etf_category 기본값
    cat = rec.get("etf_category", "")
    if cat and cat in _DEFAULT_GROWTH_BY_CATEGORY:
        return _DEFAULT_GROWTH_BY_CATEGORY[cat]

    # 3. asset_class 기본값
    cls = rec.get("asset_class", "")
    return _DEFAULT_GROWTH_BY_CLASS.get(cls, 3.0)


def _calc_reinvest_total(recommendations: list[dict], years: int) -> float:
    """
    재투자 시나리오: N년 후 월 세후 배당 총합 추정.
    빠른 근사 계산 (개별 simulate_asset 호출 없이).
    """
    total_monthly_net = 0.0
    for rec in recommendations:
        invest = float(rec.get("invest_amount_만원", 0) or 0)
        if invest <= 0:
            continue
        dy      = float(rec.get("dividend_yield", 0) or 0)
        net_tax = float(rec.get("tax_rate_eff_pct", 15.0) or 15.0) / 100.0
        g       = _get_div_growth_rate(rec) / 100.0

        # 재투자 시뮬레이션: 세후 배당 복리 적용
        cur_invest = invest
        for _ in range(years):
            ann = cur_invest * dy / 100.0 * (1 + g)
            ann_net = ann * (1 - net_tax)
            cur_invest += ann_net  # 재투자

        total_monthly_net += (cur_invest * dy * ((1 + g) ** years) / 100.0 * (1 - net_tax)) / 12

    return round(total_monthly_net, 2)


def _empty_projection(years: int) -> dict:
    year_list = list(range(1, years + 1))
    zeros = [0.0] * years
    return {
        "years":              year_list,
        "monthly_div_gross":  zeros,
        "monthly_div_net":    zeros,
        "cumulative_div_net": zeros,
        "yield_on_cost":      zeros,
        "portfolio_div_cagr": 0.0,
        "initial_monthly_net": 0.0,
        "final_monthly_net":   0.0,
        "milestones":         {"div_doubles_year": None, "target_achieved_year": None, "target_만원": 0},
        "asset_breakdown":    [],
        "top_growers":        [],
        "scenario_comparison": {
            "no_reinvest":    {"monthly_div_net_final": 0},
            "with_reinvest":  {"monthly_div_net_final": 0},
            "reinvest_bonus_pct": 0.0,
        },
    }


# ─────────────────────────────────────────────────────────────
# 생활비 커버율 계산
# ─────────────────────────────────────────────────────────────

# 2024년 기준 한국 1인 가구 월 평균 생활비 (통계청)
LIVING_COST_BENCHMARKS = {
    "서울_1인": 250,      # 만원/월 (통신·식비·주거·교통·여가 포함)
    "지방_1인": 180,
    "서울_2인": 380,
    "지방_2인": 280,
    "최소_생활비": 120,   # 식비·통신비만
    "반은퇴_기준": 200,   # 월급 없이도 버�� 수 있는 최소 배당
}

LIFE_MILESTONES = [
    (30,   "☕ 커피값 자유"),
    (50,   "📱 통신비 달성"),
    (80,   "🍽️ 식비 달성"),
    (120,  "🏠 최소 생활비 달성"),
    (200,  "⚡ 반은퇴 가능"),
    (250,  "🏙️ 서울 1인 생활비 달성"),
    (380,  "👨‍👩‍👧 서울 2인 생활비 달성"),
]


def calc_living_coverage(
    monthly_div_net: float,  # 현재 월 세후 배당 (만원)
    projection: Optional[dict] = None,  # simulate_portfolio 결과
    city: str = "서울_1인",
) -> dict:
    """
    현재 배당금으로 생활비를 얼마나 커버할 수 있는지.
    + 각 life milestone 달성 연도 추적.

    반환:
    {
        "current_coverage_pct": 41.2,       # 현재 커버율 (%)
        "benchmark_만원":       2500,        # 비교 기준 생활비
        "current_label":        "🍽️ 식비 달성",  # 현재 달성한 milestone
        "milestones": [...],                 # 각 milestone 달성 연도
    }
    """
    bench = LIVING_COST_BENCHMARKS.get(city, 2500)
    coverage = round(monthly_div_net / bench * 100, 1) if bench else 0

    # 현재 달성한 milestone 레이블
    current_label = "🌱 시작 단계"
    for threshold, label in LIFE_MILESTONES:
        if monthly_div_net >= threshold:
            current_label = label

    # 미래 milestone 달성 연도 (projection 있을 때만)
    milestone_years = []
    if projection:
        monthly_net_series = projection.get("monthly_div_net", [])
        year_list          = projection.get("years", [])
        for threshold, label in LIFE_MILESTONES:
            achieved_year = None
            for yr, m in zip(year_list, monthly_net_series):
                if m >= threshold:
                    achieved_year = yr
                    break
            already_done = monthly_div_net >= threshold
            milestone_years.append({
                "label":         label,
                "threshold_만원": threshold,
                "achieved_year": achieved_year,
                "already_done":  already_done,
            })

    return {
        "current_monthly_net": round(monthly_div_net, 2),
        "benchmark_만원":      bench,
        "benchmark_label":     city,
        "current_coverage_pct": coverage,
        "current_label":       current_label,
        "milestones":          milestone_years,
    }


# ─────────────────────────────────────────────────────────────
# 인플레이션 조정 (CPI-adjusted Real Value)
# ─────────────────────────────────────────────────────────────

# CPI 시나리오 정의 (연간 물가상승률 가정)
CPI_SCENARIOS = {
    "low":  2.0,   # 저인플레이션 (금리 안정기)
    "base": 2.5,   # 기준 시나리오 (한국은행 중기 목표)
    "high": 3.5,   # 고인플레이션 (에너지·공급망 충격)
}


def add_inflation_adjustment(
    projection: dict,
    cpi_rate: float = 2.5,
    monthly_target: float = 0.0,
) -> dict:
    """
    simulate_portfolio() 결과에 CPI 조정 레이어를 추가한다.

    왜 필요한가?
      명목 배당 200만원이 20년 후에도 200만원 가치를 하지 않는다.
      연 2.5% 인플레이션이면 20년 후 200만원의 실질 구매력은 ~122만원이다.
      투자자가 목표를 현실적으로 설정하려면 반드시 이 차이를 알아야 한다.

    Args:
        projection:    simulate_portfolio() 반환값
        cpi_rate:      기준 CPI 연율 (%, 기본 2.5)
        monthly_target: 목표 월배당 (실질 기준) — 달성 연도 재계산용

    반환 (projection dict에 추가되는 필드):
    {
        "inflation": {
            "cpi_rate_used":        2.5,
            "monthly_div_real":     [...],   # 실질 가치 월배당 (만원, 기준연도 현재가치)
            "purchasing_power_ratio": [...], # 명목 대비 실질 비율 (1년차부터 점점 하락)
            "cpi_gap_만원":         [...],   # 명목 - 실질 (인플레이션이 갉아먹는 금액)
            "real_final_monthly":   float,   # N년 후 실질 월배당
            "nominal_final_monthly": float,  # N년 후 명목 월배당 (비교용)
            "purchasing_power_loss_pct": float, # N년 후 구매력 손실율 (%)
            "real_target_year":     int|None, # 실질 기준 목표 달성 연도
            "scenarios": {
                "low":  {"cpi": 2.0, "real_y10": float, "real_y20": float, "loss_pct": float},
                "base": {"cpi": 2.5, "real_y10": float, "real_y20": float, "loss_pct": float},
                "high": {"cpi": 3.5, "real_y10": float, "real_y20": float, "loss_pct": float},
            },
            "insight": str,   # 핵심 인사이트 메시지
        }
    }
    """
    import math

    years = projection.get("years", [])
    monthly_net = projection.get("monthly_div_net", [])

    if not years or not monthly_net:
        projection["inflation"] = _empty_inflation(cpi_rate)
        return projection

    n = len(years)
    r = cpi_rate / 100.0

    # 기준 시나리오: 실질 가치 계산
    monthly_real = []
    pp_ratio     = []   # purchasing power ratio
    cpi_gap      = []

    for t, nom in zip(years, monthly_net):
        deflator = (1 + r) ** t
        real     = round(nom / deflator, 2)
        ratio    = round(1 / deflator, 4)         # 구매력 비율 (1.0 → 점점 줄어듦)
        gap      = round(nom - real, 2)
        monthly_real.append(real)
        pp_ratio.append(ratio)
        cpi_gap.append(gap)

    real_final   = monthly_real[-1] if monthly_real else 0.0
    nom_final    = monthly_net[-1]  if monthly_net  else 0.0
    loss_pct     = round((1 - pp_ratio[-1]) * 100, 1) if pp_ratio else 0.0

    # 실질 기준 목표 달성 연도
    real_target_year = None
    if monthly_target > 0:
        for yr, rv in zip(years, monthly_real):
            if rv >= monthly_target:
                real_target_year = yr
                break

    # 3가지 CPI 시나리오 비교
    scenarios = {}
    for label, cpi in CPI_SCENARIOS.items():
        r_s  = cpi / 100.0
        y10  = None
        y20  = None
        if len(monthly_net) >= 10:
            y10 = round(monthly_net[9]  / (1 + r_s) ** 10,  2)
        if len(monthly_net) >= 20:
            y20 = round(monthly_net[19] / (1 + r_s) ** 20,  2)
        elif monthly_net:
            y20 = round(monthly_net[-1] / (1 + r_s) ** len(monthly_net), 2)
        loss = round((1 - 1 / (1 + r_s) ** min(20, len(monthly_net))) * 100, 1)
        scenarios[label] = {
            "cpi_pct":    cpi,
            "real_y10":   y10,
            "real_y20":   y20,
            "loss_pct_20y": loss,
        }

    # 핵심 인사이트
    insight = _inflation_insight(
        nom_final       = nom_final,
        real_final      = real_final,
        loss_pct        = loss_pct,
        cpi_rate        = cpi_rate,
        years           = len(years),
        monthly_target  = monthly_target,
        real_target_year = real_target_year,
    )

    projection["inflation"] = {
        "cpi_rate_used":          cpi_rate,
        "monthly_div_real":       monthly_real,
        "purchasing_power_ratio": pp_ratio,
        "cpi_gap_만원":           cpi_gap,
        "real_final_monthly":     real_final,
        "nominal_final_monthly":  round(nom_final, 2),
        "purchasing_power_loss_pct": loss_pct,
        "real_target_year":       real_target_year,
        "scenarios":              scenarios,
        "insight":                insight,
    }
    return projection


def _inflation_insight(
    nom_final: float,
    real_final: float,
    loss_pct: float,
    cpi_rate: float,
    years: int,
    monthly_target: float,
    real_target_year,
) -> str:
    """인플레이션 핵심 인사이트 메시지 생성."""
    lines = []

    # 구매력 손실 메시지
    if loss_pct >= 40:
        lines.append(
            f"⚠️ {years}년 후 명목 배당 {round(nom_final)}만원은 "
            f"현재 가치로 {round(real_final)}만원 수준입니다 "
            f"(CPI {cpi_rate}% 기준, 구매력 {loss_pct}% 감소)."
        )
    elif loss_pct >= 20:
        lines.append(
            f"📉 {years}년 후 구매력이 {loss_pct}% 줄어듭니다. "
            f"명목 {round(nom_final)}만원 → 실질 {round(real_final)}만원."
        )
    else:
        lines.append(
            f"✅ {years}년 후에도 구매력 손실은 {loss_pct}% 수준으로 관리 가능합니다."
        )

    # 목표 달성 관련 메시지
    if monthly_target > 0 and real_target_year:
        lines.append(
            f"🎯 목표 월배당 {round(monthly_target)}만원(실질 기준)은 "
            f"{real_target_year}년 차에 달성 예상."
        )
    elif monthly_target > 0 and not real_target_year:
        lines.append(
            f"💡 목표 {round(monthly_target)}만원(실질)은 {years}년 내 미달성. "
            "투자금 확대 또는 배당성장 자산 비중 증가를 검토하세요."
        )

    # 권고 액션
    if loss_pct >= 30:
        lines.append(
            "💡 배당성장률이 높은 자산(SCHD·VIG 등)을 늘리면 인플레이션을 상쇄할 수 있습니다."
        )

    return " ".join(lines)


def _empty_inflation(cpi_rate: float) -> dict:
    return {
        "cpi_rate_used":          cpi_rate,
        "monthly_div_real":       [],
        "purchasing_power_ratio": [],
        "cpi_gap_만원":           [],
        "real_final_monthly":     0.0,
        "nominal_final_monthly":  0.0,
        "purchasing_power_loss_pct": 0.0,
        "real_target_year":       None,
        "scenarios":              {},
        "insight":                "",
    }

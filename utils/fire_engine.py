"""
utils/fire_engine.py — FIRE 역산 엔진
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  현재 시스템은 "5,000만원 투자 → 월 14만원" 방향으로 계산한다.
  하지만 투자자가 진짜 원하는 질문은 반대다:

    "50세에 월 200만원 배당으로 반은퇴하려면
     지금 얼마를 투자하고, 매달 얼마를 더 넣어야 하나?"

  목표를 먼저 정하고 역산(back-calculation)하는 것.
  이게 진짜 재무 어드바이저가 하는 일이다.

■ 4가지 FIRE 목표 유형
  LEAN_FIRE:    월 120만원 — 최소 생활비 달성 (식비+통신)
  REGULAR_FIRE: 월 250만원 — 서울 1인 생활비 완전 커버
  FAT_FIRE:     월 400만원 — 여유 있는 은퇴 생활
  CUSTOM:       사용자 지정 목표 월배당

■ 역산 공식
  1) 목표 투자원금 = 목표_연배당 / 세후_수익률
  2) 부족금액 = 목표_원금 - 현재_원금
  3) 현재가치(PV) 기준 월 적립 필요금액 (복리 미래가치 역산)
     FV = PMT × ((1+r)^n - 1) / r
     → PMT = FV × r / ((1+r)^n - 1)
  4) 인플레이션 조정: 목표를 실질 가치로 상향 (CPI 복리)

■ 반환 구조
  {
    "targets": {                     # 4가지 목표 유형
      "lean": {...},
      "regular": {...},
      "fat": {...},
      "custom": {...},               # monthly_target이 0이면 regular와 동일
    },
    "current_state": {...},          # 현재 포트폴리오 위치
    "fire_timeline": [...],          # 목표별 달성 연도 타임라인
    "recommended_action": str,       # 핵심 권고 메시지
  }
"""

from __future__ import annotations
import math
from typing import Optional


# FIRE 목표 유형 정의 (월 기준, 만원)
FIRE_TARGETS = {
    "lean":    {"label": "린 파이어 (Lean FIRE)",    "monthly_만원": 120,  "desc": "식비·통신비 최소 생활"},
    "regular": {"label": "일반 파이어 (FIRE)",       "monthly_만원": 250,  "desc": "서울 1인 생활비 완전 커버"},
    "fat":     {"label": "팻 파이어 (Fat FIRE)",     "monthly_만원": 400,  "desc": "여유 있는 은퇴 생활"},
}


def calc_fire_engine(
    current_investable:  float,         # 현재 투자금 (만원)
    monthly_savings:     float,         # 현재 월 적립 가능금액 (만원)
    current_age:         int,
    target_age:          int   = 50,    # 목표 FIRE 나이
    avg_net_yield:       float = 3.5,   # 포트폴리오 세후 연 배당수익률 (%)
    div_growth_rate:     float = 5.0,   # 연 배당성장률 (%)
    cpi_rate:            float = 2.5,   # 인플레이션 (%)
    custom_monthly_만원: float = 0.0,   # 사용자 지정 목표 월배당 (만원)
    annual_savings_growth: float = 3.0, # 연 저축액 증가율 (소득 상승 반영, %)
) -> dict:
    """
    FIRE 목표별 역산 분석.

    Args:
        current_investable:    현재 총 투자금 (만원)
        monthly_savings:       현재 월 적립 가능금액 (만원)
        current_age:           현재 나이
        target_age:            목표 FIRE 나이 (기본 50세)
        avg_net_yield:         포트폴리오 세후 연 배당수익률 (%)
        div_growth_rate:       연 배당성장률 CAGR (%)
        cpi_rate:              연 인플레이션율 (%)
        custom_monthly_만원:   사용자 지정 목표 월배당 (0이면 무시)
        annual_savings_growth: 저축액 연 증가율 (소득 상승 반영)

    반환:
    {
        "targets": {
            "lean":    FIRE_CALC_RESULT,
            "regular": FIRE_CALC_RESULT,
            "fat":     FIRE_CALC_RESULT,
            "custom":  FIRE_CALC_RESULT,  # custom_monthly가 0이면 None
        },
        "current_state": {
            "investable":          float,
            "monthly_savings":     float,
            "current_monthly_div": float,
            "current_age":         int,
            "target_age":          int,
            "years_to_fire":       int,
            "avg_net_yield_pct":   float,
            "div_growth_rate_pct": float,
        },
        "fire_timeline":         list[dict],   # 연도별 자산 성장 시뮬레이션
        "recommended_action":    str,
        "earliest_fire_type":    str,          # 가장 빠른 달성 FIRE 유형
        "earliest_fire_age":     int | None,
    }

    FIRE_CALC_RESULT 구조:
    {
        "label":                 str,
        "monthly_target_nominal": float,   # 명목 목표 (현재 가치)
        "monthly_target_real":   float,    # 인플레이션 조정 목표 (FIRE 시점 기준)
        "required_principal":    float,    # 필요 투자원금 (만원)
        "shortfall":             float,    # 부족금액 (만원, 음수면 이미 달성)
        "already_achieved":      bool,
        "monthly_pmt_needed":    float,    # 부족 달성을 위한 월 추가 적립금
        "achievable_by_target":  bool,     # 목표 나이 내 달성 가능?
        "projected_fire_age":    int|None, # 실제 예상 달성 나이
        "years_to_achieve":      int|None,
        "gap_years":             int|None, # 목표 나이 대비 빠름(-)/늦음(+)
    }
    """
    years_to_fire = max(target_age - current_age, 1)
    r_yield   = avg_net_yield   / 100.0
    r_growth  = div_growth_rate / 100.0
    r_cpi     = cpi_rate        / 100.0
    r_savings_growth = annual_savings_growth / 100.0

    # 현재 월 배당 (대략적 추정)
    current_monthly_div = round(current_investable * r_yield / 12, 2)

    results = {}

    # 4가지 목표 유형 처리
    target_list = dict(FIRE_TARGETS)
    if custom_monthly_만원 > 0:
        target_list["custom"] = {
            "label":       f"맞춤 목표",
            "monthly_만원": custom_monthly_만원,
            "desc":        f"월 {custom_monthly_만원:,}만원 배당 목표",
        }
    else:
        results["custom"] = None

    for key, tdef in target_list.items():
        nom_monthly = tdef["monthly_만원"]

        # 인플레이션 조정: FIRE 시점 기준 실질 목표
        # 예: 목표 월 250만원(현재가치) → 20년 후 실질 250만원 유지하려면
        #     명목으로는 250 × (1+cpi)^20 원이 필요
        real_monthly_at_fire = round(nom_monthly * ((1 + r_cpi) ** years_to_fire), 2)

        # 필요 투자원금 (배당성장 반영)
        # 핵심 공식:  원금 × 세후수익률 = 연간 배당
        # 단, 배당성장이 있으면 초기 원금 기준 수익률이 낮아도 성장으로 커버 가능
        # 보수적으로: 명목 원금 = 실질 목표 연배당 / 현재 세후 수익률
        annual_target = real_monthly_at_fire * 12
        required_principal = round(annual_target / r_yield, 0) if r_yield > 0 else 0

        shortfall = round(required_principal - current_investable, 0)
        already   = shortfall <= 0

        # 월 적립액 역산 (FV 공식)
        # FV = PMT × ((1+r/12)^(n*12) - 1) / (r/12)
        # 단, 저축액도 매년 r_savings_growth만큼 증가한다고 가정
        monthly_r = r_yield / 12.0   # 월 수익률 (배당 재투자 가정)
        n_months  = years_to_fire * 12

        if already:
            monthly_pmt = 0.0
        elif monthly_r > 0 and n_months > 0:
            # FV factor
            fv_factor = ((1 + monthly_r) ** n_months - 1) / monthly_r
            monthly_pmt = round(shortfall / fv_factor, 1) if fv_factor > 0 else shortfall / n_months
        else:
            monthly_pmt = round(shortfall / n_months, 1) if n_months > 0 else 0.0

        # 실제 달성 나이 시뮬레이션 (현재 적립액 + 기존 투자금 복리 성장)
        projected_fire_age = _simulate_fire_age(
            current_investable = current_investable,
            monthly_savings    = monthly_savings,
            r_yield_monthly    = monthly_r,
            r_savings_growth   = r_savings_growth,
            required_principal = required_principal,
            current_age        = current_age,
            max_years          = 40,
        )

        achievable = (projected_fire_age is not None and projected_fire_age <= target_age)
        years_to_achieve = (projected_fire_age - current_age) if projected_fire_age else None
        gap = (projected_fire_age - target_age) if projected_fire_age else None

        results[key] = {
            "label":                   tdef["label"],
            "desc":                    tdef["desc"],
            "monthly_target_nominal":  nom_monthly,
            "monthly_target_real":     real_monthly_at_fire,
            "required_principal":      required_principal,
            "shortfall":               max(shortfall, 0),
            "already_achieved":        already,
            "monthly_pmt_needed":      monthly_pmt,
            "achievable_by_target":    achievable,
            "projected_fire_age":      projected_fire_age,
            "years_to_achieve":        years_to_achieve,
            "gap_years":               gap,    # 음수=일찍 달성, 양수=늦게 달성
        }

    # 연도별 자산 성장 타임라인 (regular 기준)
    fire_timeline = _build_timeline(
        current_investable = current_investable,
        monthly_savings    = monthly_savings,
        r_yield_monthly    = r_yield / 12,
        r_savings_growth   = r_savings_growth,
        current_age        = current_age,
        target_age         = target_age,
        targets            = {k: v["required_principal"] for k, v in results.items() if v},
        years              = min(years_to_fire + 5, 35),
    )

    # 가장 빠른 FIRE 달성 유형
    earliest_type = None
    earliest_age  = None
    for k, v in results.items():
        if v and v["projected_fire_age"]:
            if earliest_age is None or v["projected_fire_age"] < earliest_age:
                earliest_age  = v["projected_fire_age"]
                earliest_type = k

    recommended = _make_fire_recommendation(
        results          = results,
        current_investable = current_investable,
        monthly_savings  = monthly_savings,
        years_to_fire    = years_to_fire,
        target_age       = target_age,
        earliest_type    = earliest_type,
        earliest_age     = earliest_age,
    )

    return {
        "targets":           results,
        "current_state": {
            "investable":          round(current_investable, 0),
            "monthly_savings":     round(monthly_savings, 1),
            "current_monthly_div": current_monthly_div,
            "current_age":         current_age,
            "target_age":          target_age,
            "years_to_fire":       years_to_fire,
            "avg_net_yield_pct":   avg_net_yield,
            "div_growth_rate_pct": div_growth_rate,
            "cpi_rate_pct":        cpi_rate,
        },
        "fire_timeline":         fire_timeline,
        "recommended_action":    recommended,
        "earliest_fire_type":    earliest_type,
        "earliest_fire_age":     earliest_age,
    }


def _simulate_fire_age(
    current_investable: float,
    monthly_savings:    float,
    r_yield_monthly:    float,
    r_savings_growth:   float,
    required_principal: float,
    current_age:        int,
    max_years:          int = 40,
) -> Optional[int]:
    """
    현재 투자금 + 월 적립으로 언제 목표 원금에 도달하는지 시뮬레이션.

    매년 저축액이 r_savings_growth만큼 증가한다고 가정.
    """
    portfolio = current_investable
    monthly   = monthly_savings

    for year in range(1, max_years + 1):
        for _ in range(12):
            # 월 배당 재투자 + 신규 적립
            portfolio = portfolio * (1 + r_yield_monthly) + monthly

        # 연말 저축액 인상
        monthly *= (1 + r_savings_growth)

        if portfolio >= required_principal:
            return current_age + year

    return None  # max_years 내 미달성


def _build_timeline(
    current_investable: float,
    monthly_savings:    float,
    r_yield_monthly:    float,
    r_savings_growth:   float,
    current_age:        int,
    target_age:         int,
    targets:            dict,   # {type: required_principal}
    years:              int = 30,
) -> list[dict]:
    """연도별 자산 성장 타임라인 생성."""
    timeline = []
    portfolio = current_investable
    monthly   = monthly_savings

    for year in range(1, years + 1):
        for _ in range(12):
            portfolio = portfolio * (1 + r_yield_monthly) + monthly
        monthly *= (1 + r_savings_growth)

        age = current_age + year
        achieved = {k: portfolio >= v for k, v in targets.items()}

        timeline.append({
            "year":       year,
            "age":        age,
            "portfolio":  round(portfolio, 0),
            "is_target":  age == target_age,
            "achieved":   achieved,
        })

    return timeline


def _make_fire_recommendation(
    results:           dict,
    current_investable: float,
    monthly_savings:   float,
    years_to_fire:     int,
    target_age:        int,
    earliest_type:     Optional[str],
    earliest_age:      Optional[int],
) -> str:
    """FIRE 달성 전략 핵심 권고 메시지 생성."""
    lines = []

    lean  = results.get("lean")
    reg   = results.get("regular")

    # 이미 린 파이어 달성
    if lean and lean["already_achieved"]:
        lines.append(f"🎉 이미 린 파이어(월 {lean['monthly_target_nominal']:,}만원) 달성 수준입니다!")

    # 목표 나이 내 달성 가능 여부
    if earliest_type and earliest_age:
        if earliest_age <= target_age:
            lines.append(
                f"✅ '{FIRE_TARGETS.get(earliest_type, {}).get('label', earliest_type)}' 기준으로 "
                f"{earliest_age}세에 달성 가능합니다 (목표 {target_age}세보다 {target_age - earliest_age}년 빠름)."
            )
        else:
            lines.append(
                f"⚠️ 현재 적립 속도로는 {earliest_age}세에 가장 작은 목표(린 파이어)를 달성합니다 "
                f"(목표 {target_age}세보다 {earliest_age - target_age}년 늦음)."
            )

    # 핵심 액션
    if reg and not reg["already_achieved"]:
        pmt = reg["monthly_pmt_needed"]
        gap_years = reg.get("gap_years")
        if pmt > monthly_savings * 1.5:
            lines.append(
                f"💡 일반 파이어(월 {reg['monthly_target_nominal']:,}만원) 달성을 위해 "
                f"월 {pmt:,.0f}만원 추가 적립이 필요합니다. "
                "배당성장 ETF(SCHD·VIG) 비중 확대와 복리 재투자가 핵심입니다."
            )
        elif pmt > 0:
            lines.append(
                f"💡 현재 적립액에 월 {pmt:,.0f}만원만 추가하면 "
                f"목표 나이 {target_age}세 내 일반 파이어 달성이 가능합니다."
            )

    if not lines:
        lines.append("현재 적립 속도와 수익률로 목표를 향해 순조롭게 진행 중입니다.")

    return " ".join(lines)

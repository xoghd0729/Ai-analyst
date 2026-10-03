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
    current_investable:   float,               # 현재 투자금 (만원)
    monthly_savings:      float,               # 현재 월 적립 가능금액 (만원)
    current_age:          int,
    target_age:           int   = 50,          # 목표 FIRE 나이
    avg_net_yield:        float = 3.5,         # [역할A] 세후 배당수익률 (%) — 목표 원금 역산용
    div_growth_rate:      float = 5.0,         # 연 배당성장률 (%) — 보수적 설계상 원금 계산에 미사용 (데드)
    cpi_rate:             float = 2.5,         # 인플레이션 (%)
    custom_monthly_만원:  float = 0.0,         # 사용자 지정 목표 월배당 (만원)
    annual_savings_growth: float = 0.0,        # 연 저축액 증가율 (%) — 기본 0%, 명시적 전달 원칙
    asset_growth_yield:   Optional[float] = None,  # [역할B] 자산 누적 성장률 (%) — None이면 avg_net_yield 사용
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

    # 역할A: 배당 현금흐름 목표 역산 → 세후 배당수익률
    r_yield   = avg_net_yield   / 100.0

    # 역할B: 자산 누적 성장률 → 총수익률(asset_growth_yield) 또는 배당수익률(하위 호환)
    r_growth_asset = (asset_growth_yield if asset_growth_yield is not None else avg_net_yield) / 100.0

    r_growth  = div_growth_rate / 100.0  # div_growth_rate: 보수적 설계상 원금 계산에 미사용
    r_cpi     = cpi_rate        / 100.0
    r_savings_growth = annual_savings_growth / 100.0

    # 현재 월 배당 (대략적 추정) — 역할A 수익률 기준
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

        # 월 적립액 역산 (FV 공식) — 역할B: 자산 누적 성장률 사용
        # FV = PMT × ((1+r/12)^(n*12) - 1) / (r/12)
        # 단, 저축액도 매년 r_savings_growth만큼 증가한다고 가정
        monthly_r = r_growth_asset / 12.0   # 월 수익률: 총수익률 기준 (역할B)
        n_months  = years_to_fire * 12

        if already:
            monthly_pmt = 0.0
        elif monthly_r > 0 and n_months > 0:
            # FV factor
            fv_factor = ((1 + monthly_r) ** n_months - 1) / monthly_r
            monthly_pmt = round(shortfall / fv_factor, 1) if fv_factor > 0 else shortfall / n_months
        else:
            monthly_pmt = round(shortfall / n_months, 1) if n_months > 0 else 0.0

        # 실제 달성 나이 시뮬레이션 — 역할B: 자산 누적 성장률(총수익률) 기준
        projected_fire_age = _simulate_fire_age(
            current_investable = current_investable,
            monthly_savings    = monthly_savings,
            r_yield_monthly    = r_growth_asset / 12.0,   # 총수익률 기준
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

    # 연도별 자산 성장 타임라인 (regular 기준) — 역할B: 자산 누적 성장률 기준
    fire_timeline = _build_timeline(
        current_investable = current_investable,
        monthly_savings    = monthly_savings,
        r_yield_monthly    = r_growth_asset / 12,   # 총수익률 기준
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
            "investable":               round(current_investable, 0),
            "monthly_savings":          round(monthly_savings, 1),
            "current_monthly_div":      current_monthly_div,
            "current_age":              current_age,
            "target_age":               target_age,
            "years_to_fire":            years_to_fire,
            "avg_net_yield_pct":        avg_net_yield,           # 역할A: 배당수익률
            "asset_growth_yield_pct":   asset_growth_yield if asset_growth_yield is not None else avg_net_yield,  # 역할B: 자산 성장률
            "div_growth_rate_pct":      div_growth_rate,         # 보수적 설계상 미사용 (데드)
            "cpi_rate_pct":             cpi_rate,
            "annual_savings_growth_pct": annual_savings_growth,
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


# ─────────────────────────────────────────────────────────────────────────────
# FIRE 역산 엔진 (Reverse Engine)
# "55세 달성 불가"가 아니라 "무엇을 얼마나 바꿔야 하는가"를 계산
# ─────────────────────────────────────────────────────────────────────────────

def _binary_search_min(
    lo: float, hi: float, tol: float,
    fn,
    max_iter: int = 60,
) -> Optional[float]:
    """[lo, hi]에서 fn(x)==True인 최솟값 반환. 없으면 None."""
    if fn(lo):
        return lo
    if not fn(hi):
        return None   # 범위 내 해 없음
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        if fn(mid):
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return round(hi, 1)


def _binary_search_max(
    lo: float, hi: float, tol: float,
    fn,
    max_iter: int = 60,
) -> Optional[float]:
    """[lo, hi]에서 fn(x)==True인 최댓값 반환. lo에서도 False면 None."""
    if not fn(lo):
        return None
    if fn(hi):
        return hi
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        if fn(mid):
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return round(lo, 1)


def calc_fire_reverse(
    current_investable:    float,               # 현재 투자금 (만원)
    monthly_savings:       float,               # 현재 월 적립금 (만원)
    current_age:           int,
    target_fire_age:       int,                 # 달성하고 싶은 나이
    target_monthly_만원:   float,               # 달성하고 싶은 월배당 목표 (만원)
    avg_net_yield:         float = 5.0,         # [역할A] 세후 배당수익률 (%)
    div_growth_rate:       float = 5.0,         # 배당성장률 (데드 파라미터)
    cpi_rate:              float = 2.5,         # 인플레이션 (%)
    annual_savings_growth: float = 0.0,         # 연 적립금 증가율 (%, 0=고정)
    asset_growth_yield:    Optional[float] = None,  # [역할B] 자산 성장률 (None이면 avg_net_yield 사용)
) -> dict:
    """
    현재 조건 기준으로 목표(target_fire_age / target_monthly_만원) 달성을 위해
    무엇을 얼마나 바꿔야 하는지 역산한다.

    3가지 역산 경로:
      방법 1 (savings): 월 적립금을 X만원으로 늘리면 달성
      방법 2 (capital): 초기 투자금을 Y만원으로 늘리면 달성
      방법 3 (target ): 현재 조건 유지 시 target_fire_age에 달성 가능한 최대 월배당

    반환:
    {
        "current_fire_age":          int | None,
        "gap_years":                 int | None,   # 양수=늦음, 음수=빠름
        "target_fire_age":           int,
        "target_monthly_만원":       float,
        "already_achievable":        bool,
        "required_monthly_savings":  float | None, # 방법1 결과
        "savings_increase":          float | None, # 방법1: 증가분
        "required_initial_capital":  float | None, # 방법2 결과
        "capital_increase":          float | None, # 방법2: 증가분
        "achievable_monthly":        float | None, # 방법3: 현재 조건 최대 목표
        "message":                   str,
    }
    """
    # ── 공통 파라미터 묶음 ──────────────────────────────────────────────
    _common = dict(
        current_age           = current_age,
        target_age            = target_fire_age,
        avg_net_yield         = avg_net_yield,          # 역할A: 배당수익률
        asset_growth_yield    = asset_growth_yield,     # 역할B: 총수익률 (None이면 avg_net_yield 사용)
        div_growth_rate       = div_growth_rate,
        cpi_rate              = cpi_rate,
        custom_monthly_만원   = target_monthly_만원,
        annual_savings_growth = annual_savings_growth,
    )

    def _proj_age(investable: float, savings: float) -> int:
        """주어진 조건에서 custom 목표의 예상 달성 나이."""
        if target_monthly_만원 <= 0:
            return current_age
        r = calc_fire_engine(
            current_investable = investable,
            monthly_savings    = savings,
            **_common,
        )
        custom = r["targets"].get("custom")
        if not custom:
            return 999
        return int(custom.get("projected_fire_age") or 999)

    # ── 1. 현재 조건 기준 예상 달성 나이 ──────────────────────────────
    current_fire_age = _proj_age(current_investable, monthly_savings)
    if current_fire_age == 999:
        current_fire_age = None

    already_achievable = (
        current_fire_age is not None and current_fire_age <= target_fire_age
    )
    gap_years = (
        (current_fire_age - target_fire_age) if current_fire_age else None
    )

    # ── 2. 방법 1: 필요 월 적립금 역산 ───────────────────────────────
    # fn(s): monthly_savings=s 일 때 target_fire_age 내 달성
    fn_savings = lambda s: _proj_age(current_investable, s) <= target_fire_age

    required_monthly_savings = None
    savings_increase         = None

    if not already_achievable:
        # 상한: 목표 원금을 남은 기간 동안 직선 적립하는 최악 케이스
        years_left   = max(target_fire_age - current_age, 1)
        r_temp       = calc_fire_engine(
            current_investable=current_investable,
            monthly_savings=monthly_savings,
            **_common,
        )
        required_prin = (
            r_temp["targets"]["custom"]["required_principal"]
            if r_temp["targets"].get("custom") else current_investable * 10
        )
        savings_hi = max(required_prin / (years_left * 12), monthly_savings * 20, 500.0)

        req_s = _binary_search_min(
            lo=monthly_savings, hi=savings_hi, tol=0.5,
            fn=fn_savings,
        )
        if req_s is not None:
            required_monthly_savings = req_s
            savings_increase         = round(req_s - monthly_savings, 1)

    # ── 3. 방법 2: 필요 초기 투자금 역산 ─────────────────────────────
    fn_capital = lambda c: _proj_age(c, monthly_savings) <= target_fire_age

    required_initial_capital = None
    capital_increase         = None

    if not already_achievable:
        r_temp2      = calc_fire_engine(
            current_investable=current_investable,
            monthly_savings=monthly_savings,
            **_common,
        )
        required_prin2 = (
            r_temp2["targets"]["custom"]["required_principal"]
            if r_temp2["targets"].get("custom") else current_investable * 10
        )
        capital_hi = max(required_prin2 * 1.5, current_investable * 5, 10_000.0)

        req_c = _binary_search_min(
            lo=current_investable, hi=capital_hi, tol=100.0,
            fn=fn_capital,
        )
        if req_c is not None:
            required_initial_capital = req_c
            capital_increase         = round(req_c - current_investable, 0)

    # ── 4. 방법 3: 현재 조건으로 달성 가능한 최대 월배당 ──────────────
    # fn(m): monthly_target=m 일 때 target_fire_age 내 달성
    def fn_achievable(m: float) -> bool:
        if m <= 0:
            return True
        r = calc_fire_engine(
            current_investable    = current_investable,
            monthly_savings       = monthly_savings,
            current_age           = current_age,
            target_age            = target_fire_age,
            avg_net_yield         = avg_net_yield,
            asset_growth_yield    = asset_growth_yield,
            div_growth_rate       = div_growth_rate,
            cpi_rate              = cpi_rate,
            annual_savings_growth = annual_savings_growth,
            custom_monthly_만원   = m,
        )
        custom = r["targets"].get("custom")
        if not custom:
            return False
        age = custom.get("projected_fire_age")
        return age is not None and int(age) <= target_fire_age

    achievable_monthly = _binary_search_max(
        lo=1.0, hi=max(target_monthly_만원 * 3, 1000.0), tol=0.5,
        fn=fn_achievable,
    )

    # ── 5. 메시지 생성 ─────────────────────────────────────────────
    message = _make_reverse_message(
        current_age          = current_age,
        target_fire_age      = target_fire_age,
        target_monthly       = target_monthly_만원,
        current_fire_age     = current_fire_age,
        gap_years            = gap_years,
        already_achievable   = already_achievable,
        req_savings          = required_monthly_savings,
        savings_inc          = savings_increase,
        req_capital          = required_initial_capital,
        capital_inc          = capital_increase,
        achievable_monthly   = achievable_monthly,
        current_savings      = monthly_savings,
        current_capital      = current_investable,
    )

    return {
        "current_fire_age":         current_fire_age,
        "gap_years":                gap_years,
        "target_fire_age":          target_fire_age,
        "target_monthly_만원":      target_monthly_만원,
        "already_achievable":       already_achievable,
        "required_monthly_savings": required_monthly_savings,
        "savings_increase":         savings_increase,
        "required_initial_capital": required_initial_capital,
        "capital_increase":         capital_increase,
        "achievable_monthly":       achievable_monthly,
        "message":                  message,
    }


def _make_reverse_message(
    current_age:        int,
    target_fire_age:    int,
    target_monthly:     float,
    current_fire_age:   Optional[int],
    gap_years:          Optional[int],
    already_achievable: bool,
    req_savings:        Optional[float],
    savings_inc:        Optional[float],
    req_capital:        Optional[float],
    capital_inc:        Optional[float],
    achievable_monthly: Optional[float],
    current_savings:    float,
    current_capital:    float,
) -> str:
    lines = []

    if already_achievable:
        lines.append(
            f"현재 조건으로 {current_fire_age}세에 "
            f"월 {target_monthly:,.0f}만원 달성 가능합니다 "
            f"(목표 {target_fire_age}세보다 {target_fire_age - current_fire_age}년 빠름)."
        )
        return " ".join(lines)

    fire_str = f"{current_fire_age}세" if current_fire_age else "40년 내 미달성"
    lines.append(
        f"현재 조건 예상: {fire_str} | "
        f"목표: {target_fire_age}세 / 월 {target_monthly:,.0f}만원"
    )

    if req_savings is not None and savings_inc is not None:
        lines.append(
            f"\n방법 1 (월 적립 증액): {current_savings:,.0f}만원 → "
            f"{req_savings:,.1f}만원 (+{savings_inc:,.1f}만원)"
        )
    elif req_savings is None:
        lines.append("\n방법 1 (월 적립 증액): 현실적 범위 내 단독 달성 어려움")

    if req_capital is not None and capital_inc is not None:
        lines.append(
            f"\n방법 2 (초기 투자금 증액): {current_capital:,.0f}만원 → "
            f"{req_capital:,.0f}만원 (+{capital_inc:,.0f}만원)"
        )
    elif req_capital is None:
        lines.append("\n방법 2 (초기 투자금 증액): 현실적 범위 내 단독 달성 어려움")

    if achievable_monthly is not None:
        lines.append(
            f"\n방법 3 (목표 조정): 현재 조건으로 {target_fire_age}세까지 "
            f"달성 가능한 최대 월배당 → {achievable_monthly:,.1f}만원"
        )

    return "".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# 생애주기 기반 FIRE 엔진 (Lifecycle FIRE)
# 연령별로 월 적립금이 달라지는 현실적인 저축 패턴 반영
# ─────────────────────────────────────────────────────────────────────────────

def _get_monthly_savings_at_age(
    age: float,
    savings_stages: list[dict],
    default_savings: float,
) -> float:
    """
    현재 연령에 해당하는 월 적립금 반환.
    savings_stages = [{"from_age": 25, "to_age": 27, "monthly_savings": 20}, ...]
    """
    if not savings_stages:
        return default_savings
    for stage in savings_stages:
        if stage["from_age"] <= age < stage["to_age"]:
            return float(stage["monthly_savings"])
    # 마지막 구간 이후는 마지막 스테이지 값 사용
    return float(savings_stages[-1]["monthly_savings"])


def _simulate_fire_age_lifecycle(
    current_investable:  float,
    savings_stages:      list[dict],
    default_savings:     float,
    r_yield_monthly:     float,
    required_principal:  float,
    current_age:         int,
    max_years:           int = 50,
) -> Optional[int]:
    """생애주기 적립금 기반 FIRE 달성 나이 시뮬레이션."""
    portfolio = current_investable

    for year in range(1, max_years + 1):
        sim_age = current_age + year - 1
        monthly = _get_monthly_savings_at_age(sim_age, savings_stages, default_savings)

        for _ in range(12):
            portfolio = portfolio * (1 + r_yield_monthly) + monthly

        if portfolio >= required_principal:
            return current_age + year

    return None


def _build_timeline_lifecycle(
    current_investable:  float,
    savings_stages:      list[dict],
    default_savings:     float,
    r_yield_monthly:     float,
    current_age:         int,
    target_age:          int,
    targets:             dict,
    years:               int = 35,
) -> list[dict]:
    """생애주기 기반 연도별 자산 성장 타임라인."""
    timeline = []
    portfolio = current_investable

    for year in range(1, years + 1):
        sim_age = current_age + year - 1
        monthly = _get_monthly_savings_at_age(sim_age, savings_stages, default_savings)

        for _ in range(12):
            portfolio = portfolio * (1 + r_yield_monthly) + monthly

        age = current_age + year
        achieved = {k: portfolio >= v for k, v in targets.items()}

        timeline.append({
            "year":        year,
            "age":         age,
            "portfolio":   round(portfolio, 0),
            "monthly_savings": monthly,
            "is_target":   age == target_age,
            "achieved":    achieved,
        })

    return timeline


def calc_fire_engine_lifecycle(
    current_investable:  float,
    savings_stages:      list[dict],
    current_age:         int,
    target_age:          int   = 50,
    avg_net_yield:       float = 3.5,
    div_growth_rate:     float = 5.0,
    cpi_rate:            float = 2.5,
    custom_monthly_man_won: float = 0.0,
) -> dict:
    """
    생애주기 기반 FIRE 역산 엔진.

    savings_stages 예시:
      [
        {"from_age": 25, "to_age": 27, "monthly_savings": 20},
        {"from_age": 27, "to_age": 30, "monthly_savings": 100},
        {"from_age": 30, "to_age": 60, "monthly_savings": 200},
      ]

    반환 구조는 calc_fire_engine()과 동일.
    """
    if not savings_stages:
        # fallback: 스테이지 없으면 기본 엔진으로 위임
        return calc_fire_engine(
            current_investable  = current_investable,
            monthly_savings     = 0.0,
            current_age         = current_age,
            target_age          = target_age,
            avg_net_yield       = avg_net_yield,
            div_growth_rate     = div_growth_rate,
            cpi_rate            = cpi_rate,
            custom_monthly_man_won = custom_monthly_man_won,
        )

    years_to_fire = max(target_age - current_age, 1)
    r_yield       = avg_net_yield / 100.0
    r_yield_mo    = r_yield / 12.0
    r_cpi         = cpi_rate / 100.0

    # 현재 나이 기준 적립금 (표시용)
    current_monthly = _get_monthly_savings_at_age(
        current_age, savings_stages, savings_stages[0]["monthly_savings"]
    )

    results = {}
    target_list = dict(FIRE_TARGETS)
    if custom_monthly_man_won > 0:
        target_list["custom"] = {
            "label":       "맞춤 목표",
            "monthly_man_won": custom_monthly_man_won,
            "desc":        f"월 {custom_monthly_man_won:,}만원 배당 목표",
        }
    else:
        results["custom"] = None

    for key, tdef in target_list.items():
        nom_monthly = tdef.get("monthly_man_won") or tdef.get("monthly_만원", 0)

        real_monthly_at_fire = round(nom_monthly * ((1 + r_cpi) ** years_to_fire), 2)
        annual_target        = real_monthly_at_fire * 12
        required_principal   = round(annual_target / r_yield, 0) if r_yield > 0 else 0

        shortfall  = round(required_principal - current_investable, 0)
        already    = shortfall <= 0

        projected_fire_age = _simulate_fire_age_lifecycle(
            current_investable  = current_investable,
            savings_stages      = savings_stages,
            default_savings     = current_monthly,
            r_yield_monthly     = r_yield_mo,
            required_principal  = required_principal,
            current_age         = current_age,
        )

        achievable         = (projected_fire_age is not None and projected_fire_age <= target_age)
        years_to_achieve   = (projected_fire_age - current_age) if projected_fire_age else None
        gap                = (projected_fire_age - target_age)  if projected_fire_age else None

        results[key] = {
            "label":                   tdef["label"],
            "desc":                    tdef.get("desc", ""),
            "monthly_target_nominal":  nom_monthly,
            "monthly_target_real":     real_monthly_at_fire,
            "required_principal":      required_principal,
            "shortfall":               max(shortfall, 0),
            "already_achieved":        already,
            "monthly_pmt_needed":      0.0,
            "achievable_by_target":    achievable,
            "projected_fire_age":      projected_fire_age,
            "years_to_achieve":        years_to_achieve,
            "gap_years":               gap,
        }

    fire_timeline = _build_timeline_lifecycle(
        current_investable = current_investable,
        savings_stages     = savings_stages,
        default_savings    = current_monthly,
        r_yield_monthly    = r_yield_mo,
        current_age        = current_age,
        target_age         = target_age,
        targets            = {k: v["required_principal"] for k, v in results.items() if v},
        years              = min(years_to_fire + 5, 40),
    )

    earliest_type = None
    earliest_age  = None
    for k, v in results.items():
        if v and v["projected_fire_age"]:
            if earliest_age is None or v["projected_fire_age"] < earliest_age:
                earliest_age  = v["projected_fire_age"]
                earliest_type = k

    return {
        "targets":        results,
        "current_state": {
            "investable":           round(current_investable, 0),
            "monthly_savings":      current_monthly,
            "savings_stages":       savings_stages,
            "current_monthly_div":  round(current_investable * r_yield / 12, 2),
            "current_age":          current_age,
            "target_age":           target_age,
            "years_to_fire":        years_to_fire,
            "avg_net_yield_pct":    avg_net_yield,
            "div_growth_rate_pct":  div_growth_rate,
            "cpi_rate_pct":         cpi_rate,
            "lifecycle_mode":       True,
        },
        "fire_timeline":      fire_timeline,
        "recommended_action": _make_lifecycle_recommendation(results, savings_stages, target_age, current_age),
        "earliest_fire_type": earliest_type,
        "earliest_fire_age":  earliest_age,
    }


def _make_lifecycle_recommendation(
    results:        dict,
    savings_stages: list[dict],
    target_age:     int,
    current_age:    int,
) -> str:
    lines = []

    stage_desc = " -> ".join(
        f"{s['from_age']}~{s['to_age']}세 월 {s['monthly_savings']:,}만원"
        for s in savings_stages
    )
    lines.append(f"[생애주기 모드] 적립 계획: {stage_desc}")

    lean = results.get("lean")
    if lean and lean.get("projected_fire_age"):
        age = lean["projected_fire_age"]
        gap = age - target_age
        if gap <= 0:
            lines.append(f"린 파이어(월 120만원) {age}세 달성 (목표 {target_age}세보다 {abs(gap)}년 빠름).")
        else:
            lines.append(f"린 파이어(월 120만원) {age}세 달성 예상 (목표보다 {gap}년 늦음).")

    return " ".join(lines)

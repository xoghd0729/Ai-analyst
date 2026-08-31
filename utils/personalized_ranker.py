"""
personalized_ranker.py  v2 — E_v2 Ranker
==========================================
목표수익률(target_yield)을 Ranker 점수에서 분리.
Ranker는 '지금 당장 필요 수익률 맞추기'가 아니라
'미래 현금흐름 경로에 맞는 종목 선별'을 한다.

핵심 변경 (v1 → v2):
  - _yield_fit_score()        : 랭킹에서 제거 (FIRE engine 표시용으로만 유지)
  - abs_yield_fit_v2()        : Ranker에서 사용하는 절대 수익률 포화 곡선
  - _horizon_weights()        : 투자 기간에 따른 동적 가중치
  - sector / sector_group 2층 제약 : 동일 섹터 max 1개 + 동일 그룹 max 2개

fit_score (v2):
  abs_yield × w_y + risk × w_r + age × w_a + growth × w_g

  장기(≥20년): w_y=0.15  w_r=0.40  w_g=0.30  w_a=0.15
  중기(10-20년): w_y=0.20 w_r=0.40  w_g=0.20  w_a=0.20
  단기(<10년):   w_y=0.30 w_r=0.40  w_g=0.10  w_a=0.20
"""
from __future__ import annotations
import math
from utils.risk_engine import score_asset, _GATE_BY_RISK

# ── 절대 수익률 포화 곡선 v2 ─────────────────────────────────────────────
_ABS_YIELD_BREAKPOINTS: list[tuple[float, float]] = [
    (0.0,  0.0),
    (2.0, 40.0),
    (4.0, 70.0),
    (6.0, 85.0),
    (8.0, 92.0),
    (10.0, 95.0),
]


def abs_yield_fit_v2(expected_yield: float) -> float:
    """
    절대 수익률 포화 곡선 v2.
    target_yield에 의존하지 않는 절대 점수.
    10%+ 는 95로 캡 → 극고배당(커버드콜)이 랭킹을 과점하는 것 방지.

    구간 | score
    -----+------
    0%   |   0
    2%   |  40   (저배당 영역: 급경사)
    4%   |  70   (적정 배당)
    6%   |  85
    8%   |  92
    10%+ |  95   (고배당 캡)
    """
    y = max(0.0, float(expected_yield))
    bps = _ABS_YIELD_BREAKPOINTS
    if y >= bps[-1][0]:
        return bps[-1][1]
    for i in range(len(bps) - 1):
        y0, s0 = bps[i]
        y1, s1 = bps[i + 1]
        if y0 <= y < y1:
            t = (y - y0) / (y1 - y0)
            return round(s0 + t * (s1 - s0), 1)
    return 0.0


def _horizon_weights(target_fire_age: int, current_age: int) -> dict:
    """
    투자 기간(horizon = target_fire_age - current_age)에 따른 동적 가중치.

    장기 (≥20년) : 성장 위주, yield는 최소 (지금 yield보다 나중의 DPS 성장이 더 중요)
    중기 (10-19년): 균형
    단기 (<10년) : 즉시 현금흐름 중시, growth 축소
    """
    horizon = max(0, target_fire_age - current_age)
    if horizon >= 20:
        return {"abs_yield": 0.15, "risk": 0.40, "growth": 0.30, "age": 0.15}
    elif horizon >= 10:
        return {"abs_yield": 0.20, "risk": 0.40, "growth": 0.20, "age": 0.20}
    else:
        return {"abs_yield": 0.30, "risk": 0.40, "growth": 0.10, "age": 0.20}


# ── 보조 점수 함수 (v1 유지 + growth 개선) ───────────────────────────────

def _yield_fit_score(expected_yield: float, target_yield: float) -> float:
    """
    [DEPRECATED — Ranker에서 제거됨]
    FIRE engine 표시용으로만 유지. target_yield ±1%p 내: 100점.
    """
    diff = abs(expected_yield - target_yield)
    if diff <= 1.0:
        return 100.0
    if diff >= 5.0:
        return 0.0
    return round(100.0 * (1 - (diff - 1.0) / 4.0), 1)


def _risk_fit_score(composite_risk_score: float) -> float:
    """composite_risk_score 낮을수록 높은 점수. 0->100, 100->0."""
    return round(max(0.0, 100.0 - composite_risk_score), 1)


def _age_fit_score(candidate: dict, age: int) -> float:
    """
    나이대별 자산 적합도.
    - 젊음(<35):  성장 선호, ETF / 고수익 허용
    - 중간(35-54): 균형
    - 노년(55+):   안정 선호, 낮은 beta, ETF 가중
    """
    asset_class = str(candidate.get("asset_class", ""))
    beta        = float(candidate.get("beta", 1.0) or 1.0)
    is_etf      = "etf" in asset_class.lower() or "defensive" in asset_class

    if age >= 55:
        score = 70.0
        if is_etf:        score += 20.0
        if beta <= 0.8:   score += 10.0
        if beta >= 1.3:   score -= 20.0
    elif age >= 35:
        score = 75.0
        if is_etf:        score += 5.0
        if beta <= 1.0:   score += 5.0
    else:
        score = 70.0
        score += min(10.0, candidate.get("expected_yield", 3.0))
        if is_etf:        score += 5.0

    return round(min(100.0, score), 1)


def _growth_fit_score(candidate: dict, age: int) -> float:
    """
    DPS 성장률 기반 점수.
    - dps_yoy_pct 우선, 없으면 div_growth_5y 폴백 (ETF universe 호환)
    - 젊을수록 성장 중시, 나이들수록 연속 배당 연수 중시
    """
    dps_growth = float(
        candidate.get("dps_yoy_pct") or
        candidate.get("div_growth_5y") or 0
    )
    consecutive = float(
        candidate.get("consecutive_years") or
        candidate.get("div_years") or 0
    )

    if age < 35:
        return round(min(100.0, 50.0 + dps_growth * 5.0), 1)
    elif age >= 55:
        return round(min(100.0, 50.0 + consecutive * 0.8), 1)
    else:
        return round(min(100.0, 50.0 + dps_growth * 2.5 + consecutive * 0.4), 1)


def _calc_target_yield(
    monthly_target: float,    # 만원
    investable_amount: float, # 만원
    avg_growth_years: int = 5,
) -> tuple[float, float, bool]:
    """
    목표 월배당 역산 수익률.
    [Ranker에서 제거됨 — FIRE Engine과의 연결 및 사용자 표시용으로만 사용]

    반환값: (engine_yield, raw_yield, is_capped)
      engine_yield: 실제 엔진에 사용되는 값 (1~20% 클램프)
      raw_yield:    클램프 이전 순수 역산값 (사용자에게 "현실적 필요 수익률" 표시용)
      is_capped:    engine_yield가 상한(20%)에 걸렸는지 여부
    """
    if investable_amount <= 0:
        return 5.0, None, False
    annual_target = monthly_target * 12
    raw_yield     = annual_target / investable_amount * 100
    discount      = (1.05 ** avg_growth_years) ** 0.3
    adjusted      = raw_yield / discount
    capped        = adjusted > 20.0
    engine        = round(max(1.0, min(20.0, adjusted)), 2)
    return engine, round(adjusted, 2), capped


def rank_candidates(
    candidates: list[dict],
    age: int,
    investable_amount: float,
    monthly_target: float,
    risk_tolerance: str,
    macro: dict | None = None,
    weights: dict | None = None,
    target_fire_age: int = 65,
) -> list[dict]:
    """
    후보군 전체에 fit_score를 계산해 정렬된 리스트로 반환.
    BLOCK 종목은 결과에 포함되지 않음.

    v2 변경:
      - target_yield → Ranker 점수에서 제거
      - abs_yield_fit_v2() 사용 (절대 포화 곡선)
      - target_fire_age 기반 horizon → 동적 가중치

    Args:
        candidates     : list of asset dicts (kr_stock / us_stock / etf 혼합 가능)
        target_fire_age: FIRE 목표 나이 (horizon 계산용)
        weights        : 가중치 오버라이드 (없으면 horizon 기반 자동 결정)

    Returns:
        fit_score, composite_risk_score, risk_gate가 추가된 정렬 리스트 (BLOCK 제외)
    """
    # 가중치: 오버라이드 있으면 사용, 없으면 horizon 기반 자동 결정
    w = weights or _horizon_weights(target_fire_age, age)

    # target_yield는 FIRE engine / 표시용으로만 계산 (Ranker 점수에 미사용)
    target_yield, raw_target_yield, yield_capped = _calc_target_yield(monthly_target, investable_amount)
    block_thresh = _GATE_BY_RISK.get(risk_tolerance, 65.0)
    ranked = []

    for c in candidates:
        c = dict(c)
        ticker      = str(c.get("ticker") or c.get("stock_code", ""))
        asset_class = str(c.get("asset_class", "kr_stock"))
        ml_status   = str(c.get("ml_status", "INTACT"))
        survival_hz = c.get("survival_risk_score")

        # Risk Engine 적용
        risk_result = score_asset(
            ticker         = ticker,
            asset_class    = asset_class,
            ml_status      = ml_status,
            survival_hazard= survival_hz,
            macro          = macro,
            risk_tolerance = risk_tolerance,
        )
        c.update(risk_result)

        # BLOCK 제외
        if c["risk_gate"] == "BLOCK":
            c["fit_score"] = 0.0
            c["excluded"]  = True
            continue

        # Fit 점수 계산 (v2)
        expected_yield = float(c.get("expected_yield", 0) or c.get("div_yield", 0) or 0)
        ayf = abs_yield_fit_v2(expected_yield)   # 절대 수익률 포화 (v2)
        rf  = _risk_fit_score(c["composite_risk_score"])
        af  = _age_fit_score(c, age)
        gf  = _growth_fit_score(c, age)

        fit = (
            ayf * w["abs_yield"] +
            rf  * w["risk"]      +
            af  * w["age"]       +
            gf  * w["growth"]
        )
        c["fit_score"]          = round(fit, 2)
        c["target_yield"]       = target_yield        # FIRE engine용 (표시용)
        c["raw_target_yield"]   = raw_target_yield    # 순수 역산값
        c["yield_capped"]       = yield_capped
        c["abs_yield_fit"]      = ayf                 # v2 점수 (디버그용)
        c["risk_fit"]           = rf
        c["age_fit"]            = af
        c["growth_fit"]         = gf
        c["horizon_weights"]    = w                   # 사용된 가중치 (디버그용)
        c["excluded"]           = False
        ranked.append(c)

    ranked.sort(key=lambda x: -x["fit_score"])
    return ranked


def pick_personalized_portfolio(
    kr_candidates: list[dict],
    us_candidates: list[dict],
    etf_candidates: list[dict],
    age: int,
    investable_amount: float,
    monthly_target: float,
    risk_tolerance: str,
    macro: dict | None = None,
    n_stocks: int = 4,    # 주식 총 수 (KR+US)
    n_etfs: int = 2,
    target_fire_age: int = 65,
) -> dict:
    """
    KR/US/ETF 후보군 -> 최종 포트폴리오 구성.

    v2 섹터 제약:
      - 동일 sector    : max 1개 (세분화 레벨, 예: 금융_은행)
      - 동일 sector_group: max 2개 (상위 그룹, 예: 금융)
      → JB금융+우리금융(둘 다 금융_은행) 동시 편입 차단
      → JB금융+삼성화재(금융_은행+금융_보험) 허용

    Returns:
        {
            stocks: list[dict],
            etfs:   list[dict],
            target_yield: float,
            raw_target_yield: float | None,
            yield_capped: bool,
            summary: str,
        }
    """
    target_yield, raw_target_yield, yield_capped = _calc_target_yield(monthly_target, investable_amount)

    # 주식 통합 랭킹 (KR + US)
    all_stocks = kr_candidates + us_candidates
    ranked_stocks = rank_candidates(
        all_stocks, age, investable_amount, monthly_target,
        risk_tolerance, macro, target_fire_age=target_fire_age,
    )

    # 섹터 2층 제약
    selected_stocks: list[dict] = []
    sector_count:       dict[str, int] = {}   # 세분화 섹터 (금융_은행 등)
    sector_group_count: dict[str, int] = {}   # 상위 그룹    (금융 등)

    for s in ranked_stocks:
        sector       = str(s.get("sector", "기타"))
        sector_group = str(s.get("sector_group", "기타"))

        # 동일 세분화 섹터: max 1개
        if sector_count.get(sector, 0) >= 1:
            continue
        # 동일 상위 그룹: max 2개
        if sector_group_count.get(sector_group, 0) >= 2:
            continue

        selected_stocks.append(s)
        sector_count[sector]             = sector_count.get(sector, 0) + 1
        sector_group_count[sector_group] = sector_group_count.get(sector_group, 0) + 1

        if len(selected_stocks) >= n_stocks:
            break

    # ETF 랭킹 (별도 슬롯 — 섹터 제약 미적용)
    ranked_etfs = rank_candidates(
        etf_candidates, age, investable_amount, monthly_target,
        risk_tolerance, macro, target_fire_age=target_fire_age,
    )
    selected_etfs = ranked_etfs[:n_etfs]

    # 요약 메시지
    if monthly_target > 0 and investable_amount > 0:
        annual_div = sum(
            s.get("expected_yield", 0) * investable_amount / 100 / len(selected_stocks)
            for s in selected_stocks
        ) if selected_stocks else 0
        monthly_est = round(annual_div / 12, 1)
        summary = (
            f"목표 월배당 {monthly_target:,.0f}만원 | "
            f"필요 수익률 {target_yield:.1f}% | "
            f"예상 월배당 {monthly_est:,.0f}만원 | "
            f"주식 {len(selected_stocks)}개 + ETF {len(selected_etfs)}개"
        )
    else:
        summary = f"주식 {len(selected_stocks)}개 + ETF {len(selected_etfs)}개 선별 완료"

    return {
        "stocks":           selected_stocks,
        "etfs":             selected_etfs,
        "target_yield":     target_yield,
        "raw_target_yield": raw_target_yield,
        "yield_capped":     yield_capped,
        "summary":          summary,
    }


# ── CLI 테스트 ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # abs_yield_fit_v2 곡선 확인
    print("=== abs_yield_fit_v2 곡선 ===")
    for y in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]:
        print(f"  yield {y:2d}% → score {abs_yield_fit_v2(y):.1f}")

    # horizon 가중치 확인
    print("\n=== horizon 가중치 ===")
    for fire_age, cur_age in [(50, 25), (55, 40), (65, 60)]:
        w = _horizon_weights(fire_age, cur_age)
        h = fire_age - cur_age
        print(f"  horizon={h}년  → {w}")

    # 더미 후보군으로 랭킹 테스트
    print("\n=== 랭킹 테스트 E_v2 (moderate, 40세, 5000만원, 목표55세) ===")
    dummy_stocks = [
        {"ticker": "175330", "name": "JB금융지주", "asset_class": "kr_stock",
         "ml_status": "INTACT", "expected_yield": 4.86, "sector": "금융_은행",
         "sector_group": "금융", "dps_yoy_pct": 14.6},
        {"ticker": "316140", "name": "우리금융지주", "asset_class": "kr_stock",
         "ml_status": "INTACT", "expected_yield": 4.23, "sector": "금융_은행",
         "sector_group": "금융", "dps_yoy_pct": 13.3},
        {"ticker": "ABBV", "name": "AbbVie", "asset_class": "us_stock",
         "ml_status": "INTACT", "expected_yield": 3.8, "sector": "헬스케어",
         "sector_group": "헬스케어", "dps_yoy_pct": 5.8},
        {"ticker": "CVX", "name": "Chevron", "asset_class": "us_stock",
         "ml_status": "INTACT", "expected_yield": 4.1, "sector": "에너지",
         "sector_group": "에너지", "dps_yoy_pct": 4.0},
    ]
    dummy_etfs = [
        {"ticker": "SCHD", "name": "SCHD ETF", "asset_class": "us_div_etf",
         "ml_status": "INTACT", "expected_yield": 3.6, "div_growth_5y": 10.2},
        {"ticker": "JEPI", "name": "JEPI ETF", "asset_class": "us_div_etf",
         "ml_status": "INTACT", "expected_yield": 7.5, "div_growth_5y": 0.0},
    ]
    macro = {"regime": "NEUTRAL"}

    result = pick_personalized_portfolio(
        kr_candidates  = dummy_stocks[:2],
        us_candidates  = dummy_stocks[2:],
        etf_candidates = dummy_etfs,
        age=40, investable_amount=5_000, monthly_target=100,
        risk_tolerance="moderate", macro=macro,
        n_stocks=3, n_etfs=1, target_fire_age=55,
    )
    print(f"  {result['summary']}")
    print(f"  target_yield={result['target_yield']}% (FIRE용 표시값)")
    print(f"  horizon weights: {result['stocks'][0].get('horizon_weights') if result['stocks'] else '?'}")
    print()
    for s in result["stocks"]:
        print(f"  [{s['ticker']}] fit={s['fit_score']} "
              f"abs_y={s.get('abs_yield_fit'):.1f} risk={s['composite_risk_score']:.1f} "
              f"sector={s.get('sector')} group={s.get('sector_group')}")
    for e in result["etfs"]:
        print(f"  ETF [{e['ticker']}] fit={e['fit_score']:.2f} growth_fit={e.get('growth_fit'):.1f}")

"""
utils/monte_carlo.py — Monte Carlo Yield-on-Cost 시뮬레이션
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  현재 YoC 계산은 고정 성장률(예: SCHD 9%)로 단일 선을 그린다.
  하지만 실제 배당성장은 확률적이다.

  SCHD가 "평균 9% 성장"이라도:
    - 어떤 해는 +15%
    - 어떤 해는 +3%
    - 금융위기 해는 -10% (배당 컷)

  단일 선 대신 1,000번 시뮬레이션하면:
    "85% 확률로 20년 후 월 배당 30만원 이상"
  이 문장 하나가 투자자의 신뢰도를 완전히 바꾼다.

■ 시뮬레이션 방식
  각 연도마다:
    1. 배당성장률 = N(mean_growth, sigma) 정규분포에서 샘플링
    2. 배당 컷 발생 여부 = Bernoulli(p_cut) 확률 이벤트
    3. 컷 발생 시: 배당 × (1 - cut_severity) 로 감소

  1,000회 반복 → 연도별 분포 → P10/P50/P90 신뢰구간

■ 자산별 리스크 파라미터
  asset_class / etf_category별로:
    - sigma:         배당성장률 연간 표준편차 (변동성)
    - p_cut:         연간 배당컷 발생 확률
    - cut_severity:  컷 발생 시 삭감 비율 (평균)

■ 반환 구조
  {
    "p10_monthly": [...],    # P10: 하위 10% (비관 시나리오)
    "p50_monthly": [...],    # P50: 중앙값 (기준 시나리오)
    "p90_monthly": [...],    # P90: 상위 10% (낙관 시나리오)
    "years": [...],
    "confidence_at_target": float,   # 목표 월배당 달성 확률
    "p50_final": float,              # P50 기준 최종 월배당
    "p10_final": float,
    "p90_final": float,
    "prob_doubles": float,           # 월배당 2배 달성 확률
    "expected_cut_events": float,    # 예상 배당컷 발생 횟수 (20년간)
    "summary_message": str,
    "n_simulations": int,
  }
"""

from __future__ import annotations
import math
import random
from typing import Optional


# ─── 자산별 리스크 파라미터 ───────────────────────────────────

# (sigma_pct, annual_cut_prob, cut_severity)
# sigma: 배당성장률 표준편차 (%), cut_prob: 연간 컷 확률, severity: 컷 시 삭감률
_RISK_PARAMS: dict[str, tuple[float, float, float]] = {
    # etf_category 기준 (우선)
    "dividend_growth":  (5.0, 0.005, 0.20),  # SCHD·VIG: 낮은 컷 확률, 성장 변동
    "monthly_income":   (3.0, 0.020, 0.15),  # JEPI: 커버드콜 특성상 변동성 낮음
    "high_yield":       (6.0, 0.030, 0.25),  # VYM·HDV: 중간 리스크
    "reit":             (8.0, 0.040, 0.30),  # 리츠 ETF: 금리 민감
    "cash_equivalent":  (1.0, 0.000, 0.00),  # SGOV: 거의 변동 없음
    "long_bond":        (4.0, 0.000, 0.00),  # TLT: 이자수익 안정적
    "agg_bond":         (2.0, 0.000, 0.00),  # AGG: 안정
    "tips":             (3.0, 0.000, 0.00),  # SCHP: 인플레 연동
    # asset_class 기준 (fallback)
    "kr_stock":         (8.0, 0.080, 0.40),  # 한국 개별주: 높은 변동성
    "us_stock":         (7.0, 0.040, 0.35),  # 미국 개별주
    "us_div_etf":       (5.0, 0.010, 0.20),  # 미국 배당 ETF 평균
    "kr_etf":           (5.0, 0.010, 0.20),  # 한국 ETF
    "us_reit":          (9.0, 0.050, 0.35),  # 미국 리츠 개별
    "kr_reit":          (7.0, 0.040, 0.30),
    "defensive":        (2.0, 0.000, 0.00),  # 방어 자산
}

_DEFAULT_RISK = (6.0, 0.030, 0.25)   # 미분류 기본값


def _get_risk_params(etf_category: str, asset_class: str) -> tuple[float, float, float]:
    if etf_category and etf_category in _RISK_PARAMS:
        return _RISK_PARAMS[etf_category]
    if asset_class and asset_class in _RISK_PARAMS:
        return _RISK_PARAMS[asset_class]
    return _DEFAULT_RISK


def _normal_sample(mean: float, sigma: float, rng: random.Random) -> float:
    """Box-Muller 변환으로 정규분포 샘플링 (numpy 없이)."""
    u1 = rng.random()
    u2 = rng.random()
    z  = math.sqrt(-2 * math.log(max(u1, 1e-10))) * math.cos(2 * math.pi * u2)
    return mean + sigma * z


# ─── 거시 레짐별 배당 삭감 확률 배수 ─────────────────────────────
# MacroRegimeFilter 결과를 Monte Carlo 에 전달해 p_cut 동적 조정.
# 왜 필요한가: 경기침체기에는 같은 자산이라도 배당 삭감 가능성이 훨씬 높다.
#   안정성장기: 역사적 평균 p_cut
#   금리상승기: 리츠·채권 배당 압박 → ×1.3
#   경기침체기: 전방위 배당 삭감 → ×1.8
#   인플레이션기: 실질배당 감소 → ×1.2
#   금리하강기: 채권 이익·배당 개선 → ×0.85
_REGIME_CUT_MULTIPLIER: dict[str, float] = {
    "안정성장기":  0.70,
    "금리하강기":  0.85,
    "인플레이션기": 1.20,
    "금리상승기":  1.30,
    "경기침체기":  1.80,
}


def run_monte_carlo(
    recommendations:  list[dict],
    investable_amount: float,
    years:             int   = 20,
    n_simulations:     int   = 1000,
    monthly_target:    float = 0.0,
    seed:              Optional[int] = 42,
    macro_regime:      Optional[dict] = None,   # ← 거시 레짐 연동
    monthly_savings:   float = 0.0,             # ← 월 적립금 (만원) — FIRE 복리 반영
) -> dict:
    """
    포트폴리오 Monte Carlo 배당 시뮬레이션.

    Args:
        recommendations:   assign_weights() 결과
        investable_amount: 총 투자금 (만원)
        years:             시뮬레이션 기간
        n_simulations:     시뮬레이션 횟수 (기본 1,000)
        monthly_target:    목표 월배당 (만원) — 달성 확률 계산용
        seed:              재현성을 위한 랜덤 시드
        macro_regime:      MacroRegimeFilter 결과 dict.
                           regime 키를 보고 p_cut 에 _REGIME_CUT_MULTIPLIER 적용.
                           None 이면 "안정성장기" multiplier 1.0 사용.

    반환: 위 docstring 참조
    """
    if not recommendations:
        return _empty_result(years, n_simulations)

    rng = random.Random(seed)

    # ── 거시 레짐 → p_cut 배수 결정 ─────────────────────────────
    # MacroRegimeFilter 에서 전달받은 레짐에 따라 배당 삭감 확률을 조정.
    # 예: 경기침체기에는 모든 자산의 p_cut 이 1.8배로 상승.
    _regime = (macro_regime or {}).get("regime", "안정성장기")
    _confidence = float((macro_regime or {}).get("confidence", 0.5))
    # confidence 가중 적용: 레짐 확신도가 낮으면 multiplier 를 1.0 방향으로 당김
    _raw_mult = _REGIME_CUT_MULTIPLIER.get(_regime, 1.0)
    cut_multiplier = 1.0 + (_raw_mult - 1.0) * _confidence   # weighted blend

    # 자산별 기초 데이터 추출
    assets = []
    for rec in recommendations:
        invest  = float(rec.get("invest_amount_만원", 0) or 0)
        if invest <= 0:
            continue
        dy       = float(rec.get("dividend_yield", 0) or 0)
        net_tax  = float(rec.get("tax_rate_eff_pct", 15.0) or 15.0) / 100.0
        etf_cat  = rec.get("etf_category", "") or ""
        cls      = rec.get("asset_class", "") or ""

        # 배당성장률 (projection 기반)
        from utils.dividend_projection import _get_div_growth_rate
        mean_growth = _get_div_growth_rate(rec)

        sigma, p_cut, cut_sev = _get_risk_params(etf_cat, cls)
        p_cut = min(p_cut * cut_multiplier, 0.60)   # 레짐 반영, 최대 60% cap

        assets.append({
            "invest":      invest,
            "dy":          dy,
            "net_tax":     net_tax,
            "mean_growth": mean_growth,   # 연 배당성장률 평균 (%)
            "sigma":       sigma,          # 성장률 표준편차 (%)
            "p_cut":       p_cut,          # 연간 배당컷 확률
            "cut_sev":     cut_sev,        # 컷 발생 시 평균 삭감률
        })

    if not assets:
        return _empty_result(years, n_simulations)

    # ── Monte Carlo 루프 ─────────────────────────────────────
    # all_paths[sim_idx][year_idx] = 월 세후 배당 (만원)
    all_paths: list[list[float]] = []
    cut_counts: list[int] = []

    # 월 적립금 → 자산별 비중대로 배분 (연간)
    annual_savings = monthly_savings * 12.0
    total_invest = sum(a["invest"] for a in assets) or 1.0
    asset_weights = [a["invest"] / total_invest for a in assets]

    for _ in range(n_simulations):
        yearly_monthly_net = []
        sim_cuts = 0

        # 각 연도별 포트폴리오 배당 계산
        current_yields  = [a["dy"]     for a in assets]   # 자산별 현재 yield
        current_invests = [a["invest"] for a in assets]   # 적립 누적 추적

        for t in range(1, years + 1):
            annual_net_total = 0.0

            for i, asset in enumerate(assets):
                # 이번 연도 성장률 샘플링 (정규분포)
                g = _normal_sample(asset["mean_growth"], asset["sigma"], rng) / 100.0

                # 배당 컷 이벤트
                if rng.random() < asset["p_cut"]:
                    cut_severity = _normal_sample(asset["cut_sev"] * 100, 10.0, rng) / 100.0
                    cut_severity = max(0.05, min(0.70, cut_severity))
                    current_yields[i] *= (1 - cut_severity)
                    sim_cuts += 1
                else:
                    current_yields[i] = max(0.1, current_yields[i] * (1 + g))

                # 연말 적립금 추가 (비중 비례 배분)
                current_invests[i] += annual_savings * asset_weights[i]

                annual_gross = current_invests[i] * current_yields[i] / 100.0
                annual_net   = annual_gross * (1 - asset["net_tax"])
                annual_net_total += annual_net

            monthly_net = annual_net_total / 12.0
            yearly_monthly_net.append(round(monthly_net, 2))

        all_paths.append(yearly_monthly_net)
        cut_counts.append(sim_cuts)

    # ── 퍼센타일 계산 ─────────────────────────────────────────
    p10_list = []
    p50_list = []
    p90_list = []

    for t in range(years):
        year_values = sorted(path[t] for path in all_paths)
        n = len(year_values)
        p10_list.append(round(year_values[int(n * 0.10)], 2))
        p50_list.append(round(year_values[int(n * 0.50)], 2))
        p90_list.append(round(year_values[int(n * 0.90)], 2))

    year_list  = list(range(1, years + 1))
    p50_final  = p50_list[-1] if p50_list else 0
    p10_final  = p10_list[-1] if p10_list else 0
    p90_final  = p90_list[-1] if p90_list else 0

    # ── 목표 달성 확률 ────────────────────────────────────────
    conf_at_target = 0.0
    if monthly_target > 0:
        final_values = [path[-1] for path in all_paths]
        hits = sum(1 for v in final_values if v >= monthly_target)
        conf_at_target = round(hits / n_simulations * 100, 1)

    # ── 2배 달성 확률 ─────────────────────────────────────────
    initial_monthly = sum(
        a["invest"] * a["dy"] / 100.0 * (1 - a["net_tax"]) / 12.0
        for a in assets
    )
    doubles_target = initial_monthly * 2
    doubles_hits   = sum(
        1 for path in all_paths if path[-1] >= doubles_target
    )
    prob_doubles = round(doubles_hits / n_simulations * 100, 1)

    # ── 기대 배당컷 횟수 ──────────────────────────────────────
    expected_cuts = round(sum(cut_counts) / n_simulations, 1)

    # ── 요약 메시지 ───────────────────────────────────────────
    summary = _make_summary(
        p50_final      = p50_final,
        p10_final      = p10_final,
        p90_final      = p90_final,
        conf_at_target = conf_at_target,
        monthly_target = monthly_target,
        prob_doubles   = prob_doubles,
        expected_cuts  = expected_cuts,
        years          = years,
    )

    # ── 연도별 스냅샷 (y1/y5/y10/y20) ────────────────────────
    snapshots = []
    for i in [0, 4, 9, min(19, years-1)]:
        if i < years:
            snapshots.append({
                "year":  year_list[i],
                "p10":   p10_list[i],
                "p50":   p50_list[i],
                "p90":   p90_list[i],
                "range": round(p90_list[i] - p10_list[i], 2),
            })

    return {
        "years":             year_list,
        "p10_monthly":       p10_list,
        "p50_monthly":       p50_list,
        "p90_monthly":       p90_list,
        "p50_final":         p50_final,
        "p10_final":         p10_final,
        "p90_final":         p90_final,
        "initial_monthly":   round(initial_monthly, 2),
        "confidence_at_target": conf_at_target,
        "monthly_target":    monthly_target,
        "prob_doubles":      prob_doubles,
        "expected_cut_events": expected_cuts,
        "snapshots":         snapshots,
        "summary_message":   summary,
        "n_simulations":     n_simulations,
    }


def _make_summary(
    p50_final, p10_final, p90_final,
    conf_at_target, monthly_target,
    prob_doubles, expected_cuts, years,
) -> str:
    lines = []

    lines.append(
        f"{years}년 후 월 배당 중앙값 {round(p50_final)}만원 "
        f"(비관 {round(p10_final)}만원 ~ 낙관 {round(p90_final)}만원, 80% 신뢰구간)."
    )

    if monthly_target > 0:
        emoji = "✅" if conf_at_target >= 70 else ("⚠️" if conf_at_target >= 40 else "❌")
        lines.append(
            f"{emoji} 목표 월 {round(monthly_target)}만원 달성 확률: {conf_at_target}%."
        )

    if prob_doubles >= 80:
        lines.append(f"✅ 월배당 2배 달성 확률 {prob_doubles}% — 높은 성장 신뢰도.")
    elif prob_doubles >= 50:
        lines.append(f"🟡 월배당 2배 달성 확률 {prob_doubles}%.")
    else:
        lines.append(f"⚠️ 월배당 2배 달성 확률 {prob_doubles}% — 성장 동력 강화 필요.")

    if expected_cuts > 3:
        lines.append(f"⚠️ 예상 배당컷 이벤트: {expected_cuts}회 (분산 투자로 충격 완화 필요).")
    elif expected_cuts > 0:
        lines.append(f"📋 예상 배당컷 이벤트: {expected_cuts}회 (ETF 중심 포트폴리오로 최소화됨).")

    return " ".join(lines)


def _empty_result(years: int, n: int) -> dict:
    zeros = [0.0] * years
    return {
        "years": list(range(1, years+1)),
        "p10_monthly": zeros, "p50_monthly": zeros, "p90_monthly": zeros,
        "p50_final": 0, "p10_final": 0, "p90_final": 0,
        "initial_monthly": 0,
        "confidence_at_target": 0, "monthly_target": 0,
        "prob_doubles": 0, "expected_cut_events": 0,
        "snapshots": [], "summary_message": "", "n_simulations": n,
    }

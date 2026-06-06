"""
utils/survival.py — 포트폴리오 생존확률 (Portfolio Survival Probability)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 만드는가 (헤드라인 지표)
  사용자가 진짜 궁금한 건 "월배당 얼마"가 아니라
  "이 월급이 20년 뒤에도 계속 나오는가" 이다.
  이 모듈은 흩어져 있던 ML(P_BROKEN/P_WEAKENING)·Monte Carlo·집중도를
  '생존확률' 단일 숫자로 묶는다.

기존 Monte Carlo와 무엇이 다른가 (리브랜딩이 아닌 이유)
  1) ML 구동: 종목별 배당컷 확률을 자산군 일반값이 아니라 검증된
     모델의 P_BROKEN/P_WEAKENING 으로 구동 (근시일수록 ML 가중, 시간 감쇠).
  2) 상관 충격: 현실의 배당컷은 독립이 아니라 섹터·국가 단위로 동시 발생
     (2020 항공/여행, 금리상승기 리츠, 금융위기 은행). 공통충격 인자를 넣어
     '겉은 분산, 실제는 집중'을 생존확률 하락으로 드러낸다.

생존 정의
  실질(물가조정) 월배당이 '목표(또는 초기의 80%)' 이상을
  전 기간(또는 만기) 유지할 확률.

반환
  survival_probability(전기간 유지%), endpoint_probability(만기 유지%),
  p10/p50 실질 월배당, worst_year_real, concentration(집중 그룹), summary
"""
from __future__ import annotations

import math
import random
from typing import Optional

try:
    from utils.monte_carlo import _normal_sample, _get_risk_params
except Exception:  # pragma: no cover
    def _normal_sample(mean, sigma, rng):
        return rng.gauss(mean, sigma)
    def _get_risk_params(etf_category, asset_class):
        return (8.0, 0.03, 0.30)


# ── 섹터·국가 공통충격(동시 배당컷) 연간 확률 ────────────────
# ★ 데이터 보정(2015~2024 KR, 그룹의 그 해 삭감비율 40%+ = 동시충격 연도):
#   - 일반 종목: 평균삭감 22%지만 동시충격 0% → 삭감이 흩어짐(개별적).
#     공통충격은 낮게, 개별 해저드(ML)가 처리.
#   - 금융: 평균 17%로 낮지만 동시충격 10% → 깎일 땐 함께 깎임(상관 높음).
#   주의: 분석연도 10년 소표본이라 근사값. 미국/리츠는 미측정(가정값).
_GROUP_SHOCK_PROB = {
    "kr_financial": 0.080,   # 측정: 동시충격 10%/년 (소표본 보정)
    "kr_telecom":   0.020,   # 표본부족 → 보수적 낮게 (개별 삭감 희소)
    "kr_cyclical":  0.040,   # 미측정(경기민감 가정) — 향후 보정 대상
    "kr_stock":     0.010,   # 측정: 동시충격 0% → 개별 해저드가 처리
    "us_stock":     0.012,   # 가정 (US 배당귀족 동시컷 드묾)
    "reit":         0.035,   # 가정 (금리 민감)
    "div_etf":      0.012,
    "bond":         0.004,
    "default":      0.020,
}


def _shock_group(rec: dict) -> str:
    cls = (rec.get("asset_class") or "").lower()
    sector = (rec.get("sector") or "") + (rec.get("name") or "")
    if "reit" in cls:
        return "reit"
    if cls in ("us_div_etf", "kr_etf"):
        return "div_etf"
    if cls == "defensive":
        return "bond"
    if cls == "us_stock":
        return "us_stock"
    if cls == "kr_stock":
        if any(k in sector for k in ("금융", "은행", "보험", "증권", "지주", "캐피탈")):
            return "kr_financial"
        if any(k in sector for k in ("통신", "텔레콤", "KT", "SK텔")):
            return "kr_telecom"
        if any(k in sector for k in ("정유", "화학", "철강", "건설", "조선", "에너지", "기계", "자동차")):
            return "kr_cyclical"
        return "kr_stock"
    return "default"


def _ml_hazard(rec: dict, base: float) -> float:
    """ML 확률(P_BROKEN/P_WEAKENING)을 연간 배당컷 해저드로 변환.
    근시(1~3년)엔 ML이 지배, 장기엔 base로 회귀(시간감쇠는 호출부에서)."""
    p_brk = float(rec.get("P_BROKEN", 0) or 0)
    p_wkn = float(rec.get("P_WEAKENING", 0) or 0)
    if p_brk <= 0 and p_wkn <= 0:
        return base
    ml_h = 0.7 * p_brk + 0.35 * p_wkn
    return max(base, min(0.60, ml_h))


def run_survival(
    recommendations: list[dict],
    years: int = 20,
    n_simulations: int = 2000,
    monthly_target: float = 0.0,
    cpi_rate: float = 2.5,
    seed: Optional[int] = 42,
    macro_regime: Optional[dict] = None,
    correlated: bool = True,
    ml_driven: bool = True,
    achievement_prob: Optional[float] = None,   # 목표 달성확률(Monte Carlo) — 종합점수용
) -> dict:
    rng = random.Random(seed)

    # 레짐 → 충격 배수
    shock_mult = 1.0
    if macro_regime:
        reg = (macro_regime.get("regime") or "").lower()
        if "recession" in reg or "침체" in reg:
            shock_mult = 1.8
        elif "rate_up" in reg or "긴축" in reg:
            shock_mult = 1.3

    assets = []
    group_weight: dict[str, float] = {}
    for rec in recommendations:
        invest = float(rec.get("invest_amount_만원", 0) or 0)
        if invest <= 0:
            continue
        dy      = float(rec.get("dividend_yield", 0) or 0)
        net_tax = float(rec.get("tax_rate_eff_pct", 15.0) or 15.0) / 100.0
        cls     = rec.get("asset_class", "") or ""
        etf_cat = rec.get("etf_category", "") or ""
        try:
            from utils.dividend_projection import _get_div_growth_rate
            mean_growth = _get_div_growth_rate(rec)
        except Exception:
            mean_growth = float(rec.get("div_growth_rate_pct", 4.0) or 4.0)
        sigma, base_cut, cut_sev = _get_risk_params(etf_cat, cls)
        ml_h = _ml_hazard(rec, base_cut) if ml_driven else base_cut
        grp = _shock_group(rec)
        group_weight[grp] = group_weight.get(grp, 0.0) + invest
        assets.append({
            "invest": invest, "dy": dy, "net_tax": net_tax,
            "mean_growth": mean_growth, "sigma": sigma,
            "base_cut": base_cut, "ml_h": ml_h, "cut_sev": cut_sev, "grp": grp,
        })

    if not assets:
        return {"survival_probability": 0.0, "error": "no_assets"}

    # 초기(연1) 실질 월배당 = 생존 기준선 산출용
    init_annual_net = sum(a["invest"] * a["dy"] / 100.0 * (1 - a["net_tax"]) for a in assets)
    init_monthly = init_annual_net / 12.0
    # 생존 = '소득 지속성'. 야망 목표(monthly_target)가 아니라 현재 소득 대비
    # 유지율로 본다. 단, 목표가 현재 소득 이하(인출/은퇴 단계)면 목표를 기준으로.
    if 0 < monthly_target <= init_monthly:
        threshold = monthly_target
    else:
        threshold = init_monthly * 0.80

    groups = list(group_weight.keys())

    strict_hits = 0
    endpoint_hits = 0
    min_reals: list[float] = []
    final_reals: list[float] = []

    min_noms: list[float] = []
    for _ in range(n_simulations):
        current_yields = [a["dy"] for a in assets]
        survived_all = True
        min_nominal = float("inf")
        final_nominal = 0.0
        final_real = 0.0

        for t in range(1, years + 1):
            # 1) 상관 충격: 그룹별 공통충격 발생 여부 결정
            shocked_groups = set()
            if correlated:
                for g in groups:
                    p_g = _GROUP_SHOCK_PROB.get(g, _GROUP_SHOCK_PROB["default"]) * shock_mult
                    if rng.random() < p_g:
                        shocked_groups.add(g)

            annual_net_total = 0.0
            for i, a in enumerate(assets):
                # ML 해저드: 근시 가중, 장기 base 회귀 (tau=3)
                decay = math.exp(-(t - 1) / 3.0)
                hazard = a["base_cut"] + (a["ml_h"] - a["base_cut"]) * decay
                hazard = max(0.0, min(0.60, hazard))

                cut = False
                if a["grp"] in shocked_groups:
                    cut = True                       # 그룹 동시 충격
                elif rng.random() < hazard:
                    cut = True                       # 개별 해저드

                if cut:
                    sev = _normal_sample(a["cut_sev"] * 100, 10.0, rng) / 100.0
                    sev = max(0.05, min(0.70, sev))
                    current_yields[i] *= (1 - sev)
                else:
                    g = _normal_sample(a["mean_growth"], a["sigma"], rng) / 100.0
                    current_yields[i] = max(0.1, current_yields[i] * (1 + g))

                annual_gross = a["invest"] * current_yields[i] / 100.0
                annual_net_total += annual_gross * (1 - a["net_tax"])

            monthly_nominal = annual_net_total / 12.0
            monthly_real = monthly_nominal / ((1 + cpi_rate / 100.0) ** t)
            # 생존(소득 지속성) = '명목' 소득이 기준선 이상 유지 = 배당컷 보호.
            # (물가 방어는 별도 지표로 분리 — 섞으면 채권형이 안 깎여도 점수가 0이 됨)
            if monthly_nominal < threshold:
                survived_all = False
            min_nominal = min(min_nominal, monthly_nominal)
            final_nominal = monthly_nominal
            final_real = monthly_real

        if survived_all:
            strict_hits += 1
        if final_nominal >= threshold:
            endpoint_hits += 1
        min_noms.append(min_nominal)
        final_reals.append(final_real)

    min_noms.sort()
    final_reals.sort()
    n = n_simulations
    total_w = sum(group_weight.values()) or 1.0
    conc = sorted(((g, round(w / total_w * 100, 1)) for g, w in group_weight.items()),
                  key=lambda x: -x[1])
    hhi = round(sum((w / total_w) ** 2 for w in group_weight.values()), 3)

    # ── Risk Contribution: 비중이 아니라 '위험 기여도' ─────────────
    risk_by_group: dict[str, float] = {}
    for a in assets:
        eff = a["ml_h"] + _GROUP_SHOCK_PROB.get(a["grp"], _GROUP_SHOCK_PROB["default"])
        risk_by_group[a["grp"]] = risk_by_group.get(a["grp"], 0.0) + a["invest"] * eff
    risk_total = sum(risk_by_group.values()) or 1.0
    risk_contribution = sorted(
        ((g, round(r / risk_total * 100, 1)) for g, r in risk_by_group.items()),
        key=lambda x: -x[1])

    # 확률은 99%로 캡 — '100% = 절대 안 망함'으로 들리는 것 방지 (금융 신뢰도)
    surv = min(99.0, round(strict_hits / n * 100, 1))
    endp = min(99.0, round(endpoint_hits / n * 100, 1))

    # ── 인플레이션 방어 (생존과 분리된 별도 축) ────────────────────
    # 20년 후 '실질' 월배당이 초기 대비 얼마나 구매력을 지키나.
    p50_final_real = final_reals[int(n * 0.50)]
    infl_ratio = (p50_final_real / init_monthly) if init_monthly > 0 else 0.0
    infl_score = round(max(0.0, min(100.0, infl_ratio * 100)))
    infl_level = "강" if infl_ratio >= 1.0 else ("보통" if infl_ratio >= 0.8 else "약")

    # ── 배당컷 위험 (포트폴리오 가중 ML 해저드) ────────────────────
    cut_w = sum(a["invest"] * a["ml_h"] for a in assets) / (sum(a["invest"] for a in assets) or 1.0)
    cut_level = "높음" if cut_w >= 0.18 else ("중간" if cut_w >= 0.10 else "낮음")

    # ── 소득 지속성 점수 (생존+만기, 집중 페널티) ──────────────────
    # 100점 만점은 신뢰도를 깎으므로 95로 캡 (기관도 만점 잘 안 씀)
    income_score = round(max(0.0, min(95.0, 0.6 * surv + 0.4 * endp - max(0.0, hhi - 0.30) * 40.0)))

    # ── 단일 헤드라인: AI 현금흐름 건강도 (모든 축 통합) ───────────
    ach = float(achievement_prob) if achievement_prob is not None else endp
    conc_quality = max(0.0, min(100.0, (1 - hhi) * 100))
    health = round(0.40 * surv + 0.25 * ach + 0.20 * infl_score + 0.15 * conc_quality)
    health = max(0, min(95, health))   # 만점(100) 회피 — 신뢰도
    grade = ("A+" if health >= 85 else "A" if health >= 75 else "B" if health >= 62
             else "C" if health >= 50 else "D")

    return {
        "health_score":      health,            # ★ 단일 헤드라인 점수 0~100
        "health_grade":      grade,
        "sub_metrics": {                         # 헤드라인 아래 분해 지표
            "achievement":      round(ach, 1),
            "survival":         surv,
            "cut_risk_level":   cut_level,
            "inflation_level":  infl_level,
            "inflation_score":  infl_score,
        },
        "income_sustainability_score": income_score,
        "achievement_prob":  round(float(achievement_prob), 1) if achievement_prob is not None else None,
        "risk_contribution": risk_contribution,
        "survival_probability":  surv,
        "endpoint_probability":  endp,
        "threshold_monthly_만원": round(threshold, 1),
        "initial_monthly_만원":   round(init_monthly, 1),
        "p10_worst_monthly":     round(min_noms[int(n * 0.10)], 1),   # 비관 시 최악연도 명목 월배당
        "p50_final_real":        round(p50_final_real, 1),            # 20년 후 실질(구매력)
        "concentration_hhi":     hhi,
        "concentration_groups":  conc,
        "ml_driven":             ml_driven,
        "correlated":            correlated,
        "summary":               _summary(surv, hhi, conc, risk_contribution, threshold),
    }


def _summary(surv: float, hhi: float, conc: list, risk_contrib: list, threshold: float) -> str:
    risk = "높음" if hhi >= 0.4 else ("보통" if hhi >= 0.25 else "낮음")
    msg = (f"20년간 월배당 소득({threshold:.0f}만원 이상) 지속 확률 {surv:.0f}%. "
           f"집중위험 {risk}(HHI {hhi}).")
    # 비중 대비 위험 기여가 큰 그룹을 짚는다 ("28%인데 위험 52%")
    weight_map = dict(conc)
    for g, rpct in risk_contrib[:1]:
        wpct = weight_map.get(g, 0)
        if rpct >= 35 and rpct >= wpct * 1.4:
            msg += f" '{g}'는 비중 {wpct:.0f}%지만 위험 기여 {rpct:.0f}% — 분산 효과 점검 필요."
    return msg


def survival_optimal_compare(
    recommendations: list[dict],
    monthly_target: float = 0.0,
    macro_regime: Optional[dict] = None,
    achievement_prob: Optional[float] = None,
) -> dict:
    """현재 배분 vs '분산 보정' 배분의 생존확률 비교 (표시용, 실제 배분은 안 바꿈).
    KR 개별주(kr_stock/financial/cyclical) 비중 30%를 분산 자산(ETF/방어)으로 이전한
    가상 포트폴리오의 생존확률을 함께 계산해, 차별점을 눈으로 보여준다.
    """
    cur = run_survival(recommendations, monthly_target=monthly_target,
                       macro_regime=macro_regime, achievement_prob=achievement_prob)

    KR_IND = {"kr_stock", "kr_financial", "kr_cyclical"}
    DIVERSE = ("div_etf", "bond", "us_stock", "reit")
    total_invest = sum(float(r.get("invest_amount_만원", 0) or 0) for r in recommendations) or 1.0
    variant = [dict(r) for r in recommendations]
    freed = 0.0
    trim_by_group: dict[str, float] = {}      # 줄인 금액(그룹별)
    for r in variant:
        g = _shock_group(r)
        if g in KR_IND:
            amt = float(r.get("invest_amount_만원", 0) or 0)
            cut = amt * 0.30
            r["invest_amount_만원"] = amt - cut
            freed += cut
            trim_by_group[g] = trim_by_group.get(g, 0.0) + cut
    # 분산 자산에 비례 배분
    targets = [r for r in variant if _shock_group(r) in DIVERSE]
    add_by_group: dict[str, float] = {}
    if targets and freed > 0:
        base = sum(float(r.get("invest_amount_만원", 0) or 0) for r in targets) or 1.0
        for r in targets:
            share = float(r.get("invest_amount_만원", 0) or 0) / base
            added = freed * share
            r["invest_amount_만원"] = float(r.get("invest_amount_만원", 0) or 0) + added
            g = _shock_group(r)
            add_by_group[g] = add_by_group.get(g, 0.0) + added

    opt = run_survival(variant, monthly_target=monthly_target,
                       macro_regime=macro_regime, achievement_prob=achievement_prob)

    # ── 실행 가능한 행동 제안 생성 ───────────────────────────────
    _LABEL = {"kr_stock": "KR 개별주", "kr_financial": "KR 금융주", "kr_cyclical": "KR 경기민감주",
              "div_etf": "배당 ETF", "bond": "방어형(채권)", "us_stock": "US 개별주", "reit": "리츠"}
    MIN_PCT = 2.0   # 2%p 미만 자잘한 이전은 숨김 (데모 가독성)
    trims = [(g, a) for g, a in sorted(trim_by_group.items(), key=lambda x: -x[1])
             if a / total_invest * 100 >= MIN_PCT]
    adds  = [(g, a) for g, a in sorted(add_by_group.items(), key=lambda x: -x[1])
             if a / total_invest * 100 >= MIN_PCT][:3]   # 옮길 곳은 상위 3개만
    actions = ([{"type": "trim", "group": g, "label": _LABEL.get(g, g),
                 "amount_만원": round(a), "pct_of_total": round(a / total_invest * 100, 1)}
                for g, a in trims]
               + [{"type": "add", "group": g, "label": _LABEL.get(g, g),
                   "amount_만원": round(a), "pct_of_total": round(a / total_invest * 100, 1)}
                  for g, a in adds])

    delta = round(opt["survival_probability"] - cur["survival_probability"], 1)
    trim_txt = ", ".join(f"{_LABEL.get(g,g)} {round(a/total_invest*100)}%p" for g, a in trims)
    add_txt  = ", ".join(_LABEL.get(g, g) for g, _ in adds)
    action_summary = (
        f"{trim_txt} 줄여 {add_txt}로 옮기면 생존확률 {delta:+.0f}%p 개선"
        if trims and delta > 0 else "현재 배분이 이미 균형적입니다."
    )

    return {
        "current":   {"survival": cur["survival_probability"],
                      "income_score": cur["income_sustainability_score"],
                      "hhi": cur["concentration_hhi"]},
        "optimized": {"survival": opt["survival_probability"],
                      "income_score": opt["income_sustainability_score"],
                      "hhi": opt["concentration_hhi"]},
        "delta_survival": delta,
        "actions": actions,                  # 실행 가능한 구체적 이전 제안
        "action_summary": action_summary,
        "note": "KR 개별주 비중 30%를 분산자산으로 이전한 가상 배분과 비교 (표시용, 실제 배분 불변).",
    }


# ── 자체 테스트 (numpy 불필요, 합성 포트폴리오) ────────────────
if __name__ == "__main__":
    # 집중 포트폴리오 (금융 몰빵) vs 분산 포트폴리오 생존확률 비교
    concentrated = [
        {"name": "신한지주", "asset_class": "kr_stock", "sector": "금융",
         "invest_amount_만원": 3000, "dividend_yield": 5.0, "P_BROKEN": 0.10, "P_WEAKENING": 0.20},
        {"name": "하나금융지주", "asset_class": "kr_stock", "sector": "금융",
         "invest_amount_만원": 3000, "dividend_yield": 5.5, "P_BROKEN": 0.12, "P_WEAKENING": 0.22},
        {"name": "삼성화재", "asset_class": "kr_stock", "sector": "보험",
         "invest_amount_만원": 2000, "dividend_yield": 4.5, "P_BROKEN": 0.05, "P_WEAKENING": 0.10},
        {"name": "KB금융", "asset_class": "kr_stock", "sector": "금융",
         "invest_amount_만원": 2000, "dividend_yield": 5.2, "P_BROKEN": 0.15, "P_WEAKENING": 0.25},
    ]
    diversified = [
        {"name": "SCHD", "asset_class": "us_div_etf", "etf_category": "dividend_growth",
         "invest_amount_만원": 3000, "dividend_yield": 3.5, "P_BROKEN": 0.02, "P_WEAKENING": 0.05},
        {"name": "신한지주", "asset_class": "kr_stock", "sector": "금융",
         "invest_amount_만원": 2000, "dividend_yield": 5.0, "P_BROKEN": 0.10, "P_WEAKENING": 0.20},
        {"name": "삼성화재", "asset_class": "kr_stock", "sector": "보험",
         "invest_amount_만원": 2000, "dividend_yield": 4.5, "P_BROKEN": 0.05, "P_WEAKENING": 0.10},
        {"name": "Realty Income", "asset_class": "us_reit",
         "invest_amount_만원": 1500, "dividend_yield": 5.5, "P_BROKEN": 0.08, "P_WEAKENING": 0.12},
        {"name": "SGOV", "asset_class": "defensive", "etf_category": "cash_equivalent",
         "invest_amount_만원": 1500, "dividend_yield": 5.0, "P_BROKEN": 0.0, "P_WEAKENING": 0.0},
    ]
    for label, port in (("집중(금융 몰빵)", concentrated), ("분산", diversified)):
        r = run_survival(port, years=20, n_simulations=3000, monthly_target=0)
        print(f"\n[{label}]")
        print(f"  생존확률 {r['survival_probability']}% | 만기유지 {r['endpoint_probability']}% "
              f"| HHI {r['concentration_hhi']}")
        print(f"  기준 {r['threshold_monthly_만원']}만원 | P10최악 {r['p10_worst_monthly']} "
              f"| P50만기 {r['p50_final_real']}")
        print(f"  {r['summary']}")

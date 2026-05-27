"""
stress_test.py — 배당 포트폴리오 위기 시나리오 시뮬레이션

왜 필요한가?
  "현재 배당률"만 보면 좋아 보이는 포트폴리오도 금융위기 시
  배당 급감·주가 폭락으로 무너질 수 있다.
  이 모듈은 4개 역사적 위기 시나리오에서:
    1. 자산별 가격 충격
    2. 배당 감소 충격
    3. 회복 기간
    4. 포트폴리오 내성 점수
  를 계산해 "위기에서 살아남는 포트폴리오인가"를 판단한다.

사용 예:
    from utils.stress_test import run_stress_test
    result = run_stress_test(recommendations, investable_amount=5000)
"""

from __future__ import annotations
from typing import TYPE_CHECKING

# ── 시나리오 정의 ──────────────────────────────────────────────────
# 각 시나리오는 자산 클래스별 (가격 충격 %, 배당 충격 %) 을 정의한다.
# etf_category가 있는 경우 category 우선, 없으면 asset_class 기준.
#
# 왜 이 수치인가?
#   - 2008 위기: S&P500 -57%, 리츠 -68%, 배당 삭감 약 25% (S&P 500 DPS 기준)
#   - 2022 금리급등: TLT -46%, 리츠 -35%, 성장주 -40%
#   - COVID(2020): S&P500 -34% (단기), 리츠 -42%, 빠른 회복 6-9개월
#   - 경기침체: GDP -2% 기준, 기업이익 -15~25%, 배당 삭감 5~20%

SCENARIOS: dict[str, dict] = {

    "2008_financial_crisis": {
        "name":        "2008 금융위기",
        "name_short":  "GFC 2008",
        "icon":        "💥",
        "description": "리먼브라더스 파산·서브프라임 모기지 붕괴. S&P500 -57%, 리츠 -68%.",
        "duration_months": 17,   # 저점까지 걸린 기간
        "recovery_months": 49,   # 전고점 회복까지
        # 자산 클래스별 충격: (price_shock_pct, div_shock_pct)
        "shocks_by_class": {
            "kr_stock":    (-45, -35),
            "us_stock":    (-50, -30),
            "us_div_etf":  (-40, -25),
            "us_reit":     (-65, -50),
            "kr_reit":     (-55, -45),
            "kr_etf":      (-40, -28),
            "defensive":   (-5,   0),   # 채권 강세 (비행안전)
        },
        # etf_category별 세부 조정 (class 충격 위에 추가 적용)
        "shocks_by_category": {
            "monthly_income":   (-42, -30),  # 커버드콜 프리미엄 급감
            "high_yield":       (-48, -35),
            "cash_equivalent":  (  0,  +2),  # T-Bill 수요 급증 → 금리 급락 → yield ↓
            "long_bond":        ( +8,   0),  # 장기채 가격 상승 (금리 하락)
            "agg_bond":         ( +5,   0),
            "tips":             ( +2,   0),
            "reit":             (-65, -50),
        },
    },

    "2022_rate_shock": {
        "name":        "2022 금리 급등 충격",
        "name_short":  "Rate Shock",
        "icon":        "📈",
        "description": "Fed 기준금리 0%→5.5% 급등. TLT -46%, 리츠 -35%, 성장주 타격.",
        "duration_months": 12,
        "recovery_months": 24,
        "shocks_by_class": {
            "kr_stock":    (-25, -10),
            "us_stock":    (-20,  -5),
            "us_div_etf":  (-18,   0),
            "us_reit":     (-35, -15),
            "kr_reit":     (-30, -12),
            "kr_etf":      (-20,  -8),
            "defensive":   (-20,   0),  # 채권 가격 하락
        },
        "shocks_by_category": {
            "monthly_income":  (-20,   0),
            "high_yield":      (-22,  -5),
            "cash_equivalent": (  0,  +3),  # SGOV yield 상승 (금리 오르면 유리)
            "long_bond":       (-46,   0),  # TLT 직격탄
            "agg_bond":        (-15,   0),
            "tips":            ( -8,  +2),  # 인플레 헤지로 상대적 선방
            "reit":            (-35, -15),
            "dividend_growth": (-20,  +2),  # 우량 배당성장 기업은 배당 유지·성장
        },
    },

    "covid_crash": {
        "name":        "COVID-19 급락",
        "name_short":  "COVID 2020",
        "icon":        "🦠",
        "description": "코로나19 팬데믹. S&P500 -34% (33일), 리츠 -42%. 이후 V자 회복.",
        "duration_months": 2,
        "recovery_months": 6,
        "shocks_by_class": {
            "kr_stock":    (-38, -20),
            "us_stock":    (-34, -25),
            "us_div_etf":  (-30, -15),
            "us_reit":     (-42, -30),
            "kr_reit":     (-35, -25),
            "kr_etf":      (-30, -18),
            "defensive":   (+10,   0),  # 안전자산 수요
        },
        "shocks_by_category": {
            "monthly_income":  (-32, -20),
            "high_yield":      (-38, -28),
            "cash_equivalent": (  0,  -1),
            "long_bond":       (+12,   0),
            "agg_bond":        ( +8,   0),
            "tips":            ( +3,   0),
            "reit":            (-42, -30),
            "dividend_growth": (-28, -12),
        },
    },

    "recession": {
        "name":        "경기침체 시나리오",
        "name_short":  "Recession",
        "icon":        "📉",
        "description": "GDP -2%, 기업이익 -20% 가정. 완만한 하락, 긴 회복. 배당 삭감 기업 속출.",
        "duration_months": 18,
        "recovery_months": 30,
        "shocks_by_class": {
            "kr_stock":    (-32, -25),
            "us_stock":    (-28, -20),
            "us_div_etf":  (-22, -12),
            "us_reit":     (-30, -20),
            "kr_reit":     (-28, -18),
            "kr_etf":      (-25, -15),
            "defensive":   ( +3,   0),
        },
        "shocks_by_category": {
            "monthly_income":  (-28, -22),  # 커버드콜: 변동성 감소 시 프리미엄 ↓
            "high_yield":      (-35, -28),  # 고배당 삭감 위험 높음
            "cash_equivalent": (  0,  -2),  # 침체 → 금리 인하 → yield ↓
            "long_bond":       ( +8,   0),  # 경기침체 = 금리 인하 기대
            "agg_bond":        ( +5,   0),
            "tips":            (  0,   0),
            "reit":            (-30, -20),
            "dividend_growth": (-20,  -5),  # 배당성장 기업은 상대적 선방
        },
    },
}


# ── 핵심 시뮬레이션 함수 ──────────────────────────────────────────
def _get_shock(scenario: dict, asset_class: str, etf_category: str) -> tuple[float, float]:
    """
    자산의 (가격충격%, 배당충격%)를 반환.
    etf_category → asset_class 우선순위로 충격 결정.
    """
    cat_shocks = scenario.get("shocks_by_category", {})
    cls_shocks = scenario.get("shocks_by_class", {})

    if etf_category and etf_category in cat_shocks:
        return cat_shocks[etf_category]
    if asset_class in cls_shocks:
        return cls_shocks[asset_class]
    return (-20, -10)  # 기본 보수적 가정


def run_stress_test(
    recommendations: list[dict],
    investable_amount: float,           # 총 투자금 (만원)
    scenarios: list[str] | None = None, # None이면 전체 4개
) -> dict:
    """
    포트폴리오 위기 시나리오 시뮬레이션.

    Args:
        recommendations: assign_weights() 반환값 (weight_pct, dividend_yield, asset_class 등 포함)
        investable_amount: 총 투자금 (만원)
        scenarios: 시뮬레이션할 시나리오 key 목록 (None=전체)

    반환:
    {
        "baseline": {
            "portfolio_value_만원": float,
            "monthly_div_net_만원": float,
            "annual_div_net_만원": float,
        },
        "scenarios": {
            "2008_financial_crisis": {
                "name": str, "icon": str,
                "price_shock": {
                    "portfolio_value_만원": float,
                    "portfolio_loss_만원": float,
                    "portfolio_loss_pct": float,
                },
                "div_shock": {
                    "monthly_div_net_만원": float,     # 위기 직후
                    "monthly_div_change_만원": float,  # 감소분
                    "monthly_div_change_pct": float,
                },
                "recovery": {
                    "duration_months": int,   # 저점까지
                    "recovery_months": int,   # 전고점 회복까지
                },
                "asset_impact": [...],    # 자산별 충격
                "resilient_assets": [...],
                "vulnerable_assets": [...],
                "resilience_score": float,   # 0-100
                "key_message": str,
            },
            ...
        },
        "overall_resilience_score": float,
        "overall_grade":  str,
        "portfolio_type": str,   # "방어형" / "균형형" / "공격형"
        "recommendations": [...],  # 내성 강화 조언
    }
    """
    target_scenarios = scenarios or list(SCENARIOS.keys())

    # ── 기준선 (Baseline) 계산 ──────────────────────────────────
    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0
    baseline_monthly_net = sum(
        investable_amount * r.get("weight_pct", 0) / 100
        * r.get("net_yield_pct", r.get("dividend_yield", 0)) / 100
        / 12
        for r in recommendations
    )
    baseline_annual_net = baseline_monthly_net * 12

    result_scenarios = {}

    for sc_key in target_scenarios:
        sc = SCENARIOS.get(sc_key)
        if not sc:
            continue

        # ── 자산별 충격 계산 ──────────────────────────────────────
        asset_impacts = []
        portfolio_loss_total = 0.0
        div_loss_total = 0.0
        baseline_total = 0.0

        for rec in recommendations:
            cls      = rec.get("asset_class", "")
            cat      = rec.get("etf_category", "")
            weight   = rec.get("weight_pct", 0) / 100
            invest   = investable_amount * weight
            net_y    = rec.get("net_yield_pct", rec.get("dividend_yield", 0)) / 100

            price_shock_pct, div_shock_pct = _get_shock(sc, cls, cat)

            # 가격 충격
            price_change = invest * price_shock_pct / 100
            # 배당 충격: 배당 감소 후 월배당
            base_monthly   = invest * net_y / 12
            shock_monthly  = base_monthly * (1 + div_shock_pct / 100)
            div_change     = shock_monthly - base_monthly

            asset_impacts.append({
                "ticker":            rec.get("ticker", ""),
                "name":              rec.get("name", ""),
                "asset_class":       cls,
                "etf_category":      cat,
                "weight_pct":        round(rec.get("weight_pct", 0), 1),
                "invest_만원":        round(invest, 0),
                "price_shock_pct":   price_shock_pct,
                "div_shock_pct":     div_shock_pct,
                "price_loss_만원":   round(price_change, 1),
                "base_monthly_만원": round(base_monthly, 2),
                "shock_monthly_만원":round(shock_monthly, 2),
                "div_change_만원":   round(div_change, 2),
            })

            portfolio_loss_total += price_change
            div_loss_total       += div_change
            baseline_total       += invest

        # ── 포트폴리오 레벨 집계 ─────────────────────────────────
        shock_value     = investable_amount + portfolio_loss_total
        shock_monthly   = baseline_monthly_net + div_loss_total
        portfolio_loss_pct = round(portfolio_loss_total / investable_amount * 100, 1)
        div_change_pct     = round(div_loss_total / baseline_monthly_net * 100, 1) if baseline_monthly_net > 0 else 0

        # ── 자산별 정렬 ──────────────────────────────────────────
        sorted_by_div = sorted(asset_impacts, key=lambda x: x["div_shock_pct"], reverse=True)
        resilient  = [a for a in sorted_by_div if a["div_shock_pct"] >= 0][:3]
        vulnerable = sorted(asset_impacts, key=lambda x: x["div_shock_pct"])[:3]

        # ── 내성 점수 (0~100) ────────────────────────────────────
        # 배당 감소율이 낮을수록, 가격 충격이 낮을수록 높은 점수
        div_resilience   = max(0, min(100, 100 + div_change_pct))   # div_change_pct는 음수
        price_resilience = max(0, min(100, 100 + portfolio_loss_pct))
        resilience_score = round(div_resilience * 0.6 + price_resilience * 0.4, 1)

        # ── 핵심 메시지 ───────────────────────────────────────────
        if div_change_pct >= -5:
            key_msg = f"💪 배당 감소 {abs(div_change_pct):.0f}% — 거의 영향 없음. 탁월한 내성."
        elif div_change_pct >= -15:
            key_msg = f"🟡 배당 {abs(div_change_pct):.0f}% 감소 — 감내 가능 수준. 방어 자산 역할 충분."
        elif div_change_pct >= -30:
            key_msg = f"🟠 배당 {abs(div_change_pct):.0f}% 감소 — 상당한 영향. 방어형 비중 점검 필요."
        else:
            key_msg = f"🔴 배당 {abs(div_change_pct):.0f}% 급감 — 심각한 충격. 포트폴리오 재구성 고려."

        result_scenarios[sc_key] = {
            "name":              sc["name"],
            "name_short":        sc["name_short"],
            "icon":              sc["icon"],
            "description":       sc["description"],
            "price_shock": {
                "portfolio_value_만원":  round(shock_value, 0),
                "portfolio_loss_만원":   round(portfolio_loss_total, 0),
                "portfolio_loss_pct":    portfolio_loss_pct,
            },
            "div_shock": {
                "baseline_monthly_만원":     round(baseline_monthly_net, 2),
                "shock_monthly_만원":        round(shock_monthly, 2),
                "monthly_div_change_만원":   round(div_loss_total, 2),
                "monthly_div_change_pct":    div_change_pct,
            },
            "recovery": {
                "duration_months":   sc["duration_months"],
                "recovery_months":   sc["recovery_months"],
            },
            "asset_impact":      asset_impacts,
            "resilient_assets":  resilient,
            "vulnerable_assets": vulnerable,
            "resilience_score":  resilience_score,
            "key_message":       key_msg,
        }

    # ── 종합 내성 점수 ───────────────────────────────────────────
    scores = [v["resilience_score"] for v in result_scenarios.values()]
    overall_score = round(sum(scores) / len(scores), 1) if scores else 0

    if overall_score >= 80:
        overall_grade = "🛡️ 매우 강함"
        port_type = "방어형"
    elif overall_score >= 65:
        overall_grade = "✅ 양호"
        port_type = "균형형"
    elif overall_score >= 50:
        overall_grade = "⚠️ 보통"
        port_type = "중립형"
    else:
        overall_grade = "🚨 취약"
        port_type = "공격형"

    # ── 개선 조언 ────────────────────────────────────────────────
    recs_out = _generate_stress_recommendations(recommendations, result_scenarios)

    return {
        "baseline": {
            "portfolio_value_만원":  round(investable_amount, 0),
            "monthly_div_net_만원":  round(baseline_monthly_net, 2),
            "annual_div_net_만원":   round(baseline_annual_net, 2),
        },
        "scenarios":                 result_scenarios,
        "overall_resilience_score":  overall_score,
        "overall_grade":             overall_grade,
        "portfolio_type":            port_type,
        "recommendations":           recs_out,
    }


def _generate_stress_recommendations(
    recommendations: list[dict],
    scenario_results: dict,
) -> list[str]:
    """포트폴리오 내성 강화 조언 생성."""
    tips = []
    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0

    # 방어형 비중
    defensive_w = sum(r.get("weight_pct", 0) for r in recommendations
                      if r.get("asset_class") == "defensive") / total_w
    cash_equiv_w = sum(r.get("weight_pct", 0) for r in recommendations
                       if r.get("etf_category") == "cash_equivalent") / total_w
    reit_w = sum(r.get("weight_pct", 0) for r in recommendations
                 if "reit" in r.get("asset_class", "")) / total_w
    high_yield_w = sum(r.get("weight_pct", 0) for r in recommendations
                       if r.get("etf_category") in ("high_yield", "monthly_income")) / total_w

    # 2008 내성
    sc_2008 = scenario_results.get("2008_financial_crisis", {})
    if sc_2008.get("resilience_score", 100) < 60:
        tips.append(
            f"💡 SGOV 비중을 {max(0, int((0.15 - cash_equiv_w)*100))}%p 늘리면 "
            f"2008급 위기에서 배당 감소를 완충할 수 있습니다."
        )

    # 금리 충격 내성
    sc_rate = scenario_results.get("2022_rate_shock", {})
    if sc_rate.get("resilience_score", 100) < 65 and defensive_w < 0.15:
        tips.append(
            "💡 장기채(TLT) 비중이 높을수록 금리 급등 시 취약합니다. "
            "SCHP(물가연동채)·SGOV로 채권 포지션 분산을 고려하세요."
        )

    # 리츠 과다
    if reit_w > 0.25:
        tips.append(
            f"💡 리츠 비중 {reit_w*100:.0f}%는 2008·2022 두 위기 모두 취약 구간입니다. "
            "20% 이하로 줄이고 dividend_growth ETF(SCHD·VIG)로 대체를 검토하세요."
        )

    # 고배당 커버드콜 과다
    if high_yield_w > 0.30:
        tips.append(
            f"💡 커버드콜·고배당 ETF 비중 {high_yield_w*100:.0f}%는 "
            "경기침체 시 배당 급감 위험이 있습니다. "
            "SCHD(배당성장)와 혼합하면 장기 복원력이 높아집니다."
        )

    # 충분히 방어적
    if not tips:
        best_score = max(v.get("resilience_score", 0) for v in scenario_results.values()) if scenario_results else 0
        tips.append(
            f"✅ 현재 포트폴리오는 전반적으로 위기 내성이 양호합니다 (최고 점수 {best_score}점). "
            "정기 리밸런싱으로 비중 유지를 권장합니다."
        )

    return tips[:4]


# ── FX 스트레스 테스트 ─────────────────────────────────────────────
def run_fx_stress_test(
    recommendations: list[dict],
    investable_amount: float,
    base_usd_krw: float = 1380.0,
) -> dict:
    """
    USD/KRW 환율 변동이 원화 기준 월배당에 미치는 영향.

    시나리오:
      - 원화 강세 (-10%): 1380 → 1242
      - 현재 (기준): 1380
      - 원화 약세 (+10%): 1380 → 1518
      - 원화 약세 (+20%): 1380 → 1656 (위기 시나리오)

    반환: {
        "base_usd_krw": 1380,
        "scenarios": [
            {"label": "원화 강세 -10%", "usd_krw": 1242, ...},
            ...
        ],
        "us_asset_weight_pct": float,
        "fx_sensitivity_score": float,  # 0(민감)~100(둔감)
    }
    """
    fx_scenarios = [
        {"label": "원화 강세 -20%", "usd_krw": round(base_usd_krw * 0.80, 0), "change_pct": -20},
        {"label": "원화 강세 -10%", "usd_krw": round(base_usd_krw * 0.90, 0), "change_pct": -10},
        {"label": "현재 (기준)",     "usd_krw": base_usd_krw,                  "change_pct":   0},
        {"label": "원화 약세 +10%", "usd_krw": round(base_usd_krw * 1.10, 0), "change_pct": +10},
        {"label": "원화 약세 +20%", "usd_krw": round(base_usd_krw * 1.20, 0), "change_pct": +20},
    ]

    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0
    us_assets = [r for r in recommendations if r.get("currency", "USD") == "USD"
                 or r.get("asset_class", "") in ("us_stock", "us_div_etf", "us_reit", "defensive")]
    kr_assets = [r for r in recommendations if r not in us_assets]

    us_weight = sum(r.get("weight_pct", 0) for r in us_assets) / total_w

    # 기준선 원화 월배당
    base_monthly_net = sum(
        investable_amount * r.get("weight_pct", 0) / 100
        * r.get("net_yield_pct", r.get("dividend_yield", 0)) / 100 / 12
        for r in recommendations
    )

    results = []
    for sc in fx_scenarios:
        change_ratio = sc["change_pct"] / 100

        # US 자산 배당: 달러 금액 고정, 환율 변동으로 원화 금액 변동
        us_monthly = sum(
            investable_amount * r.get("weight_pct", 0) / 100
            * r.get("net_yield_pct", r.get("dividend_yield", 0)) / 100 / 12
            for r in us_assets
        )
        kr_monthly = base_monthly_net - us_monthly

        # 환율 변화 반영: 원화 약세 → 원화 기준 US 배당 증가
        adjusted_us_monthly = us_monthly * (1 + change_ratio)
        total_monthly = kr_monthly + adjusted_us_monthly

        results.append({
            **sc,
            "monthly_div_net_만원":  round(total_monthly, 2),
            "monthly_div_change_만원": round(total_monthly - base_monthly_net, 2),
            "monthly_div_change_pct":  round((total_monthly - base_monthly_net) / base_monthly_net * 100, 1)
                                       if base_monthly_net else 0,
            "is_base": sc["change_pct"] == 0,
        })

    # FX 민감도 점수 (0=민감, 100=둔감)
    # US 비중이 낮을수록 환율 영향 적음
    fx_sensitivity_score = round(100 - us_weight * 100, 1)

    # 원화 강세 -20% 시 배당 감소 비율
    worst_case = results[0]["monthly_div_change_pct"]

    if worst_case >= -5:
        fx_grade = "✅ 환율 안정형"
        fx_msg = f"원화 20% 강세 시 배당 {abs(worst_case):.0f}%만 감소 — 환율 영향 낮음."
    elif worst_case >= -12:
        fx_grade = "🟡 환율 보통 노출"
        fx_msg = f"원화 강세 시 배당 최대 {abs(worst_case):.0f}% 감소 — 환헤지 ETF 일부 편입 고려."
    else:
        fx_grade = "🔴 환율 고노출"
        fx_msg = f"원화 강세 시 배당 최대 {abs(worst_case):.0f}% 감소 — 환헤지 ETF(456680 등) 비중 확대 필요."

    return {
        "base_usd_krw":          base_usd_krw,
        "us_asset_weight_pct":   round(us_weight * 100, 1),
        "kr_asset_weight_pct":   round((1 - us_weight) * 100, 1),
        "baseline_monthly_만원": round(base_monthly_net, 2),
        "scenarios":             results,
        "fx_sensitivity_score":  fx_sensitivity_score,
        "fx_grade":              fx_grade,
        "fx_message":            fx_msg,
    }

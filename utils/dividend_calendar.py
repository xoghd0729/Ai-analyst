"""
dividend_calendar.py — 월별 배당 현금흐름 캘린더

왜 필요한가?
  투자자는 "연간 배당 200만원"보다 "3월에 SCHD, 매월 SGOV" 같은
  실제 입금 스케줄을 원한다.
  이 모듈은 포트폴리오의 월별 예상 배당을 달력 형태로 보여준다.

  핵심 데이터: asset_metadata.json의 pay_months 필드
  ex) SCHD: [3,6,9,12] → 3·6·9·12월에 분기 배당 지급
"""

from __future__ import annotations

MONTH_NAMES = ["1월","2월","3월","4월","5월","6월",
               "7월","8월","9월","10월","11월","12월"]


def build_dividend_calendar(
    recommendations: list[dict],
    investable_amount: float,
) -> dict:
    """
    월별 배당 캘린더 생성.

    Args:
        recommendations: assign_weights() 반환값
        investable_amount: 총 투자금 (만원)

    반환:
    {
        "monthly": {
            "1": {"div_net_만원": 5.2, "assets": [{"ticker","name","div_만원"}]},
            ...
            "12": {...}
        },
        "monthly_totals": [5.2, 3.1, ...],   # 1~12월 순서
        "smoothness_score": 82,               # 월배당 균등도 (0~100)
        "dry_months": [2, 5],                 # 배당 없는 달
        "peak_month": 3,                      # 가장 많이 들어오는 달
        "peak_amount_만원": 12.5,
        "coverage_months": 10,                # 배당 있는 달 수
        "annual_total_net_만원": 142.3,
        "avg_monthly_net_만원":  11.9,
        "tip": str,                           # 캘린더 개선 팁
    }
    """
    import json, os
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    meta_path = os.path.join(BASE_DIR, "data", "asset_metadata.json")
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except Exception:
        meta = {}

    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0

    # 월별 집계 구조 초기화
    monthly: dict[str, dict] = {str(m): {"div_net_만원": 0.0, "assets": []} for m in range(1, 13)}

    for rec in recommendations:
        ticker  = rec.get("ticker", "")
        name    = rec.get("name", ticker)
        cls     = rec.get("asset_class", "")
        weight  = rec.get("weight_pct", 0) / 100
        invest  = investable_amount * weight
        # invest_amount_만원 직접 제공 시 우선 사용
        if "invest_amount_만원" in rec:
            invest = rec["invest_amount_만원"]

        # 수익률: net_yield_pct → dividend_yield → gross_yield_pct(세금 15% 차감) → 0
        raw_y = (
            rec.get("net_yield_pct")
            or rec.get("dividend_yield")
            or rec.get("gross_yield_pct")
            or 0
        )
        # gross_yield_pct는 세전 → 세후 근사 (배당세 15%)
        if rec.get("net_yield_pct") is None and rec.get("dividend_yield") is None:
            net_y = float(raw_y) * 0.85 / 100
        else:
            net_y = float(raw_y) / 100

        # pay_months 조회: asset_metadata 우선 → rec 자체 → asset_class 기본값
        pay_months = _get_pay_months(ticker, cls, rec, meta)
        if not pay_months:
            continue

        # 연간 세후 배당을 pay_months 균등 분할
        annual_net  = invest * net_y
        per_payment = annual_net / len(pay_months)   # 회당 지급액

        for m in pay_months:
            key = str(m)
            monthly[key]["div_net_만원"] = round(
                monthly[key]["div_net_만원"] + per_payment, 2
            )
            monthly[key]["assets"].append({
                "ticker":     ticker,
                "name":       name,
                "div_만원":   round(per_payment, 2),
                "pay_type":   "monthly" if len(pay_months) == 12 else "quarterly",
            })

    # 월별 자산 목록 정렬 (배당 큰 순)
    for key in monthly:
        monthly[key]["assets"].sort(key=lambda x: -x["div_만원"])
        monthly[key]["div_net_만원"] = round(monthly[key]["div_net_만원"], 2)

    # 집계 통계
    monthly_totals = [monthly[str(m)]["div_net_만원"] for m in range(1, 13)]
    annual_total   = round(sum(monthly_totals), 2)
    avg_monthly    = round(annual_total / 12, 2)
    dry_months     = [m for m in range(1, 13) if monthly_totals[m-1] < 0.01]
    coverage_months = 12 - len(dry_months)

    peak_m   = monthly_totals.index(max(monthly_totals)) + 1
    peak_amt = round(max(monthly_totals), 2)

    # 균등도 점수: 표준편차가 낮을수록 높은 점수
    if avg_monthly > 0:
        import math
        variance = sum((v - avg_monthly) ** 2 for v in monthly_totals) / 12
        std_dev  = math.sqrt(variance)
        cv       = std_dev / avg_monthly   # 변동계수
        smoothness = round(max(0, min(100, (1 - cv) * 100)), 1)
    else:
        smoothness = 0.0

    # 개선 팁
    tip = _generate_calendar_tip(dry_months, smoothness, coverage_months)

    return {
        "monthly":              monthly,
        "monthly_totals":       monthly_totals,
        "smoothness_score":     smoothness,
        "dry_months":           dry_months,
        "dry_month_names":      [MONTH_NAMES[m-1] for m in dry_months],
        "peak_month":           peak_m,
        "peak_month_name":      MONTH_NAMES[peak_m - 1],
        "peak_amount_만원":     peak_amt,
        "coverage_months":      coverage_months,
        "annual_total_net_만원": annual_total,
        "avg_monthly_net_만원":  avg_monthly,
        "tip":                  tip,
    }


def _get_pay_months(
    ticker: str,
    asset_class: str,
    rec: dict,
    meta: dict,
) -> list[int]:
    """pay_months 조회 우선순위: asset_metadata → rec 직접 → 자산군 기본값"""
    # 1. asset_metadata 조회
    for sec_key in ("us_div_etf", "kr_etf", "us_reit", "kr_reit", "defensive", "us_stock"):
        section = meta.get(sec_key, {})
        if isinstance(section, dict) and ticker in section:
            asset = section[ticker]
            if isinstance(asset, dict) and "pay_months" in asset:
                return asset["pay_months"]

    # 2. rec 자체에 pay_months 필드
    if "pay_months" in rec:
        return rec["pay_months"]

    # 3. asset_class 기반 기본값
    defaults = {
        "kr_stock":   [4],           # 한국 주식: 4월 연 1회
        "us_stock":   [3, 6, 9, 12], # 미국 주식: 분기
        "us_div_etf": [3, 6, 9, 12], # 미국 ETF: 분기 (기본)
        "kr_etf":     [1, 4, 7, 10], # 한국 ETF: 분기
        "us_reit":    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],  # 리츠: 월배당
        "kr_reit":    [3, 6, 9, 12], # 한국 리츠: 분기
        "defensive":  [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],  # 채권: 월배당
    }
    return defaults.get(asset_class, [3, 6, 9, 12])


def _generate_calendar_tip(
    dry_months: list[int],
    smoothness: float,
    coverage_months: int,
) -> str:
    """배당 캘린더 개선 팁 생성."""
    if not dry_months:
        return "✅ 12개월 모두 배당 지급 — 완전한 월급형 포트폴리오입니다."

    if len(dry_months) <= 2:
        names = [MONTH_NAMES[m-1] for m in dry_months]
        return (
            f"💡 {', '.join(names)} 배당 공백. "
            "SGOV(매월 지급) 또는 O(리얼티인컴, 매월)를 추가하면 공백을 메울 수 있습니다."
        )
    if smoothness < 50:
        return (
            "💡 배당이 특정 달에 집중됩니다. "
            "월배당 ETF(JEPI·SGOV·448290)를 추가하면 매월 균등 현금흐름이 가능합니다."
        )
    return (
        f"💡 {coverage_months}개월 배당 커버. "
        "월배당 자산(SGOV·JEPI·448290) 비중을 높이면 매달 입금 가능합니다."
    )

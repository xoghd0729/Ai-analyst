"""
Yield Trap Detector
───────────────────
철학: "높은 배당률만으로는 안전하지 않다. 주가 유지와 현금흐름 지속성이 함께 가야 한다."
"""
from __future__ import annotations

from typing import Any


_ALTERNATIVE_MAP: dict[str, list[str]] = {
    "QYLD": ["SCHD", "VYM"],
    "JEPI": ["SCHD", "DGRO"],
    "JEPQ": ["SCHD", "NOBL"],
    "MO": ["KO", "PG"],
    "T": ["VZ", "SCHD"],
    "PFE": ["JNJ", "ABBV"],
}

_DEFAULT_ALTERNATIVES = ["SCHD", "VYM"]


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _pick_alternatives(ticker: str, recommendations: list[dict]) -> list[str]:
    mapped = _ALTERNATIVE_MAP.get(ticker, _DEFAULT_ALTERNATIVES)
    rec_tickers = {str(r.get("ticker", "")) for r in recommendations}
    # 포트폴리오 내 종목을 우선 대안으로 제시, 없으면 매핑값 유지
    preferred = [t for t in mapped if t in rec_tickers and t != ticker]
    if preferred:
        return preferred[:2]
    return mapped[:2]


def detect_yield_traps(recommendations: list[dict]) -> list[dict]:
    """
    Yield Trap 후보 탐지.

    조건 (하나라도 만족 시 trap):
      (a) 배당수익률 >= 8% AND 최근 3년 주가 CAGR <= -5%
      (b) ML 모델 BROKEN
      (c) dividend_coverage < 0.8
    """
    traps: list[dict] = []

    for rec in recommendations or []:
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", ticker))
        reasons: list[str] = []
        severity = "medium"

        dividend_yield = _to_float(rec.get("dividend_yield", rec.get("expected_yield")))
        price_cagr_3y = _to_float(
            rec.get("price_cagr_3y", rec.get("capital_gain_rate", 0.0))
        )
        ml_status = str(rec.get("ml_status", "")).upper()
        dividend_coverage = _to_float(
            rec.get("dividend_coverage", rec.get("coverage_ratio", 1.0)), default=1.0
        )

        if dividend_yield >= 8.0 and price_cagr_3y <= -5.0:
            reasons.append("고배당(8%+)이지만 최근 3년 주가 CAGR이 -5% 이하")
            severity = "high"

        if ml_status == "BROKEN":
            reasons.append("ML 모델이 BROKEN으로 분류")
            severity = "high"

        if dividend_coverage < 0.8:
            reasons.append("배당커버리지 0.8 미만으로 배당 지속성 취약")
            severity = "high" if dividend_coverage < 0.6 else severity

        if not reasons:
            continue

        traps.append(
            {
                "ticker": ticker,
                "name": name,
                "reason": " / ".join(reasons),
                "severity": severity,
                "alternative_tickers": _pick_alternatives(ticker, recommendations),
            }
        )

    return traps

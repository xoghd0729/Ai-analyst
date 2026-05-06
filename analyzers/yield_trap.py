"""
Yield Trap 감지 룰 엔진.
LLM이 숫자를 해석하면 틀리기 때문에, 이 모듈은 100% 룰 기반으로 동작한다.

감지 로직:
  DANGER  → thesis 붕괴 수준 (배당 삭감 거의 확실)
  WARNING → thesis 약화 수준 (리스크 관찰 필요)
  SAFE    → 배당 지속성 양호

출력 형식:
  {
    "level": "DANGER" | "WARNING" | "SAFE",
    "signals": [{"code": str, "description": str, "severity": str}],
    "summary": str
  }
"""

from __future__ import annotations
from typing import TypedDict


class Signal(TypedDict):
    code: str
    description: str
    severity: str   # "DANGER" | "WARNING"


class YieldTrapResult(TypedDict):
    level: str
    signals: list[Signal]
    summary: str


def analyze(metrics: dict) -> YieldTrapResult:
    """
    metrics: metric_snapshots에서 조회한 지표 딕셔너리
    필수 키: dividend_yield, payout_ratio, dividend_coverage,
             free_cash_flow, earnings_growth, net_income, dividends_paid
    """
    signals: list[Signal] = []

    dy        = metrics.get("dividend_yield",      0.0)
    payout    = metrics.get("payout_ratio",        0.0)
    coverage  = metrics.get("dividend_coverage",  None)
    fcf       = metrics.get("free_cash_flow",     None)
    eg        = metrics.get("earnings_growth",    None)
    net_inc   = metrics.get("net_income",         None)
    div_paid  = metrics.get("dividends_paid",     None)

    # ── DANGER 신호 (배당 삭감 임박) ───────────────────────────────────────────

    # 1. FCF < 배당지급 → 빌려서 배당하는 구조
    if fcf is not None and div_paid is not None and abs(div_paid) > 0:
        if fcf < abs(div_paid):
            signals.append({
                "code": "FCF_BELOW_DIVIDEND",
                "description": f"잉여현금흐름({fcf/1e12:.2f}조)이 배당지급액({abs(div_paid)/1e12:.2f}조)보다 적음 — 외부 자금 또는 현금 소진으로 배당 지급 중",
                "severity": "DANGER"
            })

    # 2. 배당성향 > 100% → 순이익을 초과하는 배당
    if payout > 100:
        signals.append({
            "code": "PAYOUT_OVER_100",
            "description": f"배당성향 {payout:.1f}% — 당기순이익을 초과하는 배당 지급. 지속 불가능.",
            "severity": "DANGER"
        })

    # 3. 고배당 + 순이익 마이너스
    if dy > 3.0 and net_inc is not None and net_inc < 0:
        signals.append({
            "code": "HIGH_YIELD_NEGATIVE_EARNINGS",
            "description": f"배당수익률 {dy:.2f}%이지만 당기순이익 적자 — 전형적 Yield Trap",
            "severity": "DANGER"
        })

    # 4. 배당커버리지 < 1.0 → FCF로 배당 못 감당
    if coverage is not None and coverage < 1.0:
        signals.append({
            "code": "LOW_COVERAGE",
            "description": f"배당커버리지 {coverage:.2f}배 — FCF가 배당 지급액에 미달. 삭감 리스크 높음.",
            "severity": "DANGER"
        })

    # ── WARNING 신호 (관찰 필요) ───────────────────────────────────────────────

    # 5. 배당성향 80~100% + 순이익 감소
    if 80 <= payout <= 100 and eg is not None and eg < 0:
        signals.append({
            "code": "HIGH_PAYOUT_DECLINING_EARNINGS",
            "description": f"배당성향 {payout:.1f}% + 순이익 {eg:+.1f}% 감소 — 배당 여력 악화 중",
            "severity": "WARNING"
        })

    # 6. 배당성향 80~100% (단독)
    elif 80 <= payout <= 100:
        signals.append({
            "code": "HIGH_PAYOUT",
            "description": f"배당성향 {payout:.1f}% — 이익의 대부분을 배당으로 지급. 성장 투자 여력 제한.",
            "severity": "WARNING"
        })

    # 7. 배당커버리지 1.0~1.5 (아슬아슬)
    if coverage is not None and 1.0 <= coverage < 1.5:
        signals.append({
            "code": "THIN_COVERAGE",
            "description": f"배당커버리지 {coverage:.2f}배 — 안전 기준(1.5배) 미달. 실적 소폭 악화 시 배당 삭감 가능.",
            "severity": "WARNING"
        })

    # 8. 고배당 + 실적 감소 (고전적 Yield Trap)
    if dy > 5.0 and eg is not None and eg < -10:
        signals.append({
            "code": "YIELD_TRAP_CLASSIC",
            "description": f"배당수익률 {dy:.2f}% + 순이익 {eg:+.1f}% 급감 — 고배당이 주가 하락의 결과일 가능성 높음",
            "severity": "WARNING"
        })

    # ── 최종 판정 ──────────────────────────────────────────────────────────────

    danger_count  = sum(1 for s in signals if s["severity"] == "DANGER")
    warning_count = sum(1 for s in signals if s["severity"] == "WARNING")

    if danger_count >= 1:
        level = "DANGER"
        summary = f"⛔ DANGER: {danger_count}개의 배당 붕괴 신호 감지. 배당 삭감 또는 중단 가능성 높음."
    elif warning_count >= 2:
        level = "WARNING"
        summary = f"⚠️  WARNING: {warning_count}개의 리스크 신호. 배당 지속성 약화 중 — 모니터링 강화 필요."
    elif warning_count == 1:
        level = "CAUTION"
        summary = f"🟡 CAUTION: {warning_count}개의 경미한 리스크. 현재 배당 유지 가능하나 관찰 필요."
    else:
        level = "SAFE"
        summary = "✅ SAFE: 현재 배당 지속성 양호. 주요 위험 신호 없음."

    return {
        "level": level,
        "signals": signals,
        "summary": summary
    }


def get_metrics_from_db(stock_code: str) -> dict:
    """DB에서 배당 분석용 지표 일괄 조회"""
    from sqlalchemy import create_engine, text
    engine = create_engine("postgresql://localhost/ai_analyst")

    needed = [
        "dividend_yield", "payout_ratio", "dividend_coverage",
        "free_cash_flow", "earnings_growth", "net_income", "dividends_paid",
        "revenue", "op_income", "dividend_per_share"
    ]

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT metric_name, value FROM metric_snapshots
            WHERE stock_code = :code
              AND metric_name = ANY(:metrics)
            ORDER BY date DESC
        """), {"code": stock_code, "metrics": needed}).fetchall()

    result, seen = {}, set()
    for metric, value in rows:
        if metric not in seen:
            result[metric] = float(value)
            seen.add(metric)
    return result

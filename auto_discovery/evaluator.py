"""
종목 평가 엔진

■ 역할
  screener_kr / screener_us 에서 받은 후보 종목을
  다음 기준으로 100점 만점 채점하여 통과/탈락 결정.

■ 평가 기준 (철학: "은행보다 높은 실질 수익률 + 위험 관리")
  ┌──────────────────────────────────┬──────┐
  │ 항목                             │ 배점 │
  ├──────────────────────────────────┼──────┤
  │ Total Return (배당+자본차익)      │  35점 │
  │ 배당 지속성 (연속 배당 연도)      │  25점 │
  │ Yield Trap 안전도                │  20점 │
  │ 은행 금리 초과 여부              │  20점 │
  └──────────────────────────────────┴──────┘

  합계 >= PASS_SCORE → approved_universe.json 편입
"""

from __future__ import annotations

# ── 기준값 ────────────────────────────────────────────────────
PASS_SCORE      = 60     # 100점 만점 중 통과 기준
BANK_RATE       = 3.5    # 현재 기준금리 (%)
MAX_YIELD_TRAP  = 85.0   # 배당성향(payout ratio) 최대 허용 (%)
MIN_TOTAL_RETURN = 5.0   # 최소 Total Return (%)


def score_candidate(candidate: dict) -> dict:
    """
    후보 종목 하나를 평가하여 점수 + 합격 여부 반환.

    Parameters
    ----------
    candidate : screener_kr 또는 screener_us 에서 반환된 dict

    Returns
    -------
    dict : {score, pass, reason, ...candidate 필드}
    """
    score   = 0
    reasons = []

    dy   = float(candidate.get("expected_yield") or 0)
    cg   = float(candidate.get("capital_gain_rate") or 0)
    tr   = dy + cg
    pout = float(candidate.get("payout_ratio") or 0)
    cons = int(candidate.get("consecutive_div_years") or 1)

    # ── 1. Total Return 점수 (35점) ──────────────────────────
    if tr >= 12:
        score += 35; reasons.append(f"TR {tr:.1f}% (최상위)")
    elif tr >= 9:
        score += 28; reasons.append(f"TR {tr:.1f}% (우수)")
    elif tr >= 7:
        score += 20; reasons.append(f"TR {tr:.1f}% (양호)")
    elif tr >= 5:
        score += 12; reasons.append(f"TR {tr:.1f}% (보통)")
    else:
        score += 0;  reasons.append(f"TR {tr:.1f}% (미달)")

    # ── 2. 배당 지속성 (25점) ────────────────────────────────
    if cons >= 10:
        score += 25; reasons.append(f"{cons}년 연속 배당")
    elif cons >= 5:
        score += 18; reasons.append(f"{cons}년 연속 배당")
    elif cons >= 3:
        score += 10; reasons.append(f"{cons}년 연속 배당")
    else:
        score += 5;  reasons.append(f"{cons}년 배당")

    # ── 3. Yield Trap 안전도 (20점) ──────────────────────────
    # payout_ratio가 없으면 배당수익률로 간접 판단
    if pout == 0:
        # 10% 넘는 배당수익률은 Yield Trap 의심
        if dy >= 10:
            score += 5;  reasons.append("고배당 — Yield Trap 주의")
        elif dy >= 7:
            score += 12; reasons.append("배당수익률 적정")
        else:
            score += 20; reasons.append("배당수익률 안정적")
    else:
        if pout <= 50:
            score += 20; reasons.append(f"배당성향 {pout:.0f}% (건전)")
        elif pout <= 70:
            score += 14; reasons.append(f"배당성향 {pout:.0f}% (양호)")
        elif pout <= MAX_YIELD_TRAP:
            score += 6;  reasons.append(f"배당성향 {pout:.0f}% (주의)")
        else:
            score += 0;  reasons.append(f"배당성향 {pout:.0f}% (위험 — 탈락 요인)")

    # ── 4. 은행 금리 초과 (20점) ─────────────────────────────
    excess = tr - BANK_RATE
    if excess >= 7:
        score += 20; reasons.append(f"은행 대비 +{excess:.1f}%p (압도적)")
    elif excess >= 4:
        score += 15; reasons.append(f"은행 대비 +{excess:.1f}%p (우수)")
    elif excess >= 2:
        score += 10; reasons.append(f"은행 대비 +{excess:.1f}%p (양호)")
    elif excess >= 0:
        score += 5;  reasons.append(f"은행 대비 +{excess:.1f}%p (간신히 초과)")
    else:
        score += 0;  reasons.append(f"은행 금리 미달 (은행예금보다 불리)")

    # ── 최종 판정 ────────────────────────────────────────────
    passed = (
        score >= PASS_SCORE
        and tr >= MIN_TOTAL_RETURN
        and (pout == 0 or pout <= MAX_YIELD_TRAP)
    )

    result = dict(candidate)
    result.update({
        "eval_score":        score,
        "eval_pass":         passed,
        "total_return_est":  round(tr, 2),
        "vs_bank_pct":       round(excess, 2),
        "eval_reason":       " · ".join(reasons),
    })
    return result


def evaluate_all(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    전체 후보 평가.

    Returns
    -------
    approved : 합격 종목 리스트
    rejected : 탈락 종목 리스트
    """
    approved, rejected = [], []
    for c in candidates:
        result = score_candidate(c)
        if result["eval_pass"]:
            approved.append(result)
        else:
            rejected.append(result)

    # 점수 내림차순 정렬
    approved = sorted(approved, key=lambda x: -x["eval_score"])
    rejected = sorted(rejected, key=lambda x: -x["eval_score"])

    return approved, rejected

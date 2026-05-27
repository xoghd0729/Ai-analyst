"""
utils/behavioral_finance.py — 투자자 행동 편향 진단 엔진
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  행동경제학 연구에 따르면 개인 투자자의 초과손실 중 60% 이상이
  인지 편향에서 비롯된다 (Barber & Odean, 2000).
  AI 서비스는 이 편향을 포트폴리오 구조에서 자동으로 탐지하고,
  투자자가 인식하지 못하는 "마음의 함정"을 짚어줄 수 있다.

탐지 편향 목록:
  1. 홈 바이어스 (Home Bias)         — 국내 자산 과다 비중
  2. 집중 편향 (Concentration Bias)  — 단일 종목/섹터 쏠림
  3. 최신성 편향 (Recency Bias)       — 최근 고수익 자산 추격
  4. 배당 앵커링 (Dividend Anchoring) — 배당 컷 신호에도 보유 집착
  5. 손실 회피 (Loss Aversion)        — BROKEN 종목 미교체
  6. 수익률 환상 (Yield Illusion)     — 세전 고수익 착시
  7. 과도한 안전 추구 (Excessive Safety Seeking) — 방어 자산 과잉
  8. 분산 부족 (Under-diversification) — 자산군 편중

반환:
{
    "biases": [
        {
            "id":          str,    # 편향 식별자
            "name":        str,    # 편향 이름 (한국어)
            "severity":    str,    # "high" / "medium" / "low"
            "severity_label": str, # "🔴 심각" / "🟡 주의" / "🟢 경미"
            "detected":    bool,
            "score":       float,  # 편향 강도 (0~100)
            "evidence":    str,    # 포트폴리오에서 발견된 근거
            "nudge":       str,    # 탈편향 넛지 메시지
            "debiasing_action": str, # 구체적 행동 권고
        },
        ...
    ],
    "bias_count":       int,    # 탐지된 편향 수
    "high_severity":    int,    # 심각 편향 수
    "overall_bias_score": int,  # 전체 편향 점수 (0~100, 높을수록 편향 강함)
    "investor_type":    str,    # "신중형" / "균형형" / "편향 주의" / "편향 심각"
    "top_bias":         str,    # 가장 심각한 편향 이름
    "behavioral_summary": str,  # 3줄 요약
    "coaching_message": str,    # PB 어조의 개인화 코칭 메시지
}
"""

from __future__ import annotations
import math

# ── 상수 ─────────────────────────────────────────────────────────────────────

# 최적 국내/해외 비중 기준 (글로벌 시가총액 기준 한국 비중 ≈ 1.5%)
# 하지만 한국 투자자 접근성 고려 → 20~40% 적정 범위로 설정
HOME_BIAS_OPTIMAL_MAX = 40.0  # 국내 자산 권장 상한 (%)
HOME_BIAS_DANGER      = 70.0  # 국내 자산 위험 임계 (%)

# 집중 편향: 단일 종목 최대 비중
CONCENTRATION_WARN    = 25.0  # 경고 (%)
CONCENTRATION_DANGER  = 35.0  # 위험 (%)

# 배당 앵커링: WEAKENING 이상이면서 비중이 높을 때
ANCHORING_WEIGHT_WARN = 10.0  # 문제 종목 누적 비중 경고 (%)

# 수익률 환상: 세전-세후 격차
YIELD_ILLUSION_GAP    = 1.5   # 세전-세후 격차 (%, 이 이상이면 환상)

# 과도한 방어 자산
DEFENSIVE_SAFE_MAX    = 40.0  # 안전자산 권장 상한 (%)
DEFENSIVE_DANGER      = 60.0  # 안전자산 위험 임계 (%)

# 국내 자산 분류
KR_ASSET_CLASSES = {"kr_stock", "kr_etf", "kr_reit"}
US_ASSET_CLASSES = {"us_stock", "us_div_etf", "us_reit", "defensive"}

_SEVERITY_MAP = {
    "high":   "🔴 심각",
    "medium": "🟡 주의",
    "low":    "🟢 경미",
}


# ─────────────────────────────────────────────────────────────────────────────
# 메인 함수
# ─────────────────────────────────────────────────────────────────────────────

def detect_behavioral_biases(
    recommendations: list[dict],
    risk_alerts:     list[dict],
    summary:         dict,
    investor_age:    int   = 35,
    risk_tolerance:  str   = "moderate",
) -> dict:
    """
    포트폴리오 구조에서 행동 편향을 자동 탐지.

    Args:
        recommendations: assign_weights() 반환값
        risk_alerts:     ML 리스크 경보 목록
        summary:         포트폴리오 요약 (avg_yield, avg_yield_net 등)
        investor_age:    투자자 나이
        risk_tolerance:  risk tolerance (conservative / moderate / aggressive)

    반환: 상단 docstring 참조
    """
    if not recommendations:
        return _empty_result()

    # 포트폴리오 기초 통계 계산
    stats = _calc_portfolio_stats(recommendations, summary)

    # ── 편향 탐지 실행 ────────────────────────────────────────────────────────
    biases = [
        _detect_home_bias(stats),
        _detect_concentration_bias(stats),
        _detect_recency_bias(stats),
        _detect_dividend_anchoring(stats, risk_alerts),
        _detect_loss_aversion(risk_alerts, stats),
        _detect_yield_illusion(stats),
        _detect_excessive_safety(stats, risk_tolerance),
        _detect_under_diversification(stats),
    ]

    # 탐지된 편향만 필터
    detected = [b for b in biases if b["detected"]]
    high_sev  = [b for b in detected if b["severity"] == "high"]
    med_sev   = [b for b in detected if b["severity"] == "medium"]

    # 전체 편향 점수 (가중 평균)
    if detected:
        weights = {"high": 1.5, "medium": 1.0, "low": 0.5}
        total_weighted = sum(b["score"] * weights[b["severity"]] for b in detected)
        total_w_sum    = sum(weights[b["severity"]] for b in detected)
        overall_score  = round(min(100, total_weighted / total_w_sum), 1)
    else:
        overall_score = 0.0

    # 투자자 유형 분류
    investor_type = _classify_investor(len(high_sev), overall_score)

    # 가장 심각한 편향
    top_bias = (
        max(detected, key=lambda b: b["score"])["name"]
        if detected else "없음"
    )

    # 행동 요약 + 코칭 메시지
    behavioral_summary = _make_behavioral_summary(detected, overall_score, stats)
    coaching_message   = _make_coaching_message(
        detected, investor_age, risk_tolerance, overall_score
    )

    return {
        "biases":               biases,       # 전체 편향 목록 (미탐지 포함)
        "detected_biases":      detected,     # 탐지된 편향만
        "bias_count":           len(detected),
        "high_severity":        len(high_sev),
        "overall_bias_score":   overall_score,
        "investor_type":        investor_type,
        "top_bias":             top_bias,
        "behavioral_summary":   behavioral_summary,
        "coaching_message":     coaching_message,
        "portfolio_stats":      stats,        # 디버깅/프론트용
    }


# ─────────────────────────────────────────────────────────────────────────────
# 포트폴리오 통계 계산
# ─────────────────────────────────────────────────────────────────────────────

def _calc_portfolio_stats(recommendations: list[dict], summary: dict) -> dict:
    """포트폴리오 구조 통계 계산."""
    total_w = sum(r.get("weight_pct", 0) for r in recommendations) or 100.0

    # 자산군별 비중
    class_w: dict[str, float] = {}
    for rec in recommendations:
        cls = rec.get("asset_class", "기타")
        class_w[cls] = class_w.get(cls, 0) + rec.get("weight_pct", 0)

    # 국내/해외 비중
    kr_w  = sum(class_w.get(c, 0) for c in KR_ASSET_CLASSES)
    us_w  = sum(class_w.get(c, 0) for c in US_ASSET_CLASSES)
    kr_pct = round(kr_w / total_w * 100, 1)

    # 최대 단일 종목 비중
    max_single = max((r.get("weight_pct", 0) for r in recommendations), default=0)
    max_ticker = next(
        (r.get("ticker", "") for r in recommendations if r.get("weight_pct") == max_single),
        ""
    )

    # 자산군 수
    n_classes = len(class_w)
    n_assets  = len(recommendations)

    # 수익률 정보
    avg_yield_gross = summary.get("avg_yield", 0)
    avg_yield_net   = summary.get("avg_yield_net", avg_yield_gross * 0.85)
    yield_gap       = round(avg_yield_gross - avg_yield_net, 2)

    # 방어 자산 비중
    defensive_w = class_w.get("defensive", 0)
    defensive_pct = round(defensive_w / total_w * 100, 1) if total_w else 0

    # 섹터별 비중 (자산군 기준 간이 계산)
    sector_hhi = sum((w / total_w * 100) ** 2 for w in class_w.values())

    # 고수익 자산 비중 (gross_yield_pct >= 6%)
    high_yield_w = sum(
        r.get("weight_pct", 0) for r in recommendations
        if float(r.get("gross_yield_pct") or r.get("dividend_yield") or 0) >= 6.0
    )
    high_yield_pct = round(high_yield_w / total_w * 100, 1)

    return {
        "total_w":           total_w,
        "class_w":           class_w,
        "kr_pct":            kr_pct,
        "us_pct":            round(us_w / total_w * 100, 1),
        "max_single_pct":    round(max_single / total_w * 100, 1),
        "max_single_ticker": max_ticker,
        "n_classes":         n_classes,
        "n_assets":          n_assets,
        "avg_yield_gross":   avg_yield_gross,
        "avg_yield_net":     avg_yield_net,
        "yield_gap":         yield_gap,
        "defensive_pct":     defensive_pct,
        "sector_hhi":        round(sector_hhi, 1),
        "high_yield_pct":    high_yield_pct,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 개별 편향 탐지 함수
# ─────────────────────────────────────────────────────────────────────────────

def _detect_home_bias(stats: dict) -> dict:
    """① 홈 바이어스 — 국내 자산 과다 비중."""
    kr_pct   = stats["kr_pct"]
    detected = kr_pct > HOME_BIAS_OPTIMAL_MAX
    severity = (
        "high"   if kr_pct >= HOME_BIAS_DANGER else
        "medium" if kr_pct >= HOME_BIAS_OPTIMAL_MAX + 15 else
        "low"    if detected else "low"
    )
    score = round(min(100, max(0, (kr_pct - HOME_BIAS_OPTIMAL_MAX) * 2)), 1)

    return {
        "id":       "home_bias",
        "name":     "홈 바이어스",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"국내 자산 비중 {kr_pct}% — 글로벌 최적 배분(20~40%) 초과."
            if detected else
            f"국내 자산 비중 {kr_pct}% — 정상 범위."
        ),
        "nudge": (
            "국내에 익숙한 것은 자연스럽지만, '친숙함'이 곧 '안전함'은 아닙니다. "
            "한국 경제는 글로벌 GDP의 1.7% — 포트폴리오 비중이 그보다 훨씬 높다면 이유를 점검하세요."
        ) if detected else "",
        "debiasing_action": (
            f"국내 비중을 {kr_pct}% → 30% 이하로 낮추고 "
            "SCHD·VIG 같은 글로벌 ETF 비중을 늘리세요."
        ) if detected else "",
    }


def _detect_concentration_bias(stats: dict) -> dict:
    """② 집중 편향 — 단일 종목 과도한 비중."""
    max_pct  = stats["max_single_pct"]
    ticker   = stats["max_single_ticker"]
    detected = max_pct >= CONCENTRATION_WARN
    severity = (
        "high"   if max_pct >= CONCENTRATION_DANGER else
        "medium" if max_pct >= CONCENTRATION_WARN else
        "low"
    )
    score = round(min(100, max(0, (max_pct - 15) * 3)), 1)

    return {
        "id":       "concentration_bias",
        "name":     "집중 편향",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"{ticker} 단일 종목 비중 {max_pct}% — 분산 효과 약화 우려."
            if detected else
            f"최대 단일 종목 비중 {max_pct}% — 양호."
        ),
        "nudge": (
            f"'{ticker}'에 대한 신뢰는 소중하지만, 포트폴리오의 {max_pct}%를 "
            "한 종목에 걸면 그 종목의 배당 컷 한 번이 전체 현금흐름을 흔듭니다."
        ) if detected else "",
        "debiasing_action": (
            f"{ticker} 비중을 {max_pct}% → 15% 이하로 줄이고 "
            "동일 자산군 ETF로 분산하세요."
        ) if detected else "",
    }


def _detect_recency_bias(stats: dict) -> dict:
    """③ 최신성 편향 — 고수익률 자산 추격 과다 편입."""
    hy_pct   = stats["high_yield_pct"]
    detected = hy_pct >= 50.0
    severity = (
        "high"   if hy_pct >= 70 else
        "medium" if hy_pct >= 50 else
        "low"
    )
    score = round(min(100, max(0, (hy_pct - 40) * 2)), 1)

    return {
        "id":       "recency_bias",
        "name":     "최신성 편향 (고수익 추격)",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"연 배당 6% 이상 고수익 자산 비중 {hy_pct}% — "
            "최근 고수익 추격 패턴 감지."
            if detected else
            f"고수익 자산 비중 {hy_pct}% — 정상 범위."
        ),
        "nudge": (
            "높은 배당수익률은 종종 '주가 하락의 결과'입니다. "
            "지금의 고수익이 미래에도 유지될 것이라는 최신성 편향을 경계하세요."
        ) if detected else "",
        "debiasing_action": (
            "SCHD·VIG 등 3~5% 안정적 배당성장 ETF를 추가해 "
            "고수익 자산과 균형을 맞추세요. 현재 배당보다 10년 후 배당이 중요합니다."
        ) if detected else "",
    }


def _detect_dividend_anchoring(stats: dict, risk_alerts: list[dict]) -> dict:
    """④ 배당 앵커링 — WEAKENING 종목을 배당 때문에 계속 보유."""
    weak_held = [r for r in risk_alerts if r.get("signal") == "WEAKENING"]
    weak_w    = sum(r.get("weight_pct", 0) for r in weak_held)
    detected  = len(weak_held) >= 1 and weak_w >= ANCHORING_WEIGHT_WARN
    severity  = "high" if weak_w >= 20 else ("medium" if weak_w >= 10 else "low")
    score     = round(min(100, weak_w * 3), 1)
    tickers   = ", ".join(r.get("ticker", "") for r in weak_held[:3])

    return {
        "id":       "dividend_anchoring",
        "name":     "배당 앵커링",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"ML 신호 약화 종목({tickers}) 보유 비중 {weak_w}% — "
            "배당 때문에 교체를 미루는 앵커링 패턴."
            if detected else
            "신호 약화 종목 없음."
        ),
        "nudge": (
            f"'{tickers}'가 배당을 주고 있어도, "
            "ML 신호가 약화됐다면 이미 배당 컷 전조일 수 있습니다. "
            "'지금 받는 배당'에 앵커를 내리지 마세요."
        ) if detected else "",
        "debiasing_action": (
            f"{tickers} 비중을 절반으로 줄이고, 신호가 정상인 동일 자산군 종목으로 교체하세요. "
            "'신호 약화 = 예고 없는 배당 삭감 가능성'입니다."
        ) if detected else "",
    }


def _detect_loss_aversion(risk_alerts: list[dict], stats: dict) -> dict:
    """⑤ 손실 회피 — BROKEN 종목 미교체 (손실 확정을 두려워하는 패턴)."""
    broken    = [r for r in risk_alerts if r.get("signal") == "BROKEN"]
    broken_w  = sum(r.get("weight_pct", 0) for r in broken)
    detected  = len(broken) >= 1
    severity  = "high" if broken_w >= 10 else ("medium" if len(broken) >= 2 else "low")
    score     = round(min(100, len(broken) * 25 + broken_w * 2), 1)
    tickers   = ", ".join(r.get("ticker", "") for r in broken[:3])

    return {
        "id":       "loss_aversion",
        "name":     "손실 회피 편향",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"ML 신호 붕괴 종목({tickers}) 미교체 — "
            "손실 확정 회피로 보유 지속하는 패턴."
            if detected else
            "신호 붕괴 종목 없음."
        ),
        "nudge": (
            f"'{tickers}'를 아직 팔지 않은 이유가 '팔면 손해'라는 생각 때문인가요? "
            "이미 발생한 손실은 미래 손실과 무관합니다. "
            "'손실 확정' 이 아니라 '손실 차단'으로 생각을 바꾸세요."
        ) if detected else "",
        "debiasing_action": (
            f"신호 붕괴 종목({tickers})은 즉시 매도하세요. "
            "매도 후 동일 금액을 건강한 신호 종목에 재투자하면 "
            "포트폴리오 전체 기대수익률이 올라갑니다."
        ) if detected else "",
    }


def _detect_yield_illusion(stats: dict) -> dict:
    """⑥ 수익률 환상 — 세전 고수익에만 집중, 세후 실질 수익률 간과."""
    gap      = stats["yield_gap"]
    gross    = stats["avg_yield_gross"]
    detected = gap >= YIELD_ILLUSION_GAP and gross >= 5.0
    severity = "high" if gap >= 2.5 else ("medium" if gap >= 1.5 else "low")
    score    = round(min(100, gap * 25), 1)

    return {
        "id":       "yield_illusion",
        "name":     "수익률 환상",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"세전 평균 배당 {gross}% vs 세후 {stats['avg_yield_net']}% — "
            f"세금으로 연 {gap}%p 손실 발생 (숫자에 착시 가능)."
            if detected else
            f"세전/세후 격차 {gap}%p — 정상 수준."
        ),
        "nudge": (
            f"광고나 앱에서 보이는 '{gross}%'는 세전 숫자입니다. "
            f"실제 통장에 들어오는 돈은 세후 {stats['avg_yield_net']}% — "
            "항상 세후 수익률로 판단하세요."
        ) if detected else "",
        "debiasing_action": (
            "ISA 계좌 활용으로 세금을 줄이거나, "
            "세후 수익률 기준으로 모든 투자를 재평가하세요. "
            "배당수익률 비교 시 반드시 net yield 기준을 사용하세요."
        ) if detected else "",
    }


def _detect_excessive_safety(stats: dict, risk_tolerance: str) -> dict:
    """⑦ 과도한 안전 추구 — 방어 자산 비중이 너무 높아 성장 기회 상실."""
    def_pct  = stats["defensive_pct"]
    # 공격형은 방어 자산 30%도 과다, 안정형은 60%도 허용
    thresholds = {
        "aggressive":   (25.0, 40.0),
        "moderate":     (35.0, 55.0),
        "conservative": (50.0, 70.0),
    }
    warn_t, danger_t = thresholds.get(risk_tolerance, (35.0, 55.0))
    detected = def_pct > warn_t
    severity = "high" if def_pct > danger_t else ("medium" if def_pct > warn_t else "low")
    score    = round(min(100, max(0, (def_pct - warn_t) * 3)), 1)

    return {
        "id":       "excessive_safety",
        "name":     "과도한 안전 추구",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"방어 자산(채권·단기채) 비중 {def_pct}% — "
            f"{risk_tolerance} 투자자 권장 상한({warn_t}%) 초과."
            if detected else
            f"방어 자산 비중 {def_pct}% — 적정 수준."
        ),
        "nudge": (
            "안전이 최우선인 것은 맞지만, 배당성장 없는 방어 자산만으로는 "
            "인플레이션을 이기지 못합니다. '편안함'과 '올바른 자산 배분'은 다릅니다."
        ) if detected else "",
        "debiasing_action": (
            f"방어 자산 비중을 {def_pct}% → {round(warn_t)}% 수준으로 낮추고 "
            "SCHD·VIG 같은 배당성장 ETF로 전환하면 장기 실질 수익률이 개선됩니다."
        ) if detected else "",
    }


def _detect_under_diversification(stats: dict) -> dict:
    """⑧ 분산 부족 — 자산군/종목 수 부족."""
    n_cls    = stats["n_classes"]
    n_assets = stats["n_assets"]
    detected = n_cls < 3 or n_assets < 5
    severity = "high" if n_cls < 2 or n_assets < 3 else ("medium" if detected else "low")
    score    = round(min(100, max(0, (5 - n_assets) * 15 + (3 - n_cls) * 20)), 1)

    return {
        "id":       "under_diversification",
        "name":     "분산 부족",
        "detected": detected,
        "severity": severity if detected else "low",
        "severity_label": _SEVERITY_MAP[severity] if detected else "탐지 안됨",
        "score":    score if detected else 0.0,
        "evidence": (
            f"자산군 {n_cls}개, 총 {n_assets}종목 — "
            "분산 효과가 제한적입니다."
            if detected else
            f"자산군 {n_cls}개, {n_assets}종목 — 적정 분산."
        ),
        "nudge": (
            f"현재 {n_assets}개 종목은 특정 리스크 이벤트에 포트폴리오 전체가 "
            "흔들릴 수 있습니다. 최소 8~10개 종목, 3개 이상 자산군을 권장합니다."
        ) if detected else "",
        "debiasing_action": (
            f"자산군을 {n_cls}개 → 최소 4개로 확대하고, "
            "종목도 {n_assets}개 → 8개 이상으로 늘리세요. "
            "ETF 1~2개 추가만으로도 분산도가 크게 개선됩니다."
        ) if detected else "",
    }


# ─────────────────────────────────────────────────────────────────────────────
# 요약 생성
# ─────────────────────────────────────────────────────────────────────────────

def _classify_investor(n_high: int, overall_score: float) -> str:
    """투자자 행동 유형 분류."""
    if n_high == 0 and overall_score < 20:
        return "🟢 신중균형형"
    elif n_high == 0 and overall_score < 40:
        return "🟡 소폭 편향 주의"
    elif n_high <= 1 and overall_score < 55:
        return "🟠 편향 주의 — 점검 권고"
    else:
        return "🔴 편향 심각 — 즉시 재설계 필요"


def _make_behavioral_summary(
    detected: list[dict],
    overall_score: float,
    stats: dict,
) -> str:
    if not detected:
        return (
            "포트폴리오 구조에서 주요 행동 편향이 탐지되지 않았습니다. "
            "현재의 분산 전략을 유지하며 분기별 재점검을 권장합니다."
        )
    names = [b["name"] for b in sorted(detected, key=lambda x: -x["score"])[:3]]
    names_str = ", ".join(names)
    return (
        f"총 {len(detected)}가지 행동 편향 탐지 (전체 편향 강도 {overall_score}점). "
        f"주요 편향: {names_str}. "
        "아래 탈편향 액션을 통해 포트폴리오의 심리적 함정을 제거하세요."
    )


def _make_coaching_message(
    detected: list[dict],
    age: int,
    risk_tolerance: str,
    overall_score: float,
) -> str:
    """PB 어조의 개인화 코칭 메시지."""
    if not detected:
        return (
            f"{age}세 {_RISK_KR.get(risk_tolerance, '중립형')} 투자자로서 "
            "현재 포트폴리오는 행동경제학적으로 균형 잡힌 설계입니다. "
            "인간은 본능적으로 편향에 끌리므로, 시장이 급변할 때 이 균형이 흔들리지 않도록 "
            "사전에 리밸런싱 규칙을 문서화해 두시기 바랍니다."
        )

    high_list = [b for b in detected if b["severity"] == "high"]
    top = max(detected, key=lambda b: b["score"])

    age_note = ""
    if age >= 55:
        age_note = "은퇴 근접 구간에서 "
    elif age <= 35:
        age_note = "자산 형성 초기 단계에서 "

    msg = (
        f"{age_note}{age}세 {_RISK_KR.get(risk_tolerance, '중립형')} 투자자 기준으로 "
        f"포트폴리오 행동 편향 점수는 {overall_score}점입니다. "
    )

    if high_list:
        names = ", ".join(b["name"] for b in high_list[:2])
        msg += (
            f"특히 '{names}' 편향이 심각하게 감지되어 "
            "현금흐름과 장기 수익률에 실질적 악영향을 줄 수 있습니다. "
        )

    msg += (
        f"'{top['name']}' 편향부터 우선 해결하세요. "
        "행동 편향은 '잘못'이 아닌 인간의 본능입니다 — "
        "인식했다는 것만으로 이미 절반은 극복한 것입니다."
    )
    return msg


_RISK_KR = {
    "conservative": "안정형",
    "moderate":     "중립형",
    "aggressive":   "공격형",
}


def _empty_result() -> dict:
    return {
        "biases": [], "detected_biases": [], "bias_count": 0,
        "high_severity": 0, "overall_bias_score": 0.0,
        "investor_type": "🟢 신중균형형", "top_bias": "없음",
        "behavioral_summary": "데이터 없음.",
        "coaching_message": "포트폴리오 데이터를 제공해 주세요.",
        "portfolio_stats": {},
    }

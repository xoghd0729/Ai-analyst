"""
Thesis Agent — 투자 thesis 종합 판단

■ 역할
  ML 리스크 + 뉴스 이벤트 → INTACT / WEAKENING / BROKEN 판단
  Ollama EXAONE으로 자연어 설명 생성
  결과를 thesis_history DB에 저장 → 시간 변화 추적

■ 종합 리스크 공식
  composite_risk = ML × 0.70 + 뉴스 × 0.30
  BROKEN ≥ 0.55 / WEAKENING ≥ 0.30 / INTACT < 0.30

■ Contradiction Detection
  뉴스 긍정 + ML 위험 → "시장 기대와 펀더멘털 괴리"
  뉴스 부정 + ML 안전 → "일시적 이벤트 가능성"
"""

import os
import json
import logging
import requests
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "qwen3:14b")

THESIS_THRESHOLDS = {"BROKEN": 0.55, "WEAKENING": 0.30}

THESIS_PROMPT = """\
당신은 배당 투자 전문 리서치 애널리스트입니다.
다음 데이터를 종합하여 투자 thesis를 평가하세요.

## 종목
{name} ({stock_code})

## 재무 리스크 (XGBoost ML 분석)
- 배당 삭감 확률: {ml_risk_pct}%
- 배당성향: {payout_ratio}
- FCF 상태: {fcf_status}
- 배당커버리지: {dividend_coverage}

## 최근 뉴스 이벤트 (30일 이내)
{news_summary}
- 뉴스 리스크 점수: {news_risk_pct}%
- 주요 감지 이벤트: {dominant_event}

{contradiction_context}

## 평가 지침
- thesis_status: INTACT(유지) / WEAKENING(약화) / BROKEN(붕괴) 중 하나
- explanation: 2~3문장. 재무 데이터와 뉴스 이벤트를 연결해서 설명.
- action: 투자자에게 한 줄 액션 가이드

JSON만 반환 (다른 텍스트 없이):
{{"thesis_status": "INTACT/WEAKENING/BROKEN", "explanation": "...", "action": "..."}}"""


# ─────────────────────────────────────────────────────────────
# Ollama 호출
# ─────────────────────────────────────────────────────────────

def _call_ollama(prompt: str) -> str:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model":    OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream":   False,
            "options":  {"temperature": 0.1},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


# ─────────────────────────────────────────────────────────────
# Contradiction Detection
# ─────────────────────────────────────────────────────────────

def detect_contradiction(ml_risk_score: float, news_analysis: dict) -> tuple[bool, str]:
    """
    뉴스 신호 ↔ ML 재무 리스크 간 괴리 감지.

    반환: (is_contradiction, detail_message)

    케이스 1: 뉴스 긍정 + ML 위험
      → "시장 기대와 펀더멘털 괴리: 뉴스는 긍정적이나 재무 리스크 높음"
    케이스 2: 뉴스 부정 + ML 안전
      → "일시적 이벤트 가능성: 뉴스 부정적이나 재무 펀더멘털 양호"
    """
    news_signal = news_analysis.get("signal", "neutral")
    news_risk   = news_analysis.get("news_risk_score", 0.0)

    # 케이스 1: 뉴스 긍정인데 ML이 위험 신호
    if news_signal == "positive" and ml_risk_score >= 0.45:
        detail = (
            f"⚠️ 시장 기대와 펀더멘털 괴리 감지: "
            f"최근 뉴스 신호는 긍정적이나 ML 모델의 배당 삭감 확률이 {ml_risk_score*100:.1f}%입니다. "
            f"뉴스 개선이 재무 지표에 반영되기까지 시차가 있을 수 있습니다."
        )
        return True, detail

    # 케이스 2: 뉴스 부정인데 ML은 안전
    if news_signal == "negative" and news_risk >= 0.3 and ml_risk_score < 0.25:
        detail = (
            f"ℹ️ 일시적 이벤트 가능성: "
            f"최근 뉴스에서 부정적 신호({news_risk*100:.0f}%)가 감지되었으나 "
            f"ML 재무 분석상 배당 삭감 확률은 {ml_risk_score*100:.1f}%로 낮습니다. "
            f"단기 이벤트에 과민반응하지 않도록 주의가 필요합니다."
        )
        return True, detail

    return False, ""


# ─────────────────────────────────────────────────────────────
# 핵심 함수
# ─────────────────────────────────────────────────────────────

def generate_thesis(
    stock_code: str,
    name: str,
    ml_risk_score: float,
    news_analysis: dict,
    financial_data: Optional[dict] = None,
    save_to_db: bool = True,
    p_weakening: Optional[float] = None,   # 3-class 모델 P(WEAKENING)
    p_broken: Optional[float] = None,       # 3-class 모델 P(BROKEN)
) -> dict:
    """
    ML 리스크 + 뉴스 이벤트 → Thesis 생성 + DB 저장.

    반환:
    {
        "thesis_status":       "WEAKENING",
        "explanation":         "...",
        "action":              "...",
        "composite_risk":      0.42,
        "contradiction":       True,
        "contradiction_detail":"⚠️ 시장 기대와 펀더멘털 괴리...",
    }
    """
    fd = financial_data or {}
    news_risk      = news_analysis.get("news_risk_score", 0.0)
    composite_risk = round(ml_risk_score * 0.70 + news_risk * 0.30, 3)

    # ML 리스크가 양극단(0~0.15 or 0.65~1.0)으로 쏠리는 경우
    # payout/coverage 등 재무 지표로 중간 보정 → WEAKENING 구간 생성
    payout   = fd.get("payout_ratio")
    coverage = fd.get("dividend_coverage")
    dps_yoy  = fd.get("dps_yoy_pct")

    stress_score = 0.0
    if payout   is not None and payout   > 80:  stress_score += 0.15
    if payout   is not None and payout   > 100: stress_score += 0.10
    if coverage is not None and coverage < 1.5: stress_score += 0.15
    if coverage is not None and coverage < 1.0: stress_score += 0.10
    if dps_yoy  is not None and dps_yoy  < 0:   stress_score += 0.10

    # composite_risk가 INTACT 상단(0.15~0.30)이고 재무 스트레스 있으면 WEAKENING으로 올림
    adjusted_risk = round(min(composite_risk + stress_score * 0.5, 1.0), 3)

    if adjusted_risk >= THESIS_THRESHOLDS["BROKEN"]:
        rule_status = "BROKEN"
    elif adjusted_risk >= THESIS_THRESHOLDS["WEAKENING"]:
        rule_status = "WEAKENING"
    elif stress_score >= 0.25:
        rule_status = "WEAKENING"
    else:
        rule_status = "INTACT"

    # ── 3-class 모델 확률로 최종 보정 ────────────────────────────
    # p_weakening / p_broken 이 있으면 rule_status를 override
    # 우선순위: BROKEN 확률 > WEAKENING 확률 > rule_status(재무규칙)
    if p_broken is not None and p_weakening is not None:
        # BROKEN: 3-class P(BROKEN) > 0.40 이면 BROKEN 강제
        if p_broken >= 0.40:
            rule_status = "BROKEN"
        # WEAKENING: P(WEAKENING) > 0.25 이고 아직 BROKEN이 아니면
        elif p_weakening >= 0.25 and rule_status != "BROKEN":
            rule_status = "WEAKENING"
        # 둘 다 낮으면 재무규칙 결과 유지 (INTACT or 규칙 WEAKENING)

    # Contradiction Detection
    contradiction, contradiction_detail = detect_contradiction(ml_risk_score, news_analysis)

    # Ollama로 설명 생성
    explanation, action = _generate_explanation(
        stock_code, name, ml_risk_score, news_analysis, fd,
        rule_status, contradiction_detail,
    )

    result = {
        "stock_code":          stock_code,
        "name":                name,
        "thesis_status":       rule_status,
        "explanation":         explanation,
        "action":              action,
        "composite_risk":      composite_risk,
        "ml_risk":             round(ml_risk_score, 3),
        "news_risk":           round(news_risk, 3),
        "dominant_event":      news_analysis.get("dominant_label", "없음"),
        "news_signal":         news_analysis.get("signal", "neutral"),
        "contradiction":       contradiction,
        "contradiction_detail":contradiction_detail,
        "generated_at":        datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # DB 저장
    if save_to_db:
        _save_to_db(result)

    return result


def _generate_explanation(
    stock_code, name, ml_risk_score, news_analysis, fd,
    rule_status, contradiction_detail,
) -> tuple[str, str]:
    events = news_analysis.get("events", [])
    event_lines = [
        f"  - [{e['label']}] {e['headline'][:60]} (신뢰도 {e['confidence']:.0%})"
        for e in events[:5] if e["event_type"] != "no_relevant_event"
    ]
    news_summary = "\n".join(event_lines) if event_lines else "  - 유의미한 이벤트 없음"

    payout   = fd.get("payout_ratio")
    fcf      = fd.get("fcf")
    coverage = fd.get("dividend_coverage")

    # 괴리 감지 시 프롬프트에 추가
    contradiction_context = ""
    if contradiction_detail:
        contradiction_context = f"\n## ⚠️ 신호 괴리 감지\n{contradiction_detail}\n"

    prompt = THESIS_PROMPT.format(
        name=name, stock_code=stock_code,
        ml_risk_pct=f"{ml_risk_score * 100:.1f}",
        payout_ratio=f"{payout:.1f}%" if payout else "데이터 없음",
        fcf_status=("양호 (플러스)" if fcf > 0 else "악화 (마이너스)") if fcf is not None else "데이터 없음",
        dividend_coverage=f"{coverage:.2f}x" if coverage else "데이터 없음",
        news_summary=news_summary,
        news_risk_pct=f"{news_analysis.get('news_risk_score', 0) * 100:.1f}",
        dominant_event=news_analysis.get("dominant_label", "없음"),
        contradiction_context=contradiction_context,
    )

    try:
        raw = _call_ollama(prompt)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        return result.get("explanation", ""), result.get("action", "")
    except Exception as e:
        log.warning(f"[thesis_agent] Ollama 실패, fallback: {e}")
        return _rule_based_explanation(rule_status, ml_risk_score, news_analysis), _rule_based_action(rule_status)


# ─────────────────────────────────────────────────────────────
# DB 저장
# ─────────────────────────────────────────────────────────────

def _save_to_db(thesis: dict) -> None:
    """Thesis 결과를 thesis_history에 저장."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine("postgresql://localhost/ai_analyst")
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO thesis_history
                    (stock_code, name, thesis_status, composite_risk,
                     ml_risk, news_risk, dominant_event,
                     explanation, action, contradiction, contradiction_detail)
                VALUES
                    (:stock_code, :name, :thesis_status, :composite_risk,
                     :ml_risk, :news_risk, :dominant_event,
                     :explanation, :action, :contradiction, :contradiction_detail)
            """), {
                "stock_code":          thesis["stock_code"],
                "name":                thesis["name"],
                "thesis_status":       thesis["thesis_status"],
                "composite_risk":      thesis["composite_risk"],
                "ml_risk":             thesis["ml_risk"],
                "news_risk":           thesis["news_risk"],
                "dominant_event":      thesis.get("dominant_event", "없음"),
                "explanation":         thesis.get("explanation", ""),
                "action":              thesis.get("action", ""),
                "contradiction":       thesis.get("contradiction", False),
                "contradiction_detail":thesis.get("contradiction_detail", ""),
            })
            conn.commit()
            log.info(f"[thesis_agent] {thesis['name']} thesis 저장 완료")
    except Exception as e:
        log.warning(f"[thesis_agent] DB 저장 실패 (계속 진행): {e}")


def load_thesis_history(stock_code: str, limit: int = 10) -> list[dict]:
    """종목의 thesis 변화 이력 조회."""
    try:
        from sqlalchemy import create_engine, text
        engine = create_engine("postgresql://localhost/ai_analyst")
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT thesis_status, composite_risk, ml_risk, news_risk,
                       dominant_event, explanation, action,
                       contradiction, contradiction_detail, created_at
                FROM thesis_history
                WHERE stock_code = :code
                ORDER BY created_at DESC
                LIMIT :limit
            """), {"code": stock_code, "limit": limit}).fetchall()

        return [
            {
                "thesis_status":       r[0],
                "composite_risk":      r[1],
                "ml_risk":             r[2],
                "news_risk":           r[3],
                "dominant_event":      r[4],
                "explanation":         r[5],
                "action":              r[6],
                "contradiction":       r[7],
                "contradiction_detail":r[8],
                "created_at":          r[9].strftime("%Y-%m-%d %H:%M") if r[9] else "",
            }
            for r in rows
        ]
    except Exception as e:
        log.warning(f"[thesis_agent] history 조회 실패: {e}")
        return []


# ─────────────────────────────────────────────────────────────
# Fallback
# ─────────────────────────────────────────────────────────────

def _rule_based_explanation(status, ml_risk, news):
    dominant  = news.get("dominant_label", "없음")
    news_risk = news.get("news_risk_score", 0.0)
    if status == "BROKEN":
        return (
            f"ML 모델이 배당 삭감 확률을 {ml_risk*100:.1f}%로 평가하였으며, "
            f"뉴스에서 '{dominant}' 이벤트가 감지되었습니다. "
            f"재무 구조와 시장 신호를 고려할 때 배당 지속 가능성이 낮습니다."
        )
    elif status == "WEAKENING":
        return (
            f"배당 삭감 확률 {ml_risk*100:.1f}%로 주의 수준이며, "
            f"최근 뉴스에서 '{dominant}' 이벤트가 포착되었습니다. "
            f"단기 배당은 유지될 가능성이 높으나 모니터링이 필요합니다."
        )
    else:
        return (
            f"배당 삭감 확률 {ml_risk*100:.1f}%, 뉴스 리스크 {news_risk*100:.1f}%로 "
            f"현재 thesis는 안정적입니다. 배당 지속 가능성이 높은 상태입니다."
        )


def _rule_based_action(status):
    return {
        "BROKEN":    "비중 축소 또는 대체 종목 검토 권장",
        "WEAKENING": "현 비중 유지, 다음 분기 실적 및 배당 발표 확인 필요",
        "INTACT":    "장기 보유 유지, 반기 1회 리밸런싱 권장",
    }.get(status, "모니터링 유지")


def batch_thesis(stock_list: list[dict]) -> list[dict]:
    results = []
    for item in stock_list:
        try:
            results.append(generate_thesis(
                stock_code=item["stock_code"], name=item["name"],
                ml_risk_score=item.get("ml_risk_score", 0.0),
                news_analysis=item.get("news_analysis", {}),
                financial_data=item.get("financial_data", {}),
            ))
        except Exception as e:
            log.error(f"[thesis_agent] {item.get('name')} 실패: {e}")
    return results

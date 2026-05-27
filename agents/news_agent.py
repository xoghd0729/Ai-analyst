"""
News Intelligence Agent — 금융 이벤트 추출

■ 핵심 철학
  "감성 분석(긍정/부정)"이 아니라
  "배당 지속성에 영향을 주는 금융 이벤트 추출"

■ 2단계 파이프라인
  1차 (Python): 키워드 필터 → 관련 기사만 통과
  2차 (Ollama 로컬 LLM): 이벤트 추출 → 구조화된 JSON
  → 완전 무료, 제한 없음, 인터넷 불필요

■ 이벤트 체계
  dividend_cut / dividend_maintained / dividend_increase
  share_buyback / rights_offering / earnings_shock
  guidance_cut / restructuring / debt_increase / fcf_decline
  no_relevant_event
"""

import os
import json
import logging
import requests
from datetime import datetime

log = logging.getLogger(__name__)

# ── Ollama 설정 ────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "exaone3.5:7.8b")

# ─────────────────────────────────────────────────────────────
EVENT_TAXONOMY = {
    "dividend_cut":         {"direction": "negative", "weight": 1.0,  "label": "배당 삭감"},
    "dividend_maintained":  {"direction": "positive", "weight": 0.6,  "label": "배당 유지"},
    "dividend_increase":    {"direction": "positive", "weight": 0.8,  "label": "배당 증가"},
    "share_buyback":        {"direction": "positive", "weight": 0.5,  "label": "자사주 매입"},
    "rights_offering":      {"direction": "negative", "weight": 0.7,  "label": "유상증자"},
    "earnings_shock":       {"direction": "negative", "weight": 0.6,  "label": "실적 쇼크"},
    "guidance_cut":         {"direction": "negative", "weight": 0.7,  "label": "가이던스 하향"},
    "restructuring":        {"direction": "negative", "weight": 0.5,  "label": "구조조정"},
    "debt_increase":        {"direction": "negative", "weight": 0.4,  "label": "부채 증가"},
    "fcf_decline":          {"direction": "negative", "weight": 0.5,  "label": "FCF 감소"},
    "no_relevant_event":    {"direction": "neutral",  "weight": 0.0,  "label": "무관"},
}

EVENT_EXTRACTION_PROMPT = """\
당신은 배당 투자 전문 리서치 애널리스트입니다.

다음 뉴스에서 배당 지속성에 영향을 주는 금융 이벤트를 추출하세요.

종목: {name} ({stock_code})
뉴스 제목: {headline}
뉴스 요약: {summary}

반드시 아래 이벤트 중 하나를 선택하세요:
- dividend_cut: 배당 삭감 또는 중단 결정
- dividend_maintained: 명시적 배당 유지 발표
- dividend_increase: 배당 증가 결정
- share_buyback: 자사주 매입 (주주가치 제고 신호)
- rights_offering: 유상증자 (자금 조달, 주주가치 희석)
- earnings_shock: 실적 쇼크, 대규모 손실, 어닝 미스
- guidance_cut: 향후 실적 가이던스 하향 조정
- restructuring: 구조조정, 사업 매각, 조직 개편
- debt_increase: 부채 급증, 신용등급 하락, 차입 확대
- fcf_decline: FCF 감소, 영업현금흐름 악화
- no_relevant_event: 배당 지속성과 무관한 뉴스

중요: 제목의 전체적인 감성이 아니라, 배당 지속성에 직접 영향을 주는 사건이 있는지 판단하세요.
예) "실적 쇼크에도 배당 유지" → event_type: dividend_maintained

반드시 JSON만 반환 (다른 텍스트 없이):
{{"event_type": "...", "confidence": 0.0~1.0, "direction": "positive/negative/neutral", "reason": "배당 관점에서 한 줄 이유"}}"""

# ── 배치 추출 프롬프트 (여러 기사 → 1번 Ollama 호출) ──────────────
BATCH_EXTRACTION_PROMPT = """\
당신은 배당 투자 전문 리서치 애널리스트입니다.

종목: {name} ({stock_code})

아래 {n}개 뉴스 기사 각각에 대해 배당 지속성에 영향을 주는 금융 이벤트를 추출하세요.

이벤트 종류:
- dividend_cut: 배당 삭감 또는 중단
- dividend_maintained: 명시적 배당 유지 발표
- dividend_increase: 배당 증가 결정
- share_buyback: 자사주 매입
- rights_offering: 유상증자 (주주가치 희석)
- earnings_shock: 실적 쇼크, 대규모 손실
- guidance_cut: 향후 실적 가이던스 하향
- restructuring: 구조조정, 사업 매각
- debt_increase: 부채 급증, 신용등급 하락
- fcf_decline: FCF 감소, 영업현금흐름 악화
- no_relevant_event: 배당 지속성과 무관

중요: 전체 감성이 아니라, 배당 지속성에 직접 영향을 주는 사건 중심으로 판단하세요.

{articles_block}

반드시 JSON 배열만 반환 (다른 텍스트 없이):
[
  {{"idx": 1, "event_type": "...", "confidence": 0.0, "direction": "positive/negative/neutral", "reason": "한 줄 이유"}},
  {{"idx": 2, "event_type": "...", "confidence": 0.0, "direction": "positive/negative/neutral", "reason": "한 줄 이유"}},
  ...
]"""


def _call_ollama(prompt: str) -> str:
    """Ollama 로컬 서버 호출."""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json={
            "model":    OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream":   False,
            "options":  {"temperature": 0.1},  # JSON 안정성 위해 낮게
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"].strip()


def extract_event(stock_code, name, headline, summary="", client=None):
    """단일 기사 → 이벤트 추출 (Ollama). 배치 처리 실패 시 fallback용."""
    prompt = EVENT_EXTRACTION_PROMPT.format(
        name=name, stock_code=stock_code,
        headline=headline, summary=summary[:400],
    )
    raw = ""
    try:
        raw = _call_ollama(prompt)
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())
        event_type = result.get("event_type", "no_relevant_event")
        meta = EVENT_TAXONOMY.get(event_type, EVENT_TAXONOMY["no_relevant_event"])
        return {
            "event_type": event_type,
            "confidence": float(result.get("confidence", 0.5)),
            "direction":  result.get("direction", meta["direction"]),
            "reason":     result.get("reason", ""),
            "label":      meta["label"],
            "weight":     meta["weight"],
            "headline":   headline,
        }
    except json.JSONDecodeError as e:
        log.warning(f"[news_agent] JSON 파싱 실패: {e} | raw: {raw[:80]}")
        return _fallback_event(headline)
    except Exception as e:
        log.warning(f"[news_agent] Ollama 호출 실패: {e}")
        return _fallback_event(headline)


def batch_extract_events(stock_code: str, name: str, articles: list) -> list:
    """
    여러 기사를 한 번의 Ollama 호출로 처리 → 속도 대폭 향상.

    ■ 왜 배치인가
      기존: 기사 10개 × 1 Ollama 호출 = 10번 호출 (종목당 ~30~60초)
      변경: 기사 10개를 하나의 프롬프트에 묶어 1번 호출 (종목당 ~5~10초)
      → 전체 배치 시간: 40~60분 → ~10분

    ■ 반환 형식
      [{"event_type": ..., "confidence": ..., "direction": ..., "reason": ...,
        "label": ..., "weight": ..., "headline": ...}, ...]

    ■ 실패 처리
      JSON 파싱 실패 시 → 기사별 개별 extract_event()로 fallback (느리지만 안전)
    """
    if not articles:
        return []

    # 기사 블록 구성: [1] 제목: ... / 요약: ...
    articles_block_lines = []
    for i, a in enumerate(articles, 1):
        headline = a.get("headline", "")
        summary  = a.get("summary", "")[:200]
        articles_block_lines.append(f"[{i}] 제목: {headline}")
        if summary:
            articles_block_lines.append(f"    요약: {summary}")
    articles_block = "\n".join(articles_block_lines)

    prompt = BATCH_EXTRACTION_PROMPT.format(
        name=name,
        stock_code=stock_code,
        n=len(articles),
        articles_block=articles_block,
    )

    raw = ""
    try:
        raw = _call_ollama(prompt)

        # ```json ... ``` 블록 제거
        if "```" in raw:
            parts = raw.split("```")
            # parts[1]이 json 블록
            for part in parts[1:]:
                if part.startswith("json"):
                    raw = part[4:].strip()
                    break
                elif part.strip().startswith("["):
                    raw = part.strip()
                    break

        raw = raw.strip()

        # JSON 배열 파싱
        result_list = json.loads(raw)

        if not isinstance(result_list, list):
            raise ValueError(f"배열이 아닌 응답: {type(result_list)}")

        # 결과를 articles 순서에 맞게 매핑
        # idx가 있으면 idx 기준, 없으면 순서대로
        idx_map = {}
        for item in result_list:
            if isinstance(item, dict):
                idx = item.get("idx", len(idx_map) + 1)
                idx_map[idx] = item

        events = []
        for i, article in enumerate(articles, 1):
            item = idx_map.get(i, {})
            if not item:
                # 해당 기사 결과 누락 → fallback
                log.debug(f"[batch] idx={i} 누락, fallback 사용")
                events.append(_fallback_event(article.get("headline", "")))
                continue

            event_type = item.get("event_type", "no_relevant_event")
            if event_type not in EVENT_TAXONOMY:
                event_type = "no_relevant_event"
            meta = EVENT_TAXONOMY[event_type]

            events.append({
                "event_type": event_type,
                "confidence": float(item.get("confidence", 0.5)),
                "direction":  item.get("direction", meta["direction"]),
                "reason":     item.get("reason", ""),
                "label":      meta["label"],
                "weight":     meta["weight"],
                "headline":   article.get("headline", ""),
            })

        log.info(f"[batch] {name} ({stock_code}): {len(articles)}건 → 1회 Ollama 호출 완료")
        return events

    except (json.JSONDecodeError, ValueError) as e:
        log.warning(f"[batch] JSON 파싱 실패: {e} | raw[:120]={raw[:120]}")
        log.warning(f"[batch] {name}: 개별 호출로 fallback")
        # 개별 처리로 안전하게 fallback
        events = []
        for article in articles:
            event = extract_event(
                stock_code=stock_code, name=name,
                headline=article.get("headline", ""),
                summary=article.get("summary", ""),
            )
            events.append(event)
        return events
    except Exception as e:
        log.warning(f"[batch] Ollama 호출 실패: {e} | {name}: 개별 호출로 fallback")
        events = []
        for article in articles:
            event = extract_event(
                stock_code=stock_code, name=name,
                headline=article.get("headline", ""),
                summary=article.get("summary", ""),
            )
            events.append(event)
        return events


def _fallback_event(headline=""):
    return {
        "event_type": "no_relevant_event",
        "confidence": 0.0,
        "direction":  "neutral",
        "reason":     "분석 실패",
        "label":      "무관",
        "weight":     0.0,
        "headline":   headline,
    }


def analyze_stock_news(stock_code, name, articles):
    if not articles:
        return _empty_analysis(stock_code, name)

    # ── 배치 처리: 기사 전체를 1번 Ollama 호출로 처리 ─────────────
    # 기존: articles[:10] × 1호출씩 = 최대 10번 호출
    # 변경: articles[:10] 전부를 1번 호출로 처리 → ~10배 빠름
    target_articles = articles[:10]
    raw_events = batch_extract_events(stock_code, name, target_articles)

    events = []
    for event, article in zip(raw_events, target_articles):
        event["published"] = article.get("published", "")
        event["url"]       = article.get("url", "")
        events.append(event)

    risk_score = 0.0
    for e in events:
        if e["direction"] == "negative":
            risk_score += e["weight"] * e["confidence"]
        elif e["direction"] == "positive":
            risk_score -= e["weight"] * e["confidence"] * 0.5
    risk_score = max(0.0, min(1.0, risk_score / max(len(events), 1)))

    significant = [e for e in events if e["event_type"] != "no_relevant_event"]
    dominant = max(significant, key=lambda e: e["weight"] * e["confidence"]) if significant else None

    neg_count = sum(1 for e in events if e["direction"] == "negative")
    pos_count = sum(1 for e in events if e["direction"] == "positive")
    signal = "negative" if neg_count > pos_count else ("positive" if pos_count > neg_count else "neutral")

    return {
        "stock_code":      stock_code,
        "name":            name,
        "events":          events,
        "news_risk_score": round(risk_score, 3),
        "dominant_event":  dominant["event_type"] if dominant else "no_relevant_event",
        "dominant_label":  dominant["label"] if dominant else "없음",
        "signal":          signal,
        "article_count":   len(articles),
        "analyzed_count":  len(events),
        "analyzed_at":     datetime.now().strftime("%Y-%m-%d"),
    }


def _empty_analysis(stock_code, name):
    return {
        "stock_code": stock_code, "name": name,
        "events": [], "news_risk_score": 0.0,
        "dominant_event": "no_relevant_event", "dominant_label": "없음",
        "signal": "neutral", "article_count": 0,
        "analyzed_count": 0, "analyzed_at": datetime.now().strftime("%Y-%m-%d"),
    }

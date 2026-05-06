import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os
import re
import json
import requests
from bs4 import BeautifulSoup
from datetime import date, timedelta
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import create_engine, text

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
DART_API_KEY = os.getenv("DART_API_KEY")
engine = create_engine("postgresql://localhost/ai_analyst")

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


# ── 1. DART 공시 수집 ──────────────────────────────────────────────────────────

def fetch_dart_disclosures(corp_code: str, days: int = 30) -> list[str]:
    """최근 N일 DART 공시 제목 반환"""
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": (date.today() - timedelta(days=days)).strftime("%Y%m%d"),
        "end_de": date.today().strftime("%Y%m%d"),
        "page_count": 10,
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("status") == "000":
            items = data.get("list", [])
            titles = [item["report_nm"] for item in items]
            print(f"  DART 공시 {len(titles)}개 수집")
            return titles
        else:
            print(f"  DART 응답 이상: {data.get('message', '')}")
    except Exception as e:
        print(f"  DART 수집 실패: {e}")
    return []


# ── 2. Naver 금융 뉴스 수집 ───────────────────────────────────────────────────

def fetch_naver_news(stock_code: str, limit: int = 7) -> list[str]:
    """Naver Finance 종목 뉴스 제목 반환 (URL 변경 대응: .nhn → .naver)"""
    urls = [
        f"https://finance.naver.com/item/news_news.naver?code={stock_code}&page=1",
        f"https://finance.naver.com/item/news_news.nhn?code={stock_code}&page=1",
    ]
    # CSS selector 후보: Naver가 리뉴얼하면서 selector 변경됨
    selectors = [
        "td.title a",          # 구버전
        ".news_item .title a", # 리뉴얼 후보 1
        "a.news_tit",          # 리뉴얼 후보 2
        ".articleSubject a",   # 후보 3
        "ul.news_list li a",   # 후보 4
        "div.news_area a",     # 후보 5
    ]
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.encoding = "euc-kr"
            soup = BeautifulSoup(r.text, "html.parser")

            for sel in selectors:
                items = soup.select(sel)
                titles = [a.get_text(strip=True) for a in items[:limit] if a.get_text(strip=True)]
                if titles:
                    print(f"  Naver 뉴스 {len(titles)}개 수집 (selector: {sel})")
                    return titles

        except Exception as e:
            print(f"  Naver 뉴스 수집 실패 ({url}): {e}")

    # 마지막 수단: 원시 텍스트에서 링크 추출
    try:
        r = requests.get(urls[0], headers=HEADERS, timeout=10)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")
        # 모든 <a> 태그 중 뉴스처럼 보이는 것 추출
        all_links = [a.get_text(strip=True) for a in soup.find_all("a")
                     if len(a.get_text(strip=True)) > 10 and "naver" not in a.get_text(strip=True).lower()]
        titles = [t for t in all_links if len(t) > 15][:limit]
        if titles:
            print(f"  Naver 뉴스 {len(titles)}개 수집 (fallback 파싱)")
            return titles
    except Exception:
        pass

    print(f"  Naver 뉴스 0개 수집 (파싱 실패 — HTML 구조 확인 필요)")
    return []


# ── 3. LLM 구조화 ─────────────────────────────────────────────────────────────

def structurize_events(stock_name: str, headlines: list[str]) -> list[dict]:
    """뉴스/공시 제목 → 구조화된 이벤트 JSON"""
    if not headlines:
        return []

    prompt = f"""당신은 한국 주식 바이사이드 애널리스트입니다.
아래 {stock_name} 관련 뉴스/공시 제목을 읽고, 투자 thesis 관점에서 구조화하세요.

[뉴스/공시 제목]
{chr(10).join(f'{i+1}. {h}' for i, h in enumerate(headlines))}

[출력 형식 - JSON 배열만, 다른 텍스트 없이]
[
  {{
    "headline": "원본 제목 그대로",
    "event_type": "earnings" | "guidance" | "contract" | "regulation" | "macro" | "insider" | "restructuring" | "other",
    "impact": "positive" | "negative" | "neutral",
    "thesis_relevance": "high" | "medium" | "low",
    "summary": "이 이벤트가 장기 투자 thesis에 미치는 영향 1문장. 수치가 있으면 포함."
  }}
]

[분류 기준]
- thesis_relevance high: 실적 가이던스 변경, 대형 계약/수주, 주요 경영진 변동, 규제 리스크
- thesis_relevance medium: 사업 현황 공시, 시장 점유율 변화
- thesis_relevance low: 단순 보도자료, 행사 참여, 일반적인 시장 동향
- impact는 장기 투자 thesis(6개월~1년) 기준으로 판단
- JSON만 출력. 중복 제거.
"""

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1500,
            )
            raw = response.choices[0].message.content
            raw = re.sub(r'```json|```', '', raw)
            start, end = raw.find('['), raw.rfind(']')
            if start == -1 or end == -1:
                continue
            events = json.loads(raw[start:end+1])
            return events
        except Exception as e:
            print(f"  이벤트 구조화 시도 {attempt+1} 실패: {e}")

    return []


# ── 4. DB 저장 ────────────────────────────────────────────────────────────────

def save_events(stock_code: str, events: list[dict]):
    today_str = date.today().isoformat()
    saved = 0
    with engine.connect() as conn:
        for ev in events:
            try:
                conn.execute(text("""
                    INSERT INTO events (stock_code, date, headline, event_type, impact, thesis_relevance, summary)
                    VALUES (:code, :date, :headline, :type, :impact, :relevance, :summary)
                    ON CONFLICT (stock_code, date, headline) DO NOTHING
                """), {
                    "code": stock_code,
                    "date": today_str,
                    "headline": ev.get("headline", "")[:200],
                    "type": ev.get("event_type", "other"),
                    "impact": ev.get("impact", "neutral"),
                    "relevance": ev.get("thesis_relevance", "low"),
                    "summary": ev.get("summary", ""),
                })
                saved += 1
            except Exception as e:
                print(f"  이벤트 저장 오류: {e}")
        conn.commit()
    print(f"✅ 이벤트 {saved}개 저장")


# ── 5. 메인 진입점 ────────────────────────────────────────────────────────────

def collect_events(stock_code: str, stock_name: str, corp_code: str) -> list[dict]:
    print(f"  뉴스/공시 수집 중...")
    dart = fetch_dart_disclosures(corp_code, days=30)
    naver = fetch_naver_news(stock_code, limit=7)

    all_headlines = dart + naver
    if not all_headlines:
        print("⚠️  수집된 뉴스/공시 없음")
        return []

    events = structurize_events(stock_name, all_headlines)
    if events:
        save_events(stock_code, events)
        high = [e for e in events if e.get("thesis_relevance") == "high"]
        if high:
            print(f"  ⚡ thesis 관련 주요 이벤트 {len(high)}개 감지")
    return events


def get_recent_events(stock_code: str, days: int = 7) -> list[dict]:
    """llm.py에서 호출 — 최근 이벤트 반환 (thesis_relevance 순 정렬)"""
    since = (date.today() - timedelta(days=days)).isoformat()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT headline, event_type, impact, thesis_relevance, summary
            FROM events
            WHERE stock_code = :code AND date >= :since
            ORDER BY
                CASE thesis_relevance WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                date DESC
            LIMIT 8
        """), {"code": stock_code, "since": since}).fetchall()
    return [
        {
            "headline": r[0], "event_type": r[1],
            "impact": r[2], "thesis_relevance": r[3], "summary": r[4]
        }
        for r in rows
    ]


if __name__ == "__main__":
    events = collect_events("005930", "삼성전자", "00126380")
    for e in events:
        marker = "⚡" if e["thesis_relevance"] == "high" else "·"
        print(f"{marker} [{e['impact']:8s}] {e['headline']}")
        print(f"  → {e['summary']}")

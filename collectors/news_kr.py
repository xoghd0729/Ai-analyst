"""
한국 주식 뉴스 수집기 — Google News RSS 기반

■ 3단계 파이프라인
  1차 (Tier 1): Python 키워드 필터 — 관련 기사만 통과, 비용 0원
  2차 (Tier 2): rank_articles() — dedupe + 가중치 + recency decay → Top-K 선정
  3차 (Tier 3): news_agent.py → EXAONE 맥락 추론 (이벤트 추출)

■ 왜 Tier 2가 필요한가
  RSS는 동일 기사가 여러 소스에 복붙돼서 들어옴 → dedupe 필수
  배당삭감/유상증자 기사가 "~기대감" 기사보다 훨씬 중요 → 가중치 랭킹
  오래된 뉴스보다 최신 뉴스가 더 중요 → recency decay
  결과적으로 Top-3만 EXAONE에 전달 → 노이즈 감소 + 속도 개선
"""

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import re
import time
import logging
import difflib
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 1차 필터: 배당 투자 thesis에 영향을 주는 키워드만 통과
# 이 단계는 Claude 없이 Python으로 처리 → 비용 0원
# ─────────────────────────────────────────────────────────────
DIVIDEND_KEYWORDS = [
    # 배당 직접 관련
    "배당", "배당금", "배당수익률", "배당삭감", "배당컷", "배당유지", "배당증가",
    "주주환원", "자사주", "자사주매입", "자사주소각",
    # 부정 이벤트 (배당 삭감 선행 신호)
    "실적 쇼크", "영업손실", "순손실", "적자", "어닝쇼크",
    "구조조정", "희망퇴직", "사업재편", "매각", "분할",
    "유상증자", "증자", "신주발행",
    "부채", "신용등급", "등급하락", "워크아웃", "법정관리",
    # 긍정 이벤트
    "실적 개선", "어닝서프라이즈", "깜짝실적", "가이던스 상향",
    "FCF", "현금흐름 개선",
]

EXCLUDE_KEYWORDS = [
    "광고", "PR", "홍보", "[광고]", "sponsored",
]

# ── 미국 주식 영어 키워드 필터 ──────────────────────────────────
US_DIVIDEND_KEYWORDS = [
    # 배당 직접 관련
    "dividend", "dividends", "payout", "yield",
    "buyback", "share repurchase", "stock repurchase",
    # 부정 이벤트 (배당 삭감 선행 신호)
    "earnings", "revenue", "profit", "loss", "guidance",
    "restructuring", "layoff", "job cut", "cost cut",
    "debt", "credit rating", "downgrade", "default",
    "dilution", "share offering", "rights offering",
    "cash flow", "fcf", "free cash flow",
    # 긍정 이벤트
    "beat", "raised guidance", "raised dividend", "dividend increase",
    "dividend hike", "special dividend",
]

US_EXCLUDE_KEYWORDS = [
    "sponsored", "advertisement", "promotion",
]

# ─────────────────────────────────────────────────────────────
# Tier 2: 중요도 가중치 — 배당 지속성에 미치는 영향도 기준
# 숫자가 클수록 EXAONE에 우선 전달되어야 할 핵심 신호
# ─────────────────────────────────────────────────────────────
KEYWORD_WEIGHTS = {
    # 직접 배당 결정 (최고 우선순위)
    "배당삭감":   10, "배당컷":    10, "배당중단":  10, "무배당":    10,
    "배당증가":    8, "배당확대":   8,
    "배당유지":    6, "배당동결":   6,
    # 배당 선행 신호 (부정)
    "워크아웃":    9, "법정관리":   9,
    "유상증자":    8, "신주발행":   7,
    "실적쇼크":    8, "어닝쇼크":   8, "영업손실":   7, "순손실":    7,
    "신용등급":    6, "등급하락":   7,
    "구조조정":    5, "희망퇴직":   5,
    # 배당 선행 신호 (긍정)
    "자사주매입":  5, "자사주소각": 6,
    "어닝서프라이즈": 5, "깜짝실적":  5,
    "주주환원":    4,
    # 일반 (낮은 우선순위)
    "배당":        3,
    "실적":        2,
    "fcf":         2, "현금흐름":   2,
}

# Recency decay: 기사 발행일 기준 경과 일수 → 가중치
# 배당 결정은 발표 직후가 가장 중요하고 오래될수록 신선도 감소
RECENCY_TABLE = [
    (1,  1.0),   # 1일 이내: 100%
    (3,  0.8),   # 3일 이내: 80%
    (7,  0.5),   # 7일 이내: 50%
    (14, 0.3),   # 14일 이내: 30%
]
RECENCY_DEFAULT = 0.2   # 14일 초과


def _recency_weight(pub_str: str) -> float:
    """
    기사 발행일 문자열 → recency 가중치 (0.2 ~ 1.0).

    발행일을 파싱할 수 없으면 0.5 (중립) 반환.
    """
    pub_dt = _parse_date(pub_str)
    if pub_dt is None:
        return 0.5
    days_ago = (datetime.now() - pub_dt).days
    for max_days, weight in RECENCY_TABLE:
        if days_ago <= max_days:
            return weight
    return RECENCY_DEFAULT


def _article_score(article: dict) -> float:
    """
    단일 기사 중요도 점수.

    = Σ(등장 키워드 가중치) × recency_weight
    키워드는 제목 + 요약을 합친 텍스트에서 검색.
    """
    text  = (article.get("headline", "") + " " + article.get("summary", "")).lower()
    score = sum(w for kw, w in KEYWORD_WEIGHTS.items() if kw in text)
    score *= _recency_weight(article.get("published", ""))
    return score


def _is_duplicate(title_a: str, title_b: str, threshold: float = 0.85) -> bool:
    """
    두 기사 제목의 유사도가 threshold 이상이면 중복으로 판단.

    difflib.SequenceMatcher: 공통 부분 문자열 비율 기반.
    RSS에서 동일 기사가 여러 언론사에 복붙되는 케이스를 잡는다.
    """
    ratio = difflib.SequenceMatcher(None, title_a, title_b).ratio()
    return ratio >= threshold


def rank_articles(articles: list, top_k: int = 3) -> list:
    """
    Tier 2: 수집된 기사 → 중복 제거 → 중요도 정렬 → Top-K 반환.

    ■ 단계
      1. 제목 유사도 기반 dedupe (SequenceMatcher ≥ 0.85)
         동일 뉴스가 N개 언론사에 복붙된 경우 대표 1개만 남김
      2. KEYWORD_WEIGHTS × recency_weight 로 점수 산출
      3. 점수 내림차순 정렬 후 상위 top_k개 반환

    ■ 왜 Top-3인가
      EXAONE은 핵심 정보 3개에서 더 정확히 추론함.
      10개를 주면 "~기대감" 같은 노이즈 기사가 맥락을 흐림.
    """
    # ── Step 1: dedupe ────────────────────────────────────────
    deduped = []
    for article in articles:
        title = article.get("headline", "")
        # 이미 선택된 기사 중 유사 제목이 있으면 스킵
        if any(_is_duplicate(title, seen.get("headline", "")) for seen in deduped):
            continue
        deduped.append(article)

    # ── Step 2 & 3: score → sort → Top-K ──────────────────────
    scored = [(a, _article_score(a)) for a in deduped]
    scored.sort(key=lambda x: x[1], reverse=True)

    top = [a for a, _ in scored[:top_k]]

    log.debug(
        f"[rank] {len(articles)}건 → dedupe {len(deduped)}건 → Top-{top_k} 선정: "
        + " | ".join(a.get("headline", "")[:30] for a in top)
    )
    return top


def _is_relevant(title: str, summary: str = "") -> bool:
    """키워드 기반 1차 필터 — Claude 호출 전 불필요한 기사 제거."""
    text = (title + " " + summary).lower()
    if any(ex.lower() in text for ex in EXCLUDE_KEYWORDS):
        return False
    return any(kw in text for kw in DIVIDEND_KEYWORDS)


# ─────────────────────────────────────────────────────────────
# 네이버 금융 RSS 수집
# ─────────────────────────────────────────────────────────────

def fetch_naver_news(stock_code: str, name: str, days: int = 7) -> list[dict]:
    """
    Google News RSS로 최근 N일간 한국어 뉴스 수집.

    왜 Google News RSS인가:
      - Naver Finance RSS / Naver 검색 RSS 모두 2024년 이후 막혀 있음
      - Google News RSS는 API 키 없이 무료 제공, 한국어/한국 지역 지원
      - hl=ko&gl=KR&ceid=KR:ko → 한국어 뉴스 우선 노출

    반환: [{"headline": str, "url": str, "published": str, "summary": str}]
    """
    articles = []

    # 검색 쿼리 3종: 배당 집중 / 실적 / 회사명 단독 (폭넓게 수집 후 필터)
    search_queries = [
        f"{name} 배당",
        f"{name} 실적",
        f"{name} 주주환원",
    ]

    for q in search_queries:
        encoded = urllib.parse.quote(q)
        url = (
            f"https://news.google.com/rss/search"
            f"?q={encoded}&hl=ko&gl=KR&ceid=KR:ko"
        )
        fetched = _fetch_rss(url, source="google_news", days=days)
        articles += fetched
        time.sleep(0.4)   # Google 과도 요청 방지

    # ── Tier 1: 키워드 필터 ───────────────────────────────────
    filtered = [a for a in articles if _is_relevant(a["headline"], a.get("summary", ""))]

    # 키워드 필터 후 0건이면: 원문 기사에서 그대로 Tier 2로 (EXAONE이 no_relevant_event 처리)
    if not filtered and articles:
        filtered = articles[:10]

    # URL 기준 1차 dedupe (완전 동일 URL 제거)
    seen_urls: set[str] = set()
    url_deduped: list[dict] = []
    for a in filtered:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            url_deduped.append(a)

    # ── Tier 2: 중요도 랭킹 → Top-3 선정 ────────────────────
    # dedupe(제목 유사도) + KEYWORD_WEIGHTS × recency_decay → 상위 3개
    top_articles = rank_articles(url_deduped, top_k=3)

    log.info(
        f"[news_kr] {name} ({stock_code}): "
        f"수집 {len(articles)}건 → 필터 {len(url_deduped)}건 → Top-{len(top_articles)} 선정"
    )
    return top_articles


def _fetch_rss(url: str, source: str, days: int) -> list[dict]:
    """
    RSS URL에서 기사 목록 파싱.

    Google News RSS 특이사항:
      - <link>가 Google 리다이렉트 URL → 그대로 사용 (원본 URL 접근 안 해도 됨)
      - <description>이 없거나 HTML 포함 가능 → _clean()으로 처리
      - namespace 없이 표준 RSS 2.0 구조
    """
    articles = []
    cutoff = datetime.now() - timedelta(days=days)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
                "Accept-Language": "ko-KR,ko;q=0.9",
            }
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read()

        # Google News RSS는 가끔 BOM 포함 → 제거
        if content.startswith(b"\xef\xbb\xbf"):
            content = content[3:]

        root = ET.fromstring(content)
        channel = root.find("channel")
        if channel is None:
            log.debug(f"[news_kr] channel 태그 없음: {url[:60]}")
            return []

        for item in channel.findall("item"):
            title   = _clean(item.findtext("title") or "")
            link    = _clean(item.findtext("link") or "")
            desc    = _clean(item.findtext("description") or "")
            pub_str = item.findtext("pubDate") or ""

            if not title:
                continue

            # 날짜 파싱 — 없으면 cutoff 체크 건너뜀
            pub_dt = _parse_date(pub_str)
            if pub_dt and pub_dt < cutoff:
                continue

            articles.append({
                "headline":  title,
                "url":       link,
                "summary":   desc[:300],
                "published": pub_str,
                "source":    source,
            })

    except ET.ParseError as e:
        log.debug(f"[news_kr] XML 파싱 실패 ({url[:60]}): {e}")
    except Exception as e:
        log.debug(f"[news_kr] RSS 수집 실패 ({url[:60]}): {e}")

    return articles


def _clean(text: str) -> str:
    """HTML 태그 제거."""
    return re.sub(r"<[^>]+>", "", text).strip()


def _parse_date(date_str: str) -> Optional[datetime]:
    """RSS pubDate 파싱."""
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).replace(tzinfo=None)
        except ValueError:
            pass
    return None


# ─────────────────────────────────────────────────────────────
# 미국 주식 뉴스 (yfinance)
# ─────────────────────────────────────────────────────────────

def _parse_yf_news_item(item: dict) -> dict | None:
    """
    yfinance 버전별 뉴스 항목 파싱.

    - 구버전 (0.x): item["title"], item["link"], item["providerPublishTime"]
    - 신버전 (1.x): item["content"]["title"], item["content"]["canonicalUrl"]["url"]
    두 형식 모두 처리.
    """
    # 신버전: content 키 안에 있는 경우
    content = item.get("content") or {}
    if isinstance(content, dict) and content.get("title"):
        title   = content.get("title", "")
        url_obj = content.get("canonicalUrl") or {}
        url     = url_obj.get("url", "") if isinstance(url_obj, dict) else str(url_obj)
        summary = content.get("summary", "") or content.get("description", "")
        pub_ts  = (content.get("pubDate") or content.get("displayDate") or
                   content.get("providerPublishTime") or "")
    else:
        # 구버전: 최상위에 바로 있는 경우
        title   = item.get("title", "")
        url     = item.get("link", "") or item.get("url", "")
        summary = item.get("summary", "") or item.get("description", "")
        pub_ts  = item.get("providerPublishTime", "")

    if not title:
        return None
    return {
        "headline":  title,
        "url":       url,
        "summary":   str(summary)[:300],
        "published": str(pub_ts),
        "source":    "yahoo_finance",
    }


def fetch_us_news(ticker: str, name: str) -> list[dict]:
    """yfinance로 미국 주식 최근 뉴스 수집 (v0.x / v1.x 모두 호환)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        raw_news = t.news or []

        # raw_news가 dict(신버전)인 경우 list로 변환
        if isinstance(raw_news, dict):
            raw_news = list(raw_news.values())

        articles = []
        for item in raw_news[:30]:
            if not isinstance(item, dict):
                continue
            parsed = _parse_yf_news_item(item)
            if not parsed:
                continue
            # 영어 기사는 영어 키워드로 필터 (한국어 필터 사용 안 함)
            text = (parsed["headline"] + " " + parsed.get("summary", "")).lower()
            if any(ex in text for ex in US_EXCLUDE_KEYWORDS):
                continue
            if not any(kw in text for kw in US_DIVIDEND_KEYWORDS):
                continue
            articles.append(parsed)

        log.info(f"[news_us] {name} ({ticker}): 원본 {len(raw_news)}건 → 필터 후 {len(articles)}건")
        return articles[:10]
    except Exception as e:
        log.warning(f"[news_us] {ticker} 뉴스 수집 실패: {e}")
        return []


if __name__ == "__main__":
    # 테스트
    import urllib.parse
    articles = fetch_naver_news("005930", "삼성전자", days=30)
    print(f"\n삼성전자 관련 뉴스 {len(articles)}건:")
    for a in articles:
        print(f"  - {a['headline']}")

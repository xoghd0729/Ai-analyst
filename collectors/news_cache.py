"""
news_cache.py — 뉴스 이벤트 캐시 + Incremental Update 판단

■ 역할
  1. Event Cache: 이미 처리한 기사 → 다시 EXAONE에 보내지 않음
  2. Incremental Check: 마지막 분석 이후 새 뉴스가 없으면 → 전체 skip

■ 왜 필요한가
  배당 뉴스는 하루에 새 이벤트가 생기는 종목이 많지 않다.
  매번 전체 재분석하면 46종목 × 22초 = ~17분이지만,
  변화 있는 종목만 처리하면 → 평균 실행 5분 이하로 줄어든다.

■ 구현 방식
  - 캐시: JSON 파일 (DB 불필요, 간단)
  - 해시: MD5(제목 + URL) → 12자리
  - TTL: 7일 (오래된 캐시는 자동 정리)
  - Incremental: thesis_history의 마지막 created_at 비교

■ 사용법
  from collectors.news_cache import filter_new_articles, needs_update, cleanup_old_cache
"""

import hashlib
import json
import os
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text

log = logging.getLogger(__name__)

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE_DIR, "data", "news_event_cache.json")
CACHE_TTL_DAYS = 7

engine = create_engine("postgresql://localhost/ai_analyst")


# ─────────────────────────────────────────────────────────────
# Event Cache — 기사 hash 기반 중복 처리 방지
# ─────────────────────────────────────────────────────────────

def _load_cache() -> dict:
    """JSON 캐시 파일 로드. 없으면 빈 딕셔너리 반환."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict):
    """캐시를 JSON 파일에 저장."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _article_hash(headline: str, url: str = "") -> str:
    """
    기사 고유 해시 생성.

    MD5(제목 + URL)의 앞 12자리 사용.
    제목만으로도 충분히 식별 가능하지만 URL도 포함해서 안정성 높임.
    """
    raw = f"{headline.strip()}{url.strip()}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


def filter_new_articles(articles: list) -> tuple[list, int]:
    """
    캐시에 없는 새 기사만 반환 + 새 기사를 캐시에 등록.

    반환: (새 기사 리스트, 스킵된 기사 수)

    ■ 동작
      1. 각 기사의 해시 계산
      2. 캐시에 있으면 → skip (이미 처리됨)
      3. 없으면 → 새 기사 리스트에 추가 + 캐시 등록
    """
    cache = _load_cache()
    now   = datetime.now().isoformat()

    new_articles = []
    skip_count   = 0

    for a in articles:
        h = _article_hash(a.get("headline", ""), a.get("url", ""))
        if h in cache:
            skip_count += 1
        else:
            new_articles.append(a)
            cache[h] = now  # 처리됨으로 등록

    _save_cache(cache)

    if skip_count > 0:
        log.debug(f"[cache] 캐시 히트 {skip_count}건 스킵, 새 기사 {len(new_articles)}건")

    return new_articles, skip_count


def cleanup_old_cache() -> int:
    """
    TTL(7일) 초과 캐시 항목 제거.

    매 배치 시작 시 1회 호출하면 캐시 파일이 무한 증가하지 않음.
    반환: 삭제된 항목 수
    """
    cache   = _load_cache()
    cutoff  = (datetime.now() - timedelta(days=CACHE_TTL_DAYS)).isoformat()
    cleaned = {h: ts for h, ts in cache.items() if ts >= cutoff}
    removed = len(cache) - len(cleaned)
    _save_cache(cleaned)
    if removed > 0:
        log.info(f"[cache] 만료 캐시 {removed}건 정리 완료")
    return removed


# ─────────────────────────────────────────────────────────────
# Incremental Update — 마지막 분석 이후 변화 없으면 skip
# ─────────────────────────────────────────────────────────────

def get_last_thesis_time(stock_code: str) -> datetime | None:
    """
    thesis_history에서 해당 종목의 마지막 분석 시각 조회.

    없으면 None 반환 → 무조건 새로 분석.
    """
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT created_at FROM thesis_history
                WHERE stock_code = :code
                ORDER BY created_at DESC
                LIMIT 1
            """), {"code": stock_code}).fetchone()
        if row:
            ts = row[0]
            # DB 반환값이 이미 datetime이면 그대로, 문자열이면 파싱
            if isinstance(ts, datetime):
                return ts.replace(tzinfo=None)
            return datetime.fromisoformat(str(ts))
    except Exception as e:
        log.debug(f"[cache] last_thesis 조회 실패 ({stock_code}): {e}")
    return None


def needs_update(stock_code: str, new_articles: list,
                 force_after_hours: int = 24) -> tuple[bool, str]:
    """
    이 종목을 다시 분석할 필요가 있는지 판단.

    판단 기준 (하나라도 True면 분석):
      A. 마지막 분석이 force_after_hours(기본 24h) 이전 → 무조건 재분석
      B. 새 기사(캐시에 없던 기사)가 1건 이상 있음 → 재분석
      C. 마지막 분석 기록 없음 → 최초 분석이므로 무조건 실행

    반환: (분석 필요 여부, 이유 설명)
    """
    last_time = get_last_thesis_time(stock_code)

    # Case C: 최초 분석
    if last_time is None:
        return True, "최초 분석"

    hours_since = (datetime.now() - last_time).total_seconds() / 3600

    # Case A: 강제 재분석 주기 초과
    if hours_since >= force_after_hours:
        return True, f"마지막 분석 {hours_since:.0f}h 경과 (기준 {force_after_hours}h)"

    # Case B: 새 기사 있음
    if new_articles:
        return True, f"새 기사 {len(new_articles)}건 감지"

    # 변화 없음 → skip
    return False, f"변화 없음 (마지막 분석 {hours_since:.1f}h 전)"

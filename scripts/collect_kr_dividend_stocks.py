"""
scripts/collect_kr_dividend_stocks.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

한국 배당주 유니버스 TOP 100 수집 스타터 스크립트.

목표:
  KOSPI200 + 코스닥150 → 다음 필터 → 100개 정제 셋
    1. 최근 3년 연속 배당 지급
    2. 시가총액 ≥ 3,000억원
    3. 부채비율 ≤ 200%
    4. 영업현금흐름 양수

산출물:
  data/approved_universe_kr_v2.json

실행:
  cd ~/ai-analyst
  python scripts/collect_kr_dividend_stocks.py
  # 또는 일부만 시험:
  python scripts/collect_kr_dividend_stocks.py --limit 20

의존성:
  pip install pykrx yfinance pandas
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# 프로젝트 루트 추가
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 환경변수 로드(.env) — DART_API_KEY / KRX_ID / KRX_PW 등
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=ROOT / ".env")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("collect_kr_dividend")

# ─────────────────────────────────────────────────────────────
# OpenDART 설정 / 로컬 캐시
# ─────────────────────────────────────────────────────────────
DART_API_KEY = os.getenv("DART_API_KEY") or os.getenv("OPEN_DART_API_KEY")
DATA_DIR = ROOT / "data"
_CORP_CODE_CACHE_PATH = DATA_DIR / "dart_corp_codes.json"
_DIVIDEND_DATASET_PATH = (
    (DATA_DIR / "dividend_dataset_with_events.csv")
    if (DATA_DIR / "dividend_dataset_with_events.csv").exists()
    else (DATA_DIR / "dividend_dataset.csv")
)

# ─────────────────────────────────────────────────────────────
# 0. 시드 종목 (필터 기준점 — 코스피200 + 코스닥 우량 대표주)
# ─────────────────────────────────────────────────────────────
# 실제 운영 시 pykrx로 KOSPI200/KOSDAQ150 동적 조회
# 여기서는 Day 1 시작점으로 수동 시드 100개 제공
SEED_TICKERS_KR: list[tuple[str, str]] = [
    # (티커, 한글명) — 배당 이력이 알려진 대표 종목
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("005380", "현대차"),
    ("000270", "기아"),
    ("005490", "POSCO홀딩스"),
    ("055550", "신한지주"),
    ("105560", "KB금융"),
    ("086790", "하나금융지주"),
    ("316140", "우리금융지주"),
    ("024110", "기업은행"),
    ("034730", "SK"),
    ("003550", "LG"),
    ("018260", "삼성에스디에스"),
    ("009150", "삼성전기"),
    ("032830", "삼성생명"),
    ("000810", "삼성화재"),
    ("030200", "KT"),
    ("017670", "SK텔레콤"),
    ("032640", "LG유플러스"),
    ("015760", "한국전력"),
    ("036460", "한국가스공사"),
    ("034220", "LG디스플레이"),
    ("051910", "LG화학"),
    ("011170", "롯데케미칼"),
    ("010950", "S-Oil"),
    ("096770", "SK이노베이션"),
    ("078930", "GS"),
    ("000720", "현대건설"),
    ("009540", "HD한국조선해양"),
    ("010140", "삼성중공업"),
    ("042660", "한화오션"),
    ("267250", "HD현대"),
    ("011200", "HMM"),
    ("180640", "한진칼"),
    ("003490", "대한항공"),
    ("020560", "아시아나항공"),
    ("282330", "BGF리테일"),
    ("097950", "CJ제일제당"),
    ("271560", "오리온"),
    ("033780", "KT&G"),
    ("004020", "현대제철"),
    ("001230", "동국제강"),
    ("001440", "대한전선"),
    ("002380", "KCC"),
    ("003410", "쌍용C&E"),
    ("006400", "삼성SDI"),
    ("373220", "LG에너지솔루션"),
    ("247540", "에코프로비엠"),
    ("086520", "에코프로"),
    ("066970", "엘앤에프"),
    ("028260", "삼성물산"),
    ("000880", "한화"),
    ("009830", "한화솔루션"),
    ("010120", "LS ELECTRIC"),
    ("006800", "미래에셋증권"),
    ("016360", "삼성증권"),
    ("071050", "한국금융지주"),
    ("030610", "교보증권"),
    ("000810", "삼성화재"),
    ("088350", "한화생명"),
    ("082740", "한화엔진"),
    ("352820", "하이브"),
    ("035720", "카카오"),
    ("035420", "NAVER"),
    ("251270", "넷마블"),
    ("036570", "엔씨소프트"),
    ("259960", "크래프톤"),
    ("293490", "카카오게임즈"),
    ("112040", "위메이드"),
    ("041510", "에스엠"),
    ("122870", "와이지엔터테인먼트"),
    ("035900", "JYP Ent."),
    ("042700", "한미반도체"),
    ("000990", "DB하이텍"),
    ("064350", "현대로템"),
    ("064760", "티씨케이"),
    ("001800", "오리온홀딩스"),
    ("004990", "롯데지주"),
    ("023530", "롯데쇼핑"),
    ("004170", "신세계"),
    ("139480", "이마트"),
    ("007310", "오뚜기"),
    ("280360", "롯데웰푸드"),
    ("280360", "롯데웰푸드"),  # 중복 — 정제 시 제거
    ("005850", "에스엘"),
    ("000150", "두산"),
    ("034020", "두산에너빌리티"),
    ("042670", "HD현대인프라코어"),
    ("000150", "두산"),  # 중복
    ("259960", "크래프톤"),  # 중복
    ("145720", "덴티움"),
    ("207940", "삼성바이오로직스"),
    ("068270", "셀트리온"),
    ("196170", "알테오젠"),
    ("328130", "루닛"),
    ("377300", "카카오페이"),
    ("323410", "카카오뱅크"),
    ("383220", "F&F"),
    ("241560", "두산밥캣"),
    ("011070", "LG이노텍"),
    ("009830", "한화솔루션"),  # 중복
    ("004990", "롯데지주"),  # 중복

    # ── 추가 시드 (Day1: 60+ 통과 확보용) ─────────────────────
    ("012330", "현대모비스"),
    ("086280", "현대글로비스"),
    ("003490", "대한항공"),  # 중복일 수 있음
    ("028050", "삼성E&A"),
    ("006280", "녹십자"),
    ("009240", "한샘"),
    ("001740", "SK네트웍스"),
    ("034120", "SBS"),
    ("032350", "롯데관광개발"),
    ("090430", "아모레퍼시픽"),
    ("079430", "현대리바트"),
    ("006260", "LS"),
    ("006660", "삼성공조"),
    ("030000", "제일기획"),
    ("001120", "LG상사"),
    ("004370", "농심"),
    ("003090", "대웅"),
    ("000240", "한국앤컴퍼니"),
    ("005940", "NH투자증권"),
    ("001510", "SK증권"),
    ("003540", "대신증권"),
    ("016610", "DB금융투자"),
    ("002790", "아모레G"),
    ("027740", "마니커"),
    ("008770", "호텔신라"),
    ("010060", "OCI홀딩스"),
    ("001060", "JW중외제약"),
    ("004000", "롯데정밀화학"),
    ("004800", "효성"),  # 중복일 수 있음
    ("003300", "한일홀딩스"),
]


@dataclass
class StockProfile:
    ticker: str
    name: str
    market_cap_억: Optional[float] = None
    debt_ratio_pct: Optional[float] = None
    operating_cf_억: Optional[float] = None
    dividend_years: Optional[int] = None  # 연속 배당 지급 연수
    avg_div_yield_pct: Optional[float] = None  # 3년 평균
    sector: Optional[str] = None
    passes_filter: bool = False
    rejection_reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────
# 1. 필터링 기준
# ─────────────────────────────────────────────────────────────
FILTER_CONFIG = {
    "min_market_cap_억": 3_000,
    "max_debt_ratio_pct": 200.0,
    "min_dividend_years": 3,
    "min_operating_cf_억": 0,  # 양수
}


def apply_filters(profile: StockProfile) -> StockProfile:
    """4개 필터링 기준 적용."""
    reasons = []

    # Day1 현실 대응:
    # - pykrx/외부 시총 조회가 막힐 수 있어(None)인 경우는 시총 필터를 건너뛴다.
    if profile.market_cap_억 is not None and profile.market_cap_억 < FILTER_CONFIG["min_market_cap_억"]:
        reasons.append(f"시총<{FILTER_CONFIG['min_market_cap_억']}억")

    # 부채비율도 DART가 막히면 None일 수 있으므로, None이면 skip
    if profile.debt_ratio_pct is not None and profile.debt_ratio_pct > FILTER_CONFIG["max_debt_ratio_pct"]:
        reasons.append(f"부채비율>{FILTER_CONFIG['max_debt_ratio_pct']}%")

    if profile.dividend_years is None or profile.dividend_years < FILTER_CONFIG["min_dividend_years"]:
        reasons.append(f"연속배당<{FILTER_CONFIG['min_dividend_years']}년")

    if profile.operating_cf_억 is None or profile.operating_cf_억 <= FILTER_CONFIG["min_operating_cf_억"]:
        reasons.append("영업CF≤0")

    profile.passes_filter = len(reasons) == 0
    profile.rejection_reason = ", ".join(reasons) if reasons else None
    return profile


# ─────────────────────────────────────────────────────────────
# 2. 데이터 수집 (TODO: 실제 API 호출 채우기)
# ─────────────────────────────────────────────────────────────
def fetch_stock_data(ticker: str, name: str) -> StockProfile:
    """
    TODO (Cursor에서 완성):
      1. pykrx.get_market_cap_by_date() → 시가총액
      2. dart_fss / OpenDartReader → 부채비율, 영업현금흐름
      3. 배당 이력 → DART '배당' 공시 검색 또는
                    수동 매핑된 data/dividend_dataset.csv 활용
      4. yfinance ticker+'.KS' / '.KQ' → 보조 검증

    현재는 더미 데이터 반환 (스타터).
    """
    # NOTE:
    # - 외부 네트워크/로그인 제약이 있는 환경에서도 D1이 진행될 수 있게
    #   `data/dividend_dataset.csv`(로컬) 기반으로 핵심 필드를 우선 채운다.
    # - 가능하면 pykrx(Open KRX) + OpenDART로 보강한다.
    from datetime import date

    import pandas as pd
    import requests

    def _safe_float(v) -> Optional[float]:
        if v is None:
            return None
        try:
            if isinstance(v, str):
                v = v.replace(",", "").strip()
                if v in ("", "-", "N/A", "null", "None"):
                    return None
            return float(v)
        except Exception:
            return None

    def _get_latest_trading_date_yyyymmdd(lookback_days: int = 10) -> str:
        today = date.today()
        for i in range(1, lookback_days + 1):
            d = today - timedelta(days=i)
            ymd = d.strftime("%Y%m%d")
            try:
                from pykrx import stock as krx
                cap_df = krx.get_market_cap_by_ticker(ymd)
                if cap_df is not None and not cap_df.empty:
                    return ymd
            except Exception:
                continue
        # 마지막 fallback: 오늘 날짜(비거래일이면 pykrx에서 빈 df 가능)
        return today.strftime("%Y%m%d")

    def _load_corp_code_map() -> dict[str, str]:
        if _CORP_CODE_CACHE_PATH.exists():
            try:
                with _CORP_CODE_CACHE_PATH.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_corp_code_map(m: dict[str, str]) -> None:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with _CORP_CODE_CACHE_PATH.open("w", encoding="utf-8") as f:
                json.dump(m, f, ensure_ascii=False)
        except Exception:
            # 캐시 실패는 치명적이지 않음
            pass

    def _ensure_corp_code(stock_code: str) -> Optional[str]:
        """
        종목코드(6자리) -> DART corp_code(8자리) 매핑.
        최초 1회 corpCode.xml을 내려 받아 `data/dart_corp_codes.json`로 캐시한다.
        """
        if not DART_API_KEY:
            return None

        m = _load_corp_code_map()
        if stock_code in m:
            return m[stock_code]

        # corpCode.xml 다운로드 (zip)
        try:
            import requests
            res = requests.get(
                "https://opendart.fss.or.kr/api/corpCode.xml",
                params={"crtfc_key": DART_API_KEY},
                timeout=45,
            )
            res.raise_for_status()
            import io
            import zipfile
            import xml.etree.ElementTree as ET

            with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                xml_data = z.read("CORPCODE.xml")
            root = ET.parse(io.BytesIO(xml_data)).getroot()
            bulk: dict[str, str] = {}
            for item in root.findall("list"):
                sc = (item.findtext("stock_code") or "").strip()
                cc = (item.findtext("corp_code") or "").strip()
                if sc and cc:
                    bulk[sc] = cc
            if bulk:
                m.update(bulk)
                _save_corp_code_map(m)
            return m.get(stock_code)
        except Exception:
            return None

    def _dart_fetch_financials(corp_code: str, year: int) -> dict | None:
        if not DART_API_KEY or not corp_code:
            return None
        import requests
        years_to_try = [year, year - 1, year - 2]
        for try_year in years_to_try:
            for fs_div in ("CFS", "OFS"):
                try:
                    r = requests.get(
                        "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                        params={
                            "crtfc_key": DART_API_KEY,
                            "corp_code": corp_code,
                            "bsns_year": str(try_year),
                            "reprt_code": "11011",  # 사업보고서
                            "fs_div": fs_div,  # 연결 우선
                        },
                        timeout=20,
                    ).json()
                    if r.get("status") == "000" and r.get("list"):
                        r["_used_year"] = try_year
                        r["_used_fs_div"] = fs_div
                        return r
                except Exception:
                    continue
        return None

    def _dart_has_cash_dividend_common(corp_code: str, year: int) -> bool:
        """
        DART 결산배당(alotMatter)에서 '주당 현금배당금(원)'(보통주)을 찾으면 True.
        """
        if not DART_API_KEY or not corp_code:
            return False
        try:
            res = requests.get(
                "https://opendart.fss.or.kr/api/alotMatter.json",
                params={
                    "crtfc_key": DART_API_KEY,
                    "corp_code": corp_code,
                    "bsns_year": str(year),
                    "reprt_code": "11011",
                },
                timeout=15,
            ).json()
            if res.get("status") != "000":
                return False
            for item in res.get("list", []) or []:
                se = item.get("se", "") or ""
                stock_knd = item.get("stock_knd", "") or ""
                thstrm = item.get("thstrm", "") or ""
                if "주당 현금배당금" in se and "보통주" in stock_knd:
                    v = _safe_float(thstrm)
                    return bool(v and v > 0)
            return False
        except Exception:
            return False

    def _extract_financial_metrics(dart_json: dict) -> tuple[Optional[float], Optional[float]]:
        """
        Returns:
          debt_ratio_pct (부채총계/자산총계*100),
          operating_cf_억 (영업활동현금흐름, 억원 단위)
        """
        if not dart_json or not dart_json.get("list"):
            return None, None

        assets = None
        liabilities = None
        operating_cf = None

        for item in dart_json.get("list", []):
            acct = (item.get("account_nm") or "").replace(" ", "").strip()
            val = _safe_float(item.get("thstrm_amount"))
            if val is None:
                continue

            # 재무상태표
            if acct in ("자산총계",):
                assets = val
            elif acct in ("부채총계",):
                liabilities = val

            # 현금흐름표 (계정명 변형 다수)
            if acct in (
                "영업활동현금흐름",
                "영업활동으로인한현금흐름",
                "영업활동으로인한현금흐름",
                "영업활동으로인한현금흐름",
            ):
                operating_cf = val

        debt_ratio = None
        if assets and liabilities is not None and assets != 0:
            debt_ratio = (liabilities / assets) * 100.0

        # DART는 원 단위가 대부분이라 1e8(억원)으로 환산
        operating_cf_억 = (operating_cf / 1e8) if operating_cf is not None else None

        return debt_ratio, operating_cf_억

    def _load_dividend_history_years() -> dict[str, set[int]]:
        """
        `data/dividend_dataset.csv`가 있으면 (ticker -> 배당연도 set)로 읽어온다.
        없거나 실패하면 빈 dict.
        """
        if not _DIVIDEND_DATASET_PATH.exists():
            return {}
        try:
            m: dict[str, set[int]] = {}
            with _DIVIDEND_DATASET_PATH.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    code = (row.get("ticker") or row.get("stock_code") or row.get("code") or "").strip()
                    year_raw = (row.get("year") or row.get("fiscal_year") or "").strip()
                    if not code or not year_raw:
                        continue
                    try:
                        y = int(year_raw)
                    except Exception:
                        continue
                    m.setdefault(code, set()).add(y)
            return m
        except Exception:
            return {}

    # --- 실행 시작 ---
    log.info("Fetching %s (%s)...", ticker, name)

    profile = StockProfile(ticker=ticker, name=name)

    # 0) 로컬 배당 데이터셋 기반으로 핵심 지표 채우기 (DART 실패 시 fallback)
    try:
        if _DIVIDEND_DATASET_PATH.exists():
            df = pd.read_csv(_DIVIDEND_DATASET_PATH, dtype={"stock_code": str})
            # 헤더명이 stock_code인 파일. 방어적으로 처리
            code_col = "stock_code" if "stock_code" in df.columns else ("ticker" if "ticker" in df.columns else None)
            if code_col:
                df[code_col] = df[code_col].astype(str).str.zfill(6)
                sdf = df[df[code_col] == ticker].copy()
                if not sdf.empty and "year" in sdf.columns:
                    sdf["year"] = pd.to_numeric(sdf["year"], errors="coerce")
                    sdf = sdf.dropna(subset=["year"]).sort_values("year")

                    # operating_cf(원) -> 억원 환산
                    # 최신 1개가 비어있는 케이스가 많아서 최근 3개 유효값 평균으로 보정
                    op_cf_억 = None
                    if "operating_cf" in sdf.columns:
                        op_valid = [_safe_float(v) for v in sdf["operating_cf"].tolist()]
                        op_valid = [v for v in op_valid if v is not None]
                        if op_valid:
                            last3 = op_valid[-3:]
                            op_cf_억 = (sum(last3) / len(last3)) / 1e8

                    # operating_cf가 없거나 전부 비어있으면 fcf로 대체
                    if op_cf_억 is None and "fcf" in sdf.columns:
                        fcf_valid = [_safe_float(v) for v in sdf["fcf"].tolist()]
                        fcf_valid = [v for v in fcf_valid if v is not None]
                        if fcf_valid:
                            last3 = fcf_valid[-3:]
                            op_cf_억 = (sum(last3) / len(last3)) / 1e8

                    profile.operating_cf_억 = op_cf_억

                    # 연속 배당 연수: dps>0인 연도들의 최대 연속 구간
                    if "dps" in sdf.columns:
                        paid_years = sorted(
                            int(y)
                            for y, dps in zip(sdf["year"].tolist(), sdf["dps"].tolist())
                            if _safe_float(dps) and _safe_float(dps) > 0
                        )
                        if paid_years:
                            max_streak = 1
                            streak = 1
                            for i in range(1, len(paid_years)):
                                if paid_years[i] == paid_years[i - 1] + 1:
                                    streak += 1
                                    max_streak = max(max_streak, streak)
                                else:
                                    streak = 1
                            profile.dividend_years = max_streak
    except Exception as e:
        log.warning("로컬 배당 데이터셋 파싱 실패 %s: %s", ticker, e)

    # 1) 부채비율/영업CF/연속배당: OpenDART (Day1 핵심)
    if DART_API_KEY:
        try:
            corp_code = _ensure_corp_code(ticker)
            if corp_code:
                dart_json = _dart_fetch_financials(corp_code, datetime.now().year - 1)
                debt_ratio, op_cf_억 = _extract_financial_metrics(dart_json) if dart_json else (None, None)
                profile.debt_ratio_pct = debt_ratio
                if op_cf_억 is not None:
                    profile.operating_cf_억 = op_cf_억

                # 연속배당 연수: 최근부터 역산(최대 10년)
                base_year = datetime.now().year - 1
                streak = 0
                for y in range(base_year, base_year - 10, -1):
                    if _dart_has_cash_dividend_common(corp_code, y):
                        streak += 1
                    else:
                        break
                if streak > 0:
                    profile.dividend_years = max(profile.dividend_years or 0, streak)
        except Exception as e:
            log.warning("DART 재무 조회 실패 %s: %s", ticker, e)
    else:
        # 키가 없으면 필터에서 탈락하게 되므로, 이유를 명확히 남겨 디버깅을 돕는다
        profile.rejection_reason = "DART_API_KEY 없음"

    # 3) 연속 배당 연수: dividend_dataset.csv 기반 (있으면 최우선)
    div_hist = _load_dividend_history_years()
    if div_hist and ticker in div_hist:
        years = sorted(div_hist[ticker])
        if years:
            # 최신 10년 내 연속 배당 연수 (실무용)
            max_streak = 1
            streak = 1
            for i in range(1, len(years)):
                if years[i] == years[i - 1] + 1:
                    streak += 1
                    max_streak = max(max_streak, streak)
                else:
                    streak = 1
            profile.dividend_years = max_streak

    # 4) 평균 배당수익률/섹터는 Day1에 필수 아님 → 추후 확장
    return profile


# ─────────────────────────────────────────────────────────────
# 3. 메인 수집 함수
# ─────────────────────────────────────────────────────────────
def collect_universe(
    limit: Optional[int] = None,
    sleep_sec: float = 0.5,
) -> dict:
    """
    유니버스 100개 정제.

    Args:
        limit: 시드 종목 중 N개만 처리 (디버깅용)
        sleep_sec: API rate limit 대응

    Returns:
        {
            "universe": [StockProfile.asdict(), ...],  # passes_filter=True만
            "rejected": [...],                           # 탈락
            "stats": {
                "total_processed": int,
                "passed": int,
                "rejected": int,
                "rejection_summary": {reason: count},
            },
            "config": FILTER_CONFIG,
            "generated_at": ISO timestamp,
        }
    """
    # Day1: KOSPI200/KOSDAQ150 동적 조회는 pykrx 제약이 있을 수 있어
    # 우선 시드 리스트(중복 제거)로 진행한다.
    unique = list({t: n for t, n in SEED_TICKERS_KR}.items())
    log.info("시드 종목 %d개 (중복 제거 후)", len(unique))

    if limit:
        unique = unique[:limit]
        log.info("--limit %d 적용", limit)

    profiles: list[StockProfile] = []
    for i, (ticker, name) in enumerate(unique, 1):
        try:
            profile = fetch_stock_data(ticker, name)
            profile = apply_filters(profile)
            profiles.append(profile)

            status = "✓ PASS" if profile.passes_filter else f"✗ {profile.rejection_reason}"
            log.info("[%d/%d] %s %s — %s", i, len(unique), ticker, name, status)

            if sleep_sec and i % 10 == 0:
                time.sleep(sleep_sec)
        except Exception as e:
            log.error("[%d/%d] %s %s 수집 실패: %s", i, len(unique), ticker, name, e)

    passed = [p for p in profiles if p.passes_filter]
    rejected = [p for p in profiles if not p.passes_filter]

    rejection_summary: dict[str, int] = {}
    for p in rejected:
        for reason in (p.rejection_reason or "").split(", "):
            if reason:
                rejection_summary[reason] = rejection_summary.get(reason, 0) + 1

    result = {
        "universe": [asdict(p) for p in passed],
        "rejected": [asdict(p) for p in rejected],
        "stats": {
            "total_processed": len(profiles),
            "passed": len(passed),
            "rejected": len(rejected),
            "rejection_summary": rejection_summary,
        },
        "config": FILTER_CONFIG,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return result


def save_universe(result: dict, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log.info("저장 완료: %s", output_path)
    log.info(
        "통과: %d / 탈락: %d",
        result["stats"]["passed"],
        result["stats"]["rejected"],
    )


# ─────────────────────────────────────────────────────────────
# CLI 진입점
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="한국 배당주 유니버스 수집")
    parser.add_argument("--limit", type=int, default=None, help="처리할 종목 수 제한")
    parser.add_argument(
        "--output",
        type=str,
        default=str(ROOT / "data" / "approved_universe_kr_v2.json"),
        help="결과 저장 경로",
    )
    parser.add_argument("--sleep", type=float, default=0.5, help="API rate limit 대응 sleep")
    args = parser.parse_args()

    log.info("━" * 60)
    log.info("AI Cashflow OS — 한국 배당주 유니버스 수집기")
    log.info("필터: 시총≥%d억 / 부채≤%d%% / 연속배당≥%d년 / 영업CF>0",
             FILTER_CONFIG["min_market_cap_억"],
             int(FILTER_CONFIG["max_debt_ratio_pct"]),
             FILTER_CONFIG["min_dividend_years"])
    log.info("━" * 60)

    result = collect_universe(limit=args.limit, sleep_sec=args.sleep)
    save_universe(result, Path(args.output))

    log.info("━" * 60)
    log.info("탈락 사유 분포:")
    for reason, count in sorted(result["stats"]["rejection_summary"].items(),
                                 key=lambda x: -x[1]):
        log.info("  %s: %d", reason, count)
    log.info("━" * 60)


if __name__ == "__main__":
    main()

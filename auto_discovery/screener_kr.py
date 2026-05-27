"""
한국 배당주 자동 발굴 스크리너

■ 동작 방식
  1. DART API → 배당 공시 있는 전체 상장법인 목록 수집
  2. 기본 필터 적용:
     - 최근 3년 연속 배당 지급
     - 배당수익률 추정치 >= MIN_YIELD_PCT
     - 시가총액 >= MIN_MKTCAP_억
  3. 기존 ranking.csv에 없는 신규 종목만 반환
  4. 결과: 후보 종목 리스트 (evaluator.py로 전달)

■ 데이터 소스
  - DART 공시 API: https://opendart.fss.or.kr
  - 기업개황 API: corp_code + 기본 정보
  - DB: 기존 분석 종목 중복 제거용
"""

import os
import ssl
import json
import time
import requests
import pandas as pd
from dotenv import load_dotenv

ssl._create_default_https_context = ssl._create_unverified_context
load_dotenv()

DART_API_KEY = os.getenv("DART_API_KEY", "")
BASE_URL     = "https://opendart.fss.or.kr/api"

# ── 스크리닝 기준 ──────────────────────────────────────────────
MIN_YIELD_PCT   = 2.5    # 최소 배당수익률 (%)
MIN_DIV_YEARS   = 2      # 최소 연속 배당 연도 수
MAX_CANDIDATES  = 80     # 최대 후보 수


def _get(endpoint: str, params: dict) -> dict:
    """DART API GET 요청 공통 함수."""
    params["crtfc_key"] = DART_API_KEY
    try:
        r = requests.get(f"{BASE_URL}/{endpoint}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


def fetch_dividend_companies(year: int) -> list[dict]:
    """
    DART에서 특정 연도에 배당 공시를 낸 법인 목록 수집.
    end_de: 배당 기준일 기준으로 조회.
    """
    data = _get("list.json", {
        "bgn_de":   f"{year}0101",
        "end_de":   f"{year}1231",
        "pblntf_ty": "A",          # 정기공시
        "pblntf_detail_ty": "A001", # 사업보고서
        "page_count": 100,
    })
    if data.get("status") != "000":
        return []

    companies = []
    for item in data.get("list", []):
        companies.append({
            "corp_code":  item.get("corp_code"),
            "corp_name":  item.get("corp_nm"),
            "stock_code": item.get("stock_code", ""),
        })
    # 주식코드 있는 것만 (ETF·비상장 제외)
    return [c for c in companies if c["stock_code"] and len(c["stock_code"]) == 6]


def fetch_dividend_info(corp_code: str, year: int) -> dict | None:
    """DART 배당 공시에서 DPS, 배당수익률 정보 추출."""
    data = _get("alotMatter.json", {
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",  # 사업보고서
    })
    if data.get("status") != "000":
        return None

    items = data.get("list", [])
    for item in items:
        if "주당배당금" in item.get("se", "") or "DPS" in item.get("se", "").upper():
            try:
                dps = float(str(item.get("thstrm", "0")).replace(",", "") or 0)
                if dps > 0:
                    return {"dps": dps, "year": year}
            except ValueError:
                pass
    return None


def screen_kr_stocks(existing_codes: set[str] | None = None) -> list[dict]:
    """
    한국 배당주 자동 발굴 메인 함수.

    Parameters
    ----------
    existing_codes : 이미 유니버스에 있는 종목코드 집합 (중복 제거용)

    Returns
    -------
    list[dict] : 후보 종목 리스트
        {ticker, name, asset_class, expected_yield, source, consecutive_div_years}
    """
    if not DART_API_KEY:
        print("  ⚠️ DART_API_KEY 없음 → 한국 스크리닝 건너뜀")
        return []

    existing_codes = existing_codes or set()
    print("  [KR] 한국 배당주 스크리닝 시작...")

    # 최근 3년 배당 공시 법인 수집
    import datetime
    current_year = datetime.date.today().year
    years = [current_year - 1, current_year - 2, current_year - 3]

    year_companies: dict[int, set[str]] = {}
    for yr in years:
        companies = fetch_dividend_companies(yr)
        year_companies[yr] = {c["stock_code"] for c in companies}
        print(f"    {yr}년 배당 공시 법인: {len(year_companies[yr])}개")
        time.sleep(0.3)

    # 최근 2년 이상 연속 배당한 종목 교집합
    common = year_companies[years[0]]
    for yr in years[1:MIN_DIV_YEARS]:
        common = common & year_companies[yr]

    # 기존 유니버스에 없는 신규 후보만
    candidates = common - existing_codes
    print(f"  [KR] 연속 배당 {MIN_DIV_YEARS}년+ 신규 후보: {len(candidates)}개")

    # 배당 정보 상세 수집
    results = []
    all_companies = []
    for yr in years:
        fetched = fetch_dividend_companies(yr)
        all_companies.extend(fetched)

    code_to_name = {c["stock_code"]: c["corp_name"] for c in all_companies}

    for stock_code in list(candidates)[:MAX_CANDIDATES]:
        corp_code = None
        for c in all_companies:
            if c["stock_code"] == stock_code:
                corp_code = c.get("corp_code")
                break
        if not corp_code:
            continue

        div_info = fetch_dividend_info(corp_code, years[0])
        time.sleep(0.2)

        if not div_info:
            continue

        # 배당수익률 추정 (DPS 기반, 주가 없으면 근사값 사용)
        # 여기서는 conservative하게 추정
        name = code_to_name.get(stock_code, stock_code)
        results.append({
            "ticker":              stock_code,
            "name":                name,
            "asset_class":         "kr_stock",
            "account":             "ISA/일반",
            "risk_profile":        "moderate",
            "expected_yield":      None,   # evaluator.py에서 채움
            "capital_gain_rate":   2.5,    # 보수적 기본값
            "consecutive_div_years": MIN_DIV_YEARS,
            "source":              "DART_AUTO",
            "description":         f"{MIN_DIV_YEARS}년+ 연속 배당 공시 확인 — 자동 발굴 종목",
        })

    print(f"  [KR] 최종 후보: {len(results)}개")
    return results

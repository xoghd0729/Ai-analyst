import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import zipfile
import xml.etree.ElementTree as ET
import io
import requests, os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
engine  = create_engine("postgresql://localhost/ai_analyst")

# ─────────────────────────────────────────────────────────────
# 0. 종목코드 → DART corp_code 변환
#    우선순위: ① 세션 캐시 → ② DB corp_code_map → ③ corpCode.xml 다운로드
# ─────────────────────────────────────────────────────────────

_corp_code_cache: dict[str, str] = {}   # 세션 내 메모리 캐시


def resolve_corp_code(stock_code: str, fallback_corp_code: str | None = None) -> str | None:
    """
    종목코드(예: "033780") → DART corp_code(8자리) 변환.
    ① 세션 캐시 → ② DB corp_code_map 조회 (init_corp_codes.py 실행 후 사용 가능)
    → ③ corpCode.xml 실시간 다운로드 → ④ fallback
    """
    # ① 세션 캐시
    if stock_code in _corp_code_cache:
        return _corp_code_cache[stock_code]

    # ② DB corp_code_map 조회 (init_corp_codes.py가 실행된 경우)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT corp_code, corp_name FROM corp_code_map
                WHERE stock_code = :sc
            """), {"sc": stock_code}).fetchone()
        if row and row[0]:
            _corp_code_cache[stock_code] = row[0]
            print(f"  corp_code: {row[1]} ({stock_code}) → {row[0]}")
            return row[0]
    except Exception:
        pass   # corp_code_map 테이블 없으면 ③으로

    # ③ corpCode.xml 실시간 다운로드 (DB 없을 때 fallback)
    print("📥 DART corp_code 마스터 다운로드 중 (최초 1회)...")
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": API_KEY},
            timeout=30,
        )
        with zipfile.ZipFile(io.BytesIO(res.content)) as z:
            xml_data = z.read("CORPCODE.xml")

        root = ET.parse(io.BytesIO(xml_data)).getroot()
        bulk = {}
        for item in root.findall("list"):
            sc = (item.findtext("stock_code") or "").strip()
            cc = (item.findtext("corp_code")  or "").strip()
            if sc and cc:
                bulk[sc] = cc

        _corp_code_cache.update(bulk)
        print(f"  ✅ {len(bulk)}개 상장사 corp_code 로드")

        if stock_code in _corp_code_cache:
            return _corp_code_cache[stock_code]

    except Exception as e:
        print(f"  ⚠️ corpCode.xml 다운로드 실패: {e}")

    # ④ fallback
    if fallback_corp_code:
        _corp_code_cache[stock_code] = fallback_corp_code
        print(f"  corp_code fallback: {fallback_corp_code}")
        return fallback_corp_code

    return None

# ─────────────────────────────────────────────────────────────
# 1. 재무제표 수집
#    시도 순서: (최신연도, CFS) → (최신연도, OFS) → (이전연도, CFS) → (이전연도, OFS) ...
# ─────────────────────────────────────────────────────────────

TARGET = {
    # 손익계산서
    "매출액":                      "revenue",
    "영업이익":                    "op_income",
    "당기순이익":                  "net_income",
    # 현금흐름표 (FCF 계산용)
    "영업활동현금흐름":            "operating_cf",
    "영업활동으로인한현금흐름":    "operating_cf",
    "영업활동으로 인한 현금흐름":  "operating_cf",
    "유형자산의취득":              "capex",
    "유형자산취득":                "capex",
    "유형자산의 취득":             "capex",
    # 배당금 지급
    "배당금의지급":                "dividends_paid",
    "배당금지급":                  "dividends_paid",
    "배당금 지급":                 "dividends_paid",
    "배당금의 지급":               "dividends_paid",
}

def _fetch_financials(corp_code: str, year: str, fs_div: str) -> dict | None:
    """단일 (연도, 재무제표 구분) 조합으로 DART 조회. 성공하면 dict 반환, 실패하면 None."""
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
            params={
                "crtfc_key":  API_KEY,
                "corp_code":  corp_code,
                "bsns_year":  year,
                "reprt_code": "11011",   # 사업보고서
                "fs_div":     fs_div,    # CFS=연결, OFS=개별
            },
            timeout=15,
        ).json()

        if res.get("status") == "000" and res.get("list"):
            return res
        else:
            msg = res.get("message", "응답 없음")
            print(f"    {year}년/{fs_div}: {msg}")
            return None
    except Exception as e:
        print(f"    {year}년/{fs_div} 요청 오류: {e}")
        return None

def collect_financials(corp_code: str, stock_code: str, year: str):
    """
    DART 재무제표 수집.
    시도 순서: (year, CFS) → (year, OFS) → (year-1, CFS) → (year-1, OFS) → (year-2, ...)
    corp_code를 DART API로 재확인 후 사용.
    """
    # ── corp_code 자동 재확인 ──
    verified = resolve_corp_code(stock_code, fallback_corp_code=corp_code)
    if not verified:
        print("⚠️  corp_code 확인 실패 — 재무 수집 중단")
        return
    corp_code = verified

    # ── 시도 순서 생성 ──
    years_to_try = [year] + [str(int(year) - i) for i in range(1, 3)]
    res, used_year, used_fs = None, year, "CFS"

    for try_year in years_to_try:
        for fs in ("CFS", "OFS"):   # 연결 우선, 실패하면 개별
            res = _fetch_financials(corp_code, try_year, fs)
            if res:
                used_year, used_fs = try_year, fs
                label = "연결" if fs == "CFS" else "개별"
                if try_year != year or fs != "CFS":
                    print(f"  ↩️  {try_year}년 {label}재무제표 사용")
                break
        if res:
            break

    if not res:
        print(f"⚠️  DART 재무데이터 없음 (시도: {', '.join(years_to_try)} × CFS/OFS)")
        return

    # ── 계정명 → metric 저장 ──
    saved        = []
    seen_metrics = set()

    with engine.connect() as conn:
        for item in res.get("list", []):
            acct_raw = item.get("account_nm", "")
            acct     = acct_raw.replace(" ", "")
            metric   = TARGET.get(acct) or TARGET.get(acct_raw)
            if not metric or metric in seen_metrics:
                continue
            try:
                raw   = item.get("thstrm_amount", "").replace(",", "").strip()
                if not raw:
                    continue
                value = float(raw)
                conn.execute(text("""
                    INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
                    VALUES (:code, :date, :metric, :value)
                    ON CONFLICT (stock_code, date, metric_name)
                    DO UPDATE SET value = EXCLUDED.value
                """), {
                    "code":   stock_code,
                    "date":   f"{used_year}-12-31",
                    "metric": metric,
                    "value":  value,
                })
                seen_metrics.add(metric)
                saved.append(f"{metric}={value:,.0f}")
            except (ValueError, TypeError):
                continue
        conn.commit()

    if saved:
        print(f"✅ {stock_code} 재무데이터 저장 ({used_year}/{used_fs}): {', '.join(saved)}")
    else:
        print(f"⚠️  재무데이터 파싱 실패 — 계정명이 TARGET과 불일치할 수 있음")
        # 디버깅용: 실제 수신된 계정명 출력
        accts = [item.get("account_nm", "") for item in res.get("list", [])[:15]]
        print(f"    수신된 계정명 샘플: {accts}")

# ─────────────────────────────────────────────────────────────
# 2. 주당배당금 (DPS) 수집
# ─────────────────────────────────────────────────────────────

def get_dividend_per_share(corp_code: str, year: str, stock_code: str | None = None) -> float | None:
    """
    DART 결산배당 공시에서 주당배당금(DPS) 수집.
    corp_code 자동 재확인 + year fallback.
    """
    if stock_code:
        corp_code = resolve_corp_code(stock_code, fallback_corp_code=corp_code) or corp_code

    years_to_try = [year] + [str(int(year) - i) for i in range(1, 3)]

    for try_year in years_to_try:
        try:
            res = requests.get(
                "https://opendart.fss.or.kr/api/alotMatter.json",
                params={
                    "crtfc_key":  API_KEY,
                    "corp_code":  corp_code,
                    "bsns_year":  try_year,
                    "reprt_code": "11011",
                },
                timeout=10,
            ).json()

            if res.get("status") != "000":
                continue
            for item in res.get("list", []):
                if "보통주" in item.get("se", "") and item.get("dps"):
                    dps = item["dps"].replace(",", "").strip()
                    if dps:
                        return float(dps)
        except Exception:
            pass
    return None
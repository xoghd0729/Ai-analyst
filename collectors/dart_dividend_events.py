"""
dart_dividend_events.py — DART 배당 공시 이벤트 수집기

■ 기존 dart.py 와의 차이
  기존 (dart.py):         재무제표 API → 연간 FCF·OCF·배당금지급 등 집계값
  이것 (dart_dividend_events.py): 공시 검색 API → 배당결정 이벤트 날짜 + DPS 변화

■ 왜 공시 이벤트가 유용한가
  재무제표 확정:  3월 사업보고서 제출 시점
  배당결정 공시:  12월~2월 이사회/주총 결의 직후 (2~3개월 먼저!)
  → "내년 배당 삭감 예고"를 공시 날짜 기준으로 바로 알 수 있음
  → dps_announced (공시 DPS) vs dps_prior_year → 감소율 계산 → WEAKENING 신호

■ 사용하는 DART API
  1. list.json         — 회사별 공시 목록 검색 (날짜·제목·접수번호)
  2. alotMatter.json   — 사업보고서 주주총회 의결사항에서 DPS 파싱
  3. corpCode.xml      — corp_code 매핑 (dart.py의 resolve_corp_code 재사용)

■ 저장 테이블: dividend_events
  stock_code, corp_code, rcept_dt, rcept_no, report_nm,
  fiscal_year, dps_common, dps_prior, dps_change_pct,
  dividend_type (결산/중간/분기), raw_json

■ 주요 출력 함수
  collect_dividend_events(stock_codes, years_back=5)
      → 여러 종목의 배당 공시 이벤트를 수집해 DB에 저장
  get_dps_event_features(stock_code)
      → ML 피처용 요약 반환: 최근 DPS 변화율, 삭감 이력 등
  build_event_feature_dataset(dividend_dataset_path)
      → dividend_dataset.csv와 병합해 이벤트 피처 추가
"""

import os
import json
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# dart.py 의 resolve_corp_code 재사용
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from collectors.dart import resolve_corp_code, parse_number

load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
engine  = create_engine("postgresql://localhost/ai_analyst")

# ─────────────────────────────────────────────────────────────
# 0. 테이블 초기화
# ─────────────────────────────────────────────────────────────

def init_table():
    """dividend_events 테이블이 없으면 생성."""
    ddl = """
    CREATE TABLE IF NOT EXISTS dividend_events (
        id           SERIAL PRIMARY KEY,
        stock_code   VARCHAR(10)  NOT NULL,
        corp_code    VARCHAR(10),
        rcept_dt     DATE,                   -- 공시 접수일 (배당결정 발표 날짜)
        rcept_no     VARCHAR(20)  UNIQUE,    -- DART 공시 접수번호 (중복 방지)
        report_nm    TEXT,                   -- 공시 제목 (예: "현금ㆍ현물배당결정")
        fiscal_year  INT,                    -- 배당 대상 회계연도 (2024 등)
        dps_common   NUMERIC(12,2),          -- 보통주 주당 배당금 (이번 공시)
        dps_prior    NUMERIC(12,2),          -- 직전연도 보통주 DPS (비교용)
        dps_change_pct NUMERIC(8,2),         -- DPS 변화율 % ((이번-직전)/직전 × 100)
        dividend_type  VARCHAR(20),          -- 결산 / 중간 / 분기
        raw_json     TEXT,                   -- 원본 JSON (디버깅용)
        created_at   TIMESTAMP DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_div_evt_stock_year
        ON dividend_events (stock_code, fiscal_year);
    """
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
    print("✅ dividend_events 테이블 준비 완료")


# ─────────────────────────────────────────────────────────────
# 1. DART 공시 목록 검색 (list.json)
# ─────────────────────────────────────────────────────────────

# 배당 관련 공시 제목 키워드
DIVIDEND_KEYWORDS = [
    "배당결정", "현금ㆍ현물배당결정", "현금·현물배당결정",
    "현금배당", "중간배당", "분기배당",
    "주요사항보고서(배당결정)", "주요사항보고서(현금",
]

def _is_dividend_report(report_nm: str) -> str | None:
    """
    공시 제목에서 배당 유형을 판단.
    반환: "결산" | "중간" | "분기" | None(무관)
    """
    nm = report_nm.replace(" ", "")
    if "중간배당" in nm:
        return "중간"
    if "분기배당" in nm:
        return "분기"
    for kw in DIVIDEND_KEYWORDS:
        if kw.replace(" ", "") in nm:
            return "결산"
    return None


def search_dividend_disclosures(corp_code: str, bgn_de: str, end_de: str,
                                debug: bool = False) -> list[dict]:
    """
    DART list.json API로 특정 기간의 배당 관련 공시를 검색.

    Parameters
    ----------
    corp_code : str  — DART 8자리 기업 코드
    bgn_de    : str  — 시작일 "YYYYMMDD"
    end_de    : str  — 종료일 "YYYYMMDD"
    debug     : bool — True면 원본 응답 샘플 출력

    Returns
    -------
    list of dict — [{"rcept_no", "rcept_dt", "report_nm", "dividend_type"}, ...]

    ■ 왜 pblntf_ty 필터를 쓰지 않는가
      - B(주요사항보고)만 쓰면 삼성전자 분기배당 등 일부가 누락됨
      - A(정기공시)에도 배당 관련 공시가 포함되는 경우 있음
      - 필터 없이 전체 조회 후 report_nm 키워드로 직접 거름
      - 단, 대기업은 연간 공시가 수백건 → 페이지네이션 필수
    """
    results = []
    PAGE_SIZE = 100   # DART 최대값

    # pblntf_ty 없이 전체 공시 조회 → 키워드 필터링
    # 페이지네이션: total_count 초과 시 반복
    page_no = 1
    while True:
        try:
            res = requests.get(
                "https://opendart.fss.or.kr/api/list.json",
                params={
                    "crtfc_key":  API_KEY,
                    "corp_code":  corp_code,
                    "bgn_de":     bgn_de,
                    "end_de":     end_de,
                    "page_no":    page_no,
                    "page_count": PAGE_SIZE,
                },
                timeout=15,
            ).json()
        except Exception as e:
            print(f"    list.json 오류 (p{page_no}): {e}")
            break

        status = res.get("status", "")
        if status != "000":
            if debug:
                print(f"    [DEBUG] status={status} msg={res.get('message')} (p{page_no})")
            break

        items = res.get("list", [])
        total_count = int(res.get("total_count", 0))

        if debug and page_no == 1:
            print(f"    [DEBUG] 총 {total_count}건 | 1p 샘플:")
            for item in items[:5]:
                print(f"      {item.get('rcept_dt')} | {item.get('report_nm')}")

        for item in items:
            report_nm = item.get("report_nm", "")
            div_type  = _is_dividend_report(report_nm)
            if not div_type:
                continue
            results.append({
                "rcept_no":      item.get("rcept_no", ""),
                "rcept_dt":      item.get("rcept_dt", ""),
                "report_nm":     report_nm,
                "dividend_type": div_type,
            })

        # 다음 페이지 여부 판단
        if page_no * PAGE_SIZE >= total_count:
            break
        page_no += 1
        time.sleep(0.2)  # 페이지 간 딜레이

    # 중복 제거 (rcept_no 기준)
    seen = set()
    unique = []
    for r in results:
        if r["rcept_no"] not in seen:
            seen.add(r["rcept_no"])
            unique.append(r)

    return unique


# ─────────────────────────────────────────────────────────────
# 2. DPS 파싱
#    우선순위: ① cshDvdndInfoDetail (rcept_no 직접 조회)
#              ② alotMatter (연간 사업보고서 — 연결 배당 확인용 fallback)
# ─────────────────────────────────────────────────────────────

def fetch_dps_from_alot(corp_code: str, bsns_year: str) -> dict:
    """
    DART alotMatter.json — 사업보고서 주주총회 의결사항에서 연간 DPS 파싱.

    ■ 실제 응답 구조 (확인된 필드명)
      se        = "주당 현금배당금(원)"   ← 이 행에서 DPS를 읽음
      stock_knd = "보통주"               ← 보통주 여부 판별 (se가 아님!)
      thstrm    = "1,444"               ← 당기(이번 연도) DPS 금액
      frmtrm    = "1,444"               ← 전기 DPS (참고용)

    ■ 흔한 실수
      - se 에서 "보통주" 를 찾으면 안 됨 → stock_knd 에서 찾아야 함
      - dps 필드가 없음 → thstrm 을 써야 함

    Returns
    -------
    {"dps_common": float | None, "source": str}
    """
    # 사업보고서(11011) → 반기(11012) → 3분기(11014) → 1분기(11013) 순으로 시도
    for reprt_code in ("11011", "11012", "11014", "11013"):
        try:
            res = requests.get(
                "https://opendart.fss.or.kr/api/alotMatter.json",
                params={
                    "crtfc_key":  API_KEY,
                    "corp_code":  corp_code,
                    "bsns_year":  bsns_year,
                    "reprt_code": reprt_code,
                },
                timeout=10,
            ).json()
        except Exception:
            continue

        if res.get("status") != "000":
            continue

        for item in res.get("list", []):
            se        = item.get("se",        "")
            stock_knd = item.get("stock_knd", "")
            if "주당 현금배당금" in se and "보통주" in stock_knd:
                val = parse_number(item.get("thstrm", ""))
                if val and val > 0:
                    return {"dps_common": val, "source": f"alot-{reprt_code}"}

    return {"dps_common": None, "source": "alot"}


def _parse_fiscal_year_and_type(report_nm: str, rcept_dt: str, initial_type: str) -> tuple[int, str]:
    """
    공시 제목·접수일로 회계연도 및 배당 유형 최종 확정.

    ■ 삼성전자 등 분기배당 기업의 경우
      - 제목이 "현금ㆍ현물배당결정"이어도 7월/10월 접수면 분기배당임
      - 분기배당은 1월·4월·7월·10월 말~익월 초에 공시됨

    Returns (fiscal_year: int, dividend_type: str)
    """
    try:
        dt = datetime.strptime(rcept_dt, "%Y%m%d")
    except ValueError:
        return datetime.now().year - 1, initial_type

    m = dt.month

    # 제목에 명시된 유형 우선
    nm = report_nm.replace(" ", "")
    if "중간배당" in nm:
        return dt.year, "중간"
    if "분기배당" in nm:
        return dt.year, "분기"

    # 제목에 명시 없으면 접수 월로 유형 추정
    # 한국 결산배당: 12월 결산 → 이듬해 1~4월 공시
    # 분기배당: 4월(1Q), 7월(2Q), 10월(3Q) 공시 패턴
    if m in (1, 2, 3):          # 1~3월: 전년 결산배당
        return dt.year - 1, "결산"
    elif m == 4:                 # 4월: 결산배당(주총 결의) or 1Q분기
        return dt.year - 1, "결산"   # 보수적으로 결산 처리
    elif m in (5, 6):
        return dt.year, "중간"
    elif m in (7, 8, 9):
        return dt.year, "분기"
    elif m in (10, 11):
        return dt.year, "분기"
    else:                        # 12월: 결산 미리 결의
        return dt.year, "결산"


# ─────────────────────────────────────────────────────────────
# 3. 단일 종목 이벤트 수집 & DB 저장
# ─────────────────────────────────────────────────────────────

def _upsert_event(row: dict):
    """단일 배당 이벤트를 dividend_events 테이블에 저장(중복 무시)."""
    sql = text("""
        INSERT INTO dividend_events
            (stock_code, corp_code, rcept_dt, rcept_no, report_nm,
             fiscal_year, dps_common, dps_prior, dps_change_pct,
             dividend_type, raw_json)
        VALUES
            (:stock_code, :corp_code, :rcept_dt, :rcept_no, :report_nm,
             :fiscal_year, :dps_common, :dps_prior, :dps_change_pct,
             :dividend_type, :raw_json)
        ON CONFLICT (rcept_no) DO UPDATE SET
            dps_common      = EXCLUDED.dps_common,
            dps_prior       = EXCLUDED.dps_prior,
            dps_change_pct  = EXCLUDED.dps_change_pct,
            raw_json        = EXCLUDED.raw_json
    """)
    with engine.connect() as conn:
        conn.execute(sql, row)
        conn.commit()


def collect_one_stock(stock_code: str, years_back: int = 6, debug: bool = False) -> list[dict]:
    """
    단일 종목의 배당 공시 이벤트 수집.

    1. resolve_corp_code → DART corp_code 획득
    2. list.json로 years_back년치 배당 공시 검색
    3. 각 공시에 대해 alotMatter.json으로 DPS 파싱
    4. 직전 이벤트와 DPS 비교 → dps_change_pct 계산
    5. dividend_events 테이블에 upsert

    Returns
    -------
    list of event dicts (저장된 것들)
    """
    corp_code = resolve_corp_code(stock_code)
    if not corp_code:
        print(f"  ⚠️  {stock_code}: corp_code 없음, 건너뜀")
        return []

    end_de   = datetime.now().strftime("%Y%m%d")
    bgn_de   = (datetime.now() - timedelta(days=365 * years_back)).strftime("%Y%m%d")

    disclosures = search_dividend_disclosures(corp_code, bgn_de, end_de, debug=debug)
    if not disclosures:
        print(f"  ℹ️  {stock_code}: 배당 공시 없음 ({bgn_de}~{end_de})")
        return []

    print(f"  📋 {stock_code}: 배당 공시 {len(disclosures)}건 발견")

    # 날짜 오름차순 정렬 → DPS 변화 계산을 위해
    disclosures.sort(key=lambda x: x["rcept_dt"])

    saved_events = []
    # 연도별 결산 DPS 누적 (분기배당 기업: 4번 합산 → 연간 DPS)
    year_dps_sum: dict[int, float] = {}   # {fiscal_year: 누적DPS}
    prev_annual_dps: float | None = None  # 직전 완성된 연도의 연간 DPS

    for disc in disclosures:
        rcept_no  = disc["rcept_no"]
        rcept_dt  = disc["rcept_dt"]   # "YYYYMMDD"
        report_nm = disc["report_nm"]
        init_type = disc["dividend_type"]

        # 회계연도 + 배당 유형 최종 확정
        fiscal_year, div_type = _parse_fiscal_year_and_type(report_nm, rcept_dt, init_type)

        # ── DPS 파싱: alotMatter.json (연간 사업보고서 기준) ──
        # 분기·중간 배당은 연간 합계로 나중에 집계하므로 여기서도 alotMatter 시도
        time.sleep(0.25)  # DART API rate limit 방어
        dps_info   = fetch_dps_from_alot(corp_code, str(fiscal_year))
        dps_common = dps_info["dps_common"]

        # ── 연간 DPS 누적 & 변화율 계산 ──
        dps_change_pct: float | None = None
        if dps_common is not None:
            year_dps_sum[fiscal_year] = year_dps_sum.get(fiscal_year, 0) + dps_common

        # rcept_dt → DATE 형식 변환
        try:
            rcept_dt_date = datetime.strptime(rcept_dt, "%Y%m%d").date()
        except ValueError:
            rcept_dt_date = None

        event_row = {
            "stock_code":     stock_code,
            "corp_code":      corp_code,
            "rcept_dt":       rcept_dt_date,
            "rcept_no":       rcept_no,
            "report_nm":      report_nm,
            "fiscal_year":    fiscal_year,
            "dps_common":     dps_common,
            "dps_prior":      None,      # 후처리에서 채움
            "dps_change_pct": None,      # 후처리에서 채움
            "dividend_type":  div_type,
            "raw_json":       json.dumps(disc, ensure_ascii=False),
        }

        try:
            _upsert_event(event_row)
            saved_events.append(event_row)

            # 로그
            dps_str = f"DPS={dps_common:.0f}원" if dps_common is not None else "DPS=미파싱"
            print(f"    [{fiscal_year}] {div_type} | {rcept_dt} | {dps_str}")

        except Exception as e:
            print(f"    DB 저장 실패 ({rcept_no}): {e}")

    # ── 연간 DPS 누적값으로 변화율 후처리 업데이트 ──
    if year_dps_sum:
        sorted_years = sorted(year_dps_sum.keys())
        for i, yr in enumerate(sorted_years):
            annual_dps = year_dps_sum[yr]
            prior_dps  = year_dps_sum.get(sorted_years[i - 1]) if i > 0 else None
            chg        = None
            if prior_dps and prior_dps > 0:
                chg = round((annual_dps - prior_dps) / prior_dps * 100, 2)
            # 해당 연도의 마지막(최신) 공시에 연간 합계 반영
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE dividend_events
                    SET    dps_prior       = :prior,
                           dps_change_pct = :chg
                    WHERE  stock_code  = :sc
                      AND  fiscal_year = :yr
                      AND  rcept_dt    = (
                          SELECT MAX(rcept_dt) FROM dividend_events
                          WHERE stock_code = :sc AND fiscal_year = :yr
                      )
                """), {"prior": prior_dps, "chg": chg, "sc": stock_code, "yr": yr})
                conn.commit()
            chg_str = f"  연간합계={annual_dps:.0f}원 (전년比 {chg:+.1f}%)" if chg else f"  연간합계={annual_dps:.0f}원"
            print(f"  ✅ {yr}년 연간DPS{chg_str}")

    return saved_events


# ─────────────────────────────────────────────────────────────
# 4. 배치 수집 (여러 종목)
# ─────────────────────────────────────────────────────────────

def collect_dividend_events(stock_codes: list[str], years_back: int = 6, debug: bool = False):
    """
    여러 종목의 배당 공시 이벤트를 수집해 DB에 저장.

    Parameters
    ----------
    stock_codes : list[str] — 종목코드 리스트 (예: ["005930", "000810"])
    years_back  : int       — 몇 년치 과거 공시까지 수집할지 (기본 6년)

    사용 예
    -------
    from collectors.dart_dividend_events import collect_dividend_events
    collect_dividend_events(["005930", "000810", "017670"], years_back=6)
    """
    init_table()

    total = len(stock_codes)
    print(f"\n{'='*55}")
    print(f"  DART 배당 공시 이벤트 수집 — {total}개 종목, {years_back}년치")
    print(f"{'='*55}")

    all_events = []
    for i, sc in enumerate(stock_codes, 1):
        print(f"\n[{i}/{total}] {sc}")
        events = collect_one_stock(sc, years_back=years_back, debug=debug)
        all_events.extend(events)
        time.sleep(0.5)   # 종목 간 딜레이

    print(f"\n{'='*55}")
    print(f"  수집 완료: 총 {len(all_events)}건 이벤트 저장")
    print(f"{'='*55}")
    return all_events


# ─────────────────────────────────────────────────────────────
# 5. ML 피처 생성 함수
# ─────────────────────────────────────────────────────────────

def get_dps_event_features(stock_code: str, as_of_year: int | None = None) -> dict:
    """
    dividend_events 테이블에서 종목별 피처 추출.

    Parameters
    ----------
    stock_code  : str
    as_of_year  : int | None — 기준 연도 (None이면 가장 최근 데이터 사용)
                               leakage 방지: as_of_year=2023이면 2023년 이전 공시만 사용

    Returns
    -------
    dict with keys:
        evt_dps_latest          : 가장 최근 결산 DPS (원)
        evt_dps_change_pct      : 가장 최근 결산 DPS 변화율 (%)
        evt_consecutive_cuts    : 연속 삭감 횟수 (최근 N년 기준)
        evt_has_cut_3y          : 최근 3년 내 삭감 이력 (0/1)
        evt_has_interim         : 중간/분기 배당 있는지 (0/1)
        evt_years_since_cut     : 마지막 삭감 이후 경과 연도 (없으면 999)
    """
    # as_of_year 필터: leakage 방지
    year_filter = ""
    params = {"sc": stock_code}
    if as_of_year:
        year_filter = "AND fiscal_year < :aoy"
        params["aoy"] = as_of_year

    sql = text(f"""
        SELECT fiscal_year, dps_common, dps_change_pct, dividend_type
        FROM   dividend_events
        WHERE  stock_code = :sc
               AND dividend_type = '결산'
               {year_filter}
        ORDER  BY fiscal_year DESC
        LIMIT  10
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception:
        return _empty_event_features()

    if not rows:
        return _empty_event_features()

    df = pd.DataFrame(rows, columns=["fiscal_year", "dps_common", "dps_change_pct", "dividend_type"])

    # 최신 DPS 및 변화율
    latest = df.iloc[0]
    evt_dps_latest     = float(latest["dps_common"]) if pd.notna(latest["dps_common"]) else None
    evt_dps_change_pct = float(latest["dps_change_pct"]) if pd.notna(latest["dps_change_pct"]) else None

    # 삭감 이력 (dps_change_pct < 0)
    cuts = df[df["dps_change_pct"].notna() & (df["dps_change_pct"] < 0)]

    # 최근 3년 내 삭감
    current_year = as_of_year if as_of_year else df["fiscal_year"].max()
    recent_cuts  = cuts[cuts["fiscal_year"] >= current_year - 3]
    evt_has_cut_3y = 1 if len(recent_cuts) > 0 else 0

    # 마지막 삭감 이후 경과 연도
    evt_years_since_cut = 999
    if len(cuts) > 0:
        last_cut_year       = int(cuts["fiscal_year"].max())
        evt_years_since_cut = current_year - last_cut_year

    # 연속 삭감 횟수 (최신부터 역순)
    evt_consecutive_cuts = 0
    for _, row in df.iterrows():
        if pd.notna(row["dps_change_pct"]) and row["dps_change_pct"] < 0:
            evt_consecutive_cuts += 1
        else:
            break

    # 중간/분기 배당 여부
    sql_interim = text("""
        SELECT COUNT(*) FROM dividend_events
        WHERE  stock_code = :sc AND dividend_type IN ('중간','분기')
    """)
    with engine.connect() as conn:
        interim_cnt = conn.execute(sql_interim, {"sc": stock_code}).scalar() or 0
    evt_has_interim = 1 if interim_cnt > 0 else 0

    return {
        "evt_dps_latest":       evt_dps_latest,
        "evt_dps_change_pct":   evt_dps_change_pct,
        "evt_consecutive_cuts": evt_consecutive_cuts,
        "evt_has_cut_3y":       evt_has_cut_3y,
        "evt_has_interim":      evt_has_interim,
        "evt_years_since_cut":  evt_years_since_cut,
    }


def _empty_event_features() -> dict:
    return {
        "evt_dps_latest":       None,
        "evt_dps_change_pct":   None,
        "evt_consecutive_cuts": 0,
        "evt_has_cut_3y":       0,
        "evt_has_interim":      0,
        "evt_years_since_cut":  999,
    }


# ─────────────────────────────────────────────────────────────
# 6. dividend_dataset.csv 와 이벤트 피처 병합
# ─────────────────────────────────────────────────────────────

def build_event_feature_dataset(
    dividend_dataset_path: str,
    output_path: str | None = None,
) -> pd.DataFrame:
    """
    기존 dividend_dataset.csv 에 배당 공시 이벤트 피처를 추가.

    leakage 방지: 각 행의 year를 as_of_year로 전달
    → "해당 연도 이전" 공시 데이터만 피처로 사용

    Parameters
    ----------
    dividend_dataset_path : str — dividend_dataset.csv 경로
    output_path           : str | None — 저장 경로 (None이면 저장 안 함)

    Returns
    -------
    pd.DataFrame — 이벤트 피처가 추가된 데이터셋
    """
    df = pd.read_csv(dividend_dataset_path)
    print(f"기존 데이터셋: {len(df)}행 × {len(df.columns)}열")

    feat_cols = list(_empty_event_features().keys())
    for col in feat_cols:
        df[col] = None

    stock_codes = df["stock_code"].unique()
    print(f"종목 {len(stock_codes)}개에 대해 이벤트 피처 생성 중...")

    for i, sc in enumerate(stock_codes, 1):
        mask = df["stock_code"] == sc
        years = df.loc[mask, "year"].unique()
        for yr in years:
            feats = get_dps_event_features(str(sc).zfill(6), as_of_year=int(yr))
            for col, val in feats.items():
                df.loc[mask & (df["year"] == yr), col] = val

        if i % 10 == 0:
            print(f"  {i}/{len(stock_codes)} 처리 완료")

    print(f"이벤트 피처 추가 완료: {df.shape}")

    if output_path:
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"저장: {output_path}")

    return df


# ─────────────────────────────────────────────────────────────
# 7. 간단 요약 뷰 (수집 결과 확인용)
# ─────────────────────────────────────────────────────────────

def print_event_summary(stock_codes: list[str] | None = None):
    """
    수집된 배당 이벤트 현황 출력.
    stock_codes=None이면 전체 요약.
    """
    if stock_codes:
        sql = text("""
            SELECT stock_code, fiscal_year, dps_common, dps_change_pct, dividend_type, rcept_dt
            FROM   dividend_events
            WHERE  stock_code = ANY(:codes)
            ORDER  BY stock_code, fiscal_year
        """)
        params = {"codes": stock_codes}
    else:
        sql = text("""
            SELECT stock_code, COUNT(*) as n_events,
                   MIN(fiscal_year) as first_yr, MAX(fiscal_year) as last_yr,
                   SUM(CASE WHEN dps_change_pct < 0 THEN 1 ELSE 0 END) as n_cuts
            FROM   dividend_events
            WHERE  dividend_type = '결산'
            GROUP  BY stock_code
            ORDER  BY n_cuts DESC, last_yr DESC
        """)
        params = {}

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        print(f"조회 실패: {e}")
        return

    if not rows:
        print("수집된 이벤트 없음")
        return

    if stock_codes:
        print(f"\n{'종목':<10} {'연도':>6} {'DPS':>8} {'변화율':>8} {'유형':<6} {'공시일'}")
        print("-" * 55)
        for r in rows:
            chg = f"{r[3]:+.1f}%" if r[3] is not None else "   N/A"
            dps = f"{r[2]:.0f}원"  if r[2] is not None else "    -"
            print(f"{r[0]:<10} {r[1]:>6} {dps:>8} {chg:>8} {r[4]:<6} {r[5]}")
    else:
        print(f"\n{'종목':<10} {'이벤트':>6} {'첫해':>6} {'최근':>6} {'삭감횟수':>8}")
        print("-" * 40)
        for r in rows:
            print(f"{r[0]:<10} {r[1]:>6} {r[2]:>6} {r[3]:>6} {r[4]:>8}")


# ─────────────────────────────────────────────────────────────
# 8. 단독 실행 진입점
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DART 배당 공시 이벤트 수집")
    parser.add_argument("--codes",   nargs="+", help="종목코드 리스트 (예: 005930 000810)")
    parser.add_argument("--from-ranking", action="store_true", help="data/ranking.csv 에서 종목 읽기")
    parser.add_argument("--years",   type=int, default=6, help="수집 연도 범위 (기본 6년)")
    parser.add_argument("--summary", action="store_true", help="수집 결과 요약만 출력")
    parser.add_argument("--build-features", action="store_true",
                        help="dividend_dataset.csv에 이벤트 피처 추가 후 저장")
    parser.add_argument("--debug", action="store_true",
                        help="DART API 원본 응답 샘플 출력 (수집 0건 원인 파악용)")
    args = parser.parse_args()

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if args.summary:
        print_event_summary()

    elif args.build_features:
        dataset_path = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
        output_path  = os.path.join(BASE_DIR, "data", "dividend_dataset_with_events.csv")
        build_event_feature_dataset(dataset_path, output_path)

    else:
        # 종목 코드 결정
        if args.from_ranking:
            ranking_path = os.path.join(BASE_DIR, "data", "ranking.csv")
            ranking_df   = pd.read_csv(ranking_path)
            # 한국 종목만 (stock_code가 숫자 6자리인 것만) — 미국 티커 제외
            kr_codes = [
                str(sc).zfill(6)
                for sc in ranking_df["stock_code"].tolist()
                if str(sc).isdigit()
            ]
            stock_codes = kr_codes
            print(f"ranking.csv에서 한국 종목 {len(stock_codes)}개 로드 (미국 티커 제외)")
        elif args.codes:
            stock_codes = [str(sc).zfill(6) for sc in args.codes]
        else:
            # 기본: 소규모 테스트 (삼성전자, KT&G, 삼성화재)
            stock_codes = ["005930", "033780", "000810"]
            print("기본 테스트 종목 사용: 삼성전자, KT&G, 삼성화재")

        collect_dividend_events(stock_codes, years_back=args.years, debug=args.debug)
        print("\n[수집 후 요약]")
        print_event_summary(stock_codes)

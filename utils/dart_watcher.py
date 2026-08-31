"""
utils/dart_watcher.py
=====================
DART 신규 공시 실시간 감지 + 증분 업데이트.

목적:
  build_dataset.py가 "연도 단위 전체 수집"이라면,
  dart_watcher.py는 "오늘 새로 올라온 사업보고서/분기보고서만 빠르게 감지"한다.

동작 방식:
  1. DART getList API → bgn_de=마지막감지일 로 신규 공시 목록 조회
  2. 우리 유니버스(STOCKS) 종목 공시만 필터
  3. 신규 공시 종목의 재무 데이터를 build_dataset.py의 함수 재사용해 수집
  4. dividend_dataset.csv에 병합 (중복 제거)
  5. 감지 시각을 data/dart_watcher_state.json에 저장

APScheduler 연동 (api/main.py):
  CronTrigger(hour=6)  -- 매일 오전 6시 실행
  사업보고서(A001) + 반기보고서(A002) + 분기보고서(A003) 대상

왜 rcpNo 기반이 아니라 날짜 기반인가:
  - 날짜 기반: bgn_de 이후 공시를 전부 스캔 → 구현 단순
  - rcpNo 기반: 마지막 받은 rcpNo 이후만 → 순서 보장이 필요, DART API가
    rcpNo 순서를 100% 보장하지 않음 (정정 공시 등)
  - 결론: 날짜 기반이 더 안전하고 구현이 단순
"""
from __future__ import annotations
import os, json, logging, time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_CSV = os.path.join(BASE, "data", "dividend_dataset.csv")
STATE_PATH  = os.path.join(BASE, "data", "dart_watcher_state.json")

# DART 공시 유형: 사업보고서(A001), 반기보고서(A002), 분기보고서(A003)
TARGET_REPORT_TYPES = {"A001", "A002", "A003"}

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"


# ─────────────────────────────────────────────────────────────────
# 1. 상태 관리 (마지막 감지 시각)
# ─────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    # 초기 상태: 오늘부터 30일 전
    default_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    return {"last_checked": default_date, "processed_rcpnos": []}


def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────
# 2. DART 신규 공시 목록 조회
# ─────────────────────────────────────────────────────────────────

def _fetch_dart_list(api_key: str, bgn_de: str, end_de: str) -> list[dict]:
    """
    DART getList API 호출.
    bgn_de ~ end_de 기간의 정기보고서 목록 반환.
    """
    params = {
        "crtfc_key": api_key,
        "bgn_de":    bgn_de,
        "end_de":    end_de,
        "pblntf_ty": "A",    # 정기공시 (사업/반기/분기 보고서)
        "page_no":   1,
        "page_count": 100,
    }
    try:
        resp = requests.get(DART_LIST_URL, params=params, timeout=15)
        data = resp.json()
        if data.get("status") != "000":
            log.warning("DART getList 오류: %s", data.get("message"))
            return []
        return data.get("list", [])
    except Exception as e:
        log.error("DART getList 실패: %s", e)
        return []


# ─────────────────────────────────────────────────────────────────
# 3. 유니버스 종목 필터
# ─────────────────────────────────────────────────────────────────

def _get_universe_corp_codes() -> dict[str, str]:
    """
    dividend_dataset.csv 또는 build_dataset.py에서 corp_code → stock_code 매핑.
    DB 연결 없이 작동하도록 파일 폴백 우선.
    """
    # 1순위: dividend_dataset.csv에서 stock_code 목록 직접 사용
    # DART getList 결과에서 corp_code가 아닌 corp_name 매핑은 별도 처리 필요 →
    # 여기서는 corp_code를 알아야 하므로 DART corp_code XML 사용
    corp_code_xml = os.path.join(BASE, "data", "CORPCODE.xml")
    if os.path.exists(corp_code_xml) and os.path.exists(DATASET_CSV):
        try:
            import xml.etree.ElementTree as ET
            import pandas as pd
            tree = ET.parse(corp_code_xml)
            root = tree.getroot()

            # dividend_dataset.csv의 stock_code 목록
            df = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
            our_codes = set(df["stock_code"].str.zfill(6).unique())

            mapping = {}
            for item in root.findall("list"):
                code  = item.findtext("corp_code", "")
                stock = item.findtext("stock_code", "").zfill(6) if item.findtext("stock_code") else ""
                if stock and stock in our_codes:
                    mapping[code] = stock
            log.info("CORPCODE.xml에서 %d개 매핑 로드", len(mapping))
            return mapping
        except Exception as e:
            log.warning("CORPCODE.xml 파싱 실패: %s", e)

    # 2순위: dividend_dataset.csv stock_code 목록 직접 사용 (corp_code 없이)
    # → DART 결과 필터링 불가, 전체 정기보고서 처리 후 우리 universe와 교차
    if os.path.exists(DATASET_CSV):
        try:
            import pandas as pd
            df = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
            our_codes = set(df["stock_code"].str.zfill(6).unique())
            # corp_code를 모르므로 빈 dict 반환, check_new_disclosures에서 stock_code로 교차 처리
            log.info("유니버스 %d개 종목 (CORPCODE.xml 없어 corp_code 매핑 불가)", len(our_codes))
            return {}
        except Exception as e:
            log.warning("dividend_dataset.csv 로드 실패: %s", e)

    log.warning("유니버스 로드 실패 → 모든 공시 처리")
    return {}   # 빈 dict = 유니버스 필터 없이 전체 처리


# ─────────────────────────────────────────────────────────────────
# 4. 신규 공시 처리
# ─────────────────────────────────────────────────────────────────

def _update_dataset_for_stock(stock_code: str, year: int) -> int:
    """
    단일 종목의 특정 연도 데이터를 수집해서 dividend_dataset.csv에 병합.
    이미 같은 stock_code + year가 있으면 업데이트.
    Returns: 추가/업데이트된 행 수
    """
    try:
        import sys
        sys.path.insert(0, BASE)
        from build_dataset import (
            STOCKS, load_corp_codes, resolve_corp_code,
            collect_stock_history, label_dividend_cuts,
        )
        load_corp_codes()

        # stock_code로 STOCKS에서 종목 정보 찾기
        stock = next(
            (s for s in STOCKS if str(s["stock_code"]).zfill(6) == stock_code),
            None,
        )
        if stock is None:
            log.info("유니버스에 없는 종목: %s", stock_code)
            return 0

        # 해당 연도 데이터 수집
        rows = collect_stock_history(stock, year, year)
        if not rows:
            log.info("[%s] %d년 데이터 없음", stock_code, year)
            return 0

        new_df = pd.DataFrame(rows)
        new_df = label_dividend_cuts(new_df)

        # 기존 CSV와 병합 (중복 제거)
        if os.path.exists(DATASET_CSV):
            existing = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
            existing["stock_code"] = existing["stock_code"].astype(str).str.zfill(6)
            # 같은 stock_code + year는 신규 데이터로 교체
            mask = ~(
                (existing["stock_code"] == stock_code) &
                (existing["year"].astype(int) == year)
            )
            merged = pd.concat([existing[mask], new_df], ignore_index=True)
        else:
            merged = new_df

        merged.sort_values(["stock_code", "year"], inplace=True)
        merged.to_csv(DATASET_CSV, index=False, encoding="utf-8-sig")
        log.info("[%s] %d년 데이터 업데이트 완료 (%d행)", stock_code, year, len(new_df))
        return len(new_df)

    except Exception as e:
        log.error("[%s] 업데이트 실패: %s", stock_code, e)
        return 0


# ─────────────────────────────────────────────────────────────────
# 5. 메인 감지 함수
# ─────────────────────────────────────────────────────────────────

def check_new_disclosures(
    api_key: Optional[str] = None,
    lookback_days: int = 1,
) -> dict:
    """
    DART 신규 공시 감지 + 증분 업데이트.

    Args:
        api_key:       DART OpenAPI 키 (없으면 환경변수 DART_API_KEY)
        lookback_days: 마지막 감지 후 최소 재조회 기간 (기본 1일)

    Returns:
        {
            "new_filings":   int,   # 감지된 신규 공시 수
            "updated_codes": list,  # 업데이트된 종목 코드
            "checked_at":    str,   # 감지 시각
            "bgn_de":        str,   # 조회 시작일
        }
    """
    if api_key is None:
        api_key = os.getenv("DART_API_KEY", "")
    if not api_key:
        log.warning("DART_API_KEY 없음 → 감지 건너뜀")
        return {"new_filings": 0, "updated_codes": [], "checked_at": "", "bgn_de": ""}

    state    = _load_state()
    bgn_de   = state.get("last_checked", "")
    end_de   = datetime.now().strftime("%Y%m%d")
    done_nos = set(state.get("processed_rcpnos", []))

    if not bgn_de:
        bgn_de = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

    log.info("DART 공시 감지: %s ~ %s", bgn_de, end_de)

    # 공시 목록 조회
    filings = _fetch_dart_list(api_key, bgn_de, end_de)
    # 정기보고서만 (A001/A002/A003)
    filings = [f for f in filings
               if f.get("pblntf_ty") in TARGET_REPORT_TYPES
               and f.get("rcpNo") not in done_nos]

    if not filings:
        log.info("신규 공시 없음")
        state["last_checked"] = end_de
        _save_state(state)
        return {"new_filings": 0, "updated_codes": [], "checked_at": end_de, "bgn_de": bgn_de}

    # 유니버스 corp_code → stock_code 매핑
    universe = _get_universe_corp_codes()

    updated_codes = []
    new_rcpnos    = []

    for filing in filings:
        corp_code = filing.get("corp_code", "")
        rcpno     = filing.get("rcpNo", "")
        rcept_dt  = filing.get("rcept_dt", "")  # 공시일자 YYYYMMDD

        # 유니버스 종목인지 확인
        stock_code = universe.get(corp_code)
        if not stock_code:
            new_rcpnos.append(rcpno)  # 처리 완료로 마킹 (건너뜀)
            continue

        # 공시 연도 추출
        try:
            year = int(rcept_dt[:4]) if rcept_dt else datetime.now().year
        except ValueError:
            year = datetime.now().year

        log.info("신규 공시 감지: %s (%s) %d년", stock_code, filing.get("corp_name", ""), year)

        # 데이터 업데이트
        updated = _update_dataset_for_stock(stock_code, year)
        if updated > 0 and stock_code not in updated_codes:
            updated_codes.append(stock_code)

        new_rcpnos.append(rcpno)
        time.sleep(0.5)  # DART API rate limit

    # 상태 저장
    done_nos.update(new_rcpnos)
    # 처리된 rcpNo는 최근 500개만 유지 (메모리 관리)
    state["processed_rcpnos"] = list(done_nos)[-500:]
    state["last_checked"] = end_de
    _save_state(state)

    result = {
        "new_filings":   len(filings),
        "updated_codes": updated_codes,
        "checked_at":    end_de,
        "bgn_de":        bgn_de,
    }
    log.info("DART 감지 완료: 신규 %d건, 업데이트 %d종목",
             len(filings), len(updated_codes))
    return result


# ─────────────────────────────────────────────────────────────────
# 6. APScheduler 훅 (api/main.py에서 호출)
# ─────────────────────────────────────────────────────────────────

def scheduled_dart_watch():
    """
    APScheduler CronTrigger(hour=6)으로 호출되는 진입점.
    매일 오전 6시 DART 신규 공시 감지 + 증분 업데이트.
    """
    log.info("=== DART 신규 공시 감지 시작 (APScheduler) ===")
    result = check_new_disclosures()
    if result["updated_codes"]:
        log.info("업데이트 완료: %s", result["updated_codes"])
        # XGBoost 재스코어링 트리거 (필요 시)
        try:
            from utils.data_pipeline import update_kr_yields
            update_kr_yields(to_db=True, to_file=True)
            log.info("KR yield 업데이트 완료")
        except Exception as e:
            log.warning("KR yield 업데이트 실패: %s", e)
    return result


# ── CLI 테스트 ────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    api_key = os.getenv("DART_API_KEY", "")
    if not api_key:
        print("DART_API_KEY 환경변수를 설정하세요.")
        sys.exit(1)

    result = check_new_disclosures(api_key, lookback_days=1)
    print(f"\n감지 결과:")
    print(f"  신규 공시: {result['new_filings']}건")
    print(f"  업데이트 종목: {result['updated_codes']}")
    print(f"  조회 기간: {result['bgn_de']} ~ {result['checked_at']}")

"""
dart_incremental.py
====================
DART 데이터 증분 업데이트.

전체 재수집(build_dataset.py) 대신 마지막 수집 연도 이후 데이터만 수집해
dividend_dataset.csv에 append한다.

실행:
  python scripts/dart_incremental.py               # 증분 업데이트
  python scripts/dart_incremental.py --full        # 강제 전체 재수집
  python scripts/dart_incremental.py --ticker 005930  # 특정 종목만

설계 결정:
  - rcpNo 기반이 아닌 연도(bsns_year) 기반: DART 재무제표 API가 연도 단위로 조회되므로
    rcpNo 추적보다 max_year 추적이 더 단순하고 실패 복구가 쉬움
  - append-only: 기존 데이터 덮어쓰지 않음. 동일 (stock_code, year) 중복 시 나중 것 유지
  - checkpoint: 중단 시 재개 가능 (processed 종목 추적)
"""
from __future__ import annotations
import sys, os, json, time, logging, argparse
from datetime import datetime
import pandas as pd

# build_dataset.py의 함수 재사용
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from build_dataset import (
    collect_stock_history,
    resolve_corp_code,
    fetch_financials_one_year,
    fetch_dps,
)

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

DATASET_CSV   = os.path.join(BASE, "data", "dividend_dataset.csv")
CHECKPOINT    = os.path.join(BASE, "data", "dart_checkpoint.json")
RANKING_CSV   = os.path.join(BASE, "data", "ranking.csv")
CURRENT_YEAR  = datetime.now().year - 1   # 직전 사업연도 기준 (DART 결산)


# ─────────────────────────────────────────────────────────────
# 1. 기존 데이터 파악
# ─────────────────────────────────────────────────────────────

def get_last_collected_years() -> dict[str, int]:
    """
    dividend_dataset.csv에서 ticker(stock_code)별 최대 수집 연도 반환.
    파일 없으면 빈 dict.
    """
    if not os.path.exists(DATASET_CSV):
        return {}
    df = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(6)
    return df.groupby("stock_code")["year"].max().to_dict()


UNIVERSE_CSV  = os.path.join(BASE, "data", "training_universe_expanded.csv")


def get_target_stocks() -> list[dict]:
    """
    수집 대상 종목 로드.
    우선순위:
      1. dividend_dataset.csv에 이미 있는 종목 (최신화 대상)
      2. training_universe_expanded.csv (확장 유니버스 신규 편입)
      3. ranking.csv (fallback)
    """
    # 1. 이미 수집된 종목 (최신화 우선)
    if os.path.exists(DATASET_CSV):
        df = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        existing = df[["stock_code", "name"]].drop_duplicates()
        stocks = existing.to_dict("records")
    # 2. 확장 유니버스 (신규 편입)
    elif os.path.exists(UNIVERSE_CSV):
        df = pd.read_csv(UNIVERSE_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        stocks = df[["stock_code", "name"]].drop_duplicates().to_dict("records")
    # 3. ranking.csv fallback
    elif os.path.exists(RANKING_CSV):
        df = pd.read_csv(RANKING_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        if "overall_score" in df.columns:
            df = df[pd.to_numeric(df["overall_score"], errors="coerce").fillna(0) >= 25]
        stocks = df[["stock_code", "name"]].drop_duplicates().to_dict("records")
    else:
        log.error("종목 소스 파일 없음")
        return []
    return [{"stock_code": s["stock_code"], "name": s["name"]} for s in stocks]


# ─────────────────────────────────────────────────────────────
# 2. Checkpoint 관리
# ─────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT):
        try:
            with open(CHECKPOINT) as f:
                return json.load(f)
        except Exception:
            pass
    return {"processed": [], "failed": [], "started_at": None}


def save_checkpoint(cp: dict) -> None:
    with open(CHECKPOINT, "w") as f:
        json.dump(cp, f, indent=2, ensure_ascii=False)


def clear_checkpoint() -> None:
    if os.path.exists(CHECKPOINT):
        os.remove(CHECKPOINT)


# ─────────────────────────────────────────────────────────────
# 3. 단일 종목 증분 수집
# ─────────────────────────────────────────────────────────────

def _build_row(stock_code: str, name: str, year: int, fin: dict, dps) -> dict:
    """build_dataset.py의 row 계산 로직 복제 (import 대신 inline)."""
    op_cf  = fin.get("operating_cf")
    capex  = fin.get("capex")
    net    = fin.get("net_income")
    divp   = fin.get("dividends_paid")

    fcf = (op_cf - abs(capex)) if (op_cf is not None and capex is not None) else None
    payout_ratio = (abs(divp) / abs(net) * 100
                    if (net and divp and net != 0) else None)
    dividend_coverage = (fcf / abs(divp)
                         if (fcf is not None and divp and abs(divp) > 0) else None)
    div_to_ocf = (abs(divp) / op_cf
                  if (op_cf and op_cf > 0 and divp) else None)
    fcf_negative = int(fcf < 0) if fcf is not None else None

    return {
        "stock_code":         stock_code,
        "name":               name,
        "year":               year,
        "revenue":            fin.get("revenue"),
        "op_income":          fin.get("op_income"),
        "net_income":         net,
        "operating_cf":       op_cf,
        "capex":              capex,
        "dividends_paid":     divp,
        "total_liab":         fin.get("total_liab"),
        "total_equity":       fin.get("total_equity"),
        "interest_expense":   fin.get("interest_expense"),
        "dps":                dps,
        "fcf":                fcf,
        "payout_ratio":       payout_ratio,
        "dividend_coverage":  dividend_coverage,
        "div_to_ocf":         div_to_ocf,
        "fcf_negative":       fcf_negative,
    }


def collect_incremental_one(
    stock: dict,
    last_year: int | None,
    start_year: int = 2015,
    end_year: int | None = None,
) -> list[dict]:
    """
    한 종목의 증분 데이터 수집.

    last_year: 이미 수집된 마지막 연도. None이면 신규 종목(전체 수집).
    """
    if end_year is None:
        end_year = CURRENT_YEAR

    if last_year is not None:
        collect_from = last_year + 1
    else:
        collect_from = start_year

    if collect_from > end_year:
        log.info("  %-10s 이미 최신 (%d년까지), 건너뜀", stock["stock_code"], last_year)
        return []

    log.info("  %-10s %d~%d년 수집 중 (기존 max: %s)",
             stock["stock_code"], collect_from, end_year,
             str(last_year) if last_year else "없음")

    corp_code = resolve_corp_code(stock)
    if not corp_code:
        log.warning("  %-10s corp_code 없음, 건너뜀", stock["stock_code"])
        return []

    rows = []
    for year in range(collect_from, end_year + 1):
        try:
            fin = fetch_financials_one_year(corp_code, year)
            dps = fetch_dps(corp_code, year)

            if not fin and dps is None:
                log.debug("    [%d] 데이터 없음", year)
                continue

            row = _build_row(stock["stock_code"], stock["name"], year, fin or {}, dps)
            rows.append(row)
            log.info("    [%d] OK — FCF=%s DPS=%s", year,
                     f"{row['fcf']:.0f}" if row['fcf'] else "None", dps)
            time.sleep(0.3)   # DART API rate limit
        except Exception as e:
            log.error("    [%d] 실패: %s", year, e)
            time.sleep(1.0)

    return rows


# ─────────────────────────────────────────────────────────────
# 4. CSV append + 중복 제거
# ─────────────────────────────────────────────────────────────

def append_to_dataset(new_rows: list[dict]) -> int:
    """
    새 데이터를 dividend_dataset.csv에 append.
    (stock_code, year) 기준 중복 시 새 데이터가 우선.
    반환: 실제 추가된 행 수
    """
    if not new_rows:
        return 0

    new_df = pd.DataFrame(new_rows)

    if os.path.exists(DATASET_CSV):
        existing = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
        existing["stock_code"] = existing["stock_code"].str.zfill(6)
        # 새 데이터 우선: existing에서 겹치는 (code, year) 제거
        key = ["stock_code", "year"]
        existing = existing[
            ~existing.set_index(key).index.isin(new_df.set_index(key).index)
        ]
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df

    combined = combined.sort_values(["stock_code", "year"])
    combined.to_csv(DATASET_CSV, index=False)
    return len(new_rows)


# ─────────────────────────────────────────────────────────────
# 5. 메인 실행
# ─────────────────────────────────────────────────────────────

def run_incremental_update(
    force_full: bool = False,
    ticker_filter: str | None = None,
    end_year: int | None = None,
) -> dict:
    """
    APScheduler / 직접 호출용 진입점.

    Returns:
        {updated: int, skipped: int, failed: int, duration_sec: float}
    """
    t0 = time.time()
    log.info("=== DART 증분 업데이트 시작 ===")

    stocks     = get_target_stocks()
    last_years = {} if force_full else get_last_collected_years()
    cp         = load_checkpoint()

    if ticker_filter:
        stocks = [s for s in stocks if s["stock_code"] == ticker_filter.zfill(6)]
        log.info("필터 적용: %s → %d개", ticker_filter, len(stocks))

    if not cp.get("started_at"):
        cp["started_at"] = datetime.now().isoformat()
        cp["processed"]  = []
        cp["failed"]     = []

    updated = 0
    skipped = 0
    failed  = 0
    all_new_rows = []

    for stock in stocks:
        code = stock["stock_code"]
        if code in cp.get("processed", []):
            skipped += 1
            continue

        last_y = None if force_full else last_years.get(code)
        try:
            rows = collect_incremental_one(stock, last_y, end_year=end_year)
            if rows:
                all_new_rows.extend(rows)
                updated += len(rows)
            else:
                skipped += 1
            cp["processed"].append(code)
        except Exception as e:
            log.error("[%s] 오류: %s", code, e)
            cp["failed"].append(code)
            failed += 1

        save_checkpoint(cp)
        time.sleep(0.2)

    # 일괄 저장
    added = append_to_dataset(all_new_rows)
    clear_checkpoint()

    duration = round(time.time() - t0, 1)
    log.info("=== 완료: 추가 %d행 / 건너뜀 %d / 실패 %d / %.1fs ===",
             added, skipped, failed, duration)
    return {"updated": added, "skipped": skipped, "failed": failed,
            "duration_sec": duration}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full",   action="store_true", help="전체 재수집")
    parser.add_argument("--ticker", type=str,            help="특정 종목 코드")
    parser.add_argument("--year",   type=int,            help="수집 종료 연도")
    args = parser.parse_args()

    result = run_incremental_update(
        force_full=args.full,
        ticker_filter=args.ticker,
        end_year=args.year,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

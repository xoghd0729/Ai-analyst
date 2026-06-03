"""
scripts/expand_universe.py — KR 배당주 유니버스 자동 확장기 (DART 전용)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 DART인가
  pykrx·FinanceDataReader 는 둘 다 KRX(data.krx.co.kr)를 스크래핑하는데,
  KRX가 로그인 요구·접근 차단으로 막히는 경우가 잦다. 반면 DART
  (opendart.fss.or.kr)는 정상 작동하므로(build_dataset 수집 성공),
  유니버스 확장도 DART로 통일한다.

원리
  data/dart_corp_codes.json = {종목코드: corp_code} 약 3,900개.
  각 후보에 대해 DART 배당공시(alotMatter)를 '최근 1개 연도'만 조회해
  보통주 현금배당(DPS>0)이 있으면 = 배당주 → 유니버스에 편입.
  → 후보당 API 1회로 배당 여부 판정 (효율적, KRX 무관).

점진 확장
  --max-add (기본 60): 이번 실행에서 추가할 배당주 최대 수
  --max-scan(기본 800): 스캔할 후보 최대 수 (과도한 호출 방지)
  매주 돌리면 아직 안 본 후보부터 이어서 스캔 → 커버리지 누적.

실행
  python scripts/expand_universe.py
  python scripts/expand_universe.py --max-add 100 --max-scan 1500 --year 2024

  이후:
  python build_dataset.py     # 늘어난 유니버스 수집(이어받기 지원)
  python train_kr_3class.py
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH   = os.path.join(BASE_DIR, "data", "training_universe_expanded.csv")
CORP_PATH  = os.path.join(BASE_DIR, "data", "dart_corp_codes.json")
SCAN_STATE = os.path.join(BASE_DIR, "data", "expand_scan_state.json")  # 어디까지 스캔했나
API_KEY    = os.getenv("DART_API_KEY")


def _load_existing() -> dict[str, tuple[str, str]]:
    seed: dict[str, tuple[str, str]] = {}
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                code = str(row.get("stock_code", "")).zfill(6)
                if code and code != "000000":
                    seed[code] = (row.get("name", code), row.get("source", "existing"))
    return seed


def _parse_num(v) -> float:
    if v is None:
        return 0.0
    s = str(v).replace(",", "").strip()
    if s in ("-", "", "N/A", "null", "None"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _has_dividend(corp_code: str, year: int) -> bool:
    """DART 배당공시에서 보통주 현금 DPS > 0 이면 True."""
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/alotMatter.json",
            params={"crtfc_key": API_KEY, "corp_code": corp_code,
                    "bsns_year": str(year), "reprt_code": "11011"},
            timeout=10,
        ).json()
    except Exception:
        return False
    if res.get("status") != "000":
        return False
    for item in res.get("list", []):
        se        = item.get("se", "")
        stock_knd = item.get("stock_knd", "")
        if "주당 현금배당금" in se and "보통주" in stock_knd:
            if _parse_num(item.get("thstrm", "")) > 0:
                return True
    return False


def _corp_name(corp_code: str) -> str:
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/company.json",
            params={"crtfc_key": API_KEY, "corp_code": corp_code},
            timeout=10,
        ).json()
        if res.get("status") == "000":
            return res.get("corp_name", corp_code)
    except Exception:
        pass
    return corp_code


def expand(max_add: int, max_scan: int, year: int) -> None:
    if not API_KEY:
        print("❌ DART_API_KEY 미설정 (.env 확인)")
        sys.exit(1)
    if not os.path.exists(CORP_PATH):
        print(f"❌ {CORP_PATH} 없음")
        sys.exit(1)

    corp_map: dict[str, str] = json.load(open(CORP_PATH, encoding="utf-8"))  # {code: corp_code}
    seed = _load_existing()
    before = len(seed)
    print(f"기존 유니버스: {before}개 종목")

    # 아직 유니버스에 없는 후보만, 정렬해 결정적 순서로
    candidates = sorted(c for c in corp_map if c not in seed)
    # 지난 실행이 어디까지 스캔했는지 이어가기
    start = 0
    if os.path.exists(SCAN_STATE):
        try:
            start = int(json.load(open(SCAN_STATE)).get("cursor", 0))
        except Exception:
            start = 0
    if start >= len(candidates):
        start = 0   # 한 바퀴 다 돌았으면 처음부터
    print(f"후보 {len(candidates)}개 중 {start}번부터 최대 {max_scan}개 스캔 (배당 {year}년 기준)")

    added = 0
    scanned = 0
    i = start
    while scanned < max_scan and added < max_add and i < len(candidates):
        code = candidates[i]
        i += 1
        scanned += 1
        corp_code = corp_map[code]
        if _has_dividend(corp_code, year):
            name = _corp_name(corp_code)
            seed[code] = (name, "dart_div")
            added += 1
            print(f"  + {code} {name}  ({added}/{max_add})")
        time.sleep(0.15)   # API 부하 분산
        if scanned % 100 == 0:
            print(f"    ...{scanned}개 스캔, {added}개 추가")

    # 커서 저장 (다음 실행 이어가기)
    json.dump({"cursor": i, "total_candidates": len(candidates)},
              open(SCAN_STATE, "w"))

    # 유니버스 저장
    with open(CSV_PATH, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["stock_code", "name", "source"])
        for code, (name, source) in sorted(seed.items()):
            w.writerow([code, name, source])

    print(f"\n✅ 유니버스 {before} → {len(seed)}개  (배당주 신규 {added}개, {scanned}개 스캔)")
    print(f"   다음 스캔 커서: {i}/{len(candidates)}")
    print(f"   저장: {CSV_PATH}")
    if added:
        print("\n다음:  python build_dataset.py  →  python train_kr_3class.py")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="KR 배당주 유니버스 자동 확장 (DART)")
    ap.add_argument("--max-add",  type=int, default=60,  help="이번 실행 추가할 배당주 최대 수, 기본 60")
    ap.add_argument("--max-scan", type=int, default=800, help="스캔할 후보 최대 수, 기본 800")
    ap.add_argument("--year",     type=int, default=2024, help="배당 판정 기준 연도, 기본 2024")
    args = ap.parse_args()
    expand(args.max_add, args.max_scan, args.year)

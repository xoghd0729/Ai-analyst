"""
expand_universe.py — DART 유니버스 확대 스캐너

목표: 226종목 → 500+ 종목
기준: 5년 연속 배당 → 최근 5년(2020-2024) 중 2년 이상 배당

실행 방법:
  python3 scripts/expand_universe.py

산출물:
  data/universe_candidates.json  — 신규 후보 종목 리스트
  data/universe_candidates.csv   — Excel 검토용 CSV

동작 흐름:
  1. DART corpCode.xml 로드 (전 상장법인 마스터)
  2. 기존 dividend_dataset.csv의 stock_code 확인 (현재 유니버스)
  3. DART /fnlttSinglAcnt API로 배당 이력 스캔 → 2년 이상 배당 후보 필터
  4. approved_universe.json 업데이트 후보 생성

주의:
  - DART_API_KEY 필요 (.env 파일 또는 환경변수)
  - 전체 실행 시 약 2-4시간 소요 (API rate limit)
  - --limit N 옵션으로 N개만 테스트 가능
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("DART_API_KEY", "")
CORP_XML_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
FNLTT_URL    = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.json"

# ── 설정 ────────────────────────────────────────────────────────
SCAN_YEARS    = [2020, 2021, 2022, 2023, 2024]  # 최근 5년
MIN_DIV_YEARS = 2   # 2년 이상 배당 시 후보 포함
MAX_DEBT_RATIO = 300  # 부채비율 상한 (배당주 품질 기준)

# 현재 유니버스 데이터
EXISTING_CSV = ROOT / "data" / "dividend_dataset.csv"
APPROVED_JSON = ROOT / "data" / "approved_universe.json"
OUTPUT_JSON  = ROOT / "data" / "universe_candidates.json"
OUTPUT_CSV   = ROOT / "data" / "universe_candidates.csv"

# 한국거래소 섹터 — 배당주 관련성 높은 섹터 우선
PRIORITY_SECTORS = {
    "금융업", "보험업", "은행", "증권",
    "전기통신업", "건설업", "제조업", "운수창고업",
    "부동산업", "도소매업",
}


def load_corp_codes() -> dict[str, dict]:
    """
    DART corpCode.xml 로드.
    캐시 파일(data/corpCode_cache.json) 있으면 재사용.
    """
    cache_path = ROOT / "data" / "corpCode_cache.json"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 168:  # 7일 캐시
            with open(cache_path) as f:
                data = json.load(f)
            print(f"[Corp] 캐시 로드: {len(data)}개 법인 (갱신 {age_hours:.0f}시간 전)")
            return data

    print("[Corp] DART corpCode.xml 다운로드 중...")
    if not API_KEY:
        print("  ⚠️  DART_API_KEY 없음 — .env 파일 확인")
        return {}

    resp = requests.get(CORP_XML_URL, params={"crtfc_key": API_KEY}, timeout=60)
    resp.raise_for_status()
    print(f"  HTTP {resp.status_code}, Content-Type: {resp.headers.get('Content-Type','?')}, Size: {len(resp.content)} bytes")

    import xml.etree.ElementTree as ET
    # ZIP 여부 확인
    if not resp.content[:2] == b'PK':
        print(f"  ⚠️  ZIP 아님 — 응답 앞부분: {resp.content[:200]}")
        return {}

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_name = [n for n in zf.namelist() if n.endswith(".xml")][0]
        tree = ET.parse(zf.open(xml_name))

    root = tree.getroot()
    all_items = root.findall("list")
    print(f"  XML list 항목 수: {len(all_items)}")

    # 첫 3개 항목 구조 확인
    for i, item in enumerate(all_items[:3]):
        print(f"  [샘플 {i}] " + " | ".join(f"{c.tag}={c.text!r}" for c in item))

    corps: dict[str, dict] = {}
    for item in all_items:
        code  = (item.findtext("stock_code") or "").strip()
        corp  = (item.findtext("corp_code")  or "").strip()
        name  = (item.findtext("corp_name")  or "").strip()
        if code and corp:  # stock_code 있으면 상장법인
            corps[code] = {"corp_code": corp, "name": name, "market": "KRX"}

    # 캐시 저장
    cache_path.parent.mkdir(exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(corps, f, ensure_ascii=False)
    print(f"[Corp] {len(corps)}개 상장법인 로드 완료")
    return corps


ALOT_URL = "https://opendart.fss.or.kr/api/alotMatter.json"

def fetch_dividend_years(corp_code: str, years: list[int]) -> list[int]:
    """
    DART alotMatter API(배당공시 전용)로 배당 여부 스캔.
    fnlttSinglAcnt(재무제표)보다 훨씬 정확.
    """
    paid_years = []
    for year in years:
        try:
            params = {
                "crtfc_key":  API_KEY,
                "corp_code":  corp_code,
                "bsns_year":  str(year),
                "reprt_code": "11011",   # 사업보고서
            }
            resp = requests.get(ALOT_URL, params=params, timeout=20)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if data.get("status") != "000":
                continue
            for item in data.get("list", []):
                se = item.get("se", "")
                if "주당 현금배당금" in se:
                    val = str(item.get("thstrm", "0")).replace(",", "").strip()
                    try:
                        dps = float(val or "0")
                    except Exception:
                        dps = 0.0
                    if dps > 0:
                        paid_years.append(year)
                        break
        except Exception:
            pass
        time.sleep(0.12)

    return paid_years


def load_existing_universe() -> set[str]:
    """기존 dividend_dataset.csv의 stock_code 셋 반환."""
    if not EXISTING_CSV.exists():
        return set()
    df = pd.read_csv(EXISTING_CSV, dtype={"stock_code": str})
    return set(df["stock_code"].str.zfill(6).unique())


def scan_new_candidates(
    corps: dict[str, dict],
    existing: set[str],
    limit: Optional[int] = None,
    resume_from: Optional[str] = None,
) -> list[dict]:
    """
    기존 유니버스에 없는 종목을 DART에서 스캔.
    배당 이력 2년 이상인 종목만 후보로 반환.
    """
    candidates = []
    skipped = errors = 0

    # 스캔 대상: 기존 유니버스 제외
    targets = {k: v for k, v in corps.items() if k not in existing}
    if limit:
        targets = dict(list(targets.items())[:limit])

    total = len(targets)
    print(f"\n[스캔] 대상 {total}개 종목 (기존 {len(existing)}개 제외)")
    print(f"  기준: {SCAN_YEARS[0]}-{SCAN_YEARS[-1]} 중 {MIN_DIV_YEARS}년 이상 배당\n")

    resume = resume_from is not None
    for i, (stock_code, info) in enumerate(targets.items(), 1):
        if resume:
            if stock_code == resume_from:
                resume = False
            else:
                skipped += 1
                continue

        print(f"  [{i}/{total}] {info['name']:20} ({stock_code}) ... ", end="", flush=True)

        try:
            paid = fetch_dividend_years(info["corp_code"], SCAN_YEARS)
            n_years = len(paid)
            print(f"배당 {n_years}년 {paid}")

            if n_years >= MIN_DIV_YEARS:
                candidates.append({
                    "stock_code":    stock_code,
                    "name":          info["name"],
                    "market":        info["market"],
                    "corp_code":     info["corp_code"],
                    "dividend_years": paid,
                    "n_dividend_years": n_years,
                    "priority":      info.get("sector", "") in PRIORITY_SECTORS,
                })

        except KeyboardInterrupt:
            print(f"\n  → 중단. 마지막 처리 종목: {stock_code}")
            break
        except Exception as e:
            errors += 1
            print(f"오류: {e}")

    print(f"\n  스캔 완료: 후보 {len(candidates)}개 / 오류 {errors}개")
    return candidates


def merge_with_approved(candidates: list[dict]) -> None:
    """
    후보 종목을 approved_universe.json에 병합.
    신규 항목만 추가 (기존 항목 변경 없음).
    """
    if not APPROVED_JSON.exists():
        print(f"  ⚠️  {APPROVED_JSON} 없음 — 병합 건너뜀")
        return

    with open(APPROVED_JSON) as f:
        uni = json.load(f)

    # 기존 구조 파악
    if isinstance(uni, list):
        existing_codes = {s.get("stock_code", s.get("ticker", "")) for s in uni}
        base = uni
    else:
        kr = uni.get("kr", [])
        existing_codes = {s.get("stock_code", s.get("ticker", "")) for s in kr}
        base = kr

    new_added = 0
    for c in candidates:
        code = str(c["stock_code"]).zfill(6)
        if code not in existing_codes:
            # 기본 엔트리 형식으로 추가
            base.append({
                "stock_code":   code,
                "ticker":       f"{code}.KS",
                "name":         c["name"],
                "market":       c["market"],
                "type":         "KR_DIV",
                "dividend_years": c["dividend_years"],
                "auto_added":   True,  # 자동 추가 마킹
            })
            new_added += 1

    if isinstance(uni, list):
        out = base
    else:
        uni["kr"] = base
        out = uni

    out_path = APPROVED_JSON.with_name("approved_universe_expanded.json")
    with open(out_path, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  병합 완료: {new_added}개 신규 추가 → {out_path.name}")


def main():
    parser = argparse.ArgumentParser(description="DART 유니버스 확대 스캐너")
    parser.add_argument("--limit", type=int, default=None,
                        help="스캔할 최대 종목 수 (테스트용)")
    parser.add_argument("--resume", type=str, default=None,
                        help="이 stock_code부터 재개")
    parser.add_argument("--no-merge", action="store_true",
                        help="approved_universe.json 병합 건너뜀")
    args = parser.parse_args()

    if not API_KEY:
        print("⛔  DART_API_KEY가 없습니다.")
        print("    .env 파일에 DART_API_KEY=xxx 추가 후 재실행하세요.")
        print()
        print("    [오프라인 모드] 기존 dividend_dataset.csv 분석:")
        _offline_analysis()
        return

    # 1. Corp 마스터 로드
    corps = load_corp_codes()
    if not corps:
        print("Corp 마스터 로드 실패")
        return

    # 2. 기존 유니버스
    existing = load_existing_universe()
    print(f"[현황] 기존 유니버스: {len(existing)}개 종목")

    # 3. 신규 후보 스캔
    candidates = scan_new_candidates(corps, existing,
                                     limit=args.limit,
                                     resume_from=args.resume)

    if not candidates:
        print("신규 후보 없음")
        return

    # 4. 저장
    OUTPUT_JSON.parent.mkdir(exist_ok=True)
    with open(OUTPUT_JSON, "w") as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
    pd.DataFrame(candidates).to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n저장 완료:")
    print(f"  {OUTPUT_JSON}  ({len(candidates)}개 후보)")
    print(f"  {OUTPUT_CSV}")

    # 5. 요약 출력
    df = pd.DataFrame(candidates)
    print(f"\n[요약]")
    print(f"  총 후보: {len(df)}개")
    print(f"  5년 연속 배당 (기존 기준): {(df['n_dividend_years'] == 5).sum()}개")
    print(f"  2-4년 배당 (신규 포함):    {(df['n_dividend_years'] < 5).sum()}개")
    print(f"  KOSPI: {(df['market']=='유가증권시장').sum()}개")
    print(f"  KOSDAQ: {(df['market']=='코스닥').sum()}개")
    print(f"\n  → build_dataset.py에 추가 시 유니버스: "
          f"{len(existing) + len(df)}개 (+{len(df)}개)")

    # 6. approved_universe 병합
    if not args.no_merge:
        merge_with_approved(candidates)


def _offline_analysis():
    """DART API 없이 기존 데이터로 유니버스 현황 분석."""
    if not EXISTING_CSV.exists():
        print("  dividend_dataset.csv 없음")
        return

    df = pd.read_csv(EXISTING_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(6)

    dps_hist = df[pd.to_numeric(df.get("dps", pd.Series()), errors="coerce") > 0] \
                 .groupby("stock_code")["year"].count()

    print(f"  현재 유니버스: {df['stock_code'].nunique()}개 종목")
    print(f"  person-period rows: {len(df)}")
    print()
    print("  배당 지급 연수 분포:")
    for years, cnt in sorted(dps_hist.value_counts().items()):
        bar = "█" * (cnt // 2)
        print(f"    {years:2}년:  {cnt:3}개  {bar}")
    print()
    print("  배당 이력 기준별 후보:")
    for min_y in [2, 3, 4, 5]:
        n = (dps_hist >= min_y).sum()
        print(f"    {min_y}년 이상: {n}개 (현재 {min_y}년 미만 제외됨: {(dps_hist < min_y).sum()}개)")
    print()
    print("  실행 방법 (DART API 키 필요):")
    print("  1. .env 파일에 DART_API_KEY=<키> 추가")
    print("  2. python3 scripts/expand_universe.py --limit 50  # 테스트")
    print("  3. python3 scripts/expand_universe.py             # 전체 (2-4시간)")


if __name__ == "__main__":
    main()

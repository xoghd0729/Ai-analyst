"""
fetch_dps_history.py — DART에서 2년치 배당금 수집 → dps_yoy_pct 계산

■ 목적
  run_thesis_batch.py에서 dps_yoy_pct가 전부 imputed(=학습 중앙값)로 들어가는 문제 해결.
  DART 재무제표에서 dividends_paid를 2023, 2024년 각각 수집 → YoY 계산 → DB 저장.

■ 왜 이게 중요한가
  XGBoost 모델에서 dps_yoy_pct 중요도 = 47.7% (1위)
  이 피처가 0이면 모델이 거의 아무것도 못 판단함.

■ 실행
  python collectors/fetch_dps_history.py
  python collectors/fetch_dps_history.py --dry-run   # DB 저장 없이 출력만
"""

import os
import sys
import time
import argparse
import requests
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DART_API_KEY = os.getenv("DART_API_KEY", "")
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RANKING_CSV  = os.path.join(BASE_DIR, "data", "ranking.csv")
engine       = create_engine("postgresql://localhost/ai_analyst")

# DART 재무제표 항목 코드
# 현금흐름표(CF) → 배당금지급 항목
CF_ACCOUNT_NM = "배당금의 지급"   # 간접법 현금흐름표


def get_dart_corp_code(stock_code: str) -> str | None:
    """
    종목코드(6자리) → DART 고유번호(8자리) 변환.
    DART corpCode API 사용.
    """
    try:
        import zipfile, io
        url = "https://opendart.fss.or.kr/api/corpCode.xml"
        resp = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=30)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        xml_data = zf.read("CORPCODE.xml").decode("utf-8")

        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_data)
        for corp in root.findall("list"):
            code = corp.findtext("stock_code", "").strip()
            if code == stock_code:
                return corp.findtext("corp_code", "").strip()
    except Exception as e:
        print(f"  [DART] corpCode 조회 실패: {e}")
    return None


def fetch_dividends_paid_dart(corp_code: str, year: int) -> float | None:
    """
    DART 현금흐름표에서 '배당금의 지급' 금액 조회.

    반환: 금액(원) 또는 None
    """
    try:
        url = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
        params = {
            "crtfc_key": DART_API_KEY,
            "corp_code":  corp_code,
            "bsns_year":  str(year),
            "reprt_code": "11011",   # 사업보고서 (연간)
            "fs_div":     "CFS",     # 연결재무제표 우선
        }
        resp = requests.get(url, params=params, timeout=20)
        data = resp.json()

        if data.get("status") != "000":
            # 연결 없으면 별도재무제표로 재시도
            params["fs_div"] = "OFS"
            resp = requests.get(url, params=params, timeout=20)
            data = resp.json()

        if data.get("status") != "000":
            return None

        for item in data.get("list", []):
            acnt_nm = item.get("account_nm", "")
            if "배당금" in acnt_nm and "지급" in acnt_nm:
                # thstrm_amount: 당기 금액
                val_str = item.get("thstrm_amount", "").replace(",", "").strip()
                if val_str and val_str not in ("-", ""):
                    return abs(float(val_str))   # 음수(지급)이면 양수로 변환

    except Exception as e:
        print(f"  [DART] 재무제표 조회 실패 (year={year}): {e}")
    return None


def save_to_db(stock_code: str, year: int, amount: float):
    """metric_snapshots에 dividends_paid 저장."""
    date_str = f"{year}-12-31"
    with engine.connect() as conn:
        # 이미 있으면 upsert (덮어쓰기)
        conn.execute(text("""
            INSERT INTO metric_snapshots (stock_code, metric_name, value, date)
            VALUES (:code, 'dividends_paid', :val, :date)
            ON CONFLICT (stock_code, metric_name, date)
            DO UPDATE SET value = EXCLUDED.value
        """), {"code": stock_code, "val": amount, "date": date_str})
        conn.commit()


def run(dry_run: bool = False):
    if not DART_API_KEY:
        print("❌ DART_API_KEY가 .env에 없어요. 설정 후 재실행하세요.")
        return

    df = pd.read_csv(RANKING_CSV, encoding="utf-8-sig")
    stocks = df[["name", "stock_code"]].dropna().to_dict("records")
    stocks = [{"name": s["name"], "stock_code": str(s["stock_code"]).zfill(6)} for s in stocks]

    # DART corpCode 전체 로드 (한 번만)
    print("[1] DART corpCode 전체 다운로드 중...")
    corp_map = _load_corp_map()
    print(f"    → {len(corp_map)}개 기업 코드 로드 완료\n")

    results = []
    for i, s in enumerate(stocks, 1):
        code = s["stock_code"]
        name = s["name"]
        corp_code = corp_map.get(code)
        print(f"[{i:2d}/{len(stocks)}] {name} ({code})", end=" ")

        if not corp_code:
            print("→ DART corp_code 없음 스킵")
            continue

        # 2024, 2025년 배당금 수집
        # 2025 사업보고서는 2026년 3~4월에 제출 → 지금(2026년 5월) 조회 가능
        div_2024 = fetch_dividends_paid_dart(corp_code, 2024)
        time.sleep(0.5)
        div_2025 = fetch_dividends_paid_dart(corp_code, 2025)
        time.sleep(0.5)

        # dps_yoy_pct = (2025 - 2024) / |2024| * 100
        # 이게 모델에 넣을 실제 신호 (가장 최신 YoY 변화)
        if div_2024 and div_2025 and div_2024 != 0:
            yoy = round((div_2025 - div_2024) / abs(div_2024) * 100, 2)
        elif div_2024 is None and div_2025:
            # 2025만 있으면 YoY 계산 불가 → None
            yoy = None
        else:
            yoy = None

        status = "✅" if yoy is not None else "⚠️ "
        print(f"| 2024={_fmt(div_2024)}  2025={_fmt(div_2025)}  YoY={yoy}%  {status}")

        if not dry_run:
            if div_2024:
                save_to_db(code, 2024, div_2024)
            if div_2025:
                save_to_db(code, 2025, div_2025)

        results.append({
            "name": name, "stock_code": code,
            "div_2024": div_2024, "div_2025": div_2025,
            "dps_yoy_pct": yoy,
        })

    print(f"\n{'='*60}")
    print(f"  dps_yoy_pct 수집 완료 (2024→2025 YoY)")
    filled  = sum(1 for r in results if r["dps_yoy_pct"] is not None)
    cut     = sum(1 for r in results if r["dps_yoy_pct"] is not None and r["dps_yoy_pct"] < -10)
    grew    = sum(1 for r in results if r["dps_yoy_pct"] is not None and r["dps_yoy_pct"] > 10)
    print(f"  YoY 계산 가능: {filled}/{len(results)}종목")
    print(f"  배당 삭감 (YoY < -10%): {cut}개")
    print(f"  배당 증가 (YoY > +10%): {grew}개")

    # 배당 삭감 종목 출력
    cuts = [r for r in results if r["dps_yoy_pct"] is not None and r["dps_yoy_pct"] < -10]
    if cuts:
        print(f"\n  ⚠️  배당 삭감 감지 종목:")
        for r in sorted(cuts, key=lambda x: x["dps_yoy_pct"]):
            print(f"    {r['name']:12s} ({r['stock_code']})  YoY={r['dps_yoy_pct']:+.1f}%")

    if not dry_run:
        print(f"\n  ✅ metric_snapshots DB 저장 완료")
    print(f"{'='*60}")


def _load_corp_map() -> dict:
    """DART corpCode XML → {stock_code: corp_code} 딕셔너리."""
    try:
        import zipfile, io, xml.etree.ElementTree as ET
        url = "https://opendart.fss.or.kr/api/corpCode.xml"
        resp = requests.get(url, params={"crtfc_key": DART_API_KEY}, timeout=60)
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        xml_data = zf.read("CORPCODE.xml").decode("utf-8")
        root = ET.fromstring(xml_data)
        return {
            corp.findtext("stock_code", "").strip(): corp.findtext("corp_code", "").strip()
            for corp in root.findall("list")
            if corp.findtext("stock_code", "").strip()
        }
    except Exception as e:
        print(f"  corp_map 로드 실패: {e}")
        return {}


def _fmt(val) -> str:
    if val is None:
        return "N/A"
    return f"{val/1e9:.1f}억"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)

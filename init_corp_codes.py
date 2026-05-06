"""
DART corp_code 마스터 초기화 스크립트.

최초 1회 (또는 월 1회) 실행.
DART corpCode.xml을 다운로드해 corp_code_map 테이블에 저장.
stocks 테이블에 corp_code 컬럼을 추가하고 자동 매핑.

실행:
    cd ~/ai-analyst && source venv/bin/activate
    python init_corp_codes.py
"""

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import requests, zipfile, io, os
import xml.etree.ElementTree as ET
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
engine  = create_engine("postgresql://localhost/ai_analyst")


def create_tables():
    """corp_code_map 테이블 생성 + stocks 테이블에 corp_code 컬럼 추가"""
    with engine.connect() as conn:
        # 전용 매핑 테이블 생성
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS corp_code_map (
                stock_code  VARCHAR(10) PRIMARY KEY,
                corp_code   VARCHAR(8)  NOT NULL,
                corp_name   VARCHAR(100)
            )
        """))
        # stocks 테이블에 corp_code 컬럼 추가 (이미 있으면 무시)
        conn.execute(text("""
            ALTER TABLE stocks
            ADD COLUMN IF NOT EXISTS corp_code VARCHAR(8)
        """))
        conn.commit()
    print("✅ 테이블 준비 완료")


def download_and_parse() -> list[dict]:
    """DART corpCode.xml ZIP 다운로드 → 상장사 리스트 파싱"""
    print("📥 DART 고유번호 마스터 파일 다운로드 중...")
    res = requests.get(
        "https://opendart.fss.or.kr/api/corpCode.xml",
        params={"crtfc_key": API_KEY},
        timeout=60,
    )
    if res.status_code != 200:
        raise RuntimeError(f"DART 다운로드 실패: HTTP {res.status_code}")

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        xml_data = zf.read("CORPCODE.xml")

    print("🔄 XML 파싱 중...")
    root = ET.parse(io.BytesIO(xml_data)).getroot()

    corps = []
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code  = (item.findtext("corp_code")  or "").strip()
        corp_name  = (item.findtext("corp_name")  or "").strip()
        # 상장사(stock_code 있음)만 수집
        if stock_code and corp_code:
            corps.append({
                "stock_code": stock_code,
                "corp_code":  corp_code,
                "corp_name":  corp_name,
            })

    print(f"✅ 상장사 {len(corps)}개 파싱 완료")
    return corps


def save_to_db(corps: list[dict]):
    """corp_code_map 테이블에 UPSERT + stocks 테이블 corp_code 업데이트"""
    with engine.connect() as conn:
        # corp_code_map UPSERT
        for c in corps:
            conn.execute(text("""
                INSERT INTO corp_code_map (stock_code, corp_code, corp_name)
                VALUES (:sc, :cc, :cn)
                ON CONFLICT (stock_code)
                DO UPDATE SET corp_code = EXCLUDED.corp_code,
                              corp_name = EXCLUDED.corp_name
            """), {"sc": c["stock_code"], "cc": c["corp_code"], "cn": c["corp_name"]})

        # stocks 테이블의 corp_code 자동 업데이트
        conn.execute(text("""
            UPDATE stocks s
            SET corp_code = m.corp_code
            FROM corp_code_map m
            WHERE s.code = m.stock_code
              AND s.corp_code IS DISTINCT FROM m.corp_code
        """))
        conn.commit()

    print(f"✅ DB 저장 완료 ({len(corps)}개 매핑)")


def lookup(stock_code: str):
    """단일 종목코드 → corp_code 조회 (확인용)"""
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT corp_code, corp_name FROM corp_code_map
            WHERE stock_code = :sc
        """), {"sc": stock_code}).fetchone()
    if row:
        print(f"  {stock_code} → corp_code={row[0]}  ({row[1]})")
        return row[0]
    else:
        print(f"  {stock_code} → 매핑 없음")
        return None


if __name__ == "__main__":
    create_tables()
    corps = download_and_parse()
    save_to_db(corps)

    print("\n── 확인 ──")
    lookup("033780")   # KT&G
    lookup("005930")   # 삼성전자
    lookup("000660")   # SK하이닉스

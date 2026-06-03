"""
XGBoost 학습용 배당 삭감 예측 데이터셋 생성 스크립트.

■ 무엇을 하는가
  1. 대상 종목 × 수집 연도(기본: 2015~2024) 루프
  2. DART API로 연도별 재무제표 수집 (연결 우선 → 개별 fallback)
  3. DART 결산배당 공시로 DPS(주당배당금) 수집
  4. FCF / 배당성향 / 배당커버리지 자동 계산
  5. 전년 대비 DPS 감소 여부 → dividend_cut 라벨 자동 생성 (0 또는 1)
  6. CSV + Excel 저장

■ 실행 방법
  python build_dataset.py
  → 결과: dividend_dataset.csv  /  dividend_dataset.xlsx

■ 환경변수 (.env)
  DART_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
"""

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os, time, io, zipfile, json, re
import xml.etree.ElementTree as ET
import requests
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()


# ─────────────────────────────────────────────────────────────
# DART 공통 숫자 파싱 유틸리티
# DART API는 쉼표·하이픈·공백·N/A 등이 섞여 있음
# ─────────────────────────────────────────────────────────────
def parse_number(v) -> float | None:
    """
    DART 응답값을 float으로 변환.
    쉼표, 공백, 하이픈(-), 빈 문자열, None → None 반환.
    """
    if v is None:
        return None
    v = str(v).replace(",", "").strip()
    if v in ("-", "", "N/A", "null", "None"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
API_KEY = os.getenv("DART_API_KEY")
engine  = create_engine("postgresql://localhost/ai_analyst")

# ─────────────────────────────────────────────────────────────
# 학습 대상 종목: ranking.csv 기반 자동 선별
#
# 순서:
#   1. ranking.csv 읽기 (run_all.py 결과물)
#   2. 기준으로 자동 필터링 → 학습 가치 있는 종목만 추출
#   3. DB에서 corp_code 조회 → DART 수집 대상 확정
#
# 필터 기준:
#   - trap_level != DANGER    (Yield Trap 위험종목 제외)
#   - overall_score >= 45     (최저 품질 기준)
#   - 우량/보통 등급만         (위험 등급 제외)
# ─────────────────────────────────────────────────────────────

RANKING_CSV  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ranking.csv")

# ──────────────────────────────────────────────────────────────
# ML 학습 필터 vs 포트폴리오 필터는 다르다!
#
#   포트폴리오 추천: DANGER 제외, 점수 45+, 우량/보통만
#   ML 학습:        DANGER 포함, 점수 25+, 위험등급도 포함
#
# 이유: 배당삭감 패턴을 학습하려면 실제로 삭감한 종목(DANGER)이
#       반드시 필요하다. 없으면 모델이 "삭감"을 제대로 학습 못 함.
# ──────────────────────────────────────────────────────────────
ML_MIN_SCORE     = 25      # ML 학습용 최저 점수 (극단적 이상치만 제외)
ML_INCLUDE_DANGER = True   # DANGER 종목 ML 학습에 포함


# ─────────────────────────────────────────────────────────────
# corp_code 캐시 (XML 한 번만 다운로드) — load_stocks_from_db보다 먼저 정의
# ─────────────────────────────────────────────────────────────

_corp_cache: dict[str, str] = {}

def load_corp_codes():
    """DART corpCode.xml 다운로드 → 메모리 캐시."""
    global _corp_cache
    if _corp_cache:
        return
    print("📥 DART corp_code 마스터 다운로드 중...")
    try:
        r = requests.get(
            "https://opendart.fss.or.kr/api/corpCode.xml",
            params={"crtfc_key": API_KEY},
            timeout=30,
        )
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xml_data = z.read("CORPCODE.xml")
        root = ET.parse(io.BytesIO(xml_data)).getroot()
        for item in root.findall("list"):
            sc = (item.findtext("stock_code") or "").strip()
            cc = (item.findtext("corp_code")  or "").strip()
            if sc and cc:
                _corp_cache[sc] = cc
        print(f"  ✅ {len(_corp_cache)}개 상장사 로드 완료")
    except Exception as e:
        print(f"  ⚠️ corpCode.xml 다운로드 실패: {e}")


SEED_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "training_universe_expanded.csv")


def select_training_stocks() -> list[str]:
    """
    ML 학습용 종목 선별.

    ★ 포트폴리오 필터와 다르다 ★
      포트폴리오: DANGER 제외, 45점+, 우량/보통만  (투자 안전성 기준)
      ML 학습:   DANGER 포함, 25점+, 위험등급 포함 (삭감 패턴 학습 기준)

    DANGER 종목은 실제로 배당을 삭감한 사례가 많아
    모델이 "삭감 직전 재무 패턴"을 학습하는 데 핵심 데이터다.
    """
    # ── 확장 seed 우선: training_universe_expanded.csv 가 있으면 그걸 사용 ──
    if os.path.exists(SEED_CSV):
        sdf = pd.read_csv(SEED_CSV, encoding="utf-8-sig", dtype={"stock_code": str})
        codes = sdf["stock_code"].astype(str).str.zfill(6).tolist()
        print(f"\n  [확장 seed 사용] {SEED_CSV}")
        print(f"  → 학습 대상 {len(codes)}개 종목 (source 분포: "
              + ", ".join(f"{k}={v}" for k, v in sdf['source'].value_counts().items()) + ")")
        return codes

    if not os.path.exists(RANKING_CSV):
        print("  ⚠️ ranking.csv 없음 → run_all.py 먼저 실행 필요")
        return []

    df = pd.read_csv(RANKING_CSV, encoding="utf-8-sig")
    total = len(df)

    # ML 학습: 점수 25점 미만만 제외 (극단적 이상치)
    df["overall_score"] = pd.to_numeric(df["overall_score"], errors="coerce").fillna(0)
    df = df[df["overall_score"] >= ML_MIN_SCORE]
    after_score = len(df)

    print(f"\n  [ML 학습 대상 선별 — 포트폴리오 기준과 다름]")
    print(f"  전체 {total}개")
    print(f"  → 점수 {ML_MIN_SCORE}점+ 필터: {after_score}개  ({total - after_score}개 제거)")
    print(f"\n  최종 ML 학습 대상: {after_score}개 종목")

    # 종목 목록 출력 (DANGER 표시)
    danger = df[df["trap_level"] == "DANGER"]
    safe   = df[df["trap_level"] != "DANGER"]
    for _, row in safe.iterrows():
        print(f"    ✅ {row['name']:15} {int(row['overall_score'])}점  {row['grade']}  {row['trap_level']}")
    for _, row in danger.iterrows():
        print(f"    ⚠️  {row['name']:15} {int(row['overall_score'])}점  {row['grade']}  {row['trap_level']}  ← 삭감 패턴 학습용")

    return df["stock_code"].astype(str).str.zfill(6).tolist()


def load_stocks_from_db(training_codes: list[str]) -> list[dict]:
    """
    선별된 종목코드 기준으로 DART 마스터(corpCode.xml)에서 corp_code 조회.
    DB 불필요 — load_corp_codes()로 이미 메모리에 캐시된 XML 마스터 사용.

    종목명은 ranking.csv에서 가져옴 (이미 select_training_stocks()에서 읽은 파일).
    """
    if not training_codes:
        return []

    # DART 마스터 로드 (최초 1회만 다운로드, 이후 캐시 사용)
    load_corp_codes()

    # ranking.csv에서 종목명 맵 구성
    name_map: dict[str, str] = {}
    if os.path.exists(RANKING_CSV):
        try:
            df_csv = pd.read_csv(RANKING_CSV, encoding="utf-8-sig")
            for _, row in df_csv.iterrows():
                code = str(row.get("stock_code", "")).zfill(6)
                name_map[code] = str(row.get("name", code))
        except Exception:
            pass

    stocks = []
    missing = []
    for code in training_codes:
        if code in _corp_cache:
            stocks.append({
                "stock_code": code,
                "corp_code":  _corp_cache[code],
                "name":       name_map.get(code, code),
            })
        else:
            missing.append(code)

    print(f"\n  ✅ DART 마스터 매핑: {len(stocks)}개")
    if missing:
        print(f"  ⚠️  corp_code 미매핑 (제외): {missing}")
    return stocks

# ── 실행: ranking.csv 선별 → DB corp_code 매핑 ────────────────
training_codes = select_training_stocks()
STOCKS = load_stocks_from_db(training_codes)

# 수집 연도 범위
START_YEAR = 2013   # DART 전자공시 2013년부터 데이터 안정적 (이전 연도는 대부분 없음)
END_YEAR   = 2025


# ─────────────────────────────────────────────────────────────
# 수집할 계정명 → 필드명 매핑
# ─────────────────────────────────────────────────────────────

ACCOUNT_MAP = {
    # 손익계산서
    "매출액":                      "revenue",
    "영업수익":                    "revenue",   # 금융주(은행·보험·증권) 매출 계정
    "당기순이익":                  "net_income",
    "영업이익":                    "op_income",
    # 현금흐름표
    "영업활동현금흐름":            "operating_cf",
    "영업활동으로인한현금흐름":    "operating_cf",
    "영업활동으로 인한 현금흐름":  "operating_cf",
    "유형자산의취득":              "capex",
    "유형자산취득":                "capex",
    "유형자산의 취득":             "capex",
    # 배당금
    "배당금의지급":                "dividends_paid",
    "배당금지급":                  "dividends_paid",
    "배당금 지급":                 "dividends_paid",
    "배당금의 지급":               "dividends_paid",
    # 재무상태표 (신규 피처용)
    "부채총계":                    "total_liab",
    "자본총계":                    "total_equity",
    # 이자비용 (이자보상배율용)
    "이자비용":                    "interest_expense",
    "금융비용":                    "interest_expense",
}


def resolve_corp_code(stock: dict) -> str:
    """
    stock dict의 corp_code를 반환.
    캐시에 있으면 캐시 우선, 없으면 하드코딩 값 사용.
    """
    sc = stock["stock_code"]
    if sc in _corp_cache:
        return _corp_cache[sc]
    return stock["corp_code"]   # fallback


# ─────────────────────────────────────────────────────────────
# 1. 단일 연도 재무제표 수집
# ─────────────────────────────────────────────────────────────

def fetch_financials_one_year(corp_code: str, year: int) -> dict:
    """
    DART fnlttSinglAcntAll API로 한 해 재무 데이터 수집.
    CFS(연결) 우선 → OFS(개별) fallback.

    반환값: {"revenue": ..., "net_income": ..., ...}  (없으면 빈 dict)
    """
    for fs_div in ("CFS", "OFS"):
        try:
            res = requests.get(
                "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key":  API_KEY,
                    "corp_code":  corp_code,
                    "bsns_year":  str(year),
                    "reprt_code": "11011",  # 사업보고서
                    "fs_div":     fs_div,
                },
                timeout=15,
            ).json()
            time.sleep(0.3)  # API rate limit 방지

            if res.get("status") == "000" and res.get("list"):
                data = {}
                seen = set()
                for item in res["list"]:
                    acct_raw = item.get("account_nm", "")
                    acct     = acct_raw.replace(" ", "")
                    field    = ACCOUNT_MAP.get(acct) or ACCOUNT_MAP.get(acct_raw)
                    if not field or field in seen:
                        continue
                    raw_val = item.get("thstrm_amount", "").replace(",", "").strip()
                    if raw_val:
                        try:
                            data[field] = float(raw_val)
                            seen.add(field)
                        except ValueError:
                            pass
                if data:
                    return data
        except Exception as e:
            print(f"    [{year}/{fs_div}] 오류: {e}")
            time.sleep(1)

    return {}


# ─────────────────────────────────────────────────────────────
# 2. DPS (주당배당금) 수집
# ─────────────────────────────────────────────────────────────

def fetch_dps(corp_code: str, year: int) -> float | None:
    """
    DART에서 보통주 DPS(주당배당금) 수집.

    시도 순서:
    ① alotMatter API (결산배당 공시) — 보통주 키워드 유연 매칭
    ② 재무제표 계정명 직접 파싱 (주당배당금, 주당현금배당금 등)
    """
    # ① alotMatter API
    try:
        res = requests.get(
            "https://opendart.fss.or.kr/api/alotMatter.json",
            params={
                "crtfc_key":  API_KEY,
                "corp_code":  corp_code,
                "bsns_year":  str(year),
                "reprt_code": "11011",
            },
            timeout=10,
        ).json()
        time.sleep(0.3)

        if res.get("status") == "000":
            for item in res.get("list", []):
                se        = item.get("se",        "")
                stock_knd = item.get("stock_knd", "")
                # 실제 응답 구조:
                #   se        = "주당 현금배당금(원)"
                #   stock_knd = "보통주"          ← 보통주 여부는 여기!
                #   thstrm    = "1,444"           ← DPS 금액 (thstrm_amount 아님)
                if "주당 현금배당금" in se and "보통주" in stock_knd:
                    raw = parse_number(item.get("thstrm", ""))
                    if raw and raw > 0:
                        return raw
    except Exception as e:
        if "오류" not in str(e):  # 네트워크 오류만 출력
            pass
        time.sleep(0.5)

    # ② 재무제표에서 주당배당금 계정 직접 파싱
    DPS_ACCOUNT_KEYWORDS = [
        "주당배당금", "주당현금배당금", "주당현금배당액",
        "1주당배당금", "1주당현금배당금",
        "배당금(주당)", "현금배당금(주당)",
    ]
    try:
        for fs_div in ("CFS", "OFS"):
            res2 = requests.get(
                "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={
                    "crtfc_key":  API_KEY,
                    "corp_code":  corp_code,
                    "bsns_year":  str(year),
                    "reprt_code": "11011",
                    "fs_div":     fs_div,
                },
                timeout=10,
            ).json()
            time.sleep(0.3)

            if res2.get("status") == "000":
                for item in res2.get("list", []):
                    acct = item.get("account_nm", "").replace(" ", "")
                    if any(kw.replace(" ", "") in acct for kw in DPS_ACCOUNT_KEYWORDS):
                        raw = item.get("thstrm_amount", "").replace(",", "").strip()
                        try:
                            val = float(raw)
                            if val > 0:
                                return val
                        except ValueError:
                            pass
    except Exception:
        pass

    # ③ pykrx fallback — 배당수익률 × 연말 주가로 DPS 역산
    # DART에서 못 가져온 구형 연도(~2022) 보완용
    try:
        from pykrx import stock as krx
        # 해당 연도 12월 마지막 거래일 데이터 사용
        end   = f"{year}1231"
        start = f"{year}1201"
        fund = krx.get_market_fundamental_by_date(start, end, stock_code)
        price_df = krx.get_market_ohlcv_by_date(start, end, stock_code)
        if not fund.empty and not price_df.empty:
            div_yield = fund["DIV"].iloc[-1]        # 배당수익률 (%)
            close     = float(price_df["종가"].iloc[-1])
            if div_yield and div_yield > 0:
                dps = round(close * div_yield / 100)   # DPS = 주가 × 배당수익률
                return dps if dps > 0 else None
    except Exception:
        pass

    return None


# ─────────────────────────────────────────────────────────────
# 3. 단일 종목의 다년도 데이터 수집
# ─────────────────────────────────────────────────────────────

def collect_stock_history(stock: dict, start: int, end: int) -> list[dict]:
    """
    한 종목의 start~end 연도 데이터 수집.
    각 연도별 row: stock_code, name, year, 재무지표, DPS

    반환: list of dict (연도별 row)
    """
    corp_code  = resolve_corp_code(stock)
    stock_code = stock["stock_code"]
    name       = stock["name"]

    print(f"\n{'─'*50}")
    print(f"  ▶ {name} ({stock_code}) / corp_code: {corp_code}")
    print(f"  수집 범위: {start}~{end}년")
    print(f"{'─'*50}")

    rows = []
    for year in range(start, end + 1):
        print(f"  [{year}년] 재무 수집...", end=" ", flush=True)
        fin = fetch_financials_one_year(corp_code, year)

        print(f"DPS 수집...", end=" ", flush=True)
        dps = fetch_dps(corp_code, year)

        if not fin and dps is None:
            print("→ 데이터 없음, 건너뜀")
            continue

        row = {
            "stock_code":    stock_code,
            "name":          name,
            "year":          year,
            # 재무 데이터 (없으면 None)
            "revenue":         fin.get("revenue"),
            "op_income":       fin.get("op_income"),
            "net_income":      fin.get("net_income"),
            "operating_cf":    fin.get("operating_cf"),
            "capex":           fin.get("capex"),
            "dividends_paid":  fin.get("dividends_paid"),
            # 신규 피처 raw
            "total_liab":      fin.get("total_liab"),
            "total_equity":    fin.get("total_equity"),
            "interest_expense": fin.get("interest_expense"),
            # DPS
            "dps": dps,
        }

        # ── 파생 지표 계산 ──────────────────────────────────
        # FCF = 영업현금흐름 - CAPEX
        # CAPEX는 DART에서 음수로 잡히는 경우도, 양수인 경우도 있음
        # → abs() 처리 후 차감
        op_cf = fin.get("operating_cf")
        capex = fin.get("capex")
        if op_cf is not None and capex is not None:
            row["fcf"] = op_cf - abs(capex)
        else:
            row["fcf"] = None

        # 배당성향 (%) = 배당지급액 / 순이익 × 100
        net   = fin.get("net_income")
        divp  = fin.get("dividends_paid")
        if net and divp and net != 0:
            row["payout_ratio"] = abs(divp) / abs(net) * 100
        else:
            row["payout_ratio"] = None

        # 배당커버리지 = FCF / 배당지급액
        if row["fcf"] is not None and divp and abs(divp) > 0:
            row["dividend_coverage"] = row["fcf"] / abs(divp)
        else:
            row["dividend_coverage"] = None

        # 부채비율 (%) = 부채총계 / 자본총계 × 100
        tl = fin.get("total_liab"); te = fin.get("total_equity")
        row["debt_ratio"] = (abs(tl) / abs(te) * 100) if (tl is not None and te and te != 0) else None

        # 이자보상배율 = 영업이익 / 이자비용
        opi = fin.get("op_income"); ie = fin.get("interest_expense")
        row["interest_coverage"] = (opi / abs(ie)) if (opi is not None and ie and abs(ie) > 0) else None

        collected = [k for k, v in row.items() if v is not None and k not in ("stock_code", "name", "year")]
        print(f"→ {len(collected)}개 필드 수집 ✓")
        rows.append(row)

    return rows


# ─────────────────────────────────────────────────────────────
# 4. 배당 삭감 라벨 자동 생성
# ─────────────────────────────────────────────────────────────

def label_dividend_cuts(df: pd.DataFrame) -> pd.DataFrame:
    """
    전년 대비 DPS 감소 → dividend_cut = 1 (삭감)
                         DPS 동일/증가 → dividend_cut = 0 (유지·인상)

    ■ 라벨 정의
      dividend_cut      : 0 또는 1 (이진 분류 타깃)
      dps_yoy_pct       : 전년 대비 DPS 변화율 (%)
      dps_prev          : 전년 DPS (참조용)

    ■ 주의: 전년 DPS가 없으면 (첫 해) NaN으로 처리 → 학습에서 제외
    """
    df = df.sort_values(["stock_code", "year"]).copy()

    # None → NaN 변환
    df["dps"]           = pd.to_numeric(df["dps"],           errors="coerce")
    df["dividends_paid"] = pd.to_numeric(df["dividends_paid"], errors="coerce")

    # ── 1차: DPS 기반 라벨 (데이터 있을 때 우선) ──
    df["dps_prev"] = df.groupby("stock_code")["dps"].shift(1)
    df["dps_yoy_pct"] = (
        (df["dps"] - df["dps_prev"]) / df["dps_prev"].abs() * 100
    ).round(2)

    # ── 2차: dividends_paid 기반 라벨 (DPS 없을 때 fallback) ──
    # 총 배당지급액 감소 = 배당 삭감으로 간주
    # dividends_paid는 DART에서 음수로 오는 경우가 있으므로 abs() 처리
    df["div_paid_abs"]  = df["dividends_paid"].abs()
    df["div_paid_prev"] = df.groupby("stock_code")["div_paid_abs"].shift(1)
    df["div_paid_yoy_pct"] = (
        (df["div_paid_abs"] - df["div_paid_prev"]) / df["div_paid_prev"].abs() * 100
    ).round(2)

    def _label(row):
        # DPS 데이터가 있으면 DPS 기준
        if pd.notna(row.get("dps")) and pd.notna(row.get("dps_prev")):
            return 1 if row["dps"] < row["dps_prev"] else 0
        # DPS 없으면 dividends_paid 기준 (5% 이상 감소 = 삭감)
        if pd.notna(row.get("div_paid_abs")) and pd.notna(row.get("div_paid_prev")):
            if row["div_paid_prev"] > 0:
                return 1 if row["div_paid_abs"] < row["div_paid_prev"] * 0.95 else 0
        return None

    df["dividend_cut"] = df.apply(_label, axis=1)
    df["dividend_cut"] = pd.to_numeric(df["dividend_cut"], errors="coerce")

    # ── 3-class forward-looking 라벨 ──────────────────────────
    # label3: 현재(t) 피처로 미래(t+1) 삭감을 예측
    #   0 = INTACT    : 올해 유지, 내년도 유지
    #   1 = WEAKENING : 올해 유지, 내년 삭감 예정 (전조 상태)
    #   2 = BROKEN    : 올해 이미 삭감 발생
    #
    # leakage 방지: 피처(dps_yoy_pct, payout 등)는 모두 t년도 값.
    # 마지막 연도는 t+1 미래 불명 → label3=NaN → 학습 제외.
    df["_cut_next"] = df.groupby("stock_code")["dividend_cut"].shift(-1)

    def _label3(row):
        if pd.isna(row["dividend_cut"]):
            return None
        if row["dividend_cut"] == 1:
            return 2  # BROKEN
        if pd.notna(row["_cut_next"]) and row["_cut_next"] == 1:
            return 1  # WEAKENING
        if pd.notna(row["_cut_next"]):
            return 0  # INTACT
        return None   # 마지막 연도, 미래 불명

    df["label3"] = df.apply(_label3, axis=1)
    df = df.drop(columns=["_cut_next"])

    # 매출 성장률(%) = 전년 대비 매출 변화율
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce")
    df["_rev_prev"] = df.groupby("stock_code")["revenue"].shift(1)
    df["revenue_yoy_pct"] = (
        (df["revenue"] - df["_rev_prev"]) / df["_rev_prev"].abs() * 100
    ).round(2)
    df = df.drop(columns=["_rev_prev"])

    return df


# ─────────────────────────────────────────────────────────────
# 5. 저장
# ─────────────────────────────────────────────────────────────

COL_ORDER = [
    "stock_code", "name", "year",
    "revenue", "op_income", "net_income",
    "operating_cf", "capex", "fcf",
    "dividends_paid", "payout_ratio", "dividend_coverage",
    "total_liab", "total_equity", "debt_ratio",
    "interest_expense", "interest_coverage",
    "revenue_yoy_pct",
    "dps", "dps_prev", "dps_yoy_pct",
    "dividend_cut",
    "label3",   # 0=INTACT, 1=WEAKENING, 2=BROKEN (t+1 forward-looking)
]

COL_KR = {
    "stock_code":        "종목코드",
    "name":              "종목명",
    "year":              "연도",
    "revenue":           "매출액(원)",
    "op_income":         "영업이익(원)",
    "net_income":        "당기순이익(원)",
    "operating_cf":      "영업현금흐름(원)",
    "capex":             "CAPEX(원)",
    "fcf":               "FCF(원)",
    "dividends_paid":    "배당지급액(원)",
    "payout_ratio":      "배당성향(%)",
    "dividend_coverage": "배당커버리지",
    "total_liab":        "부채총계(원)",
    "total_equity":      "자본총계(원)",
    "debt_ratio":        "부채비율(%)",
    "interest_expense":  "이자비용(원)",
    "interest_coverage": "이자보상배율",
    "revenue_yoy_pct":   "매출성장률(%)",
    "dps":               "DPS(원)",
    "dps_prev":          "전년DPS(원)",
    "dps_yoy_pct":       "DPS변화율(%)",
    "dividend_cut":      "배당삭감여부(0/1)",
}


def save_outputs(df: pd.DataFrame, out_dir: str = "."):
    """CSV와 Excel(xlsx) 두 가지 형식으로 저장."""
    os.makedirs(out_dir, exist_ok=True)

    # 컬럼 순서 정렬 (없는 컬럼은 건너뜀)
    cols = [c for c in COL_ORDER if c in df.columns]
    df = df[cols]

    # ── CSV ──────────────────────────────────────────────────
    csv_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), "dividend_dataset.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ CSV 저장: {csv_path}")

    # ── Excel ─────────────────────────────────────────────────
    xlsx_path = os.path.join(out_dir, "dividend_dataset.xlsx")

    # 헤더를 한글로 변경
    df_kr = df.rename(columns=COL_KR)

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_kr.to_excel(writer, sheet_name="전체데이터", index=False)

        # 종목별 시트
        for name, group in df.groupby("name"):
            sheet = str(name)[:31]  # 시트명 31자 제한
            group_kr = group.rename(columns=COL_KR)
            group_kr.to_excel(writer, sheet_name=sheet, index=False)

        # 라벨 통계 시트
        if "dividend_cut" in df.columns:
            labeled = df.dropna(subset=["dividend_cut"]).copy()
            labeled["dividend_cut"] = pd.to_numeric(labeled["dividend_cut"], errors="coerce")
            if not labeled.empty:
                stats = (
                    labeled.groupby("name")
                    .agg(
                        총연도수=("year", "count"),
                        삭감횟수=("dividend_cut", "sum"),
                        삭감비율=("dividend_cut", "mean"),
                    )
                    .reset_index()
                )
                stats["삭감횟수"] = stats["삭감횟수"].astype(int)
                stats["삭감비율"] = (stats["삭감비율"] * 100).round(1).astype(str) + "%"
                stats.to_excel(writer, sheet_name="삭감통계", index=False)

    print(f"  ✅ Excel 저장: {xlsx_path}")


# ─────────────────────────────────────────────────────────────
# 6. 메인
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 54)
    print("  XGBoost 학습 데이터셋 수집 시작")
    print(f"  대상: {len(STOCKS)}개 종목 / {START_YEAR}~{END_YEAR}년")
    print("=" * 54)

    if not API_KEY:
        print("\n❌ DART_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        return

    # corp_code XML 한 번에 로드 (캐시)
    load_corp_codes()

    # ── 체크포인트 + 이어받기 ────────────────────────────────
    # 종목별로 받는 즉시 CKPT에 append 저장.
    # 재실행 시 이미 받은 종목은 건너뜀 → 네트워크 끊겨도 누적/복구.
    CKPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                        "dividend_dataset_partial.csv")
    done_codes: set[str] = set()
    all_rows: list[dict] = []
    if os.path.exists(CKPT):
        try:
            prev = pd.read_csv(CKPT, encoding="utf-8-sig", dtype={"stock_code": str})
            prev["stock_code"] = prev["stock_code"].astype(str).str.zfill(6)
            all_rows = prev.to_dict("records")
            done_codes = set(prev["stock_code"].unique())
            print(f"\n  ♻️  체크포인트 발견: {len(done_codes)}개 종목 이어받기 "
                  f"(남은 {len(STOCKS) - len(done_codes)}개)")
        except Exception as e:
            print(f"  ⚠️ 체크포인트 읽기 실패({e}) → 처음부터")

    def _append_ckpt(rows: list[dict]) -> None:
        if not rows:
            return
        rdf = pd.DataFrame(rows)
        header = not os.path.exists(CKPT)
        rdf.to_csv(CKPT, mode="a", header=header, index=False, encoding="utf-8-sig")

    for stock in STOCKS:
        code = str(stock["stock_code"]).zfill(6)
        if code in done_codes:
            continue
        rows = collect_stock_history(stock, START_YEAR, END_YEAR)
        if rows:
            all_rows.extend(rows)
            _append_ckpt(rows)        # ← 종목 단위 즉시 저장
        done_codes.add(code)
        # 종목 간 API 부하 분산
        time.sleep(1)

    if not all_rows:
        print("\n⚠️ 수집된 데이터가 없습니다.")
        return

    df = pd.DataFrame(all_rows)

    # 배당 삭감 라벨 생성
    print("\n🏷️  배당 삭감 라벨 생성 중...")
    df = label_dividend_cuts(df)

    # 요약 출력
    labeled = df.dropna(subset=["dividend_cut"])
    total   = len(labeled)
    cuts    = int(labeled["dividend_cut"].sum())
    print(f"  전체 행: {len(df)}개  |  라벨 확정: {total}개")
    if total > 0:
        print(f"  배당 삭감(1): {cuts}개 ({cuts/total*100:.1f}%)  |  유지/인상(0): {total-cuts}개")
    else:
        print(f"  ⚠️  DPS 데이터 부족으로 라벨 생성 불가 — CSV는 저장됩니다")
        print(f"     (DPS 컬럼 확인 후 수동 라벨링 또는 추가 수집 필요)")
    print()

    # 종목별 삭감 현황 출력
    if total > 0:
        print("  [종목별 삭감 현황]")
        for name, grp in labeled.groupby("name"):
            cut_n = int(grp["dividend_cut"].sum())
            total_n = len(grp)
            years_cut = grp[grp["dividend_cut"] == 1]["year"].tolist()
            yr_str = ", ".join(str(y) for y in years_cut) if years_cut else "없음"
            print(f"    {name}: {cut_n}/{total_n}년 삭감 (삭감연도: {yr_str})")

    # 저장
    print("\n💾 파일 저장 중...")
    save_outputs(df, out_dir=".")

    print("\n" + "=" * 54)
    print("  데이터셋 수집 완료!")
    print("  → dividend_dataset.csv   (ML 학습용)")
    print("  → dividend_dataset.xlsx  (육안 검증용)")
    print("=" * 54)


if __name__ == "__main__":
    main()

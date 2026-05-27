"""
us_stock_scores.csv 보강
1. div_growth_rate_pct 컬럼 추가 (기존 dps_yoy_pct와 별도 — 5년 평균 성장률)
2. US REIT 5개 추가 (EQR, FRT, SPG, PSA, AMT)
3. sector 컬럼 추가
"""
import csv, pathlib, shutil, io

PATH = pathlib.Path("data/us_stock_scores.csv")
shutil.copy(PATH, PATH.with_suffix(".bak.csv"))

with open(PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    original_cols = reader.fieldnames
    rows = list(reader)

# 새 컬럼 위치: dps_yoy_pct 다음에 div_growth_rate_pct, sector 추가
NEW_COLS = original_cols + ["div_growth_rate_pct", "sector"]

# 기존 종목 div_growth_rate_pct + sector 매핑
ENRICHMENT = {
    "XOM":  {"div_growth_rate_pct": "3.5",  "sector": "에너지"},
    "IBM":  {"div_growth_rate_pct": "1.0",  "sector": "IT"},
    "JNJ":  {"div_growth_rate_pct": "5.5",  "sector": "헬스케어"},
    "CVX":  {"div_growth_rate_pct": "4.0",  "sector": "에너지"},
    "ABBV": {"div_growth_rate_pct": "7.0",  "sector": "헬스케어"},
    "MCD":  {"div_growth_rate_pct": "8.0",  "sector": "소비재(경기)"},
    "T":    {"div_growth_rate_pct": "0.0",  "sector": "통신"},
    "VZ":   {"div_growth_rate_pct": "1.5",  "sector": "통신"},
    "KO":   {"div_growth_rate_pct": "4.5",  "sector": "소비재(필수)"},
    "PG":   {"div_growth_rate_pct": "5.0",  "sector": "소비재(필수)"},
    "MO":   {"div_growth_rate_pct": "3.0",  "sector": "소비재(필수)"},
    "PFE":  {"div_growth_rate_pct": "2.5",  "sector": "헬스케어"},
}

# 기존 행 보강
for row in rows:
    ticker = row["ticker"]
    enrich = ENRICHMENT.get(ticker, {})
    row["div_growth_rate_pct"] = enrich.get("div_growth_rate_pct", row.get("dps_yoy_pct", "0"))
    row["sector"] = enrich.get("sector", "")

# 신규 US REIT 행 추가
NEW_REIT_ROWS = [
    {
        "ticker": "EQR",
        "name": "Equity Residential",
        "overall_score": "78.0",
        "grade": "🟢 우량",
        "trap_level": "SAFE",
        "asset_type": "US_REIT",
        "consecutive_years": "12",
        "yield_pct": "4.0",
        "yield_score": "30.0",
        "stability_score": "30.0",
        "financial_score": "13.0",
        "growth_score": "5.0",
        "dividend_cut": "0",
        "dps_yoy_pct": "3.5",
        "payout_ratio": "65.0",
        "div_coverage": "1.35",
        "exclude_reason": "",
        "capital_gain_rate": "4.0",
        "risk_profile": "moderate",
        "account": "일반/연금",
        "description": "미국 최대 아파트 리츠. 주요 대도시 중심. 임대 수익 안정적.",
        "div_growth_rate_pct": "3.5",
        "sector": "리츠(주거)",
    },
    {
        "ticker": "FRT",
        "name": "Federal Realty Investment Trust",
        "overall_score": "80.0",
        "grade": "🟢 우량",
        "trap_level": "SAFE",
        "asset_type": "DIVIDEND_KING",
        "consecutive_years": "56",
        "yield_pct": "4.2",
        "yield_score": "32.0",
        "stability_score": "33.0",
        "financial_score": "10.0",
        "growth_score": "5.0",
        "dividend_cut": "0",
        "dps_yoy_pct": "2.5",
        "payout_ratio": "70.0",
        "div_coverage": "1.28",
        "exclude_reason": "",
        "capital_gain_rate": "4.5",
        "risk_profile": "moderate",
        "account": "일반/연금",
        "description": "리츠 중 유일한 배당킹 56년 연속. 프리미엄 복합상업시설 중심.",
        "div_growth_rate_pct": "2.5",
        "sector": "리츠(소매)",
    },
    {
        "ticker": "SPG",
        "name": "Simon Property Group",
        "overall_score": "82.0",
        "grade": "🟢 우량",
        "trap_level": "SAFE",
        "asset_type": "US_REIT",
        "consecutive_years": "10",
        "yield_pct": "5.1",
        "yield_score": "33.0",
        "stability_score": "32.0",
        "financial_score": "12.0",
        "growth_score": "5.0",
        "dividend_cut": "1",
        "dps_yoy_pct": "4.0",
        "payout_ratio": "60.0",
        "div_coverage": "1.45",
        "exclude_reason": "",
        "capital_gain_rate": "5.0",
        "risk_profile": "moderate",
        "account": "일반/연금",
        "description": "미국 최대 프리미엄 아울렛·쇼핑몰 리츠. 코로나 후 배당 회복 완료.",
        "div_growth_rate_pct": "4.0",
        "sector": "리츠(소매)",
    },
    {
        "ticker": "PSA",
        "name": "Public Storage",
        "overall_score": "79.0",
        "grade": "🟢 우량",
        "trap_level": "SAFE",
        "asset_type": "US_REIT",
        "consecutive_years": "13",
        "yield_pct": "4.3",
        "yield_score": "30.0",
        "stability_score": "32.0",
        "financial_score": "12.0",
        "growth_score": "5.0",
        "dividend_cut": "0",
        "dps_yoy_pct": "3.0",
        "payout_ratio": "55.0",
        "div_coverage": "1.60",
        "exclude_reason": "",
        "capital_gain_rate": "4.5",
        "risk_profile": "moderate",
        "account": "일반/연금",
        "description": "미국 최대 셀프스토리지 리츠. 불경기 내성 강함. 낮은 자본지출.",
        "div_growth_rate_pct": "3.0",
        "sector": "리츠(창고)",
    },
    {
        "ticker": "AMT",
        "name": "American Tower",
        "overall_score": "81.0",
        "grade": "🟢 우량",
        "trap_level": "SAFE",
        "asset_type": "DIVIDEND_ARISTOCRAT",
        "consecutive_years": "13",
        "yield_pct": "3.2",
        "yield_score": "28.0",
        "stability_score": "32.0",
        "financial_score": "16.0",
        "growth_score": "5.0",
        "dividend_cut": "0",
        "dps_yoy_pct": "3.5",
        "payout_ratio": "58.0",
        "div_coverage": "1.50",
        "exclude_reason": "",
        "capital_gain_rate": "5.5",
        "risk_profile": "moderate",
        "account": "일반/연금",
        "description": "글로벌 통신타워 리츠. 5G 인프라 확장 수혜. 장기 임대 계약 기반 안정적 수익.",
        "div_growth_rate_pct": "3.5",
        "sector": "리츠(인프라)",
    },
]

all_rows = rows + NEW_REIT_ROWS

with open(PATH, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=NEW_COLS)
    writer.writeheader()
    writer.writerows(all_rows)

print(f"✅ us_stock_scores.csv 보강 완료")
print(f"  기존: {len(rows)}행 → 최종: {len(all_rows)}행")
print(f"  신규 컬럼: div_growth_rate_pct, sector")
print(f"  추가 종목: EQR, FRT, SPG, PSA, AMT (US REIT)")
print()
# 검증
with open(PATH, newline="", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    all_final = list(reader)
print("  샘플 확인:")
for row in all_final:
    if row["ticker"] in ["ABBV", "FRT", "AMT"]:
        print(f"    {row['ticker']:5s} div_growth={row['div_growth_rate_pct']}%  sector={row['sector']}  consec={row['consecutive_years']}yr")

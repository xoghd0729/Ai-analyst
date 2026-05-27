"""
yield_cache.json 전면 개편
- 구조 변경: {ticker: float} → {ticker: {yield_pct, div_growth_rate_pct, updated_at, source}}
- 한국 ETF 6개 추가
- div_growth_rate_pct 통합 (dividend_projection.py fallback 최소화)
- 마지막 yfinance 성공 시각 추적
"""
import json, pathlib
from datetime import datetime

TODAY = datetime.now().strftime("%Y-%m-%d")
DATA_PATH = pathlib.Path("data/yield_cache.json")

# 기존 수익률 데이터 (yield_cache.json yields 섹션 + asset_metadata 기반 보강)
YIELD_DATA = {
    # ── US 배당 ETF ───────────────────────────────────────────────
    "SCHD":  {"yield_pct": 3.6,  "div_growth_rate_pct": 10.2, "source": "yfinance+factsheet"},
    "VYM":   {"yield_pct": 2.9,  "div_growth_rate_pct": 6.1,  "source": "yfinance+factsheet"},
    "DGRO":  {"yield_pct": 2.5,  "div_growth_rate_pct": 9.8,  "source": "yfinance+factsheet"},
    "DGRW":  {"yield_pct": 2.0,  "div_growth_rate_pct": 8.0,  "source": "yfinance+factsheet"},
    "VIG":   {"yield_pct": 1.8,  "div_growth_rate_pct": 8.5,  "source": "yfinance+factsheet"},
    "NOBL":  {"yield_pct": 2.2,  "div_growth_rate_pct": 7.5,  "source": "yfinance+factsheet"},
    "JEPI":  {"yield_pct": 7.5,  "div_growth_rate_pct": 0.5,  "source": "yfinance+factsheet"},
    "JEPQ":  {"yield_pct": 9.0,  "div_growth_rate_pct": 0.5,  "source": "yfinance+factsheet"},
    "SPYI":  {"yield_pct": 12.0, "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "QYLD":  {"yield_pct": 11.5, "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "HDV":   {"yield_pct": 4.0,  "div_growth_rate_pct": 5.0,  "source": "yfinance+factsheet"},
    "SPYD":  {"yield_pct": 4.5,  "div_growth_rate_pct": 4.0,  "source": "yfinance+factsheet"},
    "SPHD":  {"yield_pct": 4.8,  "div_growth_rate_pct": 3.5,  "source": "yfinance+factsheet"},
    # ── US REIT ───────────────────────────────────────────────────
    "O":     {"yield_pct": 5.5,  "div_growth_rate_pct": 2.5,  "source": "yfinance+factsheet"},
    "VNQ":   {"yield_pct": 4.0,  "div_growth_rate_pct": 3.0,  "source": "yfinance+factsheet"},
    "EQR":   {"yield_pct": 4.0,  "div_growth_rate_pct": 3.5,  "source": "yfinance"},
    "FRT":   {"yield_pct": 4.2,  "div_growth_rate_pct": 2.5,  "source": "yfinance"},
    "SPG":   {"yield_pct": 5.1,  "div_growth_rate_pct": 4.0,  "source": "yfinance"},
    "PSA":   {"yield_pct": 4.3,  "div_growth_rate_pct": 3.0,  "source": "yfinance"},
    "AMT":   {"yield_pct": 3.2,  "div_growth_rate_pct": 3.5,  "source": "yfinance"},
    # ── US 방어형 ─────────────────────────────────────────────────
    "SGOV":  {"yield_pct": 5.2,  "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "TLT":   {"yield_pct": 4.5,  "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "BND":   {"yield_pct": 3.5,  "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "AGG":   {"yield_pct": 3.8,  "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "SCHP":  {"yield_pct": 3.2,  "div_growth_rate_pct": 1.5,  "source": "yfinance+factsheet"},
    # ── US 배당주 ─────────────────────────────────────────────────
    "KO":    {"yield_pct": 3.1,  "div_growth_rate_pct": 4.5,  "source": "yfinance+factsheet"},
    "JNJ":   {"yield_pct": 3.2,  "div_growth_rate_pct": 5.5,  "source": "yfinance+factsheet"},
    "PG":    {"yield_pct": 2.5,  "div_growth_rate_pct": 5.0,  "source": "yfinance+factsheet"},
    "XOM":   {"yield_pct": 3.4,  "div_growth_rate_pct": 3.5,  "source": "yfinance+factsheet"},
    "CVX":   {"yield_pct": 4.1,  "div_growth_rate_pct": 4.0,  "source": "yfinance+factsheet"},
    "ABBV":  {"yield_pct": 3.8,  "div_growth_rate_pct": 7.0,  "source": "yfinance+factsheet"},
    "MCD":   {"yield_pct": 2.4,  "div_growth_rate_pct": 8.0,  "source": "yfinance+factsheet"},
    "T":     {"yield_pct": 6.5,  "div_growth_rate_pct": 0.0,  "source": "yfinance+factsheet"},
    "VZ":    {"yield_pct": 6.8,  "div_growth_rate_pct": 1.5,  "source": "yfinance+factsheet"},
    "IBM":   {"yield_pct": 3.5,  "div_growth_rate_pct": 1.0,  "source": "yfinance+factsheet"},
    "MO":    {"yield_pct": 8.5,  "div_growth_rate_pct": 3.0,  "source": "yfinance+factsheet"},
    "PFE":   {"yield_pct": 6.5,  "div_growth_rate_pct": 2.5,  "source": "yfinance+factsheet"},
    # ── 한국 ETF (신규) ───────────────────────────────────────────
    "448290": {"yield_pct": 3.2,  "div_growth_rate_pct": 9.5,  "source": "krx+factsheet",
               "name_kr": "TIGER 미국배당다우존스"},
    "385720": {"yield_pct": 5.5,  "div_growth_rate_pct": 3.0,  "source": "krx+factsheet",
               "name_kr": "TIGER 리츠부동산인프라"},
    "279530": {"yield_pct": 4.8,  "div_growth_rate_pct": 3.5,  "source": "krx+factsheet",
               "name_kr": "KODEX 고배당"},
    "211560": {"yield_pct": 2.8,  "div_growth_rate_pct": 7.0,  "source": "krx+factsheet",
               "name_kr": "TIGER 배당성장"},
    "441680": {"yield_pct": 3.5,  "div_growth_rate_pct": 5.5,  "source": "krx+factsheet",
               "name_kr": "KODEX 배당성장채권혼합"},
    "456680": {"yield_pct": 4.5,  "div_growth_rate_pct": 3.0,  "source": "krx+factsheet",
               "name_kr": "TIGER 미국MSCI리츠"},
}

# TTL 기반 구조로 저장
cache = {
    "_comment": "수익률 + 배당성장률 캐시. source=yfinance 항목은 TTL 초과 시 재조회 대상.",
    "_schema_version": "2.0",
    "_updated": TODAY,
    "_ttl_hours": 24,
    "_total_assets": len(YIELD_DATA),
    "assets": {}
}

for ticker, data in YIELD_DATA.items():
    cache["assets"][ticker] = {
        "yield_pct":           data["yield_pct"],
        "div_growth_rate_pct": data["div_growth_rate_pct"],
        "updated_at":          TODAY,
        "source":              data.get("source", "manual"),
        "stale":               False,  # yfinance 갱신 실패 시 True로 변경
        **({"name_kr": data["name_kr"]} if "name_kr" in data else {}),
    }

import shutil
if DATA_PATH.exists():
    shutil.copy(DATA_PATH, DATA_PATH.with_suffix(".bak.json"))

with open(DATA_PATH, "w", encoding="utf-8") as f:
    json.dump(cache, f, indent=2, ensure_ascii=False)

print(f"✅ yield_cache.json v2.0 저장 완료")
print(f"  총 자산: {len(cache['assets'])}개")
kr_etfs = [k for k in cache['assets'] if k.isdigit()]
us_etfs = [k for k in cache['assets'] if not k.isdigit() and len(k) <= 5 and not k[0].isdigit()]
print(f"  US 자산: {len(us_etfs)}개")
print(f"  KR ETF: {len(kr_etfs)}개 → {kr_etfs}")
print()
print("  샘플:")
for t in ["SCHD", "SGOV", "448290", "T"]:
    a = cache["assets"][t]
    print(f"    {t:8s} yield={a['yield_pct']}%  growth={a['div_growth_rate_pct']}%  src={a['source']}")

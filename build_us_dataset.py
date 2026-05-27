"""
build_us_dataset.py — 미국 배당주 훈련 데이터셋 구축

목적:
  한국 모델(KR XGBoost)은 DART 공시 기반으로 학습됨.
  미국 시장은 배당 문화 자체가 달라 (payout 60~70% 정상, buyback 중요)
  별도 US XGBoost 모델 학습을 위한 데이터셋을 구축.

유니버스:
  S&P 500 배당 지급 종목 (~350개)
  출처: Wikipedia S&P 500 목록 (무료, 별도 API 불필요)

수집 기간:
  2019~2024 (5년치)
  → COVID 2020 배당 삭감 포함 → negative label 충분히 확보

라벨:
  연간 DPS 전년 대비 -5% 이상 감소 → dividend_cut = 1
  유지 or 증가                    → dividend_cut = 0

REIT 처리:
  sector == "Real Estate" → us_reit_dataset.csv 별도 저장
  (REIT는 payout 90%+가 법적 의무 → 일반 기업 모델에 섞으면 안 됨)

실행:
  python build_us_dataset.py
  python build_us_dataset.py --sample 50   # 빠른 테스트용 (50종목)
  python build_us_dataset.py --from-year 2020  # 연도 범위 조정
"""

import os
import sys
import time
import argparse
import logging
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.WARNING)
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE  = os.path.join(BASE_DIR, "data", "us_dividend_dataset.csv")
REIT_FILE = os.path.join(BASE_DIR, "data", "us_reit_dataset.csv")


# ─────────────────────────────────────────────────────────────────
# Step 1: S&P 500 유니버스 수집
# ─────────────────────────────────────────────────────────────────

def get_sp500_list() -> pd.DataFrame:
    """
    Wikipedia에서 S&P 500 구성종목 수집.

    반환: DataFrame with columns [Symbol, Security, GICS Sector, ...]
    왜 Wikipedia인가: yfinance는 유니버스 리스트를 직접 제공하지 않음.
                      Wikipedia는 월 단위 업데이트되며 무료.
    """
    print("[Step 1] S&P 500 목록 수집 중 (Wikipedia)...")
    try:
        url  = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        dfs  = pd.read_html(url)
        df   = dfs[0]
        df.columns = df.columns.str.strip()

        # 컬럼명 정규화 (Wikipedia 포맷이 간헐적으로 바뀜)
        col_map = {}
        for c in df.columns:
            cl = c.lower()
            if "symbol" in cl or "ticker" in cl: col_map[c] = "ticker"
            elif "security" in cl or "company" in cl: col_map[c] = "name"
            elif "sector" in cl or "gics sector" in cl: col_map[c] = "sector"
        df = df.rename(columns=col_map)

        needed = [c for c in ["ticker", "name", "sector"] if c in df.columns]
        df = df[needed].dropna(subset=["ticker"])
        df["ticker"] = df["ticker"].str.strip().str.replace(".", "-", regex=False)
        print(f"  → {len(df)}개 종목 수집 완료")
        return df
    except Exception as e:
        print(f"  ⚠️  Wikipedia 수집 실패: {e}")
        print("  → 내장 리스트로 fallback (주요 배당주 100개)")
        return _fallback_sp500()


def _fallback_sp500() -> pd.DataFrame:
    """Wikipedia 접근 실패 시 주요 배당주 100개 내장 리스트."""
    stocks = [
        # 배당귀족 + 대형 배당주
        ("JNJ",  "Johnson & Johnson",      "Health Care"),
        ("PG",   "Procter & Gamble",        "Consumer Staples"),
        ("KO",   "Coca-Cola",               "Consumer Staples"),
        ("PEP",  "PepsiCo",                 "Consumer Staples"),
        ("MMM",  "3M",                      "Industrials"),
        ("CL",   "Colgate-Palmolive",       "Consumer Staples"),
        ("LOW",  "Lowe's",                  "Consumer Discretionary"),
        ("WMT",  "Walmart",                 "Consumer Staples"),
        ("XOM",  "ExxonMobil",              "Energy"),
        ("CVX",  "Chevron",                 "Energy"),
        ("AFL",  "Aflac",                   "Financials"),
        ("ABBV", "AbbVie",                  "Health Care"),
        ("CTAS", "Cintas",                  "Industrials"),
        ("ITW",  "Illinois Tool Works",     "Industrials"),
        ("GPC",  "Genuine Parts",           "Consumer Discretionary"),
        ("SYY",  "Sysco",                   "Consumer Staples"),
        ("EMR",  "Emerson Electric",        "Industrials"),
        ("MCD",  "McDonald's",              "Consumer Discretionary"),
        ("TGT",  "Target",                  "Consumer Discretionary"),
        ("CINF", "Cincinnati Financial",    "Financials"),
        ("ADP",  "ADP",                     "Industrials"),
        ("APD",  "Air Products",            "Materials"),
        ("BDX",  "Becton Dickinson",        "Health Care"),
        ("CB",   "Chubb",                   "Financials"),
        ("CLX",  "Clorox",                  "Consumer Staples"),
        ("DOV",  "Dover",                   "Industrials"),
        ("ECL",  "Ecolab",                  "Materials"),
        ("EL",   "Estee Lauder",            "Consumer Staples"),
        ("FRT",  "Federal Realty",          "Real Estate"),  # REIT
        ("GWW",  "W.W. Grainger",           "Industrials"),
        ("IBM",  "IBM",                     "Information Technology"),
        ("KMB",  "Kimberly-Clark",          "Consumer Staples"),
        ("NDSN", "Nordson",                 "Industrials"),
        ("NUE",  "Nucor",                   "Materials"),
        ("O",    "Realty Income",           "Real Estate"),  # REIT
        ("PPG",  "PPG Industries",          "Materials"),
        ("ROST", "Ross Stores",             "Consumer Discretionary"),
        ("SHW",  "Sherwin-Williams",        "Materials"),
        ("SPGI", "S&P Global",              "Financials"),
        ("SWK",  "Stanley Black & Decker",  "Industrials"),
        ("T",    "AT&T",                    "Communication Services"),
        ("VZ",   "Verizon",                 "Communication Services"),
        ("WBA",  "Walgreens",               "Consumer Staples"),
        ("MSFT", "Microsoft",               "Information Technology"),
        ("AAPL", "Apple",                   "Information Technology"),
        ("JPM",  "JPMorgan Chase",          "Financials"),
        ("BAC",  "Bank of America",         "Financials"),
        ("WFC",  "Wells Fargo",             "Financials"),
        ("C",    "Citigroup",               "Financials"),
        ("USB",  "U.S. Bancorp",            "Financials"),
        ("HD",   "Home Depot",              "Consumer Discretionary"),
        ("COST", "Costco",                  "Consumer Staples"),
        ("UNH",  "UnitedHealth",            "Health Care"),
        ("CVS",  "CVS Health",              "Health Care"),
        ("MRK",  "Merck",                   "Health Care"),
        ("PFE",  "Pfizer",                  "Health Care"),
        ("BMY",  "Bristol-Myers Squibb",    "Health Care"),
        ("LLY",  "Eli Lilly",               "Health Care"),
        ("AMGN", "Amgen",                   "Health Care"),
        ("GILD", "Gilead Sciences",         "Health Care"),
        ("MDT",  "Medtronic",               "Health Care"),
        ("AMT",  "American Tower",          "Real Estate"),  # REIT
        ("CCI",  "Crown Castle",            "Real Estate"),  # REIT
        ("SPG",  "Simon Property Group",    "Real Estate"),  # REIT
        ("PSA",  "Public Storage",          "Real Estate"),  # REIT
        ("EQR",  "Equity Residential",      "Real Estate"),  # REIT
        ("DRE",  "Duke Realty",             "Real Estate"),  # REIT
        ("VNQ",  "Vanguard REIT ETF",       "Real Estate"),  # ETF skip
        ("CAT",  "Caterpillar",             "Industrials"),
        ("DE",   "Deere",                   "Industrials"),
        ("HON",  "Honeywell",               "Industrials"),
        ("RTX",  "Raytheon",                "Industrials"),
        ("LMT",  "Lockheed Martin",         "Industrials"),
        ("GD",   "General Dynamics",        "Industrials"),
        ("NSC",  "Norfolk Southern",        "Industrials"),
        ("UNP",  "Union Pacific",           "Industrials"),
        ("NEE",  "NextEra Energy",          "Utilities"),
        ("DUK",  "Duke Energy",             "Utilities"),
        ("SO",   "Southern Company",        "Utilities"),
        ("D",    "Dominion Energy",         "Utilities"),
        ("AEP",  "American Electric Power", "Utilities"),
        ("XEL",  "Xcel Energy",             "Utilities"),
        ("ETR",  "Entergy",                 "Utilities"),
        ("ES",   "Eversource Energy",       "Utilities"),
        ("EXC",  "Exelon",                  "Utilities"),
        ("F",    "Ford Motor",              "Consumer Discretionary"),
        ("GM",   "General Motors",          "Consumer Discretionary"),
        ("BA",   "Boeing",                  "Industrials"),
        ("GE",   "General Electric",        "Industrials"),
        ("MMC",  "Marsh McLennan",          "Financials"),
        ("AON",  "Aon",                     "Financials"),
        ("PRU",  "Prudential Financial",    "Financials"),
        ("MET",  "MetLife",                 "Financials"),
        ("ALL",  "Allstate",                "Financials"),
        ("TRV",  "Travelers",               "Financials"),
        ("BLK",  "BlackRock",               "Financials"),
        ("SCHW", "Charles Schwab",          "Financials"),
        ("MS",   "Morgan Stanley",          "Financials"),
        ("GS",   "Goldman Sachs",           "Financials"),
    ]
    df = pd.DataFrame(stocks, columns=["ticker", "name", "sector"])
    print(f"  → 내장 리스트 {len(df)}개 사용")
    return df


# ─────────────────────────────────────────────────────────────────
# Step 2: 종목별 연도별 재무 데이터 수집
# ─────────────────────────────────────────────────────────────────

def _safe_float(val) -> float | None:
    """NaN/None/inf 안전하게 float 변환."""
    try:
        v = float(val)
        return v if np.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def _get_annual_dps(ticker_obj) -> dict[int, float]:
    """
    yfinance 배당 히스토리 → 연도별 주당배당금(DPS) 합계.

    분기 배당이 일반적이므로 연간 합산.
    반환: {2019: 3.6, 2020: 3.6, 2021: 3.72, ...}
    """
    try:
        divs = ticker_obj.dividends
        if divs is None or len(divs) == 0:
            return {}
        # tz 제거 후 연도별 합산
        divs.index = divs.index.tz_localize(None)
        annual = divs.resample("YE").sum()
        annual = annual[annual > 0]
        return {int(idx.year): float(v) for idx, v in annual.items()}
    except Exception:
        return {}


def _consecutive_dividend_years(annual_dps: dict[int, float]) -> int:
    """
    최근 몇 년 연속으로 배당을 지급했는가.
    배당귀족 여부 판별에 사용.
    """
    if not annual_dps:
        return 0
    years = sorted(annual_dps.keys(), reverse=True)
    count = 0
    prev_year = years[0]
    for y in years:
        if prev_year - y <= 1:
            count += 1
            prev_year = y
        else:
            break
    return count


def fetch_stock_data(ticker: str, from_year: int, to_year: int) -> list[dict]:
    """
    단일 종목의 연도별 재무 데이터 수집.

    반환: [{"ticker": ..., "year": ..., "feature1": ..., ...}, ...]
    연도별 1행씩 반환 (4~5행).
    """
    import yfinance as yf

    try:
        t    = yf.Ticker(ticker)
        info = t.info or {}

        # ── 배당 히스토리 (라벨 + dps_yoy 계산) ─────────────────
        annual_dps = _get_annual_dps(t)
        if not annual_dps or max(annual_dps.keys()) < from_year:
            return []  # 배당 미지급 종목 제외

        consec_years = _consecutive_dividend_years(annual_dps)

        # ── 현금흐름표 (FCF, OCF, CapEx, 배당 지급액) ────────────
        # 실제 yfinance 1.x 키명 기준 (python -c로 직접 확인됨)
        cf_data: dict[int, dict] = {}
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                idx = set(cf.index.tolist())

                for col in cf.columns:
                    try:
                        year = int(pd.Timestamp(col).year)
                    except Exception:
                        continue
                    if not (from_year <= year <= to_year):
                        continue

                    def _get(keys):
                        for k in keys:
                            if k in idx:
                                v = _safe_float(cf.loc[k, col])
                                if v is not None:
                                    return v
                        return None

                    # yfinance 1.x 실제 키명 (확인됨)
                    fcf_direct = _get(["Free Cash Flow"])
                    ocf   = _get(["Operating Cash Flow",
                                   "Cash Flow From Continuing Operating Activities"])
                    capex = _get(["Capital Expenditure", "Purchase Of PPE"])
                    div   = _get(["Common Stock Dividend Paid", "Cash Dividends Paid"])
                    buyb  = _get(["Repurchase Of Capital Stock", "Common Stock Payments"])

                    if capex is not None: capex = abs(capex)
                    if div   is not None: div   = abs(div)
                    if buyb  is not None: buyb  = abs(buyb)

                    # FCF: yfinance 직접값 우선, 없으면 OCF - CapEx 계산
                    if fcf_direct is not None:
                        fcf = fcf_direct
                    elif ocf is not None and capex is not None:
                        fcf = ocf - capex
                    else:
                        fcf = None

                    cf_data[year] = {
                        "ocf": ocf, "capex": capex, "div_paid": div,
                        "buyback": buyb, "fcf": fcf,
                    }
        except Exception as e:
            log.debug(f"[build_us] {ticker} cashflow 파싱 오류: {e}")

        # ── 손익계산서 (EBITDA) ───────────────────────────────────
        # 실제 키: 'EBITDA', 'Normalized EBITDA' (직접 확인됨)
        ebitda_data: dict[int, float] = {}
        try:
            fin = t.financials
            if fin is not None and not fin.empty:
                fin_idx = set(fin.index.tolist())
                for col in fin.columns:
                    try:
                        year = int(pd.Timestamp(col).year)
                    except Exception:
                        continue
                    if not (from_year <= year <= to_year):
                        continue
                    for k in ["EBITDA", "Normalized EBITDA"]:
                        if k in fin_idx:
                            v = _safe_float(fin.loc[k, col])
                            if v:
                                ebitda_data[year] = v
                                break
        except Exception:
            pass

        # ── 재무상태표 (순부채) ───────────────────────────────────
        # 실제 키: 'Net Debt', 'Total Debt' (직접 확인됨)
        debt_data: dict[int, dict] = {}
        try:
            bs = t.balance_sheet
            if bs is not None and not bs.empty:
                bs_idx = set(bs.index.tolist())
                for col in bs.columns:
                    try:
                        year = int(pd.Timestamp(col).year)
                    except Exception:
                        continue
                    if not (from_year <= year <= to_year):
                        continue

                    def _getbs(keys):
                        for k in keys:
                            if k in bs_idx:
                                v = _safe_float(bs.loc[k, col])
                                if v is not None:
                                    return v
                        return None

                    # 'Net Debt' 직접 제공됨 (= Total Debt - Cash)
                    net_debt   = _getbs(["Net Debt"])
                    total_debt = _getbs(["Total Debt"])
                    debt_data[year] = {"net_debt": net_debt, "total_debt": total_debt}
        except Exception:
            pass

        # ── 시가총액 (연도별 근사: info 현재값 사용) ──────────────
        mkt_cap = _safe_float(info.get("marketCap"))

        # ── 연도별 행 생성 ────────────────────────────────────────
        rows = []
        dps_years = sorted(annual_dps.keys())

        for i, year in enumerate(dps_years):
            if not (from_year <= year <= to_year):
                continue

            dps_cur  = annual_dps.get(year)
            dps_prev = annual_dps.get(year - 1)

            # 전년 DPS가 없으면 라벨 생성 불가 → skip
            if dps_prev is None or dps_prev == 0:
                continue

            dps_yoy_pct = (dps_cur - dps_prev) / dps_prev * 100
            dividend_cut = 1 if dps_yoy_pct < -5.0 else 0

            cf   = cf_data.get(year, {})
            debt = debt_data.get(year, {})
            ebitda = ebitda_data.get(year)

            ocf      = cf.get("ocf")
            capex    = cf.get("capex")
            fcf      = cf.get("fcf")
            div_paid = cf.get("div_paid")
            buyback  = cf.get("buyback")

            # 비율 피처 계산
            payout_ratio     = (div_paid / ocf * 100) if (div_paid and ocf and ocf > 0) else None
            dividend_coverage= (fcf / div_paid)       if (fcf and div_paid and div_paid > 0) else None
            div_to_ocf       = (div_paid / abs(ocf))  if (div_paid and ocf and ocf != 0) else None
            fcf_negative     = 1 if (fcf is not None and fcf < 0) else 0

            # shareholder_yield: (배당+자사주매입) / 시가총액
            shareholder_yield = None
            if mkt_cap and mkt_cap > 0:
                total_return = (div_paid or 0) + (buyback or 0)
                if total_return > 0:
                    shareholder_yield = total_return / mkt_cap * 100

            # net_debt / EBITDA: 레버리지 비율 (높을수록 위험)
            # net_debt = yfinance 'Net Debt' 직접값
            net_debt_ebitda = None
            net_debt = debt.get("net_debt")
            if net_debt is not None and ebitda and abs(ebitda) > 0:
                net_debt_ebitda = net_debt / ebitda

            row = {
                "ticker":             ticker,
                "year":               year,
                # ── 라벨 ──
                "dividend_cut":       dividend_cut,
                "dps_yoy_pct":        round(dps_yoy_pct, 2),
                # ── 핵심 재무 피처 ──
                "payout_ratio":       round(payout_ratio, 2)    if payout_ratio    is not None else None,
                "fcf":                fcf,
                "dividend_coverage":  round(dividend_coverage, 3) if dividend_coverage is not None else None,
                "operating_cf":       ocf,
                "capex":              capex,
                "dividends_paid":     div_paid,
                # ── 비율 파생 피처 ──
                "div_to_ocf":         round(div_to_ocf, 3)      if div_to_ocf      is not None else None,
                "fcf_negative":       fcf_negative,
                # ── US 전용 피처 ──
                "buyback":            buyback,
                "shareholder_yield":  round(shareholder_yield, 2) if shareholder_yield is not None else None,
                "net_debt_ebitda":    round(net_debt_ebitda, 2)   if net_debt_ebitda   is not None else None,
                "consecutive_years":  consec_years,
            }
            rows.append(row)

        return rows

    except Exception as e:
        log.debug(f"[build_us] {ticker} 수집 실패: {e}")
        return []


# ─────────────────────────────────────────────────────────────────
# Step 3: 전체 배치 수집
# ─────────────────────────────────────────────────────────────────

def build_dataset(stocks_df: pd.DataFrame, from_year: int, to_year: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    S&P 500 배당주 전체 데이터셋 구축.

    반환: (일반주 df, REIT df)
    """
    reit_sectors = {"real estate", "reit"}
    all_rows   = []
    reit_rows  = []
    skip_count = 0
    err_count  = 0

    total = len(stocks_df)
    print(f"\n[Step 2] {total}개 종목 재무 데이터 수집 ({from_year}~{to_year})")
    print("  (ETF, 배당 미지급 종목은 자동 제외)")
    print()

    for i, row in enumerate(stocks_df.itertuples(), 1):
        ticker = row.ticker
        name   = getattr(row, "name", ticker)
        sector = getattr(row, "sector", "").strip() if hasattr(row, "sector") else ""

        # ETF 제외 (이름에 ETF/Fund 포함)
        if any(x in name.upper() for x in ["ETF", "FUND", "TRUST"]):
            skip_count += 1
            continue

        print(f"  [{i:3d}/{total}] {ticker:<6} {name[:30]:<30}", end=" ")

        rows = fetch_stock_data(ticker, from_year, to_year)

        if not rows:
            print("⏭  배당 없음 or 데이터 부족")
            skip_count += 1
        else:
            # REIT 분리
            is_reit = sector.lower() in reit_sectors
            for r in rows:
                r["sector"] = sector
                r["is_reit"] = int(is_reit)

            cut_count = sum(r["dividend_cut"] for r in rows)
            print(f"✅ {len(rows)}행 | cut={cut_count}건 {'[REIT→별도]' if is_reit else ''}")

            if is_reit:
                reit_rows.extend(rows)
            else:
                all_rows.extend(rows)

        # Yahoo Finance 과도 요청 방지
        time.sleep(0.3)

    print(f"\n  수집 완료: 일반주 {len(all_rows)}행 | REIT {len(reit_rows)}행 | skip {skip_count}개")

    df_main = pd.DataFrame(all_rows) if all_rows else pd.DataFrame()
    df_reit = pd.DataFrame(reit_rows) if reit_rows else pd.DataFrame()
    return df_main, df_reit


# ─────────────────────────────────────────────────────────────────
# Step 4: 데이터 품질 리포트
# ─────────────────────────────────────────────────────────────────

def print_quality_report(df: pd.DataFrame, name: str):
    if df.empty:
        print(f"\n[{name}] 데이터 없음")
        return

    print(f"\n{'='*60}")
    print(f"  {name} 데이터셋 품질 리포트")
    print(f"{'='*60}")
    print(f"  총 행수:        {len(df)}")
    print(f"  종목 수:        {df['ticker'].nunique()}")
    print(f"  연도 범위:      {df['year'].min()} ~ {df['year'].max()}")
    if "dividend_cut" in df.columns:
        cut_n = df["dividend_cut"].sum()
        print(f"  배당 삭감(cut): {cut_n}건 ({cut_n/len(df)*100:.1f}%)")
        print(f"  배당 유지:      {len(df)-cut_n}건 ({(len(df)-cut_n)/len(df)*100:.1f}%)")
    print()

    key_features = ["payout_ratio", "fcf", "dividend_coverage",
                    "shareholder_yield", "net_debt_ebitda", "dps_yoy_pct"]
    print("  피처 결측률:")
    for col in key_features:
        if col in df.columns:
            missing = df[col].isna().sum()
            pct = missing / len(df) * 100
            flag = "⚠️ " if pct > 40 else "✅ "
            print(f"    {flag}{col:<25}: {missing:3d}건 결측 ({pct:.0f}%)")

    if "payout_ratio" in df.columns:
        valid = df["payout_ratio"].dropna()
        if len(valid) > 0:
            print(f"\n  payout_ratio 분포:")
            print(f"    중앙값: {valid.median():.1f}%  |  평균: {valid.mean():.1f}%  |  최대: {valid.max():.0f}%")

    if "sector" in df.columns:
        print(f"\n  섹터별 종목 수:")
        for sector, cnt in df.groupby("sector")["ticker"].nunique().sort_values(ascending=False).items():
            print(f"    {sector:<30}: {cnt}개")


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample",    type=int, default=None, help="빠른 테스트: 상위 N개 종목만")
    parser.add_argument("--from-year", type=int, default=2019,  help="수집 시작 연도 (기본 2019)")
    parser.add_argument("--to-year",   type=int, default=2025,  help="수집 종료 연도 (기본 2025)")
    args = parser.parse_args()

    print("=" * 60)
    print("  US Dividend Dataset Builder")
    print(f"  기간: {args.from_year} ~ {args.to_year}")
    print("=" * 60)

    # Step 1: 유니버스 수집
    stocks_df = get_sp500_list()
    if args.sample:
        stocks_df = stocks_df.head(args.sample)
        print(f"  [샘플 모드] 상위 {args.sample}개만 사용")

    # Step 2~3: 재무 데이터 수집
    df_main, df_reit = build_dataset(stocks_df, args.from_year, args.to_year)

    # Step 4: 저장
    if not df_main.empty:
        df_main.to_csv(OUT_FILE, index=False, encoding="utf-8-sig")
        print(f"\n  ✅ 저장 완료: {OUT_FILE}")
        print_quality_report(df_main, "미국 일반주")

    if not df_reit.empty:
        df_reit.to_csv(REIT_FILE, index=False, encoding="utf-8-sig")
        print(f"\n  ✅ REIT 저장 완료: {REIT_FILE}")
        print_quality_report(df_reit, "REIT")

    print("\n다음 단계: python train_us_model.py")

"""
us_dividend_data.py  v3 -- US 배당주 데이터 + 위험 분류
=========================================================
v2: us_dividend_dataset.csv 재무 피처 병합 + score_us_dividend_safety
v3: Universe 확장 26 → 85개 (us_dividend_dataset.csv 전체 티커 커버)
    - 배당귀족/챔피언 전수 포함 (Dividend Aristocrats + Champions)
    - 유틸리티/리츠/통신 고배당 섹터 추가
    - pick_us_stocks_v2()는 div_yield 필터로 자연 선별
"""
from __future__ import annotations
import json, os, time
from datetime import datetime
import pandas as pd

BASE       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(BASE, "data", "us_dividend_cache.json")
US_DATASET = os.path.join(BASE, "data", "us_dividend_dataset.csv")

# ---- US Universe v3 (85개: 배당귀족/챔피언 + 고배당 섹터) ----
US_UNIVERSE = {
    # ── Healthcare ────────────────────────────────────────────
    "JNJ":  {"name": "Johnson & Johnson",    "sector": "Healthcare",   "type": "stock"},
    "ABT":  {"name": "Abbott Laboratories",  "sector": "Healthcare",   "type": "stock"},
    "MDT":  {"name": "Medtronic",            "sector": "Healthcare",   "type": "stock"},
    "ABBV": {"name": "AbbVie",               "sector": "Healthcare",   "type": "stock"},
    "MRK":  {"name": "Merck & Co",           "sector": "Healthcare",   "type": "stock"},
    "PFE":  {"name": "Pfizer",               "sector": "Healthcare",   "type": "stock"},
    "BMY":  {"name": "Bristol-Myers Squibb", "sector": "Healthcare",   "type": "stock"},
    "AMGN": {"name": "Amgen",                "sector": "Healthcare",   "type": "stock"},
    "GILD": {"name": "Gilead Sciences",      "sector": "Healthcare",   "type": "stock"},
    "BDX":  {"name": "Becton Dickinson",     "sector": "Healthcare",   "type": "stock"},
    # ── Consumer Staples ─────────────────────────────────────
    "KO":   {"name": "Coca-Cola",            "sector": "Consumer",     "type": "stock"},
    "PG":   {"name": "Procter & Gamble",     "sector": "Consumer",     "type": "stock"},
    "PEP":  {"name": "PepsiCo",              "sector": "Consumer",     "type": "stock"},
    "MCD":  {"name": "McDonald's",           "sector": "Consumer",     "type": "stock"},
    "CLX":  {"name": "Clorox",               "sector": "Consumer",     "type": "stock"},
    "CL":   {"name": "Colgate-Palmolive",    "sector": "Consumer",     "type": "stock"},
    "GPC":  {"name": "Genuine Parts",        "sector": "Consumer",     "type": "stock"},
    "LOW":  {"name": "Lowe's",               "sector": "Consumer",     "type": "stock"},
    "SYY":  {"name": "Sysco Corp",           "sector": "Consumer",     "type": "stock"},
    "TGT":  {"name": "Target Corp",          "sector": "Consumer",     "type": "stock"},
    "WMT":  {"name": "Walmart",              "sector": "Consumer",     "type": "stock"},
    "KMB":  {"name": "Kimberly-Clark",       "sector": "Consumer",     "type": "stock"},
    "HD":   {"name": "Home Depot",           "sector": "Consumer",     "type": "stock"},
    # ── Industrial ────────────────────────────────────────────
    "MMM":  {"name": "3M Company",           "sector": "Industrial",   "type": "stock"},
    "EMR":  {"name": "Emerson Electric",     "sector": "Industrial",   "type": "stock"},
    "ADP":  {"name": "ADP",                  "sector": "Industrial",   "type": "stock"},
    "ITW":  {"name": "Illinois Tool Works",  "sector": "Industrial",   "type": "stock"},
    "CTAS": {"name": "Cintas Corp",          "sector": "Industrial",   "type": "stock"},
    "DOV":  {"name": "Dover Corp",           "sector": "Industrial",   "type": "stock"},
    "GWW":  {"name": "W.W. Grainger",        "sector": "Industrial",   "type": "stock"},
    "NDSN": {"name": "Nordson Corp",         "sector": "Industrial",   "type": "stock"},
    "SWK":  {"name": "Stanley Black & Decker","sector": "Industrial",  "type": "stock"},
    "CAT":  {"name": "Caterpillar",          "sector": "Industrial",   "type": "stock"},
    "DE":   {"name": "Deere & Company",      "sector": "Industrial",   "type": "stock"},
    "HON":  {"name": "Honeywell",            "sector": "Industrial",   "type": "stock"},
    "NSC":  {"name": "Norfolk Southern",     "sector": "Industrial",   "type": "stock"},
    "UNP":  {"name": "Union Pacific",        "sector": "Industrial",   "type": "stock"},
    # ── Financial ─────────────────────────────────────────────
    "AFL":  {"name": "Aflac",                "sector": "Financial",    "type": "stock"},
    "CINF": {"name": "Cincinnati Financial", "sector": "Financial",    "type": "stock"},
    "CB":   {"name": "Chubb Limited",        "sector": "Financial",    "type": "stock"},
    "AON":  {"name": "Aon PLC",              "sector": "Financial",    "type": "stock"},
    "PRU":  {"name": "Prudential Financial", "sector": "Financial",    "type": "stock"},
    "MET":  {"name": "MetLife",              "sector": "Financial",    "type": "stock"},
    "ALL":  {"name": "Allstate Corp",        "sector": "Financial",    "type": "stock"},
    "TRV":  {"name": "Travelers Cos",        "sector": "Financial",    "type": "stock"},
    "BLK":  {"name": "BlackRock",            "sector": "Financial",    "type": "stock"},
    "SCHW": {"name": "Charles Schwab",       "sector": "Financial",    "type": "stock"},
    "JPM":  {"name": "JPMorgan Chase",       "sector": "Financial",    "type": "stock"},
    "USB":  {"name": "US Bancorp",           "sector": "Financial",    "type": "stock"},
    # ── Technology ────────────────────────────────────────────
    "IBM":  {"name": "IBM Corp",             "sector": "Technology",   "type": "stock"},
    "MSFT": {"name": "Microsoft",            "sector": "Technology",   "type": "stock"},
    "AAPL": {"name": "Apple Inc",            "sector": "Technology",   "type": "stock"},
    "SPGI": {"name": "S&P Global",           "sector": "Technology",   "type": "stock"},
    # ── Materials ─────────────────────────────────────────────
    "NUE":  {"name": "Nucor Corp",           "sector": "Materials",    "type": "stock"},
    "APD":  {"name": "Air Products",         "sector": "Materials",    "type": "stock"},
    "ECL":  {"name": "Ecolab",               "sector": "Materials",    "type": "stock"},
    "PPG":  {"name": "PPG Industries",       "sector": "Materials",    "type": "stock"},
    "SHW":  {"name": "Sherwin-Williams",     "sector": "Materials",    "type": "stock"},
    # ── Utility (고배당, 안정형) ──────────────────────────────
    "ED":   {"name": "Con Edison",           "sector": "Utility",      "type": "stock"},
    "NEE":  {"name": "NextEra Energy",       "sector": "Utility",      "type": "stock"},
    "DUK":  {"name": "Duke Energy",          "sector": "Utility",      "type": "stock"},
    "SO":   {"name": "Southern Company",     "sector": "Utility",      "type": "stock"},
    "D":    {"name": "Dominion Energy",      "sector": "Utility",      "type": "stock"},
    "AEP":  {"name": "American Elec Power",  "sector": "Utility",      "type": "stock"},
    "XEL":  {"name": "Xcel Energy",          "sector": "Utility",      "type": "stock"},
    "ETR":  {"name": "Entergy Corp",         "sector": "Utility",      "type": "stock"},
    "ES":   {"name": "Eversource Energy",    "sector": "Utility",      "type": "stock"},
    "EXC":  {"name": "Exelon Corp",          "sector": "Utility",      "type": "stock"},
    # ── Telecom ───────────────────────────────────────────────
    "T":    {"name": "AT&T",                 "sector": "Telecom",      "type": "stock"},
    "VZ":   {"name": "Verizon",              "sector": "Telecom",      "type": "stock"},
    # ── Energy ────────────────────────────────────────────────
    "XOM":  {"name": "ExxonMobil",           "sector": "Energy",       "type": "stock"},
    "CVX":  {"name": "Chevron Corp",         "sector": "Energy",       "type": "stock"},
    # ── Defense & Aerospace ───────────────────────────────────
    "RTX":  {"name": "RTX Corp (Raytheon)",  "sector": "Defense",      "type": "stock"},
    "LMT":  {"name": "Lockheed Martin",      "sector": "Defense",      "type": "stock"},
    "GD":   {"name": "General Dynamics",     "sector": "Defense",      "type": "stock"},
    # ── REIT ──────────────────────────────────────────────────
    "O":    {"name": "Realty Income",        "sector": "REIT",         "type": "stock", "is_reit": True},
    # ── ETF (별도 슬롯) ───────────────────────────────────────
    "SCHD": {"name": "Schwab US Dividend Equity ETF",           "sector": "ETF", "type": "etf"},
    "VYM":  {"name": "Vanguard High Dividend Yield",            "sector": "ETF", "type": "etf"},
    "DGRO": {"name": "iShares Core Dividend Growth",            "sector": "ETF", "type": "etf"},
    "HDV":  {"name": "iShares Core High Dividend",              "sector": "ETF", "type": "etf"},
    "JEPI": {"name": "JPMorgan Equity Premium Income",          "sector": "ETF", "type": "etf"},
    "NOBL": {"name": "ProShares S&P 500 Dividend Aristocrats",  "sector": "ETF", "type": "etf"},
    "JEPQ": {"name": "JPMorgan Nasdaq Equity Premium Income",   "sector": "ETF", "type": "etf"},
    "VIG":  {"name": "Vanguard Dividend Appreciation",          "sector": "ETF", "type": "etf"},
}

_US_FIN_CACHE: dict | None = None


def _load_us_financial_features() -> dict:
    """us_dividend_dataset.csv -> ticker 별 최신 연도 재무 피처."""
    global _US_FIN_CACHE
    if _US_FIN_CACHE is not None:
        return _US_FIN_CACHE
    out: dict = {}
    try:
        df = pd.read_csv(US_DATASET)
        df = df.sort_values("year")
        latest = df.groupby("ticker").tail(1)
        for _, r in latest.iterrows():
            out[r["ticker"]] = {
                "payout_ratio":       float(r.get("payout_ratio") or 0) or None,
                "dividend_coverage":  float(r.get("dividend_coverage") or 0) or None,
                "net_debt_ebitda":    float(r.get("net_debt_ebitda") or 0) if r.get("net_debt_ebitda") == r.get("net_debt_ebitda") else None,
                "consecutive_years":  float(r.get("consecutive_years") or 0) or None,
                "dps_yoy_pct":        float(r.get("dps_yoy_pct") or 0),
                "fcf_negative":       int(r.get("fcf_negative") or 0),
                "is_reit":            bool(r.get("is_reit") or 0),
                "sector":             str(r.get("sector") or ""),
                "fcf":                float(r.get("fcf") or 0),
                "operating_cf":       float(r.get("operating_cf") or 0),
            }
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("us_dividend_dataset 로드 실패: %s", e)
    _US_FIN_CACHE = out
    return out


def _tier_to_ml_status(tier: str) -> str:
    """us_dividend_safety tier -> KR과 통일된 ml_status."""
    return {"SAFE": "INTACT", "BORDERLINE": "WEAKENING", "AT_RISK": "BROKEN"}.get(tier, "INTACT")


def _cache_valid() -> bool:
    if not os.path.exists(CACHE_PATH):
        return False
    age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(CACHE_PATH))).days
    return age < 7


def fetch_us_data(force: bool = False) -> dict:
    """yfinance + us_dividend_dataset 재무 피처 병합. 7일 캐시."""
    if not force and _cache_valid():
        with open(CACHE_PATH) as f:
            return json.load(f)

    try:
        import yfinance as yf
    except ImportError:
        return _load_cache_or_static()

    from utils.us_dividend_safety import score_us_dividend_safety

    fin_data = _load_us_financial_features()
    results  = {}
    tickers  = list(US_UNIVERSE.keys())
    print(f"  [US] {len(tickers)}개 종목 수집 중...")

    for ticker in tickers:
        try:
            t    = yf.Ticker(ticker)
            info = t.info or {}
            raw_yield = float(info.get("dividendYield") or 0)
            div_yield = raw_yield if raw_yield > 1 else raw_yield * 100
            payout    = float(info.get("payoutRatio") or 0) * 100
            pe        = float(info.get("trailingPE") or 0)
            beta      = float(info.get("beta") or 1.0)
            mkt_cap   = float(info.get("marketCap") or 0)
            sector    = info.get("sector") or US_UNIVERSE[ticker]["sector"]
            price     = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0)

            hist = t.dividends
            div_years = 0
            if hist is not None and len(hist) > 0:
                div_years = len(hist.index.year.unique())

            # 재무 피처 병합 (us_dividend_dataset.csv 우선)
            fin = fin_data.get(ticker, {})
            payout_fin = fin.get("payout_ratio") or (payout if payout > 0 else None)

            # 안전성 점수 계산
            is_reit = (US_UNIVERSE[ticker]["sector"] == "REIT")
            is_etf  = (US_UNIVERSE[ticker]["type"] == "etf")
            if is_etf:
                safety_result = {"safety_score": 80, "tier": "SAFE", "breakdown": {}}
            else:
                safety_result = score_us_dividend_safety(
                    payout_ratio      = payout_fin,
                    dividend_coverage = fin.get("dividend_coverage"),
                    net_debt_ebitda   = fin.get("net_debt_ebitda"),
                    consecutive_years = fin.get("consecutive_years") or div_years,
                    dps_yoy_pct       = fin.get("dps_yoy_pct"),
                    fcf_negative      = fin.get("fcf_negative", 0),
                    is_reit           = is_reit,
                    sector            = sector,
                )

            tier      = safety_result.get("tier", "SAFE")
            score     = safety_result.get("safety_score", 75)

            # 50년+ 배당귀족(Dividend King): AT_RISK -> BORDERLINE 하향 캡
            # 일시적 FCF 압축이 장기 track record를 override하지 않도록
            consecutive = fin.get("consecutive_years") or div_years
            if tier == "AT_RISK" and consecutive >= 50:
                tier  = "BORDERLINE"
                score = max(score, 45)

            ml_status = _tier_to_ml_status(tier)

            results[ticker] = {
                "ticker":            ticker,
                "name":              US_UNIVERSE[ticker]["name"],
                "type":              US_UNIVERSE[ticker]["type"],
                "sector":            sector,
                "div_yield":         round(div_yield, 2),
                "payout_ratio":      round(payout_fin or payout, 1),
                "pe_ratio":          round(pe, 1),
                "beta":              round(beta, 2),
                "market_cap_b":      round(mkt_cap / 1e9, 1),
                "price_usd":         round(price, 2),
                "div_years":         div_years,
                "is_reit":           is_reit,
                # 재무 피처 (from us_dividend_dataset.csv)
                "dividend_coverage": fin.get("dividend_coverage"),
                "net_debt_ebitda":   fin.get("net_debt_ebitda"),
                "consecutive_years": fin.get("consecutive_years") or div_years,
                "dps_yoy_pct":       fin.get("dps_yoy_pct", 0),
                "fcf_negative":      fin.get("fcf_negative", 0),
                "fcf":               fin.get("fcf"),
                "operating_cf":      fin.get("operating_cf"),
                # 위험 분류 (KR과 통일)
                "safety_score":      score,
                "safety_tier":       tier,
                "ml_status":         ml_status,
                "fetched_at":        datetime.now().isoformat(),
            }
            time.sleep(0.3)
        except Exception as e:
            print(f"    [{ticker}] 오류: {e}")
            fin = fin_data.get(ticker, {})
            results[ticker] = {
                **US_UNIVERSE[ticker], "ticker": ticker,
                "div_yield": 3.0, "div_years": 10,
                "payout_ratio": 50, "beta": 1.0,
                "safety_score": 60, "safety_tier": "BORDERLINE", "ml_status": "WEAKENING",
                **fin,
            }

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"  [US] {len(results)}개 저장 완료")
    return results


def _load_cache_or_static() -> dict:
    """
    캐시 우선 → 없으면 CSV 재무 피처로 보완된 정적 기본값.
    캐시 존재 시에도 신규 티커는 CSV + 기본값으로 보완.
    """
    try:
        from utils.us_dividend_safety import score_us_dividend_safety
    except ImportError:
        score_us_dividend_safety = None  # 안전성 점수 스킵

    fin_data = _load_us_financial_features()   # CSV에서 실제 재무 피처

    def _make_static(ticker: str, info: dict) -> dict:
        """CSV 재무 피처 + 안전성 점수로 ticker 기본값 생성."""
        fin   = fin_data.get(ticker, {})
        is_etf  = info.get("type") == "etf"
        is_reit = info.get("sector") == "REIT" or info.get("is_reit", False)

        if is_etf:
            safety_result = {"safety_score": 80, "tier": "SAFE"}
        elif fin and score_us_dividend_safety is not None:
            try:
                safety_result = score_us_dividend_safety(
                    payout_ratio      = fin.get("payout_ratio"),
                    dividend_coverage = fin.get("dividend_coverage"),
                    net_debt_ebitda   = fin.get("net_debt_ebitda"),
                    consecutive_years = fin.get("consecutive_years"),
                    dps_yoy_pct       = fin.get("dps_yoy_pct"),
                    fcf_negative      = fin.get("fcf_negative", 0),
                    is_reit           = bool(is_reit),
                    sector            = info.get("sector", ""),
                )
            except Exception:
                safety_result = {"safety_score": 65, "tier": "BORDERLINE"}
        else:
            safety_result = {"safety_score": 65, "tier": "BORDERLINE"}

        tier      = safety_result.get("tier", "BORDERLINE")
        score     = safety_result.get("safety_score", 65)
        ml_status = _tier_to_ml_status(tier)

        base = {**info, "ticker": ticker, "div_years": 10, "beta": 0.8, "price_usd": 0,
                "safety_score": score, "safety_tier": tier, "ml_status": ml_status,
                "is_reit": bool(is_reit)}
        if fin:
            base.update({
                "div_yield":         3.5,  # yfinance 없이는 실시간 수익률 불가 — 기본값
                "payout_ratio":      fin.get("payout_ratio") or 55,
                "dividend_coverage": fin.get("dividend_coverage"),
                "net_debt_ebitda":   fin.get("net_debt_ebitda"),
                "consecutive_years": fin.get("consecutive_years") or 10,
                "dps_yoy_pct":       fin.get("dps_yoy_pct", 0),
                "fcf_negative":      fin.get("fcf_negative", 0),
                "fcf":               fin.get("fcf"),
                "operating_cf":      fin.get("operating_cf"),
            })
        else:
            base["div_yield"] = 3.5
        return base

    static = {t: _make_static(t, v) for t, v in US_UNIVERSE.items()}

    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH) as f:
            cached = json.load(f)
        # 신규 티커: CSV-보완 기본값으로 추가
        for t, v in static.items():
            if t not in cached:
                cached[t] = v
        return cached
    return static


def pick_us_stocks_v2(risk: str, n: int = 3, age: int = 40) -> list[dict]:
    """
    전략/나이에 맞는 US 배당주 선별.
    AT_RISK 종목 자동 제외 (KR의 Survival gate와 동일 원칙).
    """
    data  = fetch_us_data()
    items = list(data.values())

    # 기본 필터: 개별주만 (ETF는 pick_etfs 슬롯), 배당수익률 1~20%
    items = [x for x in items if x.get("type", "stock") != "etf"]
    items = [x for x in items if 1.0 <= x.get("div_yield", 0) <= 20.0]

    # AT_RISK 제외 (ml_status == BROKEN)
    items = [x for x in items if x.get("ml_status", "INTACT") != "BROKEN"]

    # 전략별 정렬
    if risk == "conservative":
        items = [x for x in items if x.get("beta", 1) <= 1.0]
        items = sorted(items, key=lambda x: (
            -x.get("div_years", 0) * 0.4
            - x.get("div_yield", 0) * 0.4
            + x.get("beta", 1) * 0.2
        ))
    elif risk == "aggressive":
        items = sorted(items, key=lambda x: (
            0 if x.get("type") == "etf" else 1,
            -x.get("div_yield", 0)
        ))
    else:
        items = sorted(items, key=lambda x: -x.get("div_yield", 0))

    if age >= 50:
        items = sorted(items, key=lambda x: x.get("beta", 1))

    result = []
    for x in items[:n]:
        dy    = x.get("div_yield", 3.0)
        score = min(100.0, dy * 8 + min(x.get("div_years", 0), 30) * 0.7 +
                    max(0, (1.5 - x.get("beta", 1.0))) * 20)
        ml_st = x.get("ml_status", "INTACT")
        tier  = x.get("safety_tier", "SAFE")
        consecutive = x.get("consecutive_years") or x.get("div_years", 0)

        # REIT 판별: sector=="REIT" or is_reit 플래그 (O/AMT/PSA 등)
        _is_reit = (str(x.get("sector", "")).upper() == "REIT" or
                    bool(x.get("is_reit", False)))
        _asset_cls = ("us_etf" if x.get("type") == "etf" else
                      "us_reit" if _is_reit else "us_stock")
        result.append({
            "ticker":            x["ticker"],
            "name":              x["name"],
            "asset_class":       _asset_cls,
            "account":           "overseas",
            "risk_profile":      "stable" if x.get("beta", 1) <= 0.8 else "moderate",
            "expected_yield":    round(dy, 2),
            "capital_gain_rate": 4.0 if x.get("type") == "etf" else 3.0,
            "description":       (f"{x['name']} | {consecutive}yr dividend | "
                                  f"safety={tier} | beta={x.get('beta',1)}"),
            "sector":            x.get("sector", ""),
            "div_years":         x.get("div_years", 0),
            "overall_score":     round(score, 1),
            "safety_score":      x.get("safety_score", 70),
            "grade":             tier,
            "trap_level":        tier,
            "consecutive_years": int(consecutive),
            "asset_type":        "DIVIDEND_ARISTOCRAT",
            # KR과 통일된 위험 필드
            "ml_status":         ml_st,
            "dividend_coverage": x.get("dividend_coverage"),
            "payout_ratio":      x.get("payout_ratio"),
            "dps_yoy_pct":       x.get("dps_yoy_pct", 0),
        })
    return result


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    data = fetch_us_data(force=False)
    print(f"\n[캐시 로드] {len(data)}개")
    by_status = {}
    for t, v in data.items():
        s = v.get("ml_status", "N/A")
        by_status.setdefault(s, []).append(t)
    for s, ts in sorted(by_status.items()):
        print(f"  {s}: {ts}")

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import yfinance as yf
from pykrx import stock
from sqlalchemy import create_engine, text
from datetime import date, timedelta

engine = create_engine("postgresql://localhost/ai_analyst")

# KOSPI 종목코드 → Yahoo Finance 티커 변환
def to_yahoo_ticker(stock_code: str) -> str:
    return f"{stock_code}.KS"


def collect_naver_valuation(stock_code: str):
    """
    yfinance로 PER/PBR/EPS/시가총액/52주고저 수집
    + pykrx로 52주 고저 보완
    """
    metrics = {}
    today_str = date.today().isoformat()
    ticker_code = to_yahoo_ticker(stock_code)

    # ── yfinance: 밸류에이션 지표 ──
    try:
        ticker = yf.Ticker(ticker_code)
        info = ticker.info

        def safe(val):
            try:
                v = float(val)
                return v if v > 0 else None
            except:
                return None

        per = safe(info.get("trailingPE"))
        pbr = safe(info.get("priceToBook"))
        eps = safe(info.get("trailingEps"))
        bps = safe(info.get("bookValue"))
        div = safe(info.get("dividendYield"))
        marcap = safe(info.get("marketCap"))
        w52_high = safe(info.get("fiftyTwoWeekHigh"))
        w52_low = safe(info.get("fiftyTwoWeekLow"))

        if per: metrics["per"] = round(per, 2)
        if pbr: metrics["pbr"] = round(pbr, 2)
        if eps: metrics["eps"] = round(eps, 0)
        if bps: metrics["bps"] = round(bps, 0)
        if div: metrics["dividend_yield"] = round(div, 4)  # yfinance KS: 이미 소수 형태 (1.03 = 1.03%)
        if marcap: metrics["market_cap_억"] = round(marcap / 1e8, 0)
        if w52_high: metrics["week52_high"] = w52_high
        if w52_low: metrics["week52_low"] = w52_low

        # PER fallback: 시가총액 / 당기순이익 (yfinance EPS 없을 때)
        if not per and metrics.get("market_cap_억"):
            try:
                with engine.connect() as conn:
                    row = conn.execute(text("""
                        SELECT value FROM metric_snapshots
                        WHERE stock_code = :code AND metric_name = 'net_income'
                        ORDER BY date DESC LIMIT 1
                    """), {"code": stock_code}).fetchone()
                if row:
                    net_income = float(row[0])
                    market_cap_krw = metrics["market_cap_억"] * 1e8
                    if net_income > 0:
                        calculated_per = round(market_cap_krw / net_income, 2)
                        if 0 < calculated_per < 500:
                            metrics["per"] = calculated_per
                            print(f"  PER 계산: 시가총액 {market_cap_krw/1e12:.1f}조 / 순이익 {net_income/1e12:.1f}조 = {calculated_per}배")
            except Exception as fe:
                print(f"  PER fallback 실패: {fe}")

    except Exception as e:
        print(f"  yfinance 수집 실패: {e}")

    # ── DB 저장 ──
    saved = []
    with engine.connect() as conn:
        for metric_name, value in metrics.items():
            if value is None:
                continue
            conn.execute(text("""
                INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
                VALUES (:code, :date, :metric, :value)
                ON CONFLICT (stock_code, date, metric_name) DO UPDATE SET value = EXCLUDED.value
            """), {"code": stock_code, "date": today_str, "metric": metric_name, "value": value})
            saved.append(f"{metric_name}={value}")
        conn.commit()

    if saved:
        print(f"✅ 밸류에이션 저장: {', '.join(saved)}")
    else:
        print(f"⚠️  밸류에이션 수집 실패")

    return metrics


if __name__ == "__main__":
    result = collect_naver_valuation("005930")
    print(result)

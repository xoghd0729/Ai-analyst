import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import yfinance as yf
from sqlalchemy import create_engine, text
from datetime import date, timedelta

engine = create_engine("postgresql://localhost/ai_analyst")

# 수집할 글로벌 매크로 지표
MACRO_TICKERS = {
    "wti_oil":       "CL=F",      # WTI 원유 선물
    "us_10y_yield":  "^TNX",      # 미국 10년물 국채금리
    "us_5y_yield":   "^FVX",      # 미국 5년물 국채금리
    "vix":           "^VIX",      # VIX 공포지수
    "dollar_index":  "DX-Y.NYB",  # 달러인덱스 (DXY)
    "sp500":         "^GSPC",     # S&P 500
    "nasdaq":        "^IXIC",     # NASDAQ
    "nvidia":        "NVDA",      # NVIDIA (반도체 섹터 온도계)
    "usd_krw":       "KRW=X",     # 달러/원 환율
}


def collect_macro():
    """
    글로벌 매크로 지표 수집 → metric_snapshots에 stock_code='MACRO'로 저장
    """
    today_str = date.today().isoformat()
    end = date.today().strftime("%Y%m%d")
    start = (date.today() - timedelta(days=5)).strftime("%Y-%m-%d")

    saved = []
    errors = []

    for metric_name, ticker_code in MACRO_TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_code)
            hist = ticker.history(period="5d")
            if hist.empty:
                errors.append(metric_name)
                continue
            latest_close = float(hist["Close"].iloc[-1])

            # MACRO 종목으로 저장 (stocks 테이블에 없어도 됨)
            with engine.connect() as conn:
                # stocks 테이블에 MACRO 항목 보장
                conn.execute(text("""
                    INSERT INTO stocks (code, name, sector)
                    VALUES ('MACRO', '글로벌매크로', '매크로')
                    ON CONFLICT (code) DO NOTHING
                """))
                conn.execute(text("""
                    INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
                    VALUES ('MACRO', :date, :metric, :value)
                    ON CONFLICT DO NOTHING
                """), {"date": today_str, "metric": metric_name, "value": latest_close})
                conn.commit()

            saved.append(f"{metric_name}={latest_close:.2f}")

        except Exception as e:
            errors.append(f"{metric_name}({e})")

    if saved:
        print(f"✅ 매크로 저장: {', '.join(saved)}")
    if errors:
        print(f"⚠️  매크로 수집 실패: {', '.join(errors)}")


def get_macro_context() -> dict:
    """llm.py에서 호출 — 최신 매크로 데이터 반환"""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT metric_name, value FROM metric_snapshots
            WHERE stock_code = 'MACRO'
            ORDER BY date DESC, id DESC
        """)).fetchall()

    seen = {}
    for row in rows:
        if row[0] not in seen:
            seen[row[0]] = float(row[1])
    return seen


if __name__ == "__main__":
    collect_macro()
    print(get_macro_context())

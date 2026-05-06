from pykrx import stock
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

engine = create_engine("postgresql://localhost/ai_analyst")

def calculate_rsi(series, period=14):
    """종가 시리즈로 RSI 계산"""
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = delta.clip(upper=0).abs().rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def collect_price(stock_code: str, days: int = 60):
    # RSI 계산에 최소 28일치 필요 — 여유있게 90일치 요청
    today = datetime.today().strftime("%Y%m%d")
    start = (datetime.today() - timedelta(days=max(days, 90))).strftime("%Y%m%d")
    df = stock.get_market_ohlcv(start, today, stock_code)

    # RSI 계산 (14일 기준)
    df["rsi_14"] = calculate_rsi(df["종가"], 14)

    today_date = datetime.today().date()

    with engine.connect() as conn:
        for date, row in df.iterrows():
            rows_to_insert = [
                {"code": stock_code, "date": date.date(), "metric": "close_price", "value": float(row["종가"])},
                {"code": stock_code, "date": date.date(), "metric": "volume",      "value": float(row["거래량"])},
            ]
            # RSI는 유효한 값만 저장 (NaN 제외)
            if not __import__("math").isnan(row["rsi_14"]):
                rows_to_insert.append(
                    {"code": stock_code, "date": date.date(), "metric": "rsi_14", "value": round(float(row["rsi_14"]), 2)}
                )

            conn.execute(text("""
                INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
                VALUES (:code, :date, :metric, :value)
                ON CONFLICT (stock_code, date, metric_name) DO UPDATE SET value = EXCLUDED.value
            """), rows_to_insert)
        conn.commit()

    # 오늘 RSI 값 출력
    latest_rsi = df["rsi_14"].iloc[-1]
    rsi_str = f", RSI={latest_rsi:.1f}" if not __import__("math").isnan(latest_rsi) else ""
    print(f"✅ {stock_code} 주가 {len(df)}일치 저장{rsi_str}")
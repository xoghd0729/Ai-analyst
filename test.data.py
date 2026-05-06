from sqlalchemy import create_engine, text
from pykrx import stock
from datetime import datetime, timedelta

engine = create_engine("postgresql://localhost/ai_analyst")

today = datetime.today().strftime("%Y%m%d")
start = (datetime.today() - timedelta(days=60)).strftime("%Y%m%d")

# 주가 데이터 수집
df = stock.get_market_ohlcv(start, today, "005930")

with engine.connect() as conn:
    # 종목 저장
    conn.execute(text("""
        INSERT INTO stocks (code, name, sector)
        VALUES ('005930', '삼성전자', '반도체')
        ON CONFLICT (code) DO NOTHING
    """))

    # 주가 저장
    for date, row in df.iterrows():
        conn.execute(text("""
            INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
            VALUES (:code, :date, :metric, :value)
            ON CONFLICT DO NOTHING
        """), [
            {"code": "005930", "date": date.date(), "metric": "close_price", "value": float(row["종가"])},
            {"code": "005930", "date": date.date(), "metric": "volume", "value": float(row["거래량"])}
        ])

    conn.commit()
    print(f"✅ {len(df)}일치 데이터 저장 완료")
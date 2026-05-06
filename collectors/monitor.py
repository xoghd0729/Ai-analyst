from sqlalchemy import create_engine, text
from pykrx import stock
from datetime import datetime, timedelta
import json

engine = create_engine("postgresql://localhost/ai_analyst")

def get_latest_metric(stock_code: str, metric: str) -> float:
    today = datetime.today().strftime("%Y%m%d")
    start = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")

    try:
        if metric == "close_price":
            df = stock.get_market_ohlcv(start, today, stock_code)
            return float(df['종가'].iloc[-1])
        elif metric == "per":
            df = stock.get_market_fundamental(start, today, stock_code)
            return float(df['PER'].iloc[-1])
        elif metric == "rsi_14":
            df = stock.get_market_ohlcv(start, today, stock_code)
            delta = df['종가'].diff()
            gain = delta.clip(lower=0).rolling(14).mean()
            loss = (-delta.clip(upper=0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1])
    except Exception as e:
        print(f"⚠️ {metric} 데이터 수집 실패: {e}")
        return None
    return None

def evaluate_rule(rule: dict, stock_code: str) -> bool:
    metric = rule['metric'].lower()
    value = get_latest_metric(stock_code, metric)
    if value is None:
        return False
    op = rule['operator']
    threshold = rule['value']
    if op == ">": return value > threshold
    if op == "<": return value < threshold
    if op == ">=": return value >= threshold
    if op == "<=": return value <= threshold
    return False

def check_conditions(stock_code: str):
    with engine.connect() as conn:
        conditions = conn.execute(text("""
            SELECT c.id, c.description, c.logic
            FROM conditions c
            JOIN thesis t ON c.thesis_id = t.id
            WHERE t.stock_code = :code AND c.is_active = TRUE
        """), {"code": stock_code}).fetchall()

    for cond in conditions:
        if isinstance(cond[2], dict):
            logic = cond[2]
        else:
            logic = json.loads(cond[2])

        rules = logic['rules']
        results = [evaluate_rule(r, stock_code) for r in rules]
        triggered = all(results) if logic['operator'] == 'AND' else any(results)

        if triggered:
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO alerts (condition_id, detail)
                    VALUES (:cid, :detail)
                """), {"cid": cond[0], "detail": f"조건 이탈: {cond[1]}"})
                conn.commit()
            print(f"🚨 이탈 감지: {cond[1]}")
        else:
            print(f"✅ 정상: {cond[1]}")

if __name__ == "__main__":
    check_conditions("005930")
from sqlalchemy import create_engine, text

engine = create_engine("postgresql://localhost/ai_analyst")

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS actions (
            id SERIAL PRIMARY KEY,
            stock_code VARCHAR(10) REFERENCES stocks(code),
            recommendation VARCHAR(10) NOT NULL,  -- 유지 / 부분매도 / 매도
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    conn.commit()
    print("✅ actions 테이블 생성 완료")

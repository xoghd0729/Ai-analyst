"""
thesis_history 테이블 마이그레이션

■ 목적
  종목별 Thesis 판단 결과를 시간순으로 저장.
  INTACT → WEAKENING → BROKEN 변화를 추적.

실행:
  python db/add_thesis_history.py
"""

from sqlalchemy import create_engine, text

engine = create_engine("postgresql://localhost/ai_analyst")

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS thesis_history (
            id              SERIAL PRIMARY KEY,
            stock_code      VARCHAR(20)  NOT NULL,
            name            VARCHAR(100) NOT NULL,
            thesis_status   VARCHAR(20)  NOT NULL,   -- INTACT / WEAKENING / BROKEN
            composite_risk  FLOAT        NOT NULL,
            ml_risk         FLOAT        NOT NULL,
            news_risk       FLOAT        NOT NULL,
            dominant_event  VARCHAR(100),
            explanation     TEXT,
            action          TEXT,
            contradiction   BOOLEAN      DEFAULT FALSE,  -- 뉴스↔재무 괴리 감지
            contradiction_detail TEXT,
            created_at      TIMESTAMP    DEFAULT NOW()
        )
    """))

    # 조회 성능 위한 인덱스
    conn.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_thesis_history_stock_created
        ON thesis_history (stock_code, created_at DESC)
    """))

    conn.commit()
    print("✅ thesis_history 테이블 + 인덱스 생성 완료")

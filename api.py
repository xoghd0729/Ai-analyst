from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, text
from pydantic import BaseModel
import json
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from main import run

engine = create_engine("postgresql://localhost/ai_analyst")
app = FastAPI(title="AI Analyst API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 분석 실행 상태 추적 (간단한 in-memory)
analysis_status = {}


class AnalyzeRequest(BaseModel):
    stock_name: str
    corp_code: str


# ─────────────────────────────────────────
# POST /analyze/{stock_code}
# 분석 전체 파이프라인 실행
# ─────────────────────────────────────────
@app.post("/analyze/{stock_code}")
def analyze(stock_code: str, body: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    분석 파이프라인 실행 (백그라운드).
    - 주가 수집 → Thesis 생성 → 조건 생성 → 모니터링 → 행동 제안
    """
    analysis_status[stock_code] = "running"

    def _run():
        try:
            run(stock_code, body.stock_name, body.corp_code)
            analysis_status[stock_code] = "done"
        except Exception as e:
            analysis_status[stock_code] = f"error: {e}"

    background_tasks.add_task(_run)
    return {"status": "started", "stock_code": stock_code}


@app.get("/analyze/{stock_code}/status")
def analyze_status(stock_code: str):
    status = analysis_status.get(stock_code, "not_started")
    return {"stock_code": stock_code, "status": status}


# ─────────────────────────────────────────
# GET /thesis/{stock_code}
# 가장 최신 투자 Thesis 반환
# ─────────────────────────────────────────
@app.get("/thesis/{stock_code}")
def get_thesis(stock_code: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, content, created_at
            FROM thesis
            WHERE stock_code = :code
            ORDER BY created_at DESC
            LIMIT 1
        """), {"code": stock_code}).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="thesis not found")

    return {
        "thesis_id": row[0],
        "stock_code": stock_code,
        "content": row[1],
        "created_at": str(row[2]),
    }


# ─────────────────────────────────────────
# GET /conditions/{stock_code}
# 활성화된 이탈 조건 목록
# ─────────────────────────────────────────
@app.get("/conditions/{stock_code}")
def get_conditions(stock_code: str):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT c.id, c.type, c.description, c.logic, c.is_active
            FROM conditions c
            JOIN thesis t ON c.thesis_id = t.id
            WHERE t.stock_code = :code
            ORDER BY c.id DESC
        """), {"code": stock_code}).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="conditions not found")

    result = []
    for r in rows:
        logic = r[3] if isinstance(r[3], dict) else json.loads(r[3])
        result.append({
            "id": r[0],
            "type": r[1],
            "description": r[2],
            "logic": logic,
            "is_active": r[4],
        })
    return {"stock_code": stock_code, "conditions": result}


# ─────────────────────────────────────────
# GET /alerts/{stock_code}
# 최근 이탈 알림 목록
# ─────────────────────────────────────────
@app.get("/alerts/{stock_code}")
def get_alerts(stock_code: str):
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT a.id, a.triggered_at, a.detail, c.description, c.type
            FROM alerts a
            JOIN conditions c ON a.condition_id = c.id
            JOIN thesis t ON c.thesis_id = t.id
            WHERE t.stock_code = :code
            ORDER BY a.triggered_at DESC
            LIMIT 20
        """), {"code": stock_code}).fetchall()

    result = []
    for r in rows:
        result.append({
            "alert_id": r[0],
            "triggered_at": str(r[1]),
            "detail": r[2],
            "condition_description": r[3],
            "condition_type": r[4],
        })
    return {"stock_code": stock_code, "alerts": result}


# ─────────────────────────────────────────
# GET /action/{stock_code}
# 가장 최신 행동 제안 반환 (actions 테이블)
# ─────────────────────────────────────────
@app.get("/action/{stock_code}")
def get_action(stock_code: str):
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, recommendation, content, created_at
            FROM actions
            WHERE stock_code = :code
            ORDER BY created_at DESC
            LIMIT 1
        """), {"code": stock_code}).fetchone()

    if not row:
        return {
            "stock_code": stock_code,
            "recommendation": "유지",
            "content": "이탈 조건 없음 — 현재 포지션 유지",
            "created_at": None,
        }

    return {
        "stock_code": stock_code,
        "recommendation": row[1],
        "content": row[2],
        "created_at": str(row[3]),
    }


# ─────────────────────────────────────────
# GET /stocks
# 분석된 종목 전체 목록
# ─────────────────────────────────────────
@app.get("/stocks")
def list_stocks():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT code, name, sector FROM stocks")).fetchall()
    return {"stocks": [{"code": r[0], "name": r[1], "sector": r[2]} for r in rows]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False)

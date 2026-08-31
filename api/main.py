"""
AI 현금흐름 운영체제 — FastAPI 백엔드.

실행 방법:
  cd ~/ai-analyst
  uvicorn api.main:app --reload --port 8000

데이터 파이프라인:
  시작 시 APScheduler 자동 실행
  ETF: 매일 17:00 / US: 토 00:00 / KR: 일 01:00 (KST)
  수동 갱신: python utils/data_pipeline.py
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import ranking, stock, portfolio, auth

log = logging.getLogger(__name__)

# ── 데이터 파이프라인 스케줄러 (lifespan) ─────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: 시작 시 스케줄러 ON, 종료 시 OFF."""
    scheduler = None
    try:
        from utils.data_pipeline import start_scheduler
        scheduler = start_scheduler()
    except Exception as e:
        log.warning("스케줄러 시작 실패 (무시하고 계속): %s", e)

    yield  # 앱 실행 중

    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        log.info("데이터 파이프라인 스케줄러 종료")


app = FastAPI(
    title="AI 현금흐름 운영체제",
    description=(
        "미래 월급형 현금흐름을 설계·분석·방어·관리하는 AI 운영체제.\n\n"
        "5축 자산 유니버스 × Pipe-and-Filter 분석 파이프라인 × "
        "Monte Carlo + FIRE + 행동편향 + 세금 최적화"
    ),
    version="2.0.0",
    lifespan=lifespan,
)

# React 개발 서버에서 오는 요청 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ranking.router,   prefix="/api/ranking",   tags=["랭킹"])
app.include_router(stock.router,     prefix="/api/stock",     tags=["종목"])
app.include_router(portfolio.router, prefix="/api/portfolio", tags=["포트폴리오"])
app.include_router(auth.router,      prefix="/api/auth",      tags=["사용자"])


@app.get("/")
def root():
    return {
        "status":  "ok",
        "message": "AI 현금흐름 운영체제 API v2.0",
        "docs":    "/docs",
        "health":  "/api/health",
    }


@app.get("/api/health", tags=["시스템"])
def health_check():
    """
    헬스 체크 엔드포인트.

    발표 시 청중에게 "API 살아있다" 즉시 보여주거나,
    UptimeRobot 같은 모니터링 서비스가 5분마다 호출.

    상태 코드는 항상 200. 내부 status 필드로 세부 OK/DEGRADED 표시.
    """
    import os
    from datetime import datetime

    checks = {}
    overall = "ok"

    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 1. 데이터 파일 존재 여부
    data_files = {
        "approved_universe": "data/approved_universe_kr_v2.json",
        "asset_metadata":    "data/asset_metadata.json",
        "ml_scoring":        "data/ml_scoring_results.csv",
        "ranking":           "data/ranking.csv",
    }
    for name, path in data_files.items():
        full = os.path.join(BASE, path)
        checks[f"file_{name}"] = "ok" if os.path.exists(full) else "missing"
        if not os.path.exists(full):
            overall = "degraded"

    # 2. Survival explainer import 가능 여부 (XGBoost 의존성 제거됨)
    try:
        from utils.shap_explainer import explain_prediction  # noqa: F401
        checks["ml_model"] = "ok"
    except Exception:
        checks["ml_model"] = "missing"
        overall = "degraded"

    # 3. 파이프라인 import 가능 여부 (구조 검증)
    try:
        from api.pipeline.runner import RecommendationPipeline  # noqa: F401
        checks["pipeline"] = "ok"
    except Exception as e:
        checks["pipeline"] = f"error: {type(e).__name__}"
        overall = "degraded"

    return {
        "status":    overall,
        "service":   "AI Cashflow OS",
        "version":   "2.0.0",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "checks":    checks,
        "uptime_message":
            "✅ 시스템 정상 동작 중" if overall == "ok"
            else "⚠️ 일부 컴포넌트 누락 — 추천 결과 제한될 수 있음",
    }


@app.get("/api/pipeline/status")
def pipeline_status():
    """데이터 파이프라인 마지막 갱신 시각 조회."""
    import os, json
    from datetime import datetime

    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def mtime(p):
        try: return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")
        except: return "없음"

    def read_updated(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f).get("_updated", "없음")
        except: return "없음"

    return {
        "etf_quality_cache":   read_updated(os.path.join(BASE, "data", "etf_quality_cache.json")),
        "kr_yield_cache":      read_updated(os.path.join(BASE, "data", "kr_yield_cache.json")),
        "ranking_csv":         mtime(os.path.join(BASE, "data", "ranking.csv")),
        "ml_scoring_csv":      mtime(os.path.join(BASE, "data", "ml_scoring_results.csv")),
        "us_stock_scores_csv": mtime(os.path.join(BASE, "data", "us_stock_scores.csv")),
        "schedule": {
            "etf":      "매일 17:00 KST (장 마감 후)",
            "us_stock": "매주 토요일 00:00 KST",
            "kr_yield": "매주 일요일 01:00 KST",
        },
        "manual_refresh": "POST /api/pipeline/refresh",
    }


@app.post("/api/pipeline/refresh")
def pipeline_refresh():
    """수동 즉시 갱신 트리거."""
    from utils.data_pipeline import run_all_updates
    result = run_all_updates()
    return {"status": "ok", **result}

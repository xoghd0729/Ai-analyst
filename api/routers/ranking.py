"""
랭킹 API — KRX 고배당 종목 분석 결과 제공.

GET /api/ranking        → 전체 랭킹 목록
GET /api/ranking/top    → 상위 N개
"""

import os
import pandas as pd
from fastapi import APIRouter, Query
from sqlalchemy import create_engine, text

router = APIRouter()
engine = create_engine("postgresql://localhost/ai_analyst")

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RANKING_CSV  = os.path.join(BASE_DIR, "data", "ranking.csv")


def get_ranking_data() -> list[dict]:
    """ranking.csv에서 랭킹 데이터 로드."""
    if not os.path.exists(RANKING_CSV):
        return []
    df = pd.read_csv(RANKING_CSV, encoding="utf-8-sig", dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.strip()
    df = df.fillna(0)
    return df.to_dict(orient="records")


@router.get("")
def get_ranking(
    grade: str = Query(None, description="등급 필터: 우량 | 보통 | 위험"),
    trap:  str = Query(None, description="Yield Trap 필터: SAFE | CAUTION | WARNING | DANGER"),
    limit: int = Query(50, description="최대 반환 개수"),
):
    """
    전체 종목 랭킹 반환.
    grade, trap 파라미터로 필터링 가능.
    """
    data = get_ranking_data()

    if grade:
        data = [d for d in data if grade in str(d.get("grade", ""))]
    if trap:
        data = [d for d in data if str(d.get("trap_level", "")) == trap]

    return {
        "total": len(data),
        "items": data[:limit],
    }


@router.get("/summary")
def get_summary():
    """등급별 종목 수 요약."""
    data = get_ranking_data()
    if not data:
        return {"우량": 0, "보통": 0, "위험": 0, "total": 0}

    summary = {"우량": 0, "보통": 0, "위험": 0}
    for d in data:
        grade = str(d.get("grade", ""))
        if "우량" in grade:
            summary["우량"] += 1
        elif "보통" in grade:
            summary["보통"] += 1
        elif "위험" in grade:
            summary["위험"] += 1

    summary["total"] = len(data)
    return summary


@router.get("/top")
def get_top(n: int = Query(10, description="상위 N개")):
    """종합 점수 기준 상위 N개 종목."""
    data = get_ranking_data()
    # 종합점수 기준 정렬
    data.sort(key=lambda x: float(x.get("overall_score", 0) or 0), reverse=True)
    return {"items": data[:n]}

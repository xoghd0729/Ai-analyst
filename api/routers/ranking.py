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

BASE_DIR       = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RANKING_CSV    = os.path.join(BASE_DIR, "data", "ranking.csv")
US_SCORES_CSV  = os.path.join(BASE_DIR, "data", "us_stock_scores.csv")


def get_ranking_data() -> list[dict]:
    """ranking.csv (한국 종목)에서 랭킹 데이터 로드."""
    if not os.path.exists(RANKING_CSV):
        return []
    df = pd.read_csv(RANKING_CSV, encoding="utf-8-sig", dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.strip()
    df = df.fillna(0)
    items = df.to_dict(orient="records")
    for it in items:
        it["country"] = "kr"
    return items


def get_us_ranking_data() -> list[dict]:
    """us_stock_scores.csv (미국 종목)를 한국 랭킹과 동일 스키마로 변환."""
    if not os.path.exists(US_SCORES_CSV):
        return []
    df = pd.read_csv(US_SCORES_CSV, encoding="utf-8-sig", dtype={"ticker": str})
    df = df.fillna(0)

    items = []
    for _, row in df.iterrows():
        items.append({
            "stock_code":        str(row.get("ticker", "")),
            "name":              row.get("name", ""),
            "overall_score":     float(row.get("overall_score", 0) or 0),
            "grade":             row.get("grade", ""),
            "trap_level":        row.get("trap_level", ""),
            "yield":             float(row.get("yield_pct", 0) or 0),
            "stability":         float(row.get("stability_score", 0) or 0),
            "financial":         float(row.get("financial_score", 0) or 0),
            "growth":            float(row.get("growth_score", 0) or 0),
            "ml_status":         "INTACT" if str(row.get("trap_level", "")) == "SAFE" else "WEAKENING",
            "P_BROKEN":          0.05 if str(row.get("trap_level", "")) == "SAFE" else 0.25,
            "dps_cuts_3y":       int(row.get("dividend_cut", 0) or 0),
            "latest_yoy_pct":    float(row.get("dps_yoy_pct", 0) or 0),
            "score_reason":      row.get("description", ""),
            "rank":              0,        # 통합 후 재매김
            "avg_payout_pct":    float(row.get("payout_ratio", 0) or 0),
            "country":           "us",
            "sector":            row.get("sector", ""),
            "asset_type":        row.get("asset_type", ""),
            "consecutive_years": int(row.get("consecutive_years", 0) or 0),
        })
    return items


@router.get("")
def get_ranking(
    grade:   str = Query(None, description="등급 필터"),
    trap:    str = Query(None, description="Yield Trap 필터"),
    country: str = Query("all", description="국가 필터: kr | us | all (기본 all)"),
    limit:   int = Query(100, description="최대 반환 개수"),
):
    """
    전체 종목 랭킹 반환 (한국 + 미국 통합).

    country=kr  → 한국 종목만
    country=us  → 미국 종목만
    country=all → 둘 다, overall_score 기준 정렬 (기본)
    """
    if country == "kr":
        data = get_ranking_data()
    elif country == "us":
        data = get_us_ranking_data()
    else:
        data = get_ranking_data() + get_us_ranking_data()
        data.sort(key=lambda x: float(x.get("overall_score", 0) or 0), reverse=True)
        for i, d in enumerate(data, 1):
            d["rank"] = i

    if grade:
        data = [d for d in data if grade in str(d.get("grade", ""))]
    if trap:
        data = [d for d in data if str(d.get("trap_level", "")) == trap]

    return {
        "total":    len(data),
        "kr_count": sum(1 for d in data if d.get("country") == "kr"),
        "us_count": sum(1 for d in data if d.get("country") == "us"),
        "items":    data[:limit],
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

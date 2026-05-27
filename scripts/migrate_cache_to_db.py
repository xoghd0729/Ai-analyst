#!/usr/bin/env python3
"""
마이그레이션 스크립트: 파일 캐시 -> PostgreSQL

실행 방법:
    python scripts/migrate_cache_to_db.py

무엇을 하는가:
  1. DB 테이블 생성 (없으면 CREATE TABLE)
  2. 기존 파일 데이터를 읽어 UPSERT (ON CONFLICT DO UPDATE)
  3. 각 테이블 row 수 출력으로 마이그레이션 확인

왜 UPSERT 인가:
  재실행해도 중복 없이 최신 데이터로 갱신됨.
  배치 스크립트에서 주기적으로 실행해도 안전.
"""
import json, os, sys
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from db.models import Base, KrYieldCache, MLPrediction, ETFQuality, AssetMetadata

DB_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/ai_analyst")

DATA = {
    "ml_csv":    os.path.join(BASE_DIR, "data", "ml_scoring_results.csv"),
    "etf_json":  os.path.join(BASE_DIR, "data", "etf_quality_cache.json"),
    "meta_json": os.path.join(BASE_DIR, "data", "asset_metadata.json"),
    "kr_json":   os.path.join(BASE_DIR, "data", "kr_yield_cache.json"),
}


def migrate():
    engine = create_engine(DB_URL, pool_pre_ping=True)
    print("테이블 생성 중...")
    Base.metadata.create_all(engine)
    print("  OK: 테이블 생성 완료")

    with Session(engine) as sess:
        # ML 예측 결과
        if os.path.exists(DATA["ml_csv"]):
            df = pd.read_csv(DATA["ml_csv"], dtype={"stock_code": str})
            df["stock_code"] = df["stock_code"].str.zfill(6)
            rows = [{"stock_code": r["stock_code"], "ml_status": str(r.get("ml_status","INTACT")),
                     "p_weakening": float(r.get("P_WEAKENING",0) or 0),
                     "p_broken": float(r.get("P_BROKEN",0) or 0),
                     "ml_score": float(r.get("ml_score",0) or 0),
                     "dps_yoy_pct": float(r.get("dps_yoy_pct",0) or 0) if r.get("dps_yoy_pct") else None}
                    for _, r in df.iterrows()]
            if rows:
                stmt = pg_insert(MLPrediction).values(rows)
                stmt = stmt.on_conflict_do_update(index_elements=["stock_code"],
                    set_={c: stmt.excluded[c] for c in ["ml_status","p_weakening","p_broken","ml_score","dps_yoy_pct"]})
                sess.execute(stmt); sess.commit()
            print(f"  OK: ml_predictions {len(rows)}건 UPSERT")

        # ETF 품질
        if os.path.exists(DATA["etf_json"]):
            with open(DATA["etf_json"], encoding="utf-8") as f:
                etf_data = json.load(f)
            rows = [{"ticker": t, "name": d.get("name"),
                     "aum_billion": float(d.get("aum_billion",0) or 0),
                     "expense_ratio": float(d.get("expense_ratio",0) or 0),
                     "div_yield": float(d.get("div_yield",0) or 0),
                     "div_growth_5y": float(d.get("div_growth_5y",0) or 0),
                     "monthly_pay": bool(d.get("monthly_pay",False)),
                     "quality_score": float(d.get("quality_score",50) or 50),
                     "pass_filter": bool(d.get("pass_filter",True)),
                     "reject_reason": d.get("reject_reason")}
                    for t, d in etf_data.items() if not t.startswith("_")]
            if rows:
                stmt = pg_insert(ETFQuality).values(rows)
                stmt = stmt.on_conflict_do_update(index_elements=["ticker"],
                    set_={c: stmt.excluded[c] for c in ["name","aum_billion","expense_ratio",
                          "div_yield","div_growth_5y","monthly_pay","quality_score","pass_filter","reject_reason"]})
                sess.execute(stmt); sess.commit()
            print(f"  OK: etf_quality {len(rows)}건 UPSERT")

        # 자산 메타데이터
        if os.path.exists(DATA["meta_json"]):
            with open(DATA["meta_json"], encoding="utf-8") as f:
                raw = json.load(f)
            rows = []
            _skip = ("pay_months","div_growth_rate_pct","div_growth_5y","volatility_annual_pct",
                     "max_drawdown_pct","consecutive_years","monthly_pay","sector")
            for cat, assets in raw.items():
                if cat.startswith("_"): continue
                for ticker, d in assets.items():
                    rows.append({"ticker": ticker, "asset_class": cat,
                        "pay_months": d.get("pay_months"),
                        "div_growth_rate_pct": float(d.get("div_growth_rate_pct",0) or 0),
                        "div_growth_5y": float(d.get("div_growth_5y",0) or 0),
                        "volatility_annual_pct": float(d.get("volatility_annual_pct",15) or 15),
                        "max_drawdown_pct": float(d.get("max_drawdown_pct",-20) or -20),
                        "consecutive_years": int(d.get("consecutive_years",0) or 0),
                        "monthly_pay": bool(d.get("monthly_pay",False)),
                        "sector": d.get("sector"),
                        "extra_data": {k:v for k,v in d.items() if k not in _skip}})
            if rows:
                stmt = pg_insert(AssetMetadata).values(rows)
                stmt = stmt.on_conflict_do_update(index_elements=["ticker"],
                    set_={c: stmt.excluded[c] for c in ["asset_class","pay_months","div_growth_rate_pct",
                          "div_growth_5y","volatility_annual_pct","max_drawdown_pct","consecutive_years",
                          "monthly_pay","sector","extra_data"]})
                sess.execute(stmt); sess.commit()
            print(f"  OK: asset_metadata {len(rows)}건 UPSERT")

        # KR 수익률 캐시
        if os.path.exists(DATA["kr_json"]):
            with open(DATA["kr_json"], encoding="utf-8") as f:
                kr_data = json.load(f)
            rows = [{"stock_code": str(code).zfill(6),
                     "name": d.get("name") if isinstance(d, dict) else None,
                     "yield_pct": float(d.get("yield_pct", d) if isinstance(d, dict) else d or 0),
                     "price": int(d.get("price",0)) if isinstance(d, dict) else None}
                    for code, d in kr_data.items() if not str(code).startswith("_")]
            if rows:
                stmt = pg_insert(KrYieldCache).values(rows)
                stmt = stmt.on_conflict_do_update(index_elements=["stock_code"],
                    set_={c: stmt.excluded[c] for c in ["name","yield_pct","price"]})
                sess.execute(stmt); sess.commit()
            print(f"  OK: kr_yield_cache {len(rows)}건 UPSERT")

    print("\n마이그레이션 완료!")
    print("이후 배치 실행: python scripts/rebuild_ranking.py 로 DB 자동 갱신")


if __name__ == "__main__":
    migrate()

"""
scripts/rebuild_ranking.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
배당 포트폴리오 전용 ranking.csv 재구성 스크립트.

실행 방법:
  python scripts/rebuild_ranking.py

수행 작업:
  1. pykrx로 전 종목 현재 배당수익률 갱신 (실시간)
  2. dividend_dataset.csv + ml_scoring_results.csv 병합
  3. dividend_scorer.py 배당 전용 점수로 재계산
  4. data/ranking.csv 덮어쓰기
  5. data/yield_cache.json 갱신 (API 캐시용)

정기 실행 권장: 주 1회 (장 마감 후)
"""

import os
import sys
import json
import logging
import pandas as pd
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from utils.dividend_scorer import score_dividend_stock

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

RANKING_CSV    = os.path.join(BASE_DIR, "data", "ranking.csv")
DIV_CSV        = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
ML_CSV         = os.path.join(BASE_DIR, "data", "ml_scoring_results.csv")
YIELD_CACHE    = os.path.join(BASE_DIR, "data", "yield_cache.json")
KR_YIELD_CACHE = os.path.join(BASE_DIR, "data", "kr_yield_cache.json")


# ── Step 1: pykrx로 배당수익률 갱신 ──────────────────────────
def fetch_kr_yields_live(stock_codes: list[str]) -> dict[str, float]:
    """
    pykrx로 각 종목의 현재 배당수익률을 가져온다.
    DPS(연간) / 현재주가 × 100 = 배당수익률

    pykrx get_market_fundamental은 DIV 컬럼을 직접 제공:
      DIV = 배당수익률(%)
    """
    try:
        from pykrx import stock as krx
        today = datetime.now().strftime("%Y%m%d")

        # 최근 거래일 fundamental 가져오기 (DIV 컬럼 = 배당수익률)
        log.info(f"[pykrx] {len(stock_codes)}개 종목 배당수익률 조회 중...")
        df = krx.get_market_fundamental(today, today, stock_codes)

        if df is None or df.empty:
            # 오늘이 휴장일이면 전날로 재시도
            from datetime import timedelta
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
            df = krx.get_market_fundamental(yesterday, yesterday, stock_codes)

        if df is None or df.empty:
            log.warning("[pykrx] 데이터 없음 — 기존 캐시 사용")
            return {}

        yields = {}
        for code in stock_codes:
            if code in df.index:
                div_val = df.loc[code, "DIV"] if "DIV" in df.columns else None
                if div_val and div_val > 0:
                    yields[code] = round(float(div_val), 2)

        log.info(f"[pykrx] {len(yields)}개 종목 배당수익률 갱신 완료")
        return yields

    except Exception as e:
        log.warning(f"[pykrx] 조회 실패: {e} — 기존 데이터 사용")
        return {}


def load_kr_yield_cache() -> dict[str, float]:
    """kr_yield_cache.json에서 이전 캐시 로드."""
    try:
        with open(KR_YIELD_CACHE, encoding="utf-8") as f:
            data = json.load(f)
        from datetime import timedelta
        updated = datetime.strptime(data.get("_updated", "2000-01-01"), "%Y-%m-%d")
        if datetime.now() - updated < timedelta(hours=24 * 7):  # 1주일 이내
            log.info(f"[cache] kr_yield_cache 사용 ({data['_updated']})")
            return data.get("yields", {})
    except Exception:
        pass
    return {}


def save_kr_yield_cache(yields: dict[str, float]) -> None:
    try:
        with open(KR_YIELD_CACHE, "w", encoding="utf-8") as f:
            json.dump({
                "_updated": datetime.now().strftime("%Y-%m-%d"),
                "yields": yields
            }, f, ensure_ascii=False, indent=2)
        log.info(f"[cache] kr_yield_cache 저장 ({len(yields)}개)")
    except Exception as e:
        log.warning(f"[cache] 저장 실패: {e}")


# ── Step 2: 데이터 병합 ───────────────────────────────────────
def build_merged_df() -> pd.DataFrame:
    """dividend_dataset + ml_scoring_results 병합."""
    df_div = pd.read_csv(DIV_CSV, dtype={"stock_code": str})
    df_div["stock_code"] = df_div["stock_code"].str.zfill(6)

    df_ml  = pd.read_csv(ML_CSV,  dtype={"stock_code": str})
    df_ml["stock_code"] = df_ml["stock_code"].str.zfill(6)

    # 최근 3년 집계 (배당 삭감 횟수, 평균 payout, 평균 coverage)
    recent = df_div[df_div["year"] >= df_div["year"].max() - 2].copy()
    agg = recent.groupby(["stock_code", "name"]).agg(
        avg_dps      = ("dps",               "mean"),
        min_dps      = ("dps",               "min"),
        dps_cuts     = ("dividend_cut",       "sum"),
        avg_payout   = ("payout_ratio",       "mean"),
        avg_coverage = ("dividend_coverage",  "mean"),
        years_data   = ("year",               "count"),
    ).reset_index()

    # 가장 최근 연도 DPS + YoY
    latest_year = df_div["year"].max()
    latest = df_div[df_div["year"] == latest_year][
        ["stock_code", "dps", "dps_yoy_pct"]
    ].rename(columns={"dps": "latest_dps", "dps_yoy_pct": "latest_yoy"})

    merged = (
        agg
        .merge(latest,  on="stock_code", how="left")
        .merge(
            df_ml[["stock_code", "ml_status", "P_WEAKENING", "P_BROKEN", "ml_score"]],
            on="stock_code", how="left"
        )
    )

    # ML 데이터 없는 종목 → 중립값
    merged["ml_status"]  = merged["ml_status"].fillna("INTACT")
    merged["P_BROKEN"]   = pd.to_numeric(merged["P_BROKEN"],   errors="coerce").fillna(0.0)
    merged["P_WEAKENING"]= pd.to_numeric(merged["P_WEAKENING"],errors="coerce").fillna(0.0)

    return merged


# ── Step 3: 스코어링 + 배당수익률 갱신 ───────────────────────
def build_ranking(
    merged: pd.DataFrame,
    live_yields: dict[str, float],
    base_yields:  dict[str, float],
) -> pd.DataFrame:
    """
    dividend_scorer로 전 종목 채점 후 제외 종목 분리.
    """
    rows = []
    excluded_rows = []

    for _, r in merged.iterrows():
        code = r["stock_code"]

        # yield 우선순위: 실시간 pykrx > 기존 ranking 고정값 > 0
        yld = live_yields.get(code) or base_yields.get(code) or 0.0

        result = score_dividend_stock(
            stock_code   = code,
            name         = str(r["name"]),
            yield_pct    = float(yld),
            ml_status    = str(r.get("ml_status", "INTACT")),
            dps_cuts     = int(r.get("dps_cuts", 0) or 0),
            latest_yoy   = float(r.get("latest_yoy", 0) or 0),
            payout_ratio = float(r["avg_payout"])  if pd.notna(r.get("avg_payout"))  else None,
            div_coverage = float(r["avg_coverage"]) if pd.notna(r.get("avg_coverage")) else None,
            p_broken     = float(r.get("P_BROKEN", 0) or 0),
        )

        row = {
            "stock_code":    code,
            "name":          r["name"],
            "overall_score": result["overall_score"],
            "grade":         result["grade"],
            "trap_level":    result["trap_level"],
            "yield":         round(yld, 2),
            "yield_score":   result["yield_score"],
            "stability":     result["stability_score"],
            "financial":     result["financial_score"],
            "growth":        result["growth_score"],
            "ml_status":     r.get("ml_status", "INTACT"),
            "P_BROKEN":      round(float(r.get("P_BROKEN", 0) or 0), 3),
            "dps_cuts_3y":   int(r.get("dps_cuts", 0) or 0),
            "avg_payout_pct":round(float(r["avg_payout"]),  1) if pd.notna(r.get("avg_payout"))  else None,
            "latest_dps":    round(float(r["latest_dps"]), 0) if pd.notna(r.get("latest_dps")) else None,
            "latest_yoy_pct":round(float(r.get("latest_yoy", 0) or 0), 1),
            "score_reason":  _build_reason(result, yld, r),
        }

        if result["grade"] == "❌ 제외":
            row["exclude_reason"] = result["exclude_reason"]
            excluded_rows.append(row)
        else:
            rows.append(row)

    df_pass = pd.DataFrame(rows).sort_values("overall_score", ascending=False).reset_index(drop=True)
    df_pass["rank"] = df_pass.index + 1

    df_excl = pd.DataFrame(excluded_rows)

    log.info(f"[ranking] 통과: {len(df_pass)}개 / 제외: {len(df_excl)}개")
    if not df_excl.empty:
        for _, row in df_excl.iterrows():
            log.info(f"  ❌ {row['name']:12s} ({row['stock_code']}) — {row.get('exclude_reason','')}")

    return df_pass, df_excl


def _build_reason(result: dict, yld: float, r) -> str:
    """점수 근거 자연어 생성."""
    parts = []
    grade = result["grade"]
    ml = r.get("ml_status", "INTACT")
    cuts = int(r.get("dps_cuts", 0) or 0)
    yoy  = float(r.get("latest_yoy", 0) or 0)

    if grade == "🟢 우량":
        parts.append(f"배당수익률 {yld:.1f}%로 적정 수준")
        if ml == "INTACT" and cuts == 0:
            parts.append("AI 배당 안정 판정, 최근 3년 삭감 이력 없음")
        if yoy >= 5:
            parts.append(f"최근 DPS {yoy:.0f}% 성장")
    elif grade == "🟡 보통":
        if yld < 2.5:
            parts.append(f"배당수익률 {yld:.1f}%로 다소 낮음")
        if ml == "WEAKENING":
            parts.append("AI 배당 약화 징후 감지, 모니터링 필요")
        if cuts > 0:
            parts.append(f"최근 3년 배당삭감 {cuts}회")
    elif grade == "🟠 주의":
        parts.append("편입 가능하나 비중 축소 권장")

    return ". ".join(parts) if parts else "데이터 기반 자동 평가"


# ── Step 4: 메인 실행 ─────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("배당 포트폴리오 ranking 재구성 시작")
    log.info("=" * 60)

    # 기존 ranking.csv에서 base yield 로드
    base_yields = {}
    if os.path.exists(RANKING_CSV):
        try:
            df_base = pd.read_csv(RANKING_CSV, dtype={"stock_code": str})
            df_base["stock_code"] = df_base["stock_code"].str.zfill(6)
            base_yields = df_base.set_index("stock_code")["yield"].to_dict()
        except Exception:
            pass

    # 데이터 병합
    merged = build_merged_df()
    all_codes = merged["stock_code"].tolist()

    # pykrx 실시간 yield (캐시 우선)
    live_yields = load_kr_yield_cache()
    if not live_yields:
        live_yields = fetch_kr_yields_live(all_codes)
        if live_yields:
            save_kr_yield_cache(live_yields)

    # 스코어링
    df_pass, df_excl = build_ranking(merged, live_yields, base_yields)

    # 저장
    # 백업
    if os.path.exists(RANKING_CSV):
        backup = RANKING_CSV.replace(".csv", f"_backup_{datetime.now().strftime('%Y%m%d')}.csv")
        import shutil
        shutil.copy(RANKING_CSV, backup)

    df_pass.to_csv(RANKING_CSV, index=False)
    log.info(f"[저장] {RANKING_CSV} — {len(df_pass)}개 종목")

    # 제외 목록도 별도 저장 (투명성)
    if not df_excl.empty:
        excl_path = RANKING_CSV.replace(".csv", "_excluded.csv")
        df_excl.to_csv(excl_path, index=False)
        log.info(f"[저장] {excl_path} — {len(df_excl)}개 제외 종목")

    log.info("=" * 60)
    log.info("완료. 상위 10개:")
    log.info("=" * 60)
    cols = ["rank", "name", "yield", "overall_score", "grade", "ml_status"]
    log.info("\n" + df_pass[cols].head(10).to_string(index=False))

    return df_pass


if __name__ == "__main__":
    main()

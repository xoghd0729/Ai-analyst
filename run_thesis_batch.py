"""
run_thesis_batch.py — 전체 종목 Thesis 일괄 생성

ranking.csv의 모든 종목에 대해:
  1. DB에서 최신 재무지표 + ML 예측
  2. 뉴스 수집 + 이벤트 추출 (EXAONE)
  3. Thesis 생성 + DB 저장
  4. 요약 테이블 출력

실행:
  python run_thesis_batch.py
  python run_thesis_batch.py --top 10   # 상위 10개만
  python run_thesis_batch.py --dry-run  # DB 저장 없이 출력만
"""

import sys
import os
import argparse
import time
import numpy as np
import pandas as pd
import joblib
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 학습 데이터(dividend_dataset.csv)에서 종목별 최신 dps_yoy_pct 로드 ──
def _load_dps_yoy_lookup() -> dict:
    """
    dividend_dataset.csv → {stock_code: dps_yoy_pct} 딕셔너리.

    훈련 데이터에는 과거 연도별 dps_yoy_pct가 있음.
    inference 시 DB에 없을 때 이 값을 fallback으로 사용.
    stock_code는 6자리 zero-padding으로 정규화.
    """
    csv_path = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        df = df.dropna(subset=["dps_yoy_pct"])
        df = df.sort_values("year")
        # 종목별 가장 최신 연도의 dps_yoy_pct
        latest = df.groupby("stock_code")["dps_yoy_pct"].last()
        return latest.to_dict()
    except Exception:
        return {}


# ── CSV 전체 피처 로드 (DB 없을 때 fallback용) ──────────────────
def _load_csv_features_lookup() -> dict:
    """
    dividend_dataset.csv → {stock_code: {feature: value}} 딕셔너리.

    종목별 가장 최신 연도 행의 피처를 통째로 저장.
    DB 연결 실패 시 get_ml_risk() 에서 fallback으로 사용.
    """
    csv_path = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
    if not os.path.exists(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        df = df.sort_values("year")
        # 종목별 최신 연도 행 선택
        latest = df.groupby("stock_code").last().reset_index()
        feat_cols = [
            "fcf", "dividends_paid", "dividend_coverage",
            "operating_cf", "capex", "payout_ratio", "dps_yoy_pct",
        ]
        result = {}
        for _, row in latest.iterrows():
            sc = row["stock_code"]
            result[sc] = {c: row.get(c) for c in feat_cols}
        return result
    except Exception:
        return {}

from collectors.news_kr      import fetch_naver_news, fetch_us_news
from collectors.news_cache   import filter_new_articles, needs_update, cleanup_old_cache
from collectors.financials_us import fetch_us_financials
from agents.news_agent       import analyze_stock_news
from agents.thesis_agent     import generate_thesis


def is_us_stock(stock_code: str) -> bool:
    """미국 주식 여부 판단. 티커가 알파벳이면 미국 주식."""
    return not stock_code.isdigit()


def fetch_news(stock_code: str, name: str, days: int = 30) -> list:
    """한국/미국 구분해서 뉴스 수집."""
    if is_us_stock(stock_code):
        return fetch_us_news(stock_code, name)   # yfinance 기반
    return fetch_naver_news(stock_code, name, days=days)

# ─────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RANKING_CSV = os.path.join(BASE_DIR, "data", "ranking.csv")
MODEL_PATH       = os.path.join(BASE_DIR, "models", "dividend_cut_model.pkl")
KR_3CLASS_PATH   = os.path.join(BASE_DIR, "models", "kr_3class_model.pkl")
US_MODEL_PATH    = os.path.join(BASE_DIR, "models", "us_dividend_cut_model.pkl")
engine      = create_engine("postgresql://localhost/ai_analyst")

# 훈련 데이터에서 종목별 dps_yoy_pct 로드 (한 번만)
DPS_YOY_LOOKUP = _load_dps_yoy_lookup()
if DPS_YOY_LOOKUP:
    print(f"[init] dps_yoy 히스토리: {len(DPS_YOY_LOOKUP)}종목 로드 완료")

# CSV 전체 피처 (DB 없을 때 fallback)
CSV_FEATURES_LOOKUP = _load_csv_features_lookup()
if CSV_FEATURES_LOOKUP:
    print(f"[init] CSV 피처 fallback: {len(CSV_FEATURES_LOOKUP)}종목 로드 완료")

STATUS_ICON = {"INTACT": "🟢", "WEAKENING": "🟡", "BROKEN": "🔴"}


def _get_dps_yoy(stock_code: str) -> float:
    """
    dividends_paid 최신 2개 연도 비교 → YoY 증감률(%) 계산.

    metric_snapshots에서 날짜 기준 최신 값과 1년 전 값을 비교.
    데이터 없으면 0 반환.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT date, value FROM metric_snapshots
                WHERE stock_code = :code AND metric_name = 'dividends_paid'
                ORDER BY date DESC
                LIMIT 4
            """), {"code": stock_code}).fetchall()

        if len(rows) < 2:
            return 0.0

        # 가장 최신 vs 그 전 값
        latest_val = float(rows[0][1])
        prev_val   = float(rows[1][1])

        if prev_val == 0:
            return 0.0

        return round((latest_val - prev_val) / abs(prev_val) * 100, 2)
    except Exception:
        return 0.0


def _get_us_ml_risk(stock_code: str) -> tuple[float, dict] | None:
    """
    미국 전용 XGBoost 모델로 배당 삭감 확률 계산.
    models/us_dividend_cut_model.pkl 없으면 None 반환 → 규칙 기반으로 fallback.

    저장 형식: joblib bundle {"pipeline": ..., "feature_names": [...], "threshold": 0.3}
    피처 순서를 bundle에서 불러와 컬럼 오정렬 방지.
    """
    if not os.path.exists(US_MODEL_PATH):
        return None
    try:
        import pandas as pd

        bundle       = joblib.load(US_MODEL_PATH)
        pipeline     = bundle["pipeline"]
        feat_names   = bundle["feature_names"]   # 학습 시 확정된 컬럼 순서
        threshold    = bundle.get("threshold", 0.3)

        # DB에서 원시 지표 가져오기
        needed = [
            "payout_ratio", "dividend_coverage", "dps_yoy_pct",
            "div_to_ocf", "fcf_negative", "shareholder_yield",
            "net_debt_ebitda", "consecutive_years",
        ]
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT metric_name, value FROM metric_snapshots
                WHERE stock_code = :code AND metric_name = ANY(:metrics)
                ORDER BY date DESC
            """), {"code": stock_code, "metrics": needed}).fetchall()

        metrics: dict[str, float] = {}
        for metric, value in rows:
            if metric not in metrics:
                metrics[metric] = float(value)

        if not metrics:
            return None

        # 파생 피처 계산 (train_us_model.py와 완전 동일)
        payout  = metrics.get("payout_ratio")
        dps_yoy = metrics.get("dps_yoy_pct") or DPS_YOY_LOOKUP.get(stock_code)
        nd_eb   = metrics.get("net_debt_ebitda")

        row = {
            "payout_ratio":      payout,
            "dividend_coverage": metrics.get("dividend_coverage"),
            "dps_yoy_pct":       dps_yoy,
            "div_to_ocf":        metrics.get("div_to_ocf"),
            "fcf_negative":      metrics.get("fcf_negative", 0),
            "shareholder_yield": metrics.get("shareholder_yield"),
            "net_debt_ebitda":   min(max(nd_eb, -5), 20) if nd_eb is not None else None,
            "consecutive_years": metrics.get("consecutive_years"),
            "payout_over_100":   1 if payout and payout > 100 else 0,
            "payout_over_80":    1 if payout and payout > 80 else 0,
            "dps_declining":     1 if dps_yoy and dps_yoy < 0 else 0,
        }

        # 학습 때와 동일한 컬럼 순서로 DataFrame 구성 (없는 컬럼은 NaN → imputer 처리)
        X_df = pd.DataFrame([{c: row.get(c) for c in feat_names}])

        prob = float(pipeline.predict_proba(X_df)[:, 1][0])
        return round(prob, 3), {
            "method":       "US_XGBoost",
            "payout_ratio": payout,
            "dps_yoy_pct":  dps_yoy,
            "threshold":    threshold,
        }

    except Exception as e:
        log.warning(f"[us_ml] {stock_code} XGBoost 실패: {e}")
        return None


def _get_us_rule_risk(stock_code: str) -> tuple[float, dict]:
    """
    미국 주식 전용 규칙 기반 위험도 계산 (US XGBoost 모델 fallback).

    우선순위:
      1. models/us_dividend_cut_model.pkl 있으면 → US XGBoost
      2. 없으면 → 아래 규칙 기반 계산 (임시)

    위험도 = (payout_risk + coverage_risk + fcf_risk + yoy_risk) / 4
    반환: (risk_score 0~1, debug_info)
    """
    # US XGBoost 모델 우선 시도
    ml_result = _get_us_ml_risk(stock_code)
    if ml_result is not None:
        return ml_result
    try:
        needed = ["fcf", "dividends_paid", "dividend_coverage",
                  "operating_cf", "payout_ratio"]
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT metric_name, value FROM metric_snapshots
                WHERE stock_code = :code AND metric_name = ANY(:metrics)
                ORDER BY date DESC
            """), {"code": stock_code, "metrics": needed}).fetchall()

        metrics = {}
        for metric, value in rows:
            if metric not in metrics:
                metrics[metric] = float(value)

        if not metrics:
            return 0.2, {"reason": "재무지표 없음 — 기본값 0.2"}

        score_parts = []

        # payout_ratio: US 기준 — 80% 이하는 정상, 80~100% 주의, 100%+ 위험
        payout = metrics.get("payout_ratio")
        if payout is not None:
            if payout <= 60:   pr = 0.1
            elif payout <= 80: pr = 0.3
            elif payout <= 100: pr = 0.6
            else:              pr = 0.9
            score_parts.append(pr)

        # dividend_coverage: 1.5x 이상이면 안전
        cov = metrics.get("dividend_coverage")
        if cov is not None:
            if cov >= 2.0:   cr = 0.1
            elif cov >= 1.5: cr = 0.25
            elif cov >= 1.0: cr = 0.5
            else:            cr = 0.85
            score_parts.append(cr)

        # fcf: 양수면 안전, 음수면 위험
        fcf = metrics.get("fcf")
        if fcf is not None:
            score_parts.append(0.1 if fcf >= 0 else 0.8)

        # dps_yoy: DPS_YOY_LOOKUP에서 가져옴 (배당귀족은 양수여야)
        dps_yoy = DPS_YOY_LOOKUP.get(stock_code)
        if dps_yoy is not None:
            if dps_yoy > 3:    score_parts.append(0.05)
            elif dps_yoy > 0:  score_parts.append(0.15)
            elif dps_yoy > -5: score_parts.append(0.5)
            else:              score_parts.append(0.85)

        risk = sum(score_parts) / len(score_parts) if score_parts else 0.2
        debug = {
            "method": "US_rules",
            "payout_ratio": payout,
            "dividend_coverage": cov,
            "fcf_positive": fcf is not None and fcf >= 0,
            "components": len(score_parts),
        }
        return round(risk, 3), debug

    except Exception as e:
        log.warning(f"[us_risk] {stock_code} 규칙 계산 실패: {e}")
        return 0.2, {}


def get_ml_risk(stock_code: str) -> tuple[float, dict]:
    """
    DB 재무지표 → XGBoost 배당 삭감 확률.
    미국 종목은 규칙 기반 계산으로 우회 (한국 모델 단위 불일치 방지).

    반환: (ml_risk_score, debug_info)
      debug_info에는 실제 사용된 피처값들이 담김 (로그용)
    """
    # 미국 종목 → 규칙 기반 위험도 (ML 모델 우회)
    if is_us_stock(stock_code):
        return _get_us_rule_risk(stock_code)

    if not os.path.exists(MODEL_PATH) and not os.path.exists(KR_3CLASS_PATH):
        return 0.0, {}
    try:
        # ── DB 쿼리 (실패하면 CSV fallback) ────────────────────────
        metrics = {}
        db_ok = False
        try:
            needed = ["fcf", "dividends_paid", "dividend_coverage",
                      "operating_cf", "capex", "payout_ratio"]
            with engine.connect() as conn:
                rows = conn.execute(text("""
                    SELECT metric_name, value FROM metric_snapshots
                    WHERE stock_code = :code AND metric_name = ANY(:metrics)
                    ORDER BY date DESC
                """), {"code": stock_code, "metrics": needed}).fetchall()
            for metric, value in rows:
                if metric not in metrics:
                    metrics[metric] = float(value)
            db_ok = bool(metrics)
        except Exception:
            db_ok = False  # DB 연결 실패 → CSV fallback으로

        if not db_ok:
            # CSV fallback: dividend_dataset.csv 최신 행 사용
            csv_row = CSV_FEATURES_LOOKUP.get(stock_code, {})
            for k, v in csv_row.items():
                if v is not None and not (isinstance(v, float) and np.isnan(v)):
                    metrics[k] = float(v)
            if not metrics:
                return 0.0, {"reason": "DB + CSV 피처 없음"}

        fcf      = metrics.get("fcf", 0) or 0
        ocf      = metrics.get("operating_cf", 0) or 0   # 0 기본값 (1 아님)
        div_paid = metrics.get("dividends_paid", 0) or 0
        capex    = metrics.get("capex", 0) or 0

        # dps_yoy_pct 결정 순서:
        #   1순위: DB에서 2개 연도 비교 (현재는 1년치만 → 0.0 반환)
        #   2순위: 학습 데이터(dividend_dataset.csv)의 최신 값
        #   3순위: np.nan → 모델 내 SimpleImputer가 학습 중앙값으로 대체
        dps_yoy_db = _get_dps_yoy(stock_code) if db_ok else 0.0
        if dps_yoy_db != 0.0:
            dps_yoy = dps_yoy_db
            dps_yoy_src = "DB"
        elif stock_code in DPS_YOY_LOOKUP:
            dps_yoy = DPS_YOY_LOOKUP[stock_code]
            dps_yoy_src = "CSV"
        else:
            dps_yoy = np.nan   # imputer가 학습 중앙값으로 채움
            dps_yoy_src = "imputed"

        # payout_ratio도 없으면 np.nan → imputer 처리
        payout = metrics.get("payout_ratio")
        if payout is None:
            payout = np.nan

        fcf_feat = fcf
        div_feat = div_paid
        ocf_feat = ocf
        cap_feat = capex

        feat_map = {
            "fcf":               fcf_feat,
            "dividends_paid":    div_feat,
            "dividend_coverage": metrics.get("dividend_coverage") or np.nan,
            "operating_cf":      ocf_feat,
            "capex":             cap_feat,
            "div_to_ocf":        div_paid / (abs(ocf) + 1) if ocf != 0 else np.nan,
            "fcf_negative":      1 if fcf < 0 else 0,
            "ocf_to_capex":      ocf / (abs(capex) + 1) if capex != 0 else np.nan,
            "payout_ratio":      payout,
            "dps_yoy_pct":       dps_yoy,
        }

        # ── 3-class 모델 우선 사용, 없으면 binary fallback ──────────
        p_intact = p_weakening = p_broken = None

        if os.path.exists(KR_3CLASS_PATH):
            bundle3    = joblib.load(KR_3CLASS_PATH)
            pipeline3  = bundle3["pipeline"]
            features3  = bundle3["feature_names"]   # 학습 시 피처 순서
            thresholds = bundle3.get("threshold", {"WEAKENING": 0.25, "BROKEN": 0.40})

            X3 = pd.DataFrame([[feat_map.get(f, np.nan) for f in features3]],
                              columns=features3)
            proba3 = pipeline3.predict_proba(X3)[0]   # [P_INTACT, P_WEAKENING, P_BROKEN]

            p_intact    = float(proba3[0])
            p_weakening = float(proba3[1])
            p_broken    = float(proba3[2])

            # 복합 위험 점수: P(BROKEN) + 0.5×P(WEAKENING)
            score = round(p_broken + 0.5 * p_weakening, 3)
        else:
            # fallback: binary 모델
            saved          = joblib.load(MODEL_PATH)
            model_bin      = saved["pipeline"] if isinstance(saved, dict) else saved
            saved_features = saved.get("features", []) if isinstance(saved, dict) else []
            feature_names  = saved_features or list(feat_map.keys())
            features_bin   = pd.DataFrame([[feat_map.get(f, 0) for f in feature_names]],
                                          columns=feature_names)
            score = float(model_bin.predict_proba(features_bin)[0][1])

        debug = {
            "payout_ratio":      feat_map["payout_ratio"],
            "fcf":               fcf,
            "fcf_negative":      feat_map["fcf_negative"],
            "dividend_coverage": feat_map["dividend_coverage"],
            "dps_yoy_pct":       dps_yoy,
            "dps_yoy_src":       dps_yoy_src,
            "ml_score":          round(score, 3),
            # 3-class 확률 (thesis_agent에서 WEAKENING 판정에 사용)
            "p_intact":          p_intact,
            "p_weakening":       p_weakening,
            "p_broken":          p_broken,
        }
        return score, debug

    except Exception as e:
        return 0.0, {"error": str(e)}


def get_financial_data(stock_code: str) -> dict:
    """DB에서 최신 재무지표 조회. DB 실패 시 CSV fallback."""
    result = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT metric_name, value FROM metric_snapshots
                WHERE stock_code = :code
                  AND metric_name IN ('payout_ratio','fcf','dividend_coverage')
                ORDER BY date DESC
            """), {"code": stock_code}).fetchall()
        for m, v in rows:
            if m not in result:
                result[m] = float(v)
    except Exception:
        # DB 연결 실패 → CSV fallback
        csv_row = CSV_FEATURES_LOOKUP.get(stock_code, {})
        for k in ("payout_ratio", "fcf", "dividend_coverage"):
            v = csv_row.get(k)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                result[k] = float(v)

    # dps_yoy_pct는 lookup에서 보완 (metric_snapshots에 없을 수 있음)
    if "dps_yoy_pct" not in result and stock_code in DPS_YOY_LOOKUP:
        result["dps_yoy_pct"] = DPS_YOY_LOOKUP[stock_code]
    return result


def run_batch(stocks: list[dict], dry_run: bool = False, force: bool = False):
    results = []
    total   = len(stocks)

    print(f"\n{'='*65}")
    print(f"  Thesis 배치 분석 — {total}개 종목")
    print(f"  모드: {'DRY-RUN (저장 안 함)' if dry_run else 'DB 저장'}")
    print(f"{'='*65}\n")

    # 배치 시작 전 만료 캐시 정리 (7일 초과 항목 삭제)
    removed = cleanup_old_cache()
    if removed:
        print(f"  [cache] 만료 캐시 {removed}건 정리\n")

    skipped_count = 0

    for i, stock in enumerate(stocks, 1):
        code = stock["stock_code"]
        name = stock["name"]
        print(f"[{i:2d}/{total}] {name} ({code})", end=" ", flush=True)

        try:
            # ── Step 0: 미국 종목은 재무 데이터 먼저 수집 ────────
            # 한국 주식은 DART 배치(build_dataset.py)가 별도로 돌지만
            # 미국 주식은 yfinance로 실시간 수집해서 DB에 저장
            if is_us_stock(code):
                fetch_us_financials(code, engine)

            # ── Step 1: 뉴스 수집 → 캐시 필터링 ──────────────────
            raw_articles = fetch_news(code, name, days=30)
            new_articles, cached_count = filter_new_articles(raw_articles)

            # ── Step 2: Incremental 판단 ───────────────────────
            # 새 기사도 없고 마지막 분석도 24h 이내면 → skip (--force로 우회 가능)
            update_needed, reason = needs_update(code, new_articles)

            if not update_needed and not force:
                print(f"⏭  SKIP ({reason})")
                skipped_count += 1
                continue

            # ── Step 3: EXAONE 분석 (변화 있는 종목만) ────────────
            # new_articles가 있으면 그것만, 없으면 raw_articles 전체 사용
            # (24h 강제 재분석 케이스: 새 기사 없어도 재분석해야 함)
            articles_to_analyze = new_articles if new_articles else raw_articles
            cache_note = f"새기사={len(new_articles)}건" if cached_count else ""
            print(f"분석 중... {cache_note}", end=" ", flush=True)

            # 1. ML 리스크 (score + debug 정보)
            ml_risk, ml_debug = get_ml_risk(code)

            # 2. 뉴스 이벤트 추출
            news_analysis = analyze_stock_news(code, name, articles_to_analyze)

            # 3. 재무 데이터
            financial_data = get_financial_data(code)

            # 4. Thesis 생성
            thesis = generate_thesis(
                stock_code=code,
                name=name,
                ml_risk_score=ml_risk,
                news_analysis=news_analysis,
                financial_data=financial_data,
                save_to_db=not dry_run,
                p_weakening=ml_debug.get("p_weakening"),   # 3-class WEAKENING 확률
                p_broken=ml_debug.get("p_broken"),          # 3-class BROKEN 확률
            )

            status = thesis["thesis_status"]
            icon   = STATUS_ICON.get(status, "⚪")
            contradiction = " ⚠️ 괴리" if thesis.get("contradiction") else ""

            # debug: 피처 핵심값 출력
            dps_yoy    = ml_debug.get("dps_yoy_pct", "N/A")
            dps_src    = ml_debug.get("dps_yoy_src", "?")
            payout     = ml_debug.get("payout_ratio", "N/A")
            dps_str    = f"{dps_yoy:.1f}%({dps_src})" if isinstance(dps_yoy, float) else f"{dps_yoy}({dps_src})"
            payout_str = f"{payout:.1f}%" if isinstance(payout, float) and not np.isnan(payout) else "N/A"
            print(f"{icon} {status:9s} | risk={thesis['composite_risk']:.2f} "
                  f"(ML={ml_risk:.2f}) | dps_yoy={dps_str} payout={payout_str}{contradiction}")

            results.append({
                "name":           name,
                "stock_code":     code,
                "thesis_status":  status,
                "composite_risk": thesis["composite_risk"],
                "ml_risk":        thesis["ml_risk"],
                "news_risk":      thesis["news_risk"],
                "contradiction":  thesis.get("contradiction", False),
                "action":         thesis["action"],
            })

        except Exception as e:
            print(f"❌ 실패: {e}")
            results.append({
                "name": name, "stock_code": code,
                "thesis_status": "ERROR", "composite_risk": 0,
                "ml_risk": 0, "news_risk": 0,
                "contradiction": False, "action": str(e),
            })

        # Ollama 과부하 방지 (연속 호출 간격) — Ollama 꺼져 있으면 skip
        if i < total:
            time.sleep(0.1)

    if skipped_count:
        print(f"\n  ⏭  변화 없음으로 스킵: {skipped_count}개 종목")

    # ── 요약 테이블 ─────────────────────────────────────────
    print(f"\n{'='*65}")
    print(f"  📊 Thesis 배치 결과 요약")
    print(f"{'='*65}")

    # 분석된 종목이 없으면 (전부 skip) 바로 종료
    if not results:
        print(f"  ⏭  분석된 종목 없음 (전체 스킵: {skipped_count}개)")
        print(f"{'='*65}\n")
        return results

    df        = pd.DataFrame(results)
    intact    = df[df.thesis_status == "INTACT"]
    weakening = df[df.thesis_status == "WEAKENING"]
    broken    = df[df.thesis_status == "BROKEN"]
    errors    = df[df.thesis_status == "ERROR"]

    print(f"  🟢 INTACT    : {len(intact)}개")
    print(f"  🟡 WEAKENING : {len(weakening)}개")
    print(f"  🔴 BROKEN    : {len(broken)}개")
    if len(errors):
        print(f"  ❌ ERROR     : {len(errors)}개")
    print()

    # 위험 종목 상세
    danger = df[df.thesis_status.isin(["WEAKENING", "BROKEN"])].sort_values("composite_risk", ascending=False)
    if not danger.empty:
        print("  ⚠️  주의 필요 종목:")
        for _, r in danger.iterrows():
            icon = STATUS_ICON.get(r.thesis_status, "⚪")
            contradiction = " [괴리]" if r.contradiction else ""
            print(f"    {icon} {r['name']:12s} ({r.stock_code}) "
                  f"risk={r.composite_risk:.2f} | {r.action[:40]}{contradiction}")

    # 괴리 감지 종목
    contra = df[df.contradiction == True]
    if not contra.empty:
        print(f"\n  🔍 신호 괴리 감지 ({len(contra)}개):")
        for _, r in contra.iterrows():
            print(f"    → {r['name']} ({r.stock_code}): 뉴스↔재무 신호 불일치")

    print(f"\n{'='*65}")
    if not dry_run:
        print(f"  ✅ {len(results) - len(errors)}개 종목 thesis_history DB 저장 완료")
    print(f"{'='*65}\n")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top",      type=int, default=None, help="상위 N개만 분석")
    parser.add_argument("--skip",     type=int, default=0,    help="앞에서 N개 건너뛰기")
    parser.add_argument("--dry-run",  action="store_true",    help="DB 저장 없이 출력만")
    parser.add_argument("--us-only",  action="store_true",    help="미국 종목만 분석")
    parser.add_argument("--kr-only",  action="store_true",    help="한국 종목만 분석")
    parser.add_argument("--force",    action="store_true",    help="skip 무시하고 전체 재분석")
    args = parser.parse_args()

    # ranking.csv 로드
    df_rank = pd.read_csv(RANKING_CSV, encoding="utf-8-sig", dtype={"stock_code": str})
    df_rank["stock_code"] = df_rank["stock_code"].str.strip()
    stocks_raw = df_rank[["name", "stock_code"]].dropna().to_dict("records")

    # stock_code 정규화: 한국(숫자)은 6자리 zero-padding, 미국(알파벳)은 그대로
    def normalize_code(code: str) -> str:
        code = str(code).strip()
        return code.zfill(6) if code.isdigit() else code.upper()

    stocks = [{"name": s["name"], "stock_code": normalize_code(s["stock_code"])} for s in stocks_raw]

    # 필터 적용
    if args.us_only:
        stocks = [s for s in stocks if is_us_stock(s["stock_code"])]
        print(f"[필터] 미국 종목만: {len(stocks)}개")
    elif args.kr_only:
        stocks = [s for s in stocks if not is_us_stock(s["stock_code"])]
        print(f"[필터] 한국 종목만: {len(stocks)}개")

    if args.skip:
        stocks = stocks[args.skip:]
    if args.top:
        stocks = stocks[:args.top]

    run_batch(stocks, dry_run=args.dry_run, force=args.force)

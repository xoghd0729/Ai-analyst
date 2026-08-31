"""
종목 상세 API — 개별 종목의 분석 결과 제공.

GET /api/stock/{code}           → 종목 기본 정보 + 점수
GET /api/stock/{code}/thesis    → AI 생성 투자 thesis (실시간 ML + 뉴스 분석)
GET /api/stock/{code}/metrics   → 재무 지표
GET /api/stock/{code}/predict   → Survival 배당 삭감 예측
"""

import os
import sys
import logging
from fastapi import APIRouter, HTTPException
from utils.shap_explainer import explain_prediction as _surv_explain
from sqlalchemy import create_engine, text

# 프로젝트 루트를 sys.path에 추가 (agents/, collectors/ import 가능하게)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

log = logging.getLogger(__name__)

router = APIRouter()
engine = create_engine("postgresql://localhost/ai_analyst")

BASE_DIR   = _BASE_DIR


def query_one(sql: str, params: dict):
    with engine.connect() as conn:
        row = conn.execute(text(sql), params).fetchone()
    return row


def query_all(sql: str, params: dict):
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).fetchall()
    return rows


@router.get("/{code}")
def get_stock(code: str):
    """종목 기본 정보 + 최신 점수."""
    # 종목 기본 정보
    stock = query_one(
        "SELECT code, name FROM stocks WHERE code = :code",
        {"code": code},
    )
    if not stock:
        raise HTTPException(status_code=404, detail=f"종목 {code}를 찾을 수 없습니다.")

    # 최신 점수
    score = query_one(
        """SELECT stability_score, risk_score, momentum_score, overall_score, score_reason, created_at
           FROM scores WHERE stock_code = :code ORDER BY created_at DESC LIMIT 1""",
        {"code": code},
    )

    # Yield Trap 판정
    trap = query_one(
        """SELECT trap_level, signals FROM yield_trap_results
           WHERE stock_code = :code ORDER BY created_at DESC LIMIT 1""",
        {"code": code},
    )

    return {
        "stock_code": stock[0],
        "name":       stock[1],
        "scores": {
            "stability":  score[0] if score else None,
            "risk":       score[1] if score else None,
            "momentum":   score[2] if score else None,
            "overall":    score[3] if score else None,
            "reason":     score[4] if score else None,
        } if score else None,
        "trap": {
            "level":   trap[0] if trap else None,
            "signals": trap[1] if trap else [],
        } if trap else None,
    }


@router.get("/{code}/thesis")
def get_thesis(code: str):
    """
    종목 AI 투자 thesis — 실시간 생성.

    파이프라인:
      1. DB에서 종목명 + 최신 재무지표 조회
      2. 네이버 뉴스 RSS 수집 + 키워드 필터 (1차)
      3. Claude Haiku로 금융 이벤트 추출 (2차)
      4. XGBoost ML 배당 삭감 확률 계산
      5. Thesis Agent — ML(70%) + 뉴스(30%) 종합 → INTACT/WEAKENING/BROKEN
    """
    # ── 1. 종목 기본 정보 ─────────────────────────────────────
    stock = query_one(
        "SELECT code, name FROM stocks WHERE code = :code",
        {"code": code},
    )
    # DB에 없어도 code를 이름으로 사용 (미국 티커 등)
    name = stock[1] if stock else code

    # ── 2. 최신 재무지표 ──────────────────────────────────────
    needed = ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex", "payout_ratio"]
    rows = query_all(
        """SELECT metric_name, value FROM metric_snapshots
           WHERE stock_code = :code AND metric_name = ANY(:metrics)
           ORDER BY date DESC""",
        {"code": code, "metrics": needed},
    )
    financial_data: dict = {}
    for metric, value in rows:
        if metric not in financial_data:
            financial_data[metric] = float(value)

    # ── 3. Survival 배당 삭감 확률 ──────────────────────────────────
    ml_risk_score = 0.0
    if financial_data:
        try:
            fcf      = financial_data.get("fcf", 0) or 0
            ocf      = financial_data.get("operating_cf", 1) or 1
            div_paid = financial_data.get("dividends_paid", 0) or 0
            feat_map = {
                "fcf":               fcf,
                "dividends_paid":    div_paid,
                "dividend_coverage": financial_data.get("dividend_coverage", 0) or 0,
                "operating_cf":      ocf,
                "capex":             financial_data.get("capex", 0) or 0,
                "div_to_ocf":        div_paid / (abs(ocf) + 1),
                "fcf_negative":      1 if fcf < 0 else 0,
                "ocf_to_capex":      ocf / (abs(financial_data.get("capex", 1)) + 1),
                "payout_ratio":      financial_data.get("payout_ratio", 0) or 0,
                "dps_yoy_pct":       0,
            }
            surv = _surv_explain(feat_map)
            ml_risk_score = surv.get("hazard", 0.0)
        except Exception as e:
            log.warning(f"[thesis] Survival 예측 실패 ({code}): {e}")

    # ── 4. 뉴스 수집 + 이벤트 추출 ───────────────────────────
    news_analysis: dict = {}
    try:
        from collectors.news_kr import fetch_naver_news
        from agents.news_agent import analyze_stock_news

        articles = fetch_naver_news(stock_code=code, name=name, days=30)
        news_analysis = analyze_stock_news(
            stock_code=code,
            name=name,
            articles=articles,
        )
    except Exception as e:
        log.warning(f"[thesis] 뉴스 분석 실패 ({code}): {e}")
        # 빈 분석 결과로 진행 (Thesis는 ML만으로도 생성 가능)
        news_analysis = {
            "events": [], "news_risk_score": 0.0,
            "dominant_event": "no_relevant_event", "dominant_label": "없음",
            "signal": "neutral",
        }

    # ── 5. Thesis 생성 ────────────────────────────────────────
    try:
        from agents.thesis_agent import generate_thesis

        thesis = generate_thesis(
            stock_code=code,
            name=name,
            ml_risk_score=ml_risk_score,
            news_analysis=news_analysis,
            financial_data=financial_data,
        )
    except Exception as e:
        log.error(f"[thesis] Thesis 생성 실패 ({code}): {e}")
        raise HTTPException(status_code=500, detail=f"Thesis 생성 중 오류: {e}")

    # ── 6. 응답 구성 ──────────────────────────────────────────
    events_out = []
    for ev in news_analysis.get("events", []):
        if ev.get("event_type") != "no_relevant_event":
            events_out.append({
                "event_type": ev["event_type"],
                "label":      ev.get("label", ""),
                "direction":  ev["direction"],
                "confidence": round(ev["confidence"], 2),
                "headline":   ev.get("headline", "")[:80],
                "reason":     ev.get("reason", ""),
            })

    return {
        "stock_code":     code,
        "name":           name,
        # ── Thesis 핵심 결과 ──
        "thesis_status":  thesis["thesis_status"],   # INTACT / WEAKENING / BROKEN
        "explanation":    thesis["explanation"],
        "action":         thesis["action"],
        # ── 리스크 수치 ──
        "composite_risk": thesis["composite_risk"],  # 0~1
        "ml_risk":        thesis["ml_risk"],
        "news_risk":      thesis["news_risk"],
        "dominant_event": thesis.get("dominant_event", "없음"),
        # ── Contradiction Detection ──
        "contradiction":        thesis.get("contradiction", False),
        "contradiction_detail": thesis.get("contradiction_detail", ""),
        # ── 뉴스 이벤트 목록 ──
        "events":         events_out,
        "article_count":  news_analysis.get("article_count", 0),
        # ── 재무 스냅샷 ──
        "financial_snapshot": {
            "payout_ratio":      financial_data.get("payout_ratio"),
            "fcf":               financial_data.get("fcf"),
            "dividend_coverage": financial_data.get("dividend_coverage"),
        },
        "generated_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


@router.get("/{code}/thesis/history")
def get_thesis_history(code: str, limit: int = 20):
    """
    종목 Thesis 변화 이력 조회.

    시간순으로 INTACT → WEAKENING → BROKEN 변화를 추적.
    최신순으로 반환 (limit 기본 20개).
    """
    try:
        from agents.thesis_agent import load_thesis_history
        history = load_thesis_history(stock_code=code, limit=limit)
    except Exception as e:
        log.error(f"[thesis/history] 조회 실패 ({code}): {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if not history:
        return {
            "stock_code": code,
            "history":    [],
            "message":    "아직 저장된 thesis 이력이 없습니다. /thesis 엔드포인트를 먼저 호출하세요.",
        }

    # 상태 변화 포인트 감지 (연속 동일 상태 제외하고 변화만 마킹)
    for i, h in enumerate(history):
        if i == len(history) - 1:
            h["status_changed"] = False
        else:
            # history는 최신순이므로 다음 항목이 이전 상태
            h["status_changed"] = h["thesis_status"] != history[i + 1]["thesis_status"]

    return {
        "stock_code":   code,
        "total_records": len(history),
        "latest_status": history[0]["thesis_status"] if history else None,
        "history":      history,
    }


@router.get("/{code}/metrics")
def get_metrics(code: str):
    """종목 재무 지표 반환."""
    rows = query_all(
        """SELECT metric_name, value, date FROM metric_snapshots
           WHERE stock_code = :code
           ORDER BY date DESC""",
        {"code": code},
    )
    # 지표명별 최신값만
    seen, result = set(), {}
    for metric, value, date in rows:
        if metric not in seen:
            result[metric] = {"value": float(value), "date": str(date)}
            seen.add(metric)
    return {"stock_code": code, "metrics": result}


@router.get("/{code}/predict")
def predict_dividend_cut(code: str):
    """Survival hazard 기반 배당 삭감 위험도 예측."""
    needed = ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex", "payout_ratio"]
    rows = query_all(
        """SELECT metric_name, value FROM metric_snapshots
           WHERE stock_code = :code AND metric_name = ANY(:metrics)
           ORDER BY date DESC""",
        {"code": code, "metrics": needed},
    )
    metrics = {}
    for metric, value in rows:
        if metric not in metrics:
            metrics[metric] = float(value)

    if not metrics:
        raise HTTPException(status_code=404, detail="재무 지표 데이터가 없습니다.")

    fcf      = metrics.get("fcf", 0) or 0
    ocf      = metrics.get("operating_cf", 1) or 1
    div_paid = metrics.get("dividends_paid", 0) or 0
    feat_map = {
        "fcf":               fcf,
        "dividends_paid":    div_paid,
        "dividend_coverage": metrics.get("dividend_coverage", 0) or 0,
        "operating_cf":      ocf,
        "capex":             metrics.get("capex", 0) or 0,
        "div_to_ocf":        div_paid / (abs(ocf) + 1),
        "fcf_negative":      1 if fcf < 0 else 0,
        "ocf_to_capex":      ocf / (abs(metrics.get("capex", 1)) + 1),
        "payout_ratio":      metrics.get("payout_ratio", 0) or 0,
        "dps_yoy_pct":       0,
    }
    surv = _surv_explain(feat_map)
    hazard   = surv.get("hazard", 0.0)
    pred_lbl = surv.get("prediction", "INTACT")
    cut_prob = round(hazard * 100, 1)
    risk_level = "높음" if pred_lbl == "BROKEN" else ("보통" if pred_lbl == "WEAKENING" else "낮음")
    prediction = "삭감 위험" if pred_lbl == "BROKEN" else ("배당 약화 주의" if pred_lbl == "WEAKENING" else "배당 유지")

    return {
        "stock_code":   code,
        "cut_prob":     cut_prob,
        "prediction":   prediction,
        "risk_level":   risk_level,
        "used_metrics": metrics,
    }

@router.get("/{code}/explain")
def explain_prediction_endpoint(code: str):
    """Survival hazard 기반 배당 삭감 예측 근거 설명."""
    import json as _json
    needed = ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex", "payout_ratio"]
    try:
        rows = query_all(
            """SELECT metric_name, value FROM metric_snapshots
               WHERE stock_code = :code AND metric_name = ANY(:metrics)
               ORDER BY date DESC""",
            {"code": code, "metrics": needed},
        )
    except Exception:
        rows = []
    metrics = {}
    for metric, value in rows:
        if metric not in metrics:
            metrics[metric] = float(value)

    dps_yoy = 0.0
    if not metrics:
        try:
            import pandas as _pd
            csv_path = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
            df = _pd.read_csv(csv_path, dtype={"stock_code": str})
            df["stock_code"] = df["stock_code"].str.zfill(6)
            sub = df[df["stock_code"] == str(code).zfill(6)]
            if "year" in sub.columns:
                sub = sub.sort_values("year")
            if len(sub):
                def _last(col):
                    if col not in sub.columns: return None
                    s = sub[col].dropna()
                    return float(s.iloc[-1]) if len(s) else None
                for m in ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex", "payout_ratio"]:
                    v = _last(m)
                    if v is not None:
                        metrics[m] = v
                dv = _last("dps_yoy_pct")
                if dv is not None:
                    dps_yoy = dv
        except Exception:
            pass

    if not metrics:
        raise HTTPException(status_code=404, detail="재무 지표 데이터가 없습니다.")

    fcf      = metrics.get("fcf", 0) or 0
    ocf      = metrics.get("operating_cf", 1) or 1
    div_paid = metrics.get("dividends_paid", 0) or 0
    feat_map = {
        "fcf":               fcf,
        "dividends_paid":    div_paid,
        "dividend_coverage": metrics.get("dividend_coverage", 0) or 0,
        "operating_cf":      ocf,
        "capex":             metrics.get("capex", 0) or 0,
        "div_to_ocf":        div_paid / (abs(ocf) + 1),
        "fcf_negative":      1 if fcf < 0 else 0,
        "ocf_to_capex":      ocf / (abs(metrics.get("capex", 1)) + 1),
        "payout_ratio":      metrics.get("payout_ratio", 0) or 0,
        "dps_yoy_pct":       dps_yoy,
    }

    surv = _surv_explain(feat_map)
    hazard   = surv.get("hazard", 0.0)
    cut_prob = round(hazard * 100, 1)
    summary  = surv.get("summary", "")

    FEATURE_UNIT = {"payout_ratio": "%", "div_to_ocf": "%", "fcf_negative": "(0/1)",
                    "dividend_coverage": "x", "ocf_to_capex": "x", "dps_yoy_pct": "%"}
    RISK_DIRECTION = {
        "payout_ratio": lambda v: v > 70, "fcf": lambda v: v < 0,
        "fcf_negative": lambda v: v > 0,  "dividend_coverage": lambda v: v < 1.5,
        "div_to_ocf":   lambda v: v > 0.8,"operating_cf": lambda v: v < 0,
        "ocf_to_capex": lambda v: v < 1.0,"dps_yoy_pct": lambda v: v < -10,
    }

    top_risk_factors = []
    for i, factor in enumerate(surv.get("top_factors", [])[:6]):
        feat_name = factor.get("feature", "")
        value     = factor.get("value", feat_map.get(feat_name, 0))
        label     = factor.get("label_ko", feat_name)
        impact    = factor.get("impact", "medium")
        unit      = FEATURE_UNIT.get(feat_name, "")
        is_risk   = RISK_DIRECTION.get(feat_name, lambda v: False)(value)
        if abs(value) > 9999:
            value = round(9999.0 * (1 if value > 0 else -1), 0)
        top_risk_factors.append({
            "label":     label,
            "value":     round(value, 2) if isinstance(value, float) else value,
            "unit":      unit,
            "impact":    impact,
            "direction": "위험 증가" if is_risk else "정상 범위",
        })

    return {
        "cut_prob":        cut_prob,
        "top_risk_factors": top_risk_factors,
        "summary":         summary,
    }

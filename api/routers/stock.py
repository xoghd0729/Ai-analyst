"""
종목 상세 API — 개별 종목의 분석 결과 제공.

GET /api/stock/{code}           → 종목 기본 정보 + 점수
GET /api/stock/{code}/thesis    → AI 생성 투자 thesis (실시간 ML + 뉴스 분석)
GET /api/stock/{code}/metrics   → 재무 지표
GET /api/stock/{code}/predict   → XGBoost 배당 삭감 예측
"""

import os
import sys
import joblib
import logging
import numpy as np
from fastapi import APIRouter, HTTPException
from sqlalchemy import create_engine, text

# 프로젝트 루트를 sys.path에 추가 (agents/, collectors/ import 가능하게)
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _BASE_DIR not in sys.path:
    sys.path.insert(0, _BASE_DIR)

log = logging.getLogger(__name__)

router = APIRouter()
engine = create_engine("postgresql://localhost/ai_analyst")

BASE_DIR   = _BASE_DIR
MODEL_PATH = os.path.join(BASE_DIR, "models", "dividend_cut_model.pkl")


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

    # ── 3. ML 배당 삭감 확률 ──────────────────────────────────
    ml_risk_score = 0.0
    if os.path.exists(MODEL_PATH) and financial_data:
        try:
            fcf      = financial_data.get("fcf", 0) or 0
            ocf      = financial_data.get("operating_cf", 1) or 1
            div_paid = financial_data.get("dividends_paid", 0) or 0

            saved = joblib.load(MODEL_PATH)
            if isinstance(saved, dict):
                model          = saved["pipeline"]
                saved_features = saved.get("features", [])
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
                features = np.array([[feat_map.get(f, 0) for f in (saved_features or feat_map.keys())]])
            else:
                model    = saved
                features = np.array([[
                    fcf, div_paid,
                    financial_data.get("dividend_coverage", 0) or 0,
                    ocf, financial_data.get("capex", 0) or 0,
                    div_paid / (abs(ocf) + 1), 1 if fcf < 0 else 0,
                ]])

            ml_risk_score = float(model.predict_proba(features)[0][1])
        except Exception as e:
            log.warning(f"[thesis] ML 예측 실패 ({code}): {e}")

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
    """XGBoost로 배당 삭감 위험도 예측."""
    if not os.path.exists(MODEL_PATH):
        raise HTTPException(status_code=503, detail="모델 파일이 없습니다. train_model.py를 먼저 실행하세요.")

    # 최신 재무 지표 조회
    needed = ["fcf", "dividends_paid", "dividend_coverage", "operating_cf", "capex"]
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

    # 파생 피처 계산
    fcf      = metrics.get("fcf", 0) or 0
    ocf      = metrics.get("operating_cf", 1) or 1
    div_paid = metrics.get("dividends_paid", 0) or 0

    features = np.array([[
        fcf,
        div_paid,
        metrics.get("dividend_coverage", 0) or 0,
        ocf,
        metrics.get("capex", 0) or 0,
        div_paid / (abs(ocf) + 1),   # div_to_ocf
        1 if fcf < 0 else 0,          # fcf_negative
    ]])

    # v2 모델: dict 형식으로 저장 {"pipeline": ..., "features": ...}
    saved = joblib.load(MODEL_PATH)
    if isinstance(saved, dict):
        model    = saved["pipeline"]
        saved_features = saved.get("features", [])
        # 저장된 피처 순서에 맞게 배열 재구성
        feat_map = {
            "fcf":               fcf,
            "dividends_paid":    div_paid,
            "dividend_coverage": metrics.get("dividend_coverage", 0) or 0,
            "operating_cf":      ocf,
            "capex":             metrics.get("capex", 0) or 0,
            "div_to_ocf":        div_paid / (abs(ocf) + 1),
            "fcf_negative":      1 if fcf < 0 else 0,
            "ocf_to_capex":      ocf / (abs(metrics.get("capex", 1)) + 1),
            "payout_ratio":      0,
            "dps_yoy_pct":       0,
        }
        features = np.array([[feat_map.get(f, 0) for f in (saved_features or feat_map.keys())]])
    else:
        model = saved  # v1 구 모델 호환
    prob     = float(model.predict_proba(features)[0][1])
    pred     = int(model.predict(features)[0])

    risk_label = (
        "높음" if prob >= 0.7 else
        "보통" if prob >= 0.4 else
        "낮음"
    )

    return {
        "stock_code":   code,
        "cut_prob":     round(prob * 100, 1),
        "prediction":   "삭감 위험" if pred == 1 else "배당 유지",
        "risk_level":   risk_label,
        "used_metrics": metrics,
    }


@router.get("/{code}/explain")
def explain_prediction(code: str):
    """
    XGBoost 배당 삭감 예측 근거 설명 — Explainable AI.

    "왜 이 종목이 위험한가"를 feature importance 기반으로 설명.
    SHAP이 있으면 instance-level 기여도, 없으면 global importance 사용.

    반환 예시:
    {
      "cut_prob": 67.3,
      "top_risk_factors": [
        {"label": "배당성향", "value": 85.2, "unit": "%", "impact": "high", "direction": "위험 증가"},
        {"label": "잉여현금흐름 (FCF)", "value": -500, "unit": "억원", "impact": "high", "direction": "위험 증가"},
        {"label": "배당 커버리지", "value": 0.9, "unit": "x", "impact": "medium", "direction": "위험 증가"},
      ],
      "summary": "배당성향 과다와 FCF 마이너스가 주요 위험 요인입니다."
    }
    """
    import json as _json

    if not os.path.exists(MODEL_PATH):
        raise HTTPException(status_code=503, detail="모델 파일이 없습니다.")

    # ── 재무 지표 조회 ─────────────────────────────────────────
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

    # ── 모델 로드 + 예측 ──────────────────────────────────────
    fcf      = metrics.get("fcf", 0) or 0
    ocf      = metrics.get("operating_cf", 1) or 1
    div_paid = metrics.get("dividends_paid", 0) or 0

    saved = joblib.load(MODEL_PATH)
    model          = saved["pipeline"] if isinstance(saved, dict) else saved
    saved_features = saved.get("features", []) if isinstance(saved, dict) else []

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
    feature_names = saved_features or list(feat_map.keys())
    features      = np.array([[feat_map.get(f, 0) for f in feature_names]])
    prob          = float(model.predict_proba(features)[0][1])

    # ── Feature Importance 로드 ────────────────────────────────
    RESULT_DIR       = os.path.join(BASE_DIR, "results")
    importance_path  = os.path.join(RESULT_DIR, "feature_importance.json")

    FEATURE_LABEL_KO = {
        "fcf":               "잉여현금흐름 (FCF)",
        "dividends_paid":    "배당금 지급액",
        "dividend_coverage": "배당 커버리지",
        "operating_cf":      "영업현금흐름",
        "capex":             "설비투자 (CapEx)",
        "div_to_ocf":        "배당/영업현금흐름 비율",
        "fcf_negative":      "FCF 마이너스 여부",
        "ocf_to_capex":      "영업현금흐름/설비투자 비율",
        "payout_ratio":      "배당성향",
        "dps_yoy_pct":       "배당금 전년 대비 증감률",
    }
    FEATURE_UNIT = {
        "payout_ratio":      "%",
        "div_to_ocf":        "%",
        "fcf_negative":      "(0/1)",
        "dividend_coverage": "x",
        "ocf_to_capex":      "x",
        "dps_yoy_pct":       "%",
    }

    # global importance 순서로 정렬
    if os.path.exists(importance_path):
        with open(importance_path, encoding="utf-8") as f:
            imp_data = _json.load(f)
        ranked_features = [d["name"] for d in imp_data["features"]]
    else:
        # 모델 내부 importance로 fallback
        xgb_model   = model.named_steps["model"]
        importances  = xgb_model.feature_importances_
        ranked_features = [feature_names[i] for i in np.argsort(importances)[::-1]]

    # ── 위험 요인 분석 ─────────────────────────────────────────
    # 각 피처의 현재값이 "위험 방향"인지 판단
    RISK_DIRECTION = {
        "payout_ratio":      lambda v: v > 70,    # 70% 초과 → 위험
        "fcf":               lambda v: v < 0,      # 마이너스 → 위험
        "fcf_negative":      lambda v: v > 0,      # 1 → 위험
        "dividend_coverage": lambda v: v < 1.5,   # 1.5x 미만 → 위험
        "div_to_ocf":        lambda v: v > 0.8,   # 80% 초과 → 위험
        "operating_cf":      lambda v: v < 0,      # 마이너스 → 위험
        "ocf_to_capex":      lambda v: v < 1.0,   # 1x 미만 → 위험
        "dps_yoy_pct":       lambda v: v < -10,   # 10% 이상 감소 → 위험
    }

    top_factors = []
    for feat_name in ranked_features[:6]:  # 상위 6개 피처
        value   = feat_map.get(feat_name, 0)
        label   = FEATURE_LABEL_KO.get(feat_name, feat_name)
        unit    = FEATURE_UNIT.get(feat_name, "")
        is_risk = RISK_DIRECTION.get(feat_name, lambda v: False)(value)

        # 중요도 레벨
        rank = ranked_features.index(feat_name)
        impact = "high" if rank < 2 else ("medium" if rank < 4 else "low")

        top_factors.append({
            "feature":   feat_name,
            "label":     label,
            "value":     round(value, 2),
            "unit":      unit,
            "impact":    impact,
            "direction": "위험 증가" if is_risk else "안전",
        })

    # ── 자연어 요약 ────────────────────────────────────────────
    risk_factors   = [f for f in top_factors if f["direction"] == "위험 증가"]
    safe_factors   = [f for f in top_factors if f["direction"] == "안전"]

    if risk_factors:
        risk_labels = "와 ".join(f["label"] for f in risk_factors[:2])
        summary = f"{risk_labels}이(가) 주요 위험 요인입니다."
        if safe_factors:
            safe_label = safe_factors[0]["label"]
            summary += f" 반면 {safe_label}은(는) 양호한 상태입니다."
    else:
        summary = "현재 주요 재무 지표가 모두 양호한 상태입니다."

    return {
        "stock_code":      code,
        "cut_prob":        round(prob * 100, 1),
        "risk_level":      "높음" if prob >= 0.7 else ("보통" if prob >= 0.4 else "낮음"),
        "top_risk_factors": top_factors,
        "summary":         summary,
        "model_features":  len(feature_names),
    }

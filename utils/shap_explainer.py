"""
utils/shap_explainer.py  v2 - TabPFN Survival hazard score
===========================================================

v1 (XGBoost 3-class TreeExplainer) -> v2 (Survival hazard + rule-based attribution)

[분류 체계 - 종목 상태]
  hazard_pct < 0.35        -> INTACT    (안정)
  0.35 <= hazard_pct < 0.65 -> WEAKENING (주의)
  hazard_pct >= 0.65        -> BROKEN    (고위험)

[투자성향 gate - 별도 적용, 이 파일과 분리]
  conservative: gate=0.35 / moderate: gate=0.50 / aggressive: gate=0.65

[설명 방법]
  TabPFN은 TreeExplainer 불가 -> 재무지표 rule-based attribution.
  각 지표가 '위험 기준'을 얼마나 벗어나는지로 기여도 산출.
  kr_3class_model.pkl 기반 XGBoost 설명은 _explain_xgb_benchmark()로 보존.
"""
from __future__ import annotations

import json
import logging
import os
import pickle
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL_PATH = os.path.join(BASE_DIR, "results", "survival_pd_v4.json")
DATASET_PATH  = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
MODEL_PATH    = os.path.join(BASE_DIR, "models", "kr_3class_model.pkl")   # benchmark only

CLASS_NAMES = ["INTACT", "WEAKENING", "BROKEN"]

# 종목별 최신 재무 피처 캐시 (attribution 입력용)
_FEATURE_CACHE: dict | None = None
# 생존분석 결과 캐시
_SURVIVAL_CACHE: dict | None = None

# ─────────────────────────────────────────────────
# 피처 한국어 레이블
# ─────────────────────────────────────────────────
FEATURE_LABEL_KO = {
    "fcf":               "잉여현금흐름(FCF)",
    "dividends_paid":    "배당금 지급액",
    "dividend_coverage": "배당 커버리지",
    "operating_cf":      "영업현금흐름",
    "capex":             "설비투자(CapEx)",
    "div_to_ocf":        "배당/영업현금흐름 비율",
    "fcf_negative":      "FCF 적자 여부",
    "ocf_to_capex":      "영업CF/설비투자 비율",
    "payout_ratio":      "배당성향(%)",
    "dps_yoy_pct":       "배당금 전년 대비 증감률",
    "debt_ratio":        "부채비율(%)",
    "interest_coverage": "이자보상배율",
    "revenue_yoy_pct":   "매출 성장률(%)",
}

# ─────────────────────────────────────────────────
# Rule-based attribution 기준
# (feature, direction, warn_threshold, danger_threshold, weight)
# direction: "high" = 높을수록 위험 / "low" = 낮을수록 위험
# ─────────────────────────────────────────────────
_ATTRIBUTION_RULES: list[tuple] = [
    ("payout_ratio",      "high", 70.0,  90.0,  1.2),
    ("fcf_negative",      "high",  0.5,   1.0,  1.0),
    ("div_to_ocf",        "high",  0.7,   1.0,  1.1),
    ("dps_yoy_pct",       "low",  -5.0, -20.0,  1.0),
    ("interest_coverage", "low",   3.0,   1.5,  0.9),
    ("debt_ratio",        "high", 200.0, 350.0,  0.8),
    ("dividend_coverage", "low",   1.5,   1.0,  1.0),
    ("ocf_to_capex",      "low",   1.2,   0.8,  0.8),
    ("revenue_yoy_pct",   "low",  -3.0, -10.0,  0.7),
    ("operating_cf",      "low",   0.0,  -1e9,  0.7),
]


# ─────────────────────────────────────────────────
# 데이터 로더
# ─────────────────────────────────────────────────

def _load_survival_scores() -> dict:
    global _SURVIVAL_CACHE
    if _SURVIVAL_CACHE is not None:
        return _SURVIVAL_CACHE
    try:
        with open(SURVIVAL_PATH, encoding="utf-8") as f:
            d = json.load(f)
        _SURVIVAL_CACHE = d.get("stock_risk", {})
    except Exception as e:
        log.warning("survival_pd_v4.json 로드 실패: %s", e)
        _SURVIVAL_CACHE = {}
    return _SURVIVAL_CACHE


def _load_latest_features() -> dict:
    global _FEATURE_CACHE
    if _FEATURE_CACHE is not None:
        return _FEATURE_CACHE
    out: dict = {}
    try:
        import pandas as pd
        df = pd.read_csv(DATASET_PATH, dtype={"stock_code": str})
        df = df.sort_values(["stock_code", "year"])
        latest = df.groupby("stock_code").tail(1)
        for _, r in latest.iterrows():
            code = str(r["stock_code"]).zfill(6)
            ocf  = float(r.get("operating_cf") or 0)
            capex = float(r.get("capex") or 0)
            fcf   = r.get("fcf")
            divp  = float(r.get("dividends_paid") or 0)
            feat = {
                "fcf":               float(fcf) if hasattr(fcf, '__float__') and fcf == fcf else 0.0,
                "dividends_paid":    divp,
                "dividend_coverage": float(r.get("dividend_coverage") or 0),
                "operating_cf":      ocf,
                "capex":             capex,
                "payout_ratio":      float(r.get("payout_ratio") or 0),
                "dps_yoy_pct":       float(r.get("dps_yoy_pct") or 0),
                "debt_ratio":        float(r.get("debt_ratio") or 0),
                "interest_coverage": float(r.get("interest_coverage") or 0),
                "revenue_yoy_pct":   float(r.get("revenue_yoy_pct") or 0),
                "div_to_ocf":        divp / (abs(ocf) + 1),
                "fcf_negative":      1 if (fcf is not None and fcf == fcf and float(fcf) < 0) else 0,
                "ocf_to_capex":      ocf / (abs(capex) + 1),
            }
            out[code] = feat
    except Exception as e:
        log.warning("최신 피처 로드 실패: %s", e)
    _FEATURE_CACHE = out
    return out


# ─────────────────────────────────────────────────
# 핵심 분류 함수
# ─────────────────────────────────────────────────

def classify_by_hazard(hazard: float) -> str:
    """
    TabPFN Survival hazard score -> INTACT / WEAKENING / BROKEN.
    hazard 는 uncalibrated risk score (배당삭감 확률이 아님).
    """
    if hazard < 0.35:
        return "INTACT"
    if hazard < 0.65:
        return "WEAKENING"
    return "BROKEN"


# ─────────────────────────────────────────────────
# Rule-based Feature Attribution
# ─────────────────────────────────────────────────

def _compute_attribution(stock_data: dict, n_top: int = 3) -> list[dict]:
    """
    재무지표 기반 위험 기여도 계산.
    TabPFN 모델의 실제 gradient/SHAP이 아닌 도메인 지식 기반 attribution.
    각 지표가 위험 기준(warn/danger threshold)을 얼마나 벗어나는지 점수화.
    """
    scores: dict[str, float] = {}

    for fname, direction, warn, danger, weight in _ATTRIBUTION_RULES:
        val = stock_data.get(fname)
        if val is None:
            continue
        val = float(val)

        if direction == "high":
            if val >= danger:
                score = 1.0 * weight
            elif val >= warn:
                score = ((val - warn) / (abs(danger - warn) + 1e-9)) * weight * 0.6
            else:
                score = 0.0
        else:  # "low"
            if val <= danger:
                score = 1.0 * weight
            elif val <= warn:
                score = ((warn - val) / (abs(warn - danger) + 1e-9)) * weight * 0.6
            else:
                score = 0.0

        if score > 0:
            scores[fname] = score

    # 절댓값 기준 정렬
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n_top]

    factors = []
    for fname, score in ranked:
        raw = stock_data.get(fname, 0) or 0
        factors.append({
            "feature":   fname,
            "label_ko":  FEATURE_LABEL_KO.get(fname, fname),
            "score":     round(score, 4),
            "direction": "위험",
            "raw_value": round(float(raw), 2),
        })
    return factors


def _build_summary_v2(prediction: str, top_factors: list, hazard: float,
                      survival_1y: float | None) -> str:
    risk_labels = [f["label_ko"] for f in top_factors]
    surv_str = f", 1년 생존률 {survival_1y:.1f}%" if survival_1y is not None else ""

    if prediction == "INTACT":
        return f"배당 유지 안정 판정 (위험도 {hazard:.2f}{surv_str}). 주요 재무 지표 정상 범위."

    label = "배당 약화" if prediction == "WEAKENING" else "배당 삭감 고위험"
    parts = [f"{label} 감지 (위험도 {hazard:.2f}{surv_str})."]
    if risk_labels:
        parts.append(f"주요 위험 요인: {', '.join(risk_labels)}.")
    return " ".join(parts)


# ─────────────────────────────────────────────────
# 공개 API
# ─────────────────────────────────────────────────

def explain_prediction(
    stock_data: dict,
    hazard: float | None = None,
    survival_1y: float | None = None,
    n_top: int = 3,
) -> dict:
    """
    단일 종목 위험 설명 반환 (v2: Survival hazard 기반).

    Args:
        stock_data:   재무 피처 딕셔너리
        hazard:       TabPFN Survival hazard score (None이면 재무지표로만 판단)
        survival_1y:  1년 생존률 (%, None 허용)
        n_top:        상위 기여 피처 개수

    Returns:
        prediction, hazard, top_factors, summary, method
    """
    # hazard 없으면 재무지표로 간이 판단
    if hazard is None:
        payout = float(stock_data.get("payout_ratio", 50) or 50)
        fcf_neg = float(stock_data.get("fcf_negative", 0) or 0)
        hazard_est = min(0.9, payout / 200 + fcf_neg * 0.3)
        prediction = classify_by_hazard(hazard_est)
        hazard = hazard_est
        method = "rule-based (no survival score)"
    else:
        prediction = classify_by_hazard(hazard)
        method = "TabPFN Survival hazard"

    top_factors = _compute_attribution(stock_data, n_top=n_top)
    summary = _build_summary_v2(prediction, top_factors, hazard, survival_1y)

    return {
        "prediction":   prediction,
        "hazard":       round(hazard, 4),
        "survival_1y":  survival_1y,
        "top_factors":  top_factors,
        "summary":      summary,
        "method":       method,
    }


def explain_portfolio_risks(recommendations: list[dict]) -> list[dict]:
    """
    포트폴리오 전 종목 설명 일괄 생성.
    SurvivalWeightFilter가 이미 survival_risk_score를 채워놓음.
    WEAKENING / BROKEN 종목만 attribution 생성.
    """
    survival_scores = _load_survival_scores()
    features = _load_latest_features()
    results = []

    for rec in recommendations:
        ticker = rec.get("ticker", "")
        code   = str(rec.get("stock_code", "")).zfill(6)

        # hazard: SurvivalWeightFilter 결과 우선, 없으면 survival_pd_v4.json 직접
        hazard = rec.get("survival_risk_score")
        survival_1y = rec.get("survival_1y")
        if hazard is None:
            sr = survival_scores.get(ticker) or survival_scores.get(code) or {}
            hazard = sr.get("hazard_pct")
            survival_1y = sr.get("survival_1y")

        prediction = classify_by_hazard(float(hazard)) if hazard is not None else "INTACT"

        if prediction == "INTACT":
            results.append({
                "ticker":      ticker,
                "name":        rec.get("name", ""),
                "prediction":  "INTACT",
                "hazard":      round(float(hazard), 4) if hazard is not None else None,
                "survival_1y": survival_1y,
                "explanation": None,
            })
            continue

        # 재무 피처: CSV 최신 연도 우선
        stock_data = dict(features.get(code, {}))
        # 추천 데이터에서 최신값 덮어쓰기
        for k in ("payout_ratio", "dps_yoy_pct", "dividend_coverage"):
            v = rec.get(k)
            if v is not None:
                stock_data[k] = v

        explanation = explain_prediction(
            stock_data,
            hazard=float(hazard) if hazard is not None else None,
            survival_1y=survival_1y,
        )
        results.append({
            "ticker":      ticker,
            "name":        rec.get("name", ""),
            "prediction":  prediction,
            "hazard":      explanation["hazard"],
            "survival_1y": survival_1y,
            "weight_pct":  rec.get("weight_pct", 0),
            "explanation": explanation,
        })

    return results


# ─────────────────────────────────────────────────
# Benchmark: 기존 XGBoost 3-class (보존용)
# ─────────────────────────────────────────────────

_xgb_model_cache: Optional[dict] = None


def _explain_xgb_benchmark(stock_data: dict, n_top: int = 3) -> dict:
    """
    kr_3class_model.pkl (XGBoost) 기반 설명. benchmark / 비교용.
    프로덕션 경로에서는 호출하지 않음.
    """
    global _xgb_model_cache
    if _xgb_model_cache is None:
        if not os.path.exists(MODEL_PATH):
            return {"error": "kr_3class_model.pkl not found"}
        try:
            try:
                import joblib
                _xgb_model_cache = joblib.load(MODEL_PATH)
            except ImportError:
                with open(MODEL_PATH, "rb") as f:
                    _xgb_model_cache = pickle.load(f)
        except Exception as e:
            return {"error": str(e)}

    bundle = _xgb_model_cache
    try:
        import shap

        pipeline      = bundle.get("pipeline") or bundle.get("model")
        feature_names = bundle.get("feature_names") or bundle.get("features", [])
        if pipeline is None or not feature_names:
            return {"error": "bundle structure unknown"}

        X_row = np.array([[float(stock_data.get(f, 0) or 0) for f in feature_names]])

        if hasattr(pipeline, "steps"):
            xgb_model     = pipeline.steps[-1][1]
            X_transformed = pipeline[:-1].transform(X_row)
        else:
            xgb_model     = pipeline
            X_transformed = X_row

        proba      = pipeline.predict_proba(X_row)[0]
        pred_idx   = int(np.argmax(proba))
        prediction = CLASS_NAMES[pred_idx]
        confidence = float(proba[pred_idx])

        explainer   = shap.TreeExplainer(xgb_model)
        shap_values = explainer.shap_values(X_transformed)

        n_classes = len(CLASS_NAMES)
        if isinstance(shap_values, list):
            sv = np.asarray(shap_values[pred_idx])[0]
        else:
            arr = np.asarray(shap_values)
            if arr.ndim == 3:
                sv = arr[0, :, pred_idx] if arr.shape[-1] == n_classes else arr[pred_idx, 0, :]
            else:
                sv = arr[0]
        sv = np.asarray(sv).ravel()

        ranked = sorted(zip(feature_names, sv), key=lambda x: abs(x[1]), reverse=True)[:n_top]
        top_factors = [
            {
                "feature":   fn,
                "label_ko":  FEATURE_LABEL_KO.get(fn, fn),
                "shap_value": round(float(sv_), 4),
                "direction": "위험" if sv_ > 0 else "안전",
                "raw_value": round(float(stock_data.get(fn, 0) or 0), 2),
            }
            for fn, sv_ in ranked
        ]

        return {
            "prediction":    prediction,
            "confidence":    round(confidence, 3),
            "probabilities": {CLASS_NAMES[i]: round(float(p), 3) for i, p in enumerate(proba)},
            "top_factors":   top_factors,
            "method":        "SHAP TreeExplainer (XGBoost benchmark)",
        }
    except Exception as e:
        log.error("XGBoost benchmark SHAP 실패: %s", e, exc_info=True)
        return {"error": str(e)}

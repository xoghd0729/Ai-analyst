"""
utils/shap_explainer.py — ML 판단 근거 설명 엔진 (SHAP)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 SHAP인가?
  XGBoost가 "WEAKENING"을 판단했을 때 "왜?"를 설명할 수 없으면
  AI 블랙박스라는 비판을 피할 수 없다.

  SHAP(SHapley Additive exPlanations):
    각 피처가 최종 예측에 얼마나 기여했는지 수치로 계산.
    "payout_ratio 92%가 위험도를 +0.34 올렸다"
    이 한 줄이 ML 신뢰도를 완전히 바꾼다.

■ 동작 방식
  1. 저장된 XGBoost 모델(pkl)을 SHAP TreeExplainer에 연결
  2. 종목 데이터 한 행 → SHAP values 계산
  3. 상위 기여 피처 3개를 한국어로 번역해 반환
  4. 판단에 대한 신뢰도(confidence) 도 함께 반환

■ 반환 구조
  {
    "prediction":   "WEAKENING",
    "confidence":   0.74,
    "top_factors": [
      {"feature": "payout_ratio",   "label_ko": "배당성향",    "shap_value": +0.34, "direction": "위험"},
      {"feature": "fcf_negative",   "label_ko": "FCF 적자",    "shap_value": +0.21, "direction": "위험"},
      {"feature": "div_to_ocf",     "label_ko": "배당/영업CF", "shap_value": +0.15, "direction": "위험"},
    ],
    "summary": "배당성향 과도·잉여현금흐름 적자로 배당 약화 위험 감지",
  }
"""
from __future__ import annotations

import logging
import os
import pickle
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "kr_3class_model.pkl")
DATASET_PATH = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")

# 종목별 최신 연도 피처 캐시 (SHAP 입력용 — 실제 재무값 공급)
_FEATURE_CACHE: dict | None = None


def _load_latest_features() -> dict:
    """dividend_dataset.csv에서 종목별 '최신 연도' 13개 피처를 로드.

    SHAP 설명은 실제 재무값이 있어야 의미가 있다. 추천 데이터(ranking 기반)에는
    원시 재무값이 없으므로, 학습 데이터셋에서 종목별 최신 행을 끌어와 공급한다.
    파생 피처(div_to_ocf, fcf_negative, ocf_to_capex)도 여기서 계산한다.
    """
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
            ocf = float(r.get("operating_cf") or 0)
            capex = float(r.get("capex") or 0)
            fcf = r.get("fcf")
            divp = float(r.get("dividends_paid") or 0)
            feat = {
                "fcf":               float(fcf) if pd.notna(fcf) else 0.0,
                "dividends_paid":    divp,
                "dividend_coverage": float(r.get("dividend_coverage") or 0),
                "operating_cf":      ocf,
                "capex":             capex,
                "payout_ratio":      float(r.get("payout_ratio") or 0),
                "dps_yoy_pct":       float(r.get("dps_yoy_pct") or 0),
                "debt_ratio":        float(r.get("debt_ratio") or 0),
                "interest_coverage": float(r.get("interest_coverage") or 0),
                "revenue_yoy_pct":   float(r.get("revenue_yoy_pct") or 0),
                # 파생 피처 (학습 시 build_features와 동일 정의)
                "div_to_ocf":        divp / (abs(ocf) + 1),
                "fcf_negative":      1 if (pd.notna(fcf) and float(fcf) < 0) else 0,
                "ocf_to_capex":      ocf / (abs(capex) + 1),
            }
            out[code] = feat
    except Exception as e:
        log.warning("최신 피처 로드 실패: %s", e)
    _FEATURE_CACHE = out
    return out

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

CLASS_NAMES = ["INTACT", "WEAKENING", "BROKEN"]

_model_cache: Optional[dict] = None


def _load_model() -> Optional[dict]:
    global _model_cache
    if _model_cache is not None:
        return _model_cache
    if not os.path.exists(MODEL_PATH):
        log.warning("모델 파일 없음: %s", MODEL_PATH)
        return None
    # 모델은 train_kr_3class.py 에서 joblib.dump 로 저장됨 → joblib.load 우선.
    # (일반 pickle.load 로 읽으면 'No module named Pipeline' 등 클래스 해석 실패)
    try:
        import joblib
        bundle = joblib.load(MODEL_PATH)
        _model_cache = bundle
        return bundle
    except Exception as e_joblib:
        try:
            with open(MODEL_PATH, "rb") as f:
                bundle = pickle.load(f)
            _model_cache = bundle
            return bundle
        except Exception as e:
            log.error("모델 로드 실패: joblib(%s) / pickle(%s)", e_joblib, e)
            return None


def explain_prediction(
    stock_data: dict,
    n_top:      int = 3,
) -> dict:
    """
    단일 종목에 대한 SHAP 기반 ML 판단 근거 반환.

    Args:
        stock_data: 종목 피처 딕셔너리
                    {fcf, dividends_paid, dividend_coverage, operating_cf,
                     capex, payout_ratio, dps_yoy_pct, ...}
        n_top:      상위 기여 피처 개수 (기본 3개)

    Returns:
        prediction, confidence, top_factors, summary
    """
    bundle = _load_model()
    if bundle is None:
        return _fallback_explanation(stock_data)

    try:
        import shap
    except ImportError:
        log.warning("shap 미설치. pip install shap --break-system-packages")
        return _fallback_explanation(stock_data)

    try:
        pipeline       = bundle.get("pipeline") or bundle.get("model")
        feature_names  = bundle.get("feature_names") or bundle.get("features", [])

        if pipeline is None or not feature_names:
            return _fallback_explanation(stock_data)

        # 피처 벡터 구성 (누락 피처는 0으로 채움)
        X_row = np.array([[float(stock_data.get(f, 0) or 0) for f in feature_names]])

        # 파이프라인에서 XGBoost 추출 (SimpleImputer → XGBoost 구조)
        if hasattr(pipeline, "steps"):
            xgb_model = pipeline.steps[-1][1]
            X_transformed = pipeline[:-1].transform(X_row)
        else:
            xgb_model    = pipeline
            X_transformed = X_row

        # 예측 확률
        proba = pipeline.predict_proba(X_row)[0]
        pred_idx     = int(np.argmax(proba))
        prediction   = CLASS_NAMES[pred_idx]
        confidence   = float(proba[pred_idx])

        # SHAP TreeExplainer
        explainer   = shap.TreeExplainer(xgb_model)
        shap_values = explainer.shap_values(X_transformed)

        # 다중 클래스 SHAP 출력은 shap 버전마다 형태가 다름:
        #   구버전: list[n_classes] of (n_samples, n_features)
        #   신버전: ndarray (n_samples, n_features, n_classes)
        # 예측 클래스의 기여도를 버전 무관하게 추출.
        n_classes = len(CLASS_NAMES)
        if isinstance(shap_values, list):
            sv = np.asarray(shap_values[pred_idx])[0]
        else:
            arr = np.asarray(shap_values)
            if arr.ndim == 3:
                if arr.shape[-1] == n_classes:        # (samples, features, classes)
                    sv = arr[0, :, pred_idx]
                else:                                  # (classes, samples, features)
                    sv = arr[pred_idx, 0, :]
            else:                                       # 이진/단일: (samples, features)
                sv = arr[0]
        sv = np.asarray(sv).ravel()

        # 상위 기여 피처 (절댓값 기준 정렬)
        feat_contributions = sorted(
            zip(feature_names, sv),
            key=lambda x: abs(x[1]),
            reverse=True,
        )[:n_top]

        top_factors = []
        for fname, shap_val in feat_contributions:
            direction = "위험" if shap_val > 0 else "안전"
            top_factors.append({
                "feature":    fname,
                "label_ko":   FEATURE_LABEL_KO.get(fname, fname),
                "shap_value": round(float(shap_val), 4),
                "direction":  direction,
                "raw_value":  round(float(stock_data.get(fname, 0) or 0), 2),
            })

        summary = _build_summary(prediction, top_factors, confidence)

        return {
            "prediction":   prediction,
            "confidence":   round(confidence, 3),
            "probabilities": {
                CLASS_NAMES[i]: round(float(p), 3)
                for i, p in enumerate(proba)
            },
            "top_factors":  top_factors,
            "summary":      summary,
            "method":       "SHAP TreeExplainer",
        }

    except Exception as e:
        log.error("SHAP 계산 실패: %s", e, exc_info=True)
        return _fallback_explanation(stock_data)


def explain_portfolio_risks(recommendations: list[dict]) -> list[dict]:
    """
    포트폴리오 전 종목에 대해 SHAP 설명 일괄 생성.
    ML 위험 종목(WEAKENING/BROKEN)만 설명 생성.
    """
    results = []
    for rec in recommendations:
        ml_status = rec.get("ml_status", "INTACT")
        if ml_status == "INTACT":
            results.append({
                "ticker":    rec.get("ticker", ""),
                "name":      rec.get("name", ""),
                "ml_status": ml_status,
                "explanation": None,
            })
            continue

        # 종목 피처: 학습 데이터셋의 최신 연도 실제 재무값 우선 (13개 전부 공급)
        code = str(rec.get("stock_code", "")).zfill(6)
        feats = _load_latest_features().get(code, {})
        if feats:
            stock_data = dict(feats)
        else:
            # 폴백: 추천 데이터에 있는 값만 (없으면 explain_prediction이 0 처리)
            stock_data = {
                "fcf":               rec.get("fcf", 0),
                "dividends_paid":    rec.get("dividends_paid", 0),
                "dividend_coverage": rec.get("dividend_coverage", 1.0),
                "operating_cf":      rec.get("operating_cf", 0),
                "capex":             rec.get("capex", 0),
                "payout_ratio":      rec.get("payout_ratio", 50),
                "dps_yoy_pct":       rec.get("dps_yoy_pct") or rec.get("latest_yoy_pct", 0),
            }
        # 추천 데이터에 더 최신 값이 있으면 덮어쓰기 (실시간 우선)
        for k in ("dps_yoy_pct", "payout_ratio"):
            v = rec.get(k)
            if v is not None:
                stock_data[k] = v

        explanation = explain_prediction(stock_data)
        results.append({
            "ticker":      rec.get("ticker", ""),
            "name":        rec.get("name", ""),
            "ml_status":   ml_status,
            "weight_pct":  rec.get("weight_pct", 0),
            "explanation": explanation,
        })

    return results


def _build_summary(prediction: str, top_factors: list, confidence: float) -> str:
    """상위 요인 기반 한국어 요약 문장 생성."""
    if prediction == "INTACT":
        return f"배당 유지 안정 판정 (신뢰도 {confidence*100:.0f}%). 주요 재무 지표 정상 범위."

    risk_factors = [f["label_ko"] for f in top_factors if f["shap_value"] > 0]
    safe_factors = [f["label_ko"] for f in top_factors if f["shap_value"] < 0]

    label = "배당 약화" if prediction == "WEAKENING" else "배당 삭감"
    parts = [f"{label} 위험 감지 (신뢰도 {confidence*100:.0f}%)."]

    if risk_factors:
        parts.append(f"주요 위험 요인: {', '.join(risk_factors)}.")
    if safe_factors:
        parts.append(f"방어 요인: {', '.join(safe_factors)}.")

    return " ".join(parts)


def _fallback_explanation(stock_data: dict) -> dict:
    """SHAP/모델 없을 때 feature importance 기반 fallback."""
    payout = float(stock_data.get("payout_ratio", 50) or 50)
    dps_yoy = float(stock_data.get("dps_yoy_pct", 0) or 0)
    fcf = float(stock_data.get("fcf", 1) or 1)

    factors = []
    if payout > 80:
        factors.append({"feature": "payout_ratio", "label_ko": "배당성향(%)",
                        "shap_value": (payout - 50) / 100, "direction": "위험", "raw_value": payout})
    if dps_yoy < -10:
        factors.append({"feature": "dps_yoy_pct", "label_ko": "배당금 전년비 증감률",
                        "shap_value": abs(dps_yoy) / 100, "direction": "위험", "raw_value": dps_yoy})
    if fcf < 0:
        factors.append({"feature": "fcf", "label_ko": "잉여현금흐름(FCF)",
                        "shap_value": 0.2, "direction": "위험", "raw_value": fcf})

    return {
        "prediction":  "UNKNOWN",
        "confidence":  0.0,
        "top_factors": factors[:3],
        "summary":    "SHAP 미지원 — 재무 지표 기반 간이 설명",
        "method":     "rule-based fallback",
    }

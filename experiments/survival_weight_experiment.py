"""
survival_weight_experiment.py  v2
===============================================================
Survival 단일 소스 구조 가중치 재검증 실험 — 올바른 라벨 적용

v1과의 차이:
  - 타깃: dividend_cut(t) [당해 삭감] → label_cut_1y(t) [t+1년 삭감 예측]
  - 데이터: dividend_dataset_with_events.csv → dividend_dataset.csv
  - 평가 연도: 2024 (2024년 피처 → 2025년 삭감 예측) 또는
               2023 (2023년 피처 → 2024년 삭감 예측)
    → 유효한 label_cut_1y가 있는 가장 최근 연도를 자동 선택

알려진 한계 (문서에 명시):
  - survival_pd_v4.json은 전체 기간 데이터 기반 scoring → 누수 가능성
  - 진짜 walk-forward는 연도별 Survival 재학습 필요
  - 단면 평가 (cross-sectional) — 결과는 방향성 참고용

실행:
  cd ~/ai-analyst
  python experiments/survival_weight_experiment.py

출력:
  results/survival_weight_report.json   (INVALIDATED 플래그 제거된 새 결과)
"""
from __future__ import annotations
import json
import os
import warnings
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    f1_score,
)

warnings.filterwarnings("ignore")

BASE     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOP_FRAC = 0.20

# risk_engine.py와 동일한 상수
_ML_SCORE = {"INTACT": 15.0, "WEAKENING": 55.0, "BROKEN": 90.0}


# ══════════════════════════════════════════════════════════════
# 1. 데이터 로드
# ══════════════════════════════════════════════════════════════

def load_survival_hazards() -> Dict[str, float]:
    """survival_pd_v4.json → {stock_code: hazard_pct}

    ⚠️ 누수 주의: 전체 기간 데이터 기반 scoring.
    연도별 재산출 없이 사용하므로 walk-forward 정합성 미보장.
    """
    path = os.path.join(BASE, "results", "survival_pd_v4.json")
    with open(path) as f:
        data = json.load(f)
    return {k: float(v.get("hazard_pct", 0.5))
            for k, v in data.get("stock_risk", {}).items()}


def load_ml_status() -> Dict[str, str]:
    """ml_scoring_results.csv → {stock_code: ml_status}"""
    path = os.path.join(BASE, "data", "ml_scoring_results.csv")
    df = pd.read_csv(path, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(6)
    return dict(zip(df["stock_code"], df["ml_status"].fillna("INTACT")))


def find_eval_year(df: pd.DataFrame) -> int:
    """label_cut_1y가 유효한 가장 최근 연도 자동 선택."""
    df_valid = df.dropna(subset=["label_cut_1y"])
    if df_valid.empty:
        raise ValueError("label_cut_1y 컬럼에 유효한 값이 없습니다.")
    return int(df_valid["year"].max())


def load_features_and_labels(eval_year: int) -> pd.DataFrame:
    """
    dividend_dataset.csv에서 eval_year 행을 추출.

    피처 시점:  eval_year (t)
    예측 타깃: label_cut_1y(t) = t+1년 배당 삭감 여부
    """
    path = os.path.join(BASE, "data", "dividend_dataset.csv")
    df = pd.read_csv(path, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(6)
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    df["label_cut_1y"] = pd.to_numeric(df["label_cut_1y"], errors="coerce")

    df_year = df[df["year"] == eval_year].dropna(subset=["label_cut_1y"]).copy()
    return df_year[["stock_code", "year", "label_cut_1y"]].drop_duplicates("stock_code")


# ══════════════════════════════════════════════════════════════
# 2. 피처 테이블 조립
# ══════════════════════════════════════════════════════════════

def build_feature_table(eval_year: int) -> pd.DataFrame:
    hazards  = load_survival_hazards()
    statuses = load_ml_status()
    labels   = load_features_and_labels(eval_year)

    rows = []
    for _, row in labels.iterrows():
        code  = str(row["stock_code"])
        label = int(row["label_cut_1y"])

        hz = hazards.get(code)
        st = statuses.get(code, "INTACT")
        st_score = _ML_SCORE.get(st.upper(), _ML_SCORE["WEAKENING"])

        if hz is None:
            hz = {"INTACT": 0.2, "WEAKENING": 0.5, "BROKEN": 0.8}.get(st.upper(), 0.5)

        rows.append({
            "stock_code":   code,
            "label":        label,
            "hazard":       hz,
            "hazard_score": round(hz * 100, 1),
            "status":       st,
            "status_score": st_score,
        })

    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════
# 3. 평가
# ══════════════════════════════════════════════════════════════

def evaluate(y_true: np.ndarray, y_score: np.ndarray, name: str) -> Dict:
    if y_true.sum() == 0:
        print(f"  [SKIP] {name}: 이벤트 없음")
        return {}
    roc = roc_auc_score(y_true, y_score)
    pr  = average_precision_score(y_true, y_score)
    n_top = max(1, int(len(y_score) * TOP_FRAC))
    top_idx = np.argsort(-y_score)[:n_top]
    p_at = float(y_true[top_idx].mean())
    r_at = float(y_true[top_idx].sum() / max(1, y_true.sum()))
    y_pred = (y_score >= 50.0).astype(int)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    return {
        "method":     name,
        "n_samples":  int(len(y_true)),
        "n_events":   int(y_true.sum()),
        "event_rate": round(float(y_true.mean()), 4),
        "roc_auc":    round(roc, 4),
        "pr_auc":     round(pr,  4),
        "p_at_top20": round(p_at, 4),
        "r_at_top20": round(r_at, 4),
        "f1_at_50":   round(float(f1), 4),
    }


# ══════════════════════════════════════════════════════════════
# 4. 전략 비교
# ══════════════════════════════════════════════════════════════

def run_strategies(df: pd.DataFrame) -> Tuple[Dict, List]:
    y_true = df["label"].values.astype(int)
    results = {}

    results["A_hazard_only"] = evaluate(
        y_true, df["hazard_score"].values, "Survival hazard 단독")

    results["B_status_only"] = evaluate(
        y_true, df["status_score"].values, "ml_status 단독 (이산)")

    score_C = df["status_score"].values * 0.70 + df["hazard_score"].values * 0.30
    results["C_70_30"] = evaluate(y_true, score_C, "현재 70:30 (Survival 단일소스)")

    score_D = df["status_score"].values * 0.50 + df["hazard_score"].values * 0.50
    results["D_50_50"] = evaluate(y_true, score_D, "50:50")

    # 그리드 탐색
    grid, best_roc, best_w = [], -1.0, 0.70
    for w in np.arange(0.0, 1.05, 0.05):
        w = round(float(w), 2)
        sc = df["status_score"].values * w + df["hazard_score"].values * (1 - w)
        try:
            rg = roc_auc_score(y_true, sc)
            pg = average_precision_score(y_true, sc)
            grid.append({"w_status": w, "w_hazard": round(1 - w, 2),
                         "roc_auc": round(rg, 4), "pr_auc": round(pg, 4)})
            if rg > best_roc:
                best_roc, best_w = rg, w
        except Exception:
            pass

    score_E = df["status_score"].values * best_w + df["hazard_score"].values * (1 - best_w)
    res_E = evaluate(y_true, score_E, f"최적 (w_status={best_w:.2f})")
    res_E["optimal_w_status"] = best_w
    res_E["optimal_w_hazard"] = round(1 - best_w, 2)
    results["E_optimal"] = res_E

    results["REF_past_2model_7030"] = {
        "method":     "과거 독립 2모델 70:30 (참조값 — 현재 구조와 모델 구성 다름)",
        "roc_auc":    0.7824,
        "pr_auc":     0.7860,
        "p_at_top20": 0.9509,
        "note":       "walk-forward 2019-2024, risk_ensemble_report.json. "
                      "XGBoost(별도 모델)+Survival 구조. 현재 Survival 단일소스와 직접 비교 불가.",
    }

    return results, grid


# ══════════════════════════════════════════════════════════════
# 5. 메인
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 62)
    print("Survival Weight Experiment  v2")
    print("타깃: label_cut_1y (t+1년 배당 삭감 예측 — 올바른 타깃)")
    print("=" * 62)

    # 데이터
    print("\n[1/3] 데이터 조립 중...")
    path = os.path.join(BASE, "data", "dividend_dataset.csv")
    df_raw = pd.read_csv(path, dtype={"stock_code": str})
    df_raw["year"] = pd.to_numeric(df_raw["year"], errors="coerce")
    df_raw["label_cut_1y"] = pd.to_numeric(df_raw["label_cut_1y"], errors="coerce")
    eval_year = int(df_raw.dropna(subset=["label_cut_1y"])["year"].max())

    print(f"  평가 연도:     {eval_year} (피처) → {eval_year + 1} (삭감 예측 대상)")
    df = build_feature_table(eval_year)
    print(f"  주식 수:       {len(df)}")
    print(f"  이벤트 수:     {df['label'].sum()}")
    print(f"  이벤트 비율:   {df['label'].mean():.2%}")
    print(f"  hazard 범위:   [{df['hazard'].min():.3f}, {df['hazard'].max():.3f}]")
    print(f"  ml_status:     {df['status'].value_counts().to_dict()}")
    print()
    print("  ⚠️  누수 주의: survival_pd_v4.json은 전체 기간 데이터 기반.")
    print("      연도별 hazard 재산출 없이 사용. 결과는 방향성 참고용.")

    if df["label"].sum() == 0:
        print(f"\n[ERROR] {eval_year}년 label_cut_1y 이벤트 없음.")
        print("  → 전년도로 변경하거나 dividend_dataset.csv 재생성 필요")
        import sys; sys.exit(1)

    # 전략 평가
    print("\n[2/3] 5가지 전략 평가 중...")
    results, grid = run_strategies(df)

    print("\n결과 요약:")
    print(f"  {'전략':45s} {'ROC':>7} {'PR-AUC':>7} {'P@20':>7}")
    print("  " + "-" * 70)
    for k, v in results.items():
        if "roc_auc" in v:
            print(f"  {v.get('method','')[:45]:45s} "
                  f"{v['roc_auc']:>7.4f} {v.get('pr_auc', 0):>7.4f} "
                  f"{v.get('p_at_top20', 0):>7.4f}")

    best_key = max(
        [k for k in results if "REF" not in k and results[k].get("roc_auc")],
        key=lambda k: results[k].get("roc_auc", 0)
    )
    roc_A = results.get("A_hazard_only", {}).get("roc_auc", 0)
    roc_C = results.get("C_70_30", {}).get("roc_auc", 0)
    diff = round(roc_C - roc_A, 4)
    print(f"\n  hazard 단독 vs 현재 70:30: {diff:+.4f}")

    # 저장
    print("\n[3/3] 결과 저장 중...")
    out = {
        "experiment":   "Survival 단일소스 가중치 재검증  v2",
        "version":      2,
        "label":        "label_cut_1y",
        "label_meaning": f"{eval_year}년 피처 → {eval_year + 1}년 배당 삭감 예측",
        "eval_year":    eval_year,
        "n_samples":    int(len(df)),
        "n_events":     int(df["label"].sum()),
        "event_rate":   round(float(df["label"].mean()), 4),
        "known_limitations": [
            "단면 평가 (cross-sectional) — walk-forward 아님",
            "survival_pd_v4.json은 전체 기간 데이터 기반 → 누수 가능성",
            "n_samples 적을 경우 ROC 추정 불안정",
            "최적 가중치는 동일 데이터에서 선택 → 과적합 가능성",
        ],
        "comparison":   results,
        "weight_sensitivity_curve": grid,
        "conclusion": {
            "best_in_experiment": best_key,
            "roc_70_30_vs_hazard_only": diff,
            "interpretation": (
                "양수: 70:30이 hazard 단독보다 높음. "
                "음수: ml_status 70% 가중이 성능 저하. "
                "walk-forward 재검증 전까지 가중치 변경 보류."
            ),
        },
    }

    out_path = os.path.join(BASE, "results", "survival_weight_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"  저장: {out_path}")
    print("\n실험 완료.")
    print(f"  eval_year={eval_year}, label=label_cut_1y")
    print("  결과를 docs/recommendation_criteria.md Section 9-2에 반영하세요.")
    print("  walk-forward 재검증 전까지 가중치 변경 보류.")


if __name__ == "__main__":
    main()

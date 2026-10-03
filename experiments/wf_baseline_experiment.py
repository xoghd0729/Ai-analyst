"""
experiments/wf_baseline_experiment.py

Walk-forward 기준 실험 — label_mc_raw_1y 타깃

목적:
  기존 GroupKFold + 전역 percentile 정규화 없이, 시간 순서가 보장된 상태에서
  배당 심각 삭감(dps_yoy_pct(t+1) < -30%)을 예측할 수 있는지 확인한다.

  이 실험은 기존 TabPFN Survival 모델의 성능을 검증하는 것이 아니다.
  HistGradientBoostingClassifier 기반의 별도 기준 모델(baseline)이며,
  "동일 피처 구조 + 시간 순서 보장"만으로 얼마나 예측 가능한지 확인하는 것이다.

타깃:
  label_mc_raw_1y(t) = dps_yoy_pct(t+1) < -30%
    - 회복 조건 없음 (label_meaningful_1y와 달리 t+2 정보 사용 안 함)
    - 이벤트율: ~6.9%, 유효 2,117행, 양성 146건

실행:
  cd ~/ai-analyst
  python experiments/wf_baseline_experiment.py

결과:
  results/wf_baseline_report.json
  콘솔에 연도별 fold 결과 + OOS 요약 출력

주의:
  - 70:30 가중치는 이 실험 결과와 무관하게 유지
  - ROC-AUC가 높아도 기존 Survival 모델의 성능으로 해석하지 않는다
  - 이벤트 수가 적은 fold (n_pos < 5)는 ROC-AUC 신뢰도 낮음 → 주의 표시
"""

from __future__ import annotations

import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

# ── 경로 설정 ──────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from utils.walk_forward_validator import TRAIN_FEATURES, walk_forward_validate
from utils.survival_wf_adapter import SurvivalWalkForwardAdapter

warnings.filterwarnings("ignore")

CSV_PATH     = os.path.join(BASE, "data", "dividend_dataset.csv")
RESULT_PATH  = os.path.join(BASE, "results", "wf_baseline_report.json")
TARGET       = "label_mc_raw_1y"


# ─────────────────────────────────────────────────────────────
# 1. 데이터 로드 + label_mc_raw_1y 동적 생성
#    (build_dataset.py 재실행 없이 기존 CSV에서 직접 계산)
# ─────────────────────────────────────────────────────────────

def load_and_prepare(csv_path: str) -> pd.DataFrame:
    """
    기존 dividend_dataset.csv를 로드하고 label_mc_raw_1y를 동적 생성.
    DART API 없이 실행 가능.
    """
    df = pd.read_csv(csv_path, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].str.zfill(6)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df["dps_yoy_pct"] = pd.to_numeric(df["dps_yoy_pct"], errors="coerce")
    df = df.sort_values(["stock_code", "year"]).reset_index(drop=True)

    if TARGET in df.columns:
        print(f"[데이터] {TARGET} 컬럼 이미 존재 — 재사용")
    else:
        print(f"[데이터] {TARGET} 동적 생성 중...")
        _yoy_lookup = df.set_index(["stock_code", "year"])["dps_yoy_pct"]

        def _get_mc_raw_next(row):
            try:
                v = float(_yoy_lookup.loc[(row["stock_code"], int(row["year"]) + 1)])
                return 1.0 if v < -30 else 0.0
            except (KeyError, ValueError, TypeError):
                return float("nan")

        df[TARGET] = df.apply(_get_mc_raw_next, axis=1)

    valid = df[TARGET].notna()
    n_pos = int(df.loc[valid, TARGET].sum())
    print(f"[데이터] 유효 {valid.sum()}행, 양성 {n_pos}건 ({100*n_pos/valid.sum():.1f}%), "
          f"결측 {(~valid).sum()}건")
    return df


# ─────────────────────────────────────────────────────────────
# 2. 피처 컬럼 필터링 (TRAIN_FEATURES 중 CSV에 실제 있는 것만)
# ─────────────────────────────────────────────────────────────

def get_available_features(df: pd.DataFrame) -> list[str]:
    available = [f for f in TRAIN_FEATURES if f in df.columns]
    missing   = [f for f in TRAIN_FEATURES if f not in df.columns]
    print(f"[피처] TRAIN_FEATURES 중 사용 가능: {len(available)}개")
    if missing:
        print(f"[피처] CSV에 없는 피처 (제외): {missing}")
    return available


# ─────────────────────────────────────────────────────────────
# 3. walk-forward 실험 실행
# ─────────────────────────────────────────────────────────────

def run_experiment(df: pd.DataFrame, features: list[str]) -> dict:
    print(f"\n[실험] walk_forward_validate 실행 (target={TARGET})")
    print(f"[실험] 어댑터: HistGradientBoostingClassifier (TabPFN 아님)")
    print(f"[실험] 주의: 결과를 기존 TabPFN Survival 모델의 성능으로 해석하지 않는다\n")

    result = walk_forward_validate(
        df,
        model_class=SurvivalWalkForwardAdapter,
        model_params={
            "n_estimators": 300,
            "learning_rate": 0.05,
            "max_depth": 4,
            "use_percentile_transform": True,
        },
        target=TARGET,
        features=features,
        verbose=True,
    )
    return result


# ─────────────────────────────────────────────────────────────
# 4. 결과 출력
# ─────────────────────────────────────────────────────────────

def print_results(result: dict) -> None:
    print("\n" + "=" * 60)
    print("Walk-forward 기준 실험 결과 (label_mc_raw_1y)")
    print("=" * 60)

    print("\n[연도별 fold 결과]")
    header = f"{'test_year':>10} {'n_train':>8} {'n_test':>7} {'n_pos':>6} {'evt_rate':>9} "
    header += f"{'roc_auc':>9} {'pr_auc':>8} {'p@20':>7} {'note':>15}"
    print(header)
    print("-" * len(header))

    for fold in result["folds"]:
        yr     = fold.get("test_year", "-")
        n_tr   = fold.get("n_train", "-")
        n_te   = fold.get("n_test", "-")
        n_pos  = fold.get("n_pos_test", "-")
        roc    = fold.get("roc_auc")
        pr     = fold.get("pr_auc")
        p20    = fold.get("precision_at_20", None)
        warn   = fold.get("_warning", "")

        evt_rate = f"{n_pos}/{n_te}" if n_pos != "-" and n_te != "-" else "-"
        roc_str  = f"{roc:.4f}" if roc is not None else "  N/A  "
        pr_str   = f"{pr:.4f}"  if pr  is not None else "  N/A  "
        p20_str  = f"{p20:.3f}" if p20 is not None else " N/A "
        note     = "⚠️ 이벤트 부족" if (isinstance(n_pos, int) and n_pos < 5) else ""
        note     = note or ("⚠️ " + warn[:10] if warn else "")

        print(f"{yr:>10} {str(n_tr):>8} {str(n_te):>7} {str(n_pos):>6} {evt_rate:>9} "
              f"{roc_str:>9} {pr_str:>8} {p20_str:>7} {note:>15}")

    summary = result.get("oos_summary", {})
    print("\n[OOS 전체 요약]")
    for k in ("roc_auc_mean", "pr_auc_mean", "brier_score_mean"):
        v = summary.get(k)
        print(f"  {k:25s}: {v:.4f}" if v is not None else f"  {k:25s}: N/A")
    print(f"  {'유효 fold 수':25s}: {summary.get('n_folds', '-')}")

    print("\n[해석 주의사항]")
    print("  - 이 결과는 HistGBM 기준 모델의 성능이며 TabPFN Survival 모델 성능이 아님")
    print("  - 이벤트율 ~6.9% (146/2117) — 불균형 데이터, PR-AUC 위주 해석 권장")
    print("  - P@20: test 표본 상위 20% 중 실제 이벤트 비율 (이벤트율 대비 기준 확인 필요)")
    print("  - ROC-AUC > 0.5이면 랜덤 이상의 구별력 존재")


# ─────────────────────────────────────────────────────────────
# 5. JSON 저장
# ─────────────────────────────────────────────────────────────

def save_results(result: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)

    # numpy 타입 직렬화
    def _default(o):
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, pd.DataFrame):
            return o.to_dict(orient="records")
        raise TypeError(f"직렬화 불가: {type(o)}")

    report = {
        "experiment": "wf_baseline",
        "target": TARGET,
        "model": "HistGradientBoostingClassifier (SurvivalWalkForwardAdapter)",
        "note": "기존 TabPFN Survival 모델과 무관한 별도 기준 실험. 70:30 가중치 변경 없음.",
        "oos_summary": result.get("oos_summary", {}),
        "folds": [
            {k: v for k, v in fold.items() if k != "oos_df"}
            for fold in result.get("folds", [])
        ],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_default)
    print(f"\n[저장] {path}")


# ─────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Walk-forward 기준 실험 시작")
    print(f"타깃: {TARGET}")
    print("=" * 60 + "\n")

    df       = load_and_prepare(CSV_PATH)
    features = get_available_features(df)
    result   = run_experiment(df, features)

    print_results(result)
    save_results(result, RESULT_PATH)

    print("\n실험 완료.")
    print(f"결과 파일: results/wf_baseline_report.json")
    print("다음 단계: 결과 수치를 확인 후 Risk Engine 검토 진행")

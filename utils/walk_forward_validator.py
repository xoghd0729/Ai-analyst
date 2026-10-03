"""
Walk-Forward ML Validation Framework
=====================================

■ 목적
  ML 모델(배당 삭감 예측 등)의 out-of-time 성능을 시간순으로 검증한다.
  random split과 달리 미래 데이터가 학습에 절대 들어가지 않도록 보장한다.

■ 데이터 계약 (look-ahead bias 방지)
  - 관측시점(t): 각 행의 year 값
  - 피처: year=t의 재무 데이터 (DART 공시는 t+1년 4월 공개 — 현실에서 t+0.5 관측 가능)
  - 타깃 label_cut_1y: year=t+1의 DPS 삭감 여부
  - 타깃 label_cut_3y: year=t+1~t+3 중 삭감 여부
  - 타깃 label_cut_5y: year=t+1~t+5 중 삭감 여부

■ Fold 구조 (Expanding Window)
  Train 2015~2019 | Test 2020
  Train 2015~2020 | Test 2021
  Train 2015~2021 | Test 2022
  ...

■ 시간 기반 Leakage Assertion
  assert train_years.max() < test_years.min()   # 시간 overlap 없음
  assert feature_year == observation_year        # 피처가 미래 년도 값 아님
  assert label references observation_year + N  # 라벨이 미래 이벤트 참조

■ 평가 지표
  ROC-AUC / PR-AUC / Brier Score / Precision / Recall / F1 / C-index(생존 모델용)

■ 사용 예시
  from utils.walk_forward_validator import walk_forward_validate, TRAIN_FEATURES

  results = walk_forward_validate(
      df,
      model_class=RandomForestClassifier,
      model_params={"n_estimators": 100, "random_state": 42},
      target="label_cut_1y",
  )
  print(results["oos_summary"])
"""

from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from typing import Any, Type

# ─────────────────────────────────────────────────────────────
# 학습 피처 목록 (build_dataset.py TRAIN_FEATURES와 동기화 유지)
# ─────────────────────────────────────────────────────────────
TRAIN_FEATURES = [
    "revenue", "op_income", "net_income",
    "operating_cf", "capex", "fcf",
    "dividends_paid", "payout_ratio", "dividend_coverage",
    "total_liab", "total_equity", "debt_ratio",
    "interest_expense", "interest_coverage",
    "revenue_yoy_pct",
    "dps_yoy_pct",    # t-1→t 변화율 (관측 가능, leakage 아님)
]

VALID_TARGETS = [
    "label_cut_1y",
    "label_cut_3y",
    "label_cut_5y",
    "label_meaningful_1y",
    "label_mc_raw_1y",   # STEP 4 기준 실험 타깃: 회복 조건 없음, t+2 누수 없음
]

# 타깃별 미래 horizon (label_cut_Ny → N년 후 이벤트)
TARGET_HORIZON = {
    "label_cut_1y":        1,
    "label_cut_3y":        3,
    "label_cut_5y":        5,
    "label_meaningful_1y": 1,  # 기능 B: t+1년 심각한 삭감 위험 (meaningful_cut 기준, t+2 누수 있음)
    "label_mc_raw_1y":     1,  # STEP 4 기준 실험: dps_yoy_pct(t+1) < -30%, t+2 누수 없음
}


# ─────────────────────────────────────────────────────────────
# 시간 기반 Leakage Assertion
# ─────────────────────────────────────────────────────────────

def assert_no_temporal_leakage(
    df: pd.DataFrame,
    feature_cols: list[str],
    label_col: str,
    year_col: str = "year",
) -> None:
    """
    시간 기반 leakage 3가지 조건을 assert한다.

    1. 피처 컬럼이 미래 연도 데이터를 포함하지 않는지 확인
       → year 컬럼 기준 동일 행(t)의 값만 써야 함.
       → shift(-1) 파생 컬럼이 피처에 포함되었는지 이름 패턴으로 경고.

    2. label_col 이름이 VALID_TARGETS 중 하나인지 확인
       → label_cut_Ny는 t+N 미래 이벤트를 참조함을 명시.

    3. df 내 year 컬럼이 단조 증가(정렬 필요)하는지 확인.
    """
    errors = []

    # ── (1) 피처에 미래 참조 컬럼 패턴이 들어있는지 이름 검사 ──
    # DART 데이터 구조상 _next, _t1, _future 등이 포함되면 leakage 의심
    leakage_patterns = ["_next", "_t1", "_future", "_forward", "cut_n"]
    for feat in feature_cols:
        for pat in leakage_patterns:
            if pat in feat.lower():
                errors.append(
                    f"피처 '{feat}'에 미래 참조 패턴 '{pat}' 포함 → leakage 의심"
                )

    # ── (2) 타깃이 미래 이벤트를 참조하는 컬럼인지 확인 ──
    if label_col not in VALID_TARGETS and label_col != "label3":
        errors.append(
            f"타깃 '{label_col}'은 VALID_TARGETS({VALID_TARGETS})에 없음. "
            "레거시 label3 또는 직접 정의된 타깃은 forward-looking 여부 수동 확인 필요."
        )

    # ── (3) year 컬럼이 정수형이고 데이터가 존재하는지 ──
    if year_col not in df.columns:
        errors.append(f"year 컬럼 '{year_col}'이 DataFrame에 없음.")
    else:
        if df[year_col].isnull().any():
            errors.append(f"year 컬럼에 NaN 포함 — 시간 순 정렬 불가.")

    if errors:
        msg = "\n".join(f"  ❌ {e}" for e in errors)
        raise AssertionError(f"Temporal Leakage Assertion 실패:\n{msg}")


def assert_no_train_test_overlap(
    train_years: np.ndarray,
    test_years: np.ndarray,
) -> None:
    """Train 최대 연도 < Test 최소 연도 보장."""
    train_max = int(train_years.max())
    test_min  = int(test_years.min())
    assert train_max < test_min, (
        f"Train/Test 시간 overlap: train.max={train_max} >= test.min={test_min}. "
        "미래 데이터가 학습에 포함되었습니다."
    )


# ─────────────────────────────────────────────────────────────
# 평가 지표 계산
# ─────────────────────────────────────────────────────────────

def _compute_metrics(y_true: np.ndarray, y_prob: np.ndarray, y_pred: np.ndarray) -> dict:
    """ROC-AUC / PR-AUC / Brier / Precision / Recall / F1."""
    from sklearn.metrics import (
        roc_auc_score, average_precision_score, brier_score_loss,
        precision_score, recall_score, f1_score,
    )

    metrics: dict[str, Any] = {}

    n_pos = int(y_true.sum())
    n_neg = int((1 - y_true).sum())
    metrics["n_samples"] = len(y_true)
    metrics["n_positive"] = n_pos
    metrics["n_negative"] = n_neg
    metrics["positive_rate"] = round(n_pos / len(y_true), 4) if len(y_true) > 0 else 0.0

    if n_pos == 0 or n_neg == 0:
        # 단일 클래스면 AUC 계산 불가
        metrics.update({k: None for k in [
            "roc_auc", "pr_auc", "brier_score", "precision", "recall", "f1"
        ]})
        metrics["_warning"] = "단일 클래스 — AUC 계산 불가"
        return metrics

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        metrics["roc_auc"]     = round(roc_auc_score(y_true, y_prob), 4)
        metrics["pr_auc"]      = round(average_precision_score(y_true, y_prob), 4)
        metrics["brier_score"] = round(brier_score_loss(y_true, y_prob), 4)
        metrics["precision"]   = round(precision_score(y_true, y_pred, zero_division=0), 4)
        metrics["recall"]      = round(recall_score(y_true, y_pred, zero_division=0), 4)
        metrics["f1"]          = round(f1_score(y_true, y_pred, zero_division=0), 4)

    return metrics


# ─────────────────────────────────────────────────────────────
# Walk-Forward Validator
# ─────────────────────────────────────────────────────────────

def walk_forward_validate(
    df: pd.DataFrame,
    model_class: Type,
    model_params: dict | None = None,
    target: str = "label_cut_1y",
    features: list[str] | None = None,
    year_col: str = "year",
    min_train_years: int = 3,
    classification_threshold: float = 0.5,
    impute_strategy: str = "median",
    verbose: bool = True,
) -> dict:
    """
    Expanding-window walk-forward cross-validation.

    Parameters
    ----------
    df              : build_dataset.py 출력 DataFrame (year 컬럼 필수)
    model_class     : sklearn 호환 분류기 클래스 (fit / predict_proba 지원)
    model_params    : model_class(**model_params)로 인스턴스 생성
    target          : 예측 타깃 ("label_cut_1y" / "label_cut_3y" / "label_cut_5y")
    features        : 피처 리스트 (None이면 TRAIN_FEATURES 사용)
    year_col        : 연도 컬럼명
    min_train_years : 최소 학습 연도 수 (이 미만이면 fold 건너뜀)
    classification_threshold : 이진 분류 임계값
    impute_strategy : 결측 대치 전략 ("median" / "mean" / "zero")
    verbose         : fold별 성능 출력 여부

    Returns
    -------
    dict:
      folds        : list of fold result dict
      oos_summary  : 전체 OOS 집계 (mean ± std)
      oos_df       : 모든 test 예측 합산 DataFrame
    """
    if model_params is None:
        model_params = {}
    if features is None:
        features = TRAIN_FEATURES

    # ── 시간 기반 leakage assertion ──────────────────────────
    assert_no_temporal_leakage(df, features, target, year_col)

    df = df.copy()
    df[year_col] = pd.to_numeric(df[year_col], errors="coerce")
    df = df.dropna(subset=[year_col, target])
    df[target] = pd.to_numeric(df[target], errors="coerce")
    df = df.dropna(subset=[target])

    all_years  = sorted(df[year_col].unique())
    n_years    = len(all_years)

    if n_years <= min_train_years:
        raise ValueError(
            f"연도 수 {n_years}개가 min_train_years({min_train_years})보다 작거나 같음. "
            "데이터가 충분하지 않습니다."
        )

    folds        = []
    oos_records  = []

    for i in range(min_train_years, n_years):
        train_end   = all_years[i - 1]
        test_year   = all_years[i]

        train_yrs   = [y for y in all_years if y <= train_end]
        test_yrs    = [test_year]

        train_df = df[df[year_col].isin(train_yrs)].copy()
        test_df  = df[df[year_col].isin(test_yrs)].copy()

        # Assertion: 시간 overlap 없음
        assert_no_train_test_overlap(
            train_df[year_col].values,
            test_df[year_col].values,
        )

        # 피처 준비
        feat_cols = [f for f in features if f in df.columns]

        X_train = train_df[feat_cols].copy()
        y_train = train_df[target].values.astype(float)
        X_test  = test_df[feat_cols].copy()
        y_test  = test_df[target].values.astype(float)

        if len(X_train) < 5 or len(X_test) == 0:
            continue

        # 결측 대치 (학습 기준)
        if impute_strategy == "median":
            fill_vals = X_train.median()
        elif impute_strategy == "mean":
            fill_vals = X_train.mean()
        else:
            fill_vals = pd.Series(0, index=feat_cols)

        X_train = X_train.fillna(fill_vals)
        X_test  = X_test.fillna(fill_vals)

        # 학습 / 예측
        model = model_class(**model_params)
        try:
            model.fit(X_train, y_train)
            y_prob = model.predict_proba(X_test)[:, 1]
            y_pred = (y_prob >= classification_threshold).astype(int)
        except Exception as exc:
            if verbose:
                print(f"  ⚠️  Fold {test_year}: 모델 오류 — {exc}")
            continue

        metrics = _compute_metrics(y_test, y_prob, y_pred)
        fold_result = {
            "test_year":     test_year,
            "train_end":     train_end,
            "n_train":       len(X_train),
            "n_test":        len(X_test),
            **metrics,
        }
        folds.append(fold_result)

        # OOS 예측 누적
        oos_rows = test_df[[year_col]].copy()
        if "stock_code" in test_df.columns:
            oos_rows["stock_code"] = test_df["stock_code"].values
        oos_rows["y_true"] = y_test
        oos_rows["y_prob"] = y_prob
        oos_rows["y_pred"] = y_pred
        oos_records.append(oos_rows)

        if verbose:
            roc = metrics.get("roc_auc", "N/A")
            pr  = metrics.get("pr_auc",  "N/A")
            bs  = metrics.get("brier_score", "N/A")
            print(
                f"  Fold {test_year:4d} | "
                f"train={len(X_train):4d} test={len(X_test):3d} | "
                f"ROC-AUC={roc}  PR-AUC={pr}  Brier={bs}"
            )

    if not folds:
        return {"folds": [], "oos_summary": {}, "oos_df": pd.DataFrame()}

    # ── OOS 전체 집계 ──────────────────────────────────────────
    oos_df      = pd.concat(oos_records, ignore_index=True) if oos_records else pd.DataFrame()
    folds_df    = pd.DataFrame(folds)
    metric_cols = ["roc_auc", "pr_auc", "brier_score", "precision", "recall", "f1"]

    oos_summary: dict[str, Any] = {"target": target, "n_folds": len(folds)}
    for col in metric_cols:
        vals = folds_df[col].dropna().astype(float)
        if len(vals) == 0:
            oos_summary[f"{col}_mean"] = None
            oos_summary[f"{col}_std"]  = None
        else:
            oos_summary[f"{col}_mean"] = round(float(vals.mean()), 4)
            oos_summary[f"{col}_std"]  = round(float(vals.std()), 4)

    # 전체 OOS 예측 합산 지표
    if not oos_df.empty and oos_df["y_true"].nunique() > 1:
        from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            oos_summary["oos_roc_auc"]     = round(roc_auc_score(oos_df["y_true"], oos_df["y_prob"]), 4)
            oos_summary["oos_pr_auc"]      = round(average_precision_score(oos_df["y_true"], oos_df["y_prob"]), 4)
            oos_summary["oos_brier_score"] = round(brier_score_loss(oos_df["y_true"], oos_df["y_prob"]), 4)

    if verbose:
        print(f"\n  ── OOS 전체 합산 ({target}) ──")
        print(f"  ROC-AUC : {oos_summary.get('oos_roc_auc', 'N/A')}")
        print(f"  PR-AUC  : {oos_summary.get('oos_pr_auc',  'N/A')}")
        print(f"  Brier   : {oos_summary.get('oos_brier_score', 'N/A')}")
        print(f"  fold 평균 ROC-AUC: {oos_summary['roc_auc_mean']} ± {oos_summary['roc_auc_std']}")

    return {
        "folds":       folds,
        "oos_summary": oos_summary,
        "oos_df":      oos_df,
    }




# ─────────────────────────────────────────────────────────────
# 시간 기반 Leakage 검사 (DataFrame 입력 버전)
# ─────────────────────────────────────────────────────────────

def leakage_check_df(
    df: pd.DataFrame,
    feature_cols: list[str],
    year_col: str = "year",
) -> dict:
    """
    DataFrame 기준 시간 방향 leakage 검사.
    baseline_benchmark.py 등 외부 스크립트에서 직접 호출 가능.

    반환: {"issues": [...], "warnings": [...]}
    """
    report: dict = {"issues": [], "warnings": []}

    # (1) 피처에 미래 참조 패턴 이름 검사
    leakage_patterns = ["_next", "_t1", "_future", "_forward", "cut_n"]
    for feat in feature_cols:
        for pat in leakage_patterns:
            if pat in feat.lower() and feat in df.columns:
                msg = f"피처 '{feat}'에 미래 참조 패턴 '{pat}' 포함"
                report["issues"].append(msg)

    # (2) VALID_TARGETS가 forward-looking인지 확인
    for tgt in VALID_TARGETS:
        if tgt in df.columns:
            report["warnings"].append(f"{tgt}: forward-looking 타깃 (OK)")

    # (3) label3 BROKEN leakage 경고
    if "label3" in df.columns and "dps_yoy_pct" in df.columns:
        broken = df[df["label3"] == 2]
        if not broken.empty:
            x2 = pd.to_numeric(broken["dps_yoy_pct"], errors="coerce").dropna()
            if len(x2) >= 5:
                neg_rate = float((x2 < 0).mean())
                if neg_rate > 0.9:
                    msg = (f"label3=BROKEN 행 dps_yoy_pct<0 비율: {neg_rate:.1%} "
                           "— 신규 label_cut_Ny 타깃 사용 권장")
                    report["warnings"].append(msg)

    # (4) 연도 단조성
    if "stock_code" in df.columns and year_col in df.columns:
        bad_codes = []
        for code, grp in df.groupby("stock_code"):
            years = grp[year_col].dropna().tolist()
            if years != sorted(years):
                bad_codes.append(code)
        if bad_codes:
            report["issues"].append(f"year 정렬 이상 종목: {bad_codes[:5]}")

    if report["issues"]:
        print(f"  ⚠️  Leakage 이슈 {len(report['issues'])}건: {report['issues']}")
    else:
        print("  ✅ 시간 기반 leakage 이슈 없음")

    return report

# ─────────────────────────────────────────────────────────────
# 편의 함수: 여러 타깃 동시 비교
# ─────────────────────────────────────────────────────────────

def compare_targets(
    df: pd.DataFrame,
    model_class: Type,
    model_params: dict | None = None,
    targets: list[str] | None = None,
    **kwargs,
) -> dict[str, dict]:
    """
    label_cut_1y / label_cut_3y / label_cut_5y를 동시에 검증하고
    비교 요약을 반환한다.
    """
    if targets is None:
        targets = VALID_TARGETS
    results = {}
    for tgt in targets:
        if tgt not in df.columns:
            print(f"  ⚠️  {tgt} 컬럼 없음, 건너뜀")
            continue
        print(f"\n{'='*54}\n  Walk-Forward: {tgt}\n{'='*54}")
        results[tgt] = walk_forward_validate(
            df, model_class, model_params, target=tgt, **kwargs
        )
    return results

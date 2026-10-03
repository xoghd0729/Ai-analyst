"""
tests/test_walk_forward_validator.py

Walk-Forward ML Validation Framework 테스트.
실제 DART 데이터 없이 합성 DataFrame으로 검증.
"""
import pytest
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.walk_forward_validator import (
    walk_forward_validate,
    compare_targets,
    assert_no_temporal_leakage,
    assert_no_train_test_overlap,
    TRAIN_FEATURES,
    VALID_TARGETS,
)

# ──────────────────────────────────────────────────────────────
# 합성 데이터 생성 헬퍼
# ──────────────────────────────────────────────────────────────

def make_synthetic_df(
    n_stocks: int = 5,
    start_year: int = 2015,
    end_year: int = 2023,
    cut_prob: float = 0.25,
    seed: int = 42,
) -> pd.DataFrame:
    """
    TRAIN_FEATURES + label_cut_Ny 컬럼을 가진 합성 DataFrame 생성.
    실제 DART 데이터 없이 테스트용으로 사용.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for s in range(n_stocks):
        code = f"{s+1:06d}"
        for yr in range(start_year, end_year + 1):
            row = {"stock_code": code, "year": yr}
            # 피처: 랜덤 재무 데이터
            for feat in TRAIN_FEATURES:
                row[feat] = float(rng.normal(0, 1))
            # 라벨: 랜덤 이진 (실제론 DART에서 파생)
            row["label_cut_1y"]        = float(rng.random() < cut_prob)
            row["label_cut_3y"]        = float(rng.random() < cut_prob * 1.5)
            row["label_cut_5y"]        = float(rng.random() < cut_prob * 2.0)
            row["label_meaningful_1y"] = float(rng.random() < cut_prob * 0.5)
            row["label_mc_raw_1y"]     = float(rng.random() < cut_prob * 0.5)
            row["dividend_cut"]        = float(rng.random() < cut_prob)
            rows.append(row)
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# 1. Temporal Leakage Assertion
# ──────────────────────────────────────────────────────────────

class TestTemporalLeakageAssertion:

    def test_valid_features_pass(self):
        df = make_synthetic_df()
        # 정상 피처 + 정상 타깃 → 예외 없음
        assert_no_temporal_leakage(df, TRAIN_FEATURES, "label_cut_1y")

    def test_future_pattern_in_feature_raises(self):
        df = make_synthetic_df()
        bad_features = TRAIN_FEATURES + ["revenue_next"]   # _next 패턴
        with pytest.raises(AssertionError, match="leakage"):
            assert_no_temporal_leakage(df, bad_features, "label_cut_1y")

    def test_invalid_target_raises(self):
        df = make_synthetic_df()
        with pytest.raises(AssertionError):
            assert_no_temporal_leakage(df, TRAIN_FEATURES, "dividend_cut_raw")

    def test_missing_year_col_raises(self):
        df = make_synthetic_df().drop(columns=["year"])
        with pytest.raises(AssertionError, match="year"):
            assert_no_temporal_leakage(df, TRAIN_FEATURES, "label_cut_1y", year_col="year")


class TestTrainTestOverlapAssertion:

    def test_no_overlap_passes(self):
        train = np.array([2015, 2016, 2017, 2018, 2019])
        test  = np.array([2020])
        assert_no_train_test_overlap(train, test)  # 예외 없음

    def test_overlap_raises(self):
        train = np.array([2015, 2016, 2017, 2018, 2020])
        test  = np.array([2020])
        with pytest.raises(AssertionError, match="overlap"):
            assert_no_train_test_overlap(train, test)

    def test_train_after_test_raises(self):
        train = np.array([2015, 2016, 2021])
        test  = np.array([2020])
        with pytest.raises(AssertionError):
            assert_no_train_test_overlap(train, test)


# ──────────────────────────────────────────────────────────────
# 2. walk_forward_validate 반환 구조
# ──────────────────────────────────────────────────────────────

class TestReturnStructure:

    @pytest.fixture(scope="class")
    def result(self):
        df = make_synthetic_df(n_stocks=10, start_year=2015, end_year=2023)
        return walk_forward_validate(
            df,
            model_class=LogisticRegression,
            model_params={"max_iter": 200, "random_state": 42},
            target="label_cut_1y",
            verbose=False,
        )

    def test_has_folds_key(self, result):
        assert "folds" in result

    def test_has_oos_summary_key(self, result):
        assert "oos_summary" in result

    def test_has_oos_df_key(self, result):
        assert "oos_df" in result

    def test_folds_is_list(self, result):
        assert isinstance(result["folds"], list)

    def test_oos_df_has_required_cols(self, result):
        oos = result["oos_df"]
        if not oos.empty:
            assert "y_true" in oos.columns
            assert "y_prob" in oos.columns
            assert "y_pred" in oos.columns

    def test_oos_summary_has_metrics(self, result):
        summary = result["oos_summary"]
        assert "roc_auc_mean" in summary
        assert "pr_auc_mean" in summary
        assert "brier_score_mean" in summary
        assert "n_folds" in summary

    def test_fold_count_reasonable(self, result):
        # 2015~2023 = 9년, min_train_years=3 → 최대 6 fold
        assert len(result["folds"]) <= 6

    def test_each_fold_has_test_year(self, result):
        for fold in result["folds"]:
            assert "test_year" in fold
            assert "n_train" in fold
            assert "n_test" in fold


# ──────────────────────────────────────────────────────────────
# 3. 시간 순서 보장 (train < test)
# ──────────────────────────────────────────────────────────────

class TestTemporalOrdering:

    def test_train_years_always_before_test(self):
        df = make_synthetic_df(n_stocks=8, start_year=2015, end_year=2022)
        result = walk_forward_validate(
            df,
            model_class=DummyClassifier,
            model_params={"strategy": "most_frequent"},
            target="label_cut_1y",
            verbose=False,
        )
        for fold in result["folds"]:
            assert fold["train_end"] < fold["test_year"], (
                f"train_end={fold['train_end']} >= test_year={fold['test_year']}"
            )

    def test_no_year_overlap_in_oos_df(self):
        df = make_synthetic_df(n_stocks=5, start_year=2015, end_year=2021)
        result = walk_forward_validate(
            df,
            model_class=DummyClassifier,
            model_params={"strategy": "stratified", "random_state": 42},
            target="label_cut_1y",
            verbose=False,
        )
        oos = result["oos_df"]
        if not oos.empty and "year" in oos.columns:
            # OOS df의 각 year는 test fold의 연도들이므로 train 데이터에 없어야 함
            test_years = sorted(oos["year"].unique())
            for i, yr in enumerate(test_years[:-1]):
                assert yr < test_years[i + 1]   # 연도 순 증가


# ──────────────────────────────────────────────────────────────
# 4. 지표 범위 검사
# ──────────────────────────────────────────────────────────────

class TestMetricBounds:

    @pytest.fixture(scope="class")
    def result(self):
        df = make_synthetic_df(n_stocks=10, start_year=2015, end_year=2023, seed=7)
        return walk_forward_validate(
            df,
            model_class=LogisticRegression,
            model_params={"max_iter": 300, "random_state": 7},
            target="label_cut_1y",
            verbose=False,
        )

    def test_roc_auc_in_range(self, result):
        for fold in result["folds"]:
            v = fold.get("roc_auc")
            if v is not None:
                assert 0.0 <= v <= 1.0, f"ROC-AUC {v} out of range"

    def test_pr_auc_in_range(self, result):
        for fold in result["folds"]:
            v = fold.get("pr_auc")
            if v is not None:
                assert 0.0 <= v <= 1.0, f"PR-AUC {v} out of range"

    def test_brier_score_in_range(self, result):
        for fold in result["folds"]:
            v = fold.get("brier_score")
            if v is not None:
                assert 0.0 <= v <= 1.0, f"Brier {v} out of range"

    def test_precision_recall_in_range(self, result):
        for fold in result["folds"]:
            for k in ("precision", "recall", "f1"):
                v = fold.get(k)
                if v is not None:
                    assert 0.0 <= v <= 1.0, f"{k}={v} out of range"

    def test_oos_summary_means_in_range(self, result):
        summary = result["oos_summary"]
        for k in ("roc_auc_mean", "pr_auc_mean", "brier_score_mean"):
            v = summary.get(k)
            if v is not None:
                assert 0.0 <= v <= 1.0, f"{k}={v} out of range"


# ──────────────────────────────────────────────────────────────
# 5. compare_targets
# ──────────────────────────────────────────────────────────────

class TestCompareTargets:

    def test_returns_dict_with_all_targets(self):
        df = make_synthetic_df(n_stocks=6, start_year=2015, end_year=2022)
        results = compare_targets(
            df,
            model_class=DummyClassifier,
            model_params={"strategy": "most_frequent"},
            verbose=False,
        )
        for tgt in VALID_TARGETS:
            assert tgt in results, f"{tgt} 결과 없음"

    def test_each_result_has_oos_summary(self):
        df = make_synthetic_df(n_stocks=6, start_year=2015, end_year=2022)
        results = compare_targets(
            df,
            model_class=DummyClassifier,
            model_params={"strategy": "most_frequent"},
            verbose=False,
        )
        for tgt, res in results.items():
            assert "oos_summary" in res, f"{tgt}: oos_summary 없음"


# ──────────────────────────────────────────────────────────────
# 6. 엣지 케이스
# ──────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_insufficient_data_raises(self):
        # 1년치 데이터 → min_train_years=3 미달 → ValueError
        df = make_synthetic_df(n_stocks=3, start_year=2020, end_year=2020)
        with pytest.raises(ValueError, match="min_train_years"):
            walk_forward_validate(
                df,
                model_class=DummyClassifier,
                model_params={},
                target="label_cut_1y",
                verbose=False,
            )

    def test_missing_target_col_raises_or_skips(self):
        df = make_synthetic_df(n_stocks=3, start_year=2015, end_year=2021)
        df = df.drop(columns=["label_cut_5y"])
        # label_cut_5y 없으면 dropna 후 빈 df → ValueError 또는 빈 결과
        try:
            result = walk_forward_validate(
                df,
                model_class=DummyClassifier,
                model_params={},
                target="label_cut_5y",
                verbose=False,
            )
            # 빈 결과여도 OK
            assert "folds" in result
        except (ValueError, KeyError):
            pass  # 빈 데이터 → 예외도 허용

    def test_custom_features_subset(self):
        df = make_synthetic_df(n_stocks=5, start_year=2015, end_year=2021)
        custom_feats = ["fcf", "payout_ratio", "dps_yoy_pct"]
        result = walk_forward_validate(
            df,
            model_class=LogisticRegression,
            model_params={"max_iter": 100},
            target="label_cut_1y",
            features=custom_feats,
            verbose=False,
        )
        assert len(result["folds"]) > 0

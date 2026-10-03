"""
tests/test_survival_wf_adapter.py

SurvivalWalkForwardAdapter 단위 테스트.
실제 DART 데이터 없이 합성 데이터로 검증.

실행:
    pytest tests/test_survival_wf_adapter.py -v
"""
import pytest
import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.survival_wf_adapter import SurvivalWalkForwardAdapter


# ──────────────────────────────────────────────────────────────
# 헬퍼
# ──────────────────────────────────────────────────────────────

def make_Xy(n=200, n_features=10, pos_rate=0.15, seed=42):
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, (n, n_features)).astype(np.float32)
    y = (rng.random(n) < pos_rate).astype(int)
    return X, y


# ──────────────────────────────────────────────────────────────
# 1. 인터페이스 호환성
# ──────────────────────────────────────────────────────────────

class TestInterface:

    def test_fit_returns_self(self):
        X, y = make_Xy()
        adapter = SurvivalWalkForwardAdapter()
        ret = adapter.fit(X, y)
        assert ret is adapter

    def test_classes_set_after_fit(self):
        X, y = make_Xy()
        adapter = SurvivalWalkForwardAdapter()
        adapter.fit(X, y)
        assert hasattr(adapter, "classes_")
        assert list(adapter.classes_) == [0, 1]

    def test_predict_proba_shape(self):
        X_tr, y_tr = make_Xy(n=200)
        X_te, _    = make_Xy(n=50, seed=99)
        adapter = SurvivalWalkForwardAdapter()
        adapter.fit(X_tr, y_tr)
        proba = adapter.predict_proba(X_te)
        assert proba.shape == (50, 2)

    def test_predict_proba_rows_sum_to_one(self):
        X_tr, y_tr = make_Xy(n=200)
        X_te, _    = make_Xy(n=30, seed=77)
        adapter = SurvivalWalkForwardAdapter()
        adapter.fit(X_tr, y_tr)
        proba = adapter.predict_proba(X_te)
        row_sums = proba.sum(axis=1)
        np.testing.assert_allclose(row_sums, 1.0, atol=1e-6)

    def test_predict_shape(self):
        X_tr, y_tr = make_Xy()
        X_te, _    = make_Xy(n=20, seed=55)
        adapter = SurvivalWalkForwardAdapter()
        adapter.fit(X_tr, y_tr)
        pred = adapter.predict(X_te)
        assert pred.shape == (20,)
        assert set(pred).issubset({0, 1})

    def test_predict_proba_col1_in_zero_one(self):
        X_tr, y_tr = make_Xy(n=300)
        X_te, _    = make_Xy(n=50, seed=13)
        adapter = SurvivalWalkForwardAdapter()
        adapter.fit(X_tr, y_tr)
        proba = adapter.predict_proba(X_te)
        assert (proba[:, 1] >= 0).all() and (proba[:, 1] <= 1).all()


# ──────────────────────────────────────────────────────────────
# 2. Percentile 변환 동작 검증
# ──────────────────────────────────────────────────────────────

class TestPercentileTransform:

    def test_pct_transform_on_by_default(self):
        adapter = SurvivalWalkForwardAdapter()
        assert adapter.use_percentile_transform is True

    def test_sorted_train_scores_stored_after_fit(self):
        X, y = make_Xy(n=100)
        adapter = SurvivalWalkForwardAdapter(use_percentile_transform=True)
        adapter.fit(X, y)
        assert adapter._sorted_train_scores is not None
        assert adapter._n_train == 100

    def test_no_pct_transform_gives_raw_probs(self):
        X_tr, y_tr = make_Xy(n=200)
        X_te, _    = make_Xy(n=50, seed=7)
        adapter_pct = SurvivalWalkForwardAdapter(use_percentile_transform=True)
        adapter_raw = SurvivalWalkForwardAdapter(use_percentile_transform=False)
        adapter_pct.fit(X_tr, y_tr)
        adapter_raw.fit(X_tr, y_tr)
        proba_pct = adapter_pct.predict_proba(X_te)[:, 1]
        proba_raw = adapter_raw.predict_proba(X_te)[:, 1]
        # 두 결과가 동일하지 않아야 함 (percentile 변환 효과)
        assert not np.allclose(proba_pct, proba_raw)

    def test_pct_probs_uniformly_distributed(self):
        """
        train 샘플에 대해 percentile 변환 적용 시 분포가 균등해야 한다.
        (train 스코어를 train 기준으로 변환 → 완전 균등 분포)
        """
        X_tr, y_tr = make_Xy(n=500, pos_rate=0.2, seed=1)
        adapter = SurvivalWalkForwardAdapter(use_percentile_transform=True)
        adapter.fit(X_tr, y_tr)
        proba = adapter.predict_proba(X_tr)[:, 1]
        # 균등 분포 확인: 분산이 약 1/12 ≈ 0.083 (±0.03 허용)
        assert abs(proba.var() - 1 / 12) < 0.03, (
            f"percentile 변환 후 분산={proba.var():.4f}, 기대값≈{1/12:.4f}"
        )

    def test_sorted_train_scores_is_monotone(self):
        X, y = make_Xy(n=150)
        adapter = SurvivalWalkForwardAdapter()
        adapter.fit(X, y)
        scores = adapter._sorted_train_scores
        assert (np.diff(scores) >= 0).all(), "sorted_train_scores 가 단조 증가여야 함"


# ──────────────────────────────────────────────────────────────
# 3. walk_forward_validate 와 통합 테스트
# ──────────────────────────────────────────────────────────────

class TestWalkForwardIntegration:

    @pytest.fixture(scope="class")
    def synthetic_df(self):
        from utils.walk_forward_validator import TRAIN_FEATURES
        rng = np.random.default_rng(42)
        n_stocks, start_yr, end_yr = 8, 2015, 2023
        rows = []
        for s in range(n_stocks):
            code = f"{s+1:06d}"
            for yr in range(start_yr, end_yr + 1):
                row = {"stock_code": code, "year": yr}
                for feat in TRAIN_FEATURES:
                    row[feat] = float(rng.normal(0, 1))
                row["label_cut_1y"]        = float(rng.random() < 0.20)
                row["label_meaningful_1y"] = float(rng.random() < 0.10)
                rows.append(row)
        return pd.DataFrame(rows)

    def test_label_cut_1y_runs(self, synthetic_df):
        from utils.walk_forward_validator import walk_forward_validate
        result = walk_forward_validate(
            synthetic_df,
            model_class=SurvivalWalkForwardAdapter,
            model_params={"n_estimators": 50, "use_percentile_transform": True},
            target="label_cut_1y",
            verbose=False,
        )
        assert "folds" in result
        assert "oos_summary" in result

    def test_label_meaningful_1y_runs(self, synthetic_df):
        from utils.walk_forward_validator import walk_forward_validate
        result = walk_forward_validate(
            synthetic_df,
            model_class=SurvivalWalkForwardAdapter,
            model_params={"n_estimators": 50},
            target="label_meaningful_1y",
            verbose=False,
        )
        assert "folds" in result
        assert len(result["folds"]) > 0

    def test_temporal_ordering_preserved(self, synthetic_df):
        from utils.walk_forward_validator import walk_forward_validate
        result = walk_forward_validate(
            synthetic_df,
            model_class=SurvivalWalkForwardAdapter,
            model_params={"n_estimators": 30},
            target="label_cut_1y",
            verbose=False,
        )
        for fold in result["folds"]:
            assert fold["train_end"] < fold["test_year"], (
                f"train_end={fold['train_end']} >= test_year={fold['test_year']}"
            )

    def test_roc_auc_in_range(self, synthetic_df):
        from utils.walk_forward_validator import walk_forward_validate
        result = walk_forward_validate(
            synthetic_df,
            model_class=SurvivalWalkForwardAdapter,
            model_params={"n_estimators": 50},
            target="label_cut_1y",
            verbose=False,
        )
        for fold in result["folds"]:
            v = fold.get("roc_auc")
            if v is not None:
                assert 0.0 <= v <= 1.0, f"ROC-AUC={v} out of range"


# ──────────────────────────────────────────────────────────────
# 4. 엣지 케이스
# ──────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_predict_before_fit_raises(self):
        X, _ = make_Xy(n=10)
        adapter = SurvivalWalkForwardAdapter()
        with pytest.raises(RuntimeError, match="fit"):
            adapter.predict_proba(X)

    def test_single_class_train_raises(self):
        X, _ = make_Xy(n=50)
        y_all_zero = np.zeros(50, dtype=int)
        adapter = SurvivalWalkForwardAdapter()
        with pytest.raises(ValueError, match="클래스"):
            adapter.fit(X, y_all_zero)

    def test_repr_contains_class_name(self):
        adapter = SurvivalWalkForwardAdapter(n_estimators=100)
        assert "SurvivalWalkForwardAdapter" in repr(adapter)

    def test_fit_with_all_positive_raises(self):
        X, _ = make_Xy(n=30)
        y_all_one = np.ones(30, dtype=int)
        adapter = SurvivalWalkForwardAdapter()
        with pytest.raises(ValueError):
            adapter.fit(X, y_all_one)

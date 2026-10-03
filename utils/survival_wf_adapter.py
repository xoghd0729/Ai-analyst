"""
utils/survival_wf_adapter.py

Survival 모델을 walk_forward_validate()와 호환되는 sklearn 인터페이스로 래핑.

설계 근거:
  1. survival_pd.py 의 run_tier_model() 은 전체 기간 일괄 학습 + 전체 percentile 정규화
     → GroupKFold 분할 + rankdata() 전역 적용으로 test 데이터 오염 발생
     → walk-forward 에서는 연도 필터링된 train 데이터만으로 학습 후,
        train 스코어 분포를 기준으로 test 점수를 변환해야 함

  2. TabPFN 은 로컬 환경 의존성(torch, HF 인증) → HistGradientBoostingClassifier fallback
     (CatBoost 도 가능하지만 추가 의존성 → HGBM 단일화)

  3. label_meaningful_1y(t) 라벨 확정 한계:
       label_meaningful_1y(t) = meaningful_cut(t+1)
         where meaningful_cut(t+1) = dps_yoy_pct(t+1) < -30%
                                     AND dps_yoy_pct(t+2) >= 30% 이면 0으로 복원
       → 라벨 확정에 t+2 년 데이터 필요.
       → 예측 시점(t년 말) 에서 "t+1년에 30% 이상 삭감이 발생했지만 t+2년 회복으로
          무효화될" 케이스를 미리 알 수 없음.
       → walk-forward 평가 결과는 이 한계를 내포. 실운용 시 t+2 공시 후 재평가 권장.
       → 실제 데이터 확인: 36건이 회복 조건으로 meaningful_cut=0으로 복원됨 (2026-09-30 확인)

사용법:
    from utils.survival_wf_adapter import SurvivalWalkForwardAdapter
    from utils.walk_forward_validator import walk_forward_validate, TRAIN_FEATURES

    result = walk_forward_validate(
        df,
        model_class=SurvivalWalkForwardAdapter,
        model_params={"use_percentile_transform": True},
        target="label_meaningful_1y",
        features=TRAIN_FEATURES,
    )

연결 확인 사항:
    - walk_forward_validator.py 의 VALID_TARGETS 에 "label_meaningful_1y" 등록 완료 (STEP 4-1)
    - build_dataset.py 에서 label_meaningful_1y 생성 로직 추가 완료 (STEP 4-1)
    - 실험 실행은 STEP 4-2 완료 검증 후 별도 진행 (현재는 설계/구현 단계)
"""

from __future__ import annotations

import logging
import warnings
from typing import Optional

import numpy as np
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import HistGradientBoostingClassifier

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# survival_pd.py 와 공유하는 피처 목록
# (walk_forward_validator.py 의 TRAIN_FEATURES 와 교집합 사용 권장)
# ─────────────────────────────────────────────────────────────

SURVIVAL_PREFERRED_FEATURES = [
    # 배당 안정성 직접 지표
    "dividend_coverage", "payout_ratio", "dps_yoy_pct",
    # 현금흐름
    "operating_cf", "fcf", "capex", "div_to_ocf", "ocf_to_capex",
    "dividends_paid", "fcf_negative",
    # 재무 건전성
    "debt_ratio", "interest_coverage", "current_ratio",
    "revenue_yoy_pct", "net_margin", "roe", "roa",
    # 생존분석 파생 (altman_z 등은 load_person_period 에서 생성)
    "altman_z", "debt_ratio_slope",
    # 매크로
    "bok_rate", "kospi_ret",
]


# ─────────────────────────────────────────────────────────────
# 어댑터 클래스
# ─────────────────────────────────────────────────────────────

class SurvivalWalkForwardAdapter(BaseEstimator, ClassifierMixin):
    """
    HistGradientBoostingClassifier 기반 생존 분석 어댑터.

    walk_forward_validate() 가 요구하는 sklearn 인터페이스를 구현:
      - fit(X, y)         : train 데이터로 HGBM 학습 + percentile 기준 저장
      - predict_proba(X)  : train 분포 기준 percentile 변환 후 확률 반환
      - predict(X)        : threshold 기준 이진 예측
      - classes_          : [0, 1]

    Percentile 변환 (use_percentile_transform=True):
      raw_prob  = HGBM.predict_proba(X_test)[:, 1]
      rank      = searchsorted(sorted_train_scores, raw_prob)
      pct_prob  = rank / n_train         # train 분포 기준 백분위

    이 변환은 survival_pd.py 의 rankdata() 와 동일한 아이디어이지만,
    train 데이터만을 기준으로 정규화하므로 test 오염 없음.

    라벨 한계 (label_meaningful_1y 사용 시):
      label_meaningful_1y(t) 는 t+2 년 데이터까지 필요.
      walk-forward 평가에서 이 한계가 내포됨 — 문서 Section 9 참조.
    """

    def __init__(
        self,
        n_estimators: int = 300,
        learning_rate: float = 0.05,
        max_depth: int = 4,
        l2_regularization: float = 0.1,
        min_samples_leaf: int = 10,
        random_state: int = 42,
        use_percentile_transform: bool = True,
    ):
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.l2_regularization = l2_regularization
        self.min_samples_leaf = min_samples_leaf
        self.random_state = random_state
        self.use_percentile_transform = use_percentile_transform

        # 내부 상태 (fit 후 설정)
        self._model: Optional[HistGradientBoostingClassifier] = None
        self._sorted_train_scores: Optional[np.ndarray] = None
        self._n_train: int = 0
        self.classes_: np.ndarray = np.array([0, 1])

    # ── fit ────────────────────────────────────────────────────

    def fit(self, X: np.ndarray, y: np.ndarray) -> "SurvivalWalkForwardAdapter":
        """
        train 데이터로 HistGBM 학습 후 percentile 기준(sorted_train_scores)을 저장.

        Args:
            X : shape (n_train, n_features) — imputed, no NaN
                walk_forward_validate() 가 median imputation 후 전달
            y : shape (n_train,) — 이진 라벨 (0/1)
        """
        if len(np.unique(y)) < 2:
            raise ValueError(
                f"fit(): train 라벨에 클래스가 1개뿐입니다 "
                f"(unique={np.unique(y)}). fold 건너뜀 권장."
            )

        self._model = HistGradientBoostingClassifier(
            max_iter=self.n_estimators,
            learning_rate=self.learning_rate,
            max_depth=self.max_depth,
            l2_regularization=self.l2_regularization,
            min_samples_leaf=self.min_samples_leaf,
            random_state=self.random_state,
            early_stopping=False,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._model.fit(X, y)

        self.classes_ = np.array([0, 1])

        if self.use_percentile_transform:
            raw_train_probs = self._model.predict_proba(X)[:, 1]
            self._sorted_train_scores = np.sort(raw_train_probs)
            self._n_train = len(raw_train_probs)
            log.debug(
                "SurvivalAdapter fit: n_train=%d, n_pos=%d, "
                "score_range=[%.4f, %.4f]",
                self._n_train,
                int(y.sum()),
                self._sorted_train_scores[0],
                self._sorted_train_scores[-1],
            )

        return self

    # ── predict_proba ──────────────────────────────────────────

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        raw 확률 계산 후 train 분포 기준 percentile 변환.

        Args:
            X : shape (n_test, n_features) — imputed, no NaN

        Returns:
            shape (n_test, 2) — [[P(y=0), P(y=1)], ...]
            walk_forward_validate() 는 [:, 1] 만 사용
        """
        if self._model is None:
            raise RuntimeError("predict_proba(): fit()을 먼저 호출해야 합니다.")

        raw_probs = self._model.predict_proba(X)[:, 1]  # shape (n_test,)

        if (
            self.use_percentile_transform
            and self._sorted_train_scores is not None
            and self._n_train > 0
        ):
            # train 분위수 기준으로 test 스코어 순위 변환
            # np.searchsorted: 정렬된 배열에서 val 의 삽입 위치 반환
            rank = np.searchsorted(self._sorted_train_scores, raw_probs)
            pct_probs = rank / self._n_train          # [0, 1] 범위
            pct_probs = np.clip(pct_probs, 0.0, 1.0)  # 부동소수 방어
            final_probs = pct_probs
        else:
            final_probs = raw_probs

        return np.column_stack([1.0 - final_probs, final_probs])

    # ── predict ────────────────────────────────────────────────

    def predict(self, X: np.ndarray, threshold: float = 0.5) -> np.ndarray:
        """threshold 기준 이진 예측 (sklearn 호환)."""
        return (self.predict_proba(X)[:, 1] >= threshold).astype(int)

    # ── 직렬화 지원 ────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"SurvivalWalkForwardAdapter("
            f"n_estimators={self.n_estimators}, "
            f"learning_rate={self.learning_rate}, "
            f"max_depth={self.max_depth}, "
            f"use_percentile_transform={self.use_percentile_transform})"
        )


# ─────────────────────────────────────────────────────────────
# walk-forward 연결 헬퍼
# ─────────────────────────────────────────────────────────────

def run_survival_walk_forward(
    df,
    target: str = "label_meaningful_1y",
    features: Optional[list[str]] = None,
    model_params: Optional[dict] = None,
    verbose: bool = True,
) -> dict:
    """
    SurvivalWalkForwardAdapter 를 walk_forward_validate() 에 연결하는 편의 함수.

    Args:
        df          : build_dataset.py 로 생성한 dividend_dataset DataFrame
                      (label_meaningful_1y 컬럼 포함 필수)
        target      : "label_meaningful_1y" (Function B) 또는 "label_cut_1y" (Function A)
        features    : 피처 목록. None 이면 walk_forward_validator.TRAIN_FEATURES 사용
        model_params: SurvivalWalkForwardAdapter 파라미터 오버라이드
        verbose     : fold 별 진행 출력 여부

    Returns:
        walk_forward_validate() 반환 dict
            {
              "folds"       : List[dict],  # fold 별 metrics
              "oos_summary" : dict,        # 전체 OOS 평균
              "oos_df"      : DataFrame,   # fold 별 예측값
            }

    label_meaningful_1y 사용 시 주의:
        라벨 확정에 t+2 년 데이터 필요 (recovery condition).
        walk-forward 평가 결과는 이 한계를 내포함.
        최신 test_year 에서는 라벨이 미확정일 수 있으므로
        해당 fold 결과 해석 시 주의 요망.
    """
    from utils.walk_forward_validator import walk_forward_validate, TRAIN_FEATURES

    feat_list = features if features is not None else TRAIN_FEATURES
    params = {
        "n_estimators": 300,
        "learning_rate": 0.05,
        "max_depth": 4,
        "use_percentile_transform": True,
    }
    if model_params:
        params.update(model_params)

    if verbose:
        print(f"\n[SurvivalWalkForward] target={target}, features={len(feat_list)}개")
        print(f"  어댑터 설정: {params}")
        _label_warning(target, df)

    return walk_forward_validate(
        df,
        model_class=SurvivalWalkForwardAdapter,
        model_params=params,
        target=target,
        features=feat_list,
        verbose=verbose,
    )


def _label_warning(target: str, df) -> None:
    """label_meaningful_1y 사용 시 라벨 확정 한계 경고 출력."""
    if target != "label_meaningful_1y":
        return

    import pandas as pd
    years = sorted(df["year"].dropna().unique())
    max_year = int(max(years))
    print(
        f"\n  [라벨 한계 경고] label_meaningful_1y(t) 는 t+2 년 데이터까지 필요합니다."
        f"\n  데이터 최신 연도: {max_year}"
        f"\n  → {max_year - 1} 년 라벨: {max_year + 1} 년 공시 후 확정"
        f"  (현재 데이터에서는 {max_year} 년 회복 여부로 처리됨)"
        f"\n  → {max_year} 년 라벨: {max_year + 2} 년 공시 후 확정 (미확정 상태)"
        f"\n  실운용 시 최신 fold 결과 해석 주의 요망.\n"
    )

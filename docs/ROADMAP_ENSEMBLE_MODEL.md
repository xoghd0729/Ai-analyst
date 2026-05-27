# Week 1.5: 앙상블 모델 리팩토링 로드맵

> 목표: 단일 XGBoost 3-class → 3-모델 앙상블 + 베이지안 캘리브레이션
> 산출물: `models/kr_ensemble_v2.pkl` + 향상된 SHAP + Sortino/Calmar 메트릭

---

## 0. 왜 앙상블인가?

현재 `kr_3class_model.pkl` 단일 XGBoost의 한계:
- **Confidence 캘리브레이션 약함** — "85% 확률 STRONG"이 실제 85% 적중 아님
- **False positive 비용 큼** — BROKEN을 STABLE로 잘못 분류 시 사용자 손실
- **피처 의존도 편향** — 단일 트리 모델은 특정 피처에 과도 의존

앙상블의 효과:
- 3개 모델 평균 → confidence가 더 부드러워짐 (calibration error ↓)
- LightGBM + CatBoost로 누락값 처리 강화
- 베이지안 분포로 출력하면 Monte Carlo P10/P50/P90과 자연 결합

---

## 1. 작업 단위 분해 (Day 6~9)

### Day 6: 앙상블 트레이너 작성

**파일**: `train_kr_ensemble.py` (신규, 기존 `train_kr_3class.py` 참고)

**구조**:
```python
"""
train_kr_ensemble.py — 3-모델 앙상블 학습 파이프라인

학습 모델:
  1. XGBoost (기존, 빠르고 일반적)
  2. LightGBM (누락값 native 처리, 카테고리 피처 강함)
  3. CatBoost (오버피팅 저항, 작은 데이터에 강함)

앙상블 방식:
  - Soft voting (3개 모델의 predict_proba 평균)
  - 가중치는 cross-validation accuracy 기반 자동 산출

캘리브레이션:
  - sklearn CalibratedClassifierCV (isotonic regression)
  - 결과: predict_proba가 실제 발생 확률과 일치
"""

from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from catboost import CatBoostClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import VotingClassifier
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer

def build_ensemble(random_state=42):
    xgb = XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                        random_state=random_state, use_label_encoder=False)
    lgb = LGBMClassifier(n_estimators=200, max_depth=4, learning_rate=0.05,
                        random_state=random_state)
    cat = CatBoostClassifier(iterations=200, depth=4, learning_rate=0.05,
                            random_seed=random_state, verbose=0)

    voting = VotingClassifier(
        estimators=[('xgb', xgb), ('lgb', lgb), ('cat', cat)],
        voting='soft',
        weights=None  # CV로 자동 결정
    )

    pipeline = Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('ensemble', voting)
    ])

    return CalibratedClassifierCV(pipeline, method='isotonic', cv=5)
```

**Cursor 프롬프트**:
```
train_kr_ensemble.py를 위 구조로 작성해줘.
학습 데이터는 기존 build_dataset.py가 만든 dividend_dataset.csv 사용.
타깃은 STRONG/STABLE/BROKEN 3-class (기존과 동일).
학습 후 models/kr_ensemble_v2.pkl로 저장하고,
classification_report + confusion_matrix를 results/ensemble_v2_report.txt에 저장.
```

---

### Day 7: 캘리브레이션 검증 + 신뢰구간

**파일**: `utils/model_calibration.py` (신규) + 테스트

**검증 항목**:
1. **Brier Score** — 0에 가까울수록 좋음 (기존 < 신규)
2. **Expected Calibration Error (ECE)** — 10개 빈으로 분할 후 빈별 평균 confidence vs 실제 accuracy 차이
3. **Reliability Diagram** — 시각화 (matplotlib로 PNG 저장)

```python
def evaluate_calibration(model, X_test, y_test) -> dict:
    """
    반환:
    {
        "brier_score": float,
        "ece": float,
        "reliability_curve": [(bin_center, accuracy, confidence, count), ...],
        "calibration_grade": "A" / "B" / "C" / "D"
    }
    """
```

**Cursor 프롬프트**:
```
utils/model_calibration.py 작성:
1. evaluate_calibration() 함수 (위 시그니처)
2. plot_reliability_diagram() — matplotlib로 reports/calibration_v2.png 저장
3. tests/test_model_calibration.py — 3개 테스트:
   - test_ensemble_better_than_single (ECE 비교)
   - test_brier_score_within_bound (< 0.25)
   - test_reliability_curve_monotonic (저신뢰→고신뢰 영역에서 accuracy 증가)
```

---

### Day 8: SHAP 앙상블 대응

**파일**: `utils/shap_explainer.py` 수정

현재 `shap_explainer.py`는 단일 XGBoost 가정. 앙상블은 TreeExplainer가 직접 안 됨.

**수정 방향**:
```python
def explain_prediction(stock_data: dict, n_top: int = 3) -> dict:
    """
    앙상블 SHAP 처리:
    1. CalibratedClassifierCV → 내부 5개 fold의 VotingClassifier 평균
    2. 각 모델별로 TreeExplainer/KernelExplainer 적용
    3. SHAP value를 모델별 가중평균
    4. 결과: feature별 평균 기여도 + 모델 간 일치도(consistency score)
    """
```

**핵심 추가 필드**: `model_agreement_pct`
- 3개 모델이 같은 클래스 예측 → 100%
- 2/3 일치 → 67%
- 모두 다름 → 33%
- 이 값이 낮으면 "모델 간 의견 불일치" 경고 노출

**Cursor 프롬프트**:
```
utils/shap_explainer.py를 앙상블 모델 대응하도록 수정:
1. _load_model()이 kr_ensemble_v2.pkl 우선 로드, 없으면 기존 모델 폴백
2. explain_prediction() 반환에 model_agreement_pct 필드 추가
3. SHAPExplainerFilter의 결과에도 이 필드 포함되도록 api/pipeline/filters.py 수정
4. 테스트 tests/test_shap_explainer.py에 model_agreement 검증 케이스 추가
```

---

### Day 9: Sortino / Calmar / Information Ratio

**파일**: `utils/backtesting.py` 확장 + 새 메트릭 함수

**현재 메트릭**: CAGR, MDD, Sharpe
**추가**:
1. **Sortino Ratio** — 하방 변동성만 페널티 (배당 투자자에게 더 적합)
   ```
   Sortino = (포트폴리오 수익 - 무위험 수익) / 하방 표준편차
   ```
2. **Calmar Ratio** — MDD 대비 수익률 (위기 견딤 능력)
   ```
   Calmar = CAGR / |MDD|
   ```
3. **Information Ratio** — 벤치마크(KOSPI/SPY) 대비 알파
   ```
   IR = (포트폴리오 - 벤치마크) 평균 / 그 차이의 표준편차
   ```

**반환 구조 확장**:
```python
{
    "cagr_pct": ...,
    "mdd_pct": ...,
    "sharpe_ratio": ...,
    "sortino_ratio": ...,        # NEW
    "calmar_ratio": ...,          # NEW
    "information_ratio_kospi": ..., # NEW
    "information_ratio_sp500": ..., # NEW
    "downside_deviation_pct": ..., # NEW
}
```

**Cursor 프롬프트**:
```
utils/backtesting.py의 run_backtest() 반환 구조를 위 7개 필드 포함하도록 확장.
- Sortino: scipy 없이 numpy만으로 구현
- Calmar: cagr_pct / abs(mdd_pct), MDD=0이면 None
- Information Ratio: 벤치마크 데이터는 _HISTORICAL_DATA의 KOSPI/S&P500 사용
- 기존 필드는 그대로 유지 (하위 호환)
- tests/test_backtesting.py에 4개 새 테스트 추가
```

---

## 2. 완료 정의 (Definition of Done)

```bash
# 1. 앙상블 모델 학습 완료
ls -la models/kr_ensemble_v2.pkl
# → 파일 존재

# 2. ECE 개선 확인
python -c "
from utils.model_calibration import evaluate_calibration
import pickle
m_old = pickle.load(open('models/kr_3class_model.pkl', 'rb'))
m_new = pickle.load(open('models/kr_ensemble_v2.pkl', 'rb'))
# X_test, y_test 로드 후
# print(f'OLD ECE: {evaluate_calibration(m_old, X_test, y_test)[\"ece\"]}')
# print(f'NEW ECE: {evaluate_calibration(m_new, X_test, y_test)[\"ece\"]}')
"

# 3. SHAP 앙상블 호환
pytest tests/test_shap_explainer.py -v

# 4. 새 메트릭 노출
python -c "
from utils.backtesting import run_backtest
r = run_backtest([{'ticker':'SCHD','weight':1.0}])
assert 'sortino_ratio' in r and 'calmar_ratio' in r
assert 'information_ratio_sp500' in r
print('✓ 새 메트릭 모두 포함')
"
```

---

## 3. 의존성 추가 (requirements.txt)

```
lightgbm>=4.0.0
catboost>=1.2.0
scikit-learn>=1.3.0  # CalibratedClassifierCV
matplotlib>=3.7.0    # reliability diagram
```

---

## 4. 마이그레이션 전략

기존 `kr_3class_model.pkl`을 즉시 교체하지 않는다:
1. 새 모델 `kr_ensemble_v2.pkl` 병행 배포
2. `utils/shap_explainer.py`의 `_load_model()`이 환경변수 `USE_ENSEMBLE_MODEL=1`이면 신규, 아니면 기존
3. 1주일 A/B 비교 후 신규로 완전 전환
4. 완전 전환 시 `kr_3class_model.pkl`은 `models/legacy/`로 이동

**Cursor 프롬프트**:
```
utils/shap_explainer.py의 _load_model()에 환경변수 분기 로직 추가:
- os.getenv("USE_ENSEMBLE_MODEL", "0") == "1" → kr_ensemble_v2.pkl
- 그 외 → kr_3class_model.pkl (기존)
- 둘 다 없으면 명확한 에러 메시지
```

---

## 5. 리스크 & 대응

| 리스크 | 확률 | 대응 |
|---|---|---|
| CatBoost 학습 5분 이상 | 높음 | iterations=200으로 제한, 필요 시 GPU |
| 앙상블 ECE가 더 나쁨 | 낮음 | 모델별 가중치 grid search |
| SHAP 계산 10초 이상 | 중 | KernelExplainer는 nsamples=100으로 제한 |
| LightGBM 한국어 피처명 깨짐 | 중 | 피처명은 영어 snake_case 강제 |

---

## 6. Cursor 작업 시작 명령어

```
@docs/ROADMAP_ENSEMBLE_MODEL.md Day 6부터 순서대로 진행해줘.
train_kr_ensemble.py 작성 → 학습 실행 → 결과 리포트까지.
학습 시간이 5분 넘으면 중간 진행상황 출력해줘.
```

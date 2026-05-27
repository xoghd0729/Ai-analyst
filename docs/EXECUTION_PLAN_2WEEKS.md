# 2주 실행 마스터 플랜 — 프로덕션 핵심

> 데이터(Week 1) → 모델(Week 1.5) → 세금(Week 2)
> 매일 작업 ≈ 3~5시간 가정. 주말 포함 시 12일 압축 가능.

---

## 전체 갠트

```
Week 1 (Day 1~5) — 데이터 확장
  D1: KR 유니버스 100개
  D2: 한국 ETF 20개 통합
  D3: 시계열 2005~2025 확장
  D4: 매크로 일별 파이프라인
  D5: 특별배당 분리 + 품질 게이트

Week 1.5 (Day 6~9) — 앙상블 모델
  D6: train_kr_ensemble.py 작성·학습
  D7: 캘리브레이션 검증 + 신뢰구간
  D8: SHAP 앙상블 대응
  D9: Sortino/Calmar/IR 메트릭

Week 2 (Day 10~14) — 세금 정밀화 + 통합 검증
  D10: 해외양도세 모듈
  D11: 종합과세 누진세율
  D12: 건보료 + 분리/종합과세 비교
  D13: 통합 테스트 + 회귀 테스트
  D14: 프론트엔드 노출 + 문서화
```

---

## Cursor 작업 프롬프트 모음 (복사·붙여넣기)

### Day 1
```
.cursorrules와 @docs/ROADMAP_DATA_EXPANSION.md를 먼저 읽어줘.
그리고 scripts/collect_kr_dividend_stocks.py의 fetch_stock_data() 함수에서
TODO 부분을 pykrx + DART API로 실제 구현해줘.

요구사항:
1. pykrx.get_market_cap_by_date()로 시가총액 (단위: 억원)
2. dart-fss로 가장 최근 사업보고서 → 부채비율, 영업현금흐름
3. 배당 이력은 data/dividend_dataset.csv를 먼저 조회, 없으면 DART 배당공시
4. API rate limit 대응: 종목당 0.5초 sleep
5. 실패 종목은 건너뛰고 로그만 남기기 (전체 실패 안 됨)

마지막에 python scripts/collect_kr_dividend_stocks.py --limit 10 실행해서
샘플 결과 보여주고, data/approved_universe_kr_v2.json 확인.
```

### Day 2
```
@docs/ROADMAP_DATA_EXPANSION.md Day 2 작업.

1. data/asset_metadata.json에 20개 ETF 추가 (명세서 표 그대로)
2. scripts/fetch_etf_history.py 신규 작성:
   - yfinance + pykrx 혼합 (한국 ETF는 pykrx, 미국 추종은 yfinance)
   - 2015~2024 연도별 (price_return_pct, div_yield_pct) 추출
   - 결과를 utils/backtesting.py의 _HISTORICAL_DATA에 자동 추가 (수동 편집 X)
3. tests/test_backtesting.py에 TestETFCoverage 클래스 추가
   - test_all_20_etfs_in_historical_data
   - test_kodex_고배당_2020_drop_present
4. pytest tests/test_backtesting.py::TestETFCoverage -v 통과 확인
```

### Day 3
```
@docs/ROADMAP_DATA_EXPANSION.md Day 3.
utils/backtesting.py의 _HISTORICAL_DATA를 2005년부터 시작하도록 확장.
2008·2011·2020 같은 큰 위기 연도가 반드시 포함되도록 검증.
누락은 명시적 NaN, run_backtest()는 NaN 종목 자동 제외.
```

### Day 4
```
@docs/ROADMAP_DATA_EXPANSION.md Day 4.
utils/macro_data.py 신규 작성:
- 5개 시리즈 일별 수집 (BOK금리, UST10Y, USDKRW, VIX, KOSPI PER)
- data/macro_daily.parquet 저장 (pyarrow 사용)
- detect_regime(date) 함수
- utils/macro_regime.py와 통합하되 기존 시그니처 유지
- utils/data_pipeline.py에 매일 18:00 cron 추가
- .env 예시에 BOK_API_KEY 항목 추가
```

### Day 5
```
@docs/ROADMAP_DATA_EXPANSION.md Day 5.
utils/data_quality.py 작성 + build_dataset.py에 품질 게이트 통합.
detect_price_outliers, detect_dividend_anomalies, generate_quality_report 3개 함수.
이상치 알람은 utils/data_pipeline.py 매일 19:00 cron으로.
tests/test_data_quality.py에 5개 테스트.
```

### Day 6 (앙상블 학습)
```
@docs/ROADMAP_ENSEMBLE_MODEL.md Day 6.
train_kr_ensemble.py 신규 작성.
3-모델 (XGBoost + LightGBM + CatBoost) Soft Voting + CalibratedClassifierCV.
학습 데이터: data/dividend_dataset.csv (build_dataset.py 출력)
저장: models/kr_ensemble_v2.pkl
리포트: results/ensemble_v2_report.txt (classification_report + confusion_matrix)
학습 5분 넘으면 verbose 로그.
```

### Day 7
```
@docs/ROADMAP_ENSEMBLE_MODEL.md Day 7.
utils/model_calibration.py 작성:
- evaluate_calibration() (Brier, ECE, reliability curve)
- plot_reliability_diagram() (matplotlib PNG)
tests/test_model_calibration.py에 3개 테스트.
구버전(kr_3class_model.pkl)과 신버전(kr_ensemble_v2.pkl) ECE 비교 결과 출력.
```

### Day 8
```
@docs/ROADMAP_ENSEMBLE_MODEL.md Day 8.
utils/shap_explainer.py 수정:
- _load_model()이 USE_ENSEMBLE_MODEL=1 환경변수 보고 모델 선택
- explain_prediction() 반환에 model_agreement_pct 추가
- 앙상블 SHAP은 모델별 SHAP value 평균
api/pipeline/filters.py의 SHAPExplainerFilter도 새 필드 노출.
tests/test_shap_explainer.py 신규 작성 (없으면) 또는 보강.
```

### Day 9
```
@docs/ROADMAP_ENSEMBLE_MODEL.md Day 9.
utils/backtesting.py의 run_backtest() 반환에 4개 메트릭 추가:
sortino_ratio / calmar_ratio / information_ratio_kospi / information_ratio_sp500
기존 필드 모두 유지 (하위 호환).
tests/test_backtesting.py에 TestRiskAdjustedMetrics 클래스 + 4 테스트.
```

### Day 10
```
@docs/ROADMAP_TAX_PRECISION.md Day 10.
utils/foreign_capital_gains_tax.py 신규 작성.
22% 양도세 + 250만원 공제 + 환율 환산 + 4가지 optimization_tips.
환율 데이터는 utils/macro_data.py 우선, 없으면 한은 ECOS API 폴백.
tests/test_foreign_capital_gains_tax.py에 5개 시나리오 테스트.
```

### Day 11
```
@docs/ROADMAP_TAX_PRECISION.md Day 11.
utils/tax_brackets.py 신규 작성 (8개 누진 구간 + 지방세 10%).
utils/tax_optimizer.py의 estimated_extra_tax_만원 계산을 누진세 적용으로 교체.
**ISA 상수(4000/500/1000)는 절대 건드리지 말 것.**
tests/test_tax_optimizer.py의 ComprehensiveTaxLogic 클래스에 누진세 검증 4개 추가.
```

### Day 12
```
@docs/ROADMAP_TAX_PRECISION.md Day 12.
utils/health_insurance_premium.py + utils/tax_strategy_comparator.py 신규.
api/pipeline/filters.py에 TaxStrategyFilter 추가 (TaxOptimizerFilter 다음).
utils/storytelling.py에 generate_tax_warning() 추가.
tests/에 3개 파일 신규.
```

### Day 13 (회귀 테스트)
```
지난 12일 작업의 회귀 테스트 일괄 실행:

pytest tests/ -v --tb=short

실패 항목 자동 수정. 단, ISA 상수와 기존 함수 시그니처는 절대 변경 금지.
회귀 테스트 결과를 results/regression_report_$(date +%Y%m%d).txt로 저장.
```

### Day 14 (프론트엔드 + 문서)
```
1. frontend/src/components/ 에 3개 컴포넌트 신규:
   - TaxStrategyComparison.jsx (분리/종합과세 비교 카드)
   - HealthInsuranceAlert.jsx (피부양자 위험도 게이지)
   - ModelAgreementBadge.jsx (앙상블 모델 일치도 표시)

2. frontend/src/pages/Portfolio.jsx에 위 3개 import 및 렌더링 추가.

3. PROJECT_CONTEXT.md의 Tasks 목록에 #27 (데이터 확장), #28 (앙상블), #29 (세금 정밀화) 추가.
   각 항목에 완료된 파일 목록 명시.
```

---

## 일별 체크포인트 (매일 종료 시 확인)

각 Day 끝에 아래 명령으로 검증:
```bash
cd ~/ai-analyst

# 코드 정상 import
python -c "from utils import backtesting, tax_optimizer, shap_explainer; print('✓ import OK')"

# 새 테스트만 실행
pytest tests/ -v -k "당일추가키워드" --tb=short

# 전체 회귀 (Day 5, 9, 13에만)
pytest tests/ -v --tb=short
```

---

## 파일 변경 요약 (2주 후 최종)

```
신규 파일 (15개):
  scripts/collect_kr_dividend_stocks.py   # 이미 작성됨
  scripts/fetch_etf_history.py
  scripts/fetch_krx_history.py
  utils/macro_data.py
  utils/data_quality.py
  utils/model_calibration.py
  utils/foreign_capital_gains_tax.py
  utils/tax_brackets.py
  utils/health_insurance_premium.py
  utils/tax_strategy_comparator.py
  train_kr_ensemble.py
  frontend/src/components/TaxStrategyComparison.jsx
  frontend/src/components/HealthInsuranceAlert.jsx
  frontend/src/components/ModelAgreementBadge.jsx
  models/kr_ensemble_v2.pkl

수정 파일 (8개):
  utils/backtesting.py        (시계열 확장 + 4 메트릭 추가)
  utils/tax_optimizer.py      (누진세율 교체)
  utils/shap_explainer.py     (앙상블 대응)
  utils/macro_regime.py       (macro_data 연동)
  utils/data_pipeline.py      (cron 추가)
  utils/storytelling.py       (tax warning 추가)
  api/pipeline/filters.py     (TaxStrategyFilter 추가)
  api/pipeline/context.py     (새 필드 추가)
  api/pipeline/runner.py      (필터 순서 등록)
  build_dataset.py            (품질 게이트 통합)
  data/asset_metadata.json    (ETF 20개 추가)
  frontend/src/pages/Portfolio.jsx (3 컴포넌트 import)
  requirements.txt            (의존성 7개 추가)
  PROJECT_CONTEXT.md          (Tasks #27~#29 추가)

신규 데이터 파일 (3개):
  data/approved_universe_kr_v2.json
  data/macro_daily.parquet
  data/dividend_dataset_classified.csv
```

---

## 위험 신호 (즉시 멈추고 사용자에게 보고)

다음 상황 발생 시 작업 중단하고 보고:
1. **테스트 회귀** — 기존 테스트가 깨지면 즉시 롤백
2. **ISA 상수 변경 시도** — `.cursorrules` 위반
3. **API 키 누락** — `.env`에 새 키 필요할 때
4. **모델 학습 30분 초과** — 데이터 정합성 이슈 가능
5. **PostgreSQL 마이그레이션 필요** — 스키마 변경이 필요할 때

---

## 완료 후 기대 효과

| 지표 | Before | After |
|---|---|---|
| 백테스팅 시계열 | 10년 | **21년** |
| 추천 가능 종목 | ~20 | **120+** |
| 모델 ECE | ~0.18 | **~0.08 (목표)** |
| 세금 시뮬레이션 항목 | 3개 | **8개** |
| 신규 테스트 케이스 | 0 | **30+개** |
| 사용자 신뢰도 (정성) | "참고용" | **"의사결정 보조"** |

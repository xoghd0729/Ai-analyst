# AI 현금흐름 운영체제 — 프로젝트 전체 파일 구조 분석

> 작성일: 2026-06-12 | 모델: claude-sonnet-4-6  
> 대상: `~/ai-analyst/` 전체 파일 기반 자동 생성

---

## 1. 프로젝트 한 줄 요약

"배당 투자자가 '50세에 월 200만원 받으려면 얼마를 투자해야 하나?'라는 질문에 역산으로 답하는 AI 운영체제"

단순 추천이 아니라 **FIRE 역산 + Monte Carlo + 세금 최적화 + 행동편향 진단 + SHAP 설명** 까지 19단계 파이프라인으로 처리한다.

---

## 2. 기술 스택

| 레이어 | 기술 | 파일 |
|---|---|---|
| API 서버 | FastAPI + uvicorn | `api/main.py` |
| 파이프라인 | Pipe-and-Filter (19단계) | `api/pipeline/` |
| ML 모델 | XGBoost + sklearn Pipeline | `models/*.pkl` |
| ML 설명 | SHAP TreeExplainer | `utils/shap_explainer.py` |
| DB | PostgreSQL (SQLAlchemy ORM) + JSON/CSV 폴백 | `db/` |
| 스케줄러 | APScheduler (CronTrigger) | `utils/data_pipeline.py` |
| 프론트엔드 | React + Recharts | `frontend/src/` |
| 테스트 | pytest | `tests/` |
| LLM 연동 | Ollama (EXAONE 3.5 7.8B) | `utils/ollama_client.py`, `agents/thesis_agent.py` |

---

## 3. 디렉토리별 파일 목록 및 역할

### 3-1. `api/` — FastAPI 백엔드

#### `api/main.py`
- FastAPI 앱 진입점
- lifespan으로 APScheduler 시작/종료 관리
- CORS 설정 (React 개발서버 포트 허용)
- 라우터 등록: `portfolio`, `stock`, `ranking`, `auth`

#### `api/pipeline/context.py`
- `PortfolioRequest` dataclass: 사용자 입력 (나이, 소득, 목표 월배당, 투자금, 성향, 아키타입 등)
- `PipelineContext` dataclass: 파이프라인 전 단계 공유 상태 컨테이너 (20+ 필드)
  - 각 필터가 필요한 필드만 읽고 결과만 저장하는 구조
  - `add_error()` 메서드로 필터 실패 기록

#### `api/pipeline/base.py`
- `BaseFilter` 추상 클래스
- `name` 프로퍼티 + `process(ctx)` 추상 메서드 강제
- 새 분석 단계 추가 = 이 클래스 상속 + `process()` 구현으로 끝

#### `api/pipeline/filters.py` (582줄)
19개 Filter 클래스 구현:

| 순서 | 클래스명 | 역할 |
|---|---|---|
| 1 | `AxisWeightFilter` | 나이+성향 → 5축 기본 비중 → 아키타입 override → Macro override |
| 2 | `MacroRegimeFilter` | VIX·금리·환율 → 5가지 레짐 판정 (confidence score 포함) |
| 3 | `AssetPickerFilter` | 5축 비중에 따라 KR주식·US주식·ETF 선별 |
| 4 | `WeightAllocatorFilter` | 선별 자산에 비중 배분 + 세후 수익률 계산 |
| 5 | `SummarizeFilter` | 세전/세후 연간·월간 배당, 은행 대비 초과수익 요약 |
| 6 | `ProjectionFilter` | 20년 배당 성장 시뮬레이션 (생활비 커버리지 포함) |
| 7 | `RebalancingFilter` | 목표 비중 대비 현재 비중 편차 → 리밸런싱 플랜 |
| 8 | `StressTestFilter` | 배당 컷 30%·시장 폭락 40%·금리 급등 시나리오 |
| 9 | `SectorExposureFilter` | 섹터별 익스포저 집중도 분석 |
| 10 | `CalendarFilter` | 월별 배당 캘린더 히트맵 데이터 생성 |
| 11 | `RiskAlertFilter` | ISA 전략 + 리스크 경보 생성 |
| 12 | `FireEngineFilter` | FIRE 역산 (Lean/Regular/Fat/Custom 4가지 목표) |
| 13 | `MonteCarloFilter` | 1,000회 시뮬레이션 → P10/P50/P90 신뢰구간 |
| 14 | `TaxOptimizerFilter` | 2026 세법 기준 ISA·연금저축 절세 전략 |
| 15 | `BehavioralFinanceFilter` | 8가지 행동편향 탐지 (홈바이어스, 집중편향 등) |
| 16 | `YieldTrapFilter` | 고수익률 함정(yield trap) 탐지 |
| 17 | `PortfolioHealthFilter` | 6축 레이더 차트용 포트폴리오 건강도 점수 |
| 18 | `SHAPExplainerFilter` | WEAKENING/BROKEN 종목 SHAP 설명 생성 |
| 19 | `StorytellingFilter` | 5단락 자연어 내러티브 생성 |

#### `api/pipeline/runner.py` (241줄)
- `RecommendationPipeline.execute()`: 필터 순서대로 실행
- 필터 예외 발생 시 `ctx.add_error()` 기록 후 계속 진행 (fault-tolerant)
- `_to_response()`: PipelineContext → API 응답 JSON 직렬화

#### `api/routers/portfolio.py` (1905줄)
- `POST /api/portfolio/recommend` → `RecommendationPipeline` 실행
- `POST /api/portfolio/backtest` → `run_backtest()` 실행
- `pick_kr_stocks()`, `pick_us_stocks()`, `pick_etfs()`: 자산 선별 함수
- `assign_weights()`: 5축 비중 배분
- `ARCHETYPE_CONFIG`: 혼합형·성장형·배당형·안정형 아키타입 설정

#### `api/routers/stock.py`, `ranking.py`, `auth.py`
- 개별 종목 상세 / 랭킹 조회 / JWT 인증 엔드포인트

---

### 3-2. `utils/` — 핵심 분석 유틸리티

#### `utils/fire_engine.py` (372줄)
**FIRE 역산 엔진** — 이 프로젝트의 핵심 차별점

목표 월배당 → 필요 투자원금 역산 공식:
- 목표 투자원금 = 목표 연배당 / 세후 수익률
- PMT 공식으로 월 적립 필요금액 계산: `PMT = FV × r / ((1+r)^n - 1)`
- 인플레이션(CPI 2.5%) 반영한 실질 목표 상향 조정

4가지 FIRE 목표 유형:
- **Lean FIRE**: 월 120만원 (최소 생활비)
- **Regular FIRE**: 월 250만원 (서울 1인 생활비)
- **Fat FIRE**: 월 400만원 (여유 은퇴)
- **Custom**: 사용자 지정

#### `utils/monte_carlo.py` (347줄)
**Monte Carlo 시뮬레이션** — 확률적 미래 예측

- 1,000회 시뮬레이션 → P10/P50/P90 신뢰구간
- 자산 유형별 리스크 파라미터 (sigma, cut_prob, cut_severity)
- Macro Regime 연동: `_REGIME_CUT_MULTIPLIER` 로 레짐별 배당컷 확률 조정
- 반환: `confidence_at_target`, `prob_doubles`, `expected_cut_events`

#### `utils/tax_optimizer.py` (616줄)
**세금 최적화 엔진** — 2026 개정 세법 반영

2026 ISA 한도 (구법 대비 상향):
```python
ISA_ANNUAL_LIMIT     = 4_000   # 연 납입한도 (구: 2,000만원)
ISA_TAX_FREE_GENERAL = 500     # 일반형 비과세 (구: 200만원)
ISA_TAX_FREE_YOUTH   = 1_000   # 청년형 비과세 (구: 400만원)
```

기능:
1. 금융소득종합과세 임계점(2,000만원) 진단
2. ISA 계좌 최적 자산 배분 (절세 효과 최대화)
3. 연금저축 + IRP 세액공제 전략
4. 세금 건강 점수 (0~100)

#### `utils/macro_regime.py`
**거시경제 레짐 감지** — 5가지 국면 판정

레짐 종류: `RATE_RISING` | `RATE_FALLING` | `HIGH_VOLATILITY` | `RECESSION` | `NORMAL`

데이터 소스 우선순위:
1. yfinance 실시간 (VIX: ^VIX, 미국10Y: ^TNX, 달러/원: KRW=X)
2. `data/macro_cache.json` (TTL 6시간)
3. `data/macro_config.json` (수동 설정 fallback)

confidence 점수 방식: 각 지표가 5개 레짐을 독립 채점 → 최고점 레짐 채택

#### `utils/shap_explainer.py`
**SHAP 설명 엔진** — ML 블랙박스 해석

- XGBoost 모델 → SHAP TreeExplainer 연결
- WEAKENING/BROKEN 종목에만 실행 (성능 최적화)
- 피처 기여도 상위 3개를 한국어로 번역
- 반환: `prediction`, `confidence`, `top_factors`, `summary`

피처 목록: `fcf`, `dividends_paid`, `dividend_coverage`, `operating_cf`, `capex`, `div_to_ocf`, `fcf_negative`, `ocf_to_capex`, `payout_ratio`, `dps_yoy_pct`

#### `utils/behavioral_finance.py`
**행동편향 탐지** — 8가지 인지 편향 자동 진단

탐지 편향:
1. 홈 바이어스 (국내 자산 70%+ 위험)
2. 집중 편향 (단일 종목 35%+ 위험)
3. 최신성 편향 (최근 고수익 추격)
4. 배당 앵커링 (배당컷 신호에도 보유 집착)
5. 손실 회피 (BROKEN 종목 미교체)
6. 수익률 환상 (세전 고수익 착시)
7. 과도한 안전 추구 (방어 자산 과잉)
8. 분산 부족 (자산군 편중)

#### `utils/backtesting.py`
**백테스팅 엔진** — 2005~2024 실제 역사 데이터 검증

- yfinance 실제 수익률 우선, 실패 시 정적 테이블 폴백
- 벤치마크: KOSPI (`^KS11`), S&P500 (`^GSPC`)
- 반환: CAGR, MDD, Sharpe, 연도별 수익률, 벤치마크 대비 초과수익

내장 데이터: SCHD/VYM/DGRO/JEPI/JEPQ/SPYD/HDV/NOBL/QYLD/KO/JNJ/PG/ABBV/MCD/O/VNQ/TLT/BND/AGG (2015~2024)

#### `utils/storytelling.py`
**자연어 스토리텔링** — 5단락 PB 어조 내러티브

단락 구성: 현황 요약 → 자산 배분 전략 → 20년 미래 시나리오 → 리스크 경보 → 구체적 행동 권고

#### `utils/data_pipeline.py`
**자동 데이터 갱신** — APScheduler 연동

스케줄: ETF 매일 17:00 / US 토 00:00 / KR 일 01:00 (KST)

#### `utils/ai_advisor.py` + `utils/ollama_client.py`
- `use_llm=False`: 룰 기반 조언 (현재 기본값)
- `use_llm=True`: Ollama EXAONE 3.5 7.8B 호출 (미연동 → Task #24)

#### 기타 유틸리티

| 파일 | 역할 |
|---|---|
| `utils/universe.py` | 5축 자산 유니버스 정의 + 비중 계산 |
| `utils/etf_quality.py` | ETF 품질 필터 (AUM·비용·배당성장) |
| `utils/dividend_projection.py` | 배당 성장 20년 시뮬레이션 |
| `utils/dividend_calendar.py` | 월별 배당 캘린더 생성 |
| `utils/dividend_scorer.py` | 종목 배당 점수 산출 |
| `utils/stress_test.py` | 배당컷·시장폭락·금리급등 스트레스 테스트 |
| `utils/rebalancer.py` | 리밸런싱 플랜 생성 |
| `utils/survival.py` | ML+상관충격 생존확률 통합 지표 |
| `utils/yield_trap_detector.py` | 고수익률 함정 탐지 |
| `utils/coverage_report.py` | 데이터 커버리지 리포트 |
| `utils/data_validator.py` | 입력 데이터 유효성 검사 |

---

### 3-3. `models/` — 학습된 ML 모델

| 파일 | 크기 | 설명 |
|---|---|---|
| `kr_3class_model.pkl` | 1.2MB | KR 배당주 3-class 분류 (INTACT/WEAKENING/BROKEN) |
| `dividend_cut_model.pkl` | 99KB | KR 배당 삭감 이진 분류 (구 모델) |
| `us_dividend_cut_model.pkl` | 233KB | US 배당 삭감 이진 분류 |
| `us_risk_model.pkl` | 201KB | US 리스크 스코어 모델 |

#### KR 3-class 모델 상세 (`train_kr_3class.py`)
- 구조: `SimpleImputer → StandardScaler → XGBoost` sklearn Pipeline
- 라벨: `0=INTACT`, `1=WEAKENING`, `2=BROKEN`
- 핵심 특성: 미래 누출(leakage) 방지를 위해 t+1 정보는 피처에서 제외
- 피처 중요도 TOP 1: `dps_yoy_pct` (0.371) — 전년 대비 DPS 증감률이 압도적
- TimeSeriesSplit 교차검증 (시계열 데이터 특성 반영)

#### US 모델 검증 결과 (`reports/us_model_validation/`)
**중요 발견**: full 모델 AUC = 1.000 이지만 **leakage 주의**
- `dps_yoy_pct` 피처가 라벨 정의와 거의 동일 (dps < -5% = cut)
- no-DPS-YoY ablation 모델 AUC = 0.613 → 실제 예측력은 이쪽이 정직한 수치
- 발표 시 "full model이 강한 이유는 DPS 추세를 선행 포착하기 때문" 으로 프레이밍 필요

---

### 3-4. `data/` — 데이터 파일

#### 학습 데이터
| 파일 | 크기 | 내용 |
|---|---|---|
| `dividend_dataset.csv` | 439KB | KR 배당주 2,359행 / 종목별 다년도 재무제표 + 라벨 |
| `us_dividend_dataset.csv` | 47KB | US 배당주 433행 / 87종목 × 4~5년 |
| `us_reit_dataset.csv` | 3.9KB | US 리츠 |
| `dividend_dataset_with_events.csv` | 78KB | 뉴스 이벤트 포함 버전 |

#### 운영 데이터
| 파일 | 크기 | 내용 |
|---|---|---|
| `approved_universe_kr_v2.json` | 41KB | KR 배당주 승인 유니버스 |
| `asset_metadata.json` | 50KB | 전 자산 메타데이터 (배당성장률·지급월·MDD) |
| `ranking.csv` | 5.9KB | KR 배당주 랭킹 (overall_score, grade, ml_status) |
| `ml_scoring_results.csv` | 4.5KB | XGBoost 예측 결과 캐시 |
| `etf_quality_cache.json` | 8.4KB | ETF 품질 점수 캐시 |
| `macro_config.json` | 253B | 거시경제 수동 설정값 |
| `kr_historical_returns.json` | 38KB | KR 종목별 연도별 수익률 |
| `saved_portfolios.json` | 172KB | 저장된 포트폴리오 기록 |

#### KR 랭킹 상위 종목 (현재 기준)
1. 메리츠화재 (024800) — 점수 100, 수익률 4.8%, INTACT
2. 포스코인터내셔널 (047050) — 점수 100, 수익률 4.5%, INTACT
3. 한화손해보험 (000370) — 점수 98, 수익률 4.2%, INTACT
4. 동서 (026960) — 점수 98, 수익률 4.0%, INTACT

---

### 3-5. `db/` — 데이터베이스

#### `db/models.py` — SQLAlchemy ORM 테이블 4개

| 테이블 | 역할 | 파일 폴백 |
|---|---|---|
| `kr_yield_cache` | KR 배당수익률 캐시 | `yield_cache.json` |
| `ml_predictions` | XGBoost 예측 결과 | `ml_scoring_results.csv` |
| `etf_quality` | ETF 품질 지표 | `etf_quality_cache.json` |
| `asset_metadata` | 자산 메타데이터 flatten | `asset_metadata.json` |

#### `db/repository.py` — DB-First + 파일 폴백 패턴
```python
# 1. DB 먼저 시도 → 2. 실패 시 파일 자동 전환
```

---

### 3-6. `frontend/src/` — React 프론트엔드

#### 페이지
| 파일 | 역할 |
|---|---|
| `pages/Portfolio.jsx` | 메인 포트폴리오 결과 페이지 (전체 분석 결과 렌더링) |
| `pages/Dashboard.jsx` | 대시보드 홈 |
| `pages/StockDetail.jsx` | 종목 상세 페이지 |

#### 컴포넌트
| 파일 | 역할 |
|---|---|
| `HealthRadarChart.jsx` | 6축 레이더 차트 (포트폴리오 건강도) |
| `DividendCalendarHeatmap.jsx` | 월별 배당 히트맵 |
| `MonteCarloChart.jsx` | P10/P50/P90 밴드 차트 |
| `CashflowMilestone.jsx` | FIRE 마일스톤 진행바 |
| `BacktestChart.jsx` | 백테스팅 연도별 수익률 차트 (ComposedChart) |
| `PortfolioMonitor.jsx` | 포트폴리오 모니터링 |
| `YieldTrapWarning.jsx` | 수익률 함정 경고 |
| `ErrorBoundary.jsx` | React 에러 바운더리 |

---

### 3-7. `agents/` — AI 에이전트

#### `agents/thesis_agent.py`
**투자 thesis 종합 판단 에이전트**

- ML 리스크(70%) + 뉴스 이벤트(30%) → 가중 composite_risk 계산
- `composite_risk ≥ 0.55` → BROKEN, `≥ 0.30` → WEAKENING, `< 0.30` → INTACT
- Ollama EXAONE 3.5 7.8B로 자연어 설명 생성
- Contradiction Detection: 뉴스↑ + ML위험 → "시장 기대와 펀더멘털 괴리" 감지
- `thesis_history` DB에 저장 → 시간 변화 추적

#### `agents/news_agent.py`
뉴스 수집 및 이벤트 분류 에이전트

---

### 3-8. `auto_discovery/` — 자동 유니버스 발굴

| 파일 | 역할 |
|---|---|
| `orchestrator.py` | KR + US 스크리너 실행 → 평가 → 유니버스 업데이트 |
| `screener_kr.py` | DART API → 배당 공시 법인 필터링 (수익률 2.5%+, 연속 2년+) |
| `screener_us.py` | 미국 배당주 후보 발굴 |
| `evaluator.py` | 후보 종목 채점 엔진 |

---

### 3-9. `collectors/` — 데이터 수집기

| 파일 | 역할 |
|---|---|
| `dart.py` | DART API → KR 재무제표 수집 |
| `dart_dividend_events.py` | DART 배당 공시 이벤트 |
| `dividend.py` | 배당 데이터 수집 |
| `financials_us.py` | yfinance → US 재무데이터 |
| `macro.py` | 거시경제 지표 수집 |
| `naver.py` | 네이버 금융 크롤링 |
| `news_kr.py` | KR 뉴스 수집 |
| `news_cache.py` | 뉴스 캐시 관리 |
| `price.py` | 주가 데이터 수집 |
| `llm.py` | LLM 기반 뉴스 분석 |
| `fetch_dps_history.py` | DPS 이력 수집 |

---

### 3-10. `tests/` — 단위 테스트

| 파일 | 테스트 대상 | 주요 테스트 클래스 |
|---|---|---|
| `test_fire_engine.py` | `calc_fire_engine()` | ReturnStructure, MathAccuracy, EdgeCases, FireTimeline |
| `test_monte_carlo.py` | `run_monte_carlo()` | ReturnStructure, QuantileOrdering, ProbabilityBounds, MacroRegimeEffect |
| `test_tax_optimizer.py` | `calc_tax_optimizer()` | **TaxLawConstants2026** (ISA 4000/500/1000), ISA2026InResult |
| `test_behavioral_finance.py` | `detect_behavioral_biases()` | HomeBias, ConcentrationBias, YieldIllusion |
| `test_backtesting.py` | `run_backtest()` | CAGR, MDD, Sharpe, BenchmarkComparison |
| `test_pipeline_runner.py` | `RecommendationPipeline` | Context격리, 필터예외처리, 응답구조 |
| `test_yield_trap_detector.py` | `yield_trap_detector` | 수익률 함정 탐지 |

---

### 3-11. `scripts/` — 운영 스크립트

| 파일 | 역할 |
|---|---|
| `rebuild_ranking.py` | KR 랭킹 재생성 |
| `expand_universe.py` | 유니버스 확장 |
| `backfill_kr_history.py` | KR 종목 역사 수익률 백필 |
| `backtest_strategy.py` | 전략 백테스팅 실행 |
| `forward_backtest.py` | 미래 예측 검증 |
| `validate_us_model.py` | US 모델 expanding holdout 검증 |
| `validate_survival.py` | 생존확률 모델 검증 |
| `migrate_cache_to_db.py` | JSON 캐시 → PostgreSQL 마이그레이션 |
| `auto_update.py` | 자동 데이터 갱신 실행 |
| `patch_*.py` | 데이터 패치 스크립트들 |

---

### 3-12. `docs/` — 문서

| 파일 | 내용 |
|---|---|
| `최종보고서.md` | 졸업논문 최종 보고서 |
| `발표대본_최종.md` | 최종 발표 대본 |
| `발표준비.md` | 발표 준비 체크리스트 |
| `project_architecture.md` | 아키텍처 문서 |
| `CAPSTONE_PRESENTATION_PLAN.md` | 캡스톤 발표 계획 |
| `ROADMAP_ENSEMBLE_MODEL.md` | 앙상블 모델 로드맵 |
| `images/` | UML, ERD, 파이프라인 다이어그램 등 |

---

### 3-13. `results/` — 모델 학습 결과

| 파일 | 내용 |
|---|---|
| `kr_3class_feature_importance.json` | KR 3-class 피처 중요도 (dps_yoy_pct 0.371로 TOP) |
| `us_feature_importance.json` | US 모델 피처 중요도 |
| `prediction_result.csv` | 예측 결과 |
| `model_evaluation.png` | 모델 평가 시각화 |

---

## 4. 핵심 데이터 플로우

```
사용자 입력 (나이·소득·투자금·목표)
    ↓
POST /api/portfolio/recommend
    ↓
RecommendationPipeline.execute()
    ↓
[MacroRegime] → VIX·금리 → 레짐 판정 (RATE_RISING 등)
    ↓
[AxisWeight] → 나이+성향+레짐 → 5축 비중 결정
    ↓
[AssetPicker] → ranking.csv + ML스코어 → 자산 선별
    ↓
[WeightAllocator] → 비중 배분 + 세후 수익률
    ↓
[Summarize] → 월배당·은행대비 초과수익 계산
    ↓
[FireEngine] → Lean/Regular/Fat FIRE 역산
    ↓
[MonteCarlo] → 1,000회 시뮬레이션 → P10/P50/P90
    ↓
[TaxOptimizer] → ISA/연금저축 절세 전략
    ↓
[BehavioralFinance] → 8가지 편향 탐지
    ↓
[SHAPExplainer] → WEAKENING/BROKEN 종목 ML 설명
    ↓
[Storytelling] → 5단락 자연어 요약
    ↓
JSON 응답 반환 → React 프론트엔드 렌더링
```

---

## 5. ML 모델 피처 중요도 (KR 3-class)

| 피처 | 중요도 | 의미 |
|---|---|---|
| `dps_yoy_pct` | **0.371** | 전년 대비 DPS 증감률 — 압도적 1위 |
| `payout_ratio` | 0.058 | 배당성향 |
| `revenue_yoy_pct` | 0.059 | 매출 성장률 |
| `div_to_ocf` | 0.057 | 배당/영업현금흐름 |
| `dividends_paid` | 0.054 | 배당 지급액 |
| `debt_ratio` | 0.057 | 부채 비율 |
| 기타 7개 | ~0.05씩 | fcf, coverage, capex 등 |

---

## 6. 남은 작업 (Tasks #22~#26)

| Task | 내용 | 파일 위치 |
|---|---|---|
| #22 | `BacktestChart.jsx` — recharts ComposedChart | `frontend/src/components/` ✅ 파일 존재 |
| #23 | `portfolio_optimizer.py` — MPT 효율적 프론티어 | `utils/portfolio_optimizer.py` (미생성) |
| #24 | `ai_advisor.py` Ollama 실제 연동 | `utils/ai_advisor.py` 수정 필요 |
| #25 | `InteractiveSimulator.jsx` — 슬라이더 실시간 재계산 | `frontend/src/components/` (미생성) |
| #26 | 포트폴리오 비교 기능 (`CompareView.jsx`) | `frontend/src/pages/` (미생성) |

---

## 7. 교수님 피드백 → 대응 방향

| 피드백 | 현황 | 대응 |
|---|---|---|
| XGBoost 평범 | KR 3-class + US binary 2개 모델 | TabPFN / FT-Transformer 비교 실험 |
| Perplexity 대비 차별점 부족 | 단순 추천 수준 | FIRE 역산·실시간 운영 시스템으로 포지셔닝 |
| 미국 지원 부족 | US 모델 있으나 KR보다 약함 | SEC EDGAR 확장, 동일 엔진 적용 |
| 신규 상장 처리 없음 | 과거 데이터 기반 | 업종 평균 활용 Cold Start 로직 필요 |
| DART 갱신 구조 부재 | APScheduler 있음 | 증분 업데이트·버전 관리 보완 |
| 거시경제 변수 부족 | VIX·금리·환율만 | CPI·GDP·FRED API 추가 필요 |
| 프로젝트 규모 | 한국 배당주 중심 | 한국+미국+거시+자동갱신+Agent 확장 |

---

## 8. 빠른 실행

```bash
# 서버
cd ~/ai-analyst
uvicorn api.main:app --reload --port 8000

# 테스트
pytest tests/ -v --tb=short

# 프론트엔드
cd frontend && npm run dev

# 모델 재학습
python train_kr_3class.py
python train_us_model.py

# 데이터 수동 갱신
python utils/data_pipeline.py

# 유니버스 자동 발굴
python auto_discovery/orchestrator.py
```

# AI 현금흐름 운영체제 — 프로젝트 컨텍스트

> 이 문서를 통째로 AI에게 붙여넣으면 프로젝트 구조와 현재 상태를 이해하고 즉시 작업을 이어받을 수 있다.

---

## 1. 프로젝트 정체성

**이름**: AI 현금흐름 운영체제 (AI Cashflow OS)  
**버전**: v2.0.0  
**핵심 컨셉**: "미래 월급형 현금흐름을 설계·분석·방어·관리하는 AI 운영체제"  
**작업 디렉토리**: `~/ai-analyst/`  

단순 포트폴리오 추천이 아니라, 배당 투자자가 원하는 진짜 질문("50세에 월 200만원 받으려면 지금 얼마를 투자해야 하나?")에 역산으로 답하는 시스템이다.

---

## 2. 기술 스택

| 레이어 | 기술 |
|---|---|
| API 서버 | FastAPI (uvicorn), `api/main.py` |
| 분석 파이프라인 | Pipe-and-Filter 패턴, 18개 Filter |
| ML 모델 | XGBoost + sklearn Pipeline, `models/kr_3class_model.pkl` |
| 설명 가능성 | SHAP TreeExplainer |
| DB | PostgreSQL (SQLAlchemy ORM) + JSON/CSV 파일 폴백 |
| 스케줄러 | APScheduler (CronTrigger) |
| 프론트엔드 | React + Recharts, `frontend/src/` |
| 테스트 | pytest, `tests/` |

---

## 3. 디렉토리 구조

```
ai-analyst/
├── api/
│   ├── main.py                  # FastAPI 앱, lifespan 스케줄러
│   ├── pipeline/
│   │   ├── context.py           # PipelineContext, PortfolioRequest dataclass
│   │   ├── base.py              # BaseFilter 추상 클래스
│   │   ├── filters.py           # 18개 Filter 클래스
│   │   └── runner.py            # RecommendationPipeline.execute()
│   └── routers/
│       ├── portfolio.py         # POST /recommend, POST /backtest
│       ├── stock.py
│       └── ranking.py
├── utils/
│   ├── fire_engine.py           # FIRE 역산 (PMT 공식)
│   ├── monte_carlo.py           # P10/P50/P90 시뮬레이션 (macro_regime 연동)
│   ├── tax_optimizer.py         # 2026 세법, ISA/연금 절세
│   ├── behavioral_finance.py    # 8가지 행동편향 탐지
│   ├── backtesting.py           # CAGR/MDD/Sharpe 백테스팅 (2015-2024)
│   ├── shap_explainer.py        # SHAP 설명 엔진
│   ├── data_pipeline.py         # APScheduler 자동 데이터 갱신
│   ├── macro_regime.py          # 거시 레짐 판단
│   ├── storytelling.py          # 자연어 요약 생성
│   ├── dividend_projection.py   # 배당 성장 예측
│   └── ...
├── db/
│   ├── models.py                # SQLAlchemy ORM (KrYieldCache, MLPrediction 등)
│   └── repository.py            # DB-first + 파일 폴백 패턴
├── models/
│   └── kr_3class_model.pkl      # XGBoost 한국주식 3클래스 분류 (STRONG/STABLE/BROKEN)
├── frontend/
│   └── src/
│       ├── pages/Portfolio.jsx  # 메인 포트폴리오 결과 페이지
│       └── components/
│           ├── HealthRadarChart.jsx      # 6축 레이더 차트
│           ├── DividendCalendarHeatmap.jsx # 월별 배당 히트맵
│           ├── MonteCarloChart.jsx        # P10/P50/P90 밴드 차트
│           └── CashflowMilestone.jsx      # FIRE 마일스톤 진행바
└── tests/
    ├── test_fire_engine.py
    ├── test_monte_carlo.py
    ├── test_tax_optimizer.py
    ├── test_behavioral_finance.py
    ├── test_backtesting.py
    └── test_pipeline_runner.py
```

---

## 4. 핵심 아키텍처: Pipe-and-Filter 파이프라인

### 실행 흐름

```
POST /api/portfolio/recommend
    ↓
RecommendationPipeline(request).execute()
    ↓
[MacroRegimeFilter] → [AxisWeightFilter] → [AssetPickerFilter]
    → [WeightAllocatorFilter] → [SummarizeFilter] → [ProjectionFilter]
    → [RebalancingFilter] → [StressTestFilter] → [SectorExposureFilter]
    → [CalendarFilter] → [RiskAlertFilter] → [FireEngineFilter]
    → [MonteCarloFilter] → [TaxOptimizerFilter] → [BehavioralFinanceFilter]
    → [PortfolioHealthFilter] → [SHAPExplainerFilter] → [StorytellingFilter]
    ↓
_to_response() → JSON 반환
```

### PipelineContext 핵심 필드

```python
@dataclass
class PortfolioRequest:
    age: int
    annual_income: int        # 만원
    monthly_target: int       # 목표 월배당 (만원)
    investable_amount: int    # 투자금 (만원)
    risk_tolerance: str       # "conservative" / "moderate" / "aggressive"
    archetype: str            # "혼합형" / "성장형" / "배당형" / "안정형"
    monthly_savings: float    # 월 적립금 (만원)
    target_fire_age: int      # 목표 FIRE 나이

@dataclass
class PipelineContext:
    request: PortfolioRequest
    macro: dict               # MacroRegimeFilter 결과
    recommendations: list     # WeightAllocatorFilter 결과
    monte_carlo: dict         # MonteCarloFilter 결과
    fire_engine: dict         # FireEngineFilter 결과
    tax: dict                 # TaxOptimizerFilter 결과
    behavioral: dict          # BehavioralFinanceFilter 결과
    backtest: dict            # (선택) BacktestFilter 결과
    # ... 총 20+ 필드
```

### 필터 작성 패턴

```python
class NewFilter(BaseFilter):
    name = "NewFilter"

    def process(self, ctx: PipelineContext) -> None:
        # ctx에서 이전 필터 결과 읽기
        recs = ctx.recommendations
        # 계산 후 ctx에 저장
        ctx.new_result = some_calculation(recs)
```

---

## 5. 주요 유틸리티 함수 시그니처

### fire_engine.py
```python
calc_fire_engine(
    current_investable: float,   # 투자금 (만원)
    monthly_savings: float,      # 월 적립 (만원)
    current_age: int,
    target_age: int = 50,
    avg_net_yield: float = 3.5,  # 세후 수익률 (%)
    div_growth_rate: float = 5.0,
    cpi_rate: float = 2.5,
    custom_monthly_만원: float = 0.0,
) -> dict
# 반환: targets(lean/regular/fat/custom), current_state, fire_timeline, recommended_action
```

### monte_carlo.py
```python
run_monte_carlo(
    recommendations: list[dict],
    investable_amount: float,
    years: int = 20,
    n_simulations: int = 1000,
    monthly_target: float = 0.0,
    seed: Optional[int] = 42,
    macro_regime: Optional[dict] = None,   # ← Macro 연동 핵심
) -> dict
# 반환: p10_monthly, p50_monthly, p90_monthly, p10_final, p50_final, p90_final,
#        confidence_at_target, prob_doubles, expected_cut_events, summary_message
```

### tax_optimizer.py (2026 세법 반영)
```python
# 상수:
ISA_ANNUAL_LIMIT     = 4_000   # 연 납입한도 (구: 2,000)
ISA_TAX_FREE_GENERAL = 500     # 일반형 비과세 (구: 200)
ISA_TAX_FREE_YOUTH   = 1_000   # 청년형 비과세 (구: 400)

calc_tax_optimizer(
    recommendations: list[dict],
    investable_amount: float,
    investor_age: int,
    annual_income_만원: float = 0,
    is_youth: bool = False,
) -> dict
# 반환: comprehensive_tax, isa_strategy, pension_strategy,
#        effective_tax_rate_pct, optimized_tax_rate_pct,
#        total_annual_saving_만원, priority_actions, tax_health_score
```

### backtesting.py
```python
run_backtest(
    recommendations: list[dict],
    start_year: int = 2015,
    end_year: int = 2024,
    investable: float = 1000.0,
    risk_free_rate: float = 2.0,
) -> dict
# 반환: cagr_pct, mdd_pct, sharpe_ratio, yearly_returns, total_return_pct
# 내장 데이터: SCHD/VYM/DGRO/JEPI/JEPQ/SPYD/HDV/NOBL/QYLD/KO/JNJ/PG/ABBV/MCD/O/VNQ/TLT/BND/AGG (2015-2024)
```

### shap_explainer.py
```python
explain_portfolio_risks(recommendations: list[dict]) -> list[dict]
# WEAKENING/BROKEN 종목에만 SHAP 설명 실행
# 반환: prediction, confidence, top_factors(feature, value, impact, label_ko), summary

explain_prediction(stock_data: dict, n_top: int = 3) -> dict
# 단일 종목 SHAP 분석
# 모델: models/kr_3class_model.pkl (sklearn Pipeline: SimpleImputer → XGBoost)
# 피처: fcf, dividends_paid, dividend_coverage, operating_cf, capex,
#        div_to_ocf, fcf_negative, ocf_to_capex, payout_ratio, dps_yoy_pct
```

---

## 6. 완료된 작업 목록 (Tasks #1~#20)

| # | 작업 | 결과물 |
|---|---|---|
| 1 | build_dataset.py — DART 다년도 수집 + 라벨링 | `build_dataset.py` |
| 5 | 포트폴리오 유니버스 4축 설계 | `data/approved_universe.json` |
| 12 | Pipe-and-Filter 리팩토링 | `api/pipeline/` |
| 13 | PostgreSQL 마이그레이션 | `db/models.py`, `db/repository.py` |
| 14 | Macro Regime → Monte Carlo 연동 | `utils/monte_carlo.py` `_REGIME_CUT_MULTIPLIER` |
| 15 | tax_optimizer 2026 세법 | `utils/tax_optimizer.py` ISA 한도 4배 상향 |
| 17 | 프론트엔드 4개 컴포넌트 | `HealthRadarChart`, `DividendCalendarHeatmap`, `MonteCarloChart`, `CashflowMilestone` |
| 18 | 백테스팅 엔진 | `utils/backtesting.py` |
| 19 | 실시간 데이터 파이프라인 | `utils/data_pipeline.py` + APScheduler |
| 20 | SHAP 설명 가능성 | `utils/shap_explainer.py` + `SHAPExplainerFilter` |
| 21 | Unit Test 작성 (진행 중) | `tests/` — 6개 파일 작성 완료 |

---

## 7. 현재 진행 중: Task #21 Unit Tests

### 완료된 테스트 파일

| 파일 | 대상 | 테스트 클래스 |
|---|---|---|
| `test_fire_engine.py` | `calc_fire_engine()` | ReturnStructure, MathAccuracy, EdgeCases, FireTimeline |
| `test_monte_carlo.py` | `run_monte_carlo()` | ReturnStructure, QuantileOrdering, ProbabilityBounds, MacroRegimeEffect, ReproducibilityAndEdgeCases |
| `test_tax_optimizer.py` | `calc_tax_optimizer()` | **TaxLawConstants2026** (ISA 4000/500/1000), ReturnStructure, ISA2026InResult, ComprehensiveTaxLogic, TaxRateLogic |
| `test_behavioral_finance.py` | `detect_behavioral_biases()` | ReturnStructure, HomeBias, ConcentrationBias, YieldIllusion, ExcessiveSafety, EdgeCases |
| `test_backtesting.py` | `run_backtest()` | ReturnStructure, CAGR, MDD, Sharpe, BenchmarkComparison, EdgeCases |
| `test_pipeline_runner.py` | `RecommendationPipeline` | TestPipelineContext, TestPortfolioRequest, TestRecommendationPipeline, TestPipelineWithVariousInputs |

### 테스트 실행 방법

```bash
cd ~/ai-analyst

# 전체 실행
pytest tests/ -v

# 개별 파일
pytest tests/test_fire_engine.py -v
pytest tests/test_monte_carlo.py -v
pytest tests/test_tax_optimizer.py -v
pytest tests/test_behavioral_finance.py -v
pytest tests/test_backtesting.py -v
pytest tests/test_pipeline_runner.py -v

# 특정 클래스/함수만
pytest tests/test_tax_optimizer.py::TestTaxLawConstants2026 -v
pytest tests/test_monte_carlo.py::TestMacroRegimeEffect -v
```

---

## 8. 남은 작업 목록 (Tasks #22~#26)

### Task #22: 백테스팅 UI 차트 (`BacktestChart.jsx`)

**목표**: 백테스팅 결과를 시각화하는 React 컴포넌트

**구현 내용**:
- 연도별 수익률 막대 차트 (양수=파랑, 음수=빨강)
- KOSPI / S&P500 벤치마크 라인 오버레이
- CAGR / MDD / Sharpe 요약 카드
- recharts `ComposedChart` (BarChart + LineChart 혼합)

**파일 위치**: `frontend/src/components/BacktestChart.jsx`  
**연동**: `Portfolio.jsx`에서 import 후 렌더링  
**API**: `POST /api/portfolio/backtest` → `run_backtest()` 결과 사용

```jsx
// 데이터 형태 (yearly_returns)
[
  { year: 2015, return_pct: 12.3, vs_kospi: 5.1, vs_sp500: 1.2, kospi_ret: 7.2, sp500_ret: 11.1 },
  { year: 2016, return_pct: -2.1, ... },
  ...
]
```

---

### Task #23: MPT 효율적 프론티어 (`utils/portfolio_optimizer.py`)

**목표**: 평균-분산 최적화로 샤프 비율 최대 포트폴리오 계산

**구현 내용**:
```python
# utils/portfolio_optimizer.py
def optimize_portfolio(
    tickers: list[str],
    returns_data: dict[str, list[float]],  # 연도별 수익률
    risk_free_rate: float = 2.0,
    n_portfolios: int = 5000,              # 몬테카를로 샘플링
) -> dict:
    # scipy.optimize.minimize 또는 랜덤 샘플링
    # 반환: optimal_weights, max_sharpe_port, min_vol_port, frontier_points
```

**API 엔드포인트**: `POST /api/portfolio/optimize`  
**프론트엔드**: 2D 산점도 (x=변동성, y=수익률, 색=샤프비율)

---

### Task #24: AI Advisor LLM 실제 연동 (`utils/ai_advisor.py`)

**목표**: `use_llm=True` 시 ollama 로컬 LLM 호출

**현재 상태**: `utils/ollama_client.py` 존재, `utils/ai_advisor.py`에 `use_llm` 파라미터 있지만 미연동

**구현**:
```python
# utils/ai_advisor.py 수정
from utils.ollama_client import call_ollama

def generate_advice(portfolio_summary: dict, use_llm: bool = False) -> str:
    if use_llm:
        prompt = _build_prompt(portfolio_summary)
        return call_ollama(prompt, model="llama3.1")
    return _rule_based_advice(portfolio_summary)
```

---

### Task #25: 인터랙티브 시뮬레이터 UI (`InteractiveSimulator.jsx`)

**목표**: 슬라이더로 파라미터 조절 → 실시간 Monte Carlo + FIRE 재계산

**컴포넌트 구성**:
- 투자금 슬라이더 (0 ~ 50,000만원)
- 월 적립금 슬라이더 (0 ~ 500만원)
- 목표 수익률 슬라이더 (2% ~ 8%)
- 우측: P50 최종 월배당, FIRE 달성 나이 실시간 업데이트
- debounce 300ms로 API 호출 최소화

---

### Task #26: 포트폴리오 비교 기능

**목표**: 두 포트폴리오 나란히 비교

**API**: `POST /api/portfolio/compare` → `[req_a, req_b]` 입력
**프론트엔드**: `CompareView.jsx` — 레이더차트 2개 + 주요 지표 비교 테이블

---

## 9. 주의사항 / 코딩 규칙

### 한국어 인코딩 처리
Python 파일 수정 시 한국어 문자열이 포함된 경우, `Edit` 툴 대신 `bash heredoc`으로 작성해야 한다:
```bash
python3 - << 'EOF'
# 한국어 포함 파이썬 코드
EOF
```

### DB-First + 파일 폴백 패턴 (db/repository.py)
```python
def get_ml_scores() -> dict:
    try:
        # 1. DB 먼저 시도
        with Session(engine) as session:
            rows = session.query(MLPrediction).all()
            return {r.ticker: r.to_dict() for r in rows}
    except Exception:
        # 2. 파일 폴백
        return json.load(open("data/ml_scores.json"))
```

### 필터 에러 핸들링
```python
# runner.py — 필터 예외 발생해도 파이프라인 계속 진행
try:
    filt.process(self.ctx)
except Exception as exc:
    log.error("Pipeline step %s failed: %s", filt.name, exc)
    self.ctx.add_error(filt.name, str(exc))
```

### 2026 세법 상수 (변경 금지)
```python
ISA_ANNUAL_LIMIT     = 4_000  # 만원 — 구법 2,000 대비 2배
ISA_TAX_FREE_GENERAL = 500    # 만원 — 구법 200 대비 2.5배
ISA_TAX_FREE_YOUTH   = 1_000  # 만원 — 구법 400 대비 2.5배
```

---

## 10. 빠른 시작

```bash
# 서버 실행
cd ~/ai-analyst
uvicorn api.main:app --reload --port 8000

# 테스트 실행
pytest tests/ -v --tb=short

# 프론트엔드
cd frontend && npm run dev

# 데이터 수동 갱신
python utils/data_pipeline.py
```

---

## 11. 다음 AI에게 요청할 수 있는 작업 예시

**질문 형태**:
- "Task #22 BacktestChart.jsx 컴포넌트를 작성해줘. recharts ComposedChart로 yearly_returns를 막대+선 혼합 차트로 그려야 해."
- "tests/ 디렉토리에 있는 테스트 파일들을 실행해서 통과하는지 확인해줘."
- "Task #23 MPT 효율적 프론티어를 scipy로 구현해줘. utils/portfolio_optimizer.py에 작성하고 /api/portfolio/optimize 엔드포인트도 추가해줘."
- "SHAPExplainerFilter가 제대로 동작하는지 확인하는 테스트를 tests/test_shap_explainer.py에 추가해줘."

**작업 시작 전 확인사항**:
1. 작업 디렉토리는 항상 `~/ai-analyst/` 기준
2. 새 유틸리티 함수는 `utils/` 에, 새 API 엔드포인트는 `api/routers/portfolio.py` 에
3. 새 React 컴포넌트는 `frontend/src/components/` 에 작성 후 `Portfolio.jsx`에서 import
4. 한국어 포함 파일 수정 시 bash heredoc 사용

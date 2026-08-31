# AI Cashflow OS — 전체 구현 현황

> 마지막 업데이트: 2026-08-25 (세션2)  
> 발표일: 2026-09-02 (수)

---

## 0. 프로젝트 정체성

**"미래 월급형 현금흐름을 설계·분석·방어·관리하는 AI 운영체제"**

핵심 질문: "50세에 월 200만원 받으려면 지금 얼마를 투자해야 하나?"  
→ 단순 포트폴리오 추천이 아닌 **역산 방식** 접근

**모든 기술 결정 원칙**:  
1. 왜 이 방법인가  
2. 어떤 대안을 검토했는가  
3. 왜 대안을 버렸는가  
4. 어떤 실험 증거가 있는가

---

## 1. ML 모델

### 1-1. XGBoost 3-class Classifier

**파일**: `models/kr_3class_model.pkl`  
**역할**: 현재 상태 분류 — "지금 이 종목이 배당을 삭감할 위험이 있는가"

**클래스**:
- `INTACT` (0): 배당 안전
- `WEAKENING` (1): 약화 신호
- `BROKEN` (2): 배당 삭감 위험

**피처 10개**:
```
fcf, dividends_paid, dividend_coverage, operating_cf, capex,
div_to_ocf, fcf_negative, ocf_to_capex, payout_ratio, dps_yoy_pct
```

**Pipeline**: `SimpleImputer(strategy='median') → XGBoostClassifier`

**Walk-forward 검증 결과 (2019–2024, 6개 split)**:
- ROC-AUC: 0.799
- PR-AUC: 0.803
- P@20 (상위 20 종목 중 실제 위험 종목 비율): 0.96

**왜 XGBoost인가**:  
LightGBM, CatBoost, TabPFN, LR, RF 5개 대안 검토.  
XGBoost가 재무제표 데이터(결측값 많음, 비선형 관계)에서 가장 안정적 성능.  
TabPFN은 소규모 데이터에서 강하지만 KR 226개 종목 × 10년 규모에서 XGBoost와 유사.

---

### 1-2. TabPFN Survival Model

**파일**: `results/survival_pd_v4.json`  
**역할**: 시간축 위험 — "언제 위험해지는가" (XGBoost와 역할 분리)

**출력 필드 (종목별)**:
```json
{
  "hazard_pct": 0.32,
  "survival_1y": 0.78,
  "survival_3y": 0.61,
  "risk_label": "MODERATE"
}
```

**커버리지**: 226개 KR 종목

**단독 ROC**: 0.665 (현재연도 위험 예측에 부적합 — 시간축 모델이므로 당연)  
**XGBoost와의 차이**: XGB = "IF", Survival = "WHEN"  
→ 두 모델은 대체 관계가 아니라 보완 관계

---

## 2. Risk Engine

**파일**: `utils/risk_engine.py`

### 2-1. 앙상블 실험

**파일**: `scripts/risk_ensemble_comparison.py`  
**결과**: `results/risk_ensemble_report.json`

Walk-forward OOF (2019–2024) 기반 6가지 방법 비교:

| 방법 | ROC-AUC | P@20 | 결론 |
|---|---|---|---|
| XGB 단독 | 0.7803 | 0.9420 | 강력한 베이스라인 |
| Survival 단독 | 0.5140 | — | 현재연도 예측 부적합 |
| **XGB+Survival 70/30** | **0.7824** | **0.9509** | **최적 ← 채택** |
| XGB+Surv+Macro 70/20/10 | 0.7727 | — | Macro 추가 시 저하 |
| LR Meta Model (OOF) | 0.7831 | — | 개선 0.0028 — 유의성 의문 |
| Rank Aggregation (Borda) | 0.7609 | — | 확률값 정보 손실 최악 |

**채택 근거**:
- Survival hazard는 P@20 보완에 기여 (0.9420 → 0.9509)
- Macro regime는 composite score에 포함 시 노이즈 (ROC 저하)
- LR Meta Model의 ROC 0.0028 개선 → bootstrap CI 검증 미완, 단순 70/30이 더 안전

### 2-2. 가중치 및 점수 체계

```python
_W_XGB      = 0.70   # Layer 1
_W_SURVIVAL = 0.30   # Layer 2
_W_MACRO    = 0.00   # composite에서 제외

_ML_SCORE = {
    "INTACT":    15.0,
    "WEAKENING": 55.0,
    "BROKEN":    90.0,
}

# composite = xgb_score * 0.70 + surv_score * 0.30
# surv_score = hazard * 100
```

**risk_gate 임계값 (성향별)**:
```python
_GATE_BY_RISK = {
    "conservative": 50.0,
    "moderate":     65.0,
    "aggressive":   75.0,
}
# composite >= threshold → BLOCK
# composite >= 50       → WARN
# composite < 50        → PASS
```

**ETF 처리**: hazard 고정값 0.2 (Survival 모델 미적용)  
**US 주식**: hazard를 ml_status로 대리 측정 (INTACT→0.2, WEAKENING→0.5, BROKEN→0.8)

### 2-3. 50년+ 배당왕 캡

```python
if consecutive_years >= 50 and tier == "AT_RISK":
    tier = "BORDERLINE"
    score = max(score, 45)
```

적용 종목: KO(65년), MMM(65년), PFE, EXC, AEP → BORDERLINE으로 보호  
유지 AT_RISK: DUK, ES, XEL, D (50년 미만 or 재무 악화)

### 2-4. score_portfolio() 함수

```python
def score_portfolio(
    recommendations: list[dict],
    macro: dict | None = None,
    risk_tolerance: str = "moderate",
) -> list[dict]:
    # recommendations 각 항목에 아래 필드 추가:
    # composite_risk_score, risk_gate, layer1_xgb,
    # layer2_survival, layer3_macro, hazard, macro_regime
```

---

## 3. Pipe-and-Filter 파이프라인

**파일들**: `api/pipeline/context.py`, `api/pipeline/filters.py`, `api/pipeline/runner.py`

### 3-1. 필터 순서 (23개)

```
MacroRegimeFilter         # 2. 거시 레짐 (BULLISH/NEUTRAL/BEARISH)
AxisWeightFilter          # 1. 5축 비중 (Macro 반영)
AssetPickerFilter         # 3. KR/US/ETF 후보 선별
PersonalizedRankingFilter # 3-b. 개인화 랭킹 (목표수익률 역산)  ← 신규
WeightAllocatorFilter     # 4. 비중 배분
SurvivalWeightFilter      # 4-b. Survival hazard → 비중 보정
RiskEngineFilter          # 4-c. composite_risk_score 부착  ← 신규
SummarizeFilter           # 5. 세전/세후 수치 요약
ProjectionFilter          # 6. 20년 배당 성장 시뮬레이션
RebalancingFilter         # 7. 리밸런싱 플랜
StressTestFilter          # 8. 스트레스 테스트
SectorExposureFilter      # 9. 섹터 익스포저
CalendarFilter            # 10. 배당 캘린더
RiskAlertFilter           # 11. ISA + 리스크 경보
FireEngineFilter          # 12. FIRE 역산 (PMT 공식)
MonteCarloFilter          # 13. 1,000회 시뮬레이션  ← monthly_savings 추가
SurvivalFilter            # 13-b. 생존확률 헤드라인
TaxOptimizerFilter        # 14. 세금 최적화 (2026 세법)
BehavioralFinanceFilter   # 15. 행동편향 탐지
YieldTrapFilter           # 16. Yield Trap 감지
PortfolioHealthFilter     # 17. Health Score
SHAPExplainerFilter       # 18. Risk Attribution (Survival hazard 기반)
StorytellingFilter        # 19. 자연어 요약
```

### 3-2. PipelineContext 주요 필드

```python
@dataclass
class PortfolioRequest:
    age: int
    annual_income: int         # 만원
    monthly_target: int        # 목표 월배당 (만원)
    investable_amount: int     # 투자금 (만원)
    risk_tolerance: str        # conservative / moderate / aggressive
    archetype: str             # 혼합형 / 성장형 / 배당형 / 안정형
    monthly_savings: float     # 월 적립금 (만원)
    target_fire_age: int       # 목표 FIRE 나이

@dataclass
class PipelineContext:
    request: PortfolioRequest
    macro: dict                # MacroRegimeFilter 결과
    kr_stocks: list            # AssetPickerFilter 결과
    us_stocks: list
    etfs: list
    target_yield: float        # PersonalizedRankingFilter 역산값  ← 신규
    recommendations: list      # WeightAllocatorFilter 결과
    # + composite_risk_score 등 RiskEngineFilter 부착  ← 신규
    monte_carlo: dict          # monthly_savings 반영  ← 수정
    fire_plan: dict
    survival: dict
    tax_optimizer_result: dict
    # ... 20+ 필드
```

### 3-3. _to_response() 직렬화

`runner.py`에서 API 응답으로 변환. 추가된 필드:
```python
"target_yield": ctx.target_yield,   # 역산 목표수익률
# recommendations 각 항목에: composite_risk_score, risk_gate, ml_status, fit_score
```

---

## 4. 개인화 랭킹

**파일**: `utils/personalized_ranker.py` (301 lines)

### 4-1. 목표수익률 역산

```python
def _calc_target_yield(monthly_target, investable_amount, avg_growth_years=5):
    raw_yield = monthly_target * 12 / investable_amount * 100
    discount = (1.05 ** 5) ** 0.3   # 배당성장 부분 선반영
    adjusted = raw_yield / discount
    return max(1.0, min(20.0, adjusted))

# 예: 월150만원 / 4억 → 4.18%
```

### 4-2. fit_score 계산 (4가지 × 가중합)

```python
weights = {"yield": 0.40, "risk": 0.35, "age": 0.15, "growth": 0.10}

def _yield_fit_score(expected_yield, target_yield):
    diff = abs(expected_yield - target_yield)
    if diff <= 1.0: return 100
    if diff >= 5.0: return 0
    return round(100 - (diff - 1.0) / 4.0 * 100, 1)

def _risk_fit_score(composite_risk_score):
    return 100 - composite_risk_score

# age_fit: 나이 많을수록 안정 선호 가산
# growth_fit: 배당성장률 높을수록 가산
```

### 4-3. 선별 규칙

- 섹터당 최대 2개 (다양성)
- BLOCK 종목은 aggressive만 허용
- ETF 별도 슬롯 (n_etfs=2)

**검증**: 월150만/4억/moderate → 024800(fit=89.9) → 1위

---

## 5. US 안전성 분류

**파일**: `utils/us_dividend_data.py` (292 lines)

### 5-1. score_us_dividend_safety()

`us_dividend_dataset.csv` (87개 티커) 기반:
- FCF coverage ≥ 1.5 → +점수
- Payout ratio ≤ 60% → +점수
- OCF 양수 유지 → +점수
- 결과: SAFE / BORDERLINE / AT_RISK

### 5-2. ML status 매핑

```python
_tier_to_ml_status = {
    "SAFE":       "INTACT",
    "BORDERLINE": "WEAKENING",
    "AT_RISK":    "BROKEN",
}
```

### 5-3. pick_us_stocks_v2()

```python
# 필터링 순서:
# 1. type != "etf" (ETF 제외)
# 2. ml_status != "BROKEN" (AT_RISK 제외, aggressive 제외)
# 3. 50년+ 배당왕 캡 적용
# 4. fit_score 정렬 후 상위 n개
```

---

## 6. DART 증분 업데이트

**파일**: `scripts/dart_incremental.py` (313 lines)

### 6-1. 설계 결정

**year-based vs rcpNo-based**:
- rcpNo: 개별 공시 추적 (복잡, 복구 어려움)
- year-based: DART API가 연도 단위 → 단순하고 실패 복구 쉬움 → **채택**

### 6-2. 주요 함수

```python
def get_last_collected_years() -> dict[str, int]:
    # dividend_dataset.csv → {stock_code: max_year}

def collect_incremental_one(stock, last_year, start_year=2015, end_year=None):
    # collect_from = last_year + 1
    # last_year=None → 신규 종목 (전체 수집)

def append_to_dataset(new_rows):
    # (stock_code, year) 기준 중복 제거
    # 새 데이터 우선
    # sort by (stock_code, year) 후 저장

def run_incremental_update(force_full, ticker_filter, end_year):
    # APScheduler 호환 진입점
    # Checkpoint(data/dart_checkpoint.json)로 중단 복구
    # 반환: {updated, skipped, failed, duration_sec}
```

### 6-3. 현재 데이터 상태

- `data/dividend_dataset.csv`: 226개 종목, max_year 대부분 2025
- 대부분 최신 → 증분 수집 시 1건 예상

---

## 7. Monte Carlo

**파일**: `utils/monte_carlo.py`

### 7-1. 시그니처

```python
def run_monte_carlo(
    recommendations:  list[dict],
    investable_amount: float,
    years:             int   = 20,
    n_simulations:     int   = 1000,
    monthly_target:    float = 0.0,
    seed:              int   = 42,
    macro_regime:      dict  = None,
    monthly_savings:   float = 0.0,   # ← 이번 세션 추가
) -> dict
```

### 7-2. monthly_savings 복리 누적 (신규)

```python
annual_savings = monthly_savings * 12.0
total_invest = sum(a["invest"] for a in assets)
asset_weights = [a["invest"] / total_invest for a in assets]

# 루프 내:
current_invests[i] += annual_savings * asset_weights[i]  # 연말 적립
annual_gross = current_invests[i] * current_yields[i] / 100.0
```

**검증**: 월200만 적립 → 20년 P50 195만원 → 509만원 (복리 반영)

### 7-3. Macro Regime 연동

```python
_REGIME_CUT_MULTIPLIER = {
    "안정성장기": 0.7,   # p_cut × 0.7
    "금리상승기": 1.3,
    "경기침체기": 1.8,
    # BULLISH/NEUTRAL/BEARISH 매핑 포함
}
# confidence 가중 적용: multiplier = 1.0 + (raw_mult - 1.0) * confidence
```

### 7-4. 반환값

```python
{
    "p10_monthly": [...],   # 20개 연도별 P10 월배당
    "p50_monthly": [...],
    "p90_monthly": [...],
    "p10_final": float,
    "p50_final": float,
    "p90_final": float,
    "confidence_at_target": float,   # 목표 달성 확률 (%)
    "prob_doubles": float,
    "expected_cut_events": float,
    "summary_message": str,
}
```

---

## 8. 세금 최적화

**파일**: `utils/tax_optimizer.py`

### 8-1. 2026 세법 상수 (변경 금지)

```python
ISA_ANNUAL_LIMIT     = 4_000   # 만원 (구법 2,000의 2배)
ISA_TAX_FREE_GENERAL =   500   # 만원 (구법 200의 2.5배)
ISA_TAX_FREE_YOUTH   = 1_000   # 만원 (구법 400의 2.5배)
```

---

## 9. 백테스팅

**파일**: `utils/backtesting.py`

**내장 데이터**: 19개 티커 2015–2024 실제 수익률  
(SCHD/VYM/DGRO/JEPI/JEPQ/SPYD/HDV/NOBL/QYLD/KO/JNJ/PG/ABBV/MCD/O/VNQ/TLT/BND/AGG)

**반환값**:
```python
{
    "cagr_pct": float,
    "mdd_pct": float,
    "sharpe_ratio": float,
    "sortino_ratio": float,
    "calmar_ratio": float,
    "information_ratio_kospi": float,
    "information_ratio_sp500": float,
    "div_cagr_pct": float,
    "positive_years": int,
    "best_year": dict,      # {year, return_pct, value_만원, ...}
    "worst_year": dict,
    "vs_kospi_cagr": float,
    "vs_sp500_cagr": float,
    "benchmark": {"kospi_cagr": float, "sp500_cagr": float},
    "yearly_returns": [     # 연도별
        {year, return_pct, div_return_pct, value_만원,
         vs_kospi, vs_sp500, kospi_ret, sp500_ret}
    ],
    "grade": str,           # 우수/양호/보통/미흡
    "data_quality": dict,   # 실제 데이터 비율, 합성 데이터 출처
}
```

**API 엔드포인트**: `POST /api/portfolio/backtest`
```python
class BacktestRequest(BaseModel):
    portfolio: dict     # recommend 전체 결과 (내부에서 recommendations 추출)
    start_year: int = 2015
    end_year: int = 2024
```

---

## 10. 프론트엔드

**디렉토리**: `frontend/src/`

### 10-1. 컴포넌트 목록

| 컴포넌트 | 기능 | 상태 |
|---|---|---|
| `HealthRadarChart.jsx` | 6축 레이더 차트 | 완료 |
| `DividendCalendarHeatmap.jsx` | 월별 배당 히트맵 | 완료 |
| `MonteCarloChart.jsx` | P10/P50/P90 밴드 | 완료 |
| `CashflowMilestone.jsx` | FIRE 마일스톤 진행바 | 완료 |
| `BacktestChart.jsx` | 백테스팅 결과 차트 | **이번 세션 신규** |
| `YieldTrapWarning.jsx` | Yield Trap 경고 | 완료 |
| `PortfolioMonitor.jsx` | 포트폴리오 모니터 | 완료 |

### 10-2. BacktestChart.jsx 구조

```
상단: 제목 + 등급 배지 + summary_message
지표 카드 6개: CAGR, MDD, Sharpe, vs KOSPI, vs S&P500, 양봉연도
ComposedChart:
  - Bar: return_pct (양수=파랑 #2563eb, 음수=빨강 #dc2626)
  - Line: kospi_ret (회색 점선)
  - Line: sp500_ret (초록 점선)
  - 커스텀 툴팁: 해당 연도 전체 수치
하단: best_year / worst_year 배너 + 데이터 품질 주석
```

**API 호출 방식**:
```javascript
api.post('/portfolio/backtest', {
    portfolio: portfolio,   // 전체 recommend 결과
    start_year: startYear,
    end_year: endYear,
})
```

### 10-3. Portfolio.jsx — 이번 세션 추가

**target_yield 배너** (추천 섹션 상단):
```jsx
{tgtYield > 0 && (
  <div style={{ background: 'rgba(5,150,105,.06)', ... }}>
    🎯 역산 목표수익률 {tgtYield.toFixed(2)}%
    월 {monthly_target}만원 ÷ 투자금 {investable}만원으로 산출
  </div>
)}
```

**종목 카드 risk 표시** (각 holding card):
```jsx
// composite_risk_score 색상: 안전=초록, 주의=주황, 위험=빨강
<span>위험 {Math.round(crs)} · {gateLabel}</span>
<span>ML:{mlLabel}</span>          // INTACT/WEAK/BROKEN
<span>적합도 {fit_score.toFixed(0)}점</span>
<span>배당 {expected_yield.toFixed(1)}%</span>

// BLOCK 종목: 카드 테두리 빨간색 (#fca5a5)
```

**종목 카드 추천 이유** (세션2 추가):
```jsx
// recommendation_reason: "왜 이 종목이 선택됐는가" 문장 (파란색)
{r.recommendation_reason && (
  <div style={{ color: '#1456f0', fontSize: 11 }}>
    💡 {r.recommendation_reason}
  </div>
)}

// 적합도 컴포넌트 pill (0-100 스케일 수정):
// v >= 70 → 초록, 40~70 → 주황, < 40 → 빨강
// Math.round(v) (×100 제거 — 버그 수정)
```

---

## 11. 테스트

**디렉토리**: `tests/`

| 파일 | 대상 | 주요 테스트 클래스 |
|---|---|---|
| `test_fire_engine.py` | `calc_fire_engine()` | ReturnStructure, MathAccuracy, EdgeCases, FireTimeline |
| `test_monte_carlo.py` | `run_monte_carlo()` | QuantileOrdering, ProbabilityBounds, MacroRegimeEffect, Reproducibility |
| `test_tax_optimizer.py` | `calc_tax_optimizer()` | **TaxLawConstants2026** (4000/500/1000 고정), ISA2026InResult |
| `test_behavioral_finance.py` | `detect_behavioral_biases()` | HomeBias, ConcentrationBias, YieldIllusion, ExcessiveSafety |
| `test_backtesting.py` | `run_backtest()` | CAGR, MDD, Sharpe, BenchmarkComparison |
| `test_pipeline_runner.py` | `RecommendationPipeline` | TestPipelineContext, TestPipelineWithVariousInputs |

**실행**:
```bash
cd ~/ai-analyst
pytest tests/ -v --tb=short
```

---

## 12. API 엔드포인트

| 메서드 | 경로 | 기능 |
|---|---|---|
| POST | `/api/portfolio/recommend` | 전체 파이프라인 실행 |
| POST | `/api/portfolio/backtest` | 백테스팅 |
| GET | `/api/stock/{ticker}` | 단일 종목 조회 |
| GET | `/api/ranking` | 전체 랭킹 |

---

## 13. 데이터 파일

| 파일 | 내용 | 크기 |
|---|---|---|
| `data/dividend_dataset.csv` | KR 226종목 재무데이터 2015-2025 | ~3,000행 |
| `data/ranking.csv` | 종목 랭킹 + ML 점수 | 226행 |
| `data/approved_universe.json` | 4축 투자 유니버스 | — |
| `data/ml_scoring_results.csv` | XGBoost 예측 결과 | 226행 |
| `data/us_dividend_dataset.csv` | US 87개 티커 안전성 | 87행 |
| `results/survival_pd_v4.json` | TabPFN survival 결과 | 226개 종목 |
| `results/risk_ensemble_report.json` | 앙상블 비교 실험 결과 | — |
| `models/kr_3class_model.pkl` | XGBoost 모델 (삭제 금지 — 벤치마크) | — |

---

## 14. 코딩 규칙

### 한국어 인코딩
Python 파일에 한국어 포함 시 bash heredoc 사용:
```bash
python3 - << 'EOF'
# 한국어 포함 코드
EOF
```

### DB-First + 파일 폴백
```python
try:
    # 1. DB 먼저
    with Session(engine) as session:
        ...
except Exception:
    # 2. 파일 폴백
    json.load(open("data/ml_scores.json"))
```

### 필터 에러 핸들링
```python
# runner.py — 필터 예외 발생해도 파이프라인 계속
try:
    filt.process(self.ctx)
except Exception as exc:
    log.error("Pipeline step %s failed: %s", filt.name, exc)
    self.ctx.add_error(filt.name, str(exc))
```

---

## 15. 빠른 시작

```bash
# 서버 실행
cd ~/ai-analyst
uvicorn api.main:app --reload --port 8000

# 프론트엔드
cd frontend && npm run dev

# 테스트
pytest tests/ -v --tb=short

# DART 증분 업데이트
python scripts/dart_incremental.py

# Risk Engine CLI 테스트
python utils/risk_engine.py
```

---

## 16. 남은 작업 (발표 전)

| 우선순위 | 작업 | 상태 | 예상 시간 |
|---|---|---|---|
| 🔴 필수 | 실서버 기동 + `scripts/test_e2e.py` E2E 확인 | 미완 (서버 직접 기동 필요) | 30분 |
| 🔴 필수 | 3개 시나리오 개인화 검증 (25/40/60세) | 미완 | 20분 |
| 🟡 선택 | US 캐시 갱신 (`fetch_us_data(force=True)`) | 미완 | 10분 |
| 🟢 완료 | `recommendation_reason` 개인화 + risk attribution | ✅ 세션2 완료 | — |
| 🟢 완료 | `fit_score` 스케일 버그 수정 (0-100 통일) | ✅ 세션2 완료 | — |
| 🟢 완료 | DART 증분 watcher (`utils/dart_watcher.py`) | ✅ 세션1 완료 | — |
| 🟢 나중 | MPT 효율적 프론티어 (Task #23) | — | 3시간 |
| 🟢 나중 | LLM AI Advisor 실연동 (Task #24) | — | 2시간 |

### 발표 전 마지막 체크리스트 (서버에서 직접)

```bash
# 1. 서버 기동
cd ~/ai-analyst
uvicorn api.main:app --reload --port 8000

# 2. E2E 검증 (별도 터미널)
python scripts/test_e2e.py

# 기대 출력:
# ✅ 완료 (X.Xs)
# 종목 4-5개, fit_score 존재, BLOCK 없음
# P10/P50/P90 시나리오별 다름
# 개인화 검증: 시나리오별 추천이 70%+ 다름

# 3. US 캐시 갱신
python -c "from utils.us_dividend_data import fetch_us_data; fetch_us_data(force=True)"

# 4. 프론트엔드 확인
cd frontend && npm run dev
# http://localhost:5173 → 데모 시나리오 입력 후 recommendation_reason 표시 확인
```

---

## 17. 발표 대응 예상 질문 & 답변

**Q: 왜 XGBoost인가?**  
A: Walk-forward ROC 0.799. LightGBM/CatBoost/TabPFN/LR/RF 5개 대안 검토. 재무제표 결측값이 많은 환경에서 XGBoost의 내재적 결측 처리가 유리. 소규모(226종목)에서 TabPFN과 유사 성능이나 XGBoost가 해석성 우월.

**Q: 왜 Survival을 30%만 반영하는가?**  
A: 앙상블 실험 결과. Survival 단독 ROC 0.514 — 현재연도 위험 예측에 부적합. 그러나 P@20 기준 70/30이 단독 대비 +0.89%p 개선. Survival의 역할은 "시간축", XGBoost의 역할은 "현재 상태"이므로 70/30이 자연스러운 비율.

**Q: 왜 Macro를 composite에서 빼는가?**  
A: 실험 결과 Macro 추가 시 ROC 0.7824 → 0.7727로 저하. Macro는 "시장 환경" 정보이지 "개별 종목 재무 건전성" 정보가 아니라 노이즈로 작용. Macro는 ETF 비중 조정(AxisWeightFilter)과 Monte Carlo p_cut 조정(1.8× in 경기침체기)에서만 사용.

**Q: 50년 배당왕을 왜 BROKEN으로 분류하지 않는가?**  
A: 도메인 지식 기반 보정. 65년 연속 배당 이력은 재무 지표 단기 악화보다 강한 배당 지속 의지를 반증. KO의 2024-2025 FCF 압박은 일시적. ML 모델의 한계(과거 재무 데이터만 봄)를 도메인 지식으로 보완.

**Q: DART 데이터는 실시간인가?**  
A: pykrx 차단으로 실시간 주가 수익률 미사용. DART API 기반 재무데이터(분기/연간)를 `dart_incremental.py`로 증분 수집. 배당수익률은 DART DPS + 정적 캐시 기반 계산.

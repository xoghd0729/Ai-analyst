# AI 기반 배당·포트폴리오 최적화 시스템 v2.0

> Team FinSight

> **"50세에 월 200만원 받으려면 지금 얼마를 투자해야 하나?"**  
> 목표 월배당을 역산해 포트폴리오를 설계·분석·방어·관리하는 로컬 AI 운영체제.

---

## 핵심 기능

| 기능 | 설명 |
|------|------|
| **포트폴리오 추천** | 나이·투자금·목표 월배당 입력 → 18단계 Pipe-and-Filter 파이프라인 |
| **FIRE 역산 엔진** | PMT 공식 기반 린/일반/팻 FIRE 달성 나이·필요 적립금 계산 |
| **Monte Carlo** | 1,000회 시뮬레이션 → P10/P50/P90 밴드, 거시 레짐 연동 |
| **MPT 효율적 프론티어** | 샤프 비율 최대 포트폴리오 최적화 (5,000 랜덤 샘플링) |
| **백테스팅** | 2015–2024 연도별 CAGR/MDD/Sharpe + KOSPI/S&P500 비교 |
| **절세 최적화** | 2026 세법 반영 (ISA 연 4,000만원 한도, 비과세 500/1,000만원) |
| **행동 편향 탐지** | 홈바이어스·집중편향·수익률 착시 등 8가지 진단 |
| **AI Portfolio Advisor** | Ollama 로컬 LLM (qwen3:14b) — OpenAI/Claude 의존성 없음 |
| **포트폴리오 비교** | A/B 입력 → 레이더 차트 + 지표 비교 테이블 |
| **배당 달력 히트맵** | 12개월 배당 입금 시각화 |
| **Survival 리스크 모델** | 배당 삭감 위험 예측 (한국 배당주) |

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| **API 서버** | FastAPI (uvicorn) |
| **분석 파이프라인** | Pipe-and-Filter 패턴, 18개 Filter |
| **리스크 모델** | Survival 모델 (`utils/shap_explainer.py`) |
| **로컬 LLM** | Ollama — qwen3:14b |
| **DB** | PostgreSQL (SQLAlchemy ORM) + JSON/CSV 폴백 |
| **프론트엔드** | React + Recharts + Vite |
| **테스트** | pytest (289 passed) |
| **데이터 (한국)** | DART OpenAPI (pykrx 미사용 — KRX 차단) |
| **데이터 (미국)** | 정적 캐시 기반 (yfinance 실시간 미사용) |

---

## 실행 방법

### 사전 준비

```bash
cd ~/ai-analyst
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt --break-system-packages
```

### AI Advisor용 Ollama 설치 (선택)

```bash
# Ollama 설치: https://ollama.com
ollama pull qwen3:14b
ollama serve   # 백그라운드 실행
```

Ollama 미실행 시 rule-based fallback 분석으로 자동 전환됩니다.

### 서버 실행

```bash
# 백엔드 (포트 8000)
cd ~/ai-analyst
uvicorn api.main:app --reload --port 8000

# 프론트엔드 (포트 5173)
cd frontend && npm run dev
```

브라우저에서 `http://localhost:5173` 접속.

---

## 주요 API 엔드포인트

| 엔드포인트 | 설명 |
|-----------|------|
| `POST /api/portfolio/recommend` | 포트폴리오 추천 (18단계 파이프라인) |
| `POST /api/portfolio/backtest` | 백테스팅 (2015–2024) |
| `POST /api/portfolio/optimize` | MPT 효율적 프론티어 |
| `POST /api/portfolio/fire-reverse` | FIRE 역산 |
| `POST /api/portfolio/advisor` | AI 분석 (use_llm: true/false) |
| `POST /api/portfolio/compare` | A/B 포트폴리오 비교 |
| `GET  /api/stock/{code}` | 종목 상세 (Survival 리스크 포함) |

---

## 파이프라인 흐름

```
POST /api/portfolio/recommend
    ↓
[MacroRegimeFilter]   — 거시 레짐 판단 (금리/물가 국면)
[AxisWeightFilter]    — 4축 가중치 조정
[AssetPickerFilter]   — 종목 선택
[WeightAllocatorFilter] — 비중 배분
[SummarizeFilter]     — 현금흐름 요약
[ProjectionFilter]    — 배당 성장 예측
[RebalancingFilter]   — 리밸런싱 전략
[StressTestFilter]    — 스트레스 테스트
[SectorExposureFilter] — 섹터 노출도
[CalendarFilter]      — 배당 달력
[RiskAlertFilter]     — 리스크 경보
[FireEngineFilter]    — FIRE 역산
[MonteCarloFilter]    — 1,000회 Monte Carlo (Macro 연동)
[TaxOptimizerFilter]  — 2026 세법 절세
[BehavioralFinanceFilter] — 행동 편향
[PortfolioHealthFilter] — 건강도 점수
[SHAPExplainerFilter] — Survival 리스크 설명
[StorytellingFilter]  — 자연어 요약
    ↓
JSON 응답
```

---

## 프로젝트 구조

```
ai-analyst/
├── api/
│   ├── main.py                    # FastAPI 앱, 라우터 등록
│   ├── pipeline/
│   │   ├── context.py             # PipelineContext, PortfolioRequest
│   │   ├── base.py                # BaseFilter 추상 클래스
│   │   ├── filters.py             # 18개 Filter 구현
│   │   └── runner.py              # RecommendationPipeline.execute()
│   └── routers/
│       ├── portfolio.py           # /recommend /backtest /optimize /compare /advisor
│       ├── stock.py               # /stock/* (종목 상세, Survival 예측)
│       └── ranking.py             # /ranking
├── utils/
│   ├── fire_engine.py             # FIRE 역산 (PMT 공식)
│   ├── monte_carlo.py             # P10/P50/P90 시뮬레이션 (Macro 연동)
│   ├── tax_optimizer.py           # 2026 세법, ISA/연금 절세
│   ├── behavioral_finance.py      # 8가지 행동편향 탐지
│   ├── backtesting.py             # CAGR/MDD/Sharpe (2015–2024 내장 데이터)
│   ├── shap_explainer.py          # Survival 리스크 모델 + SHAP 대체 설명
│   ├── portfolio_optimizer.py     # MPT 효율적 프론티어
│   ├── advisor_service.py         # AI Portfolio Advisor (Ollama 연동)
│   ├── macro_regime.py            # 거시 레짐 판단
│   ├── storytelling.py            # 자연어 요약 생성
│   ├── dividend_projection.py     # 배당 성장 예측
│   └── ollama_client.py           # Ollama HTTP 클라이언트
├── db/
│   ├── models.py                  # SQLAlchemy ORM
│   └── repository.py              # DB-first + 파일 폴백 패턴
├── models/
│   └── kr_3class_model.pkl        # XGBoost (벤치마크 보존용 — 런타임 미사용)
├── frontend/src/
│   ├── pages/Portfolio.jsx        # 메인 포트폴리오 결과 페이지
│   └── components/
│       ├── HealthRadarChart.jsx
│       ├── DividendCalendarHeatmap.jsx
│       ├── MonteCarloChart.jsx
│       ├── CashflowMilestone.jsx
│       ├── BacktestChart.jsx
│       ├── EfficientFrontierChart.jsx
│       ├── InteractiveSimulator.jsx
│       ├── AdvisorPanel.jsx
│       └── CompareView.jsx
└── tests/
    ├── test_fire_engine.py
    ├── test_monte_carlo.py
    ├── test_tax_optimizer.py
    ├── test_behavioral_finance.py
    ├── test_backtesting.py
    └── test_pipeline_runner.py
```

---

## 테스트

```bash
cd ~/ai-analyst
pytest tests/ -v --tb=short
# 289 passed
```

---

## 환경변수 (.env)

```
DATABASE_URL=postgresql://user:pass@localhost/dbname
DART_API_KEY=your_dart_api_key
```

DART API 키 없이도 정적 캐시 데이터로 실행 가능.

---

## 설계 원칙

- **로컬 우선**: Ollama 로컬 LLM — OpenAI/Claude/Gemini API 의존성 없음
- **pykrx 미사용**: KRX 차단으로 수익률은 DART/정적 캐시 기반
- **XGBoost 런타임 호출 없음**: 배당 삭감 예측은 Survival 모델로 전환 (kr_3class_model.pkl은 벤치마크용 보존)
- **DB-first + 파일 폴백**: PostgreSQL 없이도 JSON/CSV로 동작
- **2026 세법 고정**: ISA 연 납입 4,000만원 / 일반형 비과세 500만원 / 청년형 1,000만원

---

## 검증 결과 (E2E)

| 항목 | 상태 |
|------|------|
| `/recommend` | ✅ |
| `/advisor` fallback (rule-based) | ✅ |
| `/advisor` Ollama qwen3:14b | ✅ (약 74초) |
| `/backtest` | ✅ |
| `/optimize` (MPT) | ✅ |
| `/fire-reverse` + Simulator | ✅ |
| `/compare` + CompareView | ✅ |
| 서버 오프라인 에러 UI | ✅ (흰 화면 없음) |
| pytest 289 passed | ✅ |
| XGBoost 런타임 호출 | ✅ 0건 |

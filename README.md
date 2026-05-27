# AI 배당주 분석 시스템

한국·미국 고배당주의 배당 안정성을 자동 분석하고, ML 기반으로 배당 삭감 위험을 예측하는 시스템.

## 기술 스택

| 구분 | 기술 |
|------|------|
| LLM (Thesis) | LLaMA 3.3 70B (Groq API) |
| ML (리스크) | XGBoost — 배당 삭감 확률 예측 |
| DB | PostgreSQL + SQLAlchemy |
| 데이터 (한국) | DART OpenAPI, pykrx, Naver Finance |
| 데이터 (미국) | yfinance |
| 프론트엔드 | React + Vite |
| 백엔드 API | FastAPI |

## 분석 유니버스

- **한국**: KRX 고배당 50 지수
- **미국**: S&P 500 Dividend Aristocrats (배당귀족주)

## 프로젝트 구조

```
ai-analyst/
│
├── api/                        # FastAPI 백엔드
│   ├── main.py                 # 앱 진입점 (uvicorn api.main:app)
│   └── routers/                # 엔드포인트별 라우터
│       ├── stock.py            # /api/stock/* (종목 상세, thesis, ML)
│       ├── ranking.py          # /api/ranking (랭킹 조회)
│       └── portfolio.py        # /api/portfolio/* (포트폴리오 관리)
│
├── agents/                     # AI 에이전트
│   ├── thesis_agent.py         # Thesis 생성 (INTACT/WEAKENING/BROKEN 판정)
│   └── news_agent.py           # 뉴스 기반 이벤트 감지
│
├── analyzers/                  # 분석 모듈
│   ├── scorer.py               # Thesis 점수화 (0~100)
│   ├── simulator.py            # 배당 시뮬레이션
│   └── yield_trap.py           # Yield Trap 룰 엔진
│
├── auto_discovery/             # 종목 자동 발굴
│   ├── orchestrator.py         # 발굴 파이프라인 조율
│   ├── screener_kr.py          # 한국 종목 스크리닝
│   ├── screener_us.py          # 미국 종목 스크리닝
│   └── evaluator.py            # 발굴 종목 평가
│
├── collectors/                 # 데이터 수집기
│   ├── dart.py                 # DART 재무제표 (한국)
│   ├── dividend.py             # 배당 이력 수집
│   ├── fetch_dps_history.py    # 주당배당금(DPS) 히스토리
│   ├── financials_us.py        # 미국 재무지표 (yfinance)
│   ├── llm.py                  # LLM 호출 유틸
│   ├── macro.py                # 매크로 지표 수집
│   ├── naver.py                # Naver Finance 수집
│   ├── news_cache.py           # 뉴스 캐시 관리
│   ├── news_kr.py              # 뉴스 수집 (한국/미국 공통)
│   └── price.py                # 주가 수집
│
├── data/                       # 데이터 파일 (CSV)
│   ├── dividend_dataset.csv    # 한국 XGBoost 학습 데이터
│   ├── us_dividend_dataset.csv # 미국 XGBoost 학습 데이터
│   ├── us_reit_dataset.csv     # 미국 REIT 학습 데이터 (별도 모델)
│   ├── ranking.csv             # 랭킹 캐시
│   └── news_event_cache.json   # 뉴스 이벤트 캐시
│
├── db/                         # DB 마이그레이션 스크립트
│   ├── init_db.py              # 테이블 초기 생성
│   ├── add_thesis_history.py   # thesis_history 테이블 추가
│   └── add_actions_table.py    # actions 테이블 추가
│
├── frontend/                   # React 프론트엔드
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx   # 메인 대시보드 (랭킹 목록)
│   │   │   └── StockDetail.jsx # 종목 상세 (Thesis + ML + Timeline)
│   │   └── ...
│   └── package.json
│
├── models/                     # 학습된 ML 모델
│   └── dividend_cut_model.pkl  # 한국 XGBoost 모델
│
├── results/                    # 모델 평가 결과
│   ├── feature_importance.json
│   ├── model_evaluation.png
│   └── prediction_result.csv
│
├── utils/                      # 공통 유틸리티
│   ├── etf_quality.py          # ETF 품질 평가
│   ├── ollama_client.py        # Ollama LLM 클라이언트
│   └── universe.py             # 종목 유니버스 정의
│
├── build_dataset.py            # 한국 XGBoost 학습 데이터 생성
├── build_us_dataset.py         # 미국 XGBoost 학습 데이터 생성
├── train_model.py              # 한국 XGBoost 모델 학습
├── run_thesis_batch.py         # 배치 분석 실행 (한국/미국)
├── run_all.py                  # 전체 파이프라인 실행
│
├── .env                        # 환경변수 (git 제외)
├── .gitignore
└── ROADMAP.md                  # 개발 로드맵
```

## ML 모델 구조

```
종목 입력
  ├── 한국 주식 → KR XGBoost (dividend_cut_model.pkl)
  ├── 미국 주식 → US Rules-based (train_us_model.py 학습 예정)
  └── ETF       → Rules-based (payout 구조 상이)
         ↓
    리스크 점수 (0.0 ~ 1.0) → INTACT / WEAKENING / BROKEN
```

## 실행 방법

### 서버 시작
```bash
# 백엔드 API
uvicorn api.main:app --reload --port 8000

# 프론트엔드
cd frontend && npm run dev
```

### 데이터 수집 & 분석 배치
```bash
# 한국 전체 분석
python run_thesis_batch.py --kr-only

# 미국 전체 분석 (상위 20개)
python run_thesis_batch.py --us-only --top 20

# 한/미 모두
python run_thesis_batch.py
```

### ML 모델 학습
```bash
# 한국 데이터셋 생성
python build_dataset.py

# 한국 모델 학습
python train_model.py

# 미국 데이터셋 생성 (2022~2025, yfinance 4년 데이터)
python build_us_dataset.py --from-year 2022
```

## 환경변수 (.env)

```
DATABASE_URL=postgresql://...
DART_API_KEY=...
GROQ_API_KEY=...
```

## 파이프라인 흐름

```
1. 데이터 수집
   ├── 주가          (pykrx / yfinance)
   ├── 재무제표      (DART / yfinance)
   └── 뉴스          (Naver / yfinance)
         ↓
2. 지표 계산
   ├── FCF, 배당성향, 커버리지
   └── DPS YoY 증감률
         ↓
3. Yield Trap 룰 엔진
         ↓
4. AI Thesis 생성 (Groq LLaMA 3.3 70B)
         ↓
5. ML 리스크 스코어링 (XGBoost)
         ↓
6. 최종 판정: INTACT / WEAKENING / BROKEN
         ↓
7. DB 저장 → API → 프론트엔드 렌더링
```

# 프로젝트 컨텍스트 (AI 세션 시작용)

## 한 줄 요약
한국·미국 고배당주의 배당 삭감 위험을 XGBoost + LLM으로 분석하는 풀스택 시스템.

## 스택
- Backend: FastAPI (`uvicorn api.main:app --reload --port 8000`)
- Frontend: React + Vite (`cd frontend && npm run dev`)
- DB: PostgreSQL (`ai_analyst` 데이터베이스)
- ML: XGBoost (`models/dividend_cut_model.pkl` KR, `models/us_dividend_cut_model.pkl` US)
- LLM: Groq API — LLaMA 3.3 70B (Thesis 생성)
- 한국 데이터: DART API, pykrx
- 미국 데이터: yfinance

## 현재 파일 구조
```
ai-analyst/
├── api/main.py                  # FastAPI 진입점
├── agents/
│   ├── thesis_agent.py          # LLM → INTACT/WEAKENING/BROKEN 판정
│   └── news_agent.py
├── analyzers/
│   ├── scorer.py
│   ├── simulator.py
│   └── yield_trap.py
├── auto_discovery/              # 종목 자동 발굴
├── collectors/
│   ├── dart.py                  # 한국 재무제표
│   ├── financials_us.py         # 미국 재무지표 (yfinance)
│   └── news_kr.py               # 한/미 뉴스 수집
├── data/
│   ├── dividend_dataset.csv     # KR 학습 데이터 (70종목, 698행, 2013~2025)
│   ├── us_dividend_dataset.csv  # US 학습 데이터 (87종목, 347행, 2022~2025)
│   └── us_reit_dataset.csv      # REIT 별도 (28행)
├── models/
│   ├── dividend_cut_model.pkl           # KR XGBoost (sklearn Pipeline)
│   └── us_dividend_cut_model.pkl        # US XGBoost (bundle: pipeline+feature_names+threshold)
├── build_dataset.py             # KR 학습 데이터 생성
├── build_us_dataset.py          # US 학습 데이터 생성 (--from-year 2022)
├── train_model.py               # KR 모델 학습
├── train_us_model.py            # US 모델 학습
├── run_thesis_batch.py          # 배치 분석 (--kr-only / --us-only / --top N)
└── run_all.py                   # 전체 파이프라인
```

## 핵심 로직 흐름
```
run_thesis_batch.py 실행
  → collectors/financials_us.py  (US 재무지표 수집 → DB)
  → collectors/news_kr.py        (뉴스 수집)
  → get_ml_risk()                (KR: XGBoost pkl / US: us_dividend_cut_model.pkl)
  → agents/thesis_agent.py       (Groq LLaMA → thesis 생성)
  → DB 저장 (thesis_history 테이블)
  → API → 프론트엔드
```

## 알려진 문제 / 주의사항

### US 모델 AUC=1.0 (과적합)
- 원인: 347행에 삭감 13건(3.7%)만 있어서 모델이 외움
- 현재 상태: 학습은 됐지만 실제 예측력 미검증
- 해결 방향: 2025년 데이터를 홀드아웃으로 분리하여 테스트

### US 학습 데이터 부족
- yfinance 연간 재무제표는 최근 4년만 제공 → 2022~2025
- 87종목 × 4년이 현실적 최대치

### KR/US 모델 분리 이유
- payout 정상 범위: KR 30~40% / US 40~70% (다른 기준)
- 재무수치 단위: KR 억원 / US USD (90,000배 차이)
- 한국 모델로 미국 주식 추론 시 항상 BROKEN 오판 발생

## US 모델 추론 시 피처 순서 (중요)
```python
# models/us_dividend_cut_model.pkl 로드 방법
bundle = joblib.load("models/us_dividend_cut_model.pkl")
pipeline     = bundle["pipeline"]       # sklearn Pipeline
feature_names = bundle["feature_names"] # 컬럼 순서 고정됨
threshold    = bundle["threshold"]      # 0.3

# 피처 목록 (이 순서대로 DataFrame 만들어야 함)
# ['payout_ratio', 'dividend_coverage', 'dps_yoy_pct', 'div_to_ocf',
#  'fcf_negative', 'shareholder_yield', 'net_debt_ebitda', 'consecutive_years',
#  'payout_over_100', 'payout_over_80', 'dps_declining']
X_df = pd.DataFrame([{c: row.get(c) for c in feature_names}])
prob = pipeline.predict_proba(X_df)[:, 1][0]
```

## 환경변수 (.env)
```
DATABASE_URL=postgresql://localhost/ai_analyst
DART_API_KEY=...
GROQ_API_KEY=...
```

## 지금 당장 해야 할 것 (우선순위 순)
1. `python train_us_model.py` 재실행 — JSON 저장 에러 fix됨, 모델 자체는 이미 저장 완료
2. `python run_thesis_batch.py --us-only --top 5` — US 모델 실제 추론 확인
3. US 모델 검증 — 2025년 데이터 홀드아웃 테스트 (AUC=1.0 원인 규명)
4. 캡스톤 보고서 작성

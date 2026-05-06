# AI 배당주 스코어링 시스템

한국·미국 고배당주를 자동 분석해 배당 안정성을 점수화하고 포트폴리오 구성 근거를 제공하는 시스템.

## 기술 스택
- **LLM**: LLaMA 3.3 70B (Groq API) — Thesis 생성, 스코어링, 판정
- **ML**: XGBoost — 배당 삭감 확률 예측
- **DB**: PostgreSQL + SQLAlchemy
- **데이터**: DART OpenAPI, pykrx, yfinance

## 분석 유니버스
- 한국: KRX 고배당 50 지수
- 미국: S&P 500 Dividend Aristocrats

## 파이프라인
1. 데이터 수집 (주가 / 재무제표 / 뉴스)
2. 배당 지표 계산 (FCF, 배당성향, 커버리지)
3. Yield Trap 룰엔진 (위험 신호 감지)
4. AI Thesis 생성
5. Thesis Scoring (0~100점)
6. 최종 판정 (유지 / 약화 / 붕괴)
7. 포트폴리오 비교 분석

## 실행
```bash
# 초기 설정 (최초 1회)
python init_corp_codes.py

# 분석 실행
python main.py
```

## 환경변수 (.env)
```
DART_API_KEY=
GROQ_API_KEY=
```

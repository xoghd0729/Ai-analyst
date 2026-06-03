# 데이터 풀 투자 주간 (5/28 ~ 6/3, 7일)

> 결정 배경: 시스템의 진짜 약점은 코드가 아니라 **데이터 품질**.
> 백테스팅 신뢰도·매크로 정확도·종목 다양성을 한 주에 끌어올린다.
> 발표(6/10)까지 6/4~6/9는 보고서·슬라이드·리허설 시간으로 남겨둠.

---

## 핵심 원칙

1. **정직성 우선** — 합성 데이터는 명시적으로 합성임을 표시, fallback 의존 줄이기
2. **자동화 우선** — 매일 cron으로 갱신되는 파이프라인이 핵심
3. **품질 게이트** — 잘못된 데이터가 추천에 들어가는 사고 방지
4. **검증 가능성** — 각 단계마다 정량 메트릭으로 개선 확인

---

## 7일 일별 (5/28 수 ~ 6/3 화)

### D1 (5/28 수) — Layer 1: 합성 데이터 정직화

**목표**: SCHD·DGRO·JEPI 등의 상장 이전 데이터를 "유사 ETF 합성"으로 명시화

**왜 가장 먼저인가**: 백테스팅 신뢰도가 모든 시스템 결과의 기반. 합성된 줄도 모르고 사용하면 잘못된 결론 도출.

**작업 항목**:
1. `utils/backtesting.py` 의 `_ASSET_HIST_RETURNS`에 합성 매핑 메타데이터 추가
   - 각 종목마다 `inception_year` 명시
   - 상장 이전 연도는 `(synthetic: 선행 ETF 티커)` 형태로 표시
2. `scripts/fetch_historical_returns.py` 신규 — 실제 yfinance 데이터 수집
   - SCHD 대용: SCHX (2009~), SDY (2005~), DVY (2003~)
   - DGRO 대용: VIG (2006~)
   - JEPI/JEPQ: 단일 ETF만 사용 (대용 없음)
3. `utils/backtesting.py` 응답에 `data_quality` 필드 추가
   - `{"real_years": 15, "synthetic_years": 6, "synthetic_sources": ["SCHX"]}`
4. 프론트엔드 `BacktestChart.jsx`의 합성 주석을 동적으로 (현재는 하드코딩)

**완료 기준**: `python -c "from utils.backtesting import run_backtest; r=run_backtest([{'ticker':'SCHD','weight':1.0}]); print(r['data_quality'])"`

---

### D2 (5/29 목) — Layer 1: yfinance Fallback 제거 + 한국 종목 백필

**목표**: 네트워크 의존 줄이기, 정적 데이터 신뢰도 ↑

**작업 항목**:
1. `_KOSPI_RETURNS_FALLBACK_2005_2024` / `_SP500_RETURNS_FALLBACK` 의 실제 데이터 검증
   - 한국거래소 공식 통계와 대조해 정정
   - 출처 주석 명시
2. 한국 종목 60+ 중 누락 연도 있는 종목 식별 → pykrx로 강제 백필
   - `scripts/backfill_kr_history.py` 신규
3. 누락 데이터 비율 < 5% 종목만 백테스팅 대상으로 강제
4. `data/historical_coverage_report.json` 생성 — 종목별 데이터 가용 연수

**완료 기준**: `data/historical_coverage_report.json` 안 평균 가용 연수 ≥ 18

---

### D3 (5/30 금) — Layer 3: 매크로 일별 파이프라인 (신규)

**목표**: 5개 시리즈 일별 데이터를 매일 자동 수집·저장

**작업 항목**:
1. `utils/macro_data.py` 신규 작성
   - `fetch_bok_rate(start='2005-01-01')` — 한국은행 ECOS API
   - `fetch_treasury_10y(start='2005-01-01')` — yfinance ^TNX
   - `fetch_usd_krw(start='2005-01-01')` — yfinance KRW=X
   - `fetch_vix(start='2005-01-01')` — yfinance ^VIX
   - `fetch_kospi_per(start='2005-01-01')` — KRX (pykrx)
2. 결과를 `data/macro_daily.parquet` 으로 저장 (pyarrow)
3. `detect_regime_at(date)` — 특정 일자의 4분면 레짐 자동 판단
4. `requirements.txt`에 `pyarrow>=14.0`, `fredapi>=0.5.1` 추가
5. `.env`에 `BOK_API_KEY` 항목 추가 가이드

**의존성 추가**: pyarrow, fredapi (선택)

**완료 기준**: `python -c "import pandas as pd; df=pd.read_parquet('data/macro_daily.parquet'); print(len(df), df.columns.tolist())"`

---

### D4 (5/31 토) — Layer 3: 매크로 → MacroRegime 연동

**목표**: 정성 판단 → 정량 자동 판단으로 교체

**작업 항목**:
1. `utils/macro_regime.py` 의 정성 판단 함수와 `macro_data.py` 통합
   - 기존 시그니처 유지 (API 호환)
   - 내부적으로 `detect_regime_at(today)` 호출
2. 레짐 변화 추적: `data/regime_history.json`
   - 일별 레짐 + 이전 레짐에서 변화 시점 기록
3. `MonteCarloFilter` 연동: 레짐별 배당 삭감 확률 (`_REGIME_CUT_MULTIPLIER`) 명시화
   - 경기침체 ×1.8, 금리상승 ×1.3, 안정성장 ×0.7
4. `utils/data_pipeline.py` 의 APScheduler 에 매일 18:00 매크로 갱신 cron 추가
5. 회귀 테스트: `tests/test_macro_regime.py` — 5개 레짐 시나리오 검증

**완료 기준**: `pytest tests/test_macro_regime.py -v` 통과

---

### D5 (6/1 일) — Layer 2: 종목·ETF 대규모 확장

**목표**: 한국 65→100+, ETF 10→20, 미국 19→30+

**작업 항목**:
1. `scripts/collect_kr_dividend_stocks.py` 시드 확장
   - 현재 125개 시드 → 250개로 확장 (코스피200 + 코스닥150 합집합)
   - 필터링 후 100+ 통과 목표
2. 한국 ETF 추가 10개 (현재 10개 → 20개)
   - 인프라: KODEX 한국부동산리츠인프라, TIGER 부동산인프라고배당
   - 글로벌: ARIRANG 글로벌리츠, TIGER 차이나항셍테크
   - 채권: KODEX 국고채10년, TIGER 미국채10년선물
3. 미국 ETF 11개 추가 (현재 19개 → 30개)
   - DGRW (WisdomTree US Quality Dividend Growth)
   - SDOG, SMDV (Dogs of the Dow 계열)
   - PFF, PGX (우선주)
   - GLD, IAU (금)
4. 모두 백테스팅 가능하도록 `_ASSET_HIST_RETURNS` 백필

**완료 기준**: `len(data['universe']) >= 100 and len(asset_metadata['kr_etf']) >= 20`

---

### D6 (6/2 월) — Layer 4: 특별배당 분리 + 환율 영향

**목표**: 배당 데이터 정밀화

**작업 항목**:
1. `utils/dividend_classifier.py` 신규
   - DART 공시 본문에서 "특별배당", "결산배당", "중간배당" 등 자동 분류
   - 정기배당만 추출해서 `dividend_dataset_classified.csv` 생성
2. `utils/dividend_projection.py` 수정 — 정기배당만 사용
3. `utils/fx_impact.py` 신규
   - 미국 배당 → 원화 환산 시 환율 영향 분리
   - `{"div_usd": 100, "fx_gain_krw": 5000, "div_krw_real": 130000}` 형태
4. `RecommendationPipeline` 응답에 `fx_breakdown` 추가
5. 백테스팅에서 환율 변동 누적 효과 시각화

**완료 기준**: `python -c "from utils.dividend_classifier import classify_dividends; print(classify_dividends('005930')[:3])"`

---

### D7 (6/3 화) — Layer 5: 데이터 품질 게이트 + 자동화

**목표**: 잘못된 데이터가 추천에 들어가는 사고 영구 방지

**작업 항목**:
1. `utils/data_quality.py` 신규
   - `detect_price_outliers(series, threshold_pct=30)` — 전일 대비 ±30% 변동
   - `detect_dividend_anomalies(series, threshold_pct=80)` — 연간 ±80% 변동
   - `validate_coverage(ticker, min_pct=95)` — 누락 데이터 비율
2. `build_dataset.py` 의 라벨링 직전 단계에 품질 게이트 통합
3. `utils/data_pipeline.py` 매일 19:00 cron — 일일 품질 리포트
   - `data/quality_report_YYYYMMDD.json`
4. 이상치 감지 시 Slack/email 알람 훅 (인터페이스만, 실제 연동은 후속)
5. 회귀 테스트 일괄: `pytest tests/ -v`
6. **이번 주 작업 종합 회귀**: D1~D6 모든 변경의 누적 회귀 검증

**완료 기준**: `pytest tests/ -v` 100% 통과 + 품질 리포트 생성

---

## 주간 종합 메트릭 (D7 종료 시점)

| 지표 | D0 (5/27) | D7 (6/3) 목표 |
|---|---|---|
| 한국 배당주 | 65개 | **100+** |
| 한국 ETF | 10개 | **20개** |
| 미국 ETF | 19개 | **30개** |
| 백테스팅 평균 가용 연수 | ~12년 (합성 포함) | **18+ (실제 위주)** |
| 매크로 일별 시리즈 | 0개 | **5개 (BOK·UST·USDKRW·VIX·KOSPI PER)** |
| 데이터 품질 자동 검증 | ❌ | **✅ 매일 cron** |
| 합성 데이터 명시 표시 | ❌ | **✅ data_quality 필드** |
| 특별배당 분리 | ❌ | **✅ 자동 분류** |
| 자동 갱신 cron 개수 | 3개 | **5개 (매크로·품질 추가)** |

---

## 의존성 추가 (requirements.txt)

```
pyarrow>=14.0.0          # parquet
fredapi>=0.5.1           # (선택) 미국 거시 데이터
beautifulsoup4>=4.12.0   # DART HTML 파싱 (특별배당 분리)
```

---

## API 키 발급 가이드 (D3 작업 전 필요)

**한국은행 ECOS API 키** (무료, 5분):
1. https://ecos.bok.or.kr 가입
2. 마이페이지 → 인증키 신청 → 즉시 발급
3. `.env`에 추가:
   ```bash
   echo "BOK_API_KEY=발급받은키" >> ~/ai-analyst/.env
   ```

---

## 위험 신호 — 즉시 보고

| 상황 | 대응 |
|---|---|
| D3까지 D1·D2 못 끝냄 | D5 확장 작업 축소 (한국 80개, ETF 15개) |
| 매크로 API 한도 초과 | 캐시 우선, 어제 데이터 fallback |
| pykrx/yfinance 네트워크 실패 | 정적 데이터 우선, 다음 날 재시도 cron |
| 회귀 테스트 깨짐 | D7 다 멈추고 디버깅, 다른 일 우선순위 뒤로 |

---

## 즉시 시작 — D1 (5/28 오늘)

Cursor 한도 풀렸으면 Cursor에 던지고, 아니면 제(여기)가 직접 진행할 수 있어요.

D1 작업 시작 신호만 주시면 바로 들어갑니다.

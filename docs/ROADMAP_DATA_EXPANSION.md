# Week 1: 데이터 확장 로드맵

> 목표: 백테스팅·ML 학습·매크로 판단의 신뢰도를 한 단계 끌어올린다.
> 산출물: 2005~2025 시계열 + 한국 배당주 100개 + ETF 20개 + 매크로 일별 데이터

---

## 0. 현재 상태 진단

| 영역 | 현재 | 목표 |
|---|---|---|
| 백테스팅 시계열 | 2015~2024 (10년) | **2005~2025 (21년)** |
| 한국 배당주 | DART 다년도 수집 (수십개) | **TOP 100 정제 셋** |
| 한국 배당 ETF | 0개 (직접 매핑) | **20개 (KODEX·TIGER·ARIRANG·KBSTAR·KOSEF)** |
| 매크로 데이터 | 정성 판단 위주 | **일별 5개 시리즈 (BOK금리·UST10Y·USDKRW·VIX·KOSPI PER)** |
| 특별배당 분리 | 없음 | **DART 공시 원문 파싱으로 분리** |

---

## 1. 작업 단위 분해 (Day 1~5)

### Day 1: 한국 배당주 유니버스 100개 확정

**파일**: `scripts/collect_kr_dividend_stocks.py` (스타터 제공됨)

**서브태스크**:
1. **KOSPI200 + 코스닥150 합집합 350개** 시작
2. **필터링 기준**:
   - 최근 3년 연속 배당 지급
   - 시가총액 ≥ 3,000억원
   - 부채비율 ≤ 200%
   - 영업현금흐름 양수
3. **수동 제외**: 우선주 별도 종목, ETN, ETF (별도 처리)
4. 결과 → `data/approved_universe_kr_v2.json` 저장

**Cursor 프롬프트**:
```
scripts/collect_kr_dividend_stocks.py 의 collect_universe() 함수를 완성해줘.
DART API와 yfinance를 사용해서 위 4가지 필터링 기준을 적용하고,
data/approved_universe_kr_v2.json 형식으로 저장.
```

---

### Day 2: 한국 배당 ETF 20개 통합

**파일**: `data/asset_metadata.json` 확장 + `utils/backtesting.py` 데이터 추가

**추가 대상 ETF (20개)**:
| 티커 | 이름 | 카테고리 |
|---|---|---|
| 161510 | ARIRANG 고배당주 | KR 고배당 |
| 210780 | TIGER 코스피고배당 | KR 고배당 |
| 279530 | KODEX 고배당 | KR 고배당 |
| 266390 | KBSTAR 고배당 | KR 고배당 |
| 322410 | HANARO 고배당 | KR 고배당 |
| 251600 | KODEX 미국S&P500배당귀족 | US 배당귀족 |
| 458730 | TIGER 미국배당다우존스 | US SCHD 추종 |
| 309210 | ARIRANG 글로벌리츠 | 글로벌 리츠 |
| 182480 | TIGER 미국MSCI리츠 | 미국 리츠 |
| 329200 | TIGER 리츠부동산인프라 | KR 리츠 |
| 365050 | TIGER 미국나스닥100커버드콜 | 옵션 인컴 |
| 441680 | TIGER 미국배당+7%프리미엄다우존스 | 커버드콜 |
| 460330 | KODEX 미국배당프리미엄액티브 | 커버드콜 |
| 069500 | KODEX 200 | KR 코어 (벤치마크) |
| 360750 | TIGER 미국S&P500 | US 코어 (벤치마크) |
| 360200 | TIGER 코스피 | KR 시장 (벤치마크) |
| 091160 | KODEX 반도체 | 섹터 |
| 091170 | KODEX 은행 | 섹터 (배당) |
| 244670 | KODEX 보험 | 섹터 (배당) |
| 117460 | KODEX 에너지화학 | 섹터 |

**Cursor 프롬프트**:
```
data/asset_metadata.json에 위 표의 20개 ETF를 추가해줘.
각 항목은 ticker / name / category / expense_ratio / inception_year / region 필드.
그리고 utils/backtesting.py 내장 _HISTORICAL_DATA 딕셔너리에
각 ETF의 2015~2024 연도별 (price_return, div_yield) 데이터를 yfinance로 받아서 추가.
yfinance 호출 코드는 scripts/fetch_etf_history.py에 별도로 작성.
```

---

### Day 3: 시계열 2005~2025로 확장

**대상 파일**:
- `utils/backtesting.py` — `_HISTORICAL_DATA` 딕셔너리
- `data/dividend_dataset.csv` — 기존 종목 백필
- `data/us_dividend_dataset.csv` — 미국 종목 백필

**중요 사건 커버리지**:
- 2008 글로벌 금융위기
- 2011 유럽 재정위기
- 2015 중국 증시 폭락
- 2018 미중 무역분쟁
- 2020 COVID-19
- 2022 인플레이션·금리인상
- 2024 한국 밸류업

**Cursor 프롬프트**:
```
utils/backtesting.py의 _HISTORICAL_DATA에서 시작연도를 2005로 확장해줘.
yfinance로 받기 어려운 한국 종목(KO국내 상장 종목)은
scripts/fetch_krx_history.py를 통해 KRX 정보데이터시스템에서 받도록 추가.
누락 연도는 None으로 두지 말고 보간(linear interpolation)하거나
명시적으로 NaN 처리. run_backtest()는 NaN을 0으로 처리하지 말고 해당 종목 제외.
```

---

### Day 4: 매크로 일별 데이터 파이프라인

**파일**: 신규 `utils/macro_data.py` + `data/macro_daily.parquet`

**5개 시리즈 (모두 일별)**:
| 시리즈 | 소스 | 용도 |
|---|---|---|
| BOK 기준금리 | 한국은행 ECOS API | `MacroRegimeFilter` 금리 레짐 판단 |
| 미국 10년물 (^TNX) | yfinance | 글로벌 위험선호 |
| USD/KRW (KRW=X) | yfinance | 환율 헤지 신호 |
| VIX (^VIX) | yfinance | 공포지수 → 스트레스 트리거 |
| KOSPI PER | KRX | 시장 밸류에이션 |

**Cursor 프롬프트**:
```
utils/macro_data.py를 새로 작성:
1. fetch_macro_series(start='2005-01-01') 함수 — 5개 시리즈 일별 수집
2. data/macro_daily.parquet로 저장 (parquet이 CSV보다 빠름, pyarrow 의존성 추가)
3. detect_regime(date) 함수 — 특정 날짜의 4분면 레짐 반환
   ("고금리·저성장" / "고금리·고성장" / "저금리·저성장" / "저금리·고성장")
4. utils/macro_regime.py의 기존 정성 판단 함수와 합치되 기존 시그니처는 유지.
5. APScheduler 등록: utils/data_pipeline.py의 cron에 매일 18:00 macro 갱신 추가.
```

---

### Day 5: 특별배당 분리 + 데이터 품질 게이트

**파일**: `utils/data_quality.py` (신규) + `build_dataset.py` 수정

**특별배당 분리 로직**:
- DART 공시 원문(`dart_collector`로 받은 텍스트)에서 키워드 매칭
  - "특별배당", "결산배당", "중간배당", "분기배당" 분류
  - "1회성", "비경상", "특별이익" 등은 제외 대상
- 결과: `data/dividend_dataset_classified.csv` (regular/special 컬럼 추가)

**데이터 품질 게이트**:
- 전일 대비 ±30% 가격 변동 → 이상치 로그 + 알람
- 연간 배당 변동 ±80% 이상 → 검토 플래그
- 누락 데이터 비율 5% 초과 → 종목 제외
- 메트릭 저장: `data/quality_report_YYYYMMDD.json`

**Cursor 프롬프트**:
```
1. utils/data_quality.py 작성:
   - detect_price_outliers(price_series, threshold_pct=30)
   - detect_dividend_anomalies(div_series, threshold_pct=80)
   - generate_quality_report(date) — 일별 품질 리포트 JSON 저장

2. build_dataset.py의 라벨링 단계 직전에 품질 게이트 통과 종목만 학습 셋 포함되도록 수정.

3. utils/data_pipeline.py에 매일 19:00 품질 리포트 생성 cron 추가.
```

---

## 2. 완료 정의 (Definition of Done)

Week 1이 완료됐다고 말하려면 아래가 모두 통과해야 한다:

```bash
# 1. 유니버스 100개 이상
python -c "import json; d=json.load(open('data/approved_universe_kr_v2.json')); print(len(d))"
# → 100 이상

# 2. ETF 20개 백테스팅 가능
pytest tests/test_backtesting.py::TestETFCoverage -v
# → PASS

# 3. 시계열 2005~2025
python -c "from utils.backtesting import run_backtest; r=run_backtest([{'ticker':'SCHD','weight':1.0}], start_year=2005, end_year=2024); print(len(r['yearly_returns']))"
# → 20 이상

# 4. 매크로 일별 데이터 5,000 행 이상
python -c "import pandas as pd; df=pd.read_parquet('data/macro_daily.parquet'); print(len(df))"
# → 5000 이상

# 5. 품질 리포트 생성
python -c "from utils.data_quality import generate_quality_report; r=generate_quality_report('2026-05-27'); print(r['total_checks'])"
# → 200 이상
```

---

## 3. 의존성 추가 (requirements.txt)

```
pyarrow>=14.0.0      # parquet
pykrx>=1.0.45        # 한국 KRX 데이터
fredapi>=0.5.1       # (선택) 미국 거시 데이터
beautifulsoup4>=4.12 # DART HTML 파싱
```

---

## 4. 리스크 & 대응

| 리스크 | 확률 | 대응 |
|---|---|---|
| yfinance API rate limit | 중 | 종목 10개씩 sleep(2) |
| DART API 일일 한도 초과 | 중 | 캐시 우선, 실패 시 어제 데이터 사용 |
| 한국은행 ECOS API 키 필요 | 높음 | `.env`에 `BOK_API_KEY` 등록 가이드 추가 |
| 2005~2010 데이터 신뢰도 | 중 | "참고용" 플래그 + Sharpe 계산에서 옵션 제외 가능 |

---

## 5. Cursor 작업 시작 명령어 (복사·붙여넣기 용)

```
@docs/ROADMAP_DATA_EXPANSION.md Day 1 작업 시작해줘.
스타터 스크립트는 scripts/collect_kr_dividend_stocks.py에 이미 있어.
collect_universe() 함수를 완성하고, 100개 이상 종목 정제 후
data/approved_universe_kr_v2.json으로 저장. 끝나면 wc -l로 라인 수 보여줘.
```

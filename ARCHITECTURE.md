# AI 현금흐름 운영체제 — 최종 아키텍처 확정 문서

> 작성일: 2026-08-23  
> 목적: 9월 포트폴리오 마감 전 구현 기준선 확정  

---

## 프로젝트 한 줄 정의

> "한국·미국 주식과 ETF의 재무·배당·거시경제 데이터를 통합 분석하고,  
> 사용자의 투자조건과 위험성향을 반영하여  
> 미래 배당 현금흐름의 지속 가능성과 목표 달성 가능성을 분석하는 개인화 금융 의사결정 시스템."

---

## 전체 아키텍처

```
[한국 DART / 미국 yfinance·SEC]
             ↓
   [자동 갱신 파이프라인]          ← APScheduler / 증분 업데이트
             ↓
   [재무·배당 Feature Engineering]
             ↓
 ┌───────────────────────────────┐
 │  레이어 1: 현재 위험 분류      │
 │  XGBoost 3-class              │
 │  INTACT / WEAKENING / BROKEN  │
 │  (walk-forward ROC 0.799)     │
 └───────────────────────────────┘
             ↓
 ┌───────────────────────────────┐
 │  레이어 2: 시간축 위험         │
 │  Survival 모델                │
 │  hazard / survival_1y / 3y   │
 └───────────────────────────────┘
             ↓
 ┌───────────────────────────────┐
 │  레이어 3: 거시환경 조정       │
 │  Macro Regime                 │
 │  (금리·물가·VIX·환율)         │
 └───────────────────────────────┘
             ↓
      [Risk Scoring 통합]
      (3-layer → 단일 위험 점수)
             ↓
 [사용자 입력: 나이·자본·적립액·성향]
             ↓
   [투자성향별 Survival Gate]
   보수=0.35 / 중립=0.50 / 공격=0.65
             ↓
  [3~5 핵심 종목 + 1~2 ETF 선정]
             ↓
       [Monte Carlo]
       P10 / P50 / P90
             ↓
 [목표 월 현금흐름 달성 시기·확률]
             ↓
      [LLM 리포트 생성]
      (결과 설명, 위험 요인 서술)
```

---

## 데이터 소스 & 갱신 주기

### 한국 (KR)

| 데이터 | 소스 | 갱신 주기 | 현재 상태 |
|--------|------|-----------|-----------|
| 재무제표 (FCF, OCF, 배당) | DART API | 분기보고서 공시 시 증분 갱신 | ✅ 구축 (전체 재스캔 방식) |
| 배당 이력·DPS 추이 | DART | 동일 | ✅ |
| 법인코드·기업 목록 | DART corpCode | 월 1회 | ✅ |
| ML 예측 결과 | 내부 (XGBoost) | DART 갱신 후 재계산 | ✅ ml_scoring_results.csv |
| Survival hazard | 내부 (TabPFN Survival) | 동일 | ✅ survival_pd_v4.json |

**미구현: 증분 업데이트 (마지막 rcpNo 이후 신규 공시만 수집)**

### 미국 (US)

| 데이터 | 소스 | 갱신 주기 | 현재 상태 |
|--------|------|-----------|-----------|
| 배당수익률·배당 이력 | yfinance | 7일 캐시 | ✅ us_dividend_cache.json |
| 배당 안전성 점수 | 내부 rule-based | 동일 | ✅ us_dividend_safety.py |
| 재무제표 (FCF·OCF 등) | yfinance / SEC | 미구현 | ❌ |
| XGBoost·Survival 예측 | 내부 | 미구현 | ❌ |

**→ 미국 주식은 현재 배당 스크리닝만 가능. ML 위험 분류 미지원.**  
**→ 단기: rule-based 안전성 점수로 대체. 중기: yfinance financials로 피처 추가.**

### ETF

| 데이터 | 소스 | 현재 상태 |
|--------|------|-----------|
| ETF 수익률·비용률·배당수익률 | yfinance + 내부 캐시 | ✅ etf_quality_cache.json |
| ML 위험 분류 | 해당 없음 (펀드) | — |
| 적용 방식 | rule-based 품질 점수 | ✅ |

### 거시경제

| 변수 | 소스 | 현재 상태 |
|------|------|-----------|
| 미국 기준금리 | 수동 입력 / FRED | ✅ macro_config.json |
| 미국 10년 국채 | 동일 | ✅ |
| VIX | 동일 | ✅ |
| USD/KRW | 동일 | ✅ |
| 한국 기준금리 | 동일 | ✅ |

**현재 역할: MacroRegimeFilter → Monte Carlo cut 확률 조정**  
**미구현: XGBoost/Survival 피처에 직접 반영**

---

## 모델 역할 확정

### Layer 1 — XGBoost 3-class (현재 위험 분류)

- **역할**: 기업의 현재 재무 상태 기반 배당 위험 분류
- **출력**: INTACT / WEAKENING / BROKEN + 각 클래스 확률
- **학습 데이터**: dividend_dataset.csv (KR, 2011~2024)
- **walk-forward 검증**: PR-AUC 0.803, ROC 0.799, P@20% 0.96 (2019~2024)
- **적용 대상**: 한국 주식 (US는 데이터 미비로 rule-based 대체)
- **상태**: ✅ 프로덕션 사용 중

### Layer 2 — Survival Model (시간축 위험)

- **역할**: 배당 삭감까지의 시간적 위험도 산출
- **출력**: hazard_pct (uncalibrated risk score), survival_1y, survival_3y
- **현재 모델**: TabPFN v8 (walk-forward 미검증 — 검증 대상)
- **분류 기준**: hazard < 0.35 = INTACT, 0.35~0.65 = WEAKENING, ≥0.65 = BROKEN
- **walk-forward 비교 결과**: Cox PH ROC 0.482, GBM Survival 0.665 (XGBoost 0.799 대비 낮음)
- **활용 방식**: 포트폴리오 가중치 조정 (SurvivalWeightFilter), 투자성향별 gate
- **상태**: ✅ 프로덕션 사용 중 (단, TabPFN walk-forward 검증 필요)

### Layer 3 — Macro Regime (거시환경)

- **역할**: 현재 금리·물가·VIX 환경 → Monte Carlo 시나리오 조정
- **출력**: expansion / stagflation / recession / neutral
- **활용**: Monte Carlo의 cut probability 가중치 조정
- **상태**: ✅ 프로덕션 사용 중

### 벤치마크 보존 모델

| 모델 | 파일 | 역할 |
|------|------|------|
| XGBoost 3-class | kr_3class_model.pkl | 기존 분류 모델 (benchmark 비교용) |
| Cox PH | lifelines | walk-forward 0.482, 선형 baseline |
| GBM Survival | scikit-survival | walk-forward 0.665, 비선형 survival baseline |

---

## 포트폴리오 선정 기준

### 입력 (사용자)

```
나이 (age)              : 투자 기간·보수성 계산
초기 투자자본 (만원)     : 포트폴리오 규모
월 추가 투자 가능액 (만원): Monte Carlo 적립 시뮬레이션
목표 월 현금흐름 (만원)   : FIRE 역산 기준
투자성향                 : conservative / moderate / aggressive
```

### 필터링 순서

```
1. DART 데이터 보유 + 최근 3년 배당 지급 이력
2. XGBoost ml_status != BROKEN (INTACT / WEAKENING만 통과)
3. Survival gate: hazard_pct <= threshold (성향별)
4. 배당수익률 필터: 1.5% ~ 15%
5. 섹터 분산 (동일 섹터 최대 2종목)
6. 종목 수: KR 2~3개 + US 1~2개 + ETF 1~2개 = 총 3~6개
```

### Cold Start 처리 (신규 상장 / 데이터 부족)

```
조건: DART 데이터 < 3년 → ML 예측 제외
대체: sector benchmark 기반 rule-based 스크리닝
기준: 해당 섹터 중위값 대비 payout_ratio / FCF / 부채비율
전환: 3년 데이터 확보 시 자동으로 ML 모델 적용
```

---

## 구현 우선순위 (9월 마감 기준)

### 즉시 (현재 주)

- [x] walk-forward 모델 비교 완료 (XGBoost 0.799 / GBM 0.665 / Cox 0.482)
- [x] XGBoost를 검증된 현재상태 분류기로 확정
- [x] Survival을 시간축 위험 레이어로 유지
- [x] SHAP → risk_attribution 명칭 교체
- [ ] ARCHITECTURE.md 기반 팀 내부 합의

### 단기 (1~2주)

- [ ] DART 증분 업데이트 (마지막 rcpNo 이후 신규 공시만)
- [ ] Cold Start 처리 로직 구현
- [ ] US 주식 yfinance financials → 기본 재무 피처 추가
- [ ] 거시경제 변수 → XGBoost 피처에 직접 반영 실험

### 중기 (2~4주)

- [ ] TabPFN walk-forward 검증 (GPU 환경 필요)
- [ ] 포트폴리오 최적화 고도화 (MPT 효율적 프론티어)
- [ ] 개인화 Monte Carlo (사용자 나이·자본·적립액 연동)
- [ ] BacktestChart.jsx UI 컴포넌트

### 후기 (마감 전)

- [ ] LLM 리포트 생성 (결과 설명 인터페이스)
- [ ] 전체 API 통합 테스트
- [ ] 포트폴리오 문서 작성

---

## Perplexity / ChatGPT 차별화 포인트

| ChatGPT에 물어보면? | 이 시스템은? |
|--------------------|-------------|
| 일반적 배당주 정보 | 실제 DART 재무데이터 기반 위험 분류 |
| 주관적 추천 | walk-forward 검증된 ML 모델 |
| 정적 답변 | 사용자 자본·나이·적립액 반영한 개인화 |
| 미래 미반영 | Monte Carlo P10/P50/P90 시뮬레이션 |
| 배당 유무만 판단 | 배당 지속 가능성 (survival_1y, hazard) |
| 데이터 없음 | 자동 갱신 파이프라인 |

---

*이 문서는 구현 기준선. 아키텍처 변경 시 반드시 여기를 먼저 수정 후 코드 반영.*

# 최종 보고서 템플릿 (10p) — AI 현금흐름 운영체제

> 분량: **10페이지** (그림·표 포함)
> 형식: docx 또는 PDF
> 작성 시간: D5 오후 + D6 하루 (총 약 12시간)

---

## 표지 (0.5p)

```
AI 현금흐름 운영체제
— 미래 월급형 현금흐름을 설계·분석·방어·관리하는 시스템

캡스톤 디자인 최종 보고서

[학번] [이름]
[전공] [지도교수]
제출일: 2026.06.10
```

---

## 목차 (0.5p)

```
1. 서론 ............................................. 1
2. 시스템 설계 ..................................... 3
3. 핵심 기능 ....................................... 5
4. 평가 결과 ....................................... 7
5. 결론 및 향후 계획 ............................... 9
참고문헌 ........................................... 10
```

---

## 1. 서론 (2p)

### 1.1 연구 배경 및 동기 (0.7p)

**채워야 할 내용**:
- 한국 노후 빈곤율 (OECD 1위, 43.4%, 2022 기준)
- 국민연금 소득대체율 40% 이하 → 추가 자산 필수
- 기존 자산관리 서비스 한계 3가지:
  1. 수익률 중심 (현금흐름 사각지대)
  2. 1억 미만 자산 외면 (대중 접근성 부족)
  3. 한국 세법 미반영 (해외 서비스의 결정적 한계)
- "내 문제의식 한 문단" — 왜 만들고 싶었나

**Cursor 보조 프롬프트**:
```
PROJECT_CONTEXT.md 참고. 캡스톤 보고서 1.1 연구 배경 0.7p 초안.
한국 노후 빈곤율, 국민연금 소득대체율, 기존 서비스 한계 3가지 포함.
어조: 학술적이되 딱딱하지 않게.
```

### 1.2 문제 정의 (0.6p)

- 핵심 질문: **"50세에 월 200만원 받으려면 지금 얼마를 투자해야 하나?"**
- 시스템 철학: **"매달 월급 → 안전한 배당 → 주가 유지 → 복리로 안전하게"**
- 기존 서비스가 답하지 못하는 이유 (forward simulation은 있어도 backward inversion 부재)

### 1.3 목표 (0.5p)

- 정량 목표: 60+ 종목 추천, 21년 백테스팅, 18-필터 파이프라인
- 정성 목표: "수익률 추천이 아니라 인생 재설계 도구"
- 차별화: Yield trap 자동 감지 + 한국 2026 세법 + 관리 대시보드

### 1.4 관련 연구 (0.2p, 간략)

- MPT (Markowitz, 1952), FIRE 운동 (Vicki Robin), SHAP (Lundberg & Lee, 2017)
- 기존 서비스 비교 표 (작게):

| 서비스 | 강점 | 약점 |
|---|---|---|
| 토스증권 | 단순 UI | 자산관리 부재 |
| 미래에셋 RBA | 전문성 | 1억 이상 한정 |
| Wealthfront | 자동화 | 한국 세법 ❌ |
| **본 시스템** | **FIRE 역산 + 한국 세법 + Yield Trap + 관리** | (없음) |

---

## 2. 시스템 설계 (2p)

### 2.1 전체 아키텍처 (0.8p, 그림 필수)

**그림 1**: 시스템 레이어 다이어그램
```
[프론트엔드 React + Recharts]
        ↓ REST
[FastAPI 게이트웨이]
        ↓
[Pipe-and-Filter 18-필터]
        ↓
[PostgreSQL + 파일 폴백]
        ↓
[DART / KRX / yfinance / ECOS]
```

기술 스택 한 문단:
- 백엔드: FastAPI, SQLAlchemy, XGBoost, SHAP, APScheduler
- 프론트엔드: React, Recharts, Tailwind
- 데이터: PostgreSQL + JSON 캐시

### 2.2 Pipe-and-Filter 파이프라인 (0.7p, 그림 + 표)

**그림 2**: 18-필터 실행 순서

```
MacroRegime → AxisWeight → AssetPicker → WeightAllocator
  → Summarize → Projection → Rebalancing → StressTest
  → SectorExposure → Calendar → RiskAlert → FireEngine
  → MonteCarlo → TaxOptimizer → BehavioralFinance
  → YieldTrapDetector → PortfolioHealth → SHAPExplainer → Storytelling
```

**왜 Pipe-and-Filter인가** (한 문단):
- 단일 책임 원칙 (SRP)
- 새 필터 추가가 쉽고, 필터 단위 테스트 가능
- 한 필터가 실패해도 다른 필터는 계속 동작 (graceful degradation)

### 2.3 데이터 흐름 (0.5p, 그림)

**그림 3**: 사용자 입력 → 추천 결과 변환 흐름 (단순화된 시퀀스 다이어그램)

---

## 3. 핵심 기능 (2p)

각 기능마다 0.5p씩, 4가지.

### 3.1 FIRE 역산 엔진 (0.5p)

**수식**:
```
필요_원금 = (목표월배당 × 12) / 세후수익률
누적금액(t) = 원금 × (1+r)^t + 월적립 × [((1+r/12)^(12t) - 1) / (r/12)]
```

**구현**: `utils/fire_engine.py` 의 `calc_fire_engine()` 함수
**입출력 예시**: "28세 윤지, 1,000만원 + 월 300만원 적립 → 50세 도달 P50: 월 187만원"

### 3.2 Monte Carlo 시뮬레이션 (0.5p)

**철학**: 단일 예측이 아닌 확률 분포 (P10/P50/P90)
**구현**: `utils/monte_carlo.py`, 1,000회 시뮬레이션
**매크로 연동**: 경기침체 레짐일 때 배당 삭감 확률 ×1.8

### 3.3 ⭐ Yield Trap 자동 감지 (0.5p) — **차별화 핵심**

**3가지 조건**:
1. 배당수익률 ≥ 8% AND 최근 3년 주가 CAGR ≤ -5%
2. ML 모델 BROKEN 분류 (SHAP 설명 동반)
3. dividend_coverage < 0.8 (배당이 영업현금흐름 초과)

**구현**: `utils/yield_trap_detector.py` + `YieldTrapFilter`
**예시**: QYLD (배당 12%, 주가 5년 -20%) → 빨강 경고 + 대안 (SCHD) 제시

### 3.4 한국 2026 세법 최적화 (0.5p)

**핵심 상수**:
- ISA 한도 4,000만원 (구법 2배)
- 비과세 일반 500 / 청년 1,000만원 (구법 2.5배)
- 종합과세 임계점 2,000만원

**구현**: `utils/tax_optimizer.py`
**예시**: "민호의 경우 추천대로 가면 연 배당 2,300만원 → 임계점 초과. ISA로 800만원 이전 시 연 47만원 절세."

---

## 4. 평가 결과 (2p)

### 4.1 백테스팅 (1p, 그림 2개)

**기간**: 2005~2024 (21년)
**대상**: 추천 포트폴리오 vs KOSPI vs S&P500

**그림 4**: 누적 수익률 곡선 (3개 선)
**그림 5**: 연도별 수익률 막대 (위기 연도 빨강 강조)

**표 1**: 6개 메트릭 종합

| 메트릭 | 본 시스템 | KOSPI | S&P500 |
|---|---|---|---|
| CAGR (%) | ?? | ?? | ?? |
| MDD (%) | ?? | ?? | ?? |
| Sharpe | ?? | ?? | ?? |
| Sortino | ?? | ?? | ?? |
| Calmar | ?? | ?? | ?? |
| Info Ratio | ?? | - | - |

(실제 백테스팅 후 채울 것)

### 4.2 ML 모델 성능 (0.5p)

**3-class 분류**: STRONG / STABLE / BROKEN
**Confusion Matrix** (그림 6)
**SHAP Summary Plot** (그림 7) — 상위 피처 5개

### 4.3 사용자 시나리오 검증 (0.5p)

3명 페르소나 결과 요약 표:

| 페르소나 | 입력 | 추천 결과 | 핵심 인사이트 |
|---|---|---|---|
| 28세 윤지 | 1,000만 + 월 300만 적립 | 50세 P50 월 187만 | FIRE 22년 후 93% 달성 |
| 42세 민호 | 1.5억 + 월 100만 | 60세 P50 월 233만 | 세금 경고 + ISA 800만 이전 권장 |
| 55세 영자 | 5억 즉시 인출 | 단계적 인출 전략 | 시퀀스 리스크 회피 |

---

## 5. 결론 및 향후 계획 (1p)

### 5.1 성과 요약 (0.4p)

- 18-필터 Pipe-and-Filter 아키텍처 (Python 약 8,000줄)
- React + Recharts 프론트 (약 3,500줄)
- 60+ 한국 종목 + 10 ETF + 21년 백테스팅
- 한국 2026 세법 + Yield Trap 자동 감지 (국내 최초)
- 6개 위험조정 메트릭 (CAGR, MDD, Sharpe, Sortino, Calmar, IR)

### 5.2 한계 (0.3p)

- 매크로 일별 데이터 미연동 (정성 판단 위주)
- 단일 XGBoost (앙상블 모델 미적용)
- 베타 사용자 paper trading 미실시 (1년 추적 필요)
- 채권·옵션·해외 직접 종목 확장 여지

### 5.3 향후 계획 (0.3p)

**Phase 2 (발표 후 ~3개월)**:
- XGBoost + LightGBM + CatBoost 앙상블
- 해외양도세 + 종합과세 누진세율 정밀화
- Vercel + Railway 퍼블릭 배포
- 베타 사용자 50명 모집 → paper trading 시작

**Phase 3 (~1년)**:
- 모바일 앱 (React Native)
- 증권사 API 연동 (자동 거래)
- 사업화 (월 9,900원 구독)

---

## 참고문헌 (1p)

```
[1] Markowitz, H. (1952). Portfolio Selection. Journal of Finance.
[2] Sharpe, W. F. (1964). Capital asset prices. Journal of Finance.
[3] Boyle, P. (1977). Options: A Monte Carlo approach. Journal of Financial Economics.
[4] Lundberg, S. M., & Lee, S.-I. (2017). A unified approach to interpreting model
    predictions. NIPS.
[5] Kahneman, D., & Tversky, A. (1979). Prospect Theory. Econometrica.
[6] Vicki Robin (2008). Your Money or Your Life. Penguin Books.
[7] 한국은행 (2024). 가계금융복지조사.
[8] 통계청 (2023). OECD 국가 노인빈곤율 비교.
[9] 국세청 (2026). 2026년 세법 개정안 — ISA 관련 조항.
[10] 금융감독원 (2025). 전자공시시스템 DART API 가이드.
```

---

## 작성 팁

### 분량 압축 노하우
- 각 섹션 페이지 분량 엄수 — 넘으면 다음 섹션이 짧아짐
- 그림·표는 페이지의 1/3 차지 (10p 보고서엔 그림 8개가 적정)
- 코드 인용은 최대 5~10줄 (전체는 GitHub 링크로)

### Cursor 활용
각 섹션마다:
```
@docs/FINAL_REPORT_TEMPLATE.md 의 X.X 섹션을 0.X 페이지 분량으로 작성.
PROJECT_CONTEXT.md 와 실제 코드 참고. 학술적 어조, 한국어.
```

### docx 변환
1차는 markdown으로 빠르게 작성 → pandoc으로 docx 변환:
```bash
pandoc reports/final_report.md -o reports/final_report.docx \
  --reference-doc=docs/report_template.docx
```

또는 Cursor의 docx 스킬 사용.

### 그림 도구
- 다이어그램: draw.io (drawio.com) — SVG 저장
- 차트: matplotlib (실제 백테스팅 결과로 PNG 생성)
- 표: markdown → docx 자동 변환

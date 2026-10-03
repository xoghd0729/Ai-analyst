# 추천 기준 명세서 — Track B-1

> **목적**: 추천 알고리즘의 모든 임계값·가중치를 코드에서 추출하여  
> 외부 근거(External)와 내부 설계값(Internal)을 명시적으로 분리한다.  
> 파일: `api/routers/portfolio.py`, `utils/universe.py`, `utils/risk_engine.py`  
> 작성: 2026-09-24

---

## 1. 성향(아키타입) 분류 기준

### 1-1. 6가지 아키타입 정의

| 아키타입 | 투자 목적 | 외부 참고 기관 | 핵심 설계 방향 |
|---------|----------|-------------|--------------|
| **성장형** | 배당성장률 우선, 10~20년 뒤 배당 극대화 | Morningstar — Dividend Growth Category | 배당성장ETF ↑, 방어자산·리츠 ↓ |
| **월배당형** | 매월 안정적 현금흐름(월급형 배당) | CFA Institute — Portfolio Planning & Construction (2026) | 월분배ETF·리츠 ↑, 방어자산·국내주 ↓ |
| **안정형** | 원금 보존 + 안정 배당, MDD 최소화 | Vanguard LifeStrategy Conservative Growth Fund | 방어자산 최대화, 변동성 자산 ↓ |
| **은퇴형** | 은퇴 후 생활비 조달, 배당만으로 생활 | Vanguard Target Date Fund Glide Path | 리츠(월세대체) + 월배당ETF + 방어 삼각 구조 |
| **혼합형** | 성장 + 현금흐름 균형 | CFA Institute — 전략적 자산배분(SAA) 기준점 개념 | axis_overrides 없음, 기본 비중 그대로 사용 |
| **배당형** | 순수 배당수익, 커버드콜 배제 | Morningstar — Dividend Sustainability 분석 | 고배당+배당성장ETF, 커버드콜 전면 배제 |

**⚠️ 중요**: 외부 기관은 "왜 이 방향인가"의 원칙을 제공하며,  
axis_overrides의 구체적 수치는 외부 기관이 제시한 숫자가 아닌 **시스템 내부 정규화값**이다.

---

### 1-2. 아키타입별 axis_overrides 전체 표

*(기준: 혼합형 = override 없음 = 기본 비중)*

| 아키타입 | kr_stock | us_stock | us_etf | reit | defensive |
|---------|----------|----------|--------|------|-----------|
| 성장형   | +0.03    | —        | +0.05  | -0.03 | -0.05 |
| 월배당형 | -0.05    | —        | +0.07  | +0.03 | -0.05 |
| 안정형   | +0.03    | -0.05    | -0.06  | —    | +0.08 |
| 은퇴형   | -0.06    | -0.07    | +0.05  | +0.05 | +0.03 |
| 혼합형   | —        | —        | —      | —    | — |
| 배당형   | +0.02    | -0.07    | +0.02  | +0.03 | +0.05 |

> 적용 코드: `apply_archetype_weights()` → 기본 비중에 delta 가산 후 재정규화 (음수 방지)

---

## 2. 5축 기본 가중치 (나이 + 투자성향)

### 2-1. 나이대별 기본 비중

*(함수: `get_axis_weights(age, risk)` in `utils/universe.py`)*

| 나이대 | kr_stock | us_stock | us_etf | reit | defensive | 설계 방향 |
|-------|----------|----------|--------|------|-----------|---------|
| ~30세  | 0.25 | 0.20 | 0.30 | 0.15 | 0.10 | 성장 중심, 미국ETF 최대 |
| 30~40세 | 0.28 | 0.17 | 0.28 | 0.17 | 0.10 | 성장 유지 |
| 40~50세 | 0.32 | 0.15 | 0.23 | 0.17 | 0.13 | 균형. 국내 배당주 주축 |
| 50~60세 | 0.35 | 0.12 | 0.18 | 0.17 | 0.18 | 현금흐름 강화, 방어 ↑ |
| 60세+  | 0.33 | 0.10 | 0.12 | 0.15 | 0.30 | 안전 최우선, 방어·국내주 중심 |

### 2-2. 투자성향 조정 (기본 비중에 추가)

| 성향 | kr_stock | us_stock | us_etf | defensive | 비고 |
|-----|----------|----------|--------|-----------|------|
| aggressive | -0.05 | +0.08 | +0.05 | -0.08 | 미국 성장주 최대화 |
| moderate   | 변화없음 | 변화없음 | 변화없음 | 변화없음 | 기본 비중 유지 |
| conservative | — | -0.05 | -0.05 | +0.10 | 방어자산 강화 |

> 정규화 적용: 음수 방지 후 합계 1.0

**외부 근거**: 나이에 따른 자산배분 이동(주식 → 채권) 원칙은  
Vanguard Glide Path / CFA Life-Cycle Investing 원칙 참고.  
**내부 설계값**: 각 셀의 비중 숫자는 외부 기관 제시값이 아닌 시스템 내부 설계.  
향후 MPT(평균-분산 최적화) 기반 재검증 예정.

---

## 3. 종목 선별 기준

### 3-1. 선별 흐름 (순서대로 적용)

```
전체 유니버스
  ↓ [1단계] overall_score >= 50  →  점수 미달 제거
  ↓ [2단계] trap_level != DANGER  →  Yield Trap 제거 (conservative만)
  ↓ [3단계] Survival Hard Gate    →  위험 종목 제거
  ↓ [4단계] 아키타입 카테고리 필터 →  etf_categories_priority / excluded_categories
  ↓
선별된 종목 → 축별 비중 배분 → 포트폴리오
```

### 3-2. overall_score 커트라인 (50점)

| 항목 | 값 | 분류 |
|-----|---|------|
| 커트라인 | **50점** | 내부 설계값 |
| 점수 구성 | yield + stability + financial + growth 4축 가중 합산 (0~100) | |
| 의미 | 4개 평가축 평균이 절반 이상인 종목만 편입 | |

**외부 근거**: 단일 지표 대신 다차원 종합 점수로 필터링하는 방식은  
CFA 포트폴리오 관리 원칙 및 Morningstar 스크리닝 방법론이 지지.  
**내부 설계값**: 커트라인 50 자체는 외부 기관 기준 아님.  
향후 과제: 실제 배당 삭감 종목의 overall_score 분포 분석 → precision/recall 기반 최적 cutoff 도출.

### 3-3. Survival Hard Gate (TabPFN 기반)

*(코드: `api/routers/portfolio.py` 내 `_SURVIVAL_GATE`, `utils/risk_engine.py`)*

| 투자성향 | hazard 임계값 | 실험 결과 | 특성 |
|---------|-------------|---------|------|
| conservative | **0.35** | Recall=50.0%, F1=0.442 | 위험 종목 최대 포착 (엄격) |
| moderate | **0.50** | Recall=35.2%, F1=0.378 | 균형 |
| aggressive | **0.65** | Precision=47.6%, F1=0.308 | 오제거 최소화 (관대) |

**근거**: walk-forward 앙상블 실험 (`risk_ensemble_comparison.py`)  
**⚠️ 해석 주의**: hazard값은 uncalibrated — "hazard 0.50 = 50% 배당삭감 확률"이 아님.  
ROC-AUC 0.583 기준의 상대적 위험 분류값.

### 3-4. Risk Engine 구성 (현재 운영 기준)

> **⚠️ XGBoost 런타임 미사용 명시**  
> `kr_3class_model.pkl`(XGBoost 3-class)은 **런타임에서 호출하지 않는다**.  
> 벤치마크 비교용으로만 보존 중 (README, DEMO_RUNBOOK, 중간보고서 일치).  
> 배당 삭감 예측은 Survival 분석으로 전환됐으며, 아래 구조가 현재 API 파이프라인이다.

**현재 파이프라인 흐름 (filters.py 실행 순서)**:

```
SurvivalWeightFilter  →  비중 보정 (hazard × 0.4 감소)
    ↓
RiskAttributionFilter →  Survival hazard → INTACT/WEAKENING/BROKEN 분류
    |                     (shap_explainer.py, TabPFN 기반)
    |                     ml_status 필드 업데이트
    ↓
RiskEngineFilter      →  composite_risk_score 계산
                          = ml_status_score × 0.70 + survival_hazard × 0.30
```

**composite_risk_score 계산 세부**:

| 레이어 | 실제 입력 | 가중치 | 비고 |
|-------|---------|--------|------|
| Layer 1 (분류 레이블) | Survival-derived ml_status → INTACT(15) / WEAKENING(55) / BROKEN(90) | **70%** | XGBoost 미사용. Survival hazard의 분류 형태 |
| Layer 2 (연속값) | Survival hazard (0~1 직접) | **30%** | P@20 보완 |
| Macro adder | BULLISH(-5) / NEUTRAL(0) / BEARISH(+15) | 별도 가산 | composite 포함 시 ROC 0.7727 → 저하, 가중치 0% 유지 |

**⚠️ 해석 주의 (중요)**: "70/30"은 두 독립 모델 간 앙상블이 아니라,  
TabPFN Survival 출력을 두 형태(분류 레이블 70% + 연속 hazard 30%)로 가중합하는 구조다.  
**이 70/30 가중치는 현재 Survival 단일 소스 구조에서 별도로 최적화·검증된 값이 아니다.**  
아래 과거 실험에서 도출된 비율을 참조했으며, 현재 구조에 맞는 재검증이 필요하다.

**과거 실험 기록** (walk-forward, `risk_ensemble_comparison.py` — XGBoost가 별도 모델이었던 시점):

| 실험 구성 | ROC | P@20 |
|---------|-----|------|
| XGB 단독 (구버전) | 0.7803 | 0.9420 |
| XGB+Survival 70/30 (실험) | **0.7824** | **0.9509** ← 당시 최적 |
| XGB+Survival+Macro | 0.7727 | — ← Macro 추가 시 저하 |

*이 실험은 XGBoost와 Survival이 독립 모델로 각각 예측하던 시점의 비교 실험이다.  
현재는 XGBoost(kr_3class_model.pkl)를 호출하지 않으며, 두 레이어 모두 동일한 TabPFN Survival에서 파생된다.  
따라서 70/30이라는 비율은 "현재 구조에서 검증된 최적값"이 아닌 **현재 적용 중인 내부 설계값·추가 검증 예정**이다.*

**현재 Risk Engine 가중치 검증 계획** (후속 실험 필요):

| 비교 모델 | 설명 | 확인 목적 |
|---------|-----|---------|
| Survival hazard 단독 (연속값) | hazard × 100 만 사용 | 연속값만의 성능 기준점 |
| ml_status 단독 (분류 레이블) | INTACT/WEAKENING/BROKEN score만 사용 | 분류 레이블만의 성능 기준점 |
| **70:30 결합** | **현재 운영 방식** | 현재값 성능 |
| 50:50 결합 | 동등 가중치 | 가중치 민감도 확인 |
| 최적 가중치 탐색 | grid search | walk-forward 기반 최적 비율 선정 |

평가 지표: ROC-AUC, PR-AUC, Precision@20, Recall, F1 (시간 순서 보장 walk-forward)

**Risk Gate 기준** (composite_risk_score, `utils/risk_engine.py` 코드 기준):

| 투자성향 | PASS | WARN | BLOCK |
|---------|------|------|-------|
| conservative | `< 50` | **없음** (50이 BLOCK 임계값과 동일) | `≥ 50` |
| moderate | `< 50` | `50 ≤ score < 65` | `≥ 65` |
| aggressive | `< 50` | `50 ≤ score < 75` | `≥ 75` |

*코드 로직: `if composite >= block_threshold → BLOCK`, `elif composite >= 50 → WARN`, `else → PASS`.  
Conservative는 block_threshold=50 = WARN 시작점과 동일해서 WARN 구간이 존재하지 않는다.*

---

## 4. 포트폴리오 건강도 평가 기준

### 4-1. growth_score 임계값

| 배당성장률(CAGR) | 점수 | 비고 |
|----------------|------|------|
| ≥ 8% | 20점 | SCHD 실제 10Y CAGR(~10~12%) 참고한 최우수 기준점 |
| ≥ 6% | 16점 | |
| ≥ 4% | 12점 | |
| ≥ 2% | 8점  | |
| < 2% | 4점  | |

**외부 근거**: Morningstar — 배당성장률을 배당 지속가능성 핵심 평가변수로 사용.  
**내부 설계값**: 8%/6%/4%/2% 구간 자체는 외부 기관 공식 기준 아님.

### 4-2. 건강도 등급 임계값 (100점 만점)

*(5축: stability 25pt + growth 20pt + cashflow 20pt + tax_efficiency 20pt + diversification 15pt)*

| 등급 | 임계값 | 의미 | 달성 수준 |
|-----|--------|------|---------|
| 🟢 매우 건강 | **≥ 85** | 5축 평균 약 80% 이상 | |
| 🟡 건강 | **≥ 72** | 5축 평균 약 70% 이상 | |
| 🟠 보통 | **≥ 58** | 5축 평균 약 55% 이상 | |
| 🔴 주의 필요 | **≥ 44** | 5축 평균 약 40% 이상 | |
| 🚨 개선 긴급 | **< 44** | 5축 평균 40% 미만 | |

**외부 근거**: CFA Institute / Vanguard — 포트폴리오를 단일 수익률이 아닌 복수 차원(안정성·성장성·현금흐름·세금효율·분산도)으로 평가.  
**내부 설계값**: 85/72/58/44 숫자 자체는 외부 기관 공식 기준 아님. 각 축 평균 분포를 근거로 내부 설계.  
향후 과제: 실제 사용자 포트폴리오 점수 분포 수집 후 백분위 기반 threshold 전환.

---

## 5. 외부 출처 세부화

교수님·리뷰어가 "어느 보고서의 어느 원칙을 참고했나?"라고 물을 때의 대답표.

| 설계 항목 | 외부 출처 | 외부 자료에서 참고한 원칙·방향 | 프로젝트에서 추가로 설계한 값 |
|---------|---------|------------------------------|---------------------------|
| 연령별 자산배분 방향 | Vanguard Glide Path (TDF), CFA Life-Cycle Investing | 연령·투자기간에 따라 위험자산 비중을 줄이는 원칙 | 연령대별 5축 비중 수치 |
| 배당성장 평가 채택 이유 | Morningstar Dividend Growth Category 분석 방법론 | 배당성장률이 배당 지속가능성·재무건전성의 핵심 평가변수임 | CAGR 8%/6%/4%/2% 구간 경계 |
| 다차원 종합 평가 방식 | CFA Institute — Portfolio Planning & Construction (2026) | 수익률 외 위험·분산·목적을 함께 고려한 다차원 평가 필요성 | 100점 건강도 배점 및 5축 가중치 |
| 아키타입별 방향 | Morningstar, CFA, Vanguard (아키타입별 상이) | 각 투자목적(성장/인컴/안정 등)에 따른 자산배분 방향 | axis_overrides 수치 |
| 커버드콜 배제 (배당형) | Morningstar — Dividend Sustainability 분석 | FCF 기반 배당이 미래수익 선매도 구조보다 장기 안정성 우수 | 배당형의 monthly_income 카테고리 전면 배제 규칙 |
| 고위험 종목 필터링 방향 | CFA 다차원 스크리닝 원칙 | 단일 지표 대신 종합 점수 기반 필터링 | overall_score 커트라인 50 |
| Survival Gate 방향 | 위험회피도에 따른 차등 필터 (일반 원칙) | 보수적 투자자에게 더 엄격한 필터 적용 | 0.35 / 0.50 / 0.65 수치 |
| Risk Engine 70/30 비율 | 자체 walk-forward 실험 (2019-2024, XGB+Survival 시점) | XGB+Survival 구조에서 70/30이 ROC 0.7824로 최적이었음 | **현재 Survival 단일 소스 구조의 70/30은 내부 설계값 · 별도 검증 예정** |

---

## 6. 외부 근거 vs 내부 설계값 분리 요약

| 구분 | 외부 근거로 뒷받침되는 것 | 내부 설계값 (수치 자체는 외부 기관 미제시) |
|-----|----------------------|--------------------------------------|
| 아키타입 방향 | ✅ Morningstar, CFA, Vanguard 원칙 | — |
| axis_overrides 수치 | — | ✅ 5축 정규화 내부값, 향후 백테스트 재검증 |
| 나이 글라이드패스 방향 | ✅ Vanguard TDF, CFA Life-Cycle | — |
| 나이별 비중 숫자 | — | ✅ 내부 설계, 향후 MPT 재검증 |
| 다차원 종목 평가 방식 | ✅ CFA, Morningstar 스크리닝 원칙 | — |
| overall_score 커트라인 50 | — | ✅ 내부 직관적 설계값 |
| 배당성장률 평가 채택 이유 | ✅ Morningstar Dividend Growth 방법론 | — |
| growth_score 구간(8%/6%/4%/2%) | — | ✅ SCHD CAGR 참고한 내부 설계 |
| 건강도 5축 구성 이유 | ✅ CFA/Vanguard 다차원 평가 원칙 | — |
| 건강도 임계값(85/72/58/44) | — | ✅ 내부 설계, 향후 백분위 전환 |
| Survival Gate 방향(conservative=엄격) | ✅ 위험회피도에 따른 필터링 원칙 | — |
| Survival Gate 수치(0.35/0.50/0.65) | — | ✅ walk-forward 실험 결과 |
| Risk Engine 70/30 가중치 | — | ✅ walk-forward 실험 ROC/P@20 최적값 |
| Risk Engine 구조 (XGB vs Survival) | — | ✅ **현재 운영: XGBoost 미사용, TabPFN Survival 단일 소스. 70% = Survival 분류 레이블, 30% = Survival hazard 연속값** |

---

## 7. 30초 설명 (발표용)

> 이 시스템의 추천 기준은 세 층으로 구성됩니다.
>
> **첫 번째**: 투자 목적에 따라 6가지 아키타입(성장형·월배당형·안정형 등)을 선택합니다.  
> 각 아키타입의 방향(예: "성장형 → 방어자산 줄이기")은 Morningstar·CFA·Vanguard 원칙에 근거합니다.  
> 단, 축별 비중 조정 수치는 5축 체계 내 정규화값이며 향후 백테스트로 재검증 예정입니다.
>
> **두 번째**: 나이 + 투자성향으로 기본 비중을 결정합니다.  
> 젊을수록 미국 성장ETF 비중을 높이고, 나이 들수록 방어자산·국내 배당주 비중을 높입니다.  
> 이 방향은 Vanguard Glide Path와 CFA Life-Cycle 원칙과 일치합니다.
>
> **세 번째**: 두 가지 필터로 저품질·고위험 종목을 제거합니다.  
> (1) overall_score 50점 미만 제거 — 4개 평가축 평균이 절반 이하인 종목은 제외.  
> (2) Survival Hard Gate — walk-forward 실험으로 도출한 임계값(conservative: 0.35, moderate: 0.50, aggressive: 0.65)으로 위험 종목 차단.  
>
> 결론: 방향의 근거는 외부 금융기관 원칙으로 뒷받침되며, 구체적 임계값은 내부 설계값임을 명시하고 향후 데이터 기반 재검증을 계획하고 있습니다.

---

## 8. 검증 계획 (pending calibration)

| 항목 | 현재 상태 | 검증 방법 | 예정 |
|-----|---------|---------|------|
| axis_overrides 수치 | 내부 정규화값 | 아키타입별 백테스트 수익률/MDD 비교 | MPT 최적화 후 |
| 나이별 기본 비중 | 내부 설계값 | 평균-분산 최적화(Task #23) | Task #23 완료 후 |
| overall_score 커트라인(50) | 직관적 내부값 | 실제 배당삭감 종목 분포 분석 → P/R 최적 cutoff | 데이터 누적 후 |
| growth_score 구간(8%/6%/4%/2%) | SCHD CAGR 참고 내부값 | 실제 포트폴리오 CAGR 분포 수집 후 재조정 | 데이터 누적 후 |
| 건강도 임계값(85/72/58/44) | 내부 설계값 | 사용자 포트폴리오 분포 수집 → 백분위 기반 전환 | 사용자 데이터 누적 후 |
| Survival Gate(0.35/0.50/0.65) | walk-forward 실험값 | 추가 연도 데이터 확보 후 재검증 | 연 1회 |
| Risk Engine 가중치(70/30) | 단면 실험(v1, 타깃 오류)은 무효화. `W_STATUS=0.70`은 과거 XGB+Survival walk-forward에서의 플레이스홀더. `label_cut_1y` 기반 v2 실험 스크립트 준비 완료. | `label_cut_1y` 기반 walk-forward 비교 (0.0/0.05/0.10/0.30/0.50/0.70). 최종 운영값 미확정. | walk-forward 재검증 후 |
| TabPFN walk-forward 검증 | 현재 미검증 (ARCHITECTURE.md 명시) | survival_pd_v4.json의 실제 예측력 확인 | GPU 환경 확보 후 |

---

## 9. Track D — Survival 모델 검증 메모

> 현재 Risk Engine에서 XGBoost 런타임 사용이 제거된 이후 남은 핵심 검증 과제.

### 9-1. 현재 구조의 핵심 제약

> ⚠️ 아래 수치는 출처 유형이 다르다. 반드시 구분해서 읽어야 한다.

| 항목 | 수치 | 유형 | 출처 |
|-----|------|------|------|
| TabPFN ROC (기존 측정, 단면 1yr) | 0.575 | **기존 측정값** | `survival_pd_v4.json` scores.tabpfn_1yr |
| TabPFN ROC (기존 측정, ensemble) | 0.583 | **기존 측정값** | `survival_pd_v4.json` scores.ensemble (1yr+3yr) |
| 과거 독립 2모델 ROC (walk-forward) | 0.7803~0.7824 | **기존 측정값** | `risk_ensemble_report.json`, walk-forward 2019-2024 |
| 현재 70:30 구조 ROC | 0.6417 | **예비 실험값 (v1 무효화)** | 타깃 정의 오류(`dividend_cut` 사용). v2 결과로 교체됨. |
| hazard 단독 ROC | 0.6550 | **예비 실험값 (v1 무효화)** | 동일 조건, 동일 한계. v2 결과로 교체됨. |
| 최적 가중치 ROC | 0.7117 | **예비 실험값 (v1 무효화)** | w_status=0.05, v2 결과로 교체됨. |
| [v2] hazard 단독 ROC | 0.5283 | **v2 단면 실험값** | n=199, label_cut_1y, 2024년. 낮은 ROC 원인 미확정 — 이벤트율 불일치(5.9%→16.6%)는 조사 항목이나 단독 원인으로 확정 불가. |
| [v2] 70:30 구조 ROC | 0.5944 | **v2 단면 실험값** | 동일 조건. ml_status 29/199 매칭 구조의 영향 포함. |
| [v2] ml_status 단독 ROC | 0.9540 | **v2 단면 실험값 — 해석 보류** | 매칭률 14.6%(29/199). 라벨·피처 시점 누수 여부 및 29종목 선정 기준 확인 전까지 신뢰 불가. |
| 과거 독립 2모델 복원 시 기대 ROC | ~0.7824 | **조건부 추정** | 과거 walk-forward 기반. 현재 데이터·코드에서 재검증 필요 |

> **v2 평가 조건**: 단면(cross-sectional), 2024년, KR 주식 199종목, 이벤트 33건 (이벤트율 16.58%).  
> survival_pd_v4.json 학습 이벤트율(5.86%)과 불일치. walk-forward 아님. 방향성 참고 제한적.  
> **ml_status 매칭률 14.6%** — 나머지 85.4%는 INTACT 기본값. B_status_only ROC 해석 불가.

### 9-2. 예비 실험 기록 (v1 — 무효화 / v2 — 실행 대기)

#### v1 실험 — 무효화 (타깃 정의 오류)

> ⚠️ **이 실험 결과는 가중치 결정 근거로 사용하지 않는다.**  
> 타깃으로 `dividend_cut(t)` (t년도 당해 삭감 여부)를 사용했으나, 올바른 예측 타깃은  
> `label_cut_1y(t)` (t+1년 삭감 여부)다. 예측 목적과 라벨 시점이 맞지 않는다.  
> 또한 `survival_pd_v4.json`은 전체 기간 데이터 기반 scoring이므로 평가 시점 기준으로도 누수가 있다.  
> 결과 파일: `results/survival_weight_report.json` (INVALIDATED 플래그 포함)

v1 조건 (참고용): 단면 평가, 2024년, n=62, events=12, 타깃=`dividend_cut`

| 전략 | ROC-AUC | PR-AUC | P@20 | 비고 |
|-----|---------|--------|------|------|
| hazard 단독 | 0.6550 | 0.4207 | 0.4167 | |
| ml_status 단독 | 0.5208 | 0.1975 | 0.2500 | |
| 현재 70:30 | 0.6417 | 0.2795 | 0.2500 | |
| 50:50 | 0.6567 | 0.3227 | 0.3333 | |
| 최적 (w_status=0.05) | 0.7117 | 0.4499 | 0.4167 | 동일 평가 데이터에서 선택 → 과적합 가능 |

기존 단면 실험은 `dividend_cut(t)`를 평가 타깃으로 사용하여 미래 1년 배당 삭감 예측이라는 목적과 라벨 시점이 일치하지 않았다. 따라서 해당 ROC-AUC, PR-AUC, P@20 결과는 가중치 결정 근거로 사용하지 않는다. 올바른 `label_cut_1y`와 시간 순서 기반 검증으로 재평가한다.

#### v2 실험 — 완료 (2026-09-29 실행)

`experiments/survival_weight_experiment.py` v2 실행 완료. 결과: `results/survival_weight_report.json` (version: 2)

조건: label_cut_1y, 2024년, n=199, events=33, event_rate=16.58%

| 전략 | ROC-AUC | PR-AUC | P@20 | F1@50 | 비고 |
|-----|---------|--------|------|-------|------|
| hazard 단독 | 0.5283 | 0.2030 | 0.231 | 0.214 | 거의 랜덤. 이벤트율 불일치 의심 |
| ml_status 단독 | 0.9540 | 0.7068 | 0.333 | 0.213 | **해석 불가** — 매칭률 14.6% + serial correlation |
| 70:30 | 0.5944 | 0.3292 | 0.308 | 0.238 | |
| 50:50 | 0.5969 | 0.2846 | 0.359 | 0.250 | |
| E_optimal | w=1.00 (ml_status 단독과 동일) | — | — | — | 채택 불가 |

**v2 주요 발견:**

1. **ml_status 매칭률 14.6% (29/199)**: `ml_scoring_results.csv`에 없는 170종목은 INTACT=15 기본값. 전체 199종목의 점수 순위가 모델의 실제 예측 능력을 대표한다고 보기 어렵다.
2. **B_status_only ROC 0.9540 — 신뢰 불가, 원인 미확정**: 이 수치를 신뢰하려면 다음을 먼저 확인해야 한다.
   - 매칭된 29종목이 어떤 조건으로 선정됐는가?
   - 종목 코드와 평가 연도가 정확히 일치하는가?
   - Status 생성 시 2024년 배당 삭감 정보가 입력 피처에 포함됐는가?
   - BROKEN 상태는 과거 삭감 사실을 나타내는가, 미래 위험을 예측한 것인가?
   - 매칭된 29종목과 나머지 170종목의 이벤트율은 각각 얼마인가?
3. **hazard 이벤트율 불일치 (5.86% vs 16.58%) — 조사 항목, 원인 확정 아님**: ROC-AUC는 예측 확률이 아닌 순위 구별력을 측정하므로, 이벤트율 차이만으로 ROC 저하를 설명할 수 없다. 가능한 원인은 여러 가지다: 학습·평가 집합의 기업 구성 차이, 기간별 시장 환경 차이, 라벨 정의 불일치, hazard 산출 시점에 미래 정보 포함, 또는 모델 자체의 순위 구별력 부족. 어느 것이 실제 원인인지는 추가 확인 전까지 가설이다.

**v2 결론**: v2 실험은 `label_cut_1y` 기반의 평가 구조로 변경되었으나, Status 예측값의 매칭률이 14.6%에 그치고 Survival hazard의 이벤트 정의 및 생성 시점이 충분히 검증되지 않았다. 따라서 v2 결과는 가중치 선택의 근거로 사용하지 않는다. 기존 70:30은 임시 운영 기본값으로 유지한다. 다음 단계에서는 운영 파이프라인의 Status 커버리지, Survival 모델의 이벤트 정의와 데이터 시점을 검증한 뒤 동일한 평가 대상에 대한 시간 순서 기반 평가를 수행한다. 과거 XGBoost 모델의 재도입은 현행 아키텍처와 필요성을 확인한 후 별도로 판단한다.

### 9-3. 가중치 재검증 실험 스크립트 (v2 — label_cut_1y 기반)

```bash
cd ~/ai-analyst
python experiments/survival_weight_experiment.py   # v2 실행
```

출력: `results/survival_weight_report.json` (version: 2, label: label_cut_1y)

비교 대상:
- A. Survival hazard 단독 → B. ml_status 단독 → C. 현재 70:30 → D. 50:50 → E. 최적 탐색 (그리드)

평가 지표: ROC-AUC, PR-AUC, Precision@20, Recall@20, F1 (임계 50)

> **v2 실험 상태**: 스크립트 작성 완료 (2026-09-25). 로컬 실행 대기.  
> 결과가 나오면 아래 9-4 표와 9-1 수치 표를 업데이트한다.

> **주의**: v2도 단면 평가이므로 독립 분류 모델 런타임 복원 여부를 이 결과만으로 결정하면 안 된다.  
> walk-forward는 연도별 Survival 재학습을 전제로 하므로 별도 GPU 환경이 필요하다.

### 9-4. 현재 결정 및 장기 옵션

**현재 결정 (2026-09-25 복구 후)**:

| 항목 | 결정 | 근거 |
|-----|------|------|
| W_STATUS=0.0 적용 | ❌ **철회** | v1 실험 타깃 오류(`dividend_cut`)로 도출 — 잘못된 평가 타깃에서 변경 금지 |
| 70:30 복구 | ✅ W_STATUS=0.70 | 잘못된 평가 결과를 운영 모델에 반영하지 않기 위한 복구. 최적값 아님. |
| w_status=0.05 확정 | ❌ | 동일 데이터에서 선택된 값 → 과적합 가능성 + 타깃 오류 |
| Risk Gate 임계값 | 기존값 유지 (50/65/75) | 미검증 — W_STATUS 변경 없으므로 점수 분포 동일 |
| 최종 운영값 | **미확정** | `label_cut_1y` 기반 v2 실험 + walk-forward 이후 결정 |
| 다음 실험 | v2 완료. 다음: 예측 시점·라벨 감사 | 아래 순서 참조 |

**가중치 채택 기준 (walk-forward 완료 후 적용)**:

아래 7개 조건을 모두 통과한 경우에만 가중치를 운영 설정으로 승격한다.

1. 예측 타깃(`label_cut_1y`)과 평가 시점이 올바르게 정렬되어 있는가?
2. 학습 시 미래 데이터가 포함되지 않았는가? (누수 방지)
3. PR-AUC와 Precision@20이 여러 Fold에서 안정적인가?
4. 연도별·업종별 성능 편차가 과도하지 않은가?
5. 위험 점수가 재무적으로 설명 가능한가? (FCF 커버리지·부채 추세와 일관성)
6. Risk Gate가 지나치게 많은 기업을 차단하지 않는가?
7. 증권사 협업 요구사항(리스크 투명성, 설명 가능성)과 충돌하지 않는가?

**장기 구조 옵션**:

| 옵션 | 예상 ROC | 공수 | 조건 |
|-----|---------|------|------|
| 70:30 (현재 플레이스홀더) | v2 단면: 0.5944 (참고 제한적) | 없음 | walk-forward 전까지 유지 |
| hazard-only | v2 단면: 0.5283 (이벤트율 불일치) | W_STATUS=0.0 | 이벤트율 정렬 후 재측정 필요 |
| ml_status 단독 | v2 단면: 0.9540 (해석 불가) | — | 매칭률·leakage 해결 후 재평가 |
| walk-forward 최적 가중치 | 미지수 | 실험 스크립트 확장 | ml_status 전종목 커버리지 + 연도별 재학습 전제 |
| 독립 분류모델 런타임 복원 | ~0.7824 (조건부 추정) | 코드 수정 + 재검증 | 과거 실험과 모델 구성 다름. 별도 검증 필요. |
| TabPFN 재학습 (피처 확장) | 미지수 | GPU 환경 필요 | — |

> **독립 분류모델 복원 판단 기준**: v2 실험 결과만으로 복원이 정당화되지 않는다.  
> (1) 데이터 누수 방지, (2) 현재 데이터에서 walk-forward 성능 확인, (3) 시간 순서 검증을 독립적으로 완료한 뒤 판단한다.  
> 과거 ROC 0.7824는 모델 구성이 달랐던 시점의 측정값이므로 현재 구조와 직접 비교하면 안 된다.

**다음 작업 순서 (v2 실험 완료 후 확정)**:

STEP 1 — **운영 코드 실제 동작 확인** ✅ **완료 (2026-09-29)**:

확인된 사실:
- `ml_scoring_results.csv` = XGBoost 3-class 모델 채점 결과, **33종목**, `data_year=2025`, `scored_at=2026-05-22`
- 14.6% 매칭률은 실험 CSV 문제가 아니라 **운영 파이프라인 문제**. `ML_SCORES.get(ticker, {})` — 없으면 INTACT 기본값.
- **ml_status 생성 경로가 두 가지**:
  - 경로 A (구형 라우터 `_append`): XGBoost CSV 조회 → 없으면 INTACT
  - 경로 B (파이프라인 `RiskAttribution`): `classify_by_hazard(hazard_pct)` → Survival hazard 기반 재분류. `/recommend` 파이프라인을 타는 종목은 이 경로.
- **BROKEN leakage 확인**: `data_year=2025`, `dps_yoy_pct` 음수 종목(SK텔레콤 -53%, 셀트리온 -50%, 한국가스공사 -21%)이 BROKEN으로 분류. 2025년 실제 배당 삭감 사실이 이미 피처에 반영된 상태에서 채점. 이 CSV를 2024년 데이터 기반 실험에 사용하면 미래 누수.
- 결론: v2 실험의 B_status_only 높은 ROC는 이 leakage의 영향을 받았을 가능성이 높다. 단, 전체 29→33종목 중 실험에 매칭된 29종목의 구성과 이벤트율은 별도 확인 필요.

STEP 2 — **Survival 모델 생성 경로 추적** ✅ **완료 (2026-09-29)**

`scripts/survival_pd.py` 및 `data/dividend_dataset.csv` 실제 코드·데이터 검증 완료. 아래 감사 결과 참조.

#### STEP 2 감사 결과 — Survival 이벤트 정의 및 시점 검증

**1. 확인된 사실**

**이벤트 정의 불일치**

- Survival 모델의 `meaningful_cut`: `dps_yoy_pct < -30%` 및 다음 연도 회복 조건을 적용한 엄격한 삭감 정의.
- 실험 평가 타깃 `label_cut_1y`: 단순 DPS 감소를 기준으로 생성된 라벨이며, 정확한 생성 로직은 별도 확인이 필요하다 (STEP 3-1).
- 2024년 단면 비교에서 `meaningful_cut` 이벤트 17개(7.56%), `label_cut_1y` 이벤트 33개(16.58%)가 관측됐다.
- `label_cut_1y=1`, `meaningful_cut=0`인 종목은 16개였으며, 반대 방향의 불일치(`meaningful_cut=1`, `label_cut_1y=0`)는 관측되지 않았다.

**이벤트율의 해석**

- `event_rate_1yr=5.86%`는 전체 person-period 데이터의 `event_next` 평균으로 기록된 값이다. (재현값: 5.39% — 계산 로직 차이)
- 모집단(전체 기간 2133행), 관측 기간, 이벤트 정의가 다르므로 2024년 평가 표본의 이벤트율 16.58%와 직접 비교하지 않는다.

**피처 및 점수 기준 시점**

- `load_person_period()`에서 `event_next`가 없는 행을 제외한다. `dividend_dataset.csv`에 2025년 데이터(225행) 존재하나, `event_next=NaN`이므로 학습에서 제외됨 — **2025년 미래 누수 없음 확인**.
- `d_tier.groupby("stock_code").tail(1)` 기준 225/226종목의 마지막 관측 연도가 2024년으로 확인됐다.
- `survival_pd_v4.json`의 점수는 2024년 피처를 기준으로 산출됐다 (코드·데이터로 검증).
- `risk_pct`는 GroupKFold OOF 점수를 tier 내부에서 percentile로 변환한 상대 순위 점수다. 보정된 절대 삭감 확률로 해석하지 않는다.
- `hazard` 임계값 0.35/0.65는 이 상대 점수 체계에 적용되는 내부 분류 기준이다.

**2. 평가 결과의 한계**

v2 실험의 ROC-AUC 0.5283은 Survival 모델의 이벤트 정의(`meaningful_cut`)와 평가 타깃(`label_cut_1y`)의 정의가 일치하지 않는 상태에서 산출됐다. 따라서 해당 수치를 모델의 미래 배당 삭감 예측력으로 확정적으로 해석하지 않는다.

이벤트 정의를 통일한 평가 결과는 아직 확보되지 않았다. GroupKFold의 연도별 구성과 시간적 누수 가능성도 별도 검증이 필요하다.

> ⚠️ `meaningful_cut`이 더 엄격하다는 이유만으로 반드시 더 좋은 타깃이 아니다. 플랫폼이 탐지하려는 위험이 "중대한 삭감(-30% 이상)"인지 "모든 감소"인지 제품 정의를 먼저 확정하고, 그다음 모델 평가 라벨을 맞춰야 한다.

**3. 다음 단계 (STEP 3)**

1. `label_cut_1y`의 실제 생성 코드 확인 — ✅ **완료 (2026-09-29)**
   - `build_dataset.py` `_cut_flag()` 확인: **DPS(t+1) < DPS(t) (임계값 없는 단순 감소)**, DPS 결측 시 `dividends_paid` 5% 감소로 대체
   - `meaningful_cut`(-30% 이상 + 회복 없음)과 정의 상이 확정
   - 두 정의는 배당 삭감의 **엄격도 차원에서 다른 타깃**이며, 어느 정의가 옳은지는 제품의 위험 정의에 따라 결정해야 한다. Survival 모델이 학습한 이벤트(심각한 삭감)와 평가 타깃(경미한 포함 모든 감소)이 불일치함은 확정.
2. `meaningful_cut`과 동일한 관측 기간 및 이벤트 정의로 평가 라벨 정렬 — 미완료
3. GroupKFold의 fold별 연도 구성과 피처 기준 시점 검증 (temporal leak 여부) — 미완료
4. 과거 시점 데이터만 사용해 미래 기간을 평가하는 walk-forward 검증 설계 — 미완료
5. 위 검증을 마치기 전까지 v2 ROC-AUC를 가중치 선택 근거로 사용하지 않는다.

기존 Risk Engine의 70:30 가중치는 임시 운영 기준으로 유지한다. 최적 가중치 또는 외부 금융기관이 검증한 기준으로 표현하지 않는다.

STEP 3 — **입력 데이터·타깃 정합성 검증** ✅ **완료 (2026-09-29)**

`build_dataset.py` 및 `scripts/survival_pd.py` GroupKFold 구성 코드·실제 데이터 검증 완료.

#### STEP 3 감사 결과 — label_cut_1y 정의 및 GroupKFold 시간적 구성

**3-1. label_cut_1y 생성 로직 — 코드 확정 (`build_dataset.py` `_cut_flag()`)**

- `label_cut_1y(t)` = `dividend_cut(t+1)` = DPS(t+1) < DPS(t) — **임계값 없는 단순 DPS 감소**
- DPS 결측 시 `dividends_paid(t+1) < dividends_paid(t) × 0.95` (5% 버퍼) 로 대체
- 회복 조건 없음 — 1원이라도 감소하면 이벤트

**3-2. 이벤트 정의 비교 (확정)**

| 구분 | label_cut_1y | meaningful_cut |
|---|---|---|
| 기준 | DPS(t+1) < DPS(t) | dps_yoy_pct < -30% |
| 임계값 | 없음 (단순 감소) | -30% 초과 감소 |
| 회복 조건 | 없음 | 있음 (다음 연도 +30% 회복 시 제외) |
| 2024년 이벤트 수 | 33개 (16.58%) | 17개 (7.56%) |
| 두 정의 일치율 | 92.0% | (2024년 단면) |
| 정의 불일치 방향 | label=1, mc=0 (경미한 감소): 16개 | label=0, mc=1: 0개 |

Survival 모델은 `meaningful_cut` 기준으로 학습됐고, v2 실험은 `label_cut_1y` 기준으로 평가했다. 이것이 ROC 0.5283의 확인된 평가 불일치 원인이다.

**3-3. GroupKFold 시간적 구성 검증 — 실제 fold 시뮬레이션**

GroupKFold(5, group=stock_code) 전체 fold 결과:

| Fold | train 연도 | val 연도 | train max > val min |
|---|---|---|---|
| 0 | 2013-2024 | 2015-2024 | ⚠️ YES |
| 1 | 2013-2024 | 2015-2024 | ⚠️ YES |
| 2 | 2013-2024 | 2015-2024 | ⚠️ YES |
| 3 | 2014-2024 | 2013-2024 | ⚠️ YES |
| 4 | 2013-2024 | 2014-2024 | ⚠️ YES |

**모든 fold에서 train에 val보다 미래 연도의 데이터가 포함됨.**

- 종목 단위 분리는 정상: 같은 종목이 train/val에 동시 등장하지 않음
- **시간적 교차오염 존재**: 다른 종목의 2024년 패턴으로 학습 → 다른 종목의 2015년 데이터 예측 가능. 거시 환경(bok_rate, kospi_ret)이 피처에 포함되므로 연도 간 패턴 차이가 모델에 암묵적으로 학습됨
- 이것은 "같은 종목의 미래 정보 사용"이 아니므로 명백한 leakage는 아니나, 엄격한 시계열 평가 요건에는 부합하지 않음
- 엄격한 walk-forward 기준: `train: year <= Y, test: year == Y+1` 형태여야 함

**3-4. risk_pct percentile 변환 cross-contamination**

`run_tier_model()`에서 OOF 스코어를 `rankdata()` 로 tier 전체에 일괄 rank-percentile 정규화:
- val fold의 OOF 점수도 전체 tier 분포(train fold 포함)에서 rank 계산됨
- val 종목의 percentile이 train 종목의 score 분포에 의존 → 경미한 cross-contamination
- 엄격한 walk-forward에서는 percentile도 train fold 범위 내에서만 산출해야 함

#### 제품 위험 정의 결정 ✅ (2026-09-29 확정)

본 프로젝트는 배당 감소 탐지와 배당 지속가능성 위험 평가를 별도의 목적과 평가 타깃으로 구분한다.

| 기능 | 타깃 | 이벤트 정의 | 용도 | 평가 지표 |
|---|---|---|---|---|
| **기능 A — 배당 감소 탐지** | `label_cut_1y` | DPS(t+1) < DPS(t), 임계값 없음 | 배당 변화 알림, 예상 현금흐름 재계산 | ROC-AUC, PR-AUC, P@20, 재현율 |
| **기능 B — 배당 지속가능성 위험 평가** | `meaningful_cut` | dps_yoy_pct < -30% + 회복 없음 | 포트폴리오 위험 점수, 종목 위험 설명, 추천 필터 | ROC-AUC, PR-AUC, P@20, 시간대별 안정성 |

두 타깃은 관측하는 위험의 범위가 다르므로 평가 결과를 직접 동일시하지 않는다. 소폭 배당 감소가 반드시 재무적 위험을 의미하지 않으며, 배당을 유지한다고 해서 재무적으로 안전하다고 단정할 수 없다.

기존 Survival 모델은 **기능 B(배당 지속가능성 위험 평가)** 를 위한 모델로 검증을 진행하되, GroupKFold 시간적 교차오염이 확인된 상태이므로 시간 순서 기반 평가가 완료되기 전까지 예측 성능이 검증됐다고 표현하지 않는다.

**현재 결정 (2026-09-29)**:

| 항목 | 결정 |
|---|---|
| 기존 Survival 모델 | 기능 B(심각한 삭감 위험 평가) 목적으로 walk-forward 검증 진행 |
| `label_cut_1y` | 기능 A용 별도 평가 타깃으로 유지. 별도 모델 구축은 검증 이후 검토 |
| 기존 70:30 가중치 | 임시 운영값 유지. 최적값으로 표현하지 않음 |
| v2 ROC 0.5283 | 확정 성능 근거로 사용하지 않음 |
| XGBoost 재도입 | 보류 — 현재 아키텍처 기준으로 진행 |
| v3 실험 및 가중치 변경 | 타깃 정렬·시간적 누수 검증·walk-forward 완료 후 진행 |

STEP 4 — **Walk-forward 평가 설계 및 실행** (STEP 1~3 완료 후): 두 타깃(기능 A/B) 각각에 대해 시간 순서 기반 평가 설계. 이후에만 가중치 비교 재개.

#### STEP 4-1 코드 감사 및 타깃 컬럼 추가 ✅ 완료 (2026-09-30)

**감사 결과**: `walk_forward_validator.py` 구조 올바름 — 재설계 불필요. 최소 수정만 필요.

**수정 완료 항목 (`build_dataset.py`)**:
- `_mc_flag()` + 회복 조건 적용으로 `meaningful_cut` 계산 (기존 `survival_pd.py`와 동일 로직)
- `label_meaningful_1y` 생성: year+1 조회 방식 (`shift(-1)` 미사용 — 연도 갭 16건 존재하여 shift 위험)
- 갭 구간 및 마지막 관측 연도: NaN 유지 (정상)
- 이벤트율: 총 2359행 중 양성 113개(4.8%), 결측 242개

**수정 완료 항목 (`walk_forward_validator.py`)**:
- `VALID_TARGETS`에 `"label_meaningful_1y"` 추가
- `TARGET_HORIZON`에 `"label_meaningful_1y": 1` 추가

**검증 5개 항목 전체 통과**:
1. ✅ 갭 구간(16건)에서 year+1 조회 → NaN (안전)
2. ✅ label_meaningful_1y 양성 113건, 결측 242건 (정상)
3. ✅ 기존 label_cut_1y 양성 411건 불변
4. ✅ meaningful_cut·label_meaningful_1y·_mc_raw 모두 TRAIN_FEATURES 미포함
5. ✅ assert_no_temporal_leakage(label_meaningful_1y) 통과; 기존 assertion 모두 정상

**미완료**: 실제 sklearn 환경에서의 pytest 실행 (sandbox 공간 부족). 로컬 환경에서 `pytest tests/test_walk_forward_validator.py -v` 실행 필요.

#### STEP 4-2 Survival 모델 Walk-forward 어댑터 구현 ✅ 완료 (2026-09-30)

**목표**: `survival_pd.py`의 GroupKFold + 전역 percentile 오염을 제거하고, walk_forward_validate()에 연결 가능한 sklearn 호환 어댑터 구현.

**5개 사전 확인 결과**:

| 항목 | 확인 결과 |
|---|---|
| ① 연도별 재학습 가능 여부 | `run_tier_model()`이 입력 df를 그대로 사용 → `df[df['year'] <= train_end]` 필터링 후 호출 가능 |
| ② percentile 분리 가능 여부 | `np.searchsorted(sorted_train_scores, test_score) / n_train` 패턴으로 train 기준 변환 가능 |
| ③ label_meaningful_1y 라벨 확정 시점 | **t+2년 데이터 필요** — 36건이 회복 조건으로 0으로 복원됨 (실데이터 확인) |
| ④ stock_risk 고정 스코어 재사용 가능 여부 | `survival_pd_v4.json` 226종목 스코어는 전체 기간 학습 결과 → walk-forward에서 재사용 시 누수. 연도별 재학습 필요 |
| ⑤ 실패 처리 현황 | `walk_forward_validator.py`에 이미 구현 (`n_pos==0` → metrics=None, fold 건너뜀) |

**label_meaningful_1y 라벨 확정 한계 — 문서화**:

- `label_meaningful_1y(t)` = `meaningful_cut(t+1)`
- `meaningful_cut(t+1)` 확정에는 `dps_yoy_pct(t+2) >= 30%` (회복 조건) 데이터 필요
- **예측 기준 t년 말에서 라벨이 완전 확정되지 않을 수 있음**
- 2025년 label은 2027년 데이터 공시 후 확정 (현재 데이터에서는 미확정)
- walk-forward 평가에서 최신 test_year 결과 해석 주의 요망

**구현 파일**: `utils/survival_wf_adapter.py` (신규 생성)

```python
class SurvivalWalkForwardAdapter(BaseEstimator, ClassifierMixin):
    """
    HistGradientBoostingClassifier 기반.
    fit(): train 데이터 학습 + sorted_train_scores 저장
    predict_proba(): searchsorted(sorted_train_scores, raw_prob) / n_train
                     → train 분포 기준 percentile 변환 (test 오염 없음)
    """
```

**사용법**:
```python
from utils.survival_wf_adapter import SurvivalWalkForwardAdapter
from utils.walk_forward_validator import walk_forward_validate, TRAIN_FEATURES

result = walk_forward_validate(
    df,
    model_class=SurvivalWalkForwardAdapter,
    model_params={"use_percentile_transform": True},
    target="label_meaningful_1y",
    features=TRAIN_FEATURES,
)
```

**테스트 파일**: `tests/test_survival_wf_adapter.py` (신규 생성)
- `TestInterface`: fit/predict_proba/predict/classes_ 기본 동작 6개 테스트
- `TestPercentileTransform`: 균등 분포 검증, 단조 증가, raw vs pct 차이
- `TestWalkForwardIntegration`: walk_forward_validate 연결, temporal ordering, ROC 범위
- `TestEdgeCases`: fit 전 예외, 단일 클래스 ValueError

**검증 6/6 통과** (sklearn 없이 핵심 로직 직접 검증):
1. ✅ percentile 변환 범위 [0, 1]
2. ✅ train 자기 변환 시 균등 분포 (분산 0.0833 ≈ 1/12)
3. ✅ sorted_train_scores 단조 증가
4. ✅ predict_proba 출력 형태 (n, 2), row_sum=1.0
5. ✅ 단일 클래스 감지 경로 확인
6. ✅ label_meaningful_1y 라벨 확정 시점 분석 (2025년 미확정 확인)

**수정 파일 (`tests/test_walk_forward_validator.py`)**:
- `make_synthetic_df()`에 `label_meaningful_1y` 열 추가 (이벤트율 `cut_prob × 0.5`)
- `VALID_TARGETS` 테스트가 `label_meaningful_1y` 포함 케이스도 커버하도록 업데이트

**미완료**: 실제 sklearn 환경 pytest 실행. 로컬에서 `pytest tests/test_survival_wf_adapter.py -v` 실행 필요.

#### STEP 4-3 walk-forward 실험 타깃 확정 ✅ (2026-09-30)

**결정**: STEP 4 walk-forward 기준 실험 타깃 = `label_mc_raw_1y`

**배경**: `label_meaningful_1y`는 회복 조건(dps_yoy_pct(t+2) >= 30) 때문에 학습 라벨 생성에 t+2 정보가 내포됨. 전체 기간에서 35건(1.7%)이 회복 조건으로 label=0으로 처리되어 있으며, 이 케이스들의 학습 라벨에 t+2 미래 데이터가 포함됨.

**타깃 정의 비교**:

| 비교 항목 | `label_meaningful_1y` | `label_mc_raw_1y` |
|---|---|---|
| 배당 삭감 기준 | dps_yoy_pct(t+1) < -30% | dps_yoy_pct(t+1) < -30% |
| 회복 조건 | 포함 (dps_yoy_pct(t+2) >= 30% 이면 0) | 제외 |
| 필요한 미래 정보 | t+1 및 t+2 | t+1만 필요 |
| t+2 시간 누수 | 존재 (35건) | 제거됨 |
| 기존 Survival 타깃과 일치 | 일치 (meaningful_cut) | 불일치 |
| walk-forward 적합성 | 부적절 (미래 누수) | 적합 |

**생성 로직**: `dps_yoy_pct(t+1) < -30%` — year+1 set_index 조회 (shift(-1) 미사용, 16건 갭 방어)

**생성 결과 검증 6/6 통과** (2026-09-30):
1. ✅ 유효 2117행, 양성 146개 (6.9%), 결측 242개 (마지막 연도 226 + 갭 16)
2. ✅ TRAIN_FEATURES에 미포함 (누수 없음)
3. ✅ label_cut_1y 양성 411건 불변 (기존 타깃 영향 없음)
4. ✅ VALID_TARGETS + TARGET_HORIZON 등록 완료 (`walk_forward_validator.py`)
5. ✅ assert_no_temporal_leakage 통과
6. ✅ 결측 위치 확인 (마지막 관측 연도 + 갭 — 정상)

**수정 파일**:
- `build_dataset.py`: `label_mc_raw_1y` 생성 로직 추가, `TRAIN_TARGETS`에 등록, `OUTPUT_COLS`에 등록
- `utils/walk_forward_validator.py`: `VALID_TARGETS`, `TARGET_HORIZON`에 `label_mc_raw_1y` 추가
- `tests/test_walk_forward_validator.py`: `make_synthetic_df()`에 `label_mc_raw_1y` 열 추가

**중요 구분 — 실험 목적 명시**:
- 이 실험은 `HistGradientBoostingClassifier`로 수행. 기존 `TabPFN Survival 모델` 자체의 성능을 검증하는 것이 아님.
- 검증 목적: "동일 피처 구조에서 시간 순서를 지킨 예측이 가능한가" — 누수 없는 기준선(baseline) 확보
- 결과가 좋더라도 기존 TabPFN의 성능이 입증되는 것은 아님.

**로컬 실행 순서 (STEP 4-3)**:
```bash
cd ~/ai-analyst

# 1. 단위 테스트
pytest tests/test_survival_wf_adapter.py -v
pytest tests/test_walk_forward_validator.py -v

# 2. 기준 실험 (DART API 불필요 — 기존 CSV + 동적 label 생성)
python experiments/wf_baseline_experiment.py

# 결과 확인: results/wf_baseline_report.json
```

**실험 스크립트**: `experiments/wf_baseline_experiment.py` (신규 생성)
- 기존 `dividend_dataset.csv`에서 `label_mc_raw_1y` 동적 생성 (DART API 불필요)
- `TRAIN_FEATURES` 중 CSV에 존재하는 16개 피처 자동 선택
- 연도별 fold 결과 표 + OOS 요약 콘솔 출력
- `results/wf_baseline_report.json` 저장

#### STEP 4-3 기준 실험 결과 ✅ 완료 (2026-09-30)

실험: `python experiments/wf_baseline_experiment.py` — HistGBM, `label_mc_raw_1y`, 8 fold (2017~2024)

**연도별 fold 결과**:

| test_year | n_train | n_test | ROC-AUC | PR-AUC | Brier |
|---|---|---|---|---|---|
| 2017 | 393 | 205 | 0.4467 | 0.0462 | 0.3417 |
| 2018 | 598 | 210 | 0.4596 | 0.0604 | 0.3576 |
| **2019** | 808 | 210 | **0.6024** | **0.1659** | 0.3373 |
| 2020 | 1018 | 214 | 0.3865 | 0.0328 | 0.3654 |
| **2021** | 1232 | 216 | **0.5913** | **0.1618** | 0.3770 |
| **2022** | 1448 | 218 | **0.6298** | **0.1808** | 0.3357 |
| 2023 | 1666 | 226 | 0.4602 | 0.0861 | 0.2989 |
| **2024** | 1892 | 225 | **0.6705** | **0.1518** | 0.2989 |

**OOS 전체 요약**:

| 지표 | 값 |
|---|---|
| ROC-AUC (전체 합산) | 0.5594 |
| ROC-AUC (fold 평균) | 0.5309 ± 0.1042 |
| PR-AUC (전체 합산) | 0.0948 |
| PR-AUC (fold 평균) | 0.1107 |
| Brier Score (fold 평균) | 0.3391 |
| 유효 fold 수 | 8 |

**세 가지 핵심 결론**:

**① 구별력 존재하나 불안정**: ROC-AUC 전체 0.5594, 평균 0.5309 ± 0.1042. 8 fold 중 4개(2017, 2018, 2020, 2023)가 0.5 미만 → "예측력 있다"고 단언할 수 없다. 평균 초과분(0.03)이 표준편차(0.10)보다 훨씬 작음.

**② PR-AUC 기대값은 넘었으나 제한적**: 이벤트율 6.9%에서 무작위 분류기 PR-AUC 기대값 ≈ 0.069. 현재 0.0948은 1.37배 수준 → 실질적 예측 정보 존재 신호이나 실운용 수준 판단은 별개.

**③ Brier Score 오보정 문제**: 이벤트율 기준 기대 Brier(항상 이벤트율 예측) ≈ 0.064. 현재 0.3391은 5배 이상 높음. percentile 변환으로 예측 확률이 균등 분포화되어 miscalibration 발생. 운용 지표로 사용 시 calibration 보정 필요.

**연도별 패턴 분석**:
- **구별력 높음 (ROC > 0.59)**: 2019, 2021, 2022, 2024
- **랜덤 이하**: 2017, 2018, 2020(최악, 0.39), 2023
- 낮은 연도 공통점: 거시 충격(COVID-19 = 2020) 또는 금리 전환기
- TRAIN_FEATURES 16개는 개별 기업 재무 위주 — 거시 변수(`bok_rate`, `kospi_ret`, `altman_z`, `debt_ratio_slope`) 미포함. `survival_pd.py`가 해당 피처를 추가 파생하는 이유와 일치.

**가중치 결정**: 이 결과만으로 70:30 가중치 변경 근거 없음. 기준선 확보 단계이며, 기존 TabPFN 모델과 직접 비교 불가. **70:30 유지**.

**결과 파일**: `results/wf_baseline_report.json`

**다음 단계 선택지 (STEP 5)**:

| 선택지 | 내용 | 조건 |
|---|---|---|
| A | `bok_rate`, `kospi_ret`, `altman_z` 피처 추가 후 재실험 | `survival_pd.py`의 `load_person_period()` 파생 피처 재사용 가능 여부 확인 필요 |
| B | 기존 TabPFN Survival 모델 walk-forward 재학습 (TabPFN 환경 필요) | torch + HF 인증 설치 후 `survival_pd.py` 재실행 |
| C | 현재 기준 실험 결과를 기준선으로 문서화하고 Risk Engine 검토로 전환 | 증권사 협업 요구사항 우선 검토 |

현재 가중치·위험 임계값 변경은 선택지 A 또는 B 결과 확인 후 진행한다.

#### STEP 4 Walk-forward 평가 설계 (확정 2026-09-29)

**평가 구조 (개념)**:
```python
for train_end_year, test_year in evaluation_windows:
    train = data[data["year"] <= train_end_year]
    test  = data[data["year"] == test_year]

    # 기능 A: 배당 감소 탐지
    evaluate(train=train, test=test, target="label_cut_1y")

    # 기능 B: 배당 지속가능성 위험 평가
    evaluate(train=train, test=test, target="meaningful_cut")
```

**준수 사항**:
1. 예측 시점에 이용 가능했던 피처만 사용한다.
2. 학습 라벨이 예측 기준일 이후의 결과를 정확히 나타내도록 정렬한다.
3. 검증 연도보다 미래인 데이터를 학습에 넣지 않는다.
4. 전처리·percentile 정규화·임계값 결정도 평가 데이터와 분리한다.
5. 두 타깃의 성능을 별도로 기록하고, 이벤트 수가 적은 평가 구간은 불확실성을 함께 보고한다.

**`risk_pct` percentile 변환 수정 방향**: 전체 기간 일괄 정규화 대신, 각 평가 시점에 이용 가능한 데이터만으로 산출.

**평가 창 (예시)**: train ≤ 2018 → test 2019, train ≤ 2019 → test 2020, ..., train ≤ 2023 → test 2024 (6개 창)

**현재 상태**: 설계 확정. 구현 대기 (STEP 3 완료 직후).

> ⚠️ 단순 매칭률 개선 목적으로 과거 XGBoost를 재적용하지 않는다. 현재 Survival 모델 기준으로 전 종목 상태값 생성이 가능한지 먼저 확인하거나, ml_status를 독립적 가중치 항목으로 유지하는 구조 자체를 재검토한다.

**향후 아키텍처 선택지** (STEP 1~3 완료 후 검토):

| 옵션 | 구조 | 전제 조건 |
|-----|------|---------|
| A | Hazard를 핵심 위험 점수로, ml_status는 설명 보조용으로만 사용 | hazard 이벤트 정의 검증 |
| B | ml_status가 hazard와 다른 추가 정보를 제공함을 검증한 후 결합 | 독립성 검증 + 전 종목 커버리지 |
| C | Hazard + 독립 재무 요인(FCF·배당 이력·부채) 결합 | 재무 피처 설계 + 가중치 검증 |

현재 정보만으로 A/B/C 중 하나를 최종 확정할 수 없다.

### 9-5. 증권사 협업 설계 원칙 (공개 금융 분석 원칙 기반)

> 아래는 증권사 협업 시 명시해야 할 설계 방향이다.  
> 현재 증권사의 공식 요구사항을 확보한 상태가 아니므로, 공개된 금융 분석 원칙(CFA Institute 등) 기반의 설계 방향과 검증해야 할 항목이다. 실제 협업 확정 사항으로 표현하면 안 된다.

#### ① 배당 안전성 평가 원칙

배당수익률이 높다고 배당이 안전한 것은 아니다. 배당 지속성 평가에는 다음을 함께 검토해야 한다.

| 평가 요소 | 역할 | 현재 시스템 처리 |
|---------|------|----------------|
| Survival hazard | 미래 삭감 위험의 연속형 신호 | Risk Engine Layer 2 |
| FCF 배당 커버리지 | 현금흐름으로 배당 지급 가능 여부 | SHAP 설명 피처 (`fcf`, `div_to_ocf`) |
| 부채 추세 | 재무 유연성 | SHAP 피처 (`payout_ratio`, `fcf_negative`) |
| 배당 지급 이력 | 정책 지속성 | `dps_yoy_pct`, `dividends_paid` |
| 이익·현금흐름 추세 | 배당 재원 기반 | `operating_cf`, `capex` |

#### ② 모델 hazard 해석 주의사항

Survival hazard는 미래 배당 삭감 위험 신호이지, 보정된 실제 확률이 아니다.

- `hazard=0.50` ≠ 배당 삭감 확률 50%
- 보정(calibration) 없이 hazard를 확률로 표현하면 안 됨
- Risk Engine 출력은 위험 신호의 순위(ranking) 역할로 해석해야 함

#### ③ ml_status와 hazard의 관계

현재 `ml_status`는 동일한 TabPFN Survival hazard를 이산화한 값이므로:
- 두 값은 완전히 독립적인 정보가 아님
- 70:30 결합이 독립적인 두 모델의 앙상블이 아님
- 경계값 근처에서 위험 점수의 불연속이 발생할 수 있음 (hazard 0.49 vs 0.51 → 최대 40점 차이)
- 이 구조의 한계를 walk-forward 검증으로 정량화하는 것이 목표

#### ④ 가중치 설명 (증권사 질문 대응)

"왜 70:30인가요?" 라는 질문에 대한 정확한 답변:

> 현재 70:30은 금융권 공식 표준이나 최적화가 완료된 결과가 아닙니다. `ml_status`와 hazard가 동일한 Survival 모델에서 파생될 수 있다는 점을 고려해, 두 값의 중복 반영 여부와 미래 예측 성능을 검증해야 합니다. 이후 `label_cut_1y` 기반 walk-forward 비교를 통해 성능·해석 가능성·Risk Gate 안정성을 평가할 예정입니다.

#### ⑤ 외부 원칙 / 내부 설계값 / 검증 예정 3-way 구분

| 구분 | 예시 | 표현 방식 |
|-----|------|---------|
| **외부 금융 원칙** | 배당 지속성 = FCF + 부채 + 이력 | "CFA Institute 배당 분석 프레임워크 참조" |
| **내부 설계값** | INTACT=15, WEAKENING=55, BROKEN=90 / 50·65·75 임계값 / 70:30 | "시스템 내부 설정. 검증 예정." |
| **검증 예정** | walk-forward ROC, PR-AUC, calibration, 업종별 안정성 | "실험 완료 전까지 pending" |

---

### 9-5. Risk Engine 구조 감사 및 ML 의존성 감사 (2026-09-30 ~ 2026-10-02, C단계)

#### 감사 결과 요약

`utils/risk_engine.py` 전체 코드 검토 결과 확인된 구조적 사실:

**① Layer 1과 Layer 2는 독립적인 두 모델이 아니다**

현재 composite_risk_score는 다음으로 구성된다:
- Layer 1 (W=0.70): `ml_status` — INTACT(15) / WEAKENING(55) / BROKEN(90)
- Layer 2 (W=0.30): `hazard_pct` — 0.0~1.0 연속값

두 값 모두 `results/survival_pd_v4.json`에서 로드된다. 즉 **동일한 TabPFN Survival 모델의 출력을 이산화(Layer 1)하거나 연속값으로 사용(Layer 2)한 것**이다. 통계적으로 독립 모델 앙상블이 아니다.

**② 70:30 가중치의 근거 이력**

`risk_engine.py` 주석에 기록된 실험 이력:

| 실험 | 구조 | ROC | P@20 | 유효성 |
|-----|------|-----|------|-------|
| 과거 최적 실험 | 분류모델(XGB 별도) + Survival 70:30 | 0.7824 | 0.9509 | ❌ 현재 구조와 다름 (XGB 런타임 미사용) |
| 단면 실험 2024 hazard 단독 | TabPFN hazard만 | 0.6550 | 0.4167 | ⚠️ 타깃이 `dividend_cut(t)` — 예측 시점 불일치, 무효화됨 |
| 단면 실험 2024 현재 70:30 | ml_status + hazard | 0.6417 | 0.2500 | ⚠️ 동일 무효화 사유 |

결론: **현재 70:30은 유효한 실험 근거가 없는 플레이스홀더**. risk_engine.py 본문 주석도 이를 명시한다.

**③ XGBoost(kr_3class_model.pkl)의 위치**

런타임에서 호출되지 않는다. 벤치마크 보존 목적. `shap_explainer.py`의 `_explain_xgb_benchmark()` 경로로만 접근 가능하며 추천 점수에 반영되지 않는다. (**삭제 금지**)

**④ risk_gate 임계값 검토**

| 성향 | BLOCK 임계값 | WARN 구간 |
|-----|------------|---------|
| conservative | ≥ 50 (WARN 없음) | 없음 |
| moderate | ≥ 65 | 50~64 |
| aggressive | ≥ 75 | 50~74 |

임계값 자체는 도메인 논리상 합리적(위험이 높을수록 차단)이나, composite_risk_score 자체의 calibration이 검증되지 않았으므로 임계값의 절대값은 현재 임의적이다.

#### 감사 결론

| 항목 | 상태 | 비고 |
|-----|------|------|
| Layer 1/2 독립성 | ❌ 동일 소스 | ml_status = hazard를 이산화한 것 |
| 70:30 실험 근거 | ❌ 유효 근거 없음 | 기존 실험은 타깃 불일치 또는 모델 구조 변경으로 무효 |
| XGBoost 런타임 사용 | ✅ 미사용 | 벤치마크 보존, 결과에 미반영 |
| risk_gate 로직 | ✅ 구조 정상 | score calibration 검증 필요 |
| survival_pd_v4.json 의존 | ⚠️ 단일 의존 | TabPFN 결과 파일 없으면 Risk Engine 전체 중간값(50) 폴백 |

#### 다음 단계 (A 실험 진입 조건)

이 감사 결과는 A 실험(거시 피처 추가)의 목적을 더 명확하게 한다:

- A 실험이 성공해도 70:30 가중치는 **label_cut_1y 기반 walk-forward에서 ml_status vs hazard 비교**가 완료되기 전까지 변경하지 않는다
- A 실험의 목표는 "HistGBM 기준 모델에서 거시 피처 추가 시 OOS ROC-AUC 및 연도별 안정성이 개선되는가" 확인이다
- A 결과로 가중치를 조정하는 결정은 내리지 않는다 (가중치 조정 = B 이후 별도 실험)

---

### 9-6. ML 의존성 감사 결과 (2026-10-02, C단계 — 별도 감사 스크립트)

**스크립트**: `experiments/ml_dependency_audit.py`  
**결과 파일**: `results/ml_audit_{risk}_age40.json` (3개 성향)  
**ranking.csv 갱신**: `rebuild_ranking.py` 재실행 완료 (2026-10-02, 42종목)  
**백업**: `data/ranking_backup_20261002.csv`

#### ① 데이터 문제 — ranking.csv 오래된 산출물

재실행 전 `avg_payout_pct`가 NaN이었던 4종목의 원인:

| 종목 | 원인 | 조치 |
|-----|------|------|
| 기아 (000270) | ranking.csv가 2026-08-27 빌드 — dividend_dataset에는 데이터 있음 | rebuild_ranking.py 재실행으로 해결 (avg 24.1%) |
| 삼성증권 (016360) | 동일 | 해결 (avg 24.8%) |
| 신한지주 (055550) | 동일 | 해결 (avg 28.6%) |
| JB금융지주 (175330) | **원천 데이터 자체 없음** — net_income 미수집, 금융지주 연결 회계 특성 | 미해결 — 별도 검토 대상으로 유지 |

JB금융지주 처리 원칙: 자동 통과·탈락 금지. `avg_payout_pct=NaN` 표시 유지, 감사 스크립트에서 NaN은 "검토 필요" 분류. 금융업 특화 지표(BIS비율, 보통주 배당 정책) 도입은 별도 작업으로 분리.

#### ② ML 의존성 감사 결과 (데이터 갱신 후 최종 수치)

**재무 룰 기준 (고정 — 결과 확인 후 소급 변경 금지)**:
1. trap_level != DANGER
2. overall_score ≥ 50
3. dps_cuts_3y = 0
4. avg_payout_pct ≤ 80 (NaN은 탈락 아님 — 검토 필요)
5. stability ≥ 20
6. financial ≥ 10

| 성향 | ML경로 | 룰경로 | Overlap | ML차단(룰엔 통과) | 룰제외(ML엔 통과) |
|-----|-------|-------|---------|-----------------|-----------------|
| conservative | 9 | 9 | 6 (66.7%) | 포스코인터(h=0.627), 한진칼(0.531) | — |
| moderate | 9 | 9 | 6 (66.7%) | 포스코인터(h=0.627), 한타(0.655), 한진칼(0.531) | 우리금융지주(cuts=1) |
| aggressive | 9 | 9 | 7 (77.8%) | 삼성화재(h=0.174), 한타(0.655) | — |

#### ③ 모델 간 차이 — 확인된 구조적 사실

**TabPFN Survival Hard Gate(hazard_pct)와 XGBoost ml_status의 독립 개입**:
- ML 차단 종목(포스코인터·한타·한진칼)은 XGBoost ml_status는 모두 INTACT — XGBoost가 안전하다고 판단한 종목을 TabPFN Survival만 위험으로 분류
- 두 ML이 서로 다른 판단을 내리는 케이스가 존재하며, 어느 쪽이 더 정확한지는 이 감사로 확인 불가

**해석 주의**:
- Overlap 66~78%는 두 경로의 차이를 보여주는 것이지, 어느 경로가 우수한지 말해주지 않는다
- ML 차단 종목이 실제로 미래에 배당을 삭감할지는 검증되지 않았다
- 룰 제외 종목(우리금융지주, cuts=1)은 삭감 이력 기준으로 제외된 것이지, ML 판단과 무관하다

#### ④ 제품 구조 재정의 방향 (C단계 결론)

이 감사 결과에 따라 제품 설명을 다음과 같이 조정한다:

| 기존 설명 | 조정된 설명 |
|---------|-----------|
| AI가 배당 삭감 위험을 예측해 종목을 추천 | 재무 지표와 배당 지속성 기준으로 위험을 평가 |
| ML 모델이 최적 종목을 선정 | 사용자의 현금흐름 목표에 맞춰 포트폴리오를 설계 |
| 위험 점수로 종목을 자동 차단 | 위험 지표를 제공하고 선정 근거와 한계를 설명 |

핵심 구조 변경 없음. 70:30 가중치 유지. ML은 보조 위험 신호로 위치 재정의.

---

## Section 9-7: Layer C 간접 오염 측정 실험 결과

**실험 목적**: SurvivalWeightFilter(Layer B)의 KR 비중 조정이 FireEngineFilter(Layer C)에 미치는 간접 영향을 수치로 측정

**실험 조건**: age=45, risk=moderate, investable=5억원, monthly_savings=300만원, monthly_target=200만원, target_fire_age=55

**실험 설계**:
- Experiment A: SurvivalWeightFilter 활성화 (multiplier = 1.0 - 0.4 × hazard_pct)
- Experiment B: SurvivalWeightFilter 비활성화 (multiplier = 1.0, bypass)
- 두 실험의 나머지 조건 동일 (재무 룰, 초기 자산, 적립금, 세금 설정 모두 동일)

### 결과 비교표

| 지표 | A: ML 적용 | B: ML 제거 | 차이 |
|-----|-----------|-----------|-----|
| KR 종목 총비중(%) | 30.63% | 32.01% | -1.38%p |
| avg_yield_net(%) | 4.049% | 4.048% | +0.001%p |
| 예상 월배당(만원) | 168.7 | 168.7 | 0 |
| 목표 달성 시점(개월) | 20 | 20 | 0 |
| FIRE 달성 나이 | 52세 | 52세 | 0 |
| 목표 FIRE 나이(200만원) | 50세 | 50세 | 0 |
| 포트폴리오 종목 수 | 16 | 16 | 0 |

### KR 종목별 비중 변화 상세

| 종목코드 | 이름 | hazard_pct | multiplier | 비중A(%) | 비중B(%) | 차이 |
|---------|-----|------------|-----------|---------|---------|-----|
| 000270 | 기아 | 0.201 | 0.9197 | 3.59 | 3.83 | -0.24 |
| 026960 | 동서 | 0.126 | 0.9495 | 3.63 | 3.75 | -0.12 |
| 175330 | JB금융지주 | 0.074 | 0.9705 | 3.59 | 3.63 | -0.04 |
| 016360 | 삼성증권 | 0.001 | 0.9997 | 3.62 | 3.55 | +0.07 |
| 055550 | 신한지주 | 0.227 | 0.9093 | 3.29 | 3.55 | -0.26 |
| 000810 | 삼성화재 | 0.174 | 0.9304 | 3.31 | 3.49 | -0.18 |
| 021240 | 코웨이 | 0.312 | 0.8753 | 3.06 | 3.43 | -0.37 (최대) |
| 000370 | 한화손해보험 | 0.190 | 0.9241 | 3.20 | 3.39 | -0.19 |
| 024800 | 메리츠화재 | 0.082 | 0.9673 | 3.34 | 3.39 | -0.05 |

### 해석

**측정된 오염 크기: 소 (avg_yield_net 차이 +0.001%p)**

- KR 종목 총비중은 -1.38%p 감소 (32.01% → 30.63%)
- 그러나 KR 수익률(평균 3.9%)과 전체 포트폴리오의 다른 자산(US/ETF)의 수익률 차이가 크지 않아, avg_yield_net의 변화는 +0.001%p에 그침
- 이 수준의 yield 차이는 FIRE 달성 시점에 영향을 주지 않음 (오차 범위 이내)

**구조적 이유**:
- SurvivalWeightFilter는 KR 종목 비중을 "개별 종목 내에서" 조정한 후 전체 포트폴리오를 재정규화
- KR 수익률과 US/ETF 수익률이 비슷한 수준(~4%)이기 때문에, KR 비중이 줄어도 전체 avg_yield_net 변화가 미미
- 코웨이(hazard=0.312, 최대 감소 -0.37%p)가 가장 큰 개별 비중 변화를 보이지만 전체에 미치는 영향은 제한적

**판단 기준 (사전 정의)**:
- 소 (< 0.1%p): Layer C 오염 수준 미미 → **현 수준**
- 중 (0.1~0.3%p): Layer C에 일정 수준 영향
- 대 (≥ 0.3%p): Layer C 오염 유의미, 구조 변경 검토 필요

**결론**: SurvivalWeightFilter의 Layer C 간접 오염은 현재 측정 조건에서 미미하다. 개별 KR 종목 비중이 최대 -0.37%p 변화하지만, 전체 avg_yield_net 변화는 0.001%p로 FIRE 결과에 실질적 영향을 주지 않는다.

**이 결론이 의미하는 것과 의미하지 않는 것**:
- 의미하는 것: 현재 파라미터 조건(moderate, 5억)에서 Layer C 구조 변경 우선순위 낮음
- 의미하지 않는 것: ML 신호가 맞다는 증거가 아니며, 보수적/공격적 성향이나 다른 투자금 규모에서도 같은 결론이 나온다는 보장이 없음

**결과 파일**: `results/layer_c_contamination_report.json`

---

## Section 9-8: ml_status 소스 불일치 감사

**감사 목적**: `cap_gain_rate` 계산에 사용되는 ml_status와 API 최종 응답에 표시되는 ml_status가 다른 출처에서 온다는 구조적 사실을 확인

### 파이프라인 실행 순서 추적

| 단계 | 필터 | ml_status 처리 |
|-----|-----|--------------|
| 3 | AssetPickerFilter → `pick_kr_stocks()` | `ml_status` = **XGBoost** (`ranking.csv` / `ml_scoring_results.csv`) 읽기 |
| 4 | WeightAllocatorFilter → `assign_weights()` | `cap_gain_rate` 결정: XGBoost ml_status 기준으로 **이 시점에 고정** |
| 4-b | SurvivalWeightFilter | ml_status 변경 없음. `hazard_pct`, `survival_weight_adj` 추가 |
| 4-c | RiskEngineFilter | 현재 `rec['ml_status']`(=XGBoost)를 읽어 composite_risk_score 계산. ml_status 덮어쓰지 않음 |
| 18 | RiskAttribution(SHAPExplainerFilter) | `rec['ml_status']` = **TabPFN Survival hazard → classify_by_hazard()** 결과로 **덮어씀** |

**구조적 사실**:
- `cap_gain_rate`(비중 배분에 영향) → XGBoost ml_status 기준
- `composite_risk_score`(RiskEngine, 비중 배분 후 부착) → 파이프라인 4-c 실행 시점의 ml_status, 즉 XGBoost 기준
- 사용자에게 표시되는 `ml_status` → TabPFN Survival hazard 분류 기준

### 불일치 종목 목록 (42개 중 19개)

**cap_gain 차이까지 발생하는 종목 (11개)**:

| 종목코드 | 이름 | XGB | TabPFN | hazard | cap_gain 차이 | moderate 통과 |
|---------|-----|-----|--------|--------|-------------|-------------|
| 047050 | 포스코인터내셔널 | INTACT | WEAKENING | 0.627 | 3.5→3.0 (-0.5%p) | BLOCKED |
| 180640 | 한진칼 | INTACT | WEAKENING | 0.531 | 3.5→3.0 (-0.5%p) | BLOCKED |
| 161390 | 한국타이어앤테크 | INTACT | BROKEN | 0.655 | 3.5→3.0 (-0.5%p) | BLOCKED |
| 030200 | KT | INTACT | BROKEN | 0.691 | 3.5→3.0 (-0.5%p) | BLOCKED |
| 004170 | 신세계 | INTACT | WEAKENING | 0.404 | 3.5→2.0 (-1.5%p) | 통과(rank=20) |
| 005830 | DB손해보험 | WEAKENING | INTACT | 0.251 | 2.0→3.5 (+1.5%p) | 통과(rank=21) |
| 066570 | LG전자 | INTACT | WEAKENING | 0.598 | 3.5→2.0 (-1.5%p) | BLOCKED |
| 032640 | LG유플러스 | WEAKENING | INTACT | 0.147 | 2.0→3.5 (+1.5%p) | 통과(rank=27) |
| 028260 | 삼성물산 | INTACT | BROKEN | 0.917 | 3.5→2.0 (-1.5%p) | BLOCKED |
| 271560 | 오리온 | INTACT | WEAKENING | 0.508 | 3.5→2.0 (-1.5%p) | BLOCKED |
| 015760 | 한국전력 | WEAKENING | INTACT | 0.108 | 2.0→3.5 (+1.5%p) | 통과(rank=33) |

ml_status 불일치만 있고 cap_gain 동일: GKL(BROKEN/BROKEN), 넥센타이어, 삼성에스디에스, BNK금융지주, POSCO홀딩스, 하이트진로, 현대차, 현대제철 (8개)

### 실질 영향 (moderate, age=45 기준)

**현재 상태에서 추천 top-9 전원 일치**:

moderate Hard Gate(hazard ≤ 0.50) 적용 후 top-9 종목 전원 XGBoost=INTACT, TabPFN=INTACT (hazard 최대값: 코웨이 0.312, INTACT 임계값 0.35 이하).

따라서 현재 데이터와 moderate 성향 기준에서는:
- `cap_gain_rate` 불일치 종목이 top-9에 포함되지 않음
- API 응답의 ml_status와 내부 계산 ml_status가 동일한 값을 나타냄
- **추천 결과에 관찰 가능한 영향 없음**

**단, 이 일치는 우연적 조건에 의존**:
- XGBoost INTACT이지만 TabPFN WEAKENING/BROKEN인 고위험 종목(포스코인터내셔널, 한진칼 등)이 Hard Gate에서 차단되기 때문에 발생하는 결과
- Conservative 성향이나 다른 파라미터에서 동일한 결론을 보장하지 않음

### 해석 원칙 (확정)

1. `cap_gain_rate`는 XGBoost ml_status 기준으로 **픽 시점에 고정**되며, 이후 TabPFN 분류가 덮어써도 **변경되지 않음**
2. 이 구조는 의도적으로 설계된 것인지, 리팩토링 과정에서 발생한 잔존물인지 확인 불가 (코드 커밋 히스토리 미확인)
3. 두 모델의 판단이 다른 경우, 어느 쪽이 더 정확한지는 현재 검증 데이터 없음 (walk-forward OOS ROC 0.5594 수준)
4. 이 불일치를 당장 수정하는 것은 이 감사의 범위 밖 — 구조를 문서화하고 향후 변경 시 참조 기준으로 사용

**결론**: ml_status 소스 불일치는 구조적으로 존재하지만, 현재 운영 조건(moderate, Hard Gate 0.50)에서 실제 추천 결과에 미치는 영향은 관찰되지 않음. 단, 이 일치는 Hard Gate의 차단 효과에 의존하는 조건부 상황이며, 구조 자체가 일관적이지 않다는 사실은 변하지 않는다.

---

## Section 9-9: SurvivalFilter 헤드라인 수치 검증

**감사 목적**: "20년간 목표 월배당 유지 확률 84%" 형태의 헤드라인 수치가 실제로 무엇을 의미하는지 계산 경로를 추적하고, 표현과 계산 간 불일치를 확인

### 계산 경로 전수 추적

**입력 흐름**:
```
ml_scoring_results.csv (XGBoost P_BROKEN, P_WEAKENING)
    ↓ _append() → rec["P_BROKEN"], rec["P_WEAKENING"]
    ↓ _ml_hazard(rec, base_cut=0.08)
        → ml_h = 0.7×P_BROKEN + 0.35×P_WEAKENING
        → final_h = max(base_cut, min(0.60, ml_h))
    ↓ 연도별 해저드: hazard(t) = base + (ml_h - base) × exp(-(t-1)/3)
    ↓ Monte Carlo 2000회 시뮬레이션
        → 각 경로에서 20년 명목 월배당이 threshold 이상인지 판정
    ↓ survival_probability = strict_hits / 2000 × 100  (max 99%)
```

**threshold 결정 로직**:
- `0 < monthly_target ≤ init_monthly` → threshold = monthly_target (사용자 목표)
- 그 외 → threshold = init_monthly × 0.80 (현재 배당의 80%)

### 실제 계산 검증 결과 (moderate, top-9 기준)

**[1] ML 해저드가 실제로 동작하는 종목**

| 종목코드 | 이름 | P_BROKEN | P_WEAKENING | ml_h_raw | base=0.08 | 최종_h | ML 유효 여부 |
|---------|-----|---------|-----------|---------|---------|------|-----------|
| 000270 | 기아 | 0.0318 | 0.0533 | 0.041 | 0.080 | 0.080 | base (ML < base) |
| 026960 | 동서 | 0 | 0 | 0 | 0.080 | 0.080 | 데이터 없음 |
| 175330 | JB금융지주 | 0.0127 | 0.0798 | 0.037 | 0.080 | 0.080 | base (ML < base) |
| 316140 | 우리금융지주 | 0.0248 | 0.0307 | 0.028 | 0.080 | 0.080 | base (ML < base) |
| 003690 | 코리안리 | 0 | 0 | 0 | 0.080 | 0.080 | 데이터 없음 |
| 016360 | 삼성증권 | 0.0171 | 0.0576 | 0.032 | 0.080 | 0.080 | base (ML < base) |
| 055550 | 신한지주 | 0.0495 | 0.0819 | 0.063 | 0.080 | 0.080 | base (ML < base) |
| **000810** | **삼성화재** | **0.0428** | **0.1763** | **0.092** | **0.080** | **0.092** | **ML > base (유일)** |
| 021240 | 코웨이 | 0 | 0 | 0 | 0.080 | 0.080 | 데이터 없음 |

**결과**: top-9 중 8종목은 XGBoost 값이 base rate(0.08)를 초과하지 않아 실제로 ML이 아닌 base rate만 사용됨. ML 신호가 실질 영향을 주는 종목은 삼성화재 1개, 그것도 +0.012에 불과하며 t=3년 이후엔 시간 감쇠로 거의 소멸

**[2] 해저드 시간 감쇠 (유일하게 ML>base인 삼성화재 기준)**

`hazard(t) = 0.08 + (0.092 - 0.08) × exp(-(t-1)/3)`

| 연도 | decay | hazard(t) | base와의 차이 |
|-----|------|---------|-----------|
| t=1 | 1.000 | 0.0920 | +0.0120 |
| t=3 | 0.513 | 0.0862 | +0.0062 |
| t=5 | 0.264 | 0.0832 | +0.0032 |
| t=8 | 0.097 | 0.0812 | +0.0012 |
| t=12 | 0.026 | 0.0803 | +0.0003 |
| t=20 | 0.002 | 0.0800 | ≈0 |

→ t=5년 이후 ML과 base의 차이는 0.003 이하로 수렴. 20년 예측에서 ML 기여 구간은 초기 3~5년에 집중

### 확인된 문제점

**① "ML 구동"이라는 설명과 실제 동작의 불일치**

SurvivalFilter 주석: "ML 구동: 종목별 배당컷 확률을 자산군 일반값이 아니라 검증된 모델의 P_BROKEN/P_WEAKENING으로 구동"

실제: 현재 top-9 추천 종목 기준 9개 중 8개에서 XGBoost P_BROKEN/P_WEAKENING이 base_cut(0.08)보다 낮거나 데이터 없음 → base rate로 대체. "ML 구동"이라는 설명은 현재 운영 조건에서 사실상 비활성 상태

**② XGBoost 모델의 시간적 오염과 uncalibrated 출력**

- 모델: GroupKFold 시간적 오염 확인 (train max year > val min year)
- OOS walk-forward ROC-AUC: 0.5594 (HistGBM baseline 기준)
- scored_at: 2026-05-22, data_year: 2025
- P_BROKEN/P_WEAKENING: uncalibrated 분류 확률 → 연간 해저드로 직접 사용 불가

단, 현재 운영 조건에서 상기 ①의 이유로 오염된 값이 실제 계산에 개입하는 범위가 제한적

**③ 헤드라인 수치의 의미 불명확**

"20년간 목표 월배당 유지 확률 84%"라는 표현이 실제로 의미하는 것:
- **threshold 조건에 따라 달라짐**: 사용자 목표가 현재 배당보다 낮으면 "목표 유지 확률", 높으면 "현재 배당의 80% 유지 확률"
- "목표 달성 확률"이 아닌 "소득 지속성 확률"
- 명목(물가 미조정) 기준 — 실질(구매력) 기준은 `endpoint_probability`로 별도 계산됨
- 기준 threshold가 사용자에게 표시되지 않으면 수치의 의미를 해석할 수 없음

**④ 20년 예측 근거 부재**

- 한국 배당주의 20년 관측 데이터 없음 → 통계적 보정 불가
- 시뮬레이션 파라미터 (base_cut, cut_sev, 섹터별 공통충격 확률)는 2015-2024 10년 소표본 또는 가정값
- 20년 생존확률을 뒷받침하는 백테스트 없음

### 처리 기준 판단

유저가 제시한 기준표 적용:

| 상황 | 판단 | 처리 방향 |
|-----|-----|---------|
| 해저드 입력 의미와 기간 불명확 | ✅ 해당 (threshold 조건 미표시) | 확률 표현 보류 |
| 과거 데이터 누출 확인 | ⚠️ XGBoost 오염 확인 (단, 실질 영향 제한적) | 현재 구조 유지, 표현 수정 검토 |
| 20년 관측 자료 부족 | ✅ 해당 | 장기 확률 대신 제한된 위험 지표로 표시 |
| 계산식은 타당하나 보정 미확인 | ✅ 해당 | 검증 전 추정치임을 명시 |

**결론**: 계산식 자체(Monte Carlo + base hazard + correlated shock)는 구조적으로 합리적이나, "검증된 ML 모델이 구동하는 20년 배당 유지 확률"이라는 설명은 현재 확인된 사실과 일치하지 않는다.

### 권장 표현 조정

| 현재 표현 | 조정 방향 |
|---------|---------|
| "20년간 목표 월배당 유지 확률 84%" | "20년 소득 지속성 시뮬레이션 점수 84점 (통계 추정치, 미검증)" |
| "ML이 구동하는 생존 확률" | "기본 위험 가정 + 배당 삭감 시뮬레이션 기반 점수" |
| P_BROKEN/P_WEAKENING → 연간 해저드 직접 사용 | 사용 전 보정 검토 필요 (uncalibrated) |

**제품 정의 연결**: `docs/product_definition.md`의 ML 한계 테이블에 다음 항목 추가 필요
- "20년 배당 유지 확률: Monte Carlo 시뮬레이션 기반 추정, 장기 실증 데이터 미보유, 미검증 상태"

**결과 범위**: 이 감사는 코드와 파라미터 수준의 추적이며 실증 백테스트 없음. 수치가 틀렸다는 결론이 아니라, 현재 상태에서 신뢰할 수 있는 표현 범위가 어디까지인지를 정의한 것.

---

## 9-10. 추천 엔진 감사 최종 종합 (2026-10-03)

> 감사 범위: Layer C 간접 영향 실험, ml_status 소스 불일치 감사, SurvivalFilter 헤드라인 검증, 표현 수정

### 항목별 상태

| 감사 항목 | 결과 | 상태 |
|---------|------|------|
| Layer C가 ML 조정(Layer B)에 독립적인가 | KR 비중 차이 -1.38%p, avg_yield_net 차이 +0.001%p, FIRE 나이 불변 | ✅ 영향 제한 확인 |
| ml_status 소스 불일치 (XGBoost vs RiskAttribution) | 19/42 종목 불일치, moderate top-9에서 실질 영향 0 (Hard Gate가 차단) | ✅ 영향 제한 확인 |
| SurvivalFilter "84%" 헤드라인이 ML 구동인가 | top-9 중 8종목이 base_cut 폴백 — ML 실질 기여 1/9 | ⚠️ 표현 수정 완료 |
| threshold 기준이 사용자 목표인지 80% 폴백인지 표시 | threshold_type 필드 추가 + UI 표시 변경 | ✅ 수정 완료 |
| 시뮬레이션 결과를 검증된 확률로 오해하도록 표현 | "지속 확률" → "시뮬레이션 결과 N% (시뮬레이션상 유지 비율)" | ✅ 수정 완료 |
| 프론트엔드에 구버전 "20년 지속 확률" 표현 잔존 | Portfolio.jsx 수정 완료, ml_effective_count UI 표시 추가 | ✅ 수정 완료 |

### 추가 검증 필요 항목 (이번 감사에서 미완료)

| 항목 | 이유 | 필요 작업 |
|-----|------|---------|
| Monte Carlo 파라미터 실증 보정 | base_cut, cut_sev, sigma, GROUP_SHOCK_PROB 가정이 미보정 상태 | 실증 배당 이력 대조 백테스트 |
| XGBoost temporal contamination 개선 | GroupKFold 확인됨 — OOS walk-forward 재실험 미완료 | walk-forward 8-fold 재실험 |
| TabPFN Survival ROC-AUC 0.56 보정 | 기준 이상이지만 보정 검증 미완료 | calibration curve 검증 |
| ml_status 불일치가 non-conservative 시나리오에서 영향 여부 | 현재 moderate top-9 기준이고 aggressive 시나리오 미검증 | aggressive 시나리오 동일 감사 |

### 구조 변경 결정

| 항목 | 결정 | 근거 |
|-----|------|------|
| Layer C 구조 변경 | **보류** | ML 간접 영향이 통계적으로 유의하지 않음 |
| 70:30 ML 가중치 조정 | **보류** | walk-forward 완료 전 조정 금지 원칙 |
| kr_3class_model.pkl 제거 | **금지** | 벤치마크 기준선 보존 목적 |
| SurvivalFilter 제거 | **해당 없음** | 표현 수정으로 충분 |

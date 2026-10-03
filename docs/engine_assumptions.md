# AI Cashflow OS — 엔진별 가정 비교표

> 생성일: 2026-09-23  
> 목적: Track A 계산 엔진 일관성 확인, 1일차 산출물

---

## 1. 엔진 목록 및 역할

| 엔진 | 위치 | 역할 | 호출 경로 |
|------|------|------|-----------|
| `FireEngineFilter` | `api/pipeline/filters.py` | 파이프라인 내 공식 FIRE 계산 | `POST /recommend` → `fire_plan` |
| `ReverseFireFilter` | `api/pipeline/filters.py` | 파이프라인 내 역산 (목표 조건) | `POST /recommend` → `reverse_fire` |
| `calc_fire_reverse()` | `utils/fire_engine.py` | 독립 역산 API 엔진 | `POST /fire-reverse` |
| `calcCompoundGrowth()` | `InteractiveSimulator.jsx` (클라이언트) | 간이 복리 미리보기 | 슬라이더 변경 시 즉시 |
| `run_monte_carlo()` | `utils/monte_carlo.py` | 수익률 불확실성 시뮬레이션 | `POST /recommend` → `monte_carlo` |

---

## 2. 주요 파라미터별 엔진 가정 비교

| 파라미터 | FireEngineFilter | ReverseFireFilter | calc_fire_reverse API | calcCompoundGrowth (클라) |
|---------|-----------------|-------------------|-----------------------|--------------------------|
| **avg_net_yield** | `ctx.avg_yield_net` ≈ **4.2%** (세후 배당수익률) | `ctx.avg_yield_net` ≈ **4.2%** | `req.avg_net_yield` (기본 5.0%) | `avg_total_return_net` ≈ **4.42%** |
| **div_growth_rate** | `ctx.projection.get("portfolio_div_cagr", 4.0)` ≈ **4%** | 동일 | `req.div_growth_rate` (기본 5.0%) | ❌ 미반영 |
| **cpi_rate** | **2.5%** | **2.5%** | `req.cpi_rate` (기본 2.5%) | ❌ 미반영 |
| **annual_savings_growth** | `req.savings_growth` (기본 **0.0%**) | `req.savings_growth` (기본 **0.0%**) | `req.annual_savings_growth` (기본 0.0%) | ❌ 미반영 |
| **목표 월배당 기준** | 현재 명목 금액 (CPI 반영 후 역산) | 현재 명목 금액 | 현재 명목 금액 | 현재 명목 금액 |
| **계산 방식** | PMT + 영구채 역산, 복리 성장 | 동일 (FireEngineFilter 재호출) | 동일 | FV = PV×(1+r)^n + PMT×... |

---

## 3. 수익률 정의 — 4.2% vs 4.42% 출처 확정

| 필드명 | 계산식 | 의미 | 값 예시 |
|--------|--------|------|---------|
| `avg_dividend_yield_net` | `total_annual_net / investable × 100` | **세후 배당수익률만** | ~4.2% |
| `avg_total_return_net` | `avg_yield_net + avg_cap_gain` | **세후 배당 + 자본차익** | ~4.42% |

> 자본차익(`avg_cap_gain`)은 포트폴리오 내 종목의 `capital_gain_rate × weight_pct` 합계.

**현재 문제:** `FireEngineFilter`와 `ReverseFireFilter`는 `avg_yield_net`(4.2%)을 쓰고, `InteractiveSimulator` 슬라이더는 `avg_total_return_net`(4.42%)을 쓴다. 동일 화면에서 다른 엔진 기준이 혼재.

**결정 필요:** 두 엔진 모두 `avg_total_return_net` 기준으로 통일할지, 아니면 역할 분리를 명시할지.

---

## 4. 목표 월배당 — 명목 vs 실질

| 항목 | 현재 상태 |
|------|-----------|
| 목표 월배당 입력 | 현재 가격 기준 명목 금액 (예: 200만원) |
| CPI 적용 방식 | 목표 원금을 CPI로 키워서 역산 (미래에 더 큰 자산 필요) |
| 사용자 화면 표시 | "200만원/월" — 현재 금액인지 미래 금액인지 미표시 |

> CPI 2.5%, 10년 → 200만원 목표 달성에 필요한 원금이 약 28% 더 크게 계산됨.  
> 사용자에게 "현재 구매력 기준 200만원"임을 명시 필요.

---

## 5. 발견된 기본값 불일치 (버그 수준)

| 항목 | calc_fire_engine 기본값 | PortfolioRequest 기본값 | 결과 |
|------|------------------------|------------------------|------|
| `annual_savings_growth` | **3.0%** | **0.0%** | 파이프라인 실행 시 0% 적용 |
| `avg_net_yield` | **3.5%** | (실제 계산값 사용) | 직접 호출 시만 3.5% 기본 |
| `div_growth_rate` (fire_reverse) | **5.0%** | (pipeline: 4.0%) | 독립 API와 파이프라인 기본값 다름 |

---

## 6. calcCompoundGrowth 간이 계산의 편향 방향

CPI와 배당 성장률 미반영으로 인한 편향 방향:

| 항목 | 간이 계산 vs 공식 FIRE |
|------|----------------------|
| CPI 미반영 | 미래 목표 금액을 작게 계산 → **낙관적 편향** |
| div_growth 미반영 | 미래 배당 수입 성장 없음 → **보수적 편향** |
| 순 편향 방향 | 단기(5년 이내)는 비슷, 장기(10년+)는 **낙관적** 경향 |

> MiniProjection에서 "간이 추정치 — CPI 미반영, 장기일수록 공식 결과와 차이 커짐" 문구 추가 권장.

---

## 7. 즉시 확정이 필요한 3가지

### Q1. 수익률 기준 통일
- 옵션 A: 전체 엔진 `avg_total_return_net`(4.42%) 기준 → 총수익률 기반 FIRE 계산
- 옵션 B: 전체 엔진 `avg_dividend_yield_net`(4.2%) 기준 → 배당만으로 목표 달성 계산 (더 보수적)
- 현재 혼재 상태

### Q2. annual_savings_growth 기본값
- 옵션 A: `PortfolioRequest.savings_growth` 기본값을 `3.0`으로 올림 → calc_fire_engine 기본값과 통일
- 옵션 B: 기본값 `0.0` 유지, UI에서 사용자가 명시적으로 입력하도록
- 현재: 0%로 계산되지만 사용자는 모름

### Q3. 목표 월배당 기준 표시
- "200만원/월 (현재 가격 기준)"으로 명시
- FIRE 결과 카드에 "CPI 2.5% 반영 — 실질 구매력 기준 목표" 추가

---

## 8. Q1~Q3 확정 결정 (2026-09-23)

### Q1. 수익률 기준 — 역할 분리 확정

| 계산 목적 | 사용 기준 | 이유 |
|-----------|-----------|------|
| 배당 현금흐름 목표 (FIRE 역산) | `avg_dividend_yield_net` (~4.2%) | 자본차익은 실현 매도 필요 → 배당 현금흐름과 다른 개념 |
| 자산 누적·복리 성장 | `avg_total_return_net` (~4.42%) | 누적 구간에서 배당 재투자 + 자본차익 복리 반영 |
| Monte Carlo | 총수익률 기반으로 명시 필요 | 별도 확인 예정 |

**이론적 근거**: 배당으로 생활비를 충당하는 FIRE 구조에서 자본차익은 실현 매도 없이 현금흐름화 불가. 목표 자산 계산 시 자본차익을 포함하면 필요 자산을 과소추정하는 위험 존재.

### Q2. annual_savings_growth 기본값 — 0.0% 통일

- `calc_fire_engine` 함수 기본값: 3.0% → **0.0%로 변경 완료**
- `PortfolioRequest.savings_growth`: 0.0% 유지
- 원칙: 파이프라인에서 항상 `req.savings_growth`를 명시적으로 전달
- UI: 적용한 성장률을 계산 가정 섹션에 표시

### Q3. 목표 월배당 — 현재 구매력 기준

- 사용자 입력 = 현재 구매력 기준 금액 (예: 200만원 = 오늘의 200만원 구매력)
- 내부 계산 = CPI 반영 미래 명목 금액으로 역산
- UI 표시: "목표 월배당 200만원 (현재 구매력 기준 / CPI 2.5% 반영)"

---

## 9. 내일 (2일차) 검증 항목

1. `calc_fire_engine` 내부에서 `avg_net_yield`가 자산 누적과 목표 자산 역산에 동시에 같은 값으로 쓰이는지 확인
2. `div_growth_rate`가 수익률과 중복 적용되는지 확인
3. 동일 조건에서 `FireEngineFilter`(avg_yield_net) vs `/fire-reverse`(dividendYield) 결과가 일치하는지 검증
4. Monte Carlo가 총수익률 기반인지 배당수익률 기반인지 확인

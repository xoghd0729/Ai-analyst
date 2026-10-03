# 18단계 파이프라인 감사표

> 작성: 2026-10-02  
> 기준: `docs/product_definition.md` Layer A/B/C 분류  
> 목적: 각 Filter가 종목 선정·현금흐름 결과에 미치는 영향과 ML 의존 지점 전수 추적  
> 코드 수정 없음 — 감사 전용

---

## 실행 순서 및 Layer 분류

| # | Filter 클래스 | Layer | ML 의존성 | 결과 영향 |
|---|------------|-------|---------|---------|
| 1 | MacroRegimeFilter | A+C | 없음 | axis_w 거시 보정, Monte Carlo regime 연동 |
| 2 | AxisWeightFilter | A | 없음 | KR/US/ETF/리츠/방어 5축 비중 결정 |
| 3 | AssetPickerFilter | **A+B** | **TabPFN hazard Hard Gate** | KR 종목 최초 차단 — ML 개입 최상단 |
| 4 | PersonalizedRankingFilter | **A+B** | composite_risk_score → BLOCK | BLOCK 종목 최종 제거, fit_score 산출 |
| 5 | WeightAllocatorFilter | A | ml_status → cap_gain_rate | cap_gain 3.5% vs 2.0% 분기 |
| 6 | SurvivalWeightFilter | **B** | TabPFN hazard → multiplier | KR 종목 비중 최대 26% 감소 |
| 7 | RiskEngineFilter | **B** | ml_status 70% + hazard 30% | composite_risk_score 부착 |
| 8 | SummarizeFilter | C | 없음 | 월배당·수익률 수치 집계 |
| 9 | ProjectionFilter | C | 없음 | 20년 배당 성장 시뮬레이션 |
| 10 | RebalancingFilter | A | macro regime (A) | 리밸런싱 제안 |
| 11 | StressTestFilter | A | 없음 | 4개 시나리오 스트레스 테스트 |
| 12 | SectorExposureFilter | A | 없음 | 섹터 집중도 분석 |
| 13 | CalendarFilter | A | 없음 | 월별 배당 캘린더 |
| 14 | RiskAlertFilter | **B** | ml_status·P_WEAKENING·P_BROKEN | 리스크 경보 생성 |
| 15 | FireEngineFilter | C | 없음 (avg_yield_net만 사용) | FIRE 역산 — ML 독립 |
| 16 | ReverseFireFilter | C | 없음 | FIRE 역산 보완 |
| 17 | MonteCarloFilter | C | macro regime (A) | P10/P50/P90 시뮬레이션 |
| 18 | SurvivalFilter | **B+C** | P_BROKEN/P_WEAKENING → 해저드 | "20년 생존확률 84%" 헤드라인 |
| 19 | TaxOptimizerFilter | C | 없음 | 2026 세법 절세 최적화 |
| 20 | BehavioralFinanceFilter | A | risk_alerts (B 간접) | 8가지 편향 탐지 |
| 21 | YieldTrapFilter | **A+B** | ml_status BROKEN → 경고 추가 | Yield Trap 경고 |
| 22 | PortfolioHealthFilter | A+C | Monte Carlo·calendar (간접) | 6축 건강도 |
| 23 | SHAPExplainerFilter | **B** | TabPFN hazard → ml_status 갱신 | ml_status 최종 덮어쓰기 |
| 24 | StorytellingFilter | A+C | 없음 (ctx 전체 사용) | 자연어 요약 |

> ※ PIPELINE_FILTERS 기준 실제 19개 (ReverseFireFilter 포함). 문서 표기 18단계는 설계 원칙 기준.

---

## ML 개입 지점 전수 추적

ML이 종목 선정·비중·점수에 실제로 영향을 주는 경로를 시간순으로 정리한다.

### 경로 1: AssetPickerFilter → pick_kr_stocks() [선별 단계, 비가역]

**ML 소스**: `survival_pd_v4.json` (TabPFN Survival)  
**개입 방식**: Hard Gate — hazard_pct > threshold이면 ranking.csv 풀에서 직접 제거  
**성향별 임계값**:

| 성향 | 임계값 | 제거 비율 (226종목 기준) |
|-----|-------|----------------------|
| conservative | 0.35 | 49% (111/226) |
| moderate | 0.50 | 34% (76/226) |
| aggressive | 0.65 | 19% (42/226) |

**추가 ML 개입**: conservative → ml_status == "INTACT" 추가 필터 (XGBoost)  
**결과 영향**: 이 단계에서 차단된 종목은 이후 파이프라인에 전혀 등장하지 않는다.  
**감사 결과**: 포스코인터(h=0.627)·한타(h=0.655)·한진칼(h=0.531)이 moderate에서 차단됨. 세 종목 모두 XGBoost ml_status는 INTACT.

---

### 경로 2: WeightAllocatorFilter → assign_weights() [비중·수익률 단계]

**ML 소스**: `ranking.csv`의 `ml_status` (XGBoost)  
**개입 방식**: ml_status와 dps_cuts_3y 조합으로 cap_gain_rate 결정

```python
if ml_st == "INTACT" and cuts == 0:
    cap_gain = 3.5   # 자본차익 3.5%
elif "우량" in grade:
    cap_gain = 2.5
else:
    cap_gain = 2.0   # WEAKENING 또는 삭감이력 있으면 2.0%
```

**결과 영향**: cap_gain_rate는 avg_total_return 계산에 반영 → FIRE 역산의 avg_yield_net에 간접 영향  
**주의**: ML 판단이 수익률 가정을 바꾸고, 이것이 현금흐름 계산(Layer C)에 전파된다.

---

### 경로 3: SurvivalWeightFilter [비중 보정 단계]

**ML 소스**: `survival_pd_v4.json` (TabPFN Survival)  
**개입 방식**: KR 종목 비중에 multiplier 적용

```
multiplier = 1.0 - 0.4 * hazard_pct
  hazard=0.0  → multiplier=1.00 (변화 없음)
  hazard=0.5  → multiplier=0.80 (-20%)
  hazard=0.65 → multiplier=0.74 (-26%)
```

**결과 영향**: KR 종목의 investable_amount 감소 → est_annual_div_만원 감소 → SummarizeFilter의 total_monthly 감소  
**Layer C 전파**: 비중 감소 → 월배당 감소 → FIRE 달성 시점 지연

---

### 경로 4: PersonalizedRankingFilter → BLOCK 제거 [최종 선별 단계]

**ML 소스**: RiskEngine의 composite_risk_score (70% ml_status + 30% hazard)  
**개입 방식**: risk_gate == "BLOCK"인 종목을 후보군에서 제거

```python
if c["risk_gate"] == "BLOCK":
    continue   # 최종 추천 풀에서 제거
```

**주의**: RiskEngineFilter는 경로 4 이후(Filter 7)에 실행된다. PersonalizedRankingFilter(Filter 4)는 RiskEngine 결과를 직접 호출해서 내부적으로 score_portfolio()를 실행한다.

**성향별 BLOCK 임계값**:

| 성향 | BLOCK |
|-----|-------|
| conservative | composite_risk_score ≥ 50 |
| moderate | ≥ 65 |
| aggressive | ≥ 75 |

---

### 경로 5: SurvivalFilter (utils/survival.py) [시뮬레이션 단계]

**ML 소스**: `P_BROKEN`, `P_WEAKENING` (XGBoost, ml_scoring_results.csv 경유)  
**개입 방식**: ML 확률을 연간 배당컷 해저드로 변환 후 Monte Carlo 시뮬레이션 구동

```python
def _ml_hazard(rec):
    p_brk = rec.get("P_BROKEN", 0)
    p_wkn = rec.get("P_WEAKENING", 0)
    # 조합하여 연간 배당컷 확률로 변환
```

**결과 영향**: "20년간 목표 월배당 유지 확률 84%" 헤드라인 숫자 결정  
**문제**: XGBoost P_BROKEN/P_WEAKENING은 GroupKFold 시간 오염으로 신뢰 불가 → 생존확률 수치의 신뢰도 불명확

---

### 경로 6: SHAPExplainerFilter [최후 ml_status 덮어쓰기]

**ML 소스**: `survival_pd_v4.json` (TabPFN Survival)  
**개입 방식**: TabPFN hazard 기반으로 ml_status를 최종 갱신

```python
rec["ml_status"] = res.get("prediction", "INTACT")  # TabPFN 기반으로 덮어씀
```

**중요**: ranking.csv에서 올라온 XGBoost ml_status가 이 단계에서 TabPFN 기반 값으로 교체된다.  
→ 최종 응답의 ml_status는 XGBoost가 아니라 TabPFN Survival 기반이다.  
→ 경로 2(cap_gain_rate)는 XGBoost ml_status 기준, 최종 응답 표시는 TabPFN 기준으로 불일치가 발생한다.

---

## Layer 분류 요약

### Layer A (재무 룰 및 검증 가능) — 유지
AxisWeightFilter, MacroRegimeFilter, SummarizeFilter, ProjectionFilter, RebalancingFilter, StressTestFilter, SectorExposureFilter, CalendarFilter, FireEngineFilter, ReverseFireFilter, MonteCarloFilter, TaxOptimizerFilter, BehavioralFinanceFilter, PortfolioHealthFilter, StorytellingFilter

총 15개. ML 없이도 동일하게 실행된다.

### Layer B (ML 위험 신호 — 검증 대기) — 출처 명시 필요
AssetPickerFilter (Hard Gate 부분), PersonalizedRankingFilter (BLOCK 제거), SurvivalWeightFilter, RiskEngineFilter, RiskAlertFilter, SurvivalFilter, YieldTrapFilter (BROKEN 경고), SHAPExplainerFilter

총 8개. ML 출력에 의존한다.

### Layer C (현금흐름 최적화) — ML 독립 확인
FireEngineFilter, MonteCarloFilter, TaxOptimizerFilter — 이 세 가지는 ML 출력을 직접 사용하지 않는다.

**예외**: SurvivalWeightFilter가 KR 비중을 감소시키면 avg_yield_net이 낮아지고, FireEngineFilter의 FIRE 달성 시점이 지연된다. ML → Layer C 간접 전파 경로가 존재한다.

---

## ML 활성화·비활성화 비교 가능 여부

| 비교 항목 | 현재 가능 여부 | 방법 |
|---------|-------------|------|
| Hard Gate 제거 시 KR 종목 변화 | ✅ 가능 | ml_dependency_audit.py 결과 활용 |
| BLOCK 제거 시 추천 종목 변화 | ⚠️ 부분 가능 | composite_risk_score 수동 0으로 설정 |
| SurvivalWeightFilter 비활성화 시 월배당 변화 | ✅ 가능 | multiplier=1.0 고정 |
| SurvivalFilter 비활성화 시 생존확률 변화 | ✅ 가능 | P_BROKEN/P_WEAKENING=0 설정 |
| ML 전체 비활성화 시 FIRE 달성 시점 변화 | ⚠️ 간접 | 위 항목 전부 적용 후 비교 |

---

## 주요 발견사항

1. **ml_status 불일치**: 경로 2(cap_gain_rate)는 XGBoost ml_status 기준, 최종 응답은 TabPFN ml_status 기준. 파이프라인 내에서 동일 필드가 두 ML 소스로 교체된다.

2. **Layer C 간접 오염**: SurvivalWeightFilter(B)가 KR 비중을 줄이면 avg_yield_net이 낮아진다. FireEngineFilter(C)는 이 낮아진 수익률로 FIRE를 역산한다. ML이 현금흐름 계산에 간접 전파된다.

3. **SurvivalFilter 신뢰도**: "20년 생존확률" 헤드라인은 XGBoost P_BROKEN/P_WEAKENING을 구동 입력으로 사용한다. 이 값들은 GroupKFold 시간 오염이 확인된 모델의 출력이다.

4. **Hard Gate 비가역성**: AssetPickerFilter에서 hazard_pct > threshold로 차단된 종목은 이후 어느 단계에서도 복구되지 않는다. 감사 결과 moderate 성향 기준 34%의 후보가 이 단계에서 탈락한다.

---

## 다음 단계

| 작업 | 우선순위 | 선행 조건 |
|-----|---------|---------|
| SurvivalWeightFilter 비활성화 시 월배당·FIRE 변화 측정 | 높음 | 이 문서 확정 |
| SurvivalFilter P_BROKEN/P_WEAKENING 소스 표시 | 높음 | 이 문서 확정 |
| cap_gain_rate의 XGBoost 의존성 문서화 | 중간 | 이 문서 확정 |
| ML 전체 비활성화 비교 실험 | 중간 | A 실험 전 |

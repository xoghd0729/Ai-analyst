# AI Cashflow OS — 최종 가이드라인 v2 (사실 검증본)
> 작성: 2026-06-30 | 졸업 발표: 2026년 9월
> v2 수정: pykrx→DART 정정 · LLM 표기 정정(Qwen2.5 현재) · Merton≠거시 분리 ·
>         데이터 수치 통일(1,679) · 필터 20개 · ETF/개별주 역할 분담 · 구현/계획 구분

---

## 0. 한 줄 포지셔닝

> **"한국인을 위한 글로벌 배당 포트폴리오 운영 시스템 — 기억하고, 감시하고, 최적화한다"**

**정직한 전제(내부용)**: 정확한 '예측'을 파는 게 아니라, 불확실성에 강건한 '운영'을 판다.
ML 삭감 예측은 점쟁이가 아니라 여러 위험 신호 중 하나(조연)로 쓴다.

---

## 1. 왜 이걸 써야 하는가 (경쟁자 대비)

### vs 범용 AI (Perplexity / ChatGPT / Claude)

| 항목 | 범용 AI | AI Cashflow OS | 상태 |
|---|---|---|---|
| 포트폴리오 기억 | ❌ 매번 재설명 | ✅ 저장 + 변화 추적 | 구현 |
| 한국 재무 데이터 | ❌ 모름·환각 | ✅ DART 실데이터 | 구현 |
| 한국 계좌(ISA/연금) | ❌ 모호 | ✅ 계좌별 세금 최적화 | 구현 |
| 자동 감시/알림 | ❌ 물어봐야 답 | ⚠ 위험 종목 식별 | 일부(자동 알림은 계획) |
| FIRE 역산 | △ 대략 | ✅ PMT 정확 역산 | 구현 |
| 배당 삭감 위험 | ❌ 불가 | ✅ 생존분석 ML(개별주) | 구현(고도화 예정) |
| Monte Carlo | ❌ 불가 | ✅ P10/P50/P90 1,000회 | 구현 |

**핵심 한 줄**: Perplexity는 "물어보면 답하는 도구", AI Cashflow OS는 "알아서 관리하는 시스템".

### vs 더리치 / Wealthfront (요약)

- **더리치**: 배당 캘린더·추적은 됨. FIRE 역산·세금 최적화·ML 위험·LLM 운영 ❌ → 우리는 ✅
- **Wealthfront**: AI 자동화는 강하나 미국 전용. 한국 ISA/연금/금융소득종합과세 ❌ → 우리는 한국 친화
  > ※ Wealthfront의 세무손익통산·직접지수 수준은 아님 — "한국 세제 특화"로 포지셔닝(동급 주장 X)

---

## 2. 타겟 사용자

SCHD·JEPI·VYM 등 미국 ETF를 ISA·연금저축으로 투자하는 한국 일반 투자자.

```
ISA 계좌       → SCHD, JEPI (월배당 ETF)
연금저축 계좌  → S&P500 / NASDAQ100 ETF
직투 계좌      → 삼성전자·국내 고배당주 등
```

이 세 계좌를 통합해 FIRE 역산 + 세금 최적화 + 위험 감시를 한 번에 주는 도구가 없다.

> **★ 역할 분담 (중요 — ETF와 ML의 연결)**
> - ETF 투자자 가치 = FIRE·세금·Monte Carlo·포트폴리오 운영 (ML 예측 불필요)
> - ML 생존모델 / Gem Screener = '직투(국내 개별주)' 부분에 적용 (ETF는 품질·분산으로 평가)
> → "US ETF 사는데 ML이 왜?"에 대한 답: ETF는 운영·세금이, 개별주는 ML이 담당.

---

## 3. AI 스택 — 업그레이드

### 3-1. 기존 vs 업그레이드

| 레이어 | 기존 | 업그레이드 | 이유 |
|---|---|---|---|
| 예측 모델 | XGBoost 단일 분류 | 생존분석 스택 + EBM | 차별성·연구 깊이 |
| 생존분석 | 없음 | 이산시간 → Cox → DeepHit | SOTA 방향 |
| 시장 구조모형 | 없음 | Merton DtD (하이브리드) | 금융공학 깊이 |
| 거시변수 | macro_regime.py(일부) | 금리·CPI·VIX 피처 추가 | 교수 #6 (Merton과 별개!) |
| 설명가능성 | SHAP만 | SHAP + EBM 병행 | 2025 베스트 프랙티스 |
| LLM | Qwen2.5 14B(Ollama, 선택연동) | Qwen3 검토(가용성 확인 후) | function-calling 강화 |
| 벤치마크 | 없음 | Altman·Ohlson + 부스팅 | 엄밀성 |
| 캘리브레이션 | 없음 | Platt / Isotonic | 확률 신뢰성 |

> ※ LLM 정정: 현재 코드 = qwen2.5:14b (EXAONE 아님). Qwen3 교체는 Ollama 태그 실재 확인 후 결정.

---

### 3-2. [1층] Risk Model Engine — 배당 생존 예측 (국내 개별주)

```
[입력] DART 재무제표 (FCF, payout_ratio, operating_cf, dps_yoy_pct, 부채비율 …)

  Step 1  이산시간 Hazard
          → 연도별 삭감확률 P(t), 결측 native 처리 (baseline)

  Step 2  Cox PH (lifelines)
          → Hazard Ratio 해석 ("커버리지↑ → 위험 0.94배")

  Step 3  DeepHit (pycox)
          → 신경망 생존, 비례위험 가정 없이 시간-이벤트 분포 학습

  Step 4  Merton Distance-to-Default
          → 주가·변동성(시장신호)을 생존모델 피처로 투입
          ※ Merton = 시장/기업 신호. 거시(금리·CPI)는 별도 피처로 추가(혼동 금지).

[출력] 종목별 배당 생존곡선(1·3·5년) + SHAP 근거 + Calibration 보정확률

[벤치마크] Altman Z / Ohlson O / 부스팅 vs 생존모형 (C-index·PR-AUC 비교표)
```

**핵심 차별점**: "예/아니오"가 아니라 "언제 삭감될 확률이 얼마"인 생존곡선.

> **★ 라벨 정의 (핵심 연구 기여)**
>
> - 기존 "DPS 아무 하락=삭감"은 한국에서 22%(노이즈) — 미국 4%와 5배 차이.
> - 재정의 **'의미있는 삭감'** = 30%+ 감소 또는 배당중단 & 1년 내 회복 아님 → 한국 4.9% ≈ 미국 4%.
> - 효과: 한·미 동일 기준·동일 모델 가능 (교수 #3 정면 해결).
>   "표준 라벨 결함을 찾아 고침"이 연구 기여.
>
> **★ 정직한 한계**:
> 재무제표만으로 1년 앞 '의미있는 삭감' forward 예측은 천장이 낮음(ROC ~0.6).
> → 그래서 Merton(시장신호) 추가로 "재무가 못 본 위기를 시장이 먼저 본다"를 검증하는 게 핵심 실험.

---

### 3-3. [2층] Gem Screener — 보석 종목 필터 (개별주)

```
게이트(제외): 삭감 고위험(생존 hazard 상위) · 고배당 함정 · 재무 부실

4축 점수(Gem Score):
  안전성 30 → 커버리지·FCF·배당성향·부채·이자보상
  지속성 30 → ★생존확률/hazard★ + 삭감이력 + Merton DtD
  성장   20 → 연속 증배·DPS 추세
  가치   20 → 배당수익률 적정·Total Return·함정 아님
```

> **★ 검증(신뢰 축)**: 과거 데이터로 "Gem 상위가 실제로 덜 깎이고 더 벌었나"
> (삭감률·TR) → "내 기준이 검증됨"

---

### 3-4. [3층] LLM Agent — 자연어 운영

**모델**: Qwen2.5 14B(Ollama, 현재) → Qwen3 검토. function-calling.

**도구 목록**:
```
get_survival_curve(ticker)  → 종목 생존곡선 조회
get_gem_score(ticker)       → Gem Score 조회
run_fire_engine()           → FIRE 역산 계산
run_monte_carlo()           → P10/P50/P90 시뮬레이션
get_tax_optimization()      → ISA·연금저축 절세 전략
get_risk_alerts()           → WEAKENING 종목 경보
```

**예시**: "SCHD 월 50만 20년?" → `run_monte_carlo()` → "P50 월 ___만(화면 수치)"

> **교수 #2 답**: LLM은 인터페이스, 계산은 검증된 엔진.

---

### 3-5. 설명가능성 (SHAP + EBM)

```
EBM (interpret)
  = 유리상자 모델, 피처 기여함수 직접 플롯
  = "배당성향 90%↑ 구간 위험 급증" 시각화

SHAP
  = DeepHit 등 블랙박스 사후 설명
  = "왜 이 종목이 위험한가" 근거 제시

→ interpretable baseline(EBM) + deep model 설명(SHAP) 이중 전략
```

---

## 4. 데이터 (수치 통일)

- **한국**: DART 재무제표, 2013~2025. 전체 2,359행 중 학습 가능 관측치 **1,679** (210종목, 13피처).
  > ※ pykrx는 차단되어 미사용 — 수익률은 DART/정적 캐시 기반. ("pykrx 실시간" 표현 쓰지 말 것)
- **미국**: yfinance. 삭감 사례 희소(~4%)라 ML 대신 룰 기반 → 라벨 통일 후 SEC EDGAR로 ML 확장(향후)
- **시장/거시**: 주가·변동성(Merton), 금리·CPI·VIX(거시 피처, 향후)

---

## 5. 로드맵 (7월~9월)

### 7월 — Risk Model Engine

| 주차 | 내용 |
|---|---|
| W1~2 | 생존 라벨('의미있는 삭감', 30%+ 기준) 재정의 + 이산시간 Hazard |
| W3 | Cox PH (Hazard Ratio 표) |
| W4 | DeepHit + Altman/Ohlson/XGBoost 벤치마크 (C-index 비교표) |

### 8월 — Merton + EBM + Agent

| 주차 | 내용 |
|---|---|
| W1~2 | Merton DtD (yfinance 주가) → 생존모델 피처 추가 + ROC 개선 검증 |
| W3 | EBM(interpret) 구현 + SHAP 병행 |
| W4 | Qwen(2.5→3 확인) function-calling Agent + 도구 등록 |

### 9월 — 통합 + 발표

| 주차 | 내용 |
|---|---|
| W1~2 | Calibration(Platt) + 파이프라인 연결(Engine→Gem→Agent) + 위험 알림 |
| W3~4 | 데모 시나리오 + 벤치마크 표 완성 + 한계/향후 과제 정리 |

> 거시변수(#6) · 신규상장 Cold Start(업종평균 fallback)는 여유 시 보완.

---

## 6. 교수 피드백 대응표 (구현/계획 명시)

| 피드백 | 대응 | 상태 |
|---|---|---|
| 1 XGBoost 평범 | 생존분석(DeepHit)+EBM+Merton 하이브리드, 다모델 벤치마크 | 7~8월 |
| 2 Perplexity 대비 | 기억·감시·세금 레이어 + 검증엔진 호출 Agent | 일부 구현 / Agent 8월 |
| 3 미국 지원 | 라벨 통일(한·미 ~4~5%) → SEC EDGAR ML 확장 | 라벨 완료 / 데이터 향후 |
| 4 Cold Start | 업종 평균 생존확률 + Merton(주가만 있으면 가능) | 9월 |
| 5 DART 갱신 | 증분 수집·버전관리 | 향후(솔직히 인정) |
| 6 거시변수 | 금리·CPI·VIX 피처 (Merton은 시장신호로 별개) | 향후 |
| 7 규모 | KR+US+생존+Merton+Agent 통합 | 전체 확장 |

---

## 7. 라이브러리 / 보존 규칙

```bash
pip install pycox lifelines interpret shap   # 생존분석·EBM·XAI

# LLM: 현재 ollama qwen2.5:14b
# Qwen3 교체 시 태그 실재 확인 후:
ollama pull qwen3:14b
```

```python
# 2026 세법 상수 — 변경 금지
ISA_ANNUAL_LIMIT     = 4_000   # 만원
ISA_TAX_FREE_GENERAL = 500     # 만원
ISA_TAX_FREE_YOUTH   = 1_000   # 만원

# kr_3class_model.pkl (기존 XGBoost) — 삭제 금지, 벤치마크용 보존
```

---

## 8. 취업 포트폴리오 어필

**ML 연구 깊이**
생존분석(의료→금융 이식) · Merton+ML 하이브리드 · Calibration · 누수/라벨 진단

**응용 AI 폭**
Qwen function-calling Agent · EBM+SHAP 이중 설명 · 20단계 Pipe-and-Filter

**도메인 깊이**
2026 한국 세법(ISA 4,000) · DART 수집 · FIRE PMT 역산

**이력서 한 줄**:
> "배당 소득 위험에 생존분석(DeepHit·Cox)·Merton 구조모형 적용, 누수·라벨 진단으로 한·미 통일,
> 검증된 우량주 스크리너 구축, 검증 엔진을 호출하는 LLM Agent로 운영 시스템화 (XAI: SHAP/EBM)."

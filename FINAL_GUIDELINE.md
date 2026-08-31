# AI Cashflow OS — 최종 가이드라인
> 작성일: 2026-06-30 | 졸업 발표 목표: 2026년 9월

---

## 0. 한 줄 포지셔닝

> **"한국인을 위한 글로벌 배당 포트폴리오 운영 시스템 — 기억하고, 감시하고, 최적화한다"**

---

## 1. 왜 이걸 써야 하는가 (경쟁자 대비)

### vs Perplexity / ChatGPT / Claude
일회성 Q&A 도구 vs 운영 시스템의 차이.

| 항목 | 범용 AI (Perplexity 등) | AI Cashflow OS |
|---|---|---|
| 포트폴리오 기억 | ❌ 매번 다시 설명 | ✅ 저장 + 변화 추적 |
| 실시간 한국 시장 데이터 | ❌ 모름 (hallucination 위험) | ✅ pykrx + DART 실데이터 |
| 한국 계좌 구조 이해 | ❌ ISA/연금저축 개념 모호 | ✅ 계좌별 세금 최적화 계산 |
| 자동 감시 / 알림 | ❌ 물어봐야 대답 | ✅ INTACT→WEAKENING 자동 탐지 |
| FIRE 역산 계산 | △ 대략적 추정 | ✅ PMT 공식 기반 정확한 역산 |
| 배당 삭감 예측 | ❌ 불가 | ✅ 생존분석 ML 모델 |
| Monte Carlo 시뮬레이션 | ❌ 불가 | ✅ P10/P50/P90 1,000회 |

**핵심 한 줄**: Perplexity는 "물어보면 대답하는 도구"고, AI Cashflow OS는 "알아서 관리해주는 시스템"이다.

### vs 더리치 (The Rich)
가장 가까운 국내 경쟁자. 포트폴리오 추적 + 배당 캘린더까지는 됨.

| 항목 | 더리치 | AI Cashflow OS |
|---|---|---|
| 배당 캘린더 | ✅ | ✅ |
| FIRE 역산 | ❌ | ✅ |
| 세금 최적화 | ❌ | ✅ ISA·연금저축 2026 세법 |
| ML 위험 예측 | ❌ | ✅ 생존분석 기반 |
| AI 설명 | ❌ | ✅ SHAP + EBM |
| LLM 자연어 운영 | ❌ | ✅ Qwen3 function-calling |

### vs Wealthfront (글로벌 최고 수준)
AI 포트폴리오 자동화까지 됨. 단, 미국 전용.

| 항목 | Wealthfront | AI Cashflow OS |
|---|---|---|
| AI 포트폴리오 최적화 | ✅ | ✅ |
| 배당 자동화 | ✅ | ✅ |
| 한국 ISA / 연금저축 | ❌ 모름 | ✅ |
| 금융소득종합과세 관리 | ❌ | ✅ 2,000만원 임계점 |
| 한국 주식 ML 예측 | ❌ | ✅ DART 데이터 기반 |

**포지셔닝**: 더리치보다 스마트하고, Wealthfront보다 한국 친화적.

---

## 2. 타겟 사용자 재정의

### 기존 타겟 (틀렸던 방향)
> KR 배당주 고액 투자자

### 수정된 타겟
> **SCHD·JEPI·VYM 같은 미국 ETF를 ISA·연금저축으로 투자하는 한국 일반 투자자**

실제 한국 투자자의 전형적 포트폴리오:
```
ISA 계좌       → SCHD, JEPI (월배당 ETF)
연금저축 계좌  → S&P500 ETF, NASDAQ100
직투 계좌      → 삼성전자, 일부 고배당주
```
이 세 계좌를 통합해서 FIRE 역산 + 세금 최적화 + 리스크 감시를 한 번에 해주는 도구가 없다.

---

## 3. AI 스택 — 최종 업그레이드 버전

### 3-1. 기존 vs 업그레이드 비교

| 레이어 | 기존 | 업그레이드 | 이유 |
|---|---|---|---|
| 예측 모델 | XGBoost 단일 | 생존분석 스택 + EBM | 차별성, 연구 깊이 |
| 생존분석 | 없음 | 이산시간 → Cox → DeepHit | SOTA 방향성 |
| 구조모형 | 없음 | Merton (하이브리드) | 금융이론 깊이 |
| 설명가능성 | SHAP만 | SHAP + EBM 병행 | 2025 베스트 프랙티스 |
| LLM | Ollama EXAONE (미연동) | **Qwen3 14B** function-calling | Qwen2.5는 레거시 |
| 벤치마크 | 없음 | Altman·Ohlson + XGBoost | 엄밀성 증명 |
| 캘리브레이션 | 없음 | Platt Scaling / Isotonic | 확률값 신뢰성 |

---

### 3-2. 최종 AI 스택 상세

#### [1층] Risk Model Engine — 배당 생존 예측

```
[입력] DART 재무제표 (FCF, payout_ratio, operating_cf, dps_yoy_pct ...)
   ↓
[Step 1] 이산시간 Hazard Model
   → 연도별 배당 삭감 확률 P(t) 추정
   → 가장 단순한 생존분석 베이스라인

[Step 2] Cox Proportional Hazards
   → 피처별 hazard ratio 해석 가능
   → "payout_ratio 1 증가 시 hazard 1.3배" 같은 설명

[Step 3] DeepHit
   → 딥러닝 생존분석 (DeepSurv보다 최신, C-index 우수)
   → 비례위험 가정 없이 시간-이벤트 분포 직접 학습

[Step 4] Merton Distance-to-Default (하이브리드)
   → 시장 데이터 (주가·부채) → Distance-to-Default 계산
   → 생존모델의 추가 피처로 투입
   → "재무제표 + 시장신호" 통합

[출력] 종목별 배당 생존곡선 (1·3·5년 생존확률)
       + SHAP 피처 기여도
       + Calibration 보정된 확률값

[벤치마크] Altman Z-score / Ohlson O-score / 기존 XGBoost 대비 성능 비교
```

**핵심 차별점**: 배당 삭감을 "예/아니오"가 아니라 "언제 삭감될 확률이 얼마"로 표현하는 생존곡선.

#### [2층] Gem Screener — 보석 종목 필터

```
4축 스코어링:
  안전성   30pt → 생존모델 생존확률 + Merton DD
  지속성   30pt → 연속배당연수 + payout 안정성
  성장성   20pt → DPS YoY + 매출성장률
  가치     20pt → 배당수익률 vs 업종평균

게이트:
  생존확률 < 50% → 자동 제외
  EBM 위험 신호 → 경고 플래그

[출력] 점수 상위 종목 + 과거 실제 배당 유지율 검증
```

#### [3층] LLM Agent — 자연어 운영

```
모델: Qwen3 14B (Ollama) — function-calling 특화
      ↳ Qwen2.5 대비: agent tool-use 벤치마크 GPT-4o 근접

도구 목록 (function-calling):
  - get_portfolio_status()    → 포트폴리오 현황 조회
  - run_fire_engine()         → FIRE 역산 계산
  - run_monte_carlo()         → P10/P50/P90 시뮬레이션
  - get_tax_optimization()    → ISA·연금저축 절세 전략
  - get_survival_curve(ticker) → 종목 생존곡선 조회
  - get_risk_alerts()         → WEAKENING 종목 경보

사용 예시:
  사용자: "SCHD 월 50만원씩 20년 사면 얼마 받아?"
  Agent → run_monte_carlo() 호출 → "P50 기준 월 312만원, P10은 189만원"

  사용자: "내 ISA 계좌 세금 얼마나 아낄 수 있어?"
  Agent → get_tax_optimization() 호출 → 실제 수치 기반 절세 전략 반환
```

---

### 3-3. 설명가능성 전략 (SHAP + EBM)

```
EBM (Explainable Boosting Machine)
  → 자체가 유리상자 모델
  → 피처별 기여 함수를 직접 플롯
  → "payout_ratio 90% 구간에서 위험도 급증" 시각화 가능
  → 금융 규제 환경에서 선호 (설명 의무)

SHAP (TreeExplainer / DeepExplainer)
  → 블랙박스 모델(DeepHit 등) 사후 설명
  → 종목별 "왜 WEAKENING인가" 근거 제시

2025 베스트 프랙티스:
  EBM으로 interpretable baseline → SHAP으로 deep model 설명
  → 둘 다 쓰면 면접에서 "설명가능 AI를 제대로 아는 사람"으로 보임
```

---

## 4. 핵심 차별화 포인트 요약 (발표용)

### 기술적 차별성 (교수님 피드백 1번 대응)
- XGBoost → 생존분석 (이산시간 → Cox → DeepHit) 진화 구조
- Merton 구조모형 + ML 하이브리드 — 재무제표 + 시장신호 통합
- EBM glass-box + SHAP 이중 설명가능성

### 서비스 차별성 (교수님 피드백 2번 대응)
- Perplexity: 물어보면 대답 / 우리: 알아서 감시
- INTACT → WEAKENING 자동 탐지 + 알림
- 한국 ISA·연금저축 계좌 구조 인식 → 세금 최적화

### 데이터 차별성
- DART 재무제표 한국 고유 데이터 (ChatGPT가 못 가진 것)
- pykrx 실시간 수익률 (Perplexity hallucination 없음)
- 2,359행 KR + 433행 US 학습 데이터

---

## 5. 구현 로드맵 (7월~9월)

### 7월 — Risk Model Engine 구축

**Week 1~2: 생존 라벨 + 이산시간 Hazard**
```python
# dividend_dataset.csv에 생존 라벨 추가
df['time_to_event'] = ...   # 배당 유지 연수
df['event']         = ...   # 1=삭감, 0=censored
# pycox로 이산시간 hazard 모델 학습
```

**Week 3: Cox PH**
```python
from lifelines import CoxPHFitter
cph = CoxPHFitter()
cph.fit(df, duration_col='time_to_event', event_col='event')
cph.print_summary()  # hazard ratio 표
```

**Week 4: DeepHit**
```python
from pycox.models import DeepHit
# 신경망 기반 생존분석, 비례위험 가정 없음
# Altman·Ohlson·XGBoost 벤치마크와 C-index 비교
```

### 8월 — Agent + Merton + EBM

**Week 1~2: Qwen3 function-calling Agent**
```python
# utils/ollama_client.py 수정
# Qwen2.5 → Qwen3:14b
OLLAMA_MODEL = "qwen3:14b"  # 이것만 바꾸면 됨

# function-calling 도구 등록
tools = [
    {"name": "run_fire_engine", "description": "..."},
    {"name": "run_monte_carlo", "description": "..."},
    {"name": "get_survival_curve", "description": "..."},
    ...
]
```

**Week 3: Merton Distance-to-Default**
```python
# yfinance 일별 주가 + 부채 데이터
# Black-Scholes로 자산가치·변동성 추정
# Distance-to-Default → 생존모델 피처 추가
```

**Week 4: EBM 구현**
```python
from interpret.glassbox import ExplainableBoostingClassifier
ebm = ExplainableBoostingClassifier()
ebm.fit(X_train, y_train)
# 피처별 기여 함수 시각화
```

### 9월 — 통합 + 발표 준비

**Week 1~2:**
- Calibration (Platt Scaling) 적용
- 전체 파이프라인 연결 (Risk Engine → Gem Screener → Agent)
- 포트폴리오 모니터링 + WEAKENING 알림 연결

**Week 3~4:**
- 발표 데모 시나리오 작성
- 벤치마크 비교 표 완성 (Altman·Ohlson·XGBoost·Cox·DeepHit)
- 한계 및 향후 과제 정리

---

## 6. 발표 시나리오 (데모 순서)

```
1. 사용자 입력
   "저 35살, 월급 500만원, ISA에 SCHD 2,000만원 있어요.
    50세에 월 200만원 배당 받고 싶어요."

2. Agent (Qwen3) 자동 도구 호출
   → run_fire_engine()   : 월 87만원 더 적립 필요
   → run_monte_carlo()   : P50 기준 50세에 월 213만원 달성 확률 68%
   → get_tax_optimization(): ISA 한도 여유 2,000만원, 연금저축 추가 납입 권장

3. 위험 감시
   → get_risk_alerts()   : 보유 종목 JEPI 생존확률 3년 후 72% (정상)
   → WEAKENING 종목 없음

4. 자연어 요약 (Qwen3 생성)
   "현재 페이스 유지 시 50세 달성 확률 68%입니다.
    월 87만원 추가 적립 시 달성 확률 89%로 상승합니다.
    ISA 한도 2,000만원이 여유 있어 SCHD 추가 편입을 권장합니다."
```

---

## 7. 교수님 피드백 최종 대응표

| 피드백 | 대응 | 구현 여부 |
|---|---|---|
| XGBoost 평범 | 생존분석 (DeepHit) + EBM + Merton 하이브리드 | 7~8월 구현 |
| Perplexity 대비 차별점 | 기억·감시·한국 세금 레이어 — 운영 시스템 포지셔닝 | 일부 기존 구현 |
| 미국 지원 부족 | US ETF 중심으로 재포지셔닝 (SCHD·JEPI·VYM) | 방향 전환 |
| 신규 상장 Cold Start | 업종 평균 생존확률 fallback | 9월 보완 |
| DART 갱신 구조 없음 | 향후 과제로 솔직하게 인정 | 한계 처리 |
| 거시경제 변수 없음 | Merton DD (시장신호) + 기존 macro_regime.py | 부분 대응 |
| 프로젝트 규모 작음 | KR + US + 거시 + LLM Agent + 생존분석 통합 | 전체 구조 확장 |

---

## 8. 핵심 라이브러리

```bash
pip install pycox          # DeepHit, DeepSurv, 이산시간 hazard
pip install lifelines      # Cox PH, Kaplan-Meier
pip install interpret      # EBM (Microsoft InterpretML)
pip install shap           # SHAP (기존)
pip install ollama         # Qwen3 연동 (기존)

# Ollama 모델 교체
ollama pull qwen3:14b
# 또는 16GB VRAM이면
ollama pull qwen3:30b-a3b  # MoE, 실제 활성 3B
```

---

## 9. 취업 포트폴리오 관점 어필 포인트

```
ML 연구 깊이:
  ✅ 생존분석 (의료 → 금융 적용) — 창의적 문제 정의
  ✅ Merton 구조모형 + ML 하이브리드 — 금융공학 이해
  ✅ Calibration — 프로덕션 ML 이해

응용 AI 폭:
  ✅ Qwen3 function-calling Agent — 2026 트렌드
  ✅ EBM glass-box + SHAP 이중 설명 — XAI 실무 수준
  ✅ 19단계 Pipe-and-Filter 파이프라인 — 시스템 설계 능력

도메인 깊이:
  ✅ 2026 한국 세법 (ISA 4,000만원 한도) 반영
  ✅ DART API + pykrx 실데이터 수집 경험
  ✅ FIRE 역산 공식 (PMT) 직접 구현
```

---

## 10. 절대 건드리지 말아야 할 것

```python
# 2026 세법 상수 — 변경 금지
ISA_ANNUAL_LIMIT     = 4_000   # 만원
ISA_TAX_FREE_GENERAL = 500     # 만원
ISA_TAX_FREE_YOUTH   = 1_000   # 만원
```

기존 XGBoost 모델(`kr_3class_model.pkl`)은 삭제하지 말고 벤치마크 비교용으로 유지.

---

*이 문서는 졸업 발표 준비 및 취업 포트폴리오 구성을 위한 최종 가이드라인입니다.*
*구현 순서: Risk Engine (7월) → Qwen3 Agent + Merton + EBM (8월) → 통합 + 발표 (9월)*

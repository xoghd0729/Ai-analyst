AI Dividend Income OS — 시스템 아키텍처 & AI 스택 (v2)

한 줄 정의:
"배당 소득의 '위험'을 은행급 신용위험 방법론으로 모델링하고, 그 위에 검증된 우량주
 스크리너와 LLM Agent를 올린 — 위험인지 소득 운영 시스템."

설계 철학: 정확한 '예측'을 파는 게 아니라, 불확실성에 강건한 '운영'을 판다.
ML 예측은 점쟁이가 아니라 여러 위험 신호 중 하나(조연)로 쓴다.


────────────────────────────────────────
0. 3층 구조 (한눈에)
────────────────────────────────────────

  [3층] LLM Agent (운영·인터페이스)
        자연어 → 검증된 엔진 도구 호출 → 리포트·알림·리밸런싱 제안
              ↑  (function-calling)
  [2층] Gem Screener (보석 스크리너)
        4축 점수(안전·지속·성장·가치) + 게이트 → 우량주 랭킹 → 과거 검증
              ↑  ('지속성' 축 입력)
  [1층] Risk Model Engine (위험 모델 엔진)
        생존분석(DeepSurv·Cox·hazard) + Merton(시장) → 종목별 배당 생존곡선·위험점수
              ↑  (데이터)
  [0층] Data Layer
        DART(한국)·SEC EDGAR(미국)·주가(yfinance)·거시(금리·CPI·VIX)


────────────────────────────────────────
1. Layer 1 — Risk Model Engine (모델링 깊이)
────────────────────────────────────────

목적: "이 배당이 1·3·5년 뒤까지 살아남을 확률"(생존곡선) + 위험점수 산출.
핵심 전환: 분류(삭감 예/아니오) → 생존(time-to-event, lifetime PD).

사용 AI/기법:
  · 이산시간 hazard (Gradient Boosting / XGBoost-AFT)
      - 연도별 패널 데이터에 맞는 생존모형. 결측 native 처리. (현 baseline)
  · Cox 비례위험 (lifelines) — 고전 표준 벤치마크 + Hazard Ratio 해석
  · ★ DeepSurv / DeepHit (PyTorch · pycox) — 신경망 생존모형 (딥러닝 크레딧)
      - 비선형·시간가변·경쟁위험. "ML 생존 > 선형 Cox"를 보이는 핵심
  · Merton Distance-to-Default — 주가·자산변동성 기반 시장형 구조모형
      - 재무가 못 보는 '갑작스러운 위기'를 시장이 먼저 본다는 가설 검증
  · Calibration (Platt / Isotonic, sklearn) — "82%가 진짜 82%"가 되게 확률 보정
  · 설명: SHAP(TreeExplainer) + EBM(Explainable Boosting Machine, 글래스박스)

벤치마크(엄밀성):
  · Altman Z-Score, Ohlson O-Score (고전 distress) vs 우리 생존모형
  · 6개 분류기(LR/RF/XGB/LGBM/CatBoost/HistGBM) 비교표

라벨 정의(핵심 발견 반영):
  · '의미있는 삭감' = 30%+ 감소 또는 배당중단 & 1년 내 회복 아님
  · 한국 4.9% ≈ 미국 4% → 한·미 동일 기준·동일 모델 (교수 #3 해결)

출력: { 종목: 생존곡선(1/3/5y), 삭감 hazard, Merton 거리, 보정확률, SHAP 근거 }


────────────────────────────────────────
2. Layer 2 — Gem Screener (보석 스크리너 + 검증)
────────────────────────────────────────

목적: 많은 종목을 '걸러서' 검증된 우량 배당주(보석)만 남긴다.

게이트 (하나라도 걸리면 제외):
  · 삭감 고위험 (Layer1 hazard 상위) · 고배당 함정 · 재무 부실

4축 가중 점수 (Gem Score):
  | 축 | 가중 | 지표 |
  |---|---|---|
  | 안전성 | 30% | 배당커버리지·FCF·배당성향·부채·이자보상 |
  | 지속성 | 30% | ★Layer1 생존확률/hazard★ + 삭감이력 + Merton |
  | 성장   | 20% | 연속 증배 연수·DPS 추세 |
  | 가치   | 20% | 배당수익률 적정·Total Return·함정 아님 |

검증 (★이 프로젝트의 신뢰 축★):
  · 과거 데이터로 "Gem Score 상위 종목이 실제로 덜 깎이고(삭감률) 더 벌었나(Total Return)"
  · 상위 vs 하위 분위 비교, 백테스트 → "내 기준이 검증됐다"

출력: 랭킹된 보석 리스트 + 점수 분해 + 근거


────────────────────────────────────────
3. Layer 3 — LLM Agent (응용 AI / 시스템 깊이)
────────────────────────────────────────

목적: 자연어로 묻고, Agent가 검증된 엔진을 '도구'로 호출해 답한다.
       → 교수 #2("왜 LLM 아닌가") 정면 답: LLM은 인터페이스, 계산은 검증 엔진.

사용 AI:
  · LLM: Qwen2.5 14B (Ollama 로컬) — function-calling 지원 / 필요시 교체 가능
  · Agent 프레임: 도구 라우터(자체) 또는 LangChain/LlamaIndex
  · (선택) RAG: 재무 공시·리포트 검색 결합

도구(Tools) = 검증된 엔진들:
  · get_survival(ticker)      → Layer1 생존곡선·위험
  · get_gem_score(ticker)     → Layer2 점수·등급
  · run_fire(params)          → FIRE 역산
  · run_montecarlo(portfolio) → 소득 시뮬레이션
  · optimize_tax(portfolio)   → 절세

출력: "내 포트폴리오 점검해줘" → 위험 종목·생존확률·달성나이·리밸런싱 제안 (검증 수치 기반)


────────────────────────────────────────
4. AI/모델 스택 요약
────────────────────────────────────────

| 기법 | 라이브러리 | 역할 | 포트폴리오 어필 |
|---|---|---|---|
| 이산시간 hazard | sklearn/xgboost | 연도별 생존 baseline | 생존분석 |
| Cox PH | lifelines | 고전 표준·해석(HR) | 통계 모델링 |
| DeepSurv/DeepHit | pycox(PyTorch) | 신경망 생존 | 딥러닝 |
| Merton DtD | numpy/scipy | 시장형 구조모형 | 금융공학 |
| Calibration | sklearn | 확률 신뢰도 | ML 성숙도 |
| SHAP / EBM | shap / interpret | 설명가능 AI | XAI |
| Altman/Ohlson | (수식) | 고전 벤치마크 | 비교 엄밀성 |
| LLM Agent | Qwen2.5+function-calling | 운영 인터페이스 | 응용 AI/에이전트 |


────────────────────────────────────────
5. 기술 스택 / 데이터
────────────────────────────────────────

- 데이터: DART(한국), SEC EDGAR(미국), yfinance(주가·변동성), 거시(금리·CPI·VIX·환율)
- 백엔드: FastAPI · Pipe-and-Filter 파이프라인 · PostgreSQL+파일 폴백
- 모델: scikit-learn, lifelines, pycox(PyTorch), xgboost/lightgbm/catboost, shap, interpret
- 프론트: React · Vite · Recharts
- LLM: Ollama(Qwen2.5 14B) + function-calling
- 테스트/검증: pytest, GroupKFold, Out-of-Time backtest


────────────────────────────────────────
6. 이력서 한 줄 (목표 산출물)
────────────────────────────────────────

"배당 소득 위험에 생존분석(DeepSurv·Cox)과 Merton 구조모형을 적용하고, 누수·라벨 진단으로
 한·미 시장을 통일. 검증된 우량주 스크리너(Gem Score)를 구축하고, 그 엔진을 호출하는
 LLM Agent로 운영 시스템화. (XAI: SHAP/EBM, 검증: GroupKFold·Out-of-Time backtest)"

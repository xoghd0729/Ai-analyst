# AI 현금흐름 운영체제 — AGENTS.md

## 프로젝트 핵심 정체성

> **"미래 월급형 현금흐름을 설계·분석·방어·관리하는 AI 운영체제"**

수익률 예측도, 가격 예측도 아니다.  
**배당이라는 현금흐름을 중심으로 사용자의 인생을 재설계하는 시스템**이다.

---

## 핵심 흐름 (이 흐름이 메인이다)

```
입력 (나이·투자금·목표배당)
  → 거시경제 레짐 감지        (Macro Regime OS)
  → 포트폴리오 생성            (5축 자산 유니버스)
  → 미래 현금흐름 시뮬레이션  (Monte Carlo + FIRE)
  → 리스크 분석 + 방어         (ML + 스트레스 테스트 + 행동편향)
  → AI 서술형 행동 제안        (Storytelling + Advisor)
```

---

## 아키텍처 (2026.05 기준)

### Pipe-and-Filter 파이프라인 (api/pipeline/)

기존 portfolio.py 1,960줄 God-Function을  
17개 독립 Filter 클래스로 분리 (SRP 준수).

```
api/pipeline/
  context.py   # 파이프라인 공유 상태 (PipelineContext)
  base.py      # BaseFilter 추상 클래스
  filters.py   # 17개 Filter 구현
  runner.py    # RecommendationPipeline 오케스트레이터
```

**Filter 실행 순서:**
MacroRegime → AxisWeight → AssetPicker → WeightAllocator  
→ Summarize → Projection → Rebalancing → StressTest  
→ SectorExposure → Calendar → RiskAlert → FireEngine  
→ MonteCarlo → TaxOptimizer → BehavioralFinance  
→ PortfolioHealth → Storytelling

### DB 레이어 (db/)

파일 캐시(JSON/CSV) → PostgreSQL 마이그레이션 완료.

```
db/
  models.py      # SQLAlchemy ORM (4개 테이블)
  repository.py  # 데이터 접근 레이어 (DB 우선 + 파일 fallback)
```

테이블: `kr_yield_cache` / `ml_predictions` / `etf_quality` / `asset_metadata`  
마이그레이션: `python scripts/migrate_cache_to_db.py`

### 주요 연동 (2026.05 신규)

1. **Macro → Monte Carlo 조건부 확률**  
   거시 레짐에 따라 배당 삭감 확률 동적 조정  
   경기침체기 ×1.8 / 금리상승기 ×1.3 / 안정성장기 ×0.7

2. **2026 ISA 세법 (tax_optimizer.py)**  
   납입한도 연 4,000만원 / 비과세 한도 일반형 500만원·청년형 1,000만원

---

## 핵심 사용자 가치 (발표 메시지)

| 지표 | 의미 |
|------|------|
| 월 30만원 배당 | 통신비·구독료 자동화 |
| 월 80만원 배당 | 교통비·식비 커버 |
| 월 150만원 배당 | 주거비+식비 커버 (Lean FIRE 진입) |
| 월 300만원 배당 | 생활비 100% 커버 |
| 월 500만원 배당 | 경제적 자유 달성 |

---

## 유틸리티 모듈 (utils/)

| 모듈 | 역할 |
|------|------|
| universe.py | 5축 자산 유니버스 정의 |
| macro_regime.py | 5레짐 거시경제 분류 |
| dividend_projection.py | 20년 배당 성장 시뮬레이션 |
| fire_engine.py | FIRE 역산 (Lean/Normal/Fat) |
| monte_carlo.py | 1,000회 YoC 시뮬레이션 + 레짐 연동 |
| tax_optimizer.py | ISA·연금저축 세금 최적화 (2026) |
| behavioral_finance.py | 8가지 투자 행동편향 탐지 |
| ai_advisor.py | 자연어 Q&A (14 인텐트) |
| storytelling.py | 서술형 리포트 생성 |
| stress_test.py | 위기 시나리오 테스트 |

---

## 개발 원칙

- **Explainable AI**: GPT가 추천하는 게 아니라 데이터 기반 분석 엔진. LLM은 설명 레이어.
- **현금흐름 중심**: 수익률·가격보다 배당이라는 실현 가능한 현금흐름이 핵심.
- **한국 투자자 현실**: ISA·연금저축·KRX 세법 기반. 미국 기준 클론 아님.
- **의사결정 보조**: "실제 투자 추천"이 아닌 "의사결정 보조 시스템"으로 포지셔닝.

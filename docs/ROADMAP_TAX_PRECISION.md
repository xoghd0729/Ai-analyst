# Week 2: 세금 정밀화 로드맵

> 목표: 절세 시뮬레이션을 "참고용"에서 "실전 신뢰 가능" 수준으로
> 산출물: 해외양도세 + 종합과세 누진세율 + 건보료 피부양자 시뮬레이션

---

## 0. 현재 한계

`utils/tax_optimizer.py` (2026 세법 반영됨)는 강력하지만 다음이 빠져 있다:

| 빠진 항목 | 사용자 영향 |
|---|---|
| 해외주식 양도세 (250만원 공제) | 미국 배당주 매도 시 양도차익 계산 불가 |
| 종합과세 6~45% 누진세율 | 임계점 초과 시 추가세 추정이 평균값에 의존 |
| 건보료 피부양자 탈락 (연소득 2,000만원) | 은퇴자에게 결정적인 변수 누락 |
| 분리과세 vs 종합과세 비교 | 사용자가 "어느 게 유리한가?" 답을 못 받음 |
| 미국 원천징수 15% 외국납부세액공제 | 이중과세 절감 미반영 |

---

## 1. 작업 단위 분해 (Day 10~12)

### Day 10: 해외주식 양도세 모듈

**파일**: `utils/foreign_capital_gains_tax.py` (신규)

**핵심 세법**:
- 양도소득세율: **22% (지방세 포함)**
- 기본공제: **연 250만원** (양도차익 합산 기준)
- 환율 적용: **매입·매도 시점 기준환율** (한국 원화 환산 후 차익 계산)
- 양도일 5월 종합소득 신고 시 신고 의무

**함수 시그니처**:
```python
def calc_foreign_capital_gains_tax(
    transactions: list[dict],   # [{ticker, buy_date, buy_usd, sell_date, sell_usd, shares, fx_buy, fx_sell}, ...]
    base_deduction_만원: float = 250,
) -> dict:
    """
    반환:
    {
        "total_gain_원": int,            # 총 양도차익 (원화 환산)
        "taxable_gain_원": int,           # 공제 후 과세표준
        "tax_due_원": int,                # 납부세액 (22%)
        "effective_tax_rate_pct": float,  # 실효세율
        "by_ticker": [                   # 종목별 상세
            {"ticker": "SCHD", "gain_원": ..., "fx_impact_원": ...},
            ...
        ],
        "fx_gain_원": int,                # 환차익 (참고용)
        "optimization_tips": [str],      # "12월 말 손실종목 매도로 상쇄" 등
    }
    """
```

**Cursor 프롬프트**:
```
utils/foreign_capital_gains_tax.py 작성:
1. 위 시그니처대로 함수 구현
2. 환율 데이터는 utils/macro_data.py의 USD/KRW 시리즈 활용
3. optimization_tips는 4가지 룰 베이스:
   - "양도차익 250만원 초과 → 일부 종목 다음 해로 매도 분산"
   - "손실 종목 보유 시 같은 해 매도로 상쇄 가능"
   - "환차익이 양도차익의 50% 이상 → 환헤지 고려"
   - "양도세 신고일(5월) D-30 알림"
4. tests/test_foreign_capital_gains_tax.py에 5개 테스트
```

---

### Day 11: 종합과세 누진세율 정밀화

**파일**: `utils/tax_optimizer.py` 수정 + `utils/tax_brackets.py` (신규)

**한국 종합소득세 누진세율 (2026 기준)**:
| 과세표준 | 세율 | 누진공제 |
|---|---|---|
| 1,400만원 이하 | 6% | 0 |
| 5,000만원 이하 | 15% | 126만원 |
| 8,800만원 이하 | 24% | 576만원 |
| 1.5억원 이하 | 35% | 1,544만원 |
| 3억원 이하 | 38% | 1,994만원 |
| 5억원 이하 | 40% | 2,594만원 |
| 10억원 이하 | 42% | 3,594만원 |
| 10억원 초과 | 45% | 6,594만원 |

**+ 지방소득세 10% 별도** → 실효 최고 49.5%

**현재 코드 문제**:
```python
# 기존 (정확하지 않음)
estimated_extra_tax_만원 = (annual_div - 2000) * 0.35  # 단순 35% 가정
```

**개선**:
```python
# tax_brackets.py
def calc_progressive_tax(taxable_income_만원: float) -> dict:
    """
    반환:
    {
        "national_tax_만원": float,    # 국세
        "local_tax_만원": float,       # 지방세 (10%)
        "total_tax_만원": float,
        "marginal_rate_pct": float,    # 한계세율
        "effective_rate_pct": float,   # 실효세율
        "bracket_name": str,           # "5,000만원 이하 (15%)"
    }
```

**Cursor 프롬프트**:
```
1. utils/tax_brackets.py 신규 작성 (위 시그니처)
2. utils/tax_optimizer.py의 calc_tax_optimizer() 내부에서
   estimated_extra_tax_만원 계산을 calc_progressive_tax() 사용으로 교체
3. 반환 구조에 새 필드 추가:
   - "marginal_rate_pct": 한계세율
   - "effective_rate_pct_after_local": 지방세 포함 실효세율
   - "bracket_name": 적용 구간 이름
4. tests/test_tax_optimizer.py의 기존 ComprehensiveTaxLogic 클래스에 누진세율 검증 추가
5. 절대 ISA 2026 상수(4000/500/1000)는 건드리지 말 것
```

---

### Day 12: 건보료 피부양자 + 분리/종합과세 비교

**파일**: `utils/health_insurance_premium.py` (신규) + `utils/tax_strategy_comparator.py` (신규)

**건보료 피부양자 자격 (2026)**:
- 연 합산소득 ≤ 2,000만원
- 부동산 소득 1억원 초과 시 즉시 탈락
- 사업소득 500만원 초과 시 즉시 탈락
- 탈락 시 지역가입자 전환 → **소득·재산 합산 보험료 부과** (월 평균 15~30만원)

**함수**:
```python
def assess_dependent_status(
    annual_div_만원: float,
    annual_pension_만원: float = 0,
    annual_other_income_만원: float = 0,
    has_property_income: bool = False,
    is_currently_dependent: bool = True,
) -> dict:
    """
    반환:
    {
        "is_eligible": bool,
        "total_income_만원": float,
        "threshold_gap_만원": float,    # 2,000까지 남은 여유
        "annual_premium_estimate_만원": float,  # 탈락 시 예상 보험료
        "risk_level": str,    # "safe" / "warning" / "danger"
        "monthly_premium_estimate_만원": float,
        "action_items": [str],
    }
    """
```

**분리과세 vs 종합과세 비교기**:
```python
def compare_separated_vs_comprehensive(
    annual_div_만원: float,
    other_income_만원: float = 0,
) -> dict:
    """
    배당소득 2,000만원 초과 시 두 가지 선택지 비교:
    1. 분리과세 신청 (15.4% 고정)
    2. 종합과세 (다른 소득과 합산해 누진세율)

    반환:
    {
        "separated_tax_만원": float,
        "comprehensive_tax_만원": float,
        "recommended": "separated" / "comprehensive",
        "saving_amount_만원": float,
        "break_even_income_만원": float,  # 어느 소득에서 역전되는가
    }
    """
```

**Cursor 프롬프트**:
```
1. utils/health_insurance_premium.py 작성 (위 시그니처)
   - 건보료 계산식은 2026 국민건강보험공단 공식 적용
   - 사용자 케이스 5종 테스트 케이스 포함

2. utils/tax_strategy_comparator.py 작성 (위 시그니처)
   - 분리과세 15.4% vs 종합과세 누진세율 비교
   - 절세 금액과 손익분기점 자동 산출

3. utils/tax_optimizer.py의 반환 구조 최상위에 추가:
   - "health_insurance": assess_dependent_status() 결과
   - "tax_strategy": compare_separated_vs_comprehensive() 결과

4. 새 필터 추가: api/pipeline/filters.py에 TaxStrategyFilter
   - TaxOptimizerFilter 다음에 실행
   - ctx.tax_strategy, ctx.health_insurance 채움

5. tests/ 디렉토리에 3개 파일 신규 작성:
   - test_health_insurance_premium.py
   - test_tax_strategy_comparator.py
   - test_tax_strategy_filter.py
```

---

## 2. 완료 정의 (Definition of Done)

```bash
# 1. 해외양도세 계산 동작
python -c "
from utils.foreign_capital_gains_tax import calc_foreign_capital_gains_tax
r = calc_foreign_capital_gains_tax([
    {'ticker':'SCHD', 'buy_date':'2023-01-01', 'buy_usd':70, 'sell_date':'2025-01-01', 'sell_usd':80, 'shares':100, 'fx_buy':1300, 'fx_sell':1380}
])
assert r['tax_due_원'] > 0
print(f'✓ 양도세 {r[\"tax_due_원\"]:,}원')
"

# 2. 누진세율 정확도
python -c "
from utils.tax_brackets import calc_progressive_tax
# 과세표준 5000만원 (15% 구간) → 5000*0.15 - 126 = 624만원 국세
r = calc_progressive_tax(5000)
assert abs(r['national_tax_만원'] - 624) < 1
print(f'✓ 누진세 {r[\"total_tax_만원\"]}만원, 실효세율 {r[\"effective_rate_pct\"]:.1f}%')
"

# 3. 건보료 시뮬레이션
python -c "
from utils.health_insurance_premium import assess_dependent_status
r = assess_dependent_status(annual_div_만원=2500)
assert r['is_eligible'] is False
assert r['annual_premium_estimate_만원'] > 0
print(f'✓ 피부양자 탈락, 월 보험료 {r[\"monthly_premium_estimate_만원\"]:.1f}만원')
"

# 4. 분리/종합과세 비교
python -c "
from utils.tax_strategy_comparator import compare_separated_vs_comprehensive
r = compare_separated_vs_comprehensive(annual_div_만원=3000, other_income_만원=5000)
assert r['recommended'] in ['separated', 'comprehensive']
print(f'✓ 추천: {r[\"recommended\"]}, 절세 {r[\"saving_amount_만원\"]}만원')
"

# 5. 파이프라인 통합
pytest tests/test_tax_strategy_filter.py -v
```

---

## 3. 의존성 추가

없음. 모두 표준 라이브러리(math, datetime, dataclasses)로 구현.

---

## 4. 사용자 가치 메시지 (스토리텔링 연동)

새 모듈이 추가되면 `utils/storytelling.py`도 다음 문구를 생성하도록 수정:

```
"⚠️ 현재 포트폴리오는 연 배당 2,300만원 예상으로,
   금융소득종합과세 임계점을 300만원 초과합니다.

   1. 종합과세 적용 시: 추가 세금 약 105만원 (한계세율 35%)
   2. 분리과세 선택 시: 354만원 (15.4% × 2,300만원)
   → 종합과세 선택이 249만원 유리합니다.

   더불어 건강보험 피부양자 자격을 잃게 되어
   월 약 18만원의 지역가입자 보험료가 추가됩니다.

   대안: ISA 계좌로 800만원 이전 시 위 모든 문제 해소 가능."
```

**Cursor 프롬프트**:
```
utils/storytelling.py에 generate_tax_warning() 함수 추가.
ctx.tax + ctx.tax_strategy + ctx.health_insurance 를 받아서
위 형식의 한국어 경고 메시지를 생성. StorytellingFilter에서 호출.
```

---

## 5. 리스크 & 대응

| 리스크 | 확률 | 대응 |
|---|---|---|
| 세법 해석 오류 | 높음 | 모든 계산식에 국세청 공식문서 URL 주석 |
| 건보료 공식 복잡도 | 중 | 단순화 버전 + "참고용" 명시 |
| 환율 데이터 누락 | 중 | macro_data.py 시리즈 우선, 없으면 한은 ECOS API |
| ISA 한도 혼동 | 낮음 | 신규 모듈에서는 ISA 건드리지 않음 |

---

## 6. Cursor 작업 시작 명령어

```
@docs/ROADMAP_TAX_PRECISION.md Day 10부터 순서대로.
ISA 한도 상수(4000/500/1000)는 절대 건드리지 말 것.
각 함수 작성 후 바로 테스트 작성 → pytest 통과 확인 → 다음 함수.
```

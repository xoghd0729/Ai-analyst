# 캡스톤 14일 발표 플랜 — Week1 개발 + Week2 폴리시

> 발표일: **6월 10일 (D+14, 오늘 5월 27일 기준)**
> 보고서: 최종 10p + 주간보고서 1p
> 형태: API + 로컬 웹 데모 (퍼블릭 론칭은 발표 후)
> 원칙: **1주차에 코드 다 끝내고, 2주차는 폴리시·리허설만**

---

## 핵심 철학 (모든 작업의 북극성)

**"매달 월급 → 안전한 배당 → 주가 유지 → 복리로 안전하게"**

= Quality Dividend Growth Investing (QDGI)

이 시스템이 풀어야 할 4가지:
1. **설계** — 미래 월급형 현금흐름 계획 (FIRE 역산, Monte Carlo)
2. **분석** — 종목·포트폴리오 진단 (ML, SHAP, 백테스팅)
3. **방어** — Yield trap 회피, 세금, 스트레스 (방어가 차별화 핵심)
4. **관리** — 시간이 지나며 유지 (리밸런싱, 알림, 모니터링)

**잘라낼 종목 타입** — Yield trap (배당↑ 주가↓), 1회성 특별배당, 사양 산업 우량주
**골라낼 종목 타입** — 배당 성장 25년+ (Aristocrat), FCF 성장, Total Return 양호

---

## 14일 일별 (요약)

```
━ Week 1 (D1~D7): 코드 다 끝내기 ━
D1 (5/27 화)  데이터 — 60종목 + 21년 백테스팅 확장
D2 (5/28 수)  ETF 10개 + Sortino/Calmar/IR 메트릭
D3 (5/29 목)  ⭐ 관리 대시보드 + Yield Trap 경고 (차별화 핵심)
D4 (5/30 금)  데모 모드 + 프론트 전체 폴리시
D5 (5/31 토)  API 안정화 + 최종 보고서 1차 (5p)
D6 (6/1  일)  최종 보고서 2차 (10p 완성)
D7 (6/2  월)  슬라이드 1차 + 1주차 점검

━ Week 2 (D8~D14): 폴리시·리허설만 ━
D8  (6/3 화) 슬라이드 폴리시 + 데모 시나리오 다듬기
D9  (6/4 수) 리허설 x3 + 발견 버그 패치
D10 (6/5 목) 보고서 최종 + 리허설 x2
D11 (6/6 금) 백업 영상 녹화 + Q&A 답변 준비
D12 (6/7 토) ⚠ 코드 프리즈 + 리허설 x2
D13 (6/8 일) 최종 점검 + 일찍 잠
D14 (6/9 월) 마지막 리허설 1회 + 발표장 동선 점검
6/10  발표일
```

---

## 핵심 결정 — 무엇을 자르고 무엇을 더할까

### ❌ 잘라낸 것 (Phase 2 = 발표 후)
| 작업 | 자른 이유 |
|---|---|
| 앙상블 모델 (XGB+LGB+CAT) | 청중 못 봄, 회귀 위험, 시간 부족 |
| 세금 정밀화 (해외양도세·누진) | 청중 못 봄, 시간 부족 |
| 매크로 일별 파이프라인 | 백엔드, 청중 못 봄 |
| 데이터 100개·ETF 20개 풀스펙 | 60개·10개로 축소 |
| 특별배당 분리·품질 게이트 | 운영 단계 |
| 퍼블릭 배포 (Vercel·Railway) | 발표 후 |

### ✅ 새로 추가한 것 (캡스톤 필수)
| 작업 | 이유 |
|---|---|
| ⭐ **관리 대시보드 (D3)** | "운영체제" 이름값. 차별화 핵심 |
| ⭐ **Yield Trap 경고 (D3)** | 사용자 철학 "주가 유지" 정면 반영 |
| **데모 모드 자동 입력 (D4)** | 라이브 데모 안정성 |
| **백업 영상 녹화 (D11)** | 데모 사고 대비 |
| **리허설 7회 이상** | 1회당 7~10분 |

---

## Phase 1 (D1~D7) — Week 1 핵심 개발

### D1 (5/27 화) — 데이터 확장 60종목 + 21년 백테스팅

**왜**: "21년치 실데이터 검증, 60+ 종목 추천 가능" 슬라이드용 한 줄.

**Cursor 프롬프트**:
```
.cursorrules 와 @docs/CAPSTONE_PRESENTATION_PLAN.md D1 작업.

1. scripts/collect_kr_dividend_stocks.py 의 fetch_stock_data() 를 pykrx + DART로 완성
   - 단, 60개 목표로 빠르게. 80개 안 채워져도 OK.
2. python scripts/collect_kr_dividend_stocks.py 실행
3. utils/backtesting.py 의 _HISTORICAL_DATA 를 2005~2024로 확장 (yfinance)
4. data/approved_universe_kr_v2.json 종목 수 확인

목표 시간: 4~5시간. 막히면 멈추고 보고.
```

**완료 기준**: 종목 ≥ 60, 백테스팅 시작연도 = 2005.

---

### D2 (5/28 수) — ETF 10개 + Sortino/Calmar/IR

**왜**: 학술 청중용 메트릭 + 한국 ETF 데모 종목.

**Cursor 프롬프트**:
```
@docs/CAPSTONE_PRESENTATION_PLAN.md D2 작업. 두 가지 병행.

[1] 한국 ETF 10개 추가 (KODEX 고배당, TIGER 코스피고배당, ARIRANG 고배당,
    KBSTAR 고배당, TIGER 미국배당다우존스, TIGER 리츠부동산인프라,
    KODEX 200, TIGER 미국S&P500, KODEX 미국S&P500배당귀족, TIGER 코스피)
   - data/asset_metadata.json 에 추가
   - utils/backtesting.py 의 _HISTORICAL_DATA 에 2015~2024 데이터 추가

[2] utils/backtesting.py 의 run_backtest() 반환에 4개 메트릭 추가:
   - sortino_ratio (하방 변동성만 페널티)
   - calmar_ratio (CAGR / |MDD|)
   - information_ratio_kospi
   - information_ratio_sp500
   기존 필드 모두 유지.

목표 시간: 5~6시간.
```

---

### D3 (5/29 목) — ⭐ 관리 대시보드 + Yield Trap 경고

**왜**: 사용자 철학 "안전한 배당 + 주가 유지" + "운영체제 이름값" 핵심.
이 화면 하나가 발표에서 차별화 결정타.

**구현 내용**:

**A. Yield Trap 경고 컴포넌트** (`frontend/src/components/YieldTrapWarning.jsx`)
- 추천 종목 중 다음 조건 자동 감지:
  - 배당수익률 ≥ 8% AND 최근 3년 주가 CAGR ≤ -5%
  - ML 모델 BROKEN 분류
  - dividend_coverage < 0.8 (배당이 영업현금흐름보다 큼)
- 빨강 배지 + 한국어 설명: "이 종목은 배당은 높지만 주가가 빠지고 있어요"
- 대안 종목 1~2개 제시

**B. 관리 대시보드 컴포넌트** (`frontend/src/components/PortfolioMonitor.jsx`)
- 4개 위젯:
  1. **이번 달 받을 배당** — `dividend_calendar.py` 활용, 큰 글씨 한 줄 ("47만원")
  2. **다음 리밸런싱 권장일** — D-카운트다운 (3개월 주기)
  3. **종목별 ML 점수 변화** — STRONG→STABLE→WEAKENING 알람
  4. **배당 성장 곡선** — `dividend_projection.py` 활용, 향후 10년 월배당 예측

**Cursor 프롬프트**:
```
@docs/CAPSTONE_PRESENTATION_PLAN.md D3 작업. 차별화 핵심.

[1] frontend/src/components/YieldTrapWarning.jsx 신규 작성:
   - props: recommendations (배열)
   - 3가지 조건으로 yield trap 종목 자동 감지
   - 빨강 카드 + 한국어 경고 메시지 + 대안 종목

[2] frontend/src/components/PortfolioMonitor.jsx 신규 작성:
   - 4개 위젯 (이번 달 배당 / 리밸런싱 카운트다운 / ML 점수 변화 / 배당 성장 곡선)
   - 백엔드 API는 이미 있는 것 활용:
     * /api/portfolio/calendar — dividend_calendar.py
     * /api/portfolio/rebalance — rebalancer.py
     * recommendations 안에 ml_score 포함됨
     * dividend_projection.py 의 결과 활용

[3] frontend/src/pages/Portfolio.jsx 에 두 컴포넌트 import + 렌더링:
   - YieldTrapWarning: 추천 종목 표 바로 위 (가장 먼저 보이게)
   - PortfolioMonitor: 페이지 하단 (스크롤 끝에)

[4] 백엔드 — Yield Trap 자동 감지 헬퍼 함수:
   - utils/yield_trap_detector.py 신규 작성
   - detect_yield_traps(recommendations: list[dict]) -> list[dict]
   - api/pipeline/filters.py 에 YieldTrapFilter 추가
   - 결과를 ctx.yield_traps 에 저장, /api/portfolio/recommend 응답에 포함

목표 시간: 6~7시간. 차별화 핵심이라 시간 더 써도 OK.
```

**데모 임팩트 포인트**: 페르소나 ② 민호의 입력값에서 일부러 QYLD 같은 yield trap이 포함되도록 시드 데이터 조정 → 데모에서 빨강 경고가 뜨는 모습 보여줌.

---

### D4 (5/30 금) — 데모 모드 + 프론트 폴리시

**왜**: 라이브 데모 안정성 + 시각 임팩트.

**Cursor 프롬프트**:
```
@docs/CAPSTONE_PRESENTATION_PLAN.md D4 작업.

[1] 데모 모드 추가:
   - frontend/src/pages/Portfolio.jsx 상단에 3개 버튼:
     "28세 윤지로 보기" / "42세 민호로 보기" / "55세 영자로 보기"
   - 클릭 시 입력 폼 자동 채우고 "추천 받기" 자동 실행
   - 정확한 입력값은 docs/DEMO_SCRIPT.md 참고

[2] 프론트 폴리시:
   - 로딩 스피너 (현재 빈 화면 → 스켈레톤 로더)
   - 차트 데이터 없을 때 친절한 메시지
   - 에러 발생 시 화면 빈 채로 안 멈추게
   - 모바일 반응형 (768px 이하)
   - 로고/타이틀 "AI Cashflow OS" 깔끔하게
   - 다크모드 토글 (선택, 시간 남으면)

[3] BacktestChart 컴포넌트 (아직 없으면) 작성:
   - recharts ComposedChart (BarChart + LineChart)
   - 연도별 수익률 막대 + KOSPI/S&P500 라인
   - 상단: CAGR/MDD/Sharpe/Sortino 4개 카드
   - "21년 시뮬레이션" 배지

목표 시간: 6~7시간.
```

---

### D5 (5/31 토) — API 안정화 + 보고서 1차 (5p)

**오전 (3h)**: API 안정화
```
api/main.py + api/routers/ 점검:
1. 3 페르소나 입력값으로 모두 정상 응답 (< 3초)
2. /api/health 엔드포인트
3. /docs Swagger 깨끗하게
4. CORS localhost:5173 허용
5. 18개 필터 중 하나 실패해도 응답은 정상 (add_error)
```

**오후 (5h)**: 최종 보고서 1차
- `docs/FINAL_REPORT_TEMPLATE.md` (10p 압축본) 따라 5p 작성
- 섹션 1~3: 서론·문제정의·시스템설계

---

### D6 (6/1 일) — 보고서 10p 완성

**Cursor 프롬프트**:
```
@docs/FINAL_REPORT_TEMPLATE.md 의 섹션 4~7 작성.
실제 코드/데이터/결과 인용.
docx 또는 PDF 형식으로 reports/final_report_v1.docx 저장.
```

---

### D7 (6/2 월) — 슬라이드 1차 + 1주차 점검

**슬라이드 (5h)**: 15장
1. 타이틀
2. 문제 — 한국 노후 빈곤율
3. 솔루션 한 줄
4. 시장·경쟁
5. 시스템 아키텍처 (18-필터)
6~7. 핵심 기능 4종 (FIRE / Monte Carlo / ML+SHAP / 세금)
8. ⭐ Yield Trap 경고 + 관리 대시보드 (차별화)
9. 데이터 — 60종목·21년
10. 평가 — 백테스팅 차트
11. 라이브 데모 전환
12~13. 데모 스크린샷 백업
14. 향후 로드맵
15. Q&A

도구: Google Slides 추천 (협업 + 자동 백업).

**1주차 점검 (1h)**:
```bash
# 코드 통계
find ai-analyst -name "*.py" | xargs wc -l
# 테스트 통과
pytest tests/ -v
# 빌드 확인
cd frontend && npm run build
```

---

## Phase 2 (D8~D14) — Week 2 폴리시·리허설만

### ⚠ 절대 룰: **D8부터는 새 기능 추가 금지**

새 기능 추가하고 싶은 욕구 = 발표 망치는 지름길.
오직 버그 픽스 + 미세 폴리시만.

### D8 (6/3 화) — 슬라이드 폴리시 + 데모 시나리오
- 슬라이드 폰트 통일, 고해상도 이미지
- DEMO_SCRIPT.md 의 9분 시나리오 다시 읽고 수정
- 페르소나별 시간 배분 재확인

### D9 (6/4 수) — 리허설 x3
- 1회차: 흐름만 확인 (시간 측정)
- 2회차: 7~8분 압축
- 3회차: 친구·가족 앞에서 (비전공자 이해도 체크)
- 발견된 버그 즉시 패치 (사소한 것만)

### D10 (6/5 목) — 보고서 최종 + 리허설 x2
- 보고서 오탈자·인용·서식 최종 점검
- PDF 변환 확인
- 리허설 x2 (와우 포인트 강조 연습)

### D11 (6/6 금) — 백업 영상 + Q&A
- OBS 또는 QuickTime으로 데모 백업 영상 녹화 (3~5분 x 3종)
- DEMO_SCRIPT.md 의 Q&A 예상 답변 외움
- 추가 예상 질문 5개 더 작성

### D12 (6/7 토) — ⚠ 코드 프리즈
- git tag v1.0-presentation
- 이후 코드 수정 절대 금지
- 리허설 x2 (사고 대응 시뮬레이션: API 끄고 백업 영상 전환 연습)

### D13 (6/8 일) — 최종 점검
- 노트북·HDMI 어댑터·USB 백업 준비
- 발표장 PC 폰트 호환성 → 슬라이드 PDF 백업 필수
- 일찍 잠

### D14 (6/9 월) — 마지막 점검
- 마지막 리허설 1회
- 발표장 직접 방문해서 동선 확인 (가능하면)
- 충분한 휴식

### 6/10 — 발표일
- 30분 일찍 도착
- HDMI 연결 테스트
- 노트북 풀충전 + 충전기
- 깊은 호흡 한 번

---

## 위험 신호 — 즉시 대응

| 상황 | 대응 |
|---|---|
| D3까지 D1·D2 못 끝냄 | 데이터 50개·ETF 5개로 추가 축소. D3는 무조건 사수. |
| D5까지 API 불안정 | 데이터 갱신 cron 끄고 캐시된 데이터만 사용 |
| D7까지 슬라이드 못 끝냄 | Week 2 D8 추가 시간 할애 |
| D12 이후 버그 발견 | 데모 시나리오에서 회피 가능하면 회피, 불가능하면 백업 영상 전환 |

---

## 1주차 마일스톤 체크리스트 (D7 종료 시점)

- [ ] data/approved_universe_kr_v2.json 60+ 종목
- [ ] utils/backtesting.py 2005년부터 백테스팅 가능
- [ ] Sortino/Calmar/IR 메트릭 응답에 포함
- [ ] frontend/src/components/YieldTrapWarning.jsx 동작
- [ ] frontend/src/components/PortfolioMonitor.jsx 동작
- [ ] 3 페르소나 "데모 모드" 버튼 동작
- [ ] /api/health 엔드포인트 추가
- [ ] 최종 보고서 10p 1차 완료
- [ ] 슬라이드 15장 1차 완료

이게 다 통과면 Week 2는 폴리시·리허설만 하면 됨.

---

## Cursor 작업 시작 명령 (D1 - 오늘)

```
.cursorrules 와 @docs/CAPSTONE_PRESENTATION_PLAN.md D1 작업 시작.
빠르게 4~5시간 안에 60종목·21년 백테스팅 끝내자.
막히면 멈추고 보고.
```

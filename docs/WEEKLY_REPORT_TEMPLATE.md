# 주간 보고서 양식 (1페이지)

> 매주 학교 제출용. 채워서 그대로 복사 → 학교 양식에 붙여넣기.
> 캡스톤 기간 동안 총 2회 작성 예상 (5/27 시작 → 6/3 → 6/10).

---

## Week 1 보고서 (5/27 ~ 6/2)

### 1. 이번 주 진행 사항

**완료된 작업** (D1~D7):

| Day | 작업 | 결과물 |
|---|---|---|
| D1 | 한국 배당주 60종목 수집, 백테스팅 21년 확장 | `data/approved_universe_kr_v2.json`, `utils/backtesting.py` |
| D2 | 한국 ETF 10개 추가, Sortino/Calmar/IR 메트릭 | `data/asset_metadata.json`, `utils/backtesting.py` |
| D3 | Yield Trap 자동 감지, 관리 대시보드 | `YieldTrapWarning.jsx`, `PortfolioMonitor.jsx`, `utils/yield_trap_detector.py` |
| D4 | 데모 모드 + 프론트엔드 폴리시 | `Portfolio.jsx` 페르소나 버튼, 로딩 UI |
| D5 | API 안정화 + 최종보고서 5p | `/api/health`, `reports/final_report_v1.docx` (5p) |
| D6 | 최종보고서 10p 완성 | `reports/final_report_v1.docx` (10p) |
| D7 | 발표 슬라이드 15장 1차 | `slides/capstone_v1.pptx` |

**정량 지표**:
- 신규 코드: 약 ____줄 (Python ____ / JSX ____)
- 신규 테스트: ____개
- 백테스팅 시계열: 10년 → **21년**
- 추천 가능 종목: 20개 → **60+ 개**
- ETF: 0개 → **10개**

### 2. 핵심 성과

**⭐ 차별화 기능 구현**:
- **Yield Trap 자동 감지** — 배당 8%↑ + 주가 -5%↓ 같은 위험 종목 빨강 경고
- **관리 대시보드** — 이번 달 배당, 리밸런싱 D-day, ML 점수 변화 시각화
- **위험조정 6개 메트릭** — Sharpe만이 아닌 Sortino/Calmar/IR까지

### 3. 다음 주 계획 (Week 2, 6/3 ~ 6/10)

| Day | 작업 |
|---|---|
| D8 | 슬라이드 폴리시 + 데모 시나리오 다듬기 |
| D9 | 리허설 3회 + 발견 버그 패치 |
| D10 | 보고서 최종 검토 + 리허설 2회 |
| D11 | 데모 백업 영상 녹화 + Q&A 답변 준비 |
| D12 | ⚠ 코드 프리즈, 리허설 2회 |
| D13 | 최종 점검, 발표장 동선 확인 |
| D14 | 마지막 리허설 + 발표 (6/10) |

### 4. 이슈 및 해결 방안

- 이슈 1: (있으면 작성, 없으면 "특이사항 없음")
- 이슈 2: ...

---

## Week 2 보고서 (6/3 ~ 6/10) — 발표 직전

### 1. 이번 주 진행 사항

**완료된 작업** (D8~D14):

| Day | 작업 | 결과물 |
|---|---|---|
| D8  | 슬라이드 폴리시 | `slides/capstone_v2.pptx` (15장 완성) |
| D9  | 리허설 3회 + 버그 패치 | 리허설 노트, 패치 commit |
| D10 | 보고서 최종 + 리허설 2회 | `reports/final_report_final.pdf` |
| D11 | 백업 영상 녹화 + Q&A | `demo_backup_1.mp4` 등 3종 |
| D12 | 코드 프리즈 + 리허설 | `git tag v1.0-presentation` |
| D13 | 최종 점검 | 체크리스트 통과 |
| D14 | 마지막 리허설 | 발표 준비 완료 |

**최종 결과물**:
- 발표 슬라이드 PPTX + PDF
- 최종 보고서 10p PDF
- 데모 백업 영상 3종 (3~5분 × 3 페르소나)
- 작동하는 API + 로컬 웹 데모

### 2. 핵심 성과 (Week 1 + Week 2 종합)

- 14일간 캡스톤 일정 100% 소화
- 총 약 ____줄 코드 (백엔드 ____ + 프론트 ____ + 테스트 ____)
- 18개 필터 파이프라인 + ML 모델 + SHAP 설명 가능성
- 차별화 기능: Yield Trap 감지, 관리 대시보드
- 21년 백테스팅 검증: CAGR __%, MDD __%, Sortino __

### 3. 발표 준비 상태

- [x] 슬라이드 15장 완성
- [x] 최종 보고서 10p 완성
- [x] 라이브 데모 안정성 검증 (리허설 7회+)
- [x] 백업 영상 녹화
- [x] Q&A 예상 답변 준비

### 4. 발표 후 계획 (Phase 2)

- 6/11~ : 베타 사용자 모집 (50명 목표)
- 6/15~ : Vercel + Railway 퍼블릭 배포
- 7월~  : 앙상블 모델 (XGB+LGB+CAT) + 세금 정밀화
- 8월~  : paper trading 6개월 추적 시작

---

## 채워야 할 빈칸 가이드

매 주 작성 시 다음만 업데이트:

### 정량 지표 계산 방법

```bash
# 코드 라인 수
cd ~/ai-analyst
find . -name "*.py" -not -path "./venv/*" -not -path "./__pycache__/*" | xargs wc -l | tail -1
find ./frontend/src -name "*.jsx" -o -name "*.js" | xargs wc -l | tail -1

# 테스트 개수
pytest tests/ --collect-only -q | tail -5

# 종목 수
python -c "import json; print(len(json.load(open('data/approved_universe_kr_v2.json'))['universe']))"

# 백테스팅 시계열
python -c "from utils.backtesting import _HISTORICAL_DATA; t=list(_HISTORICAL_DATA.values())[0]; print(f'{min(t.keys())}~{max(t.keys())}')"
```

### 정성 평가 한 줄 (선택)

지도교수가 "어떻게 진행되고 있는가?"에 답할 수 있는 한 줄:
- Week 1: "1주차에 핵심 코드 작업 100% 완료, 2주차는 폴리시·리허설에 집중"
- Week 2: "라이브 데모 안정성 검증 완료, 백업 시나리오까지 준비"

---

## 학교 양식 변환 팁

학교마다 양식이 다르므로:
1. 위 내용을 일단 markdown으로 채움
2. 학교 양식 (.docx, .hwp) 열어서 복사 붙여넣기
3. 표는 학교 양식의 표 스타일에 맞게 재조정

분량이 1p 넘으면:
- "다음 주 계획" 줄여서 표만 남기기
- "정량 지표"의 부가 설명 제거
- 이슈 섹션 통째 삭제 가능

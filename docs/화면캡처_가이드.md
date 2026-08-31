화면 캡처 가이드 — 최종보고서 [그림] 채우기

이 문서는 최종보고서의 [그림 4-3] ~ [그림 4-10] 자리에 넣을 실제 UI 화면을
직접 캡처하기 위한 안내다. (4-1 UML, 4-2 ERD, 4-11 피처중요도는 이미 이미지 생성 완료)


1. 프로젝트 실행 방법

백엔드 (터미널 1)
  cd ~/ai-analyst
  source venv/bin/activate
  uvicorn api.main:app --reload --port 8000
  → http://localhost:8000/docs 열리면 정상 (Swagger API 문서도 캡처용으로 좋음)

프론트엔드 (터미널 2)
  cd ~/ai-analyst/frontend
  npm install        # 최초 1회
  npm run dev
  → http://localhost:5173 접속

캡처 팁
  - macOS: Shift+Cmd+4 (영역 선택) 또는 Shift+Cmd+5
  - 브라우저 폭을 1280px 정도로 맞추면 보고서에 넣기 좋다
  - 데모 페르소나(25세 등)를 선택하면 즉시 결과가 나온다


2. 캡처 대상과 그림 번호 매핑

[그림 4-3] 입력 화면
  - 위치: 첫 페이지 입력 폼
  - 담을 것: 나이, 월 투자금, 적립금 증가율, 목표 월배당, 투자 성향 입력란 + 페르소나 버튼

[그림 4-4] 결과 대시보드 헤드라인
  - 위치: 추천 실행 후 최상단
  - 담을 것: 목표 월배당 / 예상 달성 나이 / FIRE 진행률 게이지 / 자산 진행률 / 현재 단계

[그림 4-5] 추천 포트폴리오
  - 담을 것: 상위 종목 Top5 + 비중 + 역할 태그(월배당/배당성장/방어)

[그림 4-6] 오늘의 액션
  - 담을 것: 위험 경고·집중도·ISA 절세·ETF 편입 등 권고 카드

[그림 4-7] 현금흐름 여정 타임라인
  - 담을 것: 현재 → 목표 달성 → Lean FIRE → 일반 FIRE 타임라인

[그림 4-8] 상세 분석 화면
  - 담을 것: 소득 지속성 점수 / 생존확률 / 위험 기여도 / Monte Carlo P10·P50·P90 차트 / 백테스팅
  - '상세 분석 보기'를 펼쳐서 캡처

[그림 4-9] SHAP 설명 화면
  - 담을 것: 배당 위험 종목의 SHAP 근거(어떤 지표가 위험 판단에 기여했는지)

[그림 4-10] 사용자 기능 화면
  - 담을 것: 로그인/회원가입 + 내 포트폴리오 목록 + 불러오기 + 변화 추적


3. 캡처 후 등록 방법

캡처한 PNG를 다음 폴더에 같은 규칙으로 저장하면 보고서에 자동 연결된다.
  ~/ai-analyst/docs/images/
  - fig4-3_input.png
  - fig4-4_dashboard.png
  - fig4-5_portfolio.png
  - fig4-6_action.png
  - fig4-7_timeline.png
  - fig4-8_analysis.png
  - fig4-9_shap.png
  - fig4-10_user.png

HWP로 옮길 때는 각 [그림] 캡션 아래에 해당 이미지를 삽입하면 된다.


4. 확인된 기능 목록 (코드 기준, 캡처 시 참고)

분석 파이프라인: 20개 필터
  거시레짐 / 축가중 / 자산선별 / 비중배분 / 요약 / 배당예측 / 리밸런싱 /
  스트레스테스트 / 섹터노출 / 배당캘린더 / 위험경고 / FIRE엔진 / 몬테카를로 /
  생존확률 / 세금최적화 / 행동편향 / 고배당함정 / 포트폴리오건강도 / 스토리텔링 / SHAP설명

주요 API 엔드포인트
  POST /api/portfolio/recommend     추천 포트폴리오 생성
  POST /api/portfolio/backtest      21년 백테스트
  GET  /api/portfolio/calc          FIRE 역산 계산
  GET  /api/stock/{code}/predict    종목 배당 삭감 예측
  GET  /api/stock/{code}/explain    SHAP 설명
  POST /api/auth/register, login    회원가입 / 로그인
  POST /api/auth/save               포트폴리오 저장
  GET  /api/auth/my                 내 포트폴리오 목록

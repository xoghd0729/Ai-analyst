# AI Dividend Analyst — 개발 로드맵

## 완료
- [x] LLM batch 처리 (Top-3 뉴스 선별 + 1회 Ollama 호출)
- [x] Incremental Update (변화 없는 종목 skip)
- [x] Event Cache (동일 기사 재처리 방지)
- [x] 스케줄러 (매일 08:00 자동 배치)
- [x] 대시보드 UI 재설계 (카드 기반, 초보자 언어)

## 진행 순서

### 6. 데이터 확장
- [x] 미국 Dividend Aristocrats 상위 20개 → ranking.csv 추가
- [ ] yfinance 기반 미국 뉴스 파이프라인 연결 (Mac 로컬 실행)

### 7. UI polish
- [x] 대시보드 종목 데이터 미표시 버그 수정
- [x] Thesis Timeline 시각화 (INTACT → WEAKENING → BROKEN 흐름)
- [x] 종목 상세 — 위험 요인 구체화

### 8. 다음 (남은 것)
- 미국 종목 배치 실행 테스트 (python run_thesis_batch.py)
- thesis_history 데이터 쌓이면 Timeline 실데이터 검증

## 핵심 원칙
- AI 제거 금지 (rule-based 회귀는 차별성 소멸)
- 기능 추가 금지 (코인·자동매매·강화학습 절대 NO)
- "AI 판단 신뢰성 > 겉 UI"

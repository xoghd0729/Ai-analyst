# 배포 가이드 — Phase 2 (발표 후)

> ⚠️ 발표일 D-14 기준: **로컬 데모만 준비**. 실제 퍼블릭 배포는 발표 후.
> 이 문서는 발표 후 사용자 확보 단계에서 참고할 가이드.

---

## 발표 전 (D-14 ~ D0): 로컬 데모만 OK

### 데모 환경 (필수)

```bash
# 터미널 1: 백엔드
cd ~/ai-analyst
source venv/bin/activate
uvicorn api.main:app --reload --port 8000

# 터미널 2: 프론트엔드
cd ~/ai-analyst/frontend
npm run dev
# → http://localhost:5173 접속
```

**체크리스트**:
- [ ] PostgreSQL 로컬 실행 (또는 SQLite 폴백)
- [ ] `.env` 모든 키 설정됨
- [ ] 3 페르소나 입력값으로 추천 결과 정상
- [ ] 18개 필터 모두 에러 없이 통과

### 발표 직전 데모 안정성 체크 (D-1)

```bash
cd ~/ai-analyst

# 1. 전체 테스트 통과 확인
pytest tests/ -v --tb=short

# 2. 핵심 API 응답 확인
curl -X POST http://localhost:8000/api/portfolio/recommend \
  -H "Content-Type: application/json" \
  -d '{
    "age": 28,
    "annual_income": 4500,
    "monthly_target": 200,
    "investable_amount": 1000,
    "risk_tolerance": "moderate",
    "monthly_savings": 300,
    "target_fire_age": 50
  }'

# 3. 프론트 빌드 통과
cd frontend && npm run build
```

---

## 발표 후 (Phase 2): 실제 퍼블릭 배포

### 아키텍처 선택

```
사용자 → Vercel (React 정적 호스팅) → Railway (FastAPI) → Supabase (Postgres)
```

| 구성요소 | 서비스 | 무료 한도 | 유료 시작 |
|---|---|---|---|
| 프론트엔드 | Vercel | 100GB/월 트래픽 | $20/월 |
| 백엔드 | Railway | $5 크레딧/월 | $5+/월 |
| DB | Supabase | 500MB | $25/월 |
| 도메인 | Cloudflare | (구입 별도) | $10/년 |

**초기 베타 50명 트래픽이면 모두 무료 한도 안에서 가능**.

---

### Step 1: Supabase PostgreSQL 셋업 (1시간)

1. [supabase.com](https://supabase.com) 회원가입
2. New Project → 이름·비밀번호·리전(Tokyo) 입력
3. SQL Editor → 기존 스키마 마이그레이션:

```bash
# 로컬 schema dump
cd ~/ai-analyst
pg_dump --schema-only $LOCAL_DB_URL > schema.sql

# Supabase SQL Editor에 붙여넣기 후 실행
```

4. Settings → Database → Connection String 복사 (포맷: `postgresql://...`)
5. Railway 환경변수에 `DATABASE_URL` 로 등록 (다음 단계)

---

### Step 2: Railway 백엔드 배포 (2~3시간)

#### 2-1. 배포 파일 준비

```bash
cd ~/ai-analyst

# Procfile 생성 (Railway가 자동 인식)
cat > Procfile << EOF
web: uvicorn api.main:app --host 0.0.0.0 --port \$PORT
EOF

# runtime 명시
echo "python-3.11.7" > runtime.txt

# requirements.txt 최종 확인
pip freeze | grep -E "fastapi|uvicorn|sqlalchemy|psycopg2|xgboost|shap|apscheduler" >> requirements.txt
```

#### 2-2. Railway 프로젝트 생성

```bash
# Railway CLI 설치
npm install -g @railway/cli

# 로그인
railway login

# 프로젝트 초기화 (~/ai-analyst 디렉토리에서)
railway init
# → Empty Project 선택

# 환경변수 등록
railway variables set DART_API_KEY=$DART_API_KEY
railway variables set BOK_API_KEY=$BOK_API_KEY
railway variables set DATABASE_URL="postgresql://..."  # Supabase URL
railway variables set CORS_ORIGINS="https://ai-cashflow.vercel.app"

# 배포
railway up
```

#### 2-3. 도메인 확인

```bash
railway domain
# → 예: https://ai-analyst-production.up.railway.app

# 테스트
curl https://ai-analyst-production.up.railway.app/api/health
```

#### 2-4. PostgreSQL 마이그레이션 실행

```bash
# Railway 셸 접속
railway shell

# 스키마 + 초기 데이터 주입
python scripts/migrate_cache_to_db.py
```

---

### Step 3: Vercel 프론트엔드 배포 (1~2시간)

#### 3-1. 빌드 설정 확인

```bash
cd ~/ai-analyst/frontend

# vite.config.js 확인 — base path 등
# package.json scripts 에 build 명령 있어야 함

# 환경변수 파일
cat > .env.production << EOF
VITE_API_BASE_URL=https://ai-analyst-production.up.railway.app
EOF
```

#### 3-2. Vercel CLI 배포

```bash
npm install -g vercel

# frontend 디렉토리에서
cd ~/ai-analyst/frontend
vercel

# 안내 따라:
# - Set up and deploy? Y
# - Which scope? 본인 계정
# - Link to existing project? N
# - Project name? ai-cashflow
# - Directory? ./
# - Override settings? N

# 프로덕션 배포
vercel --prod
# → https://ai-cashflow.vercel.app
```

#### 3-3. CORS 업데이트

Railway 환경변수에서:
```
CORS_ORIGINS=https://ai-cashflow.vercel.app,https://ai-cashflow-*.vercel.app
```

`api/main.py`의 CORS 미들웨어가 이 환경변수를 읽도록 확인.

---

### Step 4: 모니터링 + 알람 (필수)

#### 4-1. 에러 추적 — Sentry (무료)

```bash
pip install sentry-sdk[fastapi]
```

```python
# api/main.py 상단 추가
import sentry_sdk
import os

if os.getenv("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.getenv("SENTRY_DSN"),
        traces_sample_rate=0.1,
        environment=os.getenv("ENVIRONMENT", "production"),
    )
```

[sentry.io](https://sentry.io) → 새 프로젝트 → DSN을 Railway 환경변수로.

#### 4-2. Uptime 체크 — UptimeRobot (무료)

- [uptimerobot.com](https://uptimerobot.com) 가입
- New Monitor → `https://ai-analyst-production.up.railway.app/api/health`
- 5분마다 체크 → 다운 시 이메일·SMS

#### 4-3. 로그 — Railway 기본 + Better Stack (선택)

Railway 대시보드에서 로그 실시간 확인 가능. 장기 보관 필요하면 [betterstack.com](https://betterstack.com) Logtail 연동.

---

### Step 5: 사용자 행동 분석

#### Plausible (개인정보 친화, 무료 30일)

```html
<!-- frontend/index.html -->
<script defer data-domain="ai-cashflow.vercel.app"
  src="https://plausible.io/js/script.js"></script>
```

또는 Google Analytics 4 (무료).

---

## 비용 추정

### 베타 단계 (월 사용자 ~50명)
- 모두 무료 한도 → **월 $0**

### 그로스 단계 (월 사용자 ~500명)
- Railway 백엔드: $10
- Supabase 유료: $25
- Vercel Pro: $20 (혹은 무료 유지)
- 도메인: $1
- **월 ~$50 (≈ 7만원)**

### 스케일 단계 (월 사용자 ~5,000명)
- Railway 크레딧 증가: $50
- Supabase: $25 (또는 자체 Postgres)
- Vercel: $20~
- Sentry 유료: $26
- **월 ~$120 (≈ 17만원)**

---

## 보안 체크리스트 (배포 전 필수)

- [ ] `.env` 가 git에 안 올라감 (`.gitignore` 확인)
- [ ] API 키 모두 Railway 환경변수로 (코드에 하드코딩 X)
- [ ] CORS 허용 도메인 명시적 (와일드카드 X)
- [ ] FastAPI rate limit (`slowapi` 라이브러리)
- [ ] PostgreSQL connection pool 한도 (10~20)
- [ ] 사용자 입력 검증 (Pydantic) — SQL injection 방지
- [ ] HTTPS 강제 (Vercel·Railway 모두 기본)
- [ ] 백업 정책 (Supabase 일별 자동)

---

## 발표 후 첫 일주일 — 베타 모집 액션

### Day 1~3
- 트위터/X 한 문장 + 데모 URL 공유
- LinkedIn 캡스톤 회고 글 + 링크
- 네이버 카페 (배당투자), 디시 주식갤러리에 "베타 테스터 모집" 글
- 친구 5명에게 직접 카톡 ("써보고 피드백 부탁")

### Day 4~7
- 첫 사용자 10명의 입력값·결과 수동 모니터링
- 가장 많이 막힌 화면 1~2개 즉시 개선
- 사용자 인터뷰 (영상 통화 15분) — 3명만

### 모집 글 템플릿
```
[베타 테스터 모집] 배당 투자자를 위한 AI 현금흐름 운영체제

"50세에 월 200만원 받으려면 지금 얼마를 투자해야 하나?"
이 질문에 18단계 알고리즘으로 답하는 시스템을 만들었습니다.

- FIRE 역산 + Monte Carlo P10/P50/P90
- 한국 2026 세법 (ISA 4,000만원 한도) 완전 반영
- 21년 백테스팅 검증

베타 사용자 50명 모집합니다. (무료)
👉 https://ai-cashflow.vercel.app

캡스톤 프로젝트로 시작했고, 실제 사용자 피드백으로 다듬어 나가고 싶습니다.
어떤 피드백이든 환영입니다 🙏
```

---

## 트러블슈팅

### Railway 빌드 실패
- `requirements.txt` 누락 의존성 확인
- Python 버전 명시 (`runtime.txt`)
- 메모리 한도 — XGBoost 학습은 별도 서비스로 분리 권장

### Vercel 빌드 실패
- `node_modules` 캐시 문제 → `vercel --force`
- 환경변수 누락 → Vercel 대시보드 Settings → Environment Variables

### CORS 에러
- Railway 환경변수의 `CORS_ORIGINS` 정확히 일치
- 프론트 fetch URL 끝에 `/` 있는지 일관성 확인

### DB 마이그레이션 실패
- Supabase Connection String 의 `?sslmode=require` 누락
- SQLAlchemy connect 시 `pool_pre_ping=True`

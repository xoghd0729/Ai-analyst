#!/usr/bin/env python3
"""
전시 / 발표 사전 검증 스크립트 (Pre-flight Check)
=================================================
발표 30분 전 실행 → 전체 시스템 상태 한 번에 확인

사용법:
    python scripts/preflight_check.py
    python scripts/preflight_check.py --url http://localhost:8000  # 서버 URL 지정
    python scripts/preflight_check.py --fast                        # API 호출 생략

체크 항목:
    [1] 데이터 파일 존재 & 기준일
    [2] ML 모델 파일 존재
    [3] API 서버 헬스체크 (/health 또는 /docs)
    [4] 발표 데모 시나리오 파이프라인 (DEMO_RUNBOOK 값 그대로)
    [5] 극단값 입력 거부/오류 없음
    [6] 면책 표현 검증 (survival 필드)
    [7] data_freshness 필드 반환 확인
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

BASE_DIR = Path(__file__).resolve().parent.parent

# ── 색상 출력 헬퍼 ────────────────────────────────────────────
def ok(msg):   print(f"  \033[32m✓\033[0m {msg}")
def warn(msg): print(f"  \033[33m⚠\033[0m {msg}")
def fail(msg): print(f"  \033[31m✗\033[0m {msg}")
def hdr(msg):  print(f"\n\033[1m{msg}\033[0m")

PASS = 0
WARN_COUNT = 0
FAIL_COUNT = 0

def record_ok(msg):
    global PASS; PASS += 1; ok(msg)

def record_warn(msg):
    global WARN_COUNT; WARN_COUNT += 1; warn(msg)

def record_fail(msg):
    global FAIL_COUNT; FAIL_COUNT += 1; fail(msg)


# ── [1] 데이터 파일 ───────────────────────────────────────────
def check_data_files():
    hdr("[1] 데이터 파일 존재 & 기준일")
    STALE_DAYS = 30
    today = datetime.now()

    files = {
        "data/ranking.csv":              "한국주식 랭킹",
        "data/ml_scoring_results.csv":   "ML 위험 점수",
        "data/us_stock_scores.csv":      "미국주식 점수",
        "data/etf_quality_cache.json":   "ETF 구성 캐시",
        "data/dividend_dataset.csv":     "배당 학습 데이터",
        "results/survival_pd_v4.json":   "Survival 모델",
        "data/asset_metadata.json":      "자산 메타데이터",
        "data/approved_universe_kr_v2.json": "한국주식 유니버스",
    }

    for rel_path, label in files.items():
        p = BASE_DIR / rel_path
        if not p.exists():
            record_fail(f"{label} ({rel_path}) — 파일 없음")
            continue

        mtime = datetime.fromtimestamp(p.stat().st_mtime)
        days_ago = (today - mtime).days
        age_str = f"{mtime.strftime('%Y-%m-%d')} ({days_ago}일 전)"

        if days_ago > STALE_DAYS:
            record_warn(f"{label} — {age_str} ⚠ (30일 초과)")
        else:
            record_ok(f"{label} — {age_str}")


# ── [2] ML 모델 파일 ──────────────────────────────────────────
def check_model_files():
    hdr("[2] ML 모델 파일")
    models = {
        "models/dividend_cut_model.pkl":   "TabPFN Survival 기반 모델",
        "results/survival_pd_v4.json":     "Survival PD 결과 (hazard_pct)",
    }
    # kr_3class_model.pkl은 벤치마크 보존용 (런타임 미사용)
    bench = BASE_DIR / "models/kr_3class_model.pkl"
    if bench.exists():
        record_ok(f"kr_3class_model.pkl — 벤치마크 보존 ({bench.stat().st_size // 1024}KB)")
    else:
        record_warn("kr_3class_model.pkl — 없음 (벤치마크 보존용, 런타임 미사용)")

    for rel_path, label in models.items():
        p = BASE_DIR / rel_path
        if not p.exists():
            record_fail(f"{label} ({rel_path}) — 파일 없음")
        else:
            size_kb = p.stat().st_size // 1024
            record_ok(f"{label} — {size_kb}KB")


# ── [3] API 서버 헬스체크 ─────────────────────────────────────
def check_api_server(base_url: str):
    hdr(f"[3] API 서버 헬스체크 ({base_url})")
    if not HAS_REQUESTS:
        record_warn("requests 패키지 없음 — pip install requests")
        return False

    # /docs → FastAPI 기본 엔드포인트
    for endpoint in ["/health", "/docs", "/"]:
        try:
            r = requests.get(f"{base_url}{endpoint}", timeout=5)
            if r.status_code < 500:
                record_ok(f"GET {endpoint} → HTTP {r.status_code} (응답 정상)")
                return True
        except requests.exceptions.ConnectionError:
            pass
        except Exception as e:
            record_warn(f"GET {endpoint} 예외: {e}")

    record_fail(f"서버 응답 없음 — uvicorn api.main:app --port 8000 실행 확인")
    return False


# ── [4] 발표 데모 시나리오 ────────────────────────────────────
DEMO_PAYLOAD = {
    "age": 25,
    "annual_income": 4000,
    "monthly_target": 100,
    "investable_amount": 5000,
    "risk_tolerance": "moderate",
    "archetype": "혼합형",
    "monthly_savings": 100.0,
    "target_fire_age": 50,
    "savings_growth": 5.0,
}

def check_demo_pipeline(base_url: str) -> dict | None:
    hdr("[4] 발표 데모 시나리오 파이프라인")
    if not HAS_REQUESTS:
        record_warn("requests 없음 — 건너뜀")
        return None

    try:
        t0 = time.time()
        r = requests.post(
            f"{base_url}/api/portfolio/recommend",
            json=DEMO_PAYLOAD,
            timeout=60,
        )
        elapsed = round(time.time() - t0, 1)

        if r.status_code != 200:
            record_fail(f"HTTP {r.status_code} — {r.text[:200]}")
            return None

        data = r.json()
        record_ok(f"파이프라인 응답 성공 ({elapsed}초)")
        return data

    except requests.exceptions.Timeout:
        record_fail("60초 초과 — 서버 응답 없음")
        return None
    except Exception as e:
        record_fail(f"예외: {e}")
        return None


def validate_demo_response(data: dict):
    """파이프라인 응답 필드 검증"""
    checks = [
        ("recommendations", lambda d: isinstance(d.get("recommendations"), list) and len(d["recommendations"]) > 0,
         "추천 종목 1개 이상"),
        ("summary", lambda d: "avg_dividend_yield" in d.get("summary", {}),
         "summary.avg_dividend_yield 존재"),
        ("fire_plan", lambda d: isinstance(d.get("fire_plan"), dict),
         "fire_plan dict 존재"),
        ("monte_carlo", lambda d: "p50_monthly" in d.get("monte_carlo", {}),
         "monte_carlo.p50_monthly 존재"),
        ("survival", lambda d: "survival_probability" in d.get("survival", {}),
         "survival.survival_probability 존재"),
        ("data_freshness", lambda d: isinstance(d.get("data_freshness"), dict),
         "data_freshness dict 존재"),
        ("tax", lambda d: "isa_strategy" in d.get("tax", {}),
         "tax.isa_strategy 존재"),
        ("reverse_fire", lambda d: isinstance(d.get("reverse_fire"), dict),
         "reverse_fire dict 존재"),
    ]
    for key, check_fn, label in checks:
        try:
            if check_fn(data):
                record_ok(label)
            else:
                record_fail(f"{label} — 필드 누락 또는 잘못된 값")
        except Exception as e:
            record_warn(f"{label} — 검증 예외: {e}")

    # 면책 표현 검증 — "지속 확률" 표현이 생존 관련 필드에 없어야 함
    hdr("  → 면책 표현 검증")
    story = data.get("survival", {}).get("story_summary", "")
    forbidden = ["지속 확률", "ML이 예측한 장기", "생존확률"]
    for phrase in forbidden:
        if phrase in story:
            record_warn(f"story_summary에 금지 표현 포함: '{phrase}'")
        else:
            record_ok(f"금지 표현 없음: '{phrase}'")

    # data_freshness 필드 상세
    hdr("  → data_freshness 필드")
    df = data.get("data_freshness", {})
    expected_keys = ["kr_stock_ranking", "ml_scoring", "us_stock_scores",
                     "etf_quality", "dividend_dataset", "survival_model"]
    for k in expected_keys:
        if k in df:
            record_ok(f"{k}: {df[k]}")
        else:
            record_warn(f"{k}: 없음")

    # KR 종목 kr_score_breakdown
    hdr("  → KR 종목 kr_score_breakdown")
    kr_recs = [r for r in data.get("recommendations", []) if r.get("asset_class") == "kr_stock"]
    if kr_recs:
        rec = kr_recs[0]
        bd = rec.get("kr_score_breakdown")
        if bd and all(k in bd for k in ["yield_score", "stability", "financial", "growth"]):
            record_ok(f"{rec['name']} — kr_score_breakdown: {bd}")
        else:
            record_warn(f"{rec['name']} — kr_score_breakdown 없거나 불완전: {bd}")
    else:
        record_warn("KR 종목 없음 — kr_score_breakdown 검증 불가")


# ── [5] 극단값 입력 ───────────────────────────────────────────
def check_edge_cases(base_url: str):
    hdr("[5] 극단값 입력 — 오류 없이 반환 여부")
    if not HAS_REQUESTS:
        record_warn("requests 없음 — 건너뜀")
        return

    edge_cases = [
        ("18세 최연소", {**DEMO_PAYLOAD, "age": 18}),
        ("75세 고령",   {**DEMO_PAYLOAD, "age": 75, "risk_tolerance": "conservative"}),
        ("reserve=0",  {**DEMO_PAYLOAD, "investable_amount": 0, "monthly_savings": 50}),
        ("target=0",   {**DEMO_PAYLOAD, "monthly_target": 0}),
        ("초고액 투자", {**DEMO_PAYLOAD, "investable_amount": 1_000_000, "monthly_target": 500}),
        ("극소액 투자", {**DEMO_PAYLOAD, "investable_amount": 10, "monthly_savings": 1}),
    ]

    for label, payload in edge_cases:
        try:
            r = requests.post(
                f"{base_url}/api/portfolio/recommend",
                json=payload,
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                recs_cnt = len(data.get("recommendations", []))
                record_ok(f"{label} → HTTP 200, 추천 {recs_cnt}개")
            elif r.status_code in (400, 422):
                # 입력 검증 오류는 허용
                record_ok(f"{label} → HTTP {r.status_code} (입력 검증 거부 — 정상)")
            else:
                record_fail(f"{label} → HTTP {r.status_code}: {r.text[:100]}")
        except requests.exceptions.Timeout:
            record_warn(f"{label} → 30초 초과 (서버 과부하?)")
        except Exception as e:
            record_fail(f"{label} → 예외: {e}")


# ── [6] Ollama LLM 상태 ───────────────────────────────────────
def check_ollama():
    hdr("[6] Ollama LLM (qwen3:14b) 상태")
    if not HAS_REQUESTS:
        record_warn("requests 없음 — 건너뜀")
        return

    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code == 200:
            models = [m["name"] for m in r.json().get("models", [])]
            if any("qwen3" in m for m in models):
                match = [m for m in models if "qwen3" in m]
                record_ok(f"qwen3 모델 로드됨: {match[0]}")
            else:
                record_warn(f"qwen3 모델 없음. 현재 모델: {models[:3]}")
                warn("  → ollama pull qwen3:14b 실행 필요")
        else:
            record_warn(f"Ollama HTTP {r.status_code}")
    except requests.exceptions.ConnectionError:
        record_warn("Ollama 서버 미실행 — AI Advisor 사용 불가 (rule-based fallback 작동)")
        warn("  → 발표 30분 전: ollama serve && ollama run qwen3:14b 실행 권장")
    except Exception as e:
        record_warn(f"Ollama 확인 예외: {e}")


# ── [7] 환경 체크 ─────────────────────────────────────────────
def check_environment():
    hdr("[7] 환경 체크")

    # Python 버전
    pv = sys.version_info
    if pv >= (3, 10):
        record_ok(f"Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        record_warn(f"Python {pv.major}.{pv.minor} — 3.10+ 권장")

    # 필수 패키지
    pkgs = ["fastapi", "uvicorn", "pandas", "numpy", "sklearn", "xgboost"]
    for pkg in pkgs:
        try:
            import importlib
            importlib.import_module(pkg.replace("-", "_"))
            record_ok(f"패키지: {pkg}")
        except ImportError:
            record_fail(f"패키지 없음: {pkg} — pip install {pkg}")

    # frontend build or dev server (간접 확인)
    package_json = BASE_DIR / "frontend" / "package.json"
    if package_json.exists():
        record_ok("frontend/package.json 존재")
    else:
        record_fail("frontend/package.json 없음")

    # DEMO_RUNBOOK.md
    runbook = BASE_DIR / "DEMO_RUNBOOK.md"
    if runbook.exists():
        record_ok("DEMO_RUNBOOK.md 존재")
    else:
        record_warn("DEMO_RUNBOOK.md 없음 — docs/ 아래 확인")


# ── 메인 ──────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AI Cashflow OS 전시 사전 검증")
    parser.add_argument("--url",  default="http://localhost:8000", help="API 서버 URL")
    parser.add_argument("--fast", action="store_true", help="API 호출 생략 (파일 체크만)")
    args = parser.parse_args()

    print("=" * 60)
    print(" AI Cashflow OS — 전시 사전 검증 (Pre-flight Check)")
    print(f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    check_environment()
    check_data_files()
    check_model_files()

    if not args.fast:
        server_ok = check_api_server(args.url)
        if server_ok:
            demo_data = check_demo_pipeline(args.url)
            if demo_data:
                validate_demo_response(demo_data)
            check_edge_cases(args.url)
        check_ollama()
    else:
        hdr("[3-6] API 체크 건너뜀 (--fast 모드)")

    # ── 최종 결과 ──
    print("\n" + "=" * 60)
    total = PASS + WARN_COUNT + FAIL_COUNT
    print(f" 결과: ✓ {PASS}개 통과  ⚠ {WARN_COUNT}개 경고  ✗ {FAIL_COUNT}개 실패  (총 {total}개)")
    if FAIL_COUNT == 0 and WARN_COUNT == 0:
        print(" 🚀 전시 준비 완료! 발표를 시작해도 됩니다.")
    elif FAIL_COUNT == 0:
        print(" ⚠️  경고 항목 확인 후 발표 진행 가능.")
    else:
        print(" 🚨 실패 항목 해결 후 발표 진행하세요.")
    print("=" * 60)

    return 0 if FAIL_COUNT == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

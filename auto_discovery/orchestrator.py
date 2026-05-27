"""
자동 유니버스 관리 오케스트레이터

■ 전체 파이프라인
  1. 기존 approved_universe.json 로드
  2. 한국 스크리너 실행 → 신규 후보
  3. 미국 스크리너 실행 → 신규 후보
  4. 평가 엔진으로 채점
  5. 합격 종목 → approved_universe.json에 추가
  6. 기존 종목 재평가 → 탈락 종목 제거 (선택)
  7. 리포트 출력

■ 실행
  python discover.py              # 전체 실행
  python discover.py --kr-only   # 한국만
  python discover.py --us-only   # 미국만
  python discover.py --reeval    # 기존 종목 재평가
"""

import os
import json
import datetime
from typing import Literal

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_PATH = os.path.join(BASE_DIR, "data", "approved_universe.json")
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


# ── JSON 로드/저장 ─────────────────────────────────────────────

def load_universe() -> dict:
    """approved_universe.json 로드. 없으면 빈 구조 반환."""
    if os.path.exists(UNIVERSE_PATH):
        with open(UNIVERSE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_updated": None,
        "total_count":  0,
        "assets":       [],
    }


def save_universe(universe: dict) -> None:
    """approved_universe.json 저장."""
    universe["last_updated"] = datetime.datetime.now().isoformat()
    universe["total_count"]  = len(universe["assets"])
    with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, ensure_ascii=False, indent=2)
    print(f"\n  ✅ 유니버스 저장: {UNIVERSE_PATH}")
    print(f"     총 {universe['total_count']}개 자산")


# ── 오케스트레이터 메인 ───────────────────────────────────────

def run(
    mode: Literal["all", "kr_only", "us_only"] = "all",
    reeval_existing: bool = False,
) -> dict:
    """
    자동 발굴 → 평가 → 유니버스 업데이트 파이프라인.

    Parameters
    ----------
    mode            : "all" | "kr_only" | "us_only"
    reeval_existing : True면 기존 종목도 재평가해서 기준 미달 시 제거

    Returns
    -------
    dict : 실행 결과 요약
    """
    from auto_discovery.evaluator   import evaluate_all, PASS_SCORE
    from auto_discovery.screener_us import screen_us_assets, get_all_watchlist_tickers

    print("=" * 60)
    print("  🔍 자동 유니버스 발굴 파이프라인 시작")
    print("=" * 60)

    # ── 1. 기존 유니버스 로드 ──────────────────────────────────
    universe      = load_universe()
    existing      = universe["assets"]
    existing_tickers = {a["ticker"] for a in existing}

    print(f"\n  기존 유니버스: {len(existing)}개 자산")

    # ── 2. 스크리닝 ──────────────────────────────────────────
    new_candidates: list[dict] = []

    if mode in ("all", "kr_only"):
        try:
            from auto_discovery.screener_kr import screen_kr_stocks
            kr_candidates = screen_kr_stocks(existing_codes=existing_tickers)
            new_candidates.extend(kr_candidates)
        except Exception as e:
            print(f"  ⚠️ 한국 스크리너 오류: {e}")

    if mode in ("all", "us_only"):
        try:
            us_candidates = screen_us_assets(existing_tickers=existing_tickers)
            new_candidates.extend(us_candidates)
        except Exception as e:
            print(f"  ⚠️ 미국 스크리너 오류: {e}")

    print(f"\n  신규 후보 총계: {len(new_candidates)}개")

    # ── 3. 신규 후보 평가 ────────────────────────────────────
    approved_new, rejected_new = [], []
    if new_candidates:
        approved_new, rejected_new = evaluate_all(new_candidates)
        print(f"\n  평가 결과 (기준: {PASS_SCORE}점 이상)")
        print(f"  ✅ 합격: {len(approved_new)}개")
        print(f"  ❌ 탈락: {len(rejected_new)}개")

        if rejected_new:
            print("\n  [탈락 종목]")
            for r in rejected_new[:5]:
                print(f"    {r['ticker']:8} {r['name']:30} {r['eval_score']}점 — {r['eval_reason'][:50]}")

    # ── 4. 기존 종목 재평가 (선택) ───────────────────────────
    removed = []
    if reeval_existing and existing:
        print(f"\n  기존 {len(existing)}개 자산 재평가 중...")
        _, demoted = evaluate_all(existing)
        demoted_tickers = {d["ticker"] for d in demoted}
        if demoted_tickers:
            removed    = [a for a in existing if a["ticker"] in demoted_tickers]
            existing   = [a for a in existing if a["ticker"] not in demoted_tickers]
            print(f"  🗑️ 기준 미달 제거: {[r['ticker'] for r in removed]}")

    # ── 5. 유니버스 업데이트 ─────────────────────────────────
    # 이미 있는 티커 제외 후 추가
    existing_tickers_now = {a["ticker"] for a in existing}
    truly_new = [a for a in approved_new if a["ticker"] not in existing_tickers_now]

    if truly_new:
        print(f"\n  [신규 편입 종목]")
        for a in truly_new:
            print(f"  ✅ {a['ticker']:8} {a['name']:30} {a['eval_score']}점 | TR {a['total_return_est']}%")

    universe["assets"] = existing + truly_new

    # ── 6. 저장 ─────────────────────────────────────────────
    save_universe(universe)

    # ── 7. 요약 리포트 ───────────────────────────────────────
    report = {
        "run_at":          datetime.datetime.now().isoformat(),
        "mode":            mode,
        "reeval":          reeval_existing,
        "before_count":    len(existing) + len(removed),
        "new_candidates":  len(new_candidates),
        "newly_approved":  len(truly_new),
        "rejected":        len(rejected_new),
        "removed":         len(removed),
        "after_count":     len(universe["assets"]),
        "newly_added":     [a["ticker"] for a in truly_new],
        "removed_list":    [r["ticker"] for r in removed],
    }

    print("\n" + "=" * 60)
    print("  ✅ 파이프라인 완료")
    print(f"  전: {report['before_count']}개 → 후: {report['after_count']}개")
    print(f"  신규 편입: {report['newly_added']}")
    print("=" * 60)

    return report

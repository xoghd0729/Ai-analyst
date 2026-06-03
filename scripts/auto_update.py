"""
scripts/auto_update.py — 무인 데이터 갱신·재학습 오케스트레이터
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

네 단계를 순서대로 실행하고, 검증 게이트를 통과할 때만 재학습한다.

  1. expand_universe.py   — KRX 배당주 자동 편입 (유니버스 누적 확장)
  2. build_dataset.py     — DART 수집 (체크포인트·이어받기)
  3. data_validator.py    — 품질 게이트 (FAIL이면 학습 중단)
  4. train_kr_3class.py   — 재학습 (+ 성능 history 기록·회귀 감지)

각 단계 로그는 logs/auto_update_YYYYMMDD.log 에 누적.

수동 실행
  python scripts/auto_update.py
  python scripts/auto_update.py --skip-expand          # 유니버스 그대로
  python scripts/auto_update.py --min-cap 5000

주기 실행 (무인)
  data_pipeline.py 의 스케줄러에 등록하거나, 간단히 cron:
    0 2 * * 0  cd ~/ai-analyst && venv/bin/python scripts/auto_update.py
  (매주 일요일 02시)

주의
  build_dataset / expand_universe 는 외부 API(DART·pykrx)를 쓰므로
  네트워크가 안정적인 환경에서 돌려야 한다. 끊겨도 체크포인트로 복구됨.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable                      # 현재 venv의 파이썬 사용
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_PATH = os.path.join(LOG_DIR, f"auto_update_{datetime.now():%Y%m%d}.log")


def _log(msg: str) -> None:
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _run(label: str, args: list[str], gate: bool = False) -> int:
    """스크립트 실행. gate=True면 exit code != 0 일 때 전체 중단."""
    _log(f"▶ {label} 시작: {' '.join(args)}")
    proc = subprocess.run([PYTHON, *args], cwd=BASE_DIR,
                          capture_output=True, text=True)
    # 자식 출력도 로그에 남김 (요약: 마지막 40줄)
    tail = "\n".join(proc.stdout.strip().splitlines()[-40:])
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(tail + "\n")
        if proc.stderr.strip():
            f.write("[stderr] " + proc.stderr.strip()[-2000:] + "\n")
    rc = proc.returncode
    _log(f"  {label} 종료 (exit={rc})")
    if gate and rc != 0:
        _log(f"  ⛔ 게이트 실패 → 파이프라인 중단")
        sys.exit(rc)
    return rc


def main() -> None:
    ap = argparse.ArgumentParser(description="무인 데이터 갱신·재학습 파이프라인")
    ap.add_argument("--skip-expand", action="store_true", help="유니버스 확장 건너뜀")
    ap.add_argument("--min-cap", type=float, default=8000, help="유니버스 최소 시총(억), 기본 8000")
    ap.add_argument("--min-yield", type=float, default=1.5, help="유니버스 최소 배당수익률(%%)")
    args = ap.parse_args()

    _log("=" * 50)
    _log("무인 파이프라인 시작")
    _log("=" * 50)

    # 1. 유니버스 확장
    if not args.skip_expand:
        _run("1/4 유니버스 확장",
             ["scripts/expand_universe.py",
              "--min-cap", str(args.min_cap),
              "--min-yield", str(args.min_yield)])
    else:
        _log("1/4 유니버스 확장 건너뜀")

    # 2. 데이터 수집 (이어받기)
    _run("2/4 데이터 수집", ["build_dataset.py"])

    # 3. 품질 게이트 — FAIL이면 여기서 중단
    _run("3/4 데이터 검증(게이트)", ["utils/data_validator.py"], gate=True)

    # 4. 재학습 + 성능 추적
    _run("4/4 재학습", ["train_kr_3class.py"])

    _log("=" * 50)
    _log(f"✅ 파이프라인 완료. 로그: {LOG_PATH}")
    _log("=" * 50)


if __name__ == "__main__":
    main()

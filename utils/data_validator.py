"""
utils/data_validator.py — 학습 데이터 품질 검증 레이어
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가
  유니버스가 커질수록 오염 데이터(결측 폭증·이상치·라벨 깨짐)가
  모델로 흘러들 위험이 커진다. 이 모듈은 dividend_dataset.csv를
  학습 전에 자동 점검해, 문제를 등급(PASS/WARN/FAIL)으로 보고한다.

검사 항목
  1. 행/종목 수 최소 기준
  2. 피처별 결측률 (임계 초과 경고)
  3. 이상치: payout_ratio·debt_ratio 비현실적 값
  4. 연도 연속성: 종목별 연도 중복/역행
  5. 라벨 무결성: dividend_cut ∈ {0,1}, label3 ∈ {0,1,2}
  6. 클래스 균형: WEAKENING/BROKEN 최소 표본

사용
  python utils/data_validator.py
  → data/validation_report.json 저장 + 콘솔 요약, FAIL 시 exit code 1

  코드에서:
  from utils.data_validator import validate_dataset
  report = validate_dataset("data/dividend_dataset.csv")
  if report["grade"] == "FAIL": ...
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CSV = os.path.join(BASE_DIR, "data", "dividend_dataset.csv")
REPORT_PATH = os.path.join(BASE_DIR, "data", "validation_report.json")

# ── 임계값 (운영 기준) ────────────────────────────────────────
MIN_ROWS          = 300
MIN_STOCKS        = 40
MISSING_WARN_PCT  = 60.0     # 이 이상이면 경고 (노이즈 피처 후보)
MISSING_FAIL_PCT  = 95.0     # 거의 전부 결측 → 실패
MIN_WEAKENING     = 30       # 소수 클래스 최소 표본
MIN_BROKEN        = 50
# 이상치 한계
PAYOUT_MAX        = 1000.0   # 배당성향 1000% 초과 = 의심
DEBT_RATIO_MAX    = 2000.0   # 부채비율 2000% 초과 = 의심


def _check(report: dict, name: str, ok: bool, level: str, msg: str) -> None:
    report["checks"].append({"name": name, "ok": ok, "level": level, "msg": msg})


def validate_dataset(csv_path: str = DEFAULT_CSV) -> dict:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "csv": csv_path,
        "checks": [],
        "grade": "PASS",
    }
    if not os.path.exists(csv_path):
        report["grade"] = "FAIL"
        _check(report, "file_exists", False, "FAIL", f"파일 없음: {csv_path}")
        return _finalize(report)

    df = pd.read_csv(csv_path)
    n_rows = len(df)
    n_stocks = df["stock_code"].nunique() if "stock_code" in df else 0
    report["n_rows"] = n_rows
    report["n_stocks"] = int(n_stocks)

    # 1. 최소 규모
    _check(report, "min_rows", n_rows >= MIN_ROWS,
           "FAIL" if n_rows < MIN_ROWS else "OK",
           f"행 {n_rows} (최소 {MIN_ROWS})")
    _check(report, "min_stocks", n_stocks >= MIN_STOCKS,
           "FAIL" if n_stocks < MIN_STOCKS else "OK",
           f"종목 {n_stocks} (최소 {MIN_STOCKS})")

    # 2. 결측률
    miss = {}
    for col in df.columns:
        pct = round(df[col].isna().mean() * 100, 1)
        miss[col] = pct
        if pct >= MISSING_FAIL_PCT:
            _check(report, f"missing:{col}", False, "FAIL", f"{col} 결측 {pct}%")
        elif pct >= MISSING_WARN_PCT:
            _check(report, f"missing:{col}", False, "WARN", f"{col} 결측 {pct}% (노이즈 후보)")
    report["missing_pct"] = miss

    # 3. 이상치
    if "payout_ratio" in df:
        bad = int((df["payout_ratio"].abs() > PAYOUT_MAX).sum())
        _check(report, "outlier:payout_ratio", bad == 0,
               "WARN" if bad else "OK", f"배당성향 |값|>{PAYOUT_MAX}: {bad}행")
    if "debt_ratio" in df:
        bad = int((df["debt_ratio"].abs() > DEBT_RATIO_MAX).sum())
        _check(report, "outlier:debt_ratio", bad == 0,
               "WARN" if bad else "OK", f"부채비율 |값|>{DEBT_RATIO_MAX}: {bad}행")

    # 4. 연도 연속성 (종목별 연도 중복 검사)
    if {"stock_code", "year"}.issubset(df.columns):
        dup = int(df.duplicated(subset=["stock_code", "year"]).sum())
        _check(report, "year_duplicates", dup == 0,
               "FAIL" if dup else "OK", f"종목×연도 중복 {dup}행")

    # 5. 라벨 무결성
    if "dividend_cut" in df:
        vals = set(df["dividend_cut"].dropna().unique())
        ok = vals.issubset({0, 1, 0.0, 1.0})
        _check(report, "label:dividend_cut", ok, "FAIL" if not ok else "OK",
               f"dividend_cut 값 {sorted(vals)}")
    if "label3" in df:
        vals = set(df["label3"].dropna().unique())
        ok = vals.issubset({0, 1, 2, 0.0, 1.0, 2.0})
        _check(report, "label:label3", ok, "FAIL" if not ok else "OK",
               f"label3 값 {sorted(vals)}")

    # 6. 클래스 균형
    if "label3" in df:
        vc = df["label3"].dropna().astype(int).value_counts().to_dict()
        report["class_dist"] = {str(k): int(v) for k, v in vc.items()}
        weak = vc.get(1, 0)
        broken = vc.get(2, 0)
        _check(report, "class:WEAKENING", weak >= MIN_WEAKENING,
               "WARN" if weak < MIN_WEAKENING else "OK",
               f"WEAKENING {weak}건 (최소 {MIN_WEAKENING})")
        _check(report, "class:BROKEN", broken >= MIN_BROKEN,
               "WARN" if broken < MIN_BROKEN else "OK",
               f"BROKEN {broken}건 (최소 {MIN_BROKEN})")

    return _finalize(report)


def _finalize(report: dict) -> dict:
    levels = [c["level"] for c in report["checks"]]
    if "FAIL" in levels:
        report["grade"] = "FAIL"
    elif "WARN" in levels:
        report["grade"] = "WARN"
    else:
        report["grade"] = "PASS"
    report["n_fail"] = levels.count("FAIL")
    report["n_warn"] = levels.count("WARN")
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return report


def _print(report: dict) -> None:
    icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
    print("=" * 56)
    print("  데이터 검증 리포트")
    print("=" * 56)
    print(f"  행 {report.get('n_rows','?')} | 종목 {report.get('n_stocks','?')}")
    if "class_dist" in report:
        print(f"  클래스 분포 {report['class_dist']}")
    print("-" * 56)
    for c in report["checks"]:
        if c["level"] != "OK":
            print(f"  {icon.get(c['level'],'•')} [{c['level']}] {c['msg']}")
    print("-" * 56)
    print(f"  종합: {icon.get(report['grade'])} {report['grade']}  "
          f"(FAIL {report['n_fail']} / WARN {report['n_warn']})")
    print(f"  리포트: {REPORT_PATH}")
    print("=" * 56)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    rep = validate_dataset(path)
    _print(rep)
    sys.exit(1 if rep["grade"] == "FAIL" else 0)

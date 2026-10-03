"""
utils/baseline_benchmark.py
============================

■ 목적
  walk_forward_validator.py 기반으로 현재 데이터셋의
  OOS 기준 성능(baseline)을 측정하고 JSON으로 저장한다.

  피처를 추가할 때마다 이 baseline과 비교하면
  "실제 out-of-time 성능이 좋아졌는가?"를 수치로 확인할 수 있다.

■ 실행 방법
  cd ~/ai-analyst
  source venv/bin/activate
  python utils/baseline_benchmark.py

■ 출력
  data/baseline_performance.json   — fold별 + OOS 집계 결과
  콘솔: 간단 요약 테이블

■ 모델
  LogisticRegression (L2, max_iter=500) — 단순하고 재현 가능한 baseline
  RandomForestClassifier               — 비선형 baseline
  DummyClassifier (stratified)         — 무작위 baseline (floor 확인용)
"""

from __future__ import annotations
import json, os, sys, warnings
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.dummy import DummyClassifier

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from utils.walk_forward_validator import (
    walk_forward_validate,
    leakage_check_df,
    TRAIN_FEATURES,
    VALID_TARGETS,
)

# ─────────────────────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────────────────────

DATA_PATH   = os.path.join(os.path.dirname(__file__), "..", "data", "dividend_dataset.csv")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "baseline_performance.json")

MODELS = {
    "dummy":   (DummyClassifier, {"strategy": "stratified", "random_state": 42}),
    "logistic": (LogisticRegression, {"max_iter": 500, "random_state": 42, "C": 0.1}),
    "rf":      (RandomForestClassifier, {"n_estimators": 100, "random_state": 42,
                                          "max_depth": 4, "min_samples_leaf": 5}),
}


# ─────────────────────────────────────────────────────────────
# 메인 실행
# ─────────────────────────────────────────────────────────────

def run_baseline() -> dict:
    print("=" * 60)
    print("  Dividend Cut Prediction — Baseline Benchmark")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # ── 데이터 로드 ──────────────────────────────────────────
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(
            f"{DATA_PATH} 없음. build_dataset.py 먼저 실행 필요."
        )
    df = pd.read_csv(DATA_PATH, encoding="utf-8-sig", dtype={"stock_code": str})
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    print(f"\n  데이터: {len(df)}행 / {df['stock_code'].nunique()}종목 / "
          f"{int(df['year'].min())}~{int(df['year'].max())}년")

    # ── 레거시 라벨 누락 시 생성 ─────────────────────────────
    needs_regen = any(t not in df.columns for t in VALID_TARGETS)
    if needs_regen:
        print("\n  ⚠️  label_cut_1y/3y/5y 없음 → 자동 생성 중...")
        df["dividend_cut"] = pd.to_numeric(df.get("dividend_cut"), errors="coerce")
        df = df.sort_values(["stock_code", "year"])
        for n in range(1, 6):
            df[f"_cut_n{n}"] = df.groupby("stock_code")["dividend_cut"].shift(-n)
        df["label_cut_1y"] = df["_cut_n1"]
        def _any3(row):
            vals = [row[f"_cut_n{n}"] for n in range(1, 4) if pd.notna(row[f"_cut_n{n}"])]
            return (1.0 if any(v == 1 for v in vals) else 0.0) if vals else None
        def _any5(row):
            vals = [row[f"_cut_n{n}"] for n in range(1, 6) if pd.notna(row[f"_cut_n{n}"])]
            return (1.0 if any(v == 1 for v in vals) else 0.0) if vals else None
        df["label_cut_3y"] = df.apply(_any3, axis=1)
        df["label_cut_5y"] = df.apply(_any5, axis=1)
        df = df.drop(columns=[f"_cut_n{n}" for n in range(1, 6)])

    # ── 라벨 분포 출력 ───────────────────────────────────────
    print("\n  타깃 분포:")
    for tgt in VALID_TARGETS:
        if tgt in df.columns:
            s = df[tgt].dropna()
            print(f"    {tgt}: N={len(s)}, positive={int(s.sum())} ({s.mean()*100:.1f}%)")

    # ── Leakage 검사 ─────────────────────────────────────────
    avail_feats = [f for f in TRAIN_FEATURES if f in df.columns]
    print(f"\n  사용 가능 피처: {len(avail_feats)}/{len(TRAIN_FEATURES)}개")
    missing = [f for f in TRAIN_FEATURES if f not in df.columns]
    if missing:
        print(f"  누락 피처: {missing}")

    leakage_report = leakage_check_df(df, avail_feats)

    # ── Walk-Forward 실행 ────────────────────────────────────
    all_results: dict = {
        "run_at": datetime.now().isoformat(),
        "data_rows": len(df),
        "n_stocks": int(df["stock_code"].nunique()),
        "year_range": [int(df["year"].min()), int(df["year"].max())],
        "features_used": avail_feats,
        "leakage_report": leakage_report,
        "results": {},
    }

    summary_rows = []
    for model_name, (model_cls, model_params) in MODELS.items():
        all_results["results"][model_name] = {}
        for tgt in VALID_TARGETS:
            if tgt not in df.columns:
                continue
            print(f"\n{'─'*60}")
            print(f"  [{model_name.upper()}] → {tgt}")
            print(f"{'─'*60}")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    result = walk_forward_validate(
                        df,
                        model_class=model_cls,
                        model_params=model_params,
                        target=tgt,
                        features=avail_feats,
                        verbose=True,
                    )
                except Exception as exc:
                    print(f"  ❌ 오류: {exc}")
                    continue

            oos = result["oos_summary"]
            all_results["results"][model_name][tgt] = {
                "folds": result["folds"],
                "oos_summary": oos,
            }
            summary_rows.append({
                "model":   model_name,
                "target":  tgt,
                "n_folds": oos.get("n_folds", 0),
                "roc_auc": oos.get("oos_roc_auc") or oos.get("roc_auc_mean"),
                "pr_auc":  oos.get("oos_pr_auc")  or oos.get("pr_auc_mean"),
                "brier":   oos.get("oos_brier_score") or oos.get("brier_score_mean"),
                "recall":  oos.get("recall_mean"),
                "precision": oos.get("precision_mean"),
            })

    # ── 요약 테이블 ──────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  BASELINE OOS 성능 요약")
    print("=" * 70)
    fmt = "  {:<10} {:<15} {:>6} {:>7} {:>7} {:>7} {:>8} {:>9}"
    print(fmt.format("Model", "Target", "Folds", "ROC-AUC", "PR-AUC",
                     "Brier", "Recall", "Precision"))
    print("  " + "-" * 68)
    for r in summary_rows:
        def _f(v): return f"{v:.4f}" if v is not None else "  N/A"
        print(fmt.format(
            r["model"], r["target"], r["n_folds"],
            _f(r["roc_auc"]), _f(r["pr_auc"]), _f(r["brier"]),
            _f(r["recall"]), _f(r["precision"]),
        ))

    # ── 저장 ─────────────────────────────────────────────────
    all_results["summary"] = summary_rows
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  ✅ 베이스라인 저장: {OUTPUT_PATH}")
    print("     다음 Feature Engineering 후 이 파일과 비교하세요.\n")

    return all_results


if __name__ == "__main__":
    run_baseline()

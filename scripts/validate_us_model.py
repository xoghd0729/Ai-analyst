"""
Validate the US dividend-cut model for capstone reporting.

Outputs:
  reports/us_model_validation/metrics.csv
  reports/us_model_validation/summary.md

The goal is not only to get a score, but to prove what the model learned:
  - expanding-year holdout: train on prior years, test on the next year
  - leave-one-year-out: train on all other years, test on one year
  - feature ablation: full features vs. no DPS YoY signal
  - rule baselines: simple payout/coverage/DPS rules
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "us_dividend_dataset.csv")
REPORT_DIR = os.path.join(BASE_DIR, "reports", "us_model_validation")
MODEL_PATH = os.path.join(BASE_DIR, "models", "us_dividend_cut_model.pkl")

TARGET = "dividend_cut"
THRESHOLD = 0.30

BASE_FEATURES = [
    "payout_ratio",
    "dividend_coverage",
    "dps_yoy_pct",
    "div_to_ocf",
    "fcf_negative",
    "shareholder_yield",
    "net_debt_ebitda",
    "consecutive_years",
]


@dataclass
class FeatureSet:
    name: str
    columns: list[str]


def prepare_features(df: pd.DataFrame, base_cols: list[str]) -> pd.DataFrame:
    x = df[[c for c in base_cols if c in df.columns]].copy()
    if "net_debt_ebitda" in x.columns:
        x["net_debt_ebitda"] = x["net_debt_ebitda"].clip(-5, 20)
    if "payout_ratio" in x.columns:
        x["payout_over_100"] = (x["payout_ratio"] > 100).astype(int)
        x["payout_over_80"] = (x["payout_ratio"] > 80).astype(int)
    if "dps_yoy_pct" in x.columns:
        x["dps_declining"] = (x["dps_yoy_pct"] < 0).astype(int)
    return x


def make_model(y_train: pd.Series) -> Pipeline:
    pos = int((y_train == 1).sum())
    neg = int((y_train == 0).sum())
    pos_weight = neg / max(pos, 1)
    model = xgb.XGBClassifier(
        n_estimators=150,
        max_depth=3,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=pos_weight,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", model),
    ])


def metric_row(
    experiment: str,
    model_name: str,
    test_year: int,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    y_true: pd.Series,
    prob: np.ndarray,
    pred: np.ndarray,
    notes: str = "",
) -> dict:
    tn, fp, fn, tp = confusion_matrix(y_true, pred, labels=[0, 1]).ravel()
    has_both = y_true.nunique() == 2
    return {
        "experiment": experiment,
        "model": model_name,
        "test_year": test_year,
        "train_rows": len(train_df),
        "test_rows": len(test_df),
        "train_cuts": int(train_df[TARGET].sum()),
        "test_cuts": int(test_df[TARGET].sum()),
        "auc": round(roc_auc_score(y_true, prob), 4) if has_both else np.nan,
        "pr_auc": round(average_precision_score(y_true, prob), 4) if has_both else np.nan,
        "f1": round(f1_score(y_true, pred, zero_division=0), 4),
        "precision": round(precision_score(y_true, pred, zero_division=0), 4),
        "recall": round(recall_score(y_true, pred, zero_division=0), 4),
        "accuracy": round(accuracy_score(y_true, pred), 4),
        "tp": int(tp),
        "fp": int(fp),
        "tn": int(tn),
        "fn": int(fn),
        "notes": notes,
    }


def evaluate_model(
    experiment: str,
    feature_set: FeatureSet,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    test_year: int,
) -> dict | None:
    y_train = train_df[TARGET].astype(int)
    y_test = test_df[TARGET].astype(int)
    if y_train.nunique() < 2:
        return None

    x_train = prepare_features(train_df, feature_set.columns)
    x_test = prepare_features(test_df, feature_set.columns)

    pipe = make_model(y_train)
    pipe.fit(x_train, y_train)
    prob = pipe.predict_proba(x_test)[:, 1]
    pred = (prob >= THRESHOLD).astype(int)
    return metric_row(experiment, feature_set.name, test_year, train_df, test_df, y_test, prob, pred)


def evaluate_rule(
    experiment: str,
    rule_name: str,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    test_year: int,
    prob: np.ndarray,
    notes: str,
) -> dict:
    y_test = test_df[TARGET].astype(int)
    pred = (prob >= THRESHOLD).astype(int)
    return metric_row(experiment, rule_name, test_year, train_df, test_df, y_test, prob, pred, notes)


def build_rule_rows(experiment: str, train_df: pd.DataFrame, test_df: pd.DataFrame, test_year: int) -> list[dict]:
    payout = pd.to_numeric(test_df.get("payout_ratio"), errors="coerce")
    coverage = pd.to_numeric(test_df.get("dividend_coverage"), errors="coerce")
    dps = pd.to_numeric(test_df.get("dps_yoy_pct"), errors="coerce")

    rows = []
    rows.append(evaluate_rule(
        experiment,
        "rule_dps_yoy_lt_minus_5",
        train_df,
        test_df,
        test_year,
        np.where(dps < -5, 1.0, 0.0),
        "This is label-equivalent and should be treated as a leakage baseline.",
    ))
    rows.append(evaluate_rule(
        experiment,
        "rule_payout_gt_100",
        train_df,
        test_df,
        test_year,
        np.where(payout > 100, 1.0, 0.0),
        "Simple accounting stress rule.",
    ))
    rows.append(evaluate_rule(
        experiment,
        "rule_coverage_lt_1",
        train_df,
        test_df,
        test_year,
        np.where(coverage < 1, 1.0, 0.0),
        "Simple FCF coverage rule.",
    ))
    combo_score = (
        np.where(payout > 100, 0.40, 0.0)
        + np.where(coverage < 1, 0.35, 0.0)
        + np.where(dps < 0, 0.25, 0.0)
    )
    rows.append(evaluate_rule(
        experiment,
        "rule_combo_accounting",
        train_df,
        test_df,
        test_year,
        combo_score,
        "Payout, coverage, and dividend trend combined.",
    ))
    return rows


def make_summary(df: pd.DataFrame, data: pd.DataFrame) -> str:
    year_table = data.groupby("year")[TARGET].agg(["sum", "count", "mean"]).reset_index()
    quality_cols = [
        "payout_ratio",
        "fcf",
        "dividend_coverage",
        "shareholder_yield",
        "net_debt_ebitda",
        "dps_yoy_pct",
    ]
    quality = (
        data.groupby("year")[[c for c in quality_cols if c in data.columns]]
        .apply(lambda g: g.isna().mean() * 100)
        .reset_index()
    )
    full = df[(df["model"] == "xgb_full") & (df["experiment"] == "expanding_holdout")]
    no_yoy = df[(df["model"] == "xgb_no_dps_yoy") & (df["experiment"] == "expanding_holdout")]

    lines = [
        "# US Dividend-Cut Model Validation",
        "",
        "## Dataset",
        "",
        f"- Rows: {len(data)}",
        f"- Tickers: {data['ticker'].nunique()}",
        f"- Years: {int(data['year'].min())}-{int(data['year'].max())}",
        f"- Dividend cuts: {int(data[TARGET].sum())} ({data[TARGET].mean() * 100:.1f}%)",
        "",
        "### Cuts By Year",
        "",
        "| year | cuts | rows | cut_rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in year_table.itertuples(index=False):
        lines.append(f"| {int(row.year)} | {int(row.sum)} | {int(row.count)} | {row.mean * 100:.1f}% |")

    lines += [
        "",
        "### Missingness By Year",
        "",
        "| year | payout | fcf | coverage | shareholder_yield | net_debt_ebitda | dps_yoy |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in quality.itertuples(index=False):
        lines.append(
            f"| {int(row.year)} | {row.payout_ratio:.1f}% | {row.fcf:.1f}% | "
            f"{row.dividend_coverage:.1f}% | {row.shareholder_yield:.1f}% | "
            f"{row.net_debt_ebitda:.1f}% | {row.dps_yoy_pct:.1f}% |"
        )

    lines += [
        "",
        "## Key Finding",
        "",
        "- The full XGBoost model performs extremely well because `dps_yoy_pct` is very close to the label definition.",
        "- This is useful as an early warning signal, but it is not enough to claim that the model learned deep financial distress.",
        "- The no-DPS-YoY ablation is the honest stress test: it shows how much predictive power remains from payout, FCF coverage, leverage, and shareholder yield.",
        "",
        "## Expanding Holdout Results",
        "",
        "| test_year | model | test_cuts | AUC | PR-AUC | F1 | precision | recall | FP | FN |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    focus = df[df["experiment"] == "expanding_holdout"].copy()
    for row in focus.itertuples(index=False):
        auc = "" if pd.isna(row.auc) else f"{row.auc:.3f}"
        pr_auc = "" if pd.isna(row.pr_auc) else f"{row.pr_auc:.3f}"
        lines.append(
            f"| {row.test_year} | {row.model} | {row.test_cuts} | {auc} | {pr_auc} | "
            f"{row.f1:.3f} | {row.precision:.3f} | {row.recall:.3f} | {row.fp} | {row.fn} |"
        )

    def avg_metric(frame: pd.DataFrame, col: str) -> str:
        vals = frame[col].dropna()
        return "n/a" if vals.empty else f"{vals.mean():.3f}"

    lines += [
        "",
        "## Interpretation For Presentation",
        "",
        f"- Full model average expanding-holdout AUC: {avg_metric(full, 'auc')}",
        f"- No-DPS-YoY model average expanding-holdout AUC: {avg_metric(no_yoy, 'auc')}",
        "- If full >> no-DPS-YoY, explain that the current US model is strongest at detecting already-visible dividend trend breaks.",
        "- The next improvement is to predict cuts before the DPS decline appears, using payout stress, FCF coverage, leverage, earnings trend, and sector context.",
        "",
        "## Recommended Capstone Framing",
        "",
        "This project is a full-stack decision-support system. The model is not presented as an oracle; it combines ML risk, financial rules, news events, and LLM-generated thesis text. The validation step explicitly exposes model leakage risk and guides the next iteration.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    os.makedirs(REPORT_DIR, exist_ok=True)
    df = pd.read_csv(DATA_PATH)
    df = df.dropna(subset=[TARGET, "year"]).copy()
    df["year"] = df["year"].astype(int)
    df[TARGET] = df[TARGET].astype(int)

    feature_sets = [
        FeatureSet("xgb_full", BASE_FEATURES),
        FeatureSet("xgb_no_dps_yoy", [c for c in BASE_FEATURES if c != "dps_yoy_pct"]),
    ]

    rows: list[dict] = []
    years = [int(y) for y in sorted(df["year"].unique())]

    for year in years:
        test_df = df[df["year"] == year].copy()
        train_df = df[df["year"] < year].copy()
        if len(train_df) > 0:
            for fs in feature_sets:
                row = evaluate_model("expanding_holdout", fs, train_df, test_df, year)
                if row:
                    rows.append(row)
            rows.extend(build_rule_rows("expanding_holdout", train_df, test_df, year))

    for year in years:
        test_df = df[df["year"] == year].copy()
        train_df = df[df["year"] != year].copy()
        for fs in feature_sets:
            row = evaluate_model("leave_one_year_out", fs, train_df, test_df, year)
            if row:
                rows.append(row)
        rows.extend(build_rule_rows("leave_one_year_out", train_df, test_df, year))

    metrics = pd.DataFrame(rows)
    metrics_path = os.path.join(REPORT_DIR, "metrics.csv")
    metrics.to_csv(metrics_path, index=False, encoding="utf-8-sig")

    quality_cols = [
        "payout_ratio",
        "fcf",
        "dividend_coverage",
        "div_to_ocf",
        "shareholder_yield",
        "net_debt_ebitda",
        "dps_yoy_pct",
    ]
    quality = (
        df.groupby("year")[[c for c in quality_cols if c in df.columns]]
        .apply(lambda g: g.isna().mean() * 100)
        .round(2)
        .reset_index()
    )
    quality.to_csv(os.path.join(REPORT_DIR, "data_quality_by_year.csv"), index=False, encoding="utf-8-sig")

    summary = make_summary(metrics, df)
    summary_path = os.path.join(REPORT_DIR, "summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)

    meta = {
        "data_path": DATA_PATH,
        "model_path": MODEL_PATH,
        "report_dir": REPORT_DIR,
        "threshold": THRESHOLD,
        "years": years,
        "rows": int(len(df)),
        "tickers": int(df["ticker"].nunique()),
        "cuts": int(df[TARGET].sum()),
    }
    with open(os.path.join(REPORT_DIR, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"Saved metrics: {metrics_path}")
    print(f"Saved summary: {summary_path}")


if __name__ == "__main__":
    main()

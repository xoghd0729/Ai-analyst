"""
experiments/ml_dependency_audit.py

ML 의존성 감사 스크립트 — 별도 감사 경로 (파이프라인 미변경)

목적:
  ML 점수(XGBoost ml_status + TabPFN hazard_pct)를 제외했을 때
  KR 배당주 추천 결과가 어떻게 달라지는지 비교한다.

  이 스크립트는 추천 파이프라인을 변경하지 않는다.
  동일한 ranking.csv / survival_pd_v4.json을 읽어 독립 비교를 생성한다.

재무 룰 기준 (ML 제외 경로에서 사용 — 스크립트 실행 전 확정, 변경 금지):
  1. trap_level != "DANGER"       (현재 파이프라인과 동일)
  2. overall_score >= 50          (현재 파이프라인과 동일)
  3. dps_cuts_3y == 0            (배당 삭감 이력 없음)
  4. avg_payout_pct <= 80        (배당성향 80% 이하 — 지속 가능성 기준)
  5. stability >= 20             (안정성 점수 — ranking.csv 내 재무 기반 지표)
  6. financial >= 10             (재무 건전성 점수)

주의:
  - Overlap이 높다고 재무 룰이 더 정확한 것이 아님
  - Overlap이 낮다고 ML이 우수한 것이 아님
  - 이 실험은 추천 결과의 ML 의존성 측정이 목적

실행:
  cd ~/ai-analyst
  python experiments/ml_dependency_audit.py [--risk conservative|moderate|aggressive] [--age 40]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

RANKING_CSV      = os.path.join(BASE, "data", "ranking.csv")
SURVIVAL_JSON    = os.path.join(BASE, "results", "survival_pd_v4.json")
RESULT_DIR       = os.path.join(BASE, "results")

# ──────────────────────────────────────────────
# 재무 룰 기준 (고정 — 결과 보고 후 변경 금지)
# ──────────────────────────────────────────────
RULE_SPEC = {
    "trap_level_exclude": ["DANGER"],         # 규칙 1: DANGER 항상 제외 (파이프라인 동일)
    "overall_score_min": 50.0,                # 규칙 2: 점수 50점 이상 (파이프라인 동일)
    "dps_cuts_3y_max": 0,                     # 규칙 3: 최근 3년 삭감 이력 없음
    "avg_payout_pct_max": 80.0,               # 규칙 4: 배당성향 80% 이하
    "stability_min": 20.0,                    # 규칙 5: 안정성 점수 20점 이상
    "financial_min": 10.0,                    # 규칙 6: 재무 건전성 10점 이상
}

# Survival Hard Gate 임계값 (현재 파이프라인과 동일)
SURVIVAL_GATE = {
    "conservative": 0.35,
    "moderate":     0.50,
    "aggressive":   0.65,
}


def load_ranking() -> pd.DataFrame:
    df = pd.read_csv(RANKING_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)
    df = df[df["stock_code"].str.match(r"^\d{6}$")]
    return df


def load_survival() -> dict:
    if not os.path.exists(SURVIVAL_JSON):
        return {}
    with open(SURVIVAL_JSON) as f:
        return json.load(f).get("stock_risk", {})


def apply_base_filters(df: pd.DataFrame) -> pd.DataFrame:
    """파이프라인과 동일한 공통 필터 (ML 무관)."""
    # 규칙 1: DANGER 제외
    if "trap_level" in df.columns:
        df = df[~df["trap_level"].isin(RULE_SPEC["trap_level_exclude"])]
    # 규칙 2: overall_score >= 50
    if "overall_score" in df.columns:
        df = df[pd.to_numeric(df["overall_score"], errors="coerce").fillna(0)
                >= RULE_SPEC["overall_score_min"]]
    return df.copy()


def path_current_ml(df: pd.DataFrame, risk: str, survival: dict, age: int) -> pd.DataFrame:
    """
    현재 파이프라인과 동일한 경로:
      - Survival Hard Gate (hazard_pct > threshold 제외)
      - conservative: ml_status == "INTACT" 추가 필터
      - 나이 기반 정렬 틸트
    """
    df = apply_base_filters(df).copy()

    # Survival Hard Gate
    gate = SURVIVAL_GATE.get(risk, 0.50)
    if survival:
        df["_hazard"] = df["stock_code"].apply(
            lambda c: survival.get(str(c), {}).get("hazard_pct", 0.5)
        )
        df["hazard_pct_used"] = df["_hazard"]
        df = df[df["_hazard"] <= gate]
    else:
        df["hazard_pct_used"] = None

    # conservative: ml_status == INTACT
    if risk == "conservative" and "ml_status" in df.columns:
        df = df[df["ml_status"] == "INTACT"]
    elif risk == "aggressive" and "yield" in df.columns:
        df = df.sort_values("yield", ascending=False)

    # 나이 기반 정렬
    df = _age_sort(df, age)
    df["path"] = "current_ml"
    return df.head(9).copy()


def path_rule_only(df: pd.DataFrame, risk: str, age: int) -> pd.DataFrame:
    """
    재무 룰만 사용 (ML 완전 제외):
      - 규칙 1~6 적용
      - Survival Hard Gate 없음
      - ml_status 필터 없음
    """
    df = apply_base_filters(df).copy()

    # 규칙 3: 배당 삭감 이력 없음
    if "dps_cuts_3y" in df.columns:
        df = df[pd.to_numeric(df["dps_cuts_3y"], errors="coerce").fillna(99)
                <= RULE_SPEC["dps_cuts_3y_max"]]

    # 규칙 4: 배당성향 80% 이하
    # NaN은 탈락이 아닌 "검토 필요"로 분류 (데이터 없음 ≠ 위험)
    # → NaN은 통과, 80% 초과만 탈락
    if "avg_payout_pct" in df.columns:
        payout_num = pd.to_numeric(df["avg_payout_pct"], errors="coerce")
        df = df[payout_num.isna() | (payout_num <= RULE_SPEC["avg_payout_pct_max"])]

    # 규칙 5: 안정성 20점 이상
    if "stability" in df.columns:
        df = df[pd.to_numeric(df["stability"], errors="coerce").fillna(0)
                >= RULE_SPEC["stability_min"]]

    # 규칙 6: 재무 건전성 10점 이상
    if "financial" in df.columns:
        df = df[pd.to_numeric(df["financial"], errors="coerce").fillna(0)
                >= RULE_SPEC["financial_min"]]

    df = _age_sort(df, age)
    df["path"] = "rule_only"
    return df.head(9).copy()


def _age_sort(df: pd.DataFrame, age: int) -> pd.DataFrame:
    if "overall_score" not in df.columns:
        return df
    _o = pd.to_numeric(df["overall_score"], errors="coerce").fillna(0)
    if age < 35 and "growth" in df.columns:
        _g = pd.to_numeric(df["growth"], errors="coerce").fillna(0)
        df = df.assign(_rank=_o + 0.5 * _g)
    elif age >= 55 and "stability" in df.columns:
        _s = pd.to_numeric(df["stability"], errors="coerce").fillna(0)
        df = df.assign(_rank=_o + 0.5 * _s)
    else:
        df = df.assign(_rank=_o)
    return df.sort_values("_rank", ascending=False).drop(columns=["_rank"], errors="ignore")


def compare(ml_df: pd.DataFrame, rule_df: pd.DataFrame) -> dict:
    ml_codes   = set(ml_df["stock_code"])
    rule_codes = set(rule_df["stock_code"])
    overlap    = ml_codes & rule_codes
    ml_only    = ml_codes - rule_codes
    rule_only  = rule_codes - ml_codes

    return {
        "n_ml":         len(ml_codes),
        "n_rule":       len(rule_codes),
        "n_overlap":    len(overlap),
        "overlap_pct":  round(len(overlap) / max(len(ml_codes), 1) * 100, 1),
        "overlap":      sorted(overlap),
        "ml_only":      sorted(ml_only),    # ML 경로에만 있는 종목 (룰에서 제외됨)
        "rule_only":    sorted(rule_only),  # 룰 경로에만 있는 종목 (ML에서 차단됨)
    }


def stock_detail(df_ml: pd.DataFrame, df_rule: pd.DataFrame,
                 all_df: pd.DataFrame, survival: dict) -> list[dict]:
    """모든 관련 종목의 상세 비교 행."""
    codes = set(df_ml["stock_code"]) | set(df_rule["stock_code"])
    rows = []
    for code in sorted(codes):
        r = all_df[all_df["stock_code"] == code]
        if r.empty:
            continue
        r = r.iloc[0]
        hz = survival.get(str(code), {}).get("hazard_pct", None)
        rows.append({
            "stock_code":    code,
            "name":          r.get("name", ""),
            "overall_score": r.get("overall_score", ""),
            "grade":         r.get("grade", ""),
            "ml_status":     r.get("ml_status", ""),
            "dps_cuts_3y":   r.get("dps_cuts_3y", ""),
            "avg_payout_pct":r.get("avg_payout_pct", ""),
            "stability":     r.get("stability", ""),
            "financial":     r.get("financial", ""),
            "yield":         r.get("yield", ""),
            "hazard_pct":    round(hz, 3) if hz is not None else None,
            "in_ml_path":    code in set(df_ml["stock_code"]),
            "in_rule_path":  code in set(df_rule["stock_code"]),
        })
    return rows


def print_report(risk: str, age: int, comp: dict, details: list[dict],
                 gate: float) -> None:
    print("\n" + "=" * 65)
    print(f"ML 의존성 감사 결과  |  risk={risk}  age={age}")
    print("=" * 65)

    print(f"\n[재무 룰 기준] (변경 금지)")
    for k, v in RULE_SPEC.items():
        print(f"  {k}: {v}")
    print(f"  Survival Hard Gate 임계값 (현재 경로): {gate}")

    print(f"\n[결과 요약]")
    print(f"  현재 ML 경로 종목 수   : {comp['n_ml']}")
    print(f"  재무 룰 경로 종목 수   : {comp['n_rule']}")
    print(f"  Overlap (교집합)       : {comp['n_overlap']}개 ({comp['overlap_pct']}%)")

    if comp["ml_only"]:
        print(f"\n[ML 경로에만 있는 종목] — 재무 룰에서 제외됨")
        for code in comp["ml_only"]:
            d = next((x for x in details if x["stock_code"] == code), {})
            payout_tag = "⚠️데이터없음" if d.get('avg_payout_pct') is None else d.get('avg_payout_pct','')
        print(f"  {code} {d.get('name',''):12s} | score={d.get('overall_score','')} "
                  f"| ml={d.get('ml_status','')} | hazard={d.get('hazard_pct','')} "
                  f"| cuts={d.get('dps_cuts_3y','')} | payout={payout_tag}")

    if comp["rule_only"]:
        print(f"\n[재무 룰 경로에만 있는 종목] — ML에서 차단됨")
        for code in comp["rule_only"]:
            d = next((x for x in details if x["stock_code"] == code), {})
            payout_tag = "⚠️데이터없음" if d.get('avg_payout_pct') is None else d.get('avg_payout_pct','')
            print(f"  {code} {d.get('name',''):12s} | score={d.get('overall_score','')} "
                  f"| ml={d.get('ml_status','')} | hazard={d.get('hazard_pct','')} "
                  f"| cuts={d.get('dps_cuts_3y','')} | payout={payout_tag}")

    print(f"\n[전체 종목 상세]")
    hdr = f"{'code':>8} {'name':12} {'score':>6} {'ml_st':>10} {'hazard':>8} {'cuts':>5} {'payout':>7} | ML룰 ONLY"
    print(hdr)
    print("-" * len(hdr))
    for d in sorted(details, key=lambda x: -float(x.get("overall_score") or 0)):
        tag = ""
        if d["in_ml_path"] and not d["in_rule_path"]:
            tag = "ML전용"
        elif d["in_rule_path"] and not d["in_ml_path"]:
            tag = "RULE전용"
        elif d["in_ml_path"] and d["in_rule_path"]:
            tag = "공통"
        print(f"  {d['stock_code']:>8} {str(d.get('name',''))[:12]:12} "
              f"{str(d.get('overall_score','')[:4] if isinstance(d.get('overall_score'), str) else round(float(d.get('overall_score') or 0),1)):>6} "
              f"{str(d.get('ml_status','')):>10} "
              f"{str(d.get('hazard_pct','') if d.get('hazard_pct') is not None else 'N/A'):>8} "
              f"{str(d.get('dps_cuts_3y','')):>5} "
              f"{str(d.get('avg_payout_pct','') if d.get('avg_payout_pct') != '' else 'N/A'):>7} | {tag}")

    print(f"\n[해석 주의사항]")
    print("  - Overlap이 높다고 재무 룰이 더 정확한 것이 아님")
    print("  - Overlap이 낮다고 ML이 우수한 것이 아님")
    print("  - 이 실험은 ML 의존성 측정이 목적")
    print("  - ml_status(XGBoost)와 hazard_pct(TabPFN)는 별개 소스")


def save_report(risk: str, age: int, comp: dict, details: list[dict],
                gate: float) -> str:
    os.makedirs(RESULT_DIR, exist_ok=True)
    path = os.path.join(RESULT_DIR, f"ml_audit_{risk}_age{age}.json")
    report = {
        "experiment": "ml_dependency_audit",
        "risk": risk,
        "age": age,
        "survival_gate_threshold": gate,
        "rule_spec": RULE_SPEC,
        "note": (
            "ML 의존성 감사. 파이프라인 미변경. "
            "ml_status(XGBoost)와 hazard_pct(TabPFN)는 독립 소스."
        ),
        "summary": comp,
        "details": details,
    }
    def _default(o):
        import numpy as np
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return None if np.isnan(o) else float(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        raise TypeError(f"직렬화 불가: {type(o)}")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=_default)
    return path


def run(risk: str = "moderate", age: int = 40) -> dict:
    df       = load_ranking()
    survival = load_survival()
    gate     = SURVIVAL_GATE.get(risk, 0.50)

    ml_df   = path_current_ml(df, risk, survival, age)
    rule_df = path_rule_only(df, risk, age)
    comp    = compare(ml_df, rule_df)
    details = stock_detail(ml_df, rule_df, df, survival)

    print_report(risk, age, comp, details, gate)
    path = save_report(risk, age, comp, details, gate)
    print(f"\n[저장] {path}")
    return {"comp": comp, "details": details}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--risk", default="moderate",
                        choices=["conservative", "moderate", "aggressive"])
    parser.add_argument("--age", type=int, default=40)
    args = parser.parse_args()
    run(risk=args.risk, age=args.age)

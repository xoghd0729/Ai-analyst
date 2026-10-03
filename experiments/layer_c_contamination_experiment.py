"""
experiments/layer_c_contamination_experiment.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Layer C 간접 오염 측정 실험

SurvivalWeightFilter(Layer B)가 KR 종목 비중을 줄이면,
FIRE 계산(Layer C)에 간접적으로 영향을 미친다.

이 스크립트는 그 영향의 크기를 측정한다.

Experiment A: SurvivalWeightFilter 활성화
  multiplier = 1.0 - 0.4 * hazard_pct

Experiment B: SurvivalWeightFilter 비활성화 (multiplier=1.0)
  모든 KR 종목 비중 보정 없음

실험 조건: 동일
  age=45, risk=moderate, archetype=혼합형
  investable=50000만원, monthly_savings=300만원
  monthly_target=200만원, target_fire_age=55

실행:
  cd ~/ai-analyst
  python experiments/layer_c_contamination_experiment.py
"""

import os
import sys
import json
import copy
import math
import logging
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── 실험 파라미터 (고정) ─────────────────────────────────────
PARAMS = dict(
    age            = 45,
    risk           = "moderate",
    archetype      = "혼합형",
    investable     = 50_000,   # 만원 (5억)
    monthly_savings= 300,      # 만원
    monthly_target = 200,      # 목표 월배당 만원
    annual_income  = 8_000,    # 만원
    target_fire_age= 55,
)

# ── 데이터 경로 ──────────────────────────────────────────────
RANKING_CSV  = os.path.join(BASE, "data",    "ranking.csv")
SURVIVAL_JSON= os.path.join(BASE, "results", "survival_pd_v4.json")

# ── 재무 룰 (RULE_SPEC 고정, 변경 금지) ─────────────────────
RULE_SPEC = {
    "trap_level_exclude": ["DANGER"],
    "overall_score_min": 50.0,
    "dps_cuts_3y_max": 0,
    "avg_payout_pct_max": 80.0,   # NaN = pass (결측 ≠ 위험)
    "stability_min": 20.0,
    "financial_min": 10.0,
}

# ── Hard Gate 임계값 (survival_pd_v4.json 기준) ──────────────
SURVIVAL_GATE = {
    "conservative": 0.35,
    "moderate":     0.50,
    "aggressive":   0.65,
}


# ════════════════════════════════════════════════════════════
# 1. KR 종목 선별 (pick_kr_stocks 동치 구현 — FastAPI 없이)
# ════════════════════════════════════════════════════════════
def pick_kr_stocks(risk: str, n: int, age: int,
                   stock_risk: dict) -> list[dict]:
    """
    ranking.csv + survival Hard Gate로 KR 종목 선별.
    api/routers/portfolio.py:pick_kr_stocks 와 동일한 로직.
    단, FastAPI 의존성 없이 독립 실행 가능.
    """
    df = pd.read_csv(RANKING_CSV, dtype={"stock_code": str})
    df["stock_code"] = df["stock_code"].astype(str).str.zfill(6)

    # 방어 필터
    df = df[df["stock_code"].str.match(r"^\d{6}$")]
    df = df[df["trap_level"] != "DANGER"]
    df = df[pd.to_numeric(df["overall_score"], errors="coerce").fillna(0) >= 50]

    # ── 재무 룰 필터 (RULE_SPEC) ──────────────────────────────
    df = df[df["trap_level"].apply(
        lambda x: x not in RULE_SPEC["trap_level_exclude"]
    )]
    df = df[pd.to_numeric(df["overall_score"], errors="coerce").fillna(0)
            >= RULE_SPEC["overall_score_min"]]
    df = df[pd.to_numeric(df["dps_cuts_3y"], errors="coerce").fillna(0)
            <= RULE_SPEC["dps_cuts_3y_max"]]

    payout_num = pd.to_numeric(df["avg_payout_pct"], errors="coerce")
    df = df[payout_num.isna() | (payout_num <= RULE_SPEC["avg_payout_pct_max"])]

    stability_num = pd.to_numeric(df["stability"], errors="coerce")
    df = df[stability_num.isna() | (stability_num >= RULE_SPEC["stability_min"])]

    financial_num = pd.to_numeric(df["financial"], errors="coerce")
    df = df[financial_num.isna() | (financial_num >= RULE_SPEC["financial_min"])]

    # ── Survival Hard Gate ─────────────────────────────────
    gate_thr = SURVIVAL_GATE.get(risk, 0.50)
    def get_hz(code):
        return stock_risk.get(str(code), {}).get("hazard_pct", 0.5)
    df["_hazard"] = df["stock_code"].apply(get_hz)
    df = df[df["_hazard"] <= gate_thr]
    df = df.drop(columns=["_hazard"])

    # ── 성향별 필터 ────────────────────────────────────────
    if risk == "conservative":
        df = df[df["grade"].str.contains("우량", na=False)]
        df = df[df["ml_status"] == "INTACT"]
    elif risk == "aggressive":
        df = df.sort_values("yield", ascending=False)

    # ── 나이 기반 정렬 틸트 ────────────────────────────────
    o = pd.to_numeric(df["overall_score"], errors="coerce").fillna(0)
    g = pd.to_numeric(df["growth"], errors="coerce").fillna(0)
    s = pd.to_numeric(df["stability"], errors="coerce").fillna(0)
    if age < 35:
        df = df.assign(_rank=o + 0.5 * g)
    elif age >= 55:
        df = df.assign(_rank=o + 0.5 * s)
    else:
        df = df.assign(_rank=o)
    df = df.sort_values("_rank", ascending=False)

    stocks = []
    for _, row in df.head(n).iterrows():
        dy    = float(row.get("yield", 0) or 0)
        grade = str(row.get("grade", ""))
        ml_st = str(row.get("ml_status", "INTACT"))
        cuts  = int(row.get("dps_cuts_3y", 0) or 0)

        if ml_st == "INTACT" and cuts == 0:
            cap_gain = 3.5
        elif "우량" in grade:
            cap_gain = 3.0
        else:
            cap_gain = 2.0

        stocks.append({
            "ticker":            str(row["stock_code"]),
            "name":              str(row["name"]),
            "asset_class":       "kr_stock",
            "expected_yield":    dy,
            "capital_gain_rate": cap_gain,
            "overall_score":     float(row.get("overall_score", 50) or 50),
            "grade":             grade,
            "ml_status":         ml_st,
            "dps_cuts_3y":       cuts,
            "trap_level":        str(row.get("trap_level", "SAFE")),
            "avg_payout_pct":    float(row["avg_payout_pct"]) if pd.notna(row.get("avg_payout_pct")) else None,
            "stability_score":   float(row.get("stability", 0) or 0),
            "financial_score":   float(row.get("financial", 0) or 0),
        })
    return stocks


# ════════════════════════════════════════════════════════════
# 2. 전체 포트폴리오 비중 배분 (KR + US + ETF)
# ════════════════════════════════════════════════════════════
def build_full_portfolio(
    kr_stocks: list[dict],
    axis_w: dict,
    investable: int,
) -> list[dict]:
    """
    KR + US(상위3) + ETF(상위 us_div/reit/defensive) 전체 포트폴리오 구성.
    assign_weights와 동일한 비중 배분 로직, FastAPI 없이 독립 실행.
    """
    from utils.universe import ETF_UNIVERSE

    # --- KR 주식 ---
    recs = []
    if kr_stocks:
        scores  = [s["overall_score"] for s in kr_stocks]
        s_total = sum(scores) or 1
        kr_axis = axis_w["kr_stock"]
        for s, sc in zip(kr_stocks, scores):
            w = kr_axis * sc / s_total * 100
            recs.append({**s, "weight_pct": round(w, 4),
                         "invest_amount": round(investable * w / 100)})

    # --- US 개별주 (유니버스 상위3) ---
    us_universe = [e for e in ETF_UNIVERSE if e.get("asset_class") == "us_stock"][:3]
    if us_universe:
        us_axis = axis_w.get("us_stock", 0.15)
        y_total = sum(e["expected_yield"] for e in us_universe) or 1
        for e in us_universe:
            w = us_axis * e["expected_yield"] / y_total * 100
            recs.append({**e, "weight_pct": round(w, 4),
                         "invest_amount": round(investable * w / 100)})

    # --- US div ETF (상위2) ---
    etf_div = [e for e in ETF_UNIVERSE
               if e.get("asset_class") in ("us_div_etf", "kr_etf")][:2]
    if etf_div:
        etf_axis = axis_w.get("us_etf", 0.23)
        y_total  = sum(e["expected_yield"] for e in etf_div) or 1
        for e in etf_div:
            w = etf_axis * e["expected_yield"] / y_total * 100
            recs.append({**e, "weight_pct": round(w, 4),
                         "invest_amount": round(investable * w / 100)})

    # --- REIT (상위1) ---
    reit = [e for e in ETF_UNIVERSE
            if e.get("asset_class") in ("us_reit", "kr_reit")][:1]
    if reit:
        reit_axis = axis_w.get("reit", 0.17)
        recs.append({**reit[0],
                     "weight_pct": round(reit_axis * 100, 4),
                     "invest_amount": round(investable * reit_axis)})

    # --- Defensive (상위1) ---
    defv = [e for e in ETF_UNIVERSE if e.get("asset_class") == "defensive"][:1]
    if defv:
        def_axis = axis_w.get("defensive", 0.13)
        recs.append({**defv[0],
                     "weight_pct": round(def_axis * 100, 4),
                     "invest_amount": round(investable * def_axis)})

    # 전체 정규화
    total = sum(r["weight_pct"] for r in recs) or 100.0
    for r in recs:
        r["weight_pct"] = round(r["weight_pct"] / total * 100, 2)
        r["invest_amount"] = round(investable * r["weight_pct"] / 100)

    return recs


# ════════════════════════════════════════════════════════════
# 3. SurvivalWeightFilter 적용 / 미적용
# ════════════════════════════════════════════════════════════
def apply_survival_weight(recs: list[dict], stock_risk: dict,
                          bypass: bool = False) -> list[dict]:
    """
    bypass=False → SurvivalWeightFilter 정상 적용
    bypass=True  → multiplier=1.0 (Experiment B)
    """
    recs = copy.deepcopy(recs)
    investable = PARAMS["investable"]

    for r in recs:
        ticker = str(r.get("ticker", "") or r.get("stock_code", ""))
        hz = float(stock_risk.get(ticker, {}).get("hazard_pct", 0.3))
        r["hazard_pct"] = hz

        if bypass:
            multiplier = 1.0
        elif r.get("asset_class") == "kr_stock" and ticker in stock_risk:
            multiplier = round(1.0 - 0.4 * hz, 4)
        else:
            multiplier = 1.0

        r["weight_pct"] = round(r.get("weight_pct", 0) * multiplier, 4)
        r["survival_weight_adj"] = multiplier

    # 재정규화
    total = sum(r["weight_pct"] for r in recs) or 100.0
    for r in recs:
        r["weight_pct"] = round(r["weight_pct"] / total * 100, 2)
        r["invest_amount"] = round(investable * r["weight_pct"] / 100)

    return recs


# ════════════════════════════════════════════════════════════
# 4. 지표 계산
# ════════════════════════════════════════════════════════════
def calc_metrics(recs: list[dict], label: str) -> dict:
    """
    7개 비교 지표 계산.
    """
    p = PARAMS
    investable     = p["investable"]
    monthly_savings= p["monthly_savings"]
    monthly_target = p["monthly_target"]
    age            = p["age"]
    target_fire_age= p["target_fire_age"]

    # KR 비중 합산
    kr_weight = sum(r["weight_pct"] for r in recs if r.get("asset_class") == "kr_stock")

    # 가중평균 순배당수익률 (세금 미적용, 단순 가중평균)
    avg_yield_net = sum(
        r.get("expected_yield", 0) * r["weight_pct"] / 100
        for r in recs
    )

    # 현재 예상 월배당 (만원)
    monthly_div = round(investable * avg_yield_net / 100 / 12, 1)

    # 목표 월배당 달성 시점 (적립+재투자 시뮬레이션)
    r_monthly = avg_yield_net / 100 / 12
    if monthly_div >= monthly_target:
        months_to_target = 0
    elif r_monthly <= 0:
        months_to_target = 999
    else:
        capital = float(investable)
        months_to_target = 999
        for m in range(360):
            m_div = capital * r_monthly
            if m_div >= monthly_target:
                months_to_target = m
                break
            capital += float(monthly_savings) + m_div  # 적립 + 재투자

    # FIRE 계산 (fire_engine 직접 호출)
    from utils.fire_engine import calc_fire_engine
    fire_result = calc_fire_engine(
        current_investable=investable,
        monthly_savings=monthly_savings,
        current_age=age,
        target_age=target_fire_age,
        avg_net_yield=avg_yield_net,
        div_growth_rate=5.0,
        cpi_rate=2.5,
        custom_monthly_만원=float(monthly_target),
    )

    fire_tl   = fire_result.get("fire_timeline", [])
    # fire_timeline은 list[dict] — 처음으로 달성된 연도의 age 추출
    fire_age   = "N/A"
    custom_age = "N/A"
    for entry in (fire_tl if isinstance(fire_tl, list) else []):
        achieved = entry.get("achieved", {})
        if fire_age == "N/A" and achieved.get("regular"):
            fire_age = entry["age"]
        if custom_age == "N/A" and achieved.get("custom"):
            custom_age = entry["age"]

    return {
        "label":               label,
        "kr_weight_pct":       round(kr_weight, 2),
        "avg_yield_net_pct":   round(avg_yield_net, 3),
        "monthly_div_만원":    monthly_div,
        "months_to_target":    months_to_target,
        "fire_regular_age":    fire_age,
        "fire_custom_age":     custom_age,
        "n_stocks":            len(recs),
        "recs":                recs,
        "fire_result":         fire_result,
    }


# ════════════════════════════════════════════════════════════
# 5. 포트폴리오 상세 비교
# ════════════════════════════════════════════════════════════
def print_portfolio_detail(recs_a: list[dict], recs_b: list[dict]) -> None:
    print("\n=== KR 종목별 비중 변화 (A: ML 적용 vs B: ML 제거) ===")
    print(f"{'종목코드':8s} {'이름':14s} {'hazard':7s} {'mult_A':7s} | "
          f"{'비중A(%)':8s} {'비중B(%)':8s} {'차이':7s}")
    print("-" * 65)

    b_dict = {r["ticker"]: r for r in recs_b}
    for r in recs_a:
        if r.get("asset_class") != "kr_stock":
            continue
        ticker = r["ticker"]
        b_r    = b_dict.get(ticker, {})
        hz     = r.get("hazard_pct", 0)
        mult   = r.get("survival_weight_adj", 1.0)
        w_a    = r["weight_pct"]
        w_b    = b_r.get("weight_pct", 0)
        diff   = w_a - w_b
        print(f"{ticker:8s} {r['name']:14s} {hz:7.3f} {mult:7.4f} | "
              f"{w_a:8.2f} {w_b:8.2f} {diff:+7.2f}")


# ════════════════════════════════════════════════════════════
# 6. 결과 저장
# ════════════════════════════════════════════════════════════
def _safe(v):
    """JSON 직렬화 안전 변환."""
    import numpy as np
    if isinstance(v, (np.integer,)):   return int(v)
    if isinstance(v, (np.floating,)):  return None if np.isnan(v) else float(v)
    if isinstance(v, (np.bool_,)):     return bool(v)
    if isinstance(v, dict):            return {k2: _safe(v2) for k2, v2 in v.items()}
    if isinstance(v, list):            return [_safe(i) for i in v]
    return v


def save_report(m_a: dict, m_b: dict, params: dict) -> str:
    def _age_diff(va, vb):
        try:
            return int(va) - int(vb)
        except (TypeError, ValueError):
            return "N/A"

    diff = {
        "kr_weight_pct_diff":     round(m_a["kr_weight_pct"]     - m_b["kr_weight_pct"],     2),
        "avg_yield_net_pct_diff": round(m_a["avg_yield_net_pct"] - m_b["avg_yield_net_pct"], 3),
        "monthly_div_diff_만원":  round(m_a["monthly_div_만원"]   - m_b["monthly_div_만원"],  1),
        "months_to_target_diff":  m_a["months_to_target"] - m_b["months_to_target"],
        "fire_regular_age_diff":  _age_diff(m_a["fire_regular_age"], m_b["fire_regular_age"]),
        "fire_custom_age_diff":   _age_diff(m_a["fire_custom_age"],  m_b["fire_custom_age"]),
    }

    report = {
        "experiment":  "Layer C 간접 오염 측정",
        "params":      params,
        "rule_spec":   RULE_SPEC,
        "experiment_a": {k: v for k, v in m_a.items() if k not in ("recs", "fire_result")},
        "experiment_b": {k: v for k, v in m_b.items() if k not in ("recs", "fire_result")},
        "diff":        diff,
        "portfolio_a": m_a["recs"],
        "portfolio_b": m_b["recs"],
        "fire_a":      m_a["fire_result"],
        "fire_b":      m_b["fire_result"],
    }

    out_path = os.path.join(BASE, "results", "layer_c_contamination_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(_safe(report), f, ensure_ascii=False, indent=2)
    return out_path


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("Layer C 간접 오염 측정 실험 시작")
    log.info(f"  조건: {PARAMS}")
    log.info("=" * 60)

    # survival 데이터 로드
    with open(SURVIVAL_JSON, encoding="utf-8") as f:
        sv = json.load(f)
    stock_risk = sv.get("stock_risk", {})
    log.info(f"survival 데이터: {len(stock_risk)}개 종목")

    # axis 비중 (universe)
    from utils.universe import get_axis_weights
    axis_w    = get_axis_weights(PARAMS["age"], PARAMS["risk"])
    kr_axis   = axis_w["kr_stock"]
    log.info(f"axis_w: {axis_w}")

    # KR 종목 선별 (A/B 동일 — Hard Gate는 선별 단계에서 이미 적용됨)
    kr_stocks = pick_kr_stocks(
        PARAMS["risk"], 9, PARAMS["age"], stock_risk
    )
    log.info(f"KR 종목 선별: {len(kr_stocks)}개")
    for s in kr_stocks:
        hz = stock_risk.get(s["ticker"], {}).get("hazard_pct", "N/A")
        log.info(f"  {s['ticker']:8s} {s['name']:14s} yield={s['expected_yield']:.2f}% "
                 f"score={s['overall_score']:.0f} hazard={hz}")

    # 전체 포트폴리오 비중 배분 (SurvivalWeightFilter 이전 상태)
    recs_base = build_full_portfolio(kr_stocks, axis_w, PARAMS["investable"])
    log.info(f"전체 포트폴리오: {len(recs_base)}개 자산 (KR+US+ETF)")
    kr_base_w = sum(r["weight_pct"] for r in recs_base if r.get("asset_class") == "kr_stock")
    log.info(f"  KR 비중(초기): {kr_base_w:.2f}%")

    # ── Experiment A: SurvivalWeightFilter 활성화 ──────────────
    recs_a = apply_survival_weight(recs_base, stock_risk, bypass=False)

    # ── Experiment B: multiplier=1.0 (bypass) ──────────────────
    recs_b = apply_survival_weight(recs_base, stock_risk, bypass=True)

    # ── 지표 계산 ──────────────────────────────────────────────
    m_a = calc_metrics(recs_a, "A: ML 적용 (SurvivalWeightFilter 활성화)")
    m_b = calc_metrics(recs_b, "B: ML 영향 제거 (multiplier=1.0)")

    # ── 포트폴리오 상세 비교 ───────────────────────────────────
    print_portfolio_detail(recs_a, recs_b)

    # ── 비교 테이블 출력 ───────────────────────────────────────
    print()
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│          Layer C 간접 오염 측정 실험 결과 비교표              │")
    print("├──────────────────────┬──────────────┬──────────────┬────────┤")
    print("│ 지표                 │ A: ML 적용   │ B: ML 제거   │  차이  │")
    print("├──────────────────────┼──────────────┼──────────────┼────────┤")

    def row(label, va, vb, fmt="{:.2f}", unit=""):
        try:
            diff = va - vb
            print(f"│ {label:20s} │ {fmt.format(va)+unit:12s} │ "
                  f"{fmt.format(vb)+unit:12s} │ {'+' if diff>=0 else ''}{fmt.format(diff)+unit:6s} │")
        except Exception:
            print(f"│ {label:20s} │ {str(va):12s} │ {str(vb):12s} │ {'N/A':6s} │")

    row("KR 종목 총비중(%)",   m_a["kr_weight_pct"],     m_b["kr_weight_pct"],     "{:.2f}", "%")
    row("avg_yield_net(%)",    m_a["avg_yield_net_pct"], m_b["avg_yield_net_pct"], "{:.3f}", "%")
    row("예상 월배당(만원)",   m_a["monthly_div_만원"],  m_b["monthly_div_만원"],  "{:.1f}", "")
    row("목표달성(개월)",      m_a["months_to_target"],  m_b["months_to_target"],  "{:.0f}", "")
    print(f"│ {'FIRE 달성 나이':20s} │ {str(m_a['fire_regular_age'])+'세':12s} │ "
          f"{str(m_b['fire_regular_age'])+'세':12s} │ {'N/A':6s} │")
    print(f"│ {'목표 FIRE 나이':20s} │ {str(m_a['fire_custom_age'])+'세':12s} │ "
          f"{str(m_b['fire_custom_age'])+'세':12s} │ {'N/A':6s} │")
    print(f"│ {'포트폴리오 종목수':20s} │ {m_a['n_stocks']:12d} │ "
          f"{m_b['n_stocks']:12d} │ {m_a['n_stocks']-m_b['n_stocks']:+6d} │")
    print("└──────────────────────┴──────────────┴──────────────┴────────┘")

    # ── 해석 노트 ─────────────────────────────────────────────
    diff_yield = m_a["avg_yield_net_pct"] - m_b["avg_yield_net_pct"]
    diff_months= m_a["months_to_target"]  - m_b["months_to_target"]
    diff_kr    = m_a["kr_weight_pct"]     - m_b["kr_weight_pct"]

    print()
    print("[ 해석 노트 ]")
    print(f"  - KR 종목 비중 변화: {diff_kr:+.2f}%p")
    print(f"    → SurvivalWeightFilter가 KR 비중을 {abs(diff_kr):.2f}%p {'감소' if diff_kr<0 else '증가'}시킴")
    print(f"  - 평균 순수익률 변화: {diff_yield:+.3f}%p")
    print(f"    → 이는 Layer C(FIRE 계산)에 간접 전달되는 오염 크기")
    if abs(diff_yield) < 0.1:
        print(f"    → 영향 크기: 소(< 0.1%p) — Layer C 오염 수준 미미")
    elif abs(diff_yield) < 0.3:
        print(f"    → 영향 크기: 중(0.1~0.3%p) — Layer C에 일정 수준 영향")
    else:
        print(f"    → 영향 크기: 대(>= 0.3%p) — Layer C 오염 유의미")
    print()
    print("  주의: 이 차이가 'ML이 틀렸다'는 증거가 아님.")
    print("  ML 신호가 FIRE 결과를 얼마나 바꾸는지를 측정한 것이며,")
    print("  그 변화의 방향성이 맞는지는 별도 검증 필요.")

    # ── 저장 ──────────────────────────────────────────────────
    out_path = save_report(m_a, m_b, PARAMS)
    log.info(f"\n결과 저장: {out_path}")
    print(f"\n결과 파일: {out_path}")


if __name__ == "__main__":
    main()

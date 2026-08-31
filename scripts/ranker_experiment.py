"""
scripts/ranker_experiment.py  v2
================================
Ranker 7가지 방식 비교 실험 (A/B/C/D + E-25/E-40/E-60)

시나리오: 25세 / 초기자산 360만원 / 월 적립 30만원 / 목표 월배당 50만원

방식 정의:
  A        기존 target-yield fit (기준선)
  B        horizon-yield fit (미래 배당 목표 맞추기)
  C        Total Return + 위험 + 성장 (목표수익률 의존성 완화)
  D        horizon + A/B 동적 가중치 (투자기간 반영)
  E-25     absolute yield (saturation) + risk + growth + age  [장기: 25년]
  E-40     동일 구조, 중기 가중치  [중기: 15년]
  E-60     동일 구조, 단기 가중치  [단기: 5년]

평가 지표 (8개):
  1. 평균 배당수익률
  2. 평균 DPS 성장률
  3. 평균 리스크 점수
  4. 고위험 비중 (risk > 40)
  5. ETF / 개별주 구성비
  6. 10년 후 예상 월배당
  7. 20년 후 예상 월배당
  8. 목표 달성 FIRE 나이
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd, json, math

from utils.risk_engine import score_asset, _GATE_BY_RISK
from utils.fire_engine import calc_fire_engine

# ─── 시나리오 설정 ──────────────────────────────────────────────
AGE             = 25
RESERVE         = 360.0
MONTHLY_INVEST  = 30.0
MONTHLY_TARGET  = 50.0
TARGET_FIRE_AGE = 50
RISK_TOLERANCE  = "moderate"
HORIZON         = TARGET_FIRE_AGE - AGE   # 25년
AVG_NET_YIELD   = 3.5
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 데이터 로딩 ────────────────────────────────────────────────
def load_kr_candidates(n=20):
    df = pd.read_csv(os.path.join(BASE, "data", "ranking.csv"))
    df = df.rename(columns={"stock_code": "ticker", "yield": "expected_yield",
                             "latest_yoy_pct": "dps_yoy_pct"})
    df["asset_class"] = "kr_stock"
    if "ml_status" not in df.columns: df["ml_status"] = "INTACT"
    str_cols = {"sector": "기타", "sector_group": "기타"}
    for c in ["beta", "consecutive_years", "capital_gain_rate"]:
        if c not in df.columns: df[c] = 0.0
    for c, default in str_cols.items():
        if c not in df.columns: df[c] = default
    df["expected_yield"] = pd.to_numeric(df["expected_yield"], errors="coerce").fillna(0)
    df["dps_yoy_pct"]   = pd.to_numeric(df.get("dps_yoy_pct", 0), errors="coerce").fillna(0)
    return df[df["expected_yield"] > 0].dropna(subset=["ticker"]).head(n).to_dict("records")

def load_us_candidates(n=15):
    df = pd.read_csv(os.path.join(BASE, "data", "us_stock_scores.csv"))
    df = df.rename(columns={"yield_pct": "expected_yield"})
    df["asset_class"] = "us_stock"
    if "ml_status" not in df.columns: df["ml_status"] = "INTACT"
    for c in ["beta", "consecutive_years", "dps_yoy_pct", "capital_gain_rate"]:
        if c not in df.columns: df[c] = 0.0
    if "sector_group" not in df.columns: df["sector_group"] = "기타"
    df["expected_yield"] = pd.to_numeric(df["expected_yield"], errors="coerce").fillna(0)
    df["dps_yoy_pct"]   = pd.to_numeric(df["dps_yoy_pct"], errors="coerce").fillna(0)
    return df[df["expected_yield"] > 0].dropna(subset=["ticker"]).head(n).to_dict("records")

def load_etf_candidates(n=8):
    """ETF 후보. 실제 DPS 성장률 반영 (팩트시트 5년 이력 기반).
    성장형(SCHD/DGRO): 8~10% / 혼합형(VYM): 5~6% / 옵션인컴(JEPI/JEPQ/SPYI): 2~4%
    이 차이로 E25_v2에서 growth_fit이 자연스럽게 분리됨.
    """
    _DPS_MAP = {
        "SCHD": 10.0, "DGRO":  8.0, "DGRW":  8.0, "NOBL": 7.0, "VIG":  7.0,
        "VYM":   6.0, "HDV":   5.0, "SPYD":  4.0,
        "VNQ":   3.0, "XLRE":  4.0, "O":     3.0, "AMT":  5.0,
        "JEPI":  4.0, "JEPQ":  2.0, "SPYI":  2.0,
        "QYLD":  0.0, "RYLD":  0.0,
    }
    from utils.universe import ETF_UNIVERSE
    etfs = []
    for e in ETF_UNIVERSE:
        ac = str(e.get("asset_class", ""))
        if "etf" in ac.lower() or "reit" in ac.lower():
            entry = dict(e)
            ticker = str(entry.get("ticker", ""))
            entry.setdefault("ml_status", "INTACT")
            entry["dps_yoy_pct"] = _DPS_MAP.get(ticker, 3.0)
            entry.setdefault("sector", "ETF")
            entry.setdefault("beta", 0.8)
            entry.setdefault("capital_gain_rate", 2.0)
            if float(entry.get("expected_yield", 0)) > 0:
                etfs.append(entry)
    return etfs[:n]

# ─── Fit Score 함수들 ────────────────────────────────────────────
def target_yield_gap_fit(expected_yield, target_yield):
    """A/B/D: target_yield와 gap 기반 fit (기존 방식)"""
    diff = abs(expected_yield - target_yield)
    if diff <= 1.0: return 100.0
    if diff >= 5.0: return 0.0
    return round(100.0 * (1 - (diff - 1.0) / 4.0), 1)

def horizon_yield_fit(expected_yield, dps_growth, horizon, target_yield):
    """B: horizon 후 예상 yield가 target에 근접하는 정도"""
    g = max(0.0, float(dps_growth or 0)) / 100.0
    future_yield = expected_yield * ((1 + g) ** horizon)
    return target_yield_gap_fit(future_yield, target_yield)

def total_return_fit(expected_yield, dps_growth, capital_gain, target_yield):
    """C: Total Return 기반 (배당+주가) 비교"""
    g = max(0.0, float(dps_growth or 0))
    cap = max(0.0, float(capital_gain or 0))
    total_return = expected_yield + cap + g * 0.3
    return target_yield_gap_fit(total_return, target_yield + 3.0)

def abs_yield_fit(expected_yield):
    """E v1 (구): 3%에서 즉시 포화 — 비교 기준선으로만 유지."""
    y = max(0.0, float(expected_yield))
    if y <= 3.0:
        score = y * 35.0
    elif y <= 6.0:
        score = 105.0 + (y - 3.0) * 10.0
    else:
        score = 135.0 + (y - 6.0) * 3.0
    return round(min(95.0, score), 1)

# Breakpoints: [(yield_pct, score), ...]
_ABS_YIELD_BREAKPOINTS = [(0, 0), (2, 40), (4, 70), (6, 85), (8, 92), (10, 95)]

def abs_yield_fit_v2(expected_yield):
    """E v2: 완만한 piecewise-linear saturation.
    0→0, 2%→40, 4%→70, 6%→85, 8%→92, 10%→95, 10%+→95(cap)
    이유: 고배당(10%+) ETF와 4~6%대 성장주를 차별화하되,
          12%짜리 옵션 ETF가 9%짜리보다 폭발적으로 높아지지 않도록 cap.
    """
    y = max(0.0, float(expected_yield))
    bps = _ABS_YIELD_BREAKPOINTS
    if y >= bps[-1][0]:
        return bps[-1][1]
    for i in range(len(bps) - 1):
        y0, s0 = bps[i]
        y1, s1 = bps[i + 1]
        if y0 <= y < y1:
            t = (y - y0) / (y1 - y0)
            return round(s0 + t * (s1 - s0), 1)
    return 0.0

def risk_fit(composite_risk_score):
    return round(max(0.0, 100.0 - composite_risk_score), 1)

def age_fit_fn(candidate, age):
    asset_class = str(candidate.get("asset_class", ""))
    beta = float(candidate.get("beta", 1.0) or 1.0)
    is_etf = "etf" in asset_class.lower()
    if age >= 55:
        score = 70.0
        if is_etf:      score += 20.0
        if beta <= 0.8: score += 10.0
        if beta >= 1.3: score -= 20.0
    elif age >= 35:
        score = 75.0
        if is_etf:      score += 5.0
        if beta <= 1.0: score += 5.0
    else:
        score = 70.0
        score += min(10.0, candidate.get("expected_yield", 3.0))
        if is_etf: score += 5.0
    return round(min(100.0, score), 1)

def growth_fit_fn(candidate, age):
    dps_growth  = float(candidate.get("dps_yoy_pct", 0) or 0)
    consecutive = float(candidate.get("consecutive_years", 0) or
                        candidate.get("div_years", 0) or 0)
    if age < 35:
        return round(min(100.0, 50.0 + dps_growth * 5.0), 1)
    elif age >= 55:
        return round(min(100.0, 50.0 + consecutive * 0.8), 1)
    else:
        return round(min(100.0, 50.0 + dps_growth * 2.5 + consecutive * 0.4), 1)

# ─── target_yield 계산 ──────────────────────────────────────────
def calc_target_yield(monthly_target, investable, avg_growth_years=5):
    if investable <= 0: return 5.0
    raw = monthly_target * 12 / investable * 100
    discount = (1.05 ** avg_growth_years) ** 0.3
    adjusted = raw / discount
    return round(max(1.0, min(20.0, adjusted)), 2)

TARGET_YIELD = calc_target_yield(MONTHLY_TARGET, RESERVE)

# ─── 7가지 방식 정의 ────────────────────────────────────────────
METHODS = {
    "A_기존yield": {
        "desc": "target-yield gap fit: yield×0.40 + risk×0.35 + age×0.15 + growth×0.10",
        "score_fn": lambda c, rs: (
            target_yield_gap_fit(float(c.get("expected_yield", 0)), TARGET_YIELD) * 0.40 +
            risk_fit(rs["composite_risk_score"]) * 0.35 +
            age_fit_fn(c, AGE) * 0.15 +
            growth_fit_fn(c, AGE) * 0.10
        ),
    },
    "B_horizon": {
        "desc": "horizon yield fit: h_yield×0.25 + risk×0.35 + age×0.20 + growth×0.30",
        "score_fn": lambda c, rs: (
            horizon_yield_fit(float(c.get("expected_yield", 0)),
                              c.get("dps_yoy_pct", 0), HORIZON, TARGET_YIELD) * 0.25 +
            risk_fit(rs["composite_risk_score"]) * 0.35 +
            age_fit_fn(c, AGE) * 0.20 +
            growth_fit_fn(c, AGE) * 0.30
        ),
    },
    "C_TotalReturn": {
        "desc": "TR fit: TR×0.25 + risk×0.35 + age×0.20 + growth×0.20",
        "score_fn": lambda c, rs: (
            total_return_fit(float(c.get("expected_yield", 0)),
                             c.get("dps_yoy_pct", 0),
                             c.get("capital_gain_rate", 0), TARGET_YIELD) * 0.25 +
            risk_fit(rs["composite_risk_score"]) * 0.35 +
            age_fit_fn(c, AGE) * 0.20 +
            growth_fit_fn(c, AGE) * 0.20
        ),
    },
    "D_동적": {
        "desc": "A↔B 선형 보간 (horizon=25 → 100% B)",
        "score_fn": lambda c, rs: (
            horizon_yield_fit(float(c.get("expected_yield", 0)),
                              c.get("dps_yoy_pct", 0), HORIZON, TARGET_YIELD) * 0.25 +
            risk_fit(rs["composite_risk_score"]) * 0.35 +
            age_fit_fn(c, AGE) * 0.20 +
            growth_fit_fn(c, AGE) * 0.30
        ),
    },
    # ── E 방식: target_yield 완전 독립 ──────────────────────────
    "E25_장기": {
        "desc": "abs_yield(sat)×0.15 + risk×0.40 + growth×0.30 + age×0.15  [장기 25년 가중치]",
        "score_fn": lambda c, rs: (
            abs_yield_fit(float(c.get("expected_yield", 0))) * 0.15 +
            risk_fit(rs["composite_risk_score"]) * 0.40 +
            growth_fit_fn(c, AGE) * 0.30 +
            age_fit_fn(c, AGE) * 0.15
        ),
    },
    "E40_중기": {
        "desc": "abs_yield(sat)×0.20 + risk×0.40 + growth×0.20 + age×0.20  [중기 15년 가중치]",
        "score_fn": lambda c, rs: (
            abs_yield_fit(float(c.get("expected_yield", 0))) * 0.20 +
            risk_fit(rs["composite_risk_score"]) * 0.40 +
            growth_fit_fn(c, AGE) * 0.20 +
            age_fit_fn(c, AGE) * 0.20
        ),
    },
    "E60_단기": {
        "desc": "abs_yield(sat)×0.30 + risk×0.40 + growth×0.10 + age×0.20  [단기 5년 가중치]",
        "score_fn": lambda c, rs: (
            abs_yield_fit(float(c.get("expected_yield", 0))) * 0.30 +
            risk_fit(rs["composite_risk_score"]) * 0.40 +
            growth_fit_fn(c, AGE) * 0.10 +
            age_fit_fn(c, AGE) * 0.20
        ),
    },
}

# ─── 랭킹 실행 ──────────────────────────────────────────────────
def run_ranking(candidates, method_fn, n_pick=6):
    block_thresh = _GATE_BY_RISK.get(RISK_TOLERANCE, 65.0)
    scored = []
    for c in candidates:
        c = dict(c)
        rs = score_asset(
            ticker         = str(c.get("ticker") or ""),
            asset_class    = str(c.get("asset_class", "kr_stock")),
            ml_status      = str(c.get("ml_status", "INTACT")),
            survival_hazard= c.get("survival_risk_score"),
            macro          = None,
            risk_tolerance = RISK_TOLERANCE,
        )
        c.update(rs)
        if c["risk_gate"] == "BLOCK":
            continue
        c["fit_score"] = round(method_fn(c, rs), 2)
        scored.append(c)
    scored.sort(key=lambda x: -x["fit_score"])

    selected, sector_cnt = [], {}
    for s in scored:
        sector = str(s.get("sector", "기타"))
        if sector_cnt.get(sector, 0) >= 2:
            continue
        selected.append(s)
        sector_cnt[sector] = sector_cnt.get(sector, 0) + 1
        if len(selected) >= n_pick:
            break
    return selected

# ─── 8가지 평가 지표 ──────────────────────────────────────────────
def evaluate(picks, label=""):
    if not picks:
        return {k: "—" for k in [
            "avg_yield", "avg_dps_growth", "avg_risk", "high_risk_pct",
            "etf_ratio", "monthly_10y", "monthly_20y", "fire_age",
        ]}
    n = len(picks)
    avg_yield      = sum(float(p.get("expected_yield", 0)) for p in picks) / n
    avg_dps        = sum(float(p.get("dps_yoy_pct", 0) or 0) for p in picks) / n
    avg_risk       = sum(float(p.get("composite_risk_score", 50)) for p in picks) / n
    high_risk_cnt  = sum(1 for p in picks if float(p.get("composite_risk_score", 0)) > 40)
    etf_cnt        = sum(1 for p in picks if "etf" in str(p.get("asset_class", "")).lower()
                                             or "reit" in str(p.get("asset_class", "")).lower())
    etf_ratio      = round(etf_cnt / n * 100)

    # N년 후 예상 월배당 계산
    # 포트폴리오 복리: 자산 × (1 + avg_yield + avg_dps×0.5)^N + 월적립 누적
    def future_monthly(years):
        total_ret = avg_yield / 100 + (avg_dps / 100) * 0.5
        pf = RESERVE
        for _ in range(years):
            pf = pf * (1 + total_ret) + MONTHLY_INVEST * 12
        return round(pf * avg_yield / 100 / 12, 1)

    m10 = future_monthly(10)
    m20 = future_monthly(20)

    # FIRE 달성 나이 (fire_engine)
    fire = calc_fire_engine(
        current_investable  = RESERVE,
        monthly_savings     = MONTHLY_INVEST,
        current_age         = AGE,
        target_age          = TARGET_FIRE_AGE,
        avg_net_yield       = avg_yield * 0.85,
        div_growth_rate     = avg_dps,
        cpi_rate            = 2.5,
        custom_monthly_만원 = MONTHLY_TARGET,
    )
    custom = fire.get("targets", {}).get("custom") or {}
    fire_age = custom.get("projected_fire_age", "미달성")

    return {
        "avg_yield":     round(avg_yield, 2),
        "avg_dps_growth":round(avg_dps, 2),
        "avg_risk":      round(avg_risk, 1),
        "high_risk_pct": f"{high_risk_cnt}/{n}",
        "etf_ratio":     f"{etf_ratio}%({etf_cnt}/{n})",
        "monthly_10y":   f"{m10}만원",
        "monthly_20y":   f"{m20}만원",
        "fire_age":      str(fire_age),
    }

# ─── abs_yield_fit 포화 곡선 미리 확인 ──────────────────────────
print("=== abs_yield_fit saturation 곡선 확인 ===")
for y in [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12]:
    print(f"  yield={y:2d}% → abs_yield_fit={abs_yield_fit(y):.1f}")
print()

# ─── 데이터 로딩 ────────────────────────────────────────────────
print("=" * 75)
print(f"  Ranker 7가지 방식 비교 실험 (A/B/C/D + E-25/E-40/E-60)")
print(f"  시나리오: {AGE}세 / 초기자산 {RESERVE:.0f}만원 / 월적립 {MONTHLY_INVEST:.0f}만원 / 목표 {MONTHLY_TARGET:.0f}만원")
print(f"  target_yield={TARGET_YIELD}% / horizon={HORIZON}년")
print("=" * 75)

try:
    kr  = load_kr_candidates(20)
    print(f"  KR {len(kr)}개")
except Exception as e:
    print(f"  KR 로드 실패: {e}")
    kr = []

try:
    us  = load_us_candidates(15)
    print(f"  US {len(us)}개")
except Exception as e:
    print(f"  US 로드 실패: {e}")
    us = []

try:
    etf = load_etf_candidates(8)
    print(f"  ETF {len(etf)}개")
except Exception as e:
    print(f"  ETF 로드 실패: {e}")
    etf = []

all_candidates = kr + us + etf
print(f"  총 {len(all_candidates)}개\n")

# ─── 각 방식 실행 ────────────────────────────────────────────────
summary_rows = []

for method_name, cfg in METHODS.items():
    print(f"{'─'*70}")
    print(f"  [{method_name}]  {cfg['desc']}")
    picks = run_ranking(all_candidates, cfg["score_fn"], n_pick=6)

    print(f"  선택 종목:")
    for p in picks:
        ac  = str(p.get("asset_class",""))[:7]
        abs_y = abs_yield_fit(float(p.get("expected_yield",0)))
        print(f"    [{str(p['ticker']):7s}] {p.get('name','')[:12]:12s}  "
              f"yield={p.get('expected_yield',0):.1f}%  "
              f"dps={p.get('dps_yoy_pct',0) or 0:.1f}%/yr  "
              f"risk={p.get('composite_risk_score',50):.0f}  "
              f"absY={abs_y:.0f}  "
              f"sector={str(p.get('sector',''))[:7]:7s}  "
              f"fit={p['fit_score']:.1f}")

    m = evaluate(picks)
    print(f"  ① 평균 배당수익률: {m['avg_yield']}%   ② DPS성장: {m['avg_dps_growth']}%/yr")
    print(f"  ③ 평균 리스크: {m['avg_risk']}   ④ 고위험(>40): {m['high_risk_pct']}")
    print(f"  ⑤ ETF 비중: {m['etf_ratio']}   ⑥ 10년후 월배당: {m['monthly_10y']}")
    print(f"  ⑦ 20년후 월배당: {m['monthly_20y']}   ⑧ FIRE 달성 나이: {m['fire_age']}세")
    print()

    summary_rows.append({
        "방식":        method_name,
        "yield":      f"{m['avg_yield']}%",
        "DPS성장":    f"{m['avg_dps_growth']}%",
        "리스크":     f"{m['avg_risk']}",
        "고위험":     m["high_risk_pct"],
        "ETF비중":    m["etf_ratio"],
        "10년월배당": m["monthly_10y"],
        "20년월배당": m["monthly_20y"],
        "FIRE":      f"{m['fire_age']}세",
    })

# ─── 최종 비교표 ────────────────────────────────────────────────
print("=" * 75)
print("  최종 비교 요약")
print("=" * 75)
headers = list(summary_rows[0].keys())
col_w = {h: max(len(h), max(len(str(r[h])) for r in summary_rows)) + 2 for h in headers}
print(" | ".join(h.ljust(col_w[h]) for h in headers))
print("-" * sum(col_w[h] + 3 for h in headers))
for row in summary_rows:
    print(" | ".join(str(row[h]).ljust(col_w[h]) for h in headers))

print()
print("  [E 채택 기준]")
print("  E25가 A와 비교해서: 리스크↓ / 고위험 종목 없음 / FIRE 나이 비슷 or 더 빠름")
print("  E25가 B와 비교해서: 고위험 종목(risk>40) 제거 / DPS성장 비슷")
print("  → 만족하면: 'target_yield를 Ranker에서 분리하는 것이 실험으로 검증됨'")
print("=" * 75)

# ══════════════════════════════════════════════════════════════════════
#  E_v2 실험: abs_yield_fit_v2 (완만한 saturation) × 3가지 나이 시나리오
#  25세/40세/60세를 동일 평가 함수로 돌려서 자연스러운 포트폴리오 변화 확인
# ══════════════════════════════════════════════════════════════════════
print()
print("=" * 75)
print("=== E_v2 실험: abs_yield_fit_v2 saturation 곡선 확인 ===")
print("=" * 75)
for y in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12]:
    v1 = abs_yield_fit(y)
    v2 = abs_yield_fit_v2(y)
    bar_v2 = "█" * int(v2 / 5)
    print(f"  yield={y:2d}%  v1={v1:5.1f}  v2={v2:5.1f}  {bar_v2}")
print()

# 세 가지 나이 시나리오 설정
E_V2_SCENARIOS = [
    {
        "label":    "E25_v2 [장기 25년]",
        "age":      25,
        "target_fire_age": 50,
        "reserve":  360.0,
        "monthly":  30.0,
        "monthly_target": 50.0,
        "risk_tol": "moderate",
        # abs_yield(sat_v2)×0.15 + risk×0.40 + growth×0.30 + age_fit×0.15
        "weights":  {"abs_yield": 0.15, "risk": 0.40, "growth": 0.30, "age": 0.15},
    },
    {
        "label":    "E40_v2 [중기 10년]",
        "age":      40,
        "target_fire_age": 55,
        "reserve":  5000.0,
        "monthly":  50.0,
        "monthly_target": 100.0,
        "risk_tol": "moderate",
        # abs_yield(sat_v2)×0.20 + risk×0.40 + growth×0.20 + age_fit×0.20
        "weights":  {"abs_yield": 0.20, "risk": 0.40, "growth": 0.20, "age": 0.20},
    },
    {
        "label":    "E60_v2 [단기 5년]",
        "age":      60,
        "target_fire_age": 65,
        "reserve":  30000.0,
        "monthly":  0.0,
        "monthly_target": 200.0,
        "risk_tol": "conservative",
        # abs_yield(sat_v2)×0.30 + risk×0.40 + growth×0.10 + age_fit×0.20
        "weights":  {"abs_yield": 0.30, "risk": 0.40, "growth": 0.10, "age": 0.20},
    },
]

def run_e_v2(candidates, scenario, n_pick=6):
    """E_v2 방식으로 후보군 랭킹."""
    age     = scenario["age"]
    w       = scenario["weights"]
    risk_tol = scenario["risk_tol"]

    scored = []
    for c in candidates:
        c = dict(c)
        rs = score_asset(
            ticker         = str(c.get("ticker") or ""),
            asset_class    = str(c.get("asset_class", "kr_stock")),
            ml_status      = str(c.get("ml_status", "INTACT")),
            survival_hazard= c.get("survival_risk_score"),
            macro          = None,
            risk_tolerance = risk_tol,
        )
        c.update(rs)
        if c["risk_gate"] == "BLOCK":
            continue
        ay  = abs_yield_fit_v2(float(c.get("expected_yield", 0)))
        rf  = risk_fit(rs["composite_risk_score"])
        gf  = growth_fit_fn(c, age)
        af  = age_fit_fn(c, age)
        c["fit_score"] = round(
            ay * w["abs_yield"] + rf * w["risk"] + gf * w["growth"] + af * w["age"], 2
        )
        c["_ay"] = ay
        scored.append(c)

    scored.sort(key=lambda x: -x["fit_score"])

    # sector 2층 제약: 동일 세분화 섹터 max 1개 + 동일 상위 그룹 max 2개
    selected, sector_cnt, group_cnt = [], {}, {}
    for s in scored:
        sector = str(s.get("sector", "기타"))
        group  = str(s.get("sector_group", s.get("sector", "기타")))
        if sector_cnt.get(sector, 0) >= 1:      # 동일 세분화 섹터 1개 제한
            continue
        if group_cnt.get(group, 0) >= 2:         # 동일 상위 그룹 2개 제한
            continue
        selected.append(s)
        sector_cnt[sector] = sector_cnt.get(sector, 0) + 1
        group_cnt[group]   = group_cnt.get(group, 0) + 1
        if len(selected) >= n_pick:
            break
    return selected

def evaluate_v2(picks, scenario):
    """8가지 지표 — scenario별 나이/목표 반영."""
    if not picks:
        return {k: "—" for k in [
            "avg_yield","avg_dps_growth","avg_risk","high_risk_pct",
            "etf_ratio","monthly_10y","monthly_20y","fire_age","spyi_jepq",
        ]}
    n = len(picks)
    age            = scenario["age"]
    reserve        = scenario["reserve"]
    monthly_invest = scenario["monthly"]
    monthly_target = scenario["monthly_target"]
    target_fire    = scenario["target_fire_age"]

    avg_yield  = sum(float(p.get("expected_yield", 0)) for p in picks) / n
    avg_dps    = sum(float(p.get("dps_yoy_pct", 0) or 0) for p in picks) / n
    avg_risk   = sum(float(p.get("composite_risk_score", 50)) for p in picks) / n
    high_risk  = sum(1 for p in picks if float(p.get("composite_risk_score", 0)) > 40)
    etf_cnt    = sum(1 for p in picks if "etf" in str(p.get("asset_class","")).lower()
                                          or "reit" in str(p.get("asset_class","")).lower())
    spyi_jepq  = [p["ticker"] for p in picks if str(p.get("ticker","")) in ("SPYI","JEPQ","QYLD")]

    def future_monthly(years):
        total_ret = avg_yield / 100 + (avg_dps / 100) * 0.5
        pf = reserve
        for _ in range(years):
            pf = pf * (1 + total_ret) + monthly_invest * 12
        return round(pf * avg_yield / 100 / 12, 1)

    m10 = future_monthly(10)
    m20 = future_monthly(20)

    fire = calc_fire_engine(
        current_investable  = reserve,
        monthly_savings     = monthly_invest,
        current_age         = age,
        target_age          = target_fire,
        avg_net_yield       = avg_yield * 0.85,
        div_growth_rate     = avg_dps,
        cpi_rate            = 2.5,
        custom_monthly_만원 = monthly_target,
    )
    custom   = fire.get("targets", {}).get("custom") or {}
    fire_age = custom.get("projected_fire_age", "미달성")

    return {
        "avg_yield":     round(avg_yield, 2),
        "avg_dps_growth":round(avg_dps, 2),
        "avg_risk":      round(avg_risk, 1),
        "high_risk_pct": f"{high_risk}/{n}",
        "etf_ratio":     f"{etf_cnt}/{n}",
        "monthly_10y":   f"{m10}만원",
        "monthly_20y":   f"{m20}만원",
        "fire_age":      str(fire_age),
        "spyi_jepq":     ",".join(spyi_jepq) if spyi_jepq else "없음",
    }

# ─── E_v2 실행 ──────────────────────────────────────────────────
v2_summary = []

for sc in E_V2_SCENARIOS:
    print(f"{'─'*70}")
    print(f"  [{sc['label']}]")
    w = sc["weights"]
    print(f"  가중치: abs_yield_v2×{w['abs_yield']} + risk×{w['risk']} + growth×{w['growth']} + age_fit×{w['age']}")
    print(f"  나이={sc['age']}세 / 초기자산={sc['reserve']:.0f}만원 / 월적립={sc['monthly']:.0f}만원 / 목표={sc['monthly_target']:.0f}만원")

    picks = run_e_v2(all_candidates, sc, n_pick=6)

    print(f"  선택 종목:")
    for p in picks:
        sg = p.get("sector_group", p.get("sector", "?"))
        s  = p.get("sector", "?")
        print(f"    [{str(p['ticker']):7s}] {p.get('name','')[:12]:12s}  "
              f"yield={p.get('expected_yield',0):.1f}%  "
              f"dps={p.get('dps_yoy_pct',0) or 0:.1f}%/yr  "
              f"risk={p.get('composite_risk_score',50):.0f}  "
              f"absY_v2={p.get('_ay',0):.0f}  "
              f"fit={p['fit_score']:.1f}  "
              f"[{s}/{sg}]")

    m = evaluate_v2(picks, sc)
    print(f"  ① yield: {m['avg_yield']}%   ② DPS성장: {m['avg_dps_growth']}%/yr")
    print(f"  ③ 리스크: {m['avg_risk']}   ④ 고위험: {m['high_risk_pct']}   ⑤ ETF: {m['etf_ratio']}")
    print(f"  ⑥ 10년 월배당: {m['monthly_10y']}   ⑦ 20년 월배당: {m['monthly_20y']}")
    print(f"  ⑧ FIRE 달성 나이: {m['fire_age']}세   SPYI/JEPQ 포함: {m['spyi_jepq']}")
    print()

    v2_summary.append({
        "시나리오":    sc["label"],
        "yield":      f"{m['avg_yield']}%",
        "DPS성장":    f"{m['avg_dps_growth']}%",
        "리스크":     f"{m['avg_risk']}",
        "고위험":     m["high_risk_pct"],
        "ETF":        m["etf_ratio"],
        "10년배당":   m["monthly_10y"],
        "20년배당":   m["monthly_20y"],
        "FIRE":       f"{m['fire_age']}세",
        "SPYI/JEPQ":  m["spyi_jepq"],
    })

print("=" * 75)
print("  E_v2 세 시나리오 비교 (성공 기준 검증)")
print("=" * 75)
headers3 = list(v2_summary[0].keys())
col_w3 = {h: max(len(h), max(len(str(r[h])) for r in v2_summary)) + 2 for h in headers3}
print(" | ".join(h.ljust(col_w3[h]) for h in headers3))
print("-" * sum(col_w3[h] + 3 for h in headers3))
for row in v2_summary:
    print(" | ".join(str(row[h]).ljust(col_w3[h]) for h in headers3))

print()
print("  [E_v2 채택 성공 기준]")
print("  E25_v2: FIRE 50~55세 / SPYI·JEPQ 없음 / 고위험 0/6 / DPS성장 ≥ 7%")
print("  E40_v2: FIRE ≤ 55세  / 리스크 적절     / DPS성장 ≥ 5%")
print("  E60_v2: FIRE ≤ 65세  / yield ≥ 5%    / 리스크 낮음")
print("  → 3개 모두 만족: personalized_ranker.py 개편 확정")
print("=" * 75)

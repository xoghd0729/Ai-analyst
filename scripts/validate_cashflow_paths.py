"""
scripts/validate_cashflow_paths.py
====================================
25세 / 초기자산 0 / 목표 월배당 50만원 기준으로
월 적립금(10/30/50/100만원)에 따라 FIRE 달성 나이가 어떻게 달라지는지 검증.

목적:
  현재 target_yield 역산 방식이 "현재 자산으로 즉시 달성"을 전제하는지,
  아니면 "적립 복리로 장기 달성"을 반영하는지 확인.
  결과가 납득 가능하면 Personalized Ranker를 새 방식으로 재설계.

실행:
  cd ~/ai-analyst
  python scripts/validate_cashflow_paths.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.fire_engine import calc_fire_engine

# ─── 기본 가정 ─────────────────────────────────────────────────
AGE           = 25
TARGET_AGE    = 50          # 목표 FIRE 나이 (기준)
INITIAL_ASSET = 0           # 초기 자본 (만원) — 사회초년생
TARGET_MONTHLY = 50         # 목표 월배당 (만원)
AVG_NET_YIELD  = 3.5        # 세후 배당수익률 (%)
DIV_GROWTH     = 5.0        # 배당 성장률 (%)
CPI_RATE       = 2.5        # 물가상승률 (%)

# 비교할 월 적립금 시나리오
MONTHLY_SAVINGS_LIST = [10, 30, 50, 100]

# ─── 실행 ──────────────────────────────────────────────────────
print("=" * 70)
print("  25세 / 초기자산 0 / 목표 월배당 50만원 — 적립금별 달성 나이 비교")
print("=" * 70)
print(f"  기준: 세후 수익률 {AVG_NET_YIELD}% · 배당성장 {DIV_GROWTH}%/년 · CPI {CPI_RATE}%")
print()

results = []

for monthly in MONTHLY_SAVINGS_LIST:
    r = calc_fire_engine(
        current_investable  = INITIAL_ASSET,
        monthly_savings     = float(monthly),
        current_age         = AGE,
        target_age          = TARGET_AGE,
        avg_net_yield       = AVG_NET_YIELD,
        div_growth_rate     = DIV_GROWTH,
        cpi_rate            = CPI_RATE,
        custom_monthly_만원 = float(TARGET_MONTHLY),
    )

    custom  = r.get("targets", {}).get("custom") or {}
    regular = r.get("targets", {}).get("regular") or {}
    lean    = r.get("targets", {}).get("lean") or {}

    custom_age  = custom.get("projected_fire_age", "미달성")
    regular_age = regular.get("projected_fire_age", "미달성")
    lean_age    = lean.get("projected_fire_age", "미달성")

    # 현재 현금흐름 (적립 0년차)
    current_monthly = r.get("current_state", {}).get("current_monthly_div", 0)

    # 10년 후 예상 자산 (타임라인에서 추출)
    timeline = r.get("fire_timeline", [])
    asset_10y = next((t["portfolio"] for t in timeline if t["age"] == AGE + 10), None)
    div_10y   = round(asset_10y * AVG_NET_YIELD / 100 / 12, 1) if asset_10y else None

    results.append({
        "월 적립":       f"{monthly}만원",
        "현재 월배당":   f"{current_monthly:.1f}만원",
        "10년후 월배당": f"{div_10y:.1f}만원" if div_10y else "—",
        "목표 달성 나이": custom_age if custom_age != "미달성" else "50세 내 미달성",
        "Lean FIRE":    lean_age if lean_age != "미달성" else "미달성",
        "일반 FIRE":    regular_age if regular_age != "미달성" else "미달성",
    })

# ─── 표 출력 ────────────────────────────────────────────────────
headers = list(results[0].keys())
col_w = {h: max(len(h), max(len(str(r[h])) for r in results)) + 2 for h in headers}

hdr = " | ".join(h.ljust(col_w[h]) for h in headers)
print(hdr)
print("-" * len(hdr))
for row in results:
    print(" | ".join(str(row[h]).ljust(col_w[h]) for h in headers))

print()
print("─" * 70)
print("  [해석 기준]")
print("  - '목표 달성 나이'가 적립금에 비례해 앞당겨지면 FIRE 엔진 정상")
print("  - 10년 후 월배당이 현재보다 크고 적립금에 비례하면 복리 반영 정상")
print("  - '현재 월배당'은 초기자산 0이므로 거의 0이 정상")
print()

# ─── 추가: 초기자산 있는 케이스 비교 ────────────────────────────
print("=" * 70)
print("  초기자산별 비교 (월 적립 30만원 고정 / 목표 50만원)")
print("=" * 70)

INITIAL_LIST = [0, 1000, 3000, 5000]
results2 = []

for init in INITIAL_LIST:
    r = calc_fire_engine(
        current_investable  = float(init),
        monthly_savings     = 30.0,
        current_age         = AGE,
        target_age          = TARGET_AGE,
        avg_net_yield       = AVG_NET_YIELD,
        div_growth_rate     = DIV_GROWTH,
        cpi_rate            = CPI_RATE,
        custom_monthly_만원 = float(TARGET_MONTHLY),
    )
    custom = (r.get("targets", {}).get("custom") or {})
    current = r.get("current_state", {}).get("current_monthly_div", 0)
    results2.append({
        "초기 자산":     f"{init:,}만원",
        "현재 월배당":   f"{current:.1f}만원",
        "목표 달성 나이": custom.get("projected_fire_age", "미달성"),
    })

headers2 = list(results2[0].keys())
col_w2 = {h: max(len(h), max(len(str(r[h])) for r in results2)) + 2 for h in headers2}
hdr2 = " | ".join(h.ljust(col_w2[h]) for h in headers2)
print(hdr2)
print("-" * len(hdr2))
for row in results2:
    print(" | ".join(str(row[h]).ljust(col_w2[h]) for h in headers2))

print()
print("─" * 70)
print("  초기자산이 클수록 현재 월배당이 높고 달성 나이가 앞당겨지면 정상.")
print("=" * 70)

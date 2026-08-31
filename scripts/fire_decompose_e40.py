"""
fire_decompose_e40.py
======================
E40_v2 FIRE 56세 원인 분해 테스트.

SPYI 포함/제거 전후의 avg_yield / avg_dps 변화를 보고,
각 조합에서 FIRE engine이 반환하는 projected_fire_age를 비교한다.

실행:
  cd ~/ai-analyst && python scripts/fire_decompose_e40.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.fire_engine import calc_fire_engine

# ─── E40_v2 실제 포트폴리오 종목 ───────────────────────────────────────────
# (ranker_experiment.py 최종 결과 기준)
E40_FULL = [
    {"name": "JB금융지주",  "expected_yield": 4.86, "dps_yoy_pct": 14.6},
    {"name": "우리금융지주", "expected_yield": 4.23, "dps_yoy_pct": 13.3},
    {"name": "JEPI",        "expected_yield": 7.5,  "dps_yoy_pct": 4.0 },
    {"name": "SPYI",        "expected_yield": 12.0, "dps_yoy_pct": 2.0 },
    {"name": "VZ",          "expected_yield": 6.8,  "dps_yoy_pct": 1.5 },
    {"name": "FRT",         "expected_yield": 4.2,  "dps_yoy_pct": 2.5 },
]

# SPYI 제거 후 대체 후보: ABBV (비슷한 risk, 더 나은 DPS growth)
E40_NO_SPYI = [
    {"name": "JB금융지주",  "expected_yield": 4.86, "dps_yoy_pct": 14.6},
    {"name": "우리금융지주", "expected_yield": 4.23, "dps_yoy_pct": 13.3},
    {"name": "JEPI",        "expected_yield": 7.5,  "dps_yoy_pct": 4.0 },
    {"name": "ABBV",        "expected_yield": 3.8,  "dps_yoy_pct": 5.8 },
    {"name": "VZ",          "expected_yield": 6.8,  "dps_yoy_pct": 1.5 },
    {"name": "FRT",         "expected_yield": 4.2,  "dps_yoy_pct": 2.5 },
]

# 이상적 포트폴리오 (SPYI/QYLD 없음, yield 중간, dps 고성장)
E40_IDEAL = [
    {"name": "JB금융지주",  "expected_yield": 4.86, "dps_yoy_pct": 14.6},
    {"name": "SCHD",        "expected_yield": 3.6,  "dps_yoy_pct": 10.0},
    {"name": "JEPI",        "expected_yield": 7.5,  "dps_yoy_pct": 4.0 },
    {"name": "ABBV",        "expected_yield": 3.8,  "dps_yoy_pct": 5.8 },
    {"name": "VZ",          "expected_yield": 6.8,  "dps_yoy_pct": 1.5 },
    {"name": "CVX",         "expected_yield": 4.1,  "dps_yoy_pct": 4.9 },
]

BASE_PARAMS = dict(
    current_investable=5000,
    monthly_savings=50,
    current_age=40,
    target_age=55,
    cpi_rate=2.5,
    custom_monthly_만원=100.0,
)

TAX_RATE = 0.85  # 세후 수익률 계수


def avg_stats(portfolio):
    n = len(portfolio)
    avg_y = sum(p["expected_yield"] for p in portfolio) / n
    avg_d = sum(p["dps_yoy_pct"] for p in portfolio) / n
    return avg_y, avg_d


def run_fire(label, portfolio, extra_label=""):
    avg_y, avg_d = avg_stats(portfolio)
    net_y = avg_y * TAX_RATE
    result = calc_fire_engine(
        **BASE_PARAMS,
        avg_net_yield=net_y,
        div_growth_rate=avg_d,
    )
    custom = (result.get("targets") or {}).get("custom") or {}
    fire_age = custom.get("projected_fire_age", "미달성")

    current = (result.get("current_state") or {})
    cur_div = current.get("current_monthly_div", 0)

    print(f"\n  [{label}]  {extra_label}")
    print(f"    포트폴리오: {', '.join(p['name'] for p in portfolio)}")
    print(f"    avg_gross_yield : {avg_y:.2f}%")
    print(f"    avg_net_yield   : {net_y:.2f}%  (×{TAX_RATE})")
    print(f"    avg_dps_growth  : {avg_d:.2f}%")
    print(f"    현재 월배당     : {cur_div:.1f}만원 (5000만원 기준)")
    print(f"    → FIRE age      : {fire_age}세")
    return fire_age


# ─── 민감도 분석 ──────────────────────────────────────────────────────────
def sensitivity():
    """net_yield를 4.0~7.0% 범위에서 바꾸며 FIRE age 변화 관찰"""
    print("\n" + "="*65)
    print("민감도 분석: avg_net_yield 변화 → FIRE age")
    print("  (avg_dps_growth 고정: 6.38%, 조건 동일)")
    print("="*65)
    print(f"  {'net_yield':>10}  {'gross_yield':>12}  {'FIRE age':>10}")
    for pct in [4.0, 4.5, 5.0, 5.2, 5.5, 5.61, 6.0, 6.5, 7.0]:
        r = calc_fire_engine(**BASE_PARAMS, avg_net_yield=pct, div_growth_rate=6.38)
        fa = ((r.get("targets") or {}).get("custom") or {}).get("projected_fire_age", "미달성")
        gross = round(pct / TAX_RATE, 2)
        print(f"  {pct:>10.2f}%  {gross:>12.2f}%  {fa!s:>10}")


# ─── 메인 ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 65)
    print("E40_v2 FIRE 56세 원인 분해 — 40세 / 5000만원 / 월50만원 / 목표 100만원")
    print("=" * 65)

    fa_full   = run_fire("E40_FULL   (SPYI 포함)", E40_FULL)
    fa_no_sp  = run_fire("E40_NO_SPYI (SPYI→ABBV)", E40_NO_SPYI)
    fa_ideal  = run_fire("E40_IDEAL  (이상적 후보)", E40_IDEAL)

    print()
    print("─" * 65)
    print("결과 요약:")
    print(f"  SPYI 포함   → {fa_full}세")
    print(f"  SPYI→ABBV   → {fa_no_sp}세")
    print(f"  이상적 후보 → {fa_ideal}세")
    print()
    if str(fa_full) != str(fa_no_sp):
        print("  ✅ SPYI 제거 시 FIRE age 변화 → Ranker 선택이 원인임을 확인")
    else:
        print("  ℹ️  SPYI 제거해도 FIRE age 동일 → 입력조건 또는 구조적 문제")

    sensitivity()

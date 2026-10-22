#!/usr/bin/env python3
"""
scripts/smoke_test_exhibition.py
==================================
전시 전 최종 E2E 스모크 테스트 — API 서버 없이 직접 파이프라인 실행.

실행 방법:
    cd ~/ai-analyst
    python scripts/smoke_test_exhibition.py

성공 시: ✅ ALL PASSED 출력
실패 시: ❌ 항목명 + 오류 메시지 출력 후 종료 코드 1
"""
import sys, os, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "

results = []

def check(name: str, fn):
    start = time.time()
    try:
        fn()
        elapsed = time.time() - start
        results.append((PASS, name, f"{elapsed:.2f}s"))
        print(f"  {PASS} {name} ({elapsed:.2f}s)")
    except Exception as e:
        elapsed = time.time() - start
        results.append((FAIL, name, str(e)))
        print(f"  {FAIL} {name}")
        print(f"       {e}")


print("\n" + "="*60)
print("  FinSight 전시 전 스모크 테스트")
print("="*60 + "\n")

# ── 1. 임포트 체크 ────────────────────────────────────────────
print("[1/7] 핵심 모듈 임포트")

def _import_pipeline():
    from api.pipeline.runner import RecommendationPipeline
    from api.pipeline.context import PortfolioRequest

def _import_utils():
    from utils.fire_engine import calc_fire_engine
    from utils.monte_carlo import run_monte_carlo
    from utils.tax_optimizer import calc_tax_optimizer
    from utils.risk_engine import score_asset
    from utils.macro_regime import get_macro_regime
    from utils.stress_test import run_stress_test
    from utils.dividend_projection import simulate_portfolio
    from utils.rebalancer import generate_rebalancing_plan
    from utils.storytelling import generate_storytelling

check("pipeline 임포트", _import_pipeline)
check("utils 임포트", _import_utils)

# ── 2. 파이프라인 E2E (혼합형 35세) ──────────────────────────
print("\n[2/7] 파이프라인 E2E — 혼합형 35세")

_pipeline_result = {}

def _pipeline_mixed():
    from api.pipeline.runner import RecommendationPipeline
    from api.pipeline.context import PortfolioRequest
    req = PortfolioRequest(
        age=35, annual_income=5000, monthly_target=50,
        investable_amount=5000, risk_tolerance="moderate",
        archetype="혼합형", monthly_savings=30, target_fire_age=55,
    )
    result = RecommendationPipeline(req).execute()
    assert "recommendations" in result and len(result["recommendations"]) > 0
    assert "summary" in result
    assert result["summary"].get("est_monthly_div_after_tax_만원", 0) >= 0
    _pipeline_result["mixed"] = result

check("혼합형 파이프라인", _pipeline_mixed)

# ── 3. 파이프라인 E2E (안정형 55세) ──────────────────────────
print("\n[3/7] 파이프라인 E2E — 안정형 55세")

def _pipeline_conservative():
    from api.pipeline.runner import RecommendationPipeline
    from api.pipeline.context import PortfolioRequest
    req = PortfolioRequest(
        age=55, annual_income=3000, monthly_target=200,
        investable_amount=20000, risk_tolerance="conservative",
        archetype="안정형", monthly_savings=0, target_fire_age=60,
    )
    result = RecommendationPipeline(req).execute()
    assert len(result["recommendations"]) > 0
    _pipeline_result["conservative"] = result

check("안정형 파이프라인", _pipeline_conservative)

# ── 4. 핵심 유틸 단독 실행 ───────────────────────────────────
print("\n[4/7] 핵심 유틸 단독 실행")

def _fire_engine():
    from utils.fire_engine import calc_fire_engine
    r = calc_fire_engine(5000, 30, 35, 55, 3.5)
    assert "targets" in r
    reg = r["targets"]["regular"]
    assert reg["monthly_target_nominal"] > 0
    assert "required_principal" in reg

def _monte_carlo():
    from utils.monte_carlo import run_monte_carlo
    recs = [{"ticker": "SCHD", "dividend_yield": 3.5, "weight_pct": 100,
             "asset_class": "us_div_etf", "etf_category": "dividend_growth"}]
    r = run_monte_carlo(recs, 5000, years=10, n_simulations=200)
    # 반환값 구조 확인 (값이 리스트 또는 숫자 모두 허용)
    for key in ("p10_monthly", "p50_monthly", "p90_monthly"):
        assert key in r, f"Monte Carlo missing key: {key}"
    # p10 ≤ p50 ≤ p90 순서 검증 (리스트면 마지막 값 사용)
    def _scalar(v):
        return v[-1] if isinstance(v, list) else float(v)
    p10, p50, p90 = _scalar(r["p10_monthly"]), _scalar(r["p50_monthly"]), _scalar(r["p90_monthly"])
    assert p10 <= p50, f"p10({p10}) > p50({p50})"
    assert p50 <= p90, f"p50({p50}) > p90({p90})"

def _tax_optimizer():
    from utils.tax_optimizer import calc_tax_optimizer, ISA_ANNUAL_LIMIT, ISA_TAX_FREE_GENERAL, ISA_TAX_FREE_YOUTH
    # 2026 세법 상수 확인
    assert ISA_ANNUAL_LIMIT == 4_000, f"ISA limit changed! {ISA_ANNUAL_LIMIT}"
    assert ISA_TAX_FREE_GENERAL == 500
    assert ISA_TAX_FREE_YOUTH == 1_000
    recs = [{"ticker": "SCHD", "dividend_yield": 3.5, "weight_pct": 100, "asset_class": "us_div_etf"}]
    r = calc_tax_optimizer(recs, 5000, 35)
    assert "effective_tax_rate_pct" in r

def _macro_regime():
    from utils.macro_regime import get_macro_regime
    r = get_macro_regime()
    assert r["regime"] in ("RATE_RISING", "RATE_FALLING", "HIGH_VOLATILITY", "RECESSION", "NORMAL")
    assert "advisory" in r

def _risk_engine():
    from utils.risk_engine import score_asset, _W_STATUS, _W_SURVIVAL
    assert _W_STATUS == 0.70, "70:30 가중치 변경됨!"
    assert _W_SURVIVAL == 0.30
    r = score_asset("SCHD", "us_div_etf", "INTACT", None, None, "moderate")
    assert r["risk_gate"] == "PASS"

check("FIRE 역산 엔진", _fire_engine)
check("Monte Carlo P10/P50/P90", _monte_carlo)
check("세금 최적화 (2026 세법)", _tax_optimizer)
check("Macro Regime 판정", _macro_regime)
check("Risk Engine (70:30 가중치)", _risk_engine)

# ── 5. 포트폴리오 비교 ────────────────────────────────────────
print("\n[5/7] 포트폴리오 비교 (_extract_compare_metrics)")

def _compare():
    from api.routers.portfolio import _extract_compare_metrics
    a = {"summary": {"est_monthly_div_after_tax_만원": 15.0, "target_achievement_pct": 75.0},
         "fire_plan": {"fire_timeline": {"lean_fire_age": 50, "regular_fire_age": 55}},
         "monte_carlo": {"p50_monthly": 12.0, "confidence_at_target": 65.0},
         "backtest": {"mdd_pct": -15.0, "sharpe_ratio": 1.1},
         "portfolio_health": {"overall_score": 78.0},
         "tax_optimizer": {"total_annual_saving_만원": 40.0}}
    b = {"summary": {"est_monthly_div_after_tax_만원": 10.0, "target_achievement_pct": 50.0},
         "fire_plan": {"fire_timeline": {"lean_fire_age": 58, "regular_fire_age": 63}},
         "monte_carlo": {"p50_monthly": 8.0, "confidence_at_target": 45.0},
         "backtest": {"mdd_pct": -25.0, "sharpe_ratio": 0.7},
         "portfolio_health": {"overall_score": 60.0},
         "tax_optimizer": {"total_annual_saving_만원": 20.0}}
    metrics = _extract_compare_metrics(a, b)
    assert len(metrics) > 0
    winners = {m["winner"] for m in metrics}
    assert winners <= {"a", "b", "tie"}

check("포트폴리오 비교", _compare)

# ── 6. 스트레스 테스트 + 스토리텔링 ─────────────────────────
print("\n[6/7] 스트레스 테스트 + 스토리텔링")

def _stress():
    from utils.stress_test import run_stress_test
    recs = [
        {"ticker": "SCHD", "asset_class": "us_div_etf", "etf_category": "dividend_growth",
         "weight_pct": 60, "net_yield_pct": 3.0},
        {"ticker": "JEPI", "asset_class": "us_div_etf", "etf_category": "monthly_income",
         "weight_pct": 40, "net_yield_pct": 6.8},
    ]
    r = run_stress_test(recs, 5000)
    assert 0 <= r["overall_resilience_score"] <= 100
    assert len(r["scenarios"]) == 4

def _storytelling():
    from utils.storytelling import generate_storytelling
    r = generate_storytelling(
        input_data={"age": 35, "risk_tolerance": "moderate", "investable": 5000, "monthly_target": 50},
        recommendations=[{"ticker": "SCHD", "name": "SCHD", "asset_class": "us_div_etf",
                           "weight_pct": 100, "dividend_yield": 3.5, "sector": "Div"}],
        summary={"investable_amount_만원": 5000, "avg_yield_pct": 3.5,
                 "est_monthly_div_after_tax_만원": 10.0, "target_achievement_pct": 20.0},
        projection={"years": list(range(1, 11)), "monthly_div_net": [10+i for i in range(10)],
                    "milestones": {"div_doubles_year": 8, "target_achieved_year": None, "target_만원": 50}},
        living_coverage={"coverage_pct": 20.0, "monthly_expense_만원": 250, "monthly_div_net_만원": 10.0},
        stress_test={"overall_resilience_score": 70.0, "overall_grade": "✅ 양호", "scenarios": {}},
        dividend_calendar={"monthly_totals": {}, "top_months": []},
        sector_exposure={"sectors": []},
        macro_regime={"regime": "NORMAL", "label": "정상", "advisory": "정상입니다."},
        risk_alerts=[],
        archetype="혼합형",
    )
    assert "narrative" in r
    assert len(r["narrative"]["full_text"]) > 100

check("스트레스 테스트", _stress)
check("스토리텔링 내러티브", _storytelling)

# ── 7. 데이터 파일 존재 확인 ─────────────────────────────────
print("\n[7/7] 데이터 파일 존재 여부")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _check_data_files():
    required_files = [
        ("data/asset_metadata.json",       "자산 메타데이터"),
        ("data/macro_config.json",         "Macro 기준값 설정"),
        ("models/kr_3class_model.pkl",     "XGBoost 벤치마크 모델"),
    ]
    missing = []
    for rel, desc in required_files:
        path = os.path.join(BASE, rel)
        if not os.path.exists(path):
            missing.append(f"{rel} ({desc})")
    if missing:
        raise FileNotFoundError("필수 파일 없음:\n  " + "\n  ".join(missing))

def _check_survival_data():
    path = os.path.join(BASE, "results", "survival_pd_v4.json")
    if not os.path.exists(path):
        print(f"    {WARN} survival_pd_v4.json 없음 — 위험 점수 중립값(50) 사용")

check("필수 데이터 파일", _check_data_files)
_check_survival_data()

# ── 최종 결과 ─────────────────────────────────────────────────
print("\n" + "="*60)
passed = [r for r in results if r[0] == PASS]
failed = [r for r in results if r[0] == FAIL]

print(f"  결과: {len(passed)} 통과 / {len(failed)} 실패")

if failed:
    print("\n  실패 항목:")
    for icon, name, msg in failed:
        print(f"    {icon} {name}: {msg}")
    print()
    sys.exit(1)
else:
    print(f"\n  {PASS} ALL PASSED — 전시 준비 완료!\n")
    sys.exit(0)

"""
scripts/test_e2e.py — E2E 파이프라인 검증 + 개인화 3개 시나리오 비교
================================================================
실행:
    cd ~/ai-analyst
    python scripts/test_e2e.py

확인 항목:
  1. 파이프라인이 끝까지 실행되는가 (에러 없이)
  2. age/investable/risk_tolerance 따라 결과가 실제로 달라지는가
  3. 종목이 3~5개로 압축되는가
  4. 위험 종목(BLOCK)이 제거되는가
  5. Monte Carlo P10/P50/P90이 사용자별로 다른가
  6. fit_score가 최종 recommendations에 존재하는가
"""

import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.pipeline.context import PortfolioRequest
from api.pipeline.runner import RecommendationPipeline

# ─── 3개 시나리오 ───────────────────────────────────────────────
SCENARIOS = [
    {
        "label": "A. 25세 / 공격형 / 초기 3000만",
        "params": dict(
            age=25, annual_income=3000, monthly_target=50,
            investable_amount=3000, risk_tolerance="aggressive",
            archetype="성장형", monthly_savings=100.0, target_fire_age=45,
        ),
    },
    {
        "label": "B. 40세 / 중립형 / 초기 5000만",
        "params": dict(
            age=40, annual_income=6000, monthly_target=100,
            investable_amount=5000, risk_tolerance="moderate",
            archetype="혼합형", monthly_savings=50.0, target_fire_age=55,
        ),
    },
    {
        "label": "C. 60세 / 보수형 / 초기 1억",
        "params": dict(
            age=60, annual_income=0, monthly_target=200,
            investable_amount=10000, risk_tolerance="conservative",
            archetype="배당형", monthly_savings=0.0, target_fire_age=65,
        ),
    },
]

# ─── 개인화 검증 포인트 ─────────────────────────────────────────
def check_personalization(results: list[dict]) -> None:
    print("\n" + "="*60)
    print("  [개인화 검증] 시나리오별 핵심 지표 비교")
    print("="*60)

    rows = []
    for label, r in results:
        recs = r.get("recommendations", [])
        mc   = r.get("monte_carlo", {})
        fire = r.get("fire_plan", r.get("fire_engine", {}))

        n_kr  = sum(1 for x in recs if x.get("asset_class") == "kr_stock")
        n_us  = sum(1 for x in recs if x.get("asset_class") in ("us_stock","us_reit"))
        n_etf = sum(1 for x in recs if "etf" in x.get("asset_class","").lower() or
                    x.get("asset_class") == "defensive")

        avg_yield  = (sum(x.get("dividend_yield",0) for x in recs) / len(recs)) if recs else 0
        has_fit    = any(x.get("fit_score") is not None for x in recs)
        has_blocks = any(x.get("risk_gate") == "BLOCK" for x in recs)

        p50_raw = mc.get("p50_final", mc.get("p50_monthly", mc.get("base_monthly", 0)))
        p50_monthly = (p50_raw[-1] if isinstance(p50_raw, list) and p50_raw else p50_raw) or 0
        fire_age    = (fire.get("targets", {}).get("custom") or {}).get("projected_fire_age") or \
                      (fire.get("targets", {}).get("regular") or {}).get("projected_fire_age") or \
                      fire.get("earliest_fire_age") or "?"

        rows.append({
            "label":      label,
            "종목수":     len(recs),
            "KR/US/ETF":  f"{n_kr}/{n_us}/{n_etf}",
            "평균배당%":  f"{avg_yield:.1f}",
            "fit_score":  "✅" if has_fit else "❌",
            "BLOCK종목":  "⚠️있음" if has_blocks else "없음",
            "P50월배당":  f"{p50_monthly:.1f}만" if p50_monthly else "없음",
            "FIRE나이":   fire_age,
        })

    # 표 출력
    headers = list(rows[0].keys())
    col_w = {h: max(len(h), max(len(str(r[h])) for r in rows)) + 2 for h in headers}

    header_line = " | ".join(h.ljust(col_w[h]) for h in headers)
    print(header_line)
    print("-" * len(header_line))
    for row in rows:
        print(" | ".join(str(row[h]).ljust(col_w[h]) for h in headers))

    # 개인화 검증: 종목이 달라야 함
    print()
    all_tickers = []
    for label, r in results:
        tickers = [x.get("ticker") for x in r.get("recommendations", [])]
        all_tickers.append(set(tickers))
        print(f"  {label[:30]}: {tickers}")

    # 교집합 확인 — 완전히 같으면 개인화 실패
    if len(all_tickers) >= 2:
        intersect_01 = all_tickers[0] & all_tickers[1]
        intersect_12 = all_tickers[1] & all_tickers[2]
        overlap_pct  = (len(intersect_01) + len(intersect_12)) / \
                       (len(all_tickers[0]) + len(all_tickers[1]) + 1) * 100
        if overlap_pct < 30:
            print(f"\n  ✅ 개인화 작동: 시나리오별 추천이 {100-overlap_pct:.0f}% 다름")
        else:
            print(f"\n  ⚠️ 개인화 점검 필요: 시나리오 간 {overlap_pct:.0f}% 겹침")


# ─── 개별 시나리오 상세 출력 ────────────────────────────────────
def print_detail(label: str, result: dict) -> None:
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")

    recs = result.get("recommendations", [])

    if not recs:
        errs = result.get("pipeline_errors") or result.get("errors", [])
        print(f"  ❌ recommendations 없음. 오류: {errs[:3]}")
        return

    print(f"  종목 {len(recs)}개:")
    for i, r in enumerate(recs, 1):
        gate  = r.get("risk_gate", "?")
        gate_icon = "🔴" if gate == "BLOCK" else "🟡" if gate == "WARN" else "🟢"
        fit   = r.get("fit_score")
        fit_s = f"  fit={fit:.2f}" if fit is not None else ""
        crs   = r.get("composite_risk_score")
        crs_s = f"  위험={crs:.0f}" if crs is not None else ""
        print(f"    {i}. {gate_icon} [{r.get('asset_class',''):10}] {r.get('name','')[:20]:20}"
              f"  {r.get('dividend_yield',0):.1f}%  {r.get('weight_pct',0):.1f}%{fit_s}{crs_s}")

    # Monte Carlo (p10/p50/p90_monthly는 연도별 list → _final 스칼라 사용)
    mc = result.get("monte_carlo", {})
    if mc:
        def _mc_val(key, fallback_key=None):
            v = mc.get(key, None)
            if isinstance(v, list):
                v = v[-1] if v else 0
            if v is None and fallback_key:
                v = mc.get(fallback_key, 0)
                if isinstance(v, list):
                    v = v[-1] if v else 0
            return float(v or 0)
        p10 = _mc_val("p10_final", "p10_monthly")
        p50 = _mc_val("p50_final", "p50_monthly")
        p90 = _mc_val("p90_final", "p90_monthly")
        conf_raw = float(mc.get("confidence_at_target", 0) or 0)
        # confidence_at_target은 이미 % 단위 (0-100), 소수면 *100
        conf_pct = conf_raw if conf_raw > 1.0 else conf_raw * 100
        print(f"\n  Monte Carlo:")
        print(f"    P10 월배당: {p10:.1f}만원")
        print(f"    P50 월배당: {p50:.1f}만원")
        print(f"    P90 월배당: {p90:.1f}만원")
        print(f"    목표달성확률: {conf_pct:.0f}%")

    # target_yield
    ty = result.get("target_yield", 0)
    if ty:
        print(f"\n  역산 목표수익률: {ty:.2f}%")

    # pipeline_errors
    errs = result.get("pipeline_errors") or result.get("errors", [])
    if errs:
        print(f"\n  ⚠️ 파이프라인 오류 ({len(errs)}건):")
        for e in errs[:5]:
            print(f"    - {e}")


# ─── 메인 ───────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  AI 현금흐름 OS — E2E 파이프라인 검증")
    print("=" * 60)

    results = []

    for sc in SCENARIOS:
        print(f"\n▶ 실행: {sc['label']}")
        t0  = time.time()
        req = PortfolioRequest(**sc["params"])

        result = {}
        try:
            pipeline = RecommendationPipeline(req)
            result   = pipeline.execute()
            elapsed  = time.time() - t0
            print(f"  ✅ 완료 ({elapsed:.1f}초)")
        except Exception as e:
            print(f"  ❌ 파이프라인 예외: {e}")
            import traceback; traceback.print_exc()

        results.append((sc["label"], result))

        try:
            print_detail(sc["label"], result)
        except Exception as e:
            print(f"  ⚠️ 출력 예외 (결과는 저장됨): {e}")

    if len(results) == 3:
        check_personalization(results)

    # 결과 JSON 저장
    out_path = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "e2e_test_results.json")
    try:
        with open(out_path, "w") as f:
            json.dump(
                {label: {
                    "n_recs": len(r.get("recommendations", [])),
                    "tickers": [x.get("ticker") for x in r.get("recommendations", [])],
                    "p50_monthly": r.get("monte_carlo", {}).get("p50_monthly"),
                    "target_yield": r.get("target_yield"),
                    "errors": r.get("pipeline_errors") or r.get("errors", []),
                } for label, r in results},
                f, ensure_ascii=False, indent=2
            )
        print(f"\n결과 저장: {out_path}")
    except Exception as e:
        print(f"\n결과 저장 실패: {e}")

    print("\n" + "="*60)
    print("  E2E 검증 완료")
    print("="*60)


if __name__ == "__main__":
    main()

"""
RecommendationPipeline (Runner)
────────────────────────────────
Filter 목록을 순서대로 실행하고 최종 API 응답 JSON 을 조립.

왜 Runner 가 별도인가?
  Filter 들은 계산만 담당하고, 응답 직렬화(to_response)는
  Runner 가 단독으로 책임진다.
  이렇게 하면 응답 포맷을 바꿔도 Filter 코드를 건드리지 않는다.
"""
from __future__ import annotations
import logging

from .context import PipelineContext, PortfolioRequest
from .filters import PIPELINE_FILTERS

log = logging.getLogger(__name__)

BANK_RATE_PCT = 3.5


class RecommendationPipeline:
    """
    사용법:
        pipeline = RecommendationPipeline(request)
        result   = pipeline.execute()
    """

    def __init__(self, request: PortfolioRequest) -> None:
        self.ctx = PipelineContext(request=request)
        self.filters = [F() for F in PIPELINE_FILTERS]

    def execute(self) -> dict:
        """필터를 순서대로 실행하고 API 응답 dict 를 반환."""
        for filt in self.filters:
            try:
                log.debug("Pipeline step: %s", filt.name)
                filt.process(self.ctx)
            except Exception as exc:
                log.error("Pipeline step %s failed: %s", filt.name, exc, exc_info=True)
                self.ctx.add_error(filt.name, str(exc))

        return self._to_response()

    # ── 응답 직렬화 ──────────────────────────────────────────────
    def _to_response(self) -> dict:
        ctx  = self.ctx
        req  = ctx.request
        macro = ctx.macro

        return {
            # ── 입력 메타 ───────────────────────────────────────
            "input": {
                "age":            req.age,
                "annual_income":  req.annual_income,
                "monthly_target": req.monthly_target,
                "investable":     req.investable_amount,
                "risk_tolerance": req.risk_tolerance,
                "archetype":      req.archetype,
            },

            # ── 아키타입 ────────────────────────────────────────
            "archetype": {
                "label":        ctx.arch_cfg.get("label", req.archetype),
                "description":  ctx.arch_cfg.get("description", ""),
                "etf_priority": ctx.arch_cfg.get("etf_categories_priority", []),
            },

            # ── 거시 레짐 ───────────────────────────────────────
            "macro_regime": {
                "regime":              macro.get("regime"),
                "label":               macro.get("label"),
                "advisory":            macro.get("advisory"),
                "usd_krw_note":        macro.get("usd_krw_note"),
                "indicators":          macro.get("indicators"),
                "data_source":         macro.get("data_source"),
                "confidence":          macro.get("confidence", 0.0),
                "confidence_label":    macro.get("confidence_label", ""),
                "runner_up":           macro.get("runner_up", ""),
                "runner_up_conf":      macro.get("runner_up_conf", 0.0),
                "regime_scores":       macro.get("regime_scores", {}),
                "indicator_breakdown": macro.get("indicator_breakdown", {}),
                "yield_spread":        macro.get("yield_spread", 0.0),
                "signals":             macro.get("signals", {}),
            },

            # ── 비중 ────────────────────────────────────────────
            "axis_weights": {
                "base":      ctx.base_axis_w,
                "archetype": ctx.arch_axis_w,
                "final":     ctx.axis_w,
            },

            # ── 추천 자산 목록 ──────────────────────────────────
            "recommendations":    ctx.recommendations,
            "axis_summary":       self._axis_summary(),
            "target_yield":       ctx.target_yield,      # 엔진 사용값 (1~20% 클램프)
            "raw_target_yield":   getattr(ctx, "raw_target_yield", None),  # 순수 역산값
            "yield_capped":       getattr(ctx, "yield_capped", False),     # True → 20% 상한 적용

            # ── 데이터 신선도 ────────────────────────────────────
            "data_freshness":   self._data_freshness(),

            # ── 리스크 경보 ──────────────────────────────────────
            "risk_alerts":      ctx.risk_alerts,

            # ── 핵심 현금흐름 요약 ──────────────────────────────
            # 프로젝트 정체성: "AI 현금흐름 운영체제"
            # 사용자가 가장 먼저 봐야 할 숫자들
            "summary": {
                "cashflow_os": {
                    "headline": f"월 {ctx.total_monthly_net:.1f}만원 실수령 배당",
                    "achievement_pct": ctx.achievement,
                    "vs_bank_pct":     ctx.vs_bank,
                    "annual_net_만원": round(ctx.total_annual_net, 1),
                    "milestone": self._cashflow_milestone(),
                },
                "investable_amount_만원":          req.investable_amount,
                "total_stocks":                    len(ctx.recommendations),
                "avg_dividend_yield":              ctx.avg_yield,
                "avg_capital_gain_rate":           ctx.avg_cap_gain,
                "avg_total_return_pct":            ctx.avg_total_return,
                "est_annual_div_만원":             round(ctx.total_annual, 1),
                "est_monthly_div_만원":            ctx.total_monthly,
                "avg_dividend_yield_net":          ctx.avg_yield_net,
                "avg_total_return_net":            ctx.avg_total_return_net,
                "est_annual_div_after_tax_만원":   round(ctx.total_annual_net, 1),
                "est_monthly_div_after_tax_만원":  ctx.total_monthly_net,
                "target_achievement_pct":          ctx.achievement,
                "needed_investment_만원":          ctx.needed_inv,
                "vs_bank_rate_pct":                ctx.vs_bank,
                "bank_rate_pct":                   BANK_RATE_PCT,
                "monthly_pay_weight_pct":          ctx.monthly_pay_weight,
                "risk_count":                      len(ctx.risk_alerts),
            },

            # ── 분석 결과 ───────────────────────────────────────
            "projection":        ctx.projection,
            "living_coverage":   ctx.living_coverage,
            "portfolio_health":  ctx.health,
            "rebalancing_plan":  ctx.rebalancing_plan,
            "stress_test":       ctx.stress,
            "fx_stress":         ctx.fx_stress,
            "sector_exposure":   ctx.sector_exposure,
            "dividend_calendar": ctx.dividend_calendar,
            "fire_plan":         ctx.fire_plan,
            "reverse_fire":      ctx.reverse_fire,   # Reverse FIRE 역산 결과 (optional)
            "monte_carlo":       ctx.monte_carlo,
            "survival":          ctx.survival,
            "tax_optimizer":     ctx.tax_optimizer_result,
            "behavioral_finance":ctx.behavioral,
            "yield_traps":       ctx.yield_traps,
            "storytelling":      ctx.storytelling,
            "isa_strategy":      ctx.isa,

            # ── 리밸런싱 팁 ──────────────────────────────────────
            "rebalancing_tip": (
                f"{'분기 1회' if req.risk_tolerance == 'aggressive' else '반기 1회'} 리밸런싱 권장. "
                "배당삭감 신호 포착 또는 세후 Total Return이 은행 금리 이하로 하락 시 즉시 교체 검토. "
                f"현재 시장: {macro.get('label', '')}."
            ),

            # ── 파이프라인 상태 ──────────────────────────────────
            "pipeline_errors": ctx.errors,
        }

    def _cashflow_milestone(self) -> str:
        """월 배당금이 어느 생활비 마일스톤에 해당하는지 반환."""
        m = self.ctx.total_monthly_net
        if m >= 500: return "경제적 자유 달성 수준"
        if m >= 300: return "생활비 100% 커버 가능"
        if m >= 150: return "주거비 + 식비 커버 가능"
        if m >= 80:  return "통신비·교통비 커버 가능"
        if m >= 30:  return "커피·구독료 커버 가능"
        return "배당 현금흐름 시작 단계"

    def _axis_summary(self) -> list:
        """
        프론트엔드 (Portfolio.jsx) 가 기대하는 풍부한 구조로 반환.
        필드: asset_class, label, weight_pct, avg_div_yield, avg_total_return, count

        라이트 버전(weight/tickers)을 쓰던 회귀 버그 픽스 (Day 4).
        """
        agg: dict[str, dict] = {}
        for r in self.ctx.recommendations:
            cls = r.get("asset_class") or r.get("axis") or "기타"
            if cls not in agg:
                agg[cls] = {
                    "label":   r.get("asset_class_label", cls),
                    "pct":     0.0,
                    "dyields": [],
                    "tr":      [],
                    "count":   0,
                    "tickers": [],
                }
            agg[cls]["pct"]     += float(r.get("weight_pct", 0) or 0)
            dy = r.get("dividend_yield", r.get("expected_yield"))
            if dy is not None:
                try:
                    agg[cls]["dyields"].append(float(dy))
                except (TypeError, ValueError):
                    pass
            tr = r.get("total_return_pct", r.get("expected_total_return"))
            if tr is not None:
                try:
                    agg[cls]["tr"].append(float(tr))
                except (TypeError, ValueError):
                    pass
            agg[cls]["count"]   += 1
            agg[cls]["tickers"].append(r.get("ticker", ""))

        result = []
        for cls, d in agg.items():
            if d["count"] == 0:
                continue
            avg_dy = round(sum(d["dyields"]) / len(d["dyields"]), 2) if d["dyields"] else 0.0
            avg_tr = round(sum(d["tr"])      / len(d["tr"]),      2) if d["tr"]      else 0.0
            result.append({
                "asset_class":      cls,
                "axis":             cls,                 # 하위 호환
                "label":            d["label"],
                "weight_pct":       round(d["pct"], 1),
                "weight":           round(d["pct"], 1),  # 하위 호환
                "avg_div_yield":    avg_dy,
                "avg_total_return": avg_tr,
                "count":            d["count"],
                "tickers":          d["tickers"],
            })
        # 비중 큰 순으로 정렬
        result.sort(key=lambda x: -x["weight_pct"])
        return result

    def _data_freshness(self) -> dict:
        import os
        from datetime import datetime
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        def mtime(p):
            try: return datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d")
            except: return "unknown"
        return {
            "kr_stock_ranking": mtime(os.path.join(BASE_DIR, "data", "ranking.csv")),
            "ml_scoring":       mtime(os.path.join(BASE_DIR, "data", "ml_scoring_results.csv")),
            "us_stock_scores":  mtime(os.path.join(BASE_DIR, "data", "us_stock_scores.csv")),
            "etf_quality":      mtime(os.path.join(BASE_DIR, "data", "etf_quality_cache.json")),
        }

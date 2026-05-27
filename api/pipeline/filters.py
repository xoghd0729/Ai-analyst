"""
Pipeline Filters
────────────────
19단계 포트폴리오 파이프라인의 각 단계를 독립 Filter 클래스로 구현.

왜 Filter로 분리하는가?
  기존 portfolio.py 에서는 하나의 함수에 모든 단계가 순차 나열되어 있어
  1,960줄짜리 God Function 이 되었다.
  각 단계를 Filter 클래스로 분리하면:
    1. 단위 테스트 가능 (각 Filter 를 독립적으로 테스트)
    2. 단계 순서 변경/추가/삭제가 runner.py 한 줄 수정으로 끝남
    3. 각 Filter 가 어떤 ctx 필드를 read/write 하는지 명확
"""
from __future__ import annotations

import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from .base import BaseFilter
from .context import PipelineContext

BANK_RATE_PCT = 3.5


# ═══════════════════════════════════════════════════════════════
# Filter 1 — 5축 비중 계산
# ═══════════════════════════════════════════════════════════════
class AxisWeightFilter(BaseFilter):
    """
    나이 + 성향 → 5축 기본 비중 계산.
    아키타입 override → Macro override 순으로 적용.
    """
    name = "AxisWeight"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.universe import get_axis_weights, fetch_etf_yields
            from api.routers.portfolio import apply_archetype_weights, ARCHETYPE_CONFIG
            from utils.macro_regime import apply_macro_to_weights

            req = ctx.request
            ctx.etf_yields   = fetch_etf_yields()
            ctx.base_axis_w  = get_axis_weights(req.age, req.risk_tolerance)
            ctx.arch_axis_w  = apply_archetype_weights(ctx.base_axis_w, req.archetype)
            ctx.axis_w       = apply_macro_to_weights(ctx.arch_axis_w, ctx.macro) if ctx.macro else ctx.arch_axis_w
            ctx.arch_cfg     = ARCHETYPE_CONFIG.get(req.archetype, ARCHETYPE_CONFIG["혼합형"])
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 2 — 거시경제 레짐 감지
# ═══════════════════════════════════════════════════════════════
class MacroRegimeFilter(BaseFilter):
    """
    5개 거시 지표(금리·인플레·PMI·신용스프레드·환율)를 분석해
    5가지 레짐 중 하나를 선택. confidence score 포함.
    이 결과는 이후 AxisWeight, MonteCarloFilter 에서 활용된다.
    """
    name = "MacroRegime"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.macro_regime import get_macro_regime
            ctx.macro = get_macro_regime()
        except Exception as e:
            ctx.add_error(self.name, str(e))
            ctx.macro = {"regime": "안정성장기", "label": "🟢 안정성장기", "advisory": "",
                         "indicators": {}, "data_source": "fallback", "confidence": 0.5}


# ═══════════════════════════════════════════════════════════════
# Filter 3 — 자산 선별 (KR주식 + US주식 + ETF)
# ═══════════════════════════════════════════════════════════════
class AssetPickerFilter(BaseFilter):
    """
    5축 비중과 아키타입에 따라 편입 자산을 선별.
      - KR 배당주: ranking.csv 기반 ML 스코어 필터링
      - US 배당주: S&P 배당귀족 기반 점수 정렬
      - ETF:       아키타입별 카테고리 우선순위 적용
    """
    name = "AssetPicker"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from api.routers.portfolio import pick_kr_stocks, pick_us_stocks, pick_etfs
            req = ctx.request
            kr_count      = 7 if req.risk_tolerance == "conservative" else 5
            ctx.kr_stocks = pick_kr_stocks(req.risk_tolerance, kr_count)
            ctx.us_stocks = pick_us_stocks(req.risk_tolerance, ctx.etf_yields, n=4)
            ctx.etfs      = pick_etfs(req.risk_tolerance, ctx.etf_yields,
                                      archetype=req.archetype, macro_regime=ctx.macro)
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 4 — 비중 배분 + 세후 수익률 + 추천이유
# ═══════════════════════════════════════════════════════════════
class WeightAllocatorFilter(BaseFilter):
    """
    선별된 자산에 5축 비중을 배분하고
    자산 유형별 세후 수익률 및 추천이유를 첨부.
    """
    name = "WeightAllocator"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from api.routers.portfolio import assign_weights
            req = ctx.request
            ctx.recommendations = assign_weights(
                ctx.kr_stocks, ctx.us_stocks, ctx.etfs, ctx.axis_w,
                req.investable_amount, req.monthly_target,
                annual_income=req.annual_income,
                archetype=req.archetype,
                req_age=req.age,
                req_risk=req.risk_tolerance,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 5 — 포트폴리오 요약 수치
# ═══════════════════════════════════════════════════════════════
class SummarizeFilter(BaseFilter):
    """
    세전/세후 연간·월간 배당금, 평균 수익률, 은행 대비 초과수익 등
    포트폴리오 핵심 지표를 계산.
    """
    name = "Summarize"

    def process(self, ctx: PipelineContext) -> None:
        try:
            req  = ctx.request
            recs = ctx.recommendations
            ctx.total_annual     = sum(r["est_annual_div_만원"] for r in recs)
            ctx.total_annual_net = sum(r["est_annual_div_after_tax"] for r in recs)
            ctx.total_monthly    = round(ctx.total_annual / 12, 2)
            ctx.total_monthly_net= round(ctx.total_annual_net / 12, 2)
            inv = req.investable_amount or 1
            ctx.avg_yield        = round(ctx.total_annual / inv * 100, 2)
            ctx.avg_yield_net    = round(ctx.total_annual_net / inv * 100, 2)
            ctx.avg_cap_gain     = round(
                sum(r["capital_gain_rate"] * r["weight_pct"] for r in recs) / 100, 2)
            ctx.avg_total_return     = round(ctx.avg_yield + ctx.avg_cap_gain, 2)
            ctx.avg_total_return_net = round(ctx.avg_yield_net + ctx.avg_cap_gain, 2)
            ctx.vs_bank              = round(ctx.avg_total_return_net - BANK_RATE_PCT, 2)
            ctx.achievement          = round(ctx.total_monthly_net / req.monthly_target * 100, 1) if req.monthly_target else 0
            ctx.needed_inv           = round(req.monthly_target * 12 / (ctx.avg_yield_net / 100)) if ctx.avg_yield_net else 0
            ctx.monthly_pay_weight   = round(sum(r["weight_pct"] for r in recs if r.get("monthly_pay")), 1)
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 6 — 배당 성장 시뮬레이션 (20년)
# ═══════════════════════════════════════════════════════════════
class ProjectionFilter(BaseFilter):
    """
    포트폴리오의 20년 배당 성장 시뮬레이션과 생활비 커버율 계산.
    CAGR, 배당 vs CPI, FIRE 달성 예상 시점 등을 반환.
    """
    name = "Projection"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.dividend_projection import simulate_portfolio, calc_living_coverage
            req = ctx.request
            ctx.projection = simulate_portfolio(
                recommendations=ctx.recommendations,
                investable_amount=req.investable_amount,
                years=20, reinvest=False,
                monthly_target=float(req.monthly_target),
            )
            ctx.living_coverage = calc_living_coverage(
                monthly_div_net=ctx.total_monthly_net,
                projection=ctx.projection,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 7 — 동적 리밸런싱 제안
# ═══════════════════════════════════════════════════════════════
class RebalancingFilter(BaseFilter):
    """
    거시 레짐 + 현재 비중 편차를 기반으로
    리밸런싱 액션 플랜을 생성.
    """
    name = "Rebalancing"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.rebalancer import generate_rebalancing_plan
            ctx.rebalancing_plan = generate_rebalancing_plan(
                current_recs=ctx.recommendations,
                target_axis_w=ctx.axis_w,
                macro_regime=ctx.macro,
                investable_amount=ctx.request.investable_amount,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 8 — 스트레스 테스트 (시나리오 + FX)
# ═══════════════════════════════════════════════════════════════
class StressTestFilter(BaseFilter):
    """
    금융위기·금리충격·배당컷 등 4가지 시나리오 스트레스 테스트.
    FX 충격(원달러 ±15%) 포트폴리오 영향 별도 산출.
    """
    name = "StressTest"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.stress_test import run_stress_test, run_fx_stress_test
            ctx.stress    = run_stress_test(ctx.recommendations, ctx.request.investable_amount)
            ctx.fx_stress = run_fx_stress_test(
                ctx.recommendations, ctx.request.investable_amount,
                base_usd_krw=float(ctx.macro.get("indicators", {}).get("usd_krw", 1380)),
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 9 — 섹터 익스포저 분석
# ═══════════════════════════════════════════════════════════════
class SectorExposureFilter(BaseFilter):
    """
    포트폴리오의 섹터별 집중도를 분석.
    금융·IT·에너지 등 섹터 편중 리스크 산출.
    """
    name = "SectorExposure"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from api.routers.portfolio import _calc_sector_exposure
            ctx.sector_exposure = _calc_sector_exposure(ctx.recommendations)
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 10 — 배당 캘린더
# ═══════════════════════════════════════════════════════════════
class CalendarFilter(BaseFilter):
    """
    종목별 배당 지급월 데이터를 기반으로
    월별 예상 배당금 캘린더를 생성.
    배당 공백 월(dry month) 탐지 포함.
    """
    name = "Calendar"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.dividend_calendar import build_dividend_calendar
            ctx.dividend_calendar = build_dividend_calendar(
                ctx.recommendations, ctx.request.investable_amount)
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 11 — ISA 전략 + ML 리스크 경보
# ═══════════════════════════════════════════════════════════════
class RiskAlertFilter(BaseFilter):
    """
    XGBoost 배당 삭감 예측 모델 기반 리스크 경보 생성.
    ISA 절세 전략 산출.
    """
    name = "RiskAlert"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from api.routers.portfolio import get_isa_strategy, _build_risk_alerts
            ctx.isa         = get_isa_strategy(ctx.request.annual_income, ctx.request.investable_amount)
            ctx.risk_alerts = _build_risk_alerts(ctx.recommendations)
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 12 — FIRE 역산 엔진
# ═══════════════════════════════════════════════════════════════
class FireEngineFilter(BaseFilter):
    """
    PMT 역산 공식으로 Lean/Normal/Fat FIRE 달성 시나리오 계산.
    현재 포트폴리오 배당 성장률을 기반으로 은퇴 연령 예측.
    """
    name = "FireEngine"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.fire_engine import calc_fire_engine
            req = ctx.request
            ctx.fire_plan = calc_fire_engine(
                current_investable  = req.investable_amount,
                monthly_savings     = req.monthly_savings,
                current_age         = req.age,
                target_age          = req.target_fire_age,
                avg_net_yield       = ctx.avg_yield_net,
                div_growth_rate     = ctx.projection.get("portfolio_div_cagr", 4.0),
                cpi_rate            = 2.5,
                custom_monthly_만원 = float(req.monthly_target),
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 13 — Monte Carlo 시뮬레이션 (거시 레짐 연동)
# ═══════════════════════════════════════════════════════════════
class MonteCarloFilter(BaseFilter):
    """
    1,000회 Monte Carlo YoC 시뮬레이션.
    핵심 개선: 거시경제 레짐(MacroRegimeFilter 결과)을 전달해
    배당 삭감 확률을 동적으로 조정.
      안정성장기: p_cut × 0.7
      금리상승기: p_cut × 1.3
      경기침체기: p_cut × 1.8
    → 같은 포트폴리오라도 경기 상황에 따라 다른 리스크 경고를 출력.
    """
    name = "MonteCarlo"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.monte_carlo import run_monte_carlo
            ctx.monte_carlo = run_monte_carlo(
                recommendations   = ctx.recommendations,
                investable_amount = ctx.request.investable_amount,
                years             = 20,
                n_simulations     = 1000,
                monthly_target    = float(ctx.request.monthly_target),
                macro_regime      = ctx.macro,          # ← 거시 레짐 연동 (신규)
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 14 — 세금 최적화 엔진 (2026 세법 적용)
# ═══════════════════════════════════════════════════════════════
class TaxOptimizerFilter(BaseFilter):
    """
    금융소득종합과세·ISA·연금저축 세금 최적화.
    2026년 개정 세법 적용:
      - ISA 납입한도: 연 4,000만원 / 총 2억원
      - ISA 비과세 한도: 일반형 500만원 / 청년형 1,000만원
    """
    name = "TaxOptimizer"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.tax_optimizer import calc_tax_optimizer
            req = ctx.request
            is_youth_isa = req.age <= 34 or req.annual_income <= 3_600
            ctx.tax_optimizer_result = calc_tax_optimizer(
                recommendations      = ctx.recommendations,
                investable_amount    = req.investable_amount,
                annual_income_만원   = req.annual_income,
                current_age          = req.age,
                div_cagr             = ctx.projection.get("portfolio_div_cagr", 5.0) or 5.0,
                isa_already_used_만원= 0,
                has_pension_savings  = False,
                has_irp              = False,
                is_youth_isa         = is_youth_isa,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 15 — 행동편향 진단
# ═══════════════════════════════════════════════════════════════
class BehavioralFinanceFilter(BaseFilter):
    """
    8가지 투자 행동편향 탐지.
    홈바이어스·집중편향·최신성편향·배당앵커링·손실회피
    ·수익률환상·과도한안전추구·분산부족.
    """
    name = "BehavioralFinance"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.behavioral_finance import detect_behavioral_biases
            ctx.behavioral = detect_behavioral_biases(
                recommendations = ctx.recommendations,
                risk_alerts     = ctx.risk_alerts,
                summary         = {"avg_yield": ctx.avg_yield, "avg_yield_net": ctx.avg_yield_net},
                investor_age    = ctx.request.age,
                risk_tolerance  = ctx.request.risk_tolerance,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 16 — Yield Trap 감지
# ═══════════════════════════════════════════════════════════════
class YieldTrapFilter(BaseFilter):
    """
    배당 함정(Yield Trap) 자동 감지.
    고배당이더라도 주가 하락/배당 지속성 취약/ML BROKEN이면 경고를 생성한다.
    """
    name = "YieldTrap"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.yield_trap_detector import detect_yield_traps
            ctx.yield_traps = detect_yield_traps(ctx.recommendations)
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 17 — Portfolio Health Score (6축)
# ═══════════════════════════════════════════════════════════════
class PortfolioHealthFilter(BaseFilter):
    """
    배당 캘린더·Monte Carlo 결과를 반영한 6축 건강도 스코어.
    stability / growth / cashflow / cashflow_smooth
    inflation_defense / tax_efficiency / diversification
    """
    name = "PortfolioHealth"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from api.routers.portfolio import calc_portfolio_health
            ctx.health = calc_portfolio_health(
                ctx.recommendations,
                projection        = ctx.projection,
                dividend_calendar = ctx.dividend_calendar,
                monte_carlo       = ctx.monte_carlo,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 18 — 서술형 스토리텔링
# ═══════════════════════════════════════════════════════════════
class StorytellingFilter(BaseFilter):
    """
    분석 결과 전체를 한국어 서술형 리포트로 변환.
    Level 2 스토리텔링:
      intro → portfolio → risk(MC+행동편향) → action(FIRE+세금)
    """
    name = "Storytelling"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.storytelling import generate_storytelling
            req = ctx.request
            ctx.storytelling = generate_storytelling(
                input_data   = {
                    "age": req.age, "risk_tolerance": req.risk_tolerance,
                    "investable": req.investable_amount, "monthly_target": req.monthly_target,
                },
                recommendations  = ctx.recommendations,
                summary          = {
                    "investable_amount_만원":          req.investable_amount,
                    "avg_yield":                       ctx.avg_yield,
                    "avg_yield_net":                   ctx.avg_yield_net,
                    "total_annual_net":                ctx.total_annual_net,
                    "est_monthly_div_after_tax_만원":  ctx.total_monthly_net,
                },
                projection       = ctx.projection,
                living_coverage  = ctx.living_coverage,
                stress_test      = ctx.stress,
                dividend_calendar= ctx.dividend_calendar,
                sector_exposure  = ctx.sector_exposure,
                macro_regime     = ctx.macro,
                risk_alerts      = ctx.risk_alerts,
                archetype        = req.archetype,
                fire_plan        = ctx.fire_plan,
                monte_carlo      = ctx.monte_carlo,
                behavioral       = ctx.behavioral,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))
            ctx.storytelling = ""


# ═══════════════════════════════════════════════════════════════
# Filter 순서 정의 (runner.py 에서 import)
# ═══════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════
# Filter 18 — SHAP 설명 가능성
# ═══════════════════════════════════════════════════════════════
class SHAPExplainerFilter(BaseFilter):
    """
    ML 위험 종목(WEAKENING/BROKEN)에 대해 SHAP 기반 판단 근거 생성.
    "배당성향 92%가 위험도를 +0.34 올렸다" 형태로 블랙박스 해제.
    context.recommendations 의 각 종목에 shap_explanation 키 추가.
    """
    name = "SHAPExplainer"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.shap_explainer import explain_portfolio_risks
            shap_results = explain_portfolio_risks(ctx.recommendations)
            shap_map = {r["ticker"]: r.get("explanation") for r in shap_results}
            # recommendations 에 explanation 첨부
            for rec in ctx.recommendations:
                ticker = rec.get("ticker", "")
                if ticker in shap_map and shap_map[ticker]:
                    rec["shap_explanation"] = shap_map[ticker]
        except Exception as e:
            ctx.add_error(self.name, str(e))


PIPELINE_FILTERS: list[type[BaseFilter]] = [
    MacroRegimeFilter,       # 2. 거시 레짐 (AxisWeight 보다 먼저 — axis_w 에 반영)
    AxisWeightFilter,        # 1. 5축 비중
    AssetPickerFilter,       # 3. 자산 선별
    WeightAllocatorFilter,   # 4. 비중 배분
    SummarizeFilter,         # 5. 수치 요약
    ProjectionFilter,        # 6. 성장 시뮬레이션
    RebalancingFilter,       # 7. 리밸런싱
    StressTestFilter,        # 8. 스트레스 테스트
    SectorExposureFilter,    # 9. 섹터 분석
    CalendarFilter,          # 10. 배당 캘린더
    RiskAlertFilter,         # 11. ISA + 리스크 경보
    FireEngineFilter,        # 12. FIRE 역산
    MonteCarloFilter,        # 13. Monte Carlo (Macro 연동)
    TaxOptimizerFilter,      # 14. 세금 최적화 (2026)
    BehavioralFinanceFilter, # 15. 행동편향
    YieldTrapFilter,         # 16. Yield Trap 감지
    PortfolioHealthFilter,   # 17. Health Score
    SHAPExplainerFilter,     # 18. SHAP 설명 (ML 위험 종목)
    StorytellingFilter,      # 19. 스토리텔링
]

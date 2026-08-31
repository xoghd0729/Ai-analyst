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
            from utils.us_dividend_data import pick_us_stocks_v2
            req = ctx.request
            age = int(getattr(req, "age", 35) or 35)
            # 후보풀 크기: PersonalizedRankingFilter가 최종 선택 → 여기서는 넉넉히
            # KR: 최종 2~3개 × 3 = 6~9개 후보, US: 10개 후보 (85개 유니버스에서)
            if req.risk_tolerance == "conservative":
                kr_count, us_cand = 9, 10
            elif req.risk_tolerance == "aggressive":
                kr_count, us_cand = 6, 10
            else:
                kr_count, us_cand = 9, 10
            ctx.kr_stocks = pick_kr_stocks(req.risk_tolerance, kr_count, age=age)
            # Cold Start 플래그 부착: 데이터 3년 미만 → ml_status="NO_DATA", sector_score 대체
            try:
                from utils.cold_start import apply_cold_start_flags
                ctx.kr_stocks = apply_cold_start_flags(ctx.kr_stocks)
            except Exception:
                pass
            # yfinance 기반 US 배당주 (7일 캐시, 85개 유니버스) — 실패 시 CSV 방식 폴백
            try:
                ctx.us_stocks = pick_us_stocks_v2(req.risk_tolerance, n=us_cand, age=age)
            except Exception:
                ctx.us_stocks = pick_us_stocks(req.risk_tolerance, ctx.etf_yields, n=3)
            # ETF: 후보 전체 전달 → PersonalizedRankingFilter가 n_etfs=2 선택
            # pick_etfs는 모든 ETF 후보 반환 (상위 8개), 우선순위 정렬만 여기서
            all_etfs = pick_etfs(req.risk_tolerance, ctx.etf_yields,
                                 archetype=req.archetype, macro_regime=ctx.macro)
            _priority = lambda e: (
                0 if e.get("asset_class") == "us_div_etf" else
                1 if e.get("asset_class") in ("us_reit", "kr_reit") else
                2 if e.get("asset_class") == "defensive" else 3
            )
            # 전체 후보 유지 (최대 8개) — 최종 2개는 PersonalizedRankingFilter에서 선택
            ctx.etfs = sorted(all_etfs, key=_priority)[:8]
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 3-b — 개인화 랭킹 (Risk Engine + 목표수익률 역산)
# ═══════════════════════════════════════════════════════════════
class PersonalizedRankingFilter(BaseFilter):
    """
    AssetPickerFilter가 구성한 KR/US/ETF 후보군을 개인화 점수로 재정렬 (E_v2).
      - risk_engine  : composite_risk_score 계산 후 BLOCK 제거
      - ranker v2    : abs_yield_fit_v2 + risk + growth + age (horizon 기반 동적 가중치)
      - sector 2층   : 동일 세분화 섹터 max 1개 + 동일 상위 그룹 max 2개
    WeightAllocatorFilter 이전에 실행되어 ctx.kr_stocks / ctx.us_stocks 순서를 확정.
    """
    name = "PersonalizedRanking"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.personalized_ranker import pick_personalized_portfolio
            req = ctx.request
            n_stocks = 4 if req.risk_tolerance == "moderate" else 3
            result = pick_personalized_portfolio(
                kr_candidates    = list(ctx.kr_stocks or []),
                us_candidates    = list(ctx.us_stocks or []),
                etf_candidates   = list(ctx.etfs or []),
                age              = int(getattr(req, "age", 40) or 40),
                investable_amount= float(req.investable_amount or 0),
                monthly_target   = float(req.monthly_target or 0),
                risk_tolerance   = req.risk_tolerance,
                macro            = ctx.macro,
                n_stocks         = n_stocks,
                n_etfs           = 2,
                target_fire_age  = int(getattr(req, "target_fire_age", 65) or 65),
            )
            # 재정렬 결과 반영 (ETF는 별도 슬롯 유지)
            # 중요: ranker가 선택한 결과로 교체 (빈 경우 명시적으로 빈 리스트)
            # fallback "or ctx.xxx" 금지 — 안 쓰면 원래 후보 전체가 넘어가는 버그
            all_stocks       = result["stocks"]
            ctx.kr_stocks        = [s for s in all_stocks if s.get("asset_class") == "kr_stock"]
            ctx.us_stocks        = [s for s in all_stocks if s.get("asset_class") not in ("kr_stock",)]
            ctx.etfs             = result["etfs"] if result["etfs"] else ctx.etfs[:2]
            ctx.target_yield     = result.get("target_yield", 0)
            ctx.raw_target_yield = result.get("raw_target_yield")   # 클램프 이전 순수 역산값
            ctx.yield_capped     = result.get("yield_capped", False) # 20% 상한 적용 여부
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

            # ── fit_score 기반 비중 차별화 ─────────────────────────
            # PersonalizedRankingFilter가 부여한 fit_score(0-100)를 비중에 반영.
            # 같은 자산군 내에서 fit 높은 종목에 더 큰 비중, 낮은 종목에 작은 비중.
            # fit=0 → 0.70x, fit=50 → 1.00x, fit=100 → 1.30x (±30% 범위)
            recs = ctx.recommendations
            has_fit = recs and any(r.get("fit_score") is not None for r in recs)
            if has_fit and len(recs) > 1:
                # 자산군(KR/US/ETF)별로 그룹화해 그룹 총비중은 보존
                from collections import defaultdict
                groups = defaultdict(list)
                for r in recs:
                    ac = r.get("asset_class", "")
                    g = "kr" if ac == "kr_stock" else ("us" if "us" in ac else "etf")
                    groups[g].append(r)

                for grp in groups.values():
                    if len(grp) <= 1:
                        continue
                    total_before = sum(r["weight_pct"] for r in grp) or 1.0
                    for r in grp:
                        fs = float(r.get("fit_score") or 50)
                        r["weight_pct"] *= (0.70 + fs * 0.006)  # 0.70~1.30x
                    total_after = sum(r["weight_pct"] for r in grp) or 1.0
                    scale = total_before / total_after
                    for r in grp:
                        r["weight_pct"] = round(r["weight_pct"] * scale, 2)

                # 전체 재정규화 (소수점 오차 보정)
                total = sum(r["weight_pct"] for r in recs) or 100.0
                for r in recs:
                    r["weight_pct"] = round(r["weight_pct"] / total * 100, 2)
                ctx.recommendations = recs

        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 4-b — Survival Score → 가중치 보정
# ═══════════════════════════════════════════════════════════════
class SurvivalWeightFilter(BaseFilter):
    """
    TabPFN 생존 스코어를 포트폴리오 비중에 직접 반영.

    로직:
      multiplier = 1.0 - 0.4 * hazard_pct
        → hazard=0.0 : multiplier=1.00 (변화 없음)
        → hazard=0.5 : multiplier=0.80 (20% 감소)
        → hazard=0.65: multiplier=0.74 (gate 직전 최대 26% 감소)

    KR 주식만 보정 (US/ETF는 survival 모델 미적용).
    보정 후 전체 합계가 100%가 되도록 재정규화.
    보정값은 recommendation에 'survival_weight_adj' 필드로 기록.
    """
    name = "SurvivalWeight"

    def process(self, ctx: PipelineContext) -> None:
        try:
            import os, json
            BASE = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))
            sv_path = os.path.join(BASE, "results", "survival_pd_v4.json")
            if not os.path.exists(sv_path):
                return
            with open(sv_path) as f:
                sv = json.load(f)
            stock_risk = sv.get("stock_risk", {})
            if not stock_risk or not ctx.recommendations:
                return

            recs = ctx.recommendations
            for r in recs:
                ticker = str(r.get("ticker", "") or r.get("stock_code", ""))
                if r.get("asset_class") == "kr_stock" and ticker in stock_risk:
                    hz = float(stock_risk[ticker].get("hazard_pct", 0.3))
                    multiplier = round(1.0 - 0.4 * hz, 4)
                    r["weight_pct"] = round(r.get("weight_pct", 0) * multiplier, 2)
                    r["survival_risk_score"] = round(hz, 4)   # uncalibrated score (≠ 확률)
                    r["survival_weight_adj"] = round(multiplier, 4)
                    r["survival_1y"] = stock_risk[ticker].get("survival_1y", None)
                else:
                    r["survival_hazard"] = None
                    r["survival_weight_adj"] = 1.0

            # 재정규화 → 합계 100%
            total = sum(r.get("weight_pct", 0) for r in recs) or 100.0
            for r in recs:
                r["weight_pct"] = round(r.get("weight_pct", 0) / total * 100, 2)

            # invest_amount_만원 재계산
            investable = ctx.request.investable_amount
            for r in recs:
                r["invest_amount_만원"] = round(investable * r["weight_pct"] / 100)

        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 4-c — Risk Engine: composite_risk_score 부착
# ═══════════════════════════════════════════════════════════════
class RiskEngineFilter(BaseFilter):
    """
    SurvivalWeightFilter 이후 recommendations 전체에
    composite_risk_score / risk_gate / layer1_xgb / layer2_survival 부착.

    근거: walk-forward 앙상블 실험 (risk_ensemble_comparison.py)
      XGB 70% + Survival 30% = ROC 0.7824, P@20 0.9509 (최적)
      Macro composite 제외 (성능 저하 확인, ROC 0.7727)
    """
    name = "RiskEngine"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.risk_engine import score_portfolio
            ctx.recommendations = score_portfolio(
                ctx.recommendations,
                macro=ctx.macro,
                risk_tolerance=ctx.request.risk_tolerance,
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
                annual_savings_growth = req.savings_growth,   # 적립 증액 반영 (프론트와 통일)
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
                macro_regime      = ctx.macro,
                monthly_savings   = float(ctx.request.monthly_savings),  # ← 적립 복리 반영
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))


# ═══════════════════════════════════════════════════════════════
# Filter 13-b — 포트폴리오 생존확률 (ML + 상관충격 통합 헤드라인)
# ═══════════════════════════════════════════════════════════════
class SurvivalFilter(BaseFilter):
    """
    흩어진 ML(P_BROKEN/P_WEAKENING)·Monte Carlo·집중도를 '생존확률' 단일
    지표로 통합. 종목별 ML 확률로 배당컷 해저드를 구동하고, 섹터·국가
    공통충격으로 상관 배당컷을 반영해 '겉은 분산, 실제는 집중'을 드러낸다.
    "20년간 목표 월배당 유지 확률 84%" 형태의 헤드라인 숫자 생성.
    """
    name = "Survival"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.survival import run_survival, survival_optimal_compare
            ach = None
            if isinstance(ctx.monte_carlo, dict):
                ach = ctx.monte_carlo.get("confidence_at_target")
            ctx.survival = run_survival(
                recommendations  = ctx.recommendations,
                years            = 20,
                n_simulations    = 2000,
                monthly_target   = float(ctx.request.monthly_target),
                macro_regime     = ctx.macro,
                achievement_prob = ach,
            )
            # 현재 vs 분산보정 비교 (표시용 — 실제 배분은 안 바꿈)
            ctx.survival["compare"] = survival_optimal_compare(
                ctx.recommendations,
                monthly_target   = float(ctx.request.monthly_target),
                macro_regime     = ctx.macro,
                achievement_prob = ach,
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
class ReverseFireFilter(BaseFilter):
    """
    FIRE 역산 (Reverse): 현재 조건 → 목표 달성을 위해 무엇을 바꿔야 하는가.

    FireEngineFilter 이후 실행 — fire_plan의 avg_yield_net 재활용.
    실패해도 pipeline 전체에 영향 없음 (ctx.reverse_fire = {} 유지).

    E_v2 계약:
      - target_yield 는 Ranker 점수에 미사용
      - monthly_target / target_fire_age 는 FIRE/Reverse FIRE 쪽으로만 전달
    """
    name = "ReverseFire"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.fire_engine import calc_fire_reverse
            req = ctx.request
            # avg_yield_net: SummarizeFilter 결과 재사용 (포트폴리오 세후 수익률)
            avg_yield_net = ctx.avg_yield_net or 3.5

            ctx.reverse_fire = calc_fire_reverse(
                current_investable  = float(req.investable_amount),
                monthly_savings     = float(req.monthly_savings),
                current_age         = int(req.age),
                target_fire_age     = int(req.target_fire_age),
                target_monthly_만원 = float(req.monthly_target),
                avg_net_yield       = avg_yield_net,
                div_growth_rate     = float(ctx.projection.get("portfolio_div_cagr", 4.0)),
                cpi_rate            = 2.5,
            )
        except Exception as e:
            ctx.add_error(self.name, str(e))
            # reverse_fire는 optional — 실패해도 빈 dict 유지, pipeline 계속


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
# Filter 18 — 위험 요인 분석 (Risk Factor Attribution)
# ═══════════════════════════════════════════════════════════════
class SHAPExplainerFilter(BaseFilter):
    """
    WEAKENING/BROKEN 종목에 대해 위험 요인 attribution 생성.

    [v2 변경사항]
    기존: XGBoost TreeExplainer 기반 SHAP (kr_3class_model.pkl)
    현재: TabPFN Survival hazard score 기반 rule-based feature attribution.
          재무지표가 위험 기준 임계값을 얼마나 벗어나는지를 점수화.
          실제 SHAP(Shapley value)가 아님 — 도메인 지식 기반 attribution.
          XGBoost SHAP은 _explain_xgb_benchmark() 로 benchmark 전용 보존.

    출력 키: rec["risk_attribution"] (WEAKENING/BROKEN만), rec["ml_status"]
    """
    name = "RiskAttribution"

    def process(self, ctx: PipelineContext) -> None:
        try:
            from utils.shap_explainer import explain_portfolio_risks
            shap_results = explain_portfolio_risks(ctx.recommendations)
            result_map = {r["ticker"]: r for r in shap_results}
            for rec in ctx.recommendations:
                ticker = rec.get("ticker", "")
                res = result_map.get(ticker)
                if res is None:
                    continue
                # ml_status: survival hazard 기반 분류로 업데이트
                rec["ml_status"] = res.get("prediction", "INTACT")
                if res.get("hazard") is not None:
                    rec.setdefault("survival_risk_score", res["hazard"])
                if res.get("survival_1y") is not None:
                    rec.setdefault("survival_1y", res["survival_1y"])
                # attribution 첨부 (WEAKENING/BROKEN만)
                if res.get("explanation"):
                    explanation = res["explanation"]
                    rec["risk_attribution"] = explanation
                    # recommendation_reason에 위험 요인 문장 후위 첨부
                    prediction = res.get("prediction", "INTACT")
                    if prediction in ("WEAKENING", "BROKEN"):
                        top_factors = explanation.get("top_factors", [])
                        if top_factors:
                            factor_labels = [f["label_ko"] for f in top_factors[:3]]
                            risk_sentence = (
                                f"⚠️ AI 위험 신호 — {', '.join(factor_labels)} 지표 이상 감지"
                                if prediction == "WEAKENING" else
                                f"🚨 고위험 — {', '.join(factor_labels)} 악화, 비중 최소화"
                            )
                            existing_reason = rec.get("recommendation_reason", "")
                            if existing_reason:
                                rec["recommendation_reason"] = existing_reason + ". " + risk_sentence
                            else:
                                rec["recommendation_reason"] = risk_sentence
        except Exception as e:
            ctx.add_error(self.name, str(e))


PIPELINE_FILTERS: list[type[BaseFilter]] = [
    MacroRegimeFilter,       # 2. 거시 레짐 (AxisWeight 보다 먼저 — axis_w 에 반영)
    AxisWeightFilter,        # 1. 5축 비중
    AssetPickerFilter,          # 3. 자산 선별
    PersonalizedRankingFilter,  # 3-b. 개인화 랭킹 (Risk Engine + 목표수익률)
    WeightAllocatorFilter,      # 4. 비중 배분
    SurvivalWeightFilter,    # 4-b. Survival Score → 가중치 보정
    RiskEngineFilter,        # 4-c. composite_risk_score 부착 (XGB 70%+Survival 30%)
    SummarizeFilter,         # 5. 수치 요약
    ProjectionFilter,        # 6. 성장 시뮬레이션
    RebalancingFilter,       # 7. 리밸런싱
    StressTestFilter,        # 8. 스트레스 테스트
    SectorExposureFilter,    # 9. 섹터 분석
    CalendarFilter,          # 10. 배당 캘린더
    RiskAlertFilter,         # 11. ISA + 리스크 경보
    FireEngineFilter,        # 12. FIRE 역산
    ReverseFireFilter,       # 12-b. FIRE 역산 (Reverse) — optional, 실패해도 pipeline 계속
    MonteCarloFilter,        # 13. Monte Carlo (Macro 연동)
    SurvivalFilter,          # 13-b. 생존확률 (ML+상관충격 통합)
    TaxOptimizerFilter,      # 14. 세금 최적화 (2026)
    BehavioralFinanceFilter, # 15. 행동편향
    YieldTrapFilter,         # 16. Yield Trap 감지
    PortfolioHealthFilter,   # 17. Health Score
    SHAPExplainerFilter,     # 18. Risk Attribution (Survival hazard 기반, SHAP 아님)
    StorytellingFilter,      # 19. 스토리텔링
]

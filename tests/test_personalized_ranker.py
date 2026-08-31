"""
tests/test_personalized_ranker.py
===================================
E_v2 Ranker 핵심 불변조건 단위 테스트.

테스트 원칙:
  - 절대값 고정 X (시장 데이터 변동 허용) — 방향성/불변조건만 검증
  - score_asset() 는 mock — Risk Engine 변화에 독립적
  - 한 클래스 = 한 불변조건 집합

검증 영역:
  1. abs_yield_fit_v2  : 포화 곡선 정확값 고정
  2. _horizon_weights  : 장기/중기/단기 가중치 방향성
  3. Target yield 독립 : target_yield 변경이 fit_score에 영향 없음 (E_v2 핵심)
  4. Sector 제약       : 동일 sector max 1개
  5. Sector group 제약 : 동일 상위 그룹 max 2개 (JB+우리금융 동시 편입 차단)
  6. ETF 자연 선별     : SPYI/JEPQ 하드코딩 배제 아님 — growth_fit이 자연 분리
  7. Risk gate         : BLOCK 종목 제외
  8. Personalization   : 나이/자산 변화 → 동일 후보군에서 순위 달라짐

실행:
  cd ~/ai-analyst && pytest tests/test_personalized_ranker.py -v
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import patch

from utils.personalized_ranker import (
    abs_yield_fit_v2,
    _horizon_weights,
    _calc_target_yield,
    rank_candidates,
    pick_personalized_portfolio,
)


# ── Mock 헬퍼 ───────────────────────────────────────────────────────────────

def _make_risk_mock(scores: dict | None = None, blocked: set | None = None):
    """
    score_asset() 테스트용 mock 팩토리.
    scores  : {ticker: composite_risk_score} — 없으면 20.0 기본값
    blocked : 이 ticker들은 risk_gate=BLOCK 반환
    """
    scores  = scores  or {}
    blocked = blocked or set()

    def _fn(ticker, asset_class, ml_status, survival_hazard, macro, risk_tolerance):
        if ticker in blocked:
            return {"composite_risk_score": 90.0, "risk_gate": "BLOCK",
                    "xgb_score": 0.0, "survival_score": 0.0, "macro_score": 0.0}
        crs = float(scores.get(ticker, 20.0))
        return {"composite_risk_score": crs, "risk_gate": "PASS",
                "xgb_score": 0.0, "survival_score": 0.0, "macro_score": 0.0}
    return _fn


# 기본 mock — 모두 risk=20, PASS
_DEFAULT_MOCK = _make_risk_mock()


def _stock(ticker, yield_pct, dps_pct, sector, sector_group="기타", **kw):
    """테스트용 주식 후보 딕셔너리 생성 헬퍼."""
    return {
        "ticker":        ticker,
        "name":          ticker,
        "asset_class":   kw.get("asset_class", "us_stock"),
        "ml_status":     kw.get("ml_status", "INTACT"),
        "expected_yield": yield_pct,
        "dps_yoy_pct":   dps_pct,
        "sector":        sector,
        "sector_group":  sector_group,
        **{k: v for k, v in kw.items() if k not in ("asset_class", "ml_status")},
    }


def _etf(ticker, yield_pct, div_growth_5y):
    """테스트용 ETF 후보 딕셔너리 생성 헬퍼."""
    return {
        "ticker":        ticker,
        "name":          ticker,
        "asset_class":   "us_div_etf",
        "ml_status":     "INTACT",
        "expected_yield": yield_pct,
        "div_growth_5y": div_growth_5y,
        "sector":        "ETF",
        "sector_group":  "ETF",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. abs_yield_fit_v2 포화 곡선
# ═══════════════════════════════════════════════════════════════════════════

class TestAbsYieldFitV2:
    """포화 곡선 정확값 고정 — 이 값들이 바뀌면 Ranker 전체 calibration이 깨짐."""

    def test_breakpoints_exact(self):
        """브레이크포인트 6개 정확값."""
        assert abs_yield_fit_v2(0)  == 0.0
        assert abs_yield_fit_v2(2)  == 40.0
        assert abs_yield_fit_v2(4)  == 70.0
        assert abs_yield_fit_v2(6)  == 85.0
        assert abs_yield_fit_v2(8)  == 92.0
        assert abs_yield_fit_v2(10) == 95.0

    def test_cap_at_10pct_plus(self):
        """10% 이상은 95.0으로 캡."""
        assert abs_yield_fit_v2(12) == 95.0
        assert abs_yield_fit_v2(20) == 95.0

    def test_midpoint_interpolation(self):
        """구간 내 선형 보간 정확값."""
        # 3%: 2~4 구간 → 40 + (1/2)*(70-40) = 55
        assert abs_yield_fit_v2(3) == 55.0
        # 5%: 4~6 구간 → 70 + (1/2)*(85-70) = 77.5
        assert abs_yield_fit_v2(5) == 77.5
        # 9%: 8~10 구간 → 92 + (1/2)*(95-92) = 93.5
        assert abs_yield_fit_v2(9) == 93.5

    def test_strictly_monotone_increasing(self):
        """수익률 높을수록 점수 증가 (단조증가)."""
        yields = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        scores = [abs_yield_fit_v2(y) for y in yields]
        for i in range(len(scores) - 1):
            assert scores[i] < scores[i + 1], \
                f"단조증가 위반: {yields[i]}% → {yields[i+1]}%"

    def test_negative_yield_returns_zero(self):
        """음수 수익률 → 0."""
        assert abs_yield_fit_v2(-1) == 0.0
        assert abs_yield_fit_v2(-10) == 0.0

    def test_high_yield_capped_same_as_ten(self):
        """12% / 20% 는 10%와 같은 점수 (커버드콜 고yield 과점 방지)."""
        assert abs_yield_fit_v2(12) == abs_yield_fit_v2(10)
        assert abs_yield_fit_v2(20) == abs_yield_fit_v2(10)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Horizon 가중치
# ═══════════════════════════════════════════════════════════════════════════

class TestHorizonWeights:
    """투자 기간별 가중치 방향성."""

    def test_long_horizon_growth_dominant(self):
        """장기(≥20년): growth 가중치가 abs_yield보다 높음."""
        w = _horizon_weights(target_fire_age=50, current_age=25)  # 25년
        assert w["growth"] > w["abs_yield"], \
            f"장기에서 growth({w['growth']}) ≤ abs_yield({w['abs_yield']})"

    def test_short_horizon_yield_dominant(self):
        """단기(<10년): abs_yield 가중치가 growth보다 높음."""
        w = _horizon_weights(target_fire_age=65, current_age=60)  # 5년
        assert w["abs_yield"] > w["growth"], \
            f"단기에서 abs_yield({w['abs_yield']}) ≤ growth({w['growth']})"

    def test_weights_sum_to_one(self):
        """모든 horizon에서 가중치 합 = 1.0."""
        for fire_age, cur_age in [(50, 25), (55, 40), (65, 60)]:
            w = _horizon_weights(fire_age, cur_age)
            total = sum(w.values())
            assert abs(total - 1.0) < 1e-9, \
                f"가중치 합 != 1.0: horizon={fire_age-cur_age}년, sum={total}"

    def test_weights_have_required_keys(self):
        """가중치 딕셔너리에 4개 키 모두 존재."""
        w = _horizon_weights(50, 25)
        assert set(w.keys()) == {"abs_yield", "risk", "growth", "age"}

    def test_risk_weight_consistent(self):
        """risk 가중치는 모든 horizon에서 0.40으로 고정."""
        for fire_age, cur_age in [(50, 25), (55, 40), (65, 60)]:
            w = _horizon_weights(fire_age, cur_age)
            assert w["risk"] == 0.40, \
                f"risk 가중치 변경됨: horizon={fire_age-cur_age}년, risk={w['risk']}"

    def test_boundary_10yr(self):
        """horizon=10년: 중기 가중치 (abs_yield=0.20, growth=0.20)."""
        w = _horizon_weights(target_fire_age=50, current_age=40)  # 10년 정확히
        assert w["abs_yield"] == 0.20
        assert w["growth"] == 0.20

    def test_boundary_20yr(self):
        """horizon=20년: 장기 가중치 (abs_yield=0.15, growth=0.30)."""
        w = _horizon_weights(target_fire_age=50, current_age=30)  # 20년 정확히
        assert w["abs_yield"] == 0.15
        assert w["growth"] == 0.30


# ═══════════════════════════════════════════════════════════════════════════
# 3. Target yield 독립성 (E_v2 핵심 불변조건)
# ═══════════════════════════════════════════════════════════════════════════

class TestTargetYieldIndependence:
    """target_yield 변경이 fit_score에 영향을 주지 않음.

    v1에서 v2로 가장 중요한 변경: Ranker가 target_yield를 점수에 쓰지 않는다.
    이 테스트가 깨지면 target_yield가 Ranker 점수에 재도입된 것.
    """

    @pytest.fixture
    def two_candidates(self):
        return [
            _stock("LOW", 3.0, 5.0, "IT", "IT"),
            _stock("HIGH", 7.0, 3.0, "통신", "통신"),
        ]

    def test_fit_score_unchanged_when_monthly_target_changes(self, two_candidates):
        """월목표 50만 vs 300만 — fit_score 동일."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            result_50  = rank_candidates(two_candidates, age=40,
                                          investable_amount=5000,
                                          monthly_target=50,
                                          risk_tolerance="moderate")
            result_300 = rank_candidates(two_candidates, age=40,
                                          investable_amount=5000,
                                          monthly_target=300,
                                          risk_tolerance="moderate")

        scores_50  = {r["ticker"]: r["fit_score"] for r in result_50}
        scores_300 = {r["ticker"]: r["fit_score"] for r in result_300}

        assert scores_50 == scores_300, \
            f"monthly_target 변경이 fit_score에 영향: {scores_50} vs {scores_300}"

    def test_fit_score_unchanged_when_investable_changes(self, two_candidates):
        """투자금 360만(target_yield 극대) vs 100,000만(target_yield 극소) — fit_score 동일."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            result_small = rank_candidates(two_candidates, age=40,
                                            investable_amount=360,
                                            monthly_target=50,
                                            risk_tolerance="moderate")
            result_large = rank_candidates(two_candidates, age=40,
                                            investable_amount=100_000,
                                            monthly_target=50,
                                            risk_tolerance="moderate")

        scores_small = {r["ticker"]: r["fit_score"] for r in result_small}
        scores_large = {r["ticker"]: r["fit_score"] for r in result_large}

        assert scores_small == scores_large, \
            f"investable 변경이 fit_score에 영향: {scores_small} vs {scores_large}"

    def test_ranking_order_unchanged(self, two_candidates):
        """fit_score 순위도 동일 (target_yield 독립이면 순위도 독립)."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            result_a = rank_candidates(two_candidates, age=40,
                                        investable_amount=360,
                                        monthly_target=5, risk_tolerance="moderate")
            result_b = rank_candidates(two_candidates, age=40,
                                        investable_amount=360,
                                        monthly_target=999, risk_tolerance="moderate")

        order_a = [r["ticker"] for r in result_a]
        order_b = [r["ticker"] for r in result_b]
        assert order_a == order_b, f"순위 달라짐: {order_a} vs {order_b}"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Sector 제약 (세분화 max 1개)
# ═══════════════════════════════════════════════════════════════════════════

class TestSectorConstraint:
    """동일 sector에서 최대 1개만 선택."""

    def _run_pick(self, stocks, n_stocks=4):
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            return pick_personalized_portfolio(
                kr_candidates=stocks, us_candidates=[], etf_candidates=[],
                age=40, investable_amount=5000, monthly_target=100,
                risk_tolerance="moderate", n_stocks=n_stocks, n_etfs=0,
            )

    def test_three_same_sector_only_one_selected(self):
        """같은 sector 3개 후보 → 1개만 선택."""
        stocks = [
            _stock("A", 5.0, 14.0, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("B", 4.5, 13.0, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("C", 4.0,  8.0, "금융_은행", "금융", asset_class="kr_stock"),
        ]
        result = self._run_pick(stocks, n_stocks=3)
        sectors = [s.get("sector") for s in result["stocks"]]
        assert sectors.count("금융_은행") <= 1, \
            f"금융_은행 2개 이상 선택: {[s['ticker'] for s in result['stocks']]}"

    def test_jb_wori_both_bank_only_one_selected(self):
        """JB금융 + 우리금융 (둘 다 금융_은행) → 동시 편입 차단."""
        stocks = [
            _stock("JB",  4.86, 14.6, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("WR",  4.23, 13.3, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("KO",  3.1,   5.0, "소비재(필수)", "소비재"),
        ]
        result = self._run_pick(stocks, n_stocks=3)
        tickers = [s["ticker"] for s in result["stocks"]]
        assert not ("JB" in tickers and "WR" in tickers), \
            f"JB금융+우리금융 동시 편입됨: {tickers}"

    def test_different_sector_both_selected(self):
        """JB금융(금융_은행) + KO(소비재) → 둘 다 선택 가능."""
        stocks = [
            _stock("JB", 4.86, 14.6, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("KO",  3.1,  5.0, "소비재(필수)", "소비재"),
        ]
        result = self._run_pick(stocks, n_stocks=2)
        tickers = set(s["ticker"] for s in result["stocks"])
        assert "JB" in tickers and "KO" in tickers, \
            f"다른 sector인데 하나가 제외됨: {tickers}"

    def test_best_in_sector_selected(self):
        """같은 sector에서 fit_score 1위가 선택됨."""
        # A가 B보다 yield 높아 abs_yield_fit_v2 점수도 높음
        stocks = [
            _stock("A_HIGH", 6.0, 8.0, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("B_LOW",  3.0, 8.0, "금융_은행", "금융", asset_class="kr_stock"),
        ]
        result = self._run_pick(stocks, n_stocks=2)
        tickers = [s["ticker"] for s in result["stocks"]]
        # A가 먼저 선택되고 B는 차단되어야 함
        assert "A_HIGH" in tickers, f"높은 yield 종목이 미선택: {tickers}"
        assert "B_LOW" not in tickers, f"낮은 yield 종목이 선택됨: {tickers}"


# ═══════════════════════════════════════════════════════════════════════════
# 5. Sector group 제약 (상위 그룹 max 2개)
# ═══════════════════════════════════════════════════════════════════════════

class TestSectorGroupConstraint:
    """동일 sector_group에서 최대 2개 (세분화 다르면 허용)."""

    def _run_pick(self, stocks, n_stocks=4):
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            return pick_personalized_portfolio(
                kr_candidates=stocks, us_candidates=[], etf_candidates=[],
                age=40, investable_amount=5000, monthly_target=100,
                risk_tolerance="moderate", n_stocks=n_stocks, n_etfs=0,
            )

    def test_bank_plus_insurance_both_allowed(self):
        """금융_은행 + 금융_보험 → 둘 다 선택 (다른 sector, 같은 금융 그룹)."""
        stocks = [
            _stock("BANK",     4.86, 14.6, "금융_은행",  "금융", asset_class="kr_stock"),
            _stock("INSURE",   4.80, 20.0, "금융_보험",  "금융", asset_class="kr_stock"),
            _stock("OTHER",    3.10,  5.0, "소비재(필수)", "소비재"),
        ]
        result = self._run_pick(stocks, n_stocks=3)
        tickers = {s["ticker"] for s in result["stocks"]}
        # BANK + INSURE 모두 금융 그룹이지만 sector가 달라 허용
        assert "BANK" in tickers and "INSURE" in tickers, \
            f"금융_은행+금융_보험이 동시 선택 안 됨: {tickers}"

    def test_three_finance_subsectors_max_two(self):
        """금융_은행 + 금융_보험 + 금융_증권 = 3개 금융 → 2개만 선택."""
        stocks = [
            _stock("BANK",    5.0, 14.0, "금융_은행",  "금융", asset_class="kr_stock"),
            _stock("INSURE",  4.8, 20.0, "금융_보험",  "금융", asset_class="kr_stock"),
            _stock("SECUR",   3.0, 14.0, "금융_증권",  "금융", asset_class="kr_stock"),
            _stock("OTHER",   3.1,  5.0, "소비재(필수)", "소비재"),
        ]
        result = self._run_pick(stocks, n_stocks=4)
        groups = [s.get("sector_group") for s in result["stocks"]]
        assert groups.count("금융") <= 2, \
            f"금융 그룹 3개 이상: {[s['ticker'] for s in result['stocks']]}"

    def test_two_different_groups_all_allowed(self):
        """금융 그룹 2개 + 에너지 그룹 2개 = 4개 → 모두 선택 가능."""
        stocks = [
            _stock("BANK",  5.0, 14.0, "금융_은행", "금융", asset_class="kr_stock"),
            _stock("INS",   4.8, 20.0, "금융_보험", "금융", asset_class="kr_stock"),
            _stock("XOM",   3.4,  4.0, "에너지",   "에너지"),
            _stock("CVX",   4.1,  4.9, "에너지",   "에너지"),
        ]
        # 에너지에서 두 개 같은 sector → 1개만 선택됨
        # 실제로는 에너지 sector가 같아서 1개만 선택, 금융 2개 + 에너지 1개 = 3개
        result = self._run_pick(stocks, n_stocks=4)
        tickers = {s["ticker"] for s in result["stocks"]}
        # 금융 그룹에서 2개는 선택됨
        finance_tickers = {s["ticker"] for s in result["stocks"]
                           if s.get("sector_group") == "금융"}
        assert len(finance_tickers) == 2, \
            f"금융 그룹 2개 선택 실패: {finance_tickers}"


# ═══════════════════════════════════════════════════════════════════════════
# 6. ETF 자연 선별 (SPYI/JEPQ 하드코딩 배제 없음)
# ═══════════════════════════════════════════════════════════════════════════

class TestETFNaturalSelection:
    """SPYI/JEPQ는 하드코딩으로 제외하지 않는다.
    대신 장기 투자자에게는 growth_fit이 낮아 자연스럽게 순위가 낮아야 한다.
    단기 투자자에게는 고yield로 인해 SPYI가 높게 평가되는 것이 올바름.
    """

    @pytest.fixture
    def schd_vs_spyi(self):
        return [
            _etf("SCHD", yield_pct=3.6, div_growth_5y=10.2),
            _etf("SPYI", yield_pct=12.0, div_growth_5y=0.0),
        ]

    def test_schd_beats_spyi_at_long_horizon(self, schd_vs_spyi):
        """장기(horizon=25년): DPS 성장률 10% SCHD > yield 12% SPYI."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            ranked = rank_candidates(
                schd_vs_spyi, age=25, investable_amount=360,
                monthly_target=50, risk_tolerance="moderate",
                target_fire_age=50,   # horizon=25년
            )
        scores = {r["ticker"]: r["fit_score"] for r in ranked}
        assert scores["SCHD"] > scores["SPYI"], \
            f"장기(25년)에서 SCHD({scores['SCHD']:.1f}) <= SPYI({scores['SPYI']:.1f})"

    def test_spyi_beats_schd_at_short_horizon(self, schd_vs_spyi):
        """단기(horizon=5년): yield 12% SPYI > DPS 성장 10% SCHD."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            ranked = rank_candidates(
                schd_vs_spyi, age=60, investable_amount=30000,
                monthly_target=200, risk_tolerance="conservative",
                target_fire_age=65,   # horizon=5년
            )
        scores = {r["ticker"]: r["fit_score"] for r in ranked}
        assert scores["SPYI"] > scores["SCHD"], \
            f"단기(5년)에서 SPYI({scores['SPYI']:.1f}) <= SCHD({scores['SCHD']:.1f})"

    def test_growth_fit_uses_div_growth_5y_fallback(self, schd_vs_spyi):
        """div_growth_5y가 dps_yoy_pct 없을 때 growth_fit에 반영됨."""
        # SCHD는 dps_yoy_pct 없이 div_growth_5y=10.2만 가짐
        # QYLD는 div_growth_5y=-2.0 (음수 성장)
        qyld = _etf("QYLD", yield_pct=11.5, div_growth_5y=-2.0)
        schd = schd_vs_spyi[0]  # div_growth_5y=10.2

        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            ranked = rank_candidates(
                [schd, qyld], age=25, investable_amount=360,
                monthly_target=50, risk_tolerance="moderate",
                target_fire_age=50,
            )
        scores = {r["ticker"]: r["fit_score"] for r in ranked}
        # 장기에서 성장률 10.2% SCHD > -2.0% QYLD
        assert scores["SCHD"] > scores["QYLD"], \
            f"div_growth_5y fallback 미동작: SCHD={scores['SCHD']:.1f}, QYLD={scores['QYLD']:.1f}"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Risk gate 제외
# ═══════════════════════════════════════════════════════════════════════════

class TestRiskGate:
    """BLOCK 종목은 결과에서 제외됨."""

    def test_blocked_ticker_excluded(self):
        """BLOCK 종목은 fit_score = 0 + excluded = True."""
        candidates = [
            _stock("SAFE",  4.0, 5.0, "IT", "IT"),
            _stock("RISKY", 8.0, 3.0, "통신", "통신"),
        ]
        mock = _make_risk_mock(blocked={"RISKY"})
        with patch("utils.personalized_ranker.score_asset", mock):
            ranked = rank_candidates(candidates, age=40, investable_amount=5000,
                                      monthly_target=100, risk_tolerance="moderate")

        tickers = [r["ticker"] for r in ranked]
        assert "RISKY" not in tickers, f"BLOCK 종목이 결과에 포함: {tickers}"
        assert "SAFE" in tickers

    def test_all_blocked_returns_empty(self):
        """전부 BLOCK이면 빈 리스트."""
        candidates = [
            _stock("A", 5.0, 5.0, "IT", "IT"),
            _stock("B", 4.0, 3.0, "통신", "통신"),
        ]
        mock = _make_risk_mock(blocked={"A", "B"})
        with patch("utils.personalized_ranker.score_asset", mock):
            ranked = rank_candidates(candidates, age=40, investable_amount=5000,
                                      monthly_target=100, risk_tolerance="moderate")
        assert ranked == []

    def test_high_risk_score_still_passes_unless_blocked(self):
        """risk_score가 높아도 risk_gate=PASS면 결과에 포함 (고위험 아님)."""
        candidates = [_stock("H", 5.0, 5.0, "IT", "IT")]
        mock = _make_risk_mock(scores={"H": 70.0})  # 높은 risk score지만 PASS
        with patch("utils.personalized_ranker.score_asset", mock):
            ranked = rank_candidates(candidates, age=40, investable_amount=5000,
                                      monthly_target=100, risk_tolerance="moderate")
        assert "H" in [r["ticker"] for r in ranked]


# ═══════════════════════════════════════════════════════════════════════════
# 8. Personalization — 나이/자산에 따라 결과 달라짐
# ═══════════════════════════════════════════════════════════════════════════

class TestPersonalization:
    """동일 후보군이라도 사용자 프로필에 따라 순위가 달라짐."""

    @pytest.fixture
    def growth_vs_income(self):
        """성장형 vs 고배당형 — 나이에 따라 선호가 달라야 함."""
        return [
            _stock("GROWTH", 2.0, 12.0, "IT",  "IT"),    # 저yield, 고성장
            _stock("INCOME", 8.0,  0.5, "통신", "통신"),  # 고yield, 저성장
        ]

    def test_young_prefers_growth_over_income(self, growth_vs_income):
        """25세(장기): growth_fit 가중치 높아 성장형이 우선."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            ranked = rank_candidates(growth_vs_income, age=25,
                                      investable_amount=360, monthly_target=50,
                                      risk_tolerance="moderate", target_fire_age=50)
        order = [r["ticker"] for r in ranked]
        assert order[0] == "GROWTH", f"25세에서 INCOME이 우선: {order}"

    def test_old_prefers_income_over_growth(self, growth_vs_income):
        """60세(단기): abs_yield 가중치 높아 고배당이 우선."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            ranked = rank_candidates(growth_vs_income, age=60,
                                      investable_amount=30000, monthly_target=200,
                                      risk_tolerance="conservative",
                                      target_fire_age=65)
        order = [r["ticker"] for r in ranked]
        assert order[0] == "INCOME", f"60세에서 GROWTH가 우선: {order}"

    def test_different_ages_different_order(self, growth_vs_income):
        """25세와 60세에서 순위가 반전됨."""
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            young = rank_candidates(growth_vs_income, age=25,
                                     investable_amount=360, monthly_target=50,
                                     risk_tolerance="moderate", target_fire_age=50)
            old   = rank_candidates(growth_vs_income, age=60,
                                     investable_amount=30000, monthly_target=200,
                                     risk_tolerance="conservative", target_fire_age=65)

        young_order = [r["ticker"] for r in young]
        old_order   = [r["ticker"] for r in old]
        assert young_order != old_order, \
            f"나이 달라도 순위 동일: {young_order}"

    def test_horizon_changes_weights_in_result(self):
        """target_fire_age가 달라지면 horizon_weights가 달라짐."""
        candidates = [_stock("X", 5.0, 5.0, "IT", "IT")]
        with patch("utils.personalized_ranker.score_asset", _DEFAULT_MOCK):
            long_r  = rank_candidates(candidates, age=25, investable_amount=360,
                                       monthly_target=50, risk_tolerance="moderate",
                                       target_fire_age=50)  # 25년
            short_r = rank_candidates(candidates, age=25, investable_amount=360,
                                       monthly_target=50, risk_tolerance="moderate",
                                       target_fire_age=30)  # 5년

        w_long  = long_r[0]["horizon_weights"]
        w_short = short_r[0]["horizon_weights"]
        assert w_long != w_short, \
            f"horizon 달라도 weights 동일: {w_long}"

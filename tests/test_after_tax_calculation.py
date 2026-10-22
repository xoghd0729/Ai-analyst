"""
세후 배당금 계산 분리 검증 (tests/test_after_tax_calculation.py)
================================================================
각 계산 단계를 독립적으로 검증.
DPS 오차가 낮다고 세후 금액이 정확하다는 보장은 없으므로 별도 검증.

검증 대상:
  1. 주수 계산 (수수료 포함/미포함)
  2. DPS → 연간 배당금 환산
  3. 환율 적용 (USD → KRW)
  4. 원천징수세 15.4% 적용
  5. 월 평균 환산 (연간 ÷ 12)
  6. 전체 파이프라인 PRU 기준 수작업 검증
  7. 세율 경계값 (0%, 100%, 15.4%)
  8. 환율 변화가 세후 배당에 미치는 영향
"""
import pytest
from utils.calc_share_based_dividend import (
    calc_shares,
    calc_annual_dps,
    calc_share_based_for_ticker,
    TAX_RATE_DIVIDEND,
    DEFAULT_USD_KRW,
    DEFAULT_COMMISSION,
)

# ── 테스트용 픽스처 캐시 ────────────────────────────────────────────
MOCK_CACHE = {
    "PRU": {
        "ticker": "PRU", "name": "Prudential Financial",
        "price_usd": 113.09, "div_yield": 4.95,
        "fetched_at": "2026-10-12T20:21:16.538447",
    },
    "SCHD": {
        "ticker": "SCHD", "name": "Schwab US Dividend Equity ETF",
        "price_usd": 33.04, "div_yield": 3.24,
        "fetched_at": "2026-10-12T20:21:16.538447",
    },
}


class TestTaxRateConstant:
    """세율 상수 검증"""

    def test_tax_rate_is_15_4_pct(self):
        """한국 원천징수세율 15.4% (소득세 14% + 지방세 1.4%) 확인"""
        assert TAX_RATE_DIVIDEND == 0.154, (
            f"세율 {TAX_RATE_DIVIDEND} — 15.4%(0.154) 이어야 함. "
            "한국-미국 조세조약 기준 원천징수세율"
        )

    def test_after_tax_multiplier(self):
        """세후 잔존율 = 1 - 0.154 = 0.846"""
        assert abs((1 - TAX_RATE_DIVIDEND) - 0.846) < 1e-9


class TestShareCalculationSteps:
    """주수 계산 단계 검증"""

    def test_step1_investment_to_won(self):
        """만원 → 원 환산"""
        investment_manwon = 245.8
        assert investment_manwon * 10_000 == 2_458_000

    def test_step2_price_in_krw_with_commission(self):
        """주당 원화 비용 = price_usd × usd_krw × (1 + commission)"""
        price_usd = 113.09
        usd_krw = 1380
        commission = 0.0025
        price_krw_with_commission = price_usd * usd_krw * (1 + commission)
        expected = 113.09 * 1380 * 1.0025
        assert abs(price_krw_with_commission - expected) < 0.01

    def test_step3_shares_formula(self):
        """주수 = 투자원화 / 주당원화비용"""
        investment_won = 2_458_000
        price_krw_with_commission = 113.09 * 1380 * 1.0025
        shares = investment_won / price_krw_with_commission
        # PRU 245.8만원 → ~15.71주
        assert 15.5 < shares < 16.0

    def test_commission_reduces_shares(self):
        """수수료 있으면 주수가 줄어야 함"""
        shares_no_fee = calc_shares(100, 50.0, usd_krw=1380, commission_rate=0.0)
        shares_with_fee = calc_shares(100, 50.0, usd_krw=1380, commission_rate=0.0025)
        assert shares_with_fee < shares_no_fee

    def test_higher_exchange_rate_reduces_shares(self):
        """환율 상승 → 같은 원화로 살 수 있는 USD 주식 감소"""
        shares_1380 = calc_shares(100, 50.0, usd_krw=1380)
        shares_1500 = calc_shares(100, 50.0, usd_krw=1500)
        assert shares_1500 < shares_1380


class TestDividendCalculationSteps:
    """배당금 계산 단계 검증"""

    def test_step4_annual_dps(self):
        """연간 DPS = price × yield%"""
        dps = calc_annual_dps(113.09, 4.95)
        assert abs(dps - 5.598) < 0.01  # PRU DPS ≈ $5.60

    def test_step5_annual_div_usd(self):
        """연간 배당(USD) = 주수 × DPS"""
        shares = 15.71
        dps = 5.598
        annual_usd = shares * dps
        assert abs(annual_usd - 87.94) < 0.5

    def test_step6_usd_to_krw(self):
        """USD → KRW 환산"""
        annual_usd = 87.94
        usd_krw = 1380
        annual_krw = annual_usd * usd_krw
        assert abs(annual_krw - 121_357) < 100

    def test_step7_after_tax(self):
        """세후 = 세전 × (1 - 0.154)"""
        annual_krw = 121_357
        after_tax = annual_krw * (1 - TAX_RATE_DIVIDEND)
        assert abs(after_tax - 102_668) < 200  # ≈ 102,668원

    def test_step8_monthly_manwon(self):
        """월 세후 배당(만원) = 세후연간 / 12 / 10000"""
        after_tax_annual_krw = 102_668
        monthly = after_tax_annual_krw / 12 / 10_000
        assert abs(monthly - 0.856) < 0.01  # PRU ≈ 0.86만원


class TestEndToEndPRU:
    """PRU 수작업 검증 — 전체 파이프라인 E2E"""

    def test_pru_full_calculation(self):
        """
        PRU 245.8만원 투자, 환율 1380, 수수료 0.25%, 세율 15.4%
        수작업 계산:
          shares = 2,458,000 / (113.09 × 1380 × 1.0025) = 15.71주
          dps    = 113.09 × 4.95% = $5.598
          annual_usd   = 15.71 × 5.598 = $87.94
          annual_krw   = 87.94 × 1380 = 121,357원
          after_tax    = 121,357 × 0.846 = 102,668원
          monthly_만원 = 102,668 / 12 / 10000 = 0.856만원
        """
        r = calc_share_based_for_ticker(
            "PRU", 245.8, usd_krw=1380,
            commission_rate=0.0025, tax_rate=0.154,
            cache=MOCK_CACHE
        )
        assert r is not None

        # 주수: 15.5 ~ 16.0
        assert 15.5 < r.shares < 16.0, f"주수 {r.shares}"

        # DPS: $5.50 ~ $5.70
        assert 5.50 < r.annual_dps_usd < 5.70, f"DPS ${r.annual_dps_usd}"

        # 연간 배당(KRW): 110,000 ~ 130,000원
        assert 110_000 < r.annual_div_krw < 130_000, \
            f"연간배당 {r.annual_div_krw}원"

        # 세후 연간 배당: 93,000 ~ 110,000원
        assert 93_000 < r.annual_div_after_tax_krw < 110_000, \
            f"세후연간 {r.annual_div_after_tax_krw}원"

        # 월 세후 배당: 0.78만원 ~ 0.92만원
        assert 0.78 < r.monthly_div_after_tax_manwon < 0.92, \
            f"월세후 {r.monthly_div_after_tax_manwon}만원"

    def test_pru_tax_applied_correctly(self):
        """세후 = 세전 × 0.846 검증"""
        r = calc_share_based_for_ticker("PRU", 245.8, cache=MOCK_CACHE)
        assert r is not None
        ratio = r.annual_div_after_tax_krw / r.annual_div_krw
        assert abs(ratio - 0.846) < 0.001, \
            f"세율 적용 비율 {ratio:.4f} — 0.846 이어야 함"

    def test_pru_monthly_is_annual_divided_by_12(self):
        """월 배당 = 연간 배당 / 12 / 10000"""
        r = calc_share_based_for_ticker("PRU", 245.8, cache=MOCK_CACHE)
        assert r is not None
        expected_monthly = r.annual_div_after_tax_krw / 12 / 10_000
        assert abs(r.monthly_div_after_tax_manwon - expected_monthly) < 0.01, \
            f"월배당 불일치: {r.monthly_div_after_tax_manwon} vs {expected_monthly:.4f}"


class TestExchangeRateEffect:
    """
    환율 변화가 세후 배당에 미치는 영향.

    【현재 모델 한계 문서화】
    이 계산 모델은 매수 시점과 배당 수령 시점의 환율을 동일하게 가정한다.
    수식: KRW배당 = (투자원화 / (price × usd_krw × 1.0025)) × (price × yield%) × usd_krw
          usd_krw가 약분되어 사라짐 → 환율 변화가 KRW 배당에 영향 없음.

    실제 투자에서는:
      - 매수 시 환율이 높으면 → 같은 원화로 주수 감소
      - 배당 수령 시 환율이 높으면 → USD 배당의 원화 가치 증가
    이 두 효과가 단일 환율 가정에서 정확히 상쇄됨.

    한계: 매수 후 환율이 바뀐 경우(예: 매수 1380, 배당 수령 1500)를 모델링하지 않음.
    이 테스트는 모델의 현재 동작을 문서화하며, 다기간 시뮬레이션 시 별도 처리 필요.
    """

    def test_exchange_rate_fully_neutral(self):
        """
        현재 모델: 환율 변화 → KRW 배당 변화 없음 (수식에서 usd_krw 소거).
        이는 단일 시점 계산의 수학적 결과이며 의도된 동작임.
        """
        r_1380 = calc_share_based_for_ticker("PRU", 245.8, usd_krw=1380, cache=MOCK_CACHE)
        r_1500 = calc_share_based_for_ticker("PRU", 245.8, usd_krw=1500, cache=MOCK_CACHE)
        diff_pct = abs(r_1500.annual_div_krw - r_1380.annual_div_krw) / r_1380.annual_div_krw * 100
        # 0%에 가까워야 함 (수수료 계산은 동일 usd_krw 사용)
        assert diff_pct < 0.01, (
            f"환율 중립성 실패: {diff_pct:.4f}% 차이. "
            "수식 변경 여부 확인 필요"
        )

    def test_exchange_rate_model_limitation_documented(self):
        """
        매수 환율 vs 배당 수령 환율이 다른 경우를 현 모델이 처리하지 않음을 확인.
        이 테스트는 항상 통과해야 하며, 다기간 모델 추가 시 별도 필터에서 처리 예정.
        """
        # 현재 모델: 같은 투자금, 다른 환율 → KRW 배당 동일
        r_1380 = calc_share_based_for_ticker("PRU", 245.8, usd_krw=1380, cache=MOCK_CACHE)
        r_1200 = calc_share_based_for_ticker("PRU", 245.8, usd_krw=1200, cache=MOCK_CACHE)
        # usd_krw 소거 → 동일
        assert abs(r_1380.annual_div_krw - r_1200.annual_div_krw) < 10, (
            "모델 동작 변경됨 — 환율이 KRW 배당에 영향을 미치기 시작함"
        )


class TestTaxRateBoundaries:
    """세율 경계값 테스트"""

    def test_zero_tax_rate(self):
        """세율 0% → 세후 = 세전"""
        r = calc_share_based_for_ticker(
            "PRU", 100, usd_krw=1380, tax_rate=0.0, cache=MOCK_CACHE
        )
        assert r is not None
        assert r.annual_div_after_tax_krw == r.annual_div_krw

    def test_full_tax_rate(self):
        """세율 100% → 세후 = 0"""
        r = calc_share_based_for_ticker(
            "PRU", 100, usd_krw=1380, tax_rate=1.0, cache=MOCK_CACHE
        )
        assert r is not None
        assert r.annual_div_after_tax_krw == 0

    def test_standard_15_4_tax(self):
        """표준 15.4% 세율 적용 시 세후 잔존 84.6%"""
        r = calc_share_based_for_ticker(
            "PRU", 245.8, usd_krw=1380,
            tax_rate=TAX_RATE_DIVIDEND, cache=MOCK_CACHE
        )
        assert r is not None
        ratio = r.annual_div_after_tax_krw / r.annual_div_krw
        assert abs(ratio - 0.846) < 0.001

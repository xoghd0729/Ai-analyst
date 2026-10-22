"""
배당 이력 검증 테스트 (tests/test_dividend_verification.py)
============================================================
전제: utils/verify_ttm_dps.py 실행 후
      data/dividends/ttm_reference.json 이 존재해야 함.

파일이 없으면 테스트를 skip한다 (CI에서 오류 없이 통과).
"""
import json
import os
import pytest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REF_PATH = BASE_DIR / "data" / "dividends" / "ttm_reference.json"

# reference 파일 없으면 전체 모듈 skip
pytestmark = pytest.mark.skipif(
    not REF_PATH.exists(),
    reason=(
        "ttm_reference.json 없음. "
        "먼저 utils/verify_ttm_dps.py 를 실행하세요: "
        "  pip install yfinance && python utils/verify_ttm_dps.py"
    ),
)


@pytest.fixture(scope="module")
def ref():
    with open(REF_PATH, encoding="utf-8") as f:
        return json.load(f)


class TestReferenceStructure:
    """reference 파일 구조 검증"""

    def test_has_results(self, ref):
        assert "results" in ref
        assert len(ref["results"]) > 0

    def test_has_methodology(self, ref):
        m = ref.get("methodology", {})
        assert "estimate_method" in m
        assert "error_pct_formula" in m

    def test_key_tickers_present(self, ref):
        """SCHD·PRU·PEP 세 종목은 반드시 있어야 함"""
        for ticker in ["SCHD", "PRU", "PEP"]:
            assert ticker in ref["results"], f"{ticker} 결과 없음"


class TestEstimateAccuracy:
    """price×yield% 추정치 vs TTM DPS 오차 검증"""

    def test_schd_error_within_15pct(self, ref):
        r = ref["results"].get("SCHD", {})
        err = r.get("error_pct")
        if err is None:
            pytest.skip("SCHD TTM 데이터 없음")
        assert abs(err) <= 15, (
            f"SCHD 오차 {err:+.1f}% — 15% 초과. "
            f"추정 DPS=${r['estimate_dps']:.4f}, TTM DPS=${r['ttm_dps']:.4f}"
        )

    def test_pru_error_within_15pct(self, ref):
        r = ref["results"].get("PRU", {})
        err = r.get("error_pct")
        if err is None:
            pytest.skip("PRU TTM 데이터 없음")
        assert abs(err) <= 15, (
            f"PRU 오차 {err:+.1f}% — 15% 초과. "
            f"추정 DPS=${r['estimate_dps']:.4f}, TTM DPS=${r['ttm_dps']:.4f}"
        )

    def test_pep_error_within_15pct(self, ref):
        r = ref["results"].get("PEP", {})
        err = r.get("error_pct")
        if err is None:
            pytest.skip("PEP TTM 데이터 없음")
        assert abs(err) <= 15, (
            f"PEP 오차 {err:+.1f}% — 15% 초과. "
            f"추정 DPS=${r['estimate_dps']:.4f}, TTM DPS=${r['ttm_dps']:.4f}"
        )

    def test_average_absolute_error_within_10pct(self, ref):
        """
        TTM 신뢰 가능한 종목(payment_count_warning=False)의 평균 절대 오차 ≤ 10%.
        소액 이벤트 혼입 경고가 있는 종목(예: HDV)은 집계에서 제외.
        """
        valid = [
            v for v in ref["results"].values()
            if v.get("error_pct") is not None
            and v.get("ttm_reliable", True)  # 신규 필드 없으면 True로 폴백
        ]
        if len(valid) == 0:
            pytest.skip("신뢰 가능한 TTM 데이터 있는 종목 없음")
        avg_err = sum(abs(v["error_pct"]) for v in valid) / len(valid)
        assert avg_err <= 10, (
            f"평균 절대 오차 {avg_err:.1f}% — 10% 초과. "
            "캐시 div_yield 데이터 소스 재검토 필요"
        )

    def test_hdv_warning_flagged(self, ref):
        """HDV 소액 이벤트(자본이득분배 혼입 의심)가 경고로 플래그됐는지 확인"""
        hdv = ref["results"].get("HDV")
        if hdv is None:
            pytest.skip("HDV 결과 없음")
        # ttm_reference.json이 구 버전(payment_count_warning 없음)이면 skip
        if "payment_count_warning" not in hdv:
            pytest.skip("구 버전 ttm_reference.json — verify_ttm_dps.py 재실행 필요")
        assert hdv["payment_count_warning"] is True, (
            f"HDV payment_count_warning=False — "
            f"6회 지급({hdv['payment_count']}건)에 소액 이벤트가 포함되지 않은지 재확인"
        )


class TestDividendPaymentCount:
    """배당 지급 횟수 합리성 검증 (분기 배당 기준)"""

    def test_schd_quarterly(self, ref):
        r = ref["results"].get("SCHD", {})
        cnt = r.get("payment_count")
        if cnt is None:
            pytest.skip("SCHD payment_count 없음")
        # SCHD는 분기 배당 → TTM에서 4회 지급
        assert 3 <= cnt <= 5, f"SCHD 지급 횟수 {cnt}회 — 분기배당이면 4회 예상"

    def test_pru_quarterly(self, ref):
        r = ref["results"].get("PRU", {})
        cnt = r.get("payment_count")
        if cnt is None:
            pytest.skip("PRU payment_count 없음")
        assert 3 <= cnt <= 5, f"PRU 지급 횟수 {cnt}회 — 분기배당이면 4회 예상"

    def test_pep_quarterly(self, ref):
        r = ref["results"].get("PEP", {})
        cnt = r.get("payment_count")
        if cnt is None:
            pytest.skip("PEP payment_count 없음")
        assert 3 <= cnt <= 5, f"PEP 지급 횟수 {cnt}회 — 분기배당이면 4회 예상"


class TestDataConsistency:
    """캐시 데이터 일관성 검증"""

    def test_estimate_dps_matches_cache_formula(self, ref):
        """추정 DPS = price × yield% / 100 수식 일관성"""
        for ticker, r in ref["results"].items():
            if r.get("fetch_error"):
                continue
            expected = round(r["price_cache_usd"] * r["yield_cache_pct"] / 100, 4)
            actual   = round(r["estimate_dps"], 4)
            assert abs(expected - actual) < 0.01, (
                f"{ticker}: 수식 불일치 — "
                f"price={r['price_cache_usd']} × yield={r['yield_cache_pct']}% "
                f"= {expected}, stored={actual}"
            )

    def test_no_fetch_errors_for_key_tickers(self, ref):
        """핵심 3종목에서 fetch 오류 없어야 함"""
        for ticker in ["SCHD", "PRU", "PEP"]:
            r = ref["results"].get(ticker, {})
            err = r.get("fetch_error")
            assert err is None, f"{ticker} fetch 오류: {err}"

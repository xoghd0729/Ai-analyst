"""
배당 특화 지표 계산 모듈.
DART에서 수집된 재무 원시 데이터를 바탕으로
배당 지속성 분석에 필요한 파생 지표를 계산·저장한다.

핵심 지표:
  payout_ratio     배당성향 (%)      = dividends_paid / net_income * 100
  dividend_coverage 배당커버리지 (배) = free_cash_flow / dividends_paid
  free_cash_flow   잉여현금흐름 (원) = operating_cf - capex
  earnings_growth  순이익 성장률 (%) = (올해 - 작년) / |작년| * 100
  dividend_yield   배당수익률 (%)    = dps / current_price * 100
"""

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os
from datetime import date, datetime, timedelta
from dotenv import load_dotenv
from pykrx import stock as krx
from sqlalchemy import create_engine, text
from collectors.dart import get_dividend_per_share

load_dotenv()
engine = create_engine("postgresql://localhost/ai_analyst")


# ── 내부 헬퍼 ─────────────────────────────────────────────────────────────────

def _get(conn, stock_code: str, metric: str) -> float | None:
    """metric_snapshots에서 최신값 조회"""
    row = conn.execute(text("""
        SELECT value FROM metric_snapshots
        WHERE stock_code = :code AND metric_name = :metric
        ORDER BY date DESC LIMIT 1
    """), {"code": stock_code, "metric": metric}).fetchone()
    return float(row[0]) if row else None


def _save(conn, stock_code: str, metric: str, value: float, ref_date: str | None = None):
    d = ref_date or date.today().isoformat()
    conn.execute(text("""
        INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
        VALUES (:code, :date, :metric, :value)
        ON CONFLICT (stock_code, date, metric_name)
        DO UPDATE SET value = EXCLUDED.value
    """), {"code": stock_code, "date": d, "metric": metric, "value": value})


# ── 핵심 계산 ─────────────────────────────────────────────────────────────────

def compute_dividend_metrics(stock_code: str, corp_code: str, year: str):
    """
    DART 수집 후 호출.
    배당 지속성 분석을 위한 파생 지표 일괄 계산 및 저장.
    """
    today_str = date.today().isoformat()
    results = {}

    with engine.connect() as conn:
        net_income     = _get(conn, stock_code, "net_income")
        operating_cf   = _get(conn, stock_code, "operating_cf")
        capex          = _get(conn, stock_code, "capex")
        dividends_paid = _get(conn, stock_code, "dividends_paid")

        # ① 잉여현금흐름 (FCF)
        if operating_cf is not None and capex is not None:
            fcf = operating_cf - abs(capex)   # capex는 음수로 저장되는 경우 대응
            _save(conn, stock_code, "free_cash_flow", fcf)
            results["free_cash_flow"] = fcf
        else:
            fcf = None

        # ② 배당성향 (payout_ratio)
        if dividends_paid and net_income and net_income > 0:
            payout = abs(dividends_paid) / net_income * 100
            _save(conn, stock_code, "payout_ratio", round(payout, 2))
            results["payout_ratio"] = round(payout, 2)
        else:
            payout = None

        # ③ 배당커버리지 (FCF / 배당지급)
        if fcf is not None and dividends_paid and abs(dividends_paid) > 0:
            coverage = fcf / abs(dividends_paid)
            _save(conn, stock_code, "dividend_coverage", round(coverage, 2))
            results["dividend_coverage"] = round(coverage, 2)

        # ④ 주당배당금 DPS + 배당수익률 정밀 계산
        dps = get_dividend_per_share(corp_code, year)
        if dps:
            _save(conn, stock_code, "dividend_per_share", dps, f"{year}-12-31")
            results["dividend_per_share"] = dps

            # 현재가 기반 배당수익률 재계산
            try:
                today_yyyymmdd = datetime.today().strftime("%Y%m%d")
                start_yyyymmdd = (datetime.today() - timedelta(days=5)).strftime("%Y%m%d")
                df = krx.get_market_ohlcv(start_yyyymmdd, today_yyyymmdd, stock_code)
                current_price = float(df["종가"].iloc[-1])
                if current_price > 0:
                    dy = dps / current_price * 100
                    _save(conn, stock_code, "dividend_yield", round(dy, 4))
                    results["dividend_yield"] = round(dy, 4)
            except Exception:
                pass

        # ⑤ 순이익 성장률 (전년 대비)
        try:
            prev_year = str(int(year) - 1)
            ni_prev_row = conn.execute(text("""
                SELECT value FROM metric_snapshots
                WHERE stock_code = :code AND metric_name = 'net_income'
                  AND date = :prev_date
                LIMIT 1
            """), {"code": stock_code, "prev_date": f"{prev_year}-12-31"}).fetchone()

            if ni_prev_row and net_income is not None:
                ni_prev = float(ni_prev_row[0])
                if ni_prev != 0:
                    growth = (net_income - ni_prev) / abs(ni_prev) * 100
                    _save(conn, stock_code, "earnings_growth", round(growth, 2))
                    results["earnings_growth"] = round(growth, 2)
        except Exception:
            pass

        conn.commit()

    # 결과 출력
    lines = []
    if "free_cash_flow"    in results: lines.append(f"FCF={results['free_cash_flow']/1e12:.2f}조")
    if "payout_ratio"      in results: lines.append(f"배당성향={results['payout_ratio']:.1f}%")
    if "dividend_coverage" in results: lines.append(f"커버리지={results['dividend_coverage']:.2f}배")
    if "dividend_per_share" in results: lines.append(f"DPS={results['dividend_per_share']:,.0f}원")
    if "dividend_yield"    in results: lines.append(f"배당수익률={results['dividend_yield']:.2f}%")
    if "earnings_growth"   in results: lines.append(f"순이익성장={results['earnings_growth']:+.1f}%")

    if lines:
        print(f"✅ 배당 지표: {', '.join(lines)}")
    else:
        print("⚠️  배당 파생 지표 계산 실패 (원시 데이터 부족)")

    return results

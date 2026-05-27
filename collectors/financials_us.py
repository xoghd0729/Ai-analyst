"""
collectors/financials_us.py — 미국 주식 재무 지표 수집 (yfinance)

한국 주식은 DART API로 재무 데이터를 가져오지만,
미국 주식은 yfinance가 동일한 데이터를 무료로 제공함.

수집 항목:
  - fcf              : 잉여현금흐름 (Operating CF - CapEx)
  - operating_cf     : 영업현금흐름
  - capex            : 설비투자
  - dividends_paid   : 배당 지급액
  - dividend_coverage: fcf / dividends_paid (배당 커버리지)
  - payout_ratio     : 배당성향 (%)
  - dps_yoy_pct      : 주당배당금 전년 대비 증감률 (%)

저장 위치: metric_snapshots (한국 주식과 동일한 테이블)
  → stock.py /thesis, /metrics 엔드포인트가 그대로 활용 가능
  → XGBoost ML 모델에도 실제 피처로 입력됨
"""

import logging
from datetime import datetime, date

log = logging.getLogger(__name__)


def fetch_us_financials(ticker: str, engine) -> dict:
    """
    yfinance로 미국 주식 재무 지표 수집 후 DB 저장.

    반환: 저장된 지표 딕셔너리 (ML 피처로 즉시 사용 가능)
    """
    try:
        import yfinance as yf
        from sqlalchemy import text

        t        = yf.Ticker(ticker)
        info     = t.info or {}
        today    = date.today().isoformat()  # "2025-05-19"

        metrics: dict[str, float] = {}

        # ── 1. ticker.info — 기본 재무 지표 ──────────────────────
        # payout_ratio: yfinance는 0~1 소수로 줌 → % 변환
        pr = info.get("payoutRatio")
        if pr is not None:
            try:
                payout_pct = float(pr) * 100
                metrics["payout_ratio"] = round(payout_pct, 2)
            except (TypeError, ValueError):
                pass

        # operating CF, fcf, capex — info에 있는 경우 우선 사용
        for yf_key, metric_name in [
            ("freeCashflow",      "fcf"),
            ("operatingCashflow", "operating_cf"),
        ]:
            val = info.get(yf_key)
            if val is not None:
                try:
                    metrics[metric_name] = float(val)
                except (TypeError, ValueError):
                    pass

        # ── 2. ticker.cashflow — 더 상세한 현금흐름표 ────────────
        # info보다 정확. 최신 연도(column[0]) 사용
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty:
                col = cf.columns[0]  # 가장 최신 연도

                def _get_cf(keys: list) -> float | None:
                    """여러 후보 키 중 첫 번째로 값 있는 것 반환."""
                    for k in keys:
                        if k in cf.index:
                            v = cf.loc[k, col]
                            if v is not None and str(v) != "nan":
                                return float(v)
                    return None

                ocf = _get_cf([
                    "Operating Cash Flow",
                    "Cash From Operations",
                    "Total Cash From Operating Activities",
                ])
                capex = _get_cf([
                    "Capital Expenditure",
                    "Capital Expenditures",
                    "Purchase Of Property Plant And Equipment",
                ])
                div_paid = _get_cf([
                    "Common Stock Dividend Paid",
                    "Cash Dividends Paid",
                    "Dividends Paid",
                    "Payment Of Dividends",
                ])

                if ocf is not None:
                    metrics["operating_cf"] = ocf
                if capex is not None:
                    # yfinance capex는 보통 음수로 표기 → 절댓값으로 저장
                    metrics["capex"] = abs(capex)
                if div_paid is not None:
                    metrics["dividends_paid"] = abs(div_paid)

                # FCF 재계산 (info보다 정확)
                if ocf is not None and capex is not None:
                    metrics["fcf"] = ocf - abs(capex)

        except Exception as e:
            log.warning(f"[fin_us] {ticker} cashflow 파싱 실패: {e}")

        # ── 3. 배당 커버리지 계산 ─────────────────────────────────
        # dividend_coverage = fcf / dividends_paid
        # 클수록 안전 (2x 이상이면 여유)
        fcf     = metrics.get("fcf")
        div     = metrics.get("dividends_paid")
        if fcf is not None and div and div > 0:
            metrics["dividend_coverage"] = round(fcf / div, 3)

        # ── 4. dps_yoy_pct — 주당배당금 전년 대비 증감률 ─────────
        # 배당귀족 판별의 핵심: 매년 배당이 올랐는가
        try:
            divs = t.dividends
            if divs is not None and len(divs) >= 4:
                # 연간 합계로 집계 (분기 배당이 일반적이므로)
                # "YE" → pandas 2.2+, "A" → 구버전 호환, 둘 다 시도
                for freq in ("YE", "Y", "A"):
                    try:
                        annual = divs.resample(freq).sum()
                        # 진행 중인 올해는 분기 배당 일부만 들어와 YoY가 -50~-75%로 왜곡된다.
                        # 마지막 완전 연도끼리 비교해야 배당귀족주가 오판되지 않는다.
                        annual = annual[annual > 0]
                        current_year = date.today().year
                        annual = annual[annual.index.year < current_year]
                        if len(annual) >= 2:
                            this_yr = float(annual.iloc[-1])
                            prev_yr = float(annual.iloc[-2])
                            if prev_yr > 0:
                                yoy = (this_yr - prev_yr) / prev_yr * 100
                                metrics["dps_yoy_pct"] = round(yoy, 2)
                        break
                    except Exception:
                        continue
        except Exception as e:
            log.warning(f"[fin_us] {ticker} 배당 히스토리 파싱 실패: {e}")

        # ── 5. DB 저장 ────────────────────────────────────────────
        if not metrics:
            log.warning(f"[fin_us] {ticker}: 수집된 재무 지표 없음")
            return {}

        # ticker.info에서 회사명 가져오기 (없으면 ticker 그대로)
        company_name = info.get("longName") or info.get("shortName") or ticker

        saved = []
        with engine.connect() as conn:
            # metric_snapshots는 stocks 테이블을 외래키로 참조함
            # → US 티커를 stocks에 먼저 등록해야 저장 가능
            conn.execute(text("""
                INSERT INTO stocks (code, name, sector)
                VALUES (:code, :name, '미국배당주')
                ON CONFLICT (code) DO NOTHING
            """), {"code": ticker, "name": company_name})

            for metric_name, value in metrics.items():
                conn.execute(text("""
                    INSERT INTO metric_snapshots (stock_code, date, metric_name, value)
                    VALUES (:code, :date, :metric, :value)
                    ON CONFLICT (stock_code, date, metric_name)
                    DO UPDATE SET value = EXCLUDED.value
                """), {
                    "code":   ticker,
                    "date":   today,
                    "metric": metric_name,
                    "value":  value,
                })
                saved.append(f"{metric_name}={value:,.1f}")
            conn.commit()

        log.info(f"[fin_us] {ticker}: {len(metrics)}개 지표 저장 — {', '.join(saved)}")
        return metrics

    except Exception as e:
        log.error(f"[fin_us] {ticker} 재무 수집 실패: {e}")
        return {}


def fetch_us_financials_batch(tickers: list[tuple[str, str]], engine) -> dict[str, dict]:
    """
    여러 종목 일괄 수집.

    tickers: [(stock_code, name), ...]
    반환: {stock_code: metrics_dict}
    """
    results = {}
    for code, name in tickers:
        print(f"  📊 {name} ({code}) 재무 수집 중...", end=" ", flush=True)
        m = fetch_us_financials(code, engine)
        if m:
            summary = []
            if "fcf" in m:
                fcf_b = m["fcf"] / 1e9
                summary.append(f"FCF={fcf_b:.1f}B")
            if "payout_ratio" in m:
                summary.append(f"payout={m['payout_ratio']:.0f}%")
            if "dps_yoy_pct" in m:
                summary.append(f"dps_yoy={m['dps_yoy_pct']:+.1f}%")
            print(f"✅ {' | '.join(summary)}")
        else:
            print("⚠️  데이터 없음")
        results[code] = m
    return results

"""
TTM DPS 검증 스크립트 (utils/verify_ttm_dps.py)
================================================
실행 방법:
  cd ~/ai-analyst
  source venv/bin/activate
  pip install yfinance
  python utils/verify_ttm_dps.py

결과:
  data/dividends/ttm_reference.json 에 저장
  콘솔에 price×yield% 추정치 vs TTM DPS 비교표 출력

용어 정의:
  TTM DPS       : 최근 12개월 실제 지급된 주당 배당금 합계 (Trailing Twelve Months)
  Estimate DPS  : price_usd × div_yield% / 100  (현재 캐시 추정치)
  오차율(%)     : (Estimate - TTM) / TTM × 100
                  양수 = 추정치가 실제보다 높음 (과대 추정)
                  음수 = 추정치가 실제보다 낮음 (과소 추정)

주의:
  - TTM은 과거 실적, Estimate는 현재 시점 기준 연간화 수치
  - 배당 성장 중인 종목은 TTM < Estimate가 정상 (이미 인상됐을 수 있음)
  - 이 검증은 계산 일관성 확인용이며 미래 배당을 보장하지 않음
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_PATH = BASE_DIR / "data" / "us_dividend_cache.json"
OUTPUT_PATH = BASE_DIR / "data" / "dividends" / "ttm_reference.json"

# 검증 대상 종목
VERIFY_TICKERS = ["SCHD", "PRU", "PEP", "JEPI", "JEPQ", "VYM", "HDV", "DGRO"]


def get_ttm_dps(ticker: str, as_of_date: str) -> dict:
    """
    yfinance로 TTM DPS 계산.
    as_of_date: "YYYY-MM-DD" — 이 날짜 기준 과거 12개월 배당 합산

    주의사항:
    - yfinance는 자본이득분배(capital gains distribution)와 특별분배를
      일반 배당과 동일하게 dividends 시리즈에 포함할 수 있음.
    - 예: HDV는 분기 배당 ETF인데 7~9월에 소액 이벤트가 추가로 집계됨.
    - 이 함수는 지급 횟수(payment_count)와 소액 이벤트 여부를 함께 반환하며,
      호출측에서 payment_count_warning으로 확인해야 함.
    - 결과의 payment_count_warning == True이면 TTM 수치를 그대로 신뢰하지 말 것.
    """
    import yfinance as yf

    as_of = datetime.strptime(as_of_date, "%Y-%m-%d")
    start  = as_of - timedelta(days=366)

    tk = yf.Ticker(ticker)
    try:
        divs = tk.dividends
    except Exception as e:
        return {"ttm_dps": None, "payments": [], "error": f"yfinance_fetch_failed: {e}"}

    if divs is None or len(divs) == 0:
        return {"ttm_dps": None, "payments": [], "error": "no_dividend_data"}

    # tz-aware → naive 변환
    try:
        divs.index = divs.index.tz_localize(None)
    except Exception:
        try:
            divs.index = divs.index.tz_convert(None)
        except Exception:
            pass

    window = divs[(divs.index >= start) & (divs.index <= as_of)]
    ttm_dps = float(window.sum())
    payments = [
        {"date": str(idx.date()), "amount": round(float(v), 6)}
        for idx, v in window.items()
    ]

    # 소액 이벤트 탐지: 최대 지급액의 40% 미만인 이벤트가 있으면 경고
    # (자본이득분배·특별분배 혼입 가능성)
    payment_count_warning = False
    warning_reason = None
    if payments:
        max_amt = max(p["amount"] for p in payments)
        small_events = [p for p in payments if p["amount"] < max_amt * 0.4]
        # 분기 배당이면 4회 예상, 월 배당이면 12회 예상
        # 이 범위를 크게 벗어나거나 소액 이벤트가 있으면 경고
        if small_events:
            payment_count_warning = True
            warning_reason = (
                f"소액 이벤트 {len(small_events)}건 탐지 "
                f"(최대 ${max_amt:.4f}의 40% 미만): "
                f"{[p['date'] for p in small_events]}. "
                "자본이득분배·특별분배 혼입 가능 — TTM 수치 재확인 필요"
            )

    # 현재 주가 (as_of 기준 종가)
    hist = tk.history(start=as_of - timedelta(days=5), end=as_of + timedelta(days=1))
    price_on_date = float(hist["Close"].iloc[-1]) if len(hist) > 0 else None

    return {
        "ttm_dps": round(ttm_dps, 6),
        "payment_count": len(payments),
        "payments": payments,
        "price_on_date": round(price_on_date, 4) if price_on_date else None,
        "payment_count_warning": payment_count_warning,
        "warning_reason": warning_reason,
        "error": None,
    }


def main():
    # 캐시 로드
    with open(CACHE_PATH, encoding="utf-8") as f:
        cache = json.load(f)

    results = {}
    print(f"\n{'='*72}")
    print(f"{'TTM DPS 검증':^72}")
    print(f"{'='*72}")
    print(f"{'종목':<8} {'캐시주가':>10} {'캐시수익률':>10} {'추정DPS':>10} "
          f"{'TTM DPS':>10} {'오차(%)':>8} {'지급횟수':>6}")
    print(f"{'-'*72}")

    for ticker in VERIFY_TICKERS:
        entry = cache.get(ticker)
        if not entry:
            print(f"{ticker:<8} {'캐시없음':>10}")
            continue

        price_cache  = float(entry.get("price_usd") or 0)
        yield_cache  = float(entry.get("div_yield") or 0)
        estimate_dps = round(price_cache * yield_cache / 100, 6)
        fetched_at   = entry.get("fetched_at", "")[:10]  # YYYY-MM-DD

        try:
            ttm = get_ttm_dps(ticker, fetched_at)
        except Exception as e:
            ttm = {"ttm_dps": None, "error": str(e)}
            print(f"  !! {ticker} 오류: {e}")

        ttm_dps = ttm.get("ttm_dps")
        error_pct = None
        if ttm_dps and ttm_dps > 0:
            error_pct = round((estimate_dps - ttm_dps) / ttm_dps * 100, 2)

        # payment_count_warning: TTM 신뢰도 판정
        payment_count_warning = ttm.get("payment_count_warning", False)
        warning_reason = ttm.get("warning_reason")
        ttm_reliable = (ttm.get("error") is None) and (not payment_count_warning)

        results[ticker] = {
            "price_cache_usd":   price_cache,
            "yield_cache_pct":   yield_cache,
            "estimate_dps":      estimate_dps,
            "ttm_dps":           ttm_dps,
            "error_pct":         error_pct if ttm_reliable else None,
            "error_pct_raw":     error_pct,   # 경고 여부 무관 원본 오차율
            "payment_count":     ttm.get("payment_count"),
            "payment_count_warning": payment_count_warning,
            "warning_reason":    warning_reason,
            "ttm_reliable":      ttm_reliable,
            "payments":          ttm.get("payments", []),
            "price_on_cache_date": ttm.get("price_on_date"),
            "cache_date":        fetched_at,
            "fetch_error":       ttm.get("error"),
        }

        fetch_err = ttm.get("fetch_error") or ttm.get("error")
        err_str = f"{error_pct:+.1f}%" if error_pct is not None else "N/A"
        if payment_count_warning:
            err_str += " ⚠️"
        cnt_str = str(ttm.get("payment_count", "-"))
        ttm_str = f"${ttm_dps:.4f}" if ttm_dps else "N/A"
        print(f"{ticker:<8} ${price_cache:>9.2f} {yield_cache:>9.2f}% ${estimate_dps:>9.4f} "
              f"{ttm_str:>10} {err_str:>10} {cnt_str:>6}")
        if fetch_err:
            print(f"         └─ 오류: {fetch_err}")

    print(f"{'='*72}")

    # 주의사항 출력
    print()
    print("【div_yield 정의 주의】")
    print("  캐시의 div_yield = yfinance dividendYield = '최근 분기 배당×4 / 현재 주가'")
    print("  (trailing TTM DPS / 현재 주가가 아님)")
    print("  → 배당 인상 중인 종목은 estimate > TTM이 구조적으로 발생")
    print()

    # 경고 종목 출력
    warned = {t: v for t, v in results.items() if v.get("payment_count_warning")}
    if warned:
        print("【⚠️  데이터 품질 경고 — 아래 종목은 TTM 수치 신뢰 불가】")
        for t, v in warned.items():
            print(f"  {t}: {v['warning_reason']}")
        print()

    # 요약 (신뢰 가능한 종목만)
    valid = {t: v for t, v in results.items()
             if v.get("error_pct") is not None and v.get("ttm_reliable")}
    unreliable = {t: v for t, v in results.items()
                  if v.get("error_pct_raw") is not None and not v.get("ttm_reliable")}
    if valid:
        avg_err = sum(abs(v["error_pct"]) for v in valid.values()) / len(valid)
        over = sum(1 for v in valid.values() if v["error_pct"] > 0)
        under = sum(1 for v in valid.values() if v["error_pct"] < 0)
        print(f"신뢰 가능 종목 ({len(valid)}건) — 평균 절대 오차: {avg_err:.1f}%  |  과대추정: {over}건  |  과소추정: {under}건")
        if avg_err <= 5:
            print("✅ 추정 정확도 양호 (±5% 이내)")
        elif avg_err <= 10:
            print("⚠️  추정 정확도 보통 (5~10% 오차)")
        else:
            print("❌ 추정 오차 큼 (10% 초과) — 캐시 데이터 재검토 필요")
    if unreliable:
        print(f"데이터 경고 종목 ({len(unreliable)}건): {list(unreliable.keys())} — 오차율 집계 제외")

    # JSON 저장
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now().isoformat(),
        "description": "TTM DPS vs price×yield% 비교 검증 결과",
        "methodology": {
            "ttm_window": "cache fetched_at 기준 과거 365일",
            "estimate_method": "price_usd × div_yield% / 100",
            "error_pct_formula": "(estimate - ttm) / ttm × 100",
        },
        "results": results,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장: {OUTPUT_PATH}")
    return output


if __name__ == "__main__":
    main()

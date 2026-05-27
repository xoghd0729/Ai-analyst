"""
ETF 품질 스코어링 엔진 (Rule-based, ML 아님)

■ 설계 철학
  개별주 → ML (단일 기업 의사결정 리스크 예측)
  ETF    → Rule-based Quality Score (분산 자산은 룰로 QC)

  ETF는 본질적으로 "이미 분산된 포트폴리오"라서
  배당삭감 '의사결정' 예측 개념이 약하다.
  대신 구조적 품질(수수료, 성장성, 안정성)을 룰로 평가한다.

■ 4개 차원 평가 (총 100점)
  income_score   (35점): 분배금 3년 CAGR — 배당성장주인가
  growth_score   (25점): 5년 가격 CAGR  — 자본차익 실적
  stability_score(25점): Max Drawdown    — 위기 시 얼마나 버티나
  expense_score  (15점): Expense Ratio   — 수수료가 복리를 갉아먹나

■ 등급 기준
  80+ : PREMIUM  — 핵심 편입 자산
  60+ : PASS     — 정상 편입
  40+ : CAUTION  — 비중 50% 축소
  40미만: REJECT  — 이번 추천 풀에서 제외
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 디스크 캐시 — 서버 재시작 후에도 스코어 유지 (TTL 24시간)
# ─────────────────────────────────────────────────────────────
_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "etf_quality_cache.json"
)
_CACHE_TTL_HOURS = 24

def _load_disk_cache() -> dict:
    """디스크 캐시 로드. 파일 없거나 파싱 실패 시 빈 dict 반환."""
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_disk_cache(data: dict) -> None:
    try:
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning(f"[etf_quality] 캐시 저장 실패: {e}")

def _get_cached_score(ticker: str) -> Optional[dict]:
    """
    디스크 캐시에서 스코어 조회.
    - _updated 기준 TTL 초과 시 None 반환 → 재조회
    - 정적 기준값(팩트시트 기반)은 _updated 무관하게 항상 유효
    """
    cache = _load_disk_cache()
    scores = cache.get("scores", {})
    if ticker not in scores:
        return None
    # _updated 필드가 있으면 TTL 검사, 없으면 정적값으로 판단해 그냥 사용
    updated_str = cache.get("_updated")
    if updated_str:
        try:
            updated = datetime.strptime(updated_str, "%Y-%m-%d")
            if datetime.now() - updated > timedelta(hours=_CACHE_TTL_HOURS):
                return None  # 캐시 만료
        except Exception:
            pass
    return scores[ticker]

def _update_disk_cache(ticker: str, score_data: dict) -> None:
    """단일 ticker 스코어를 캐시에 upsert."""
    cache = _load_disk_cache()
    if "scores" not in cache:
        cache["scores"] = {}
    cache["scores"][ticker] = score_data
    cache["_updated"] = datetime.now().strftime("%Y-%m-%d")
    _save_disk_cache(cache)

# ─────────────────────────────────────────────────────────────
# 수수료(Expense Ratio) 하드코딩 기본값
# yfinance가 ETF 수수료를 항상 제공하지 않으므로 알려진 값 사전 정의
# ─────────────────────────────────────────────────────────────
KNOWN_EXPENSE_RATIOS: dict[str, float] = {
    # 미국 ETF
    "SCHD":  0.06,
    "VYM":   0.06,
    "DGRO":  0.08,
    "DGRW":  0.28,
    "JEPI":  0.35,
    "JEPQ":  0.35,
    "VNQ":   0.12,
    "O":     None,   # 개별 리츠, 수수료 없음
    "TLT":   0.15,
    "BND":   0.03,
    # 한국 상장 ETF
    "448290": 0.01,  # TIGER 미국배당다우존스
    "385720": 0.07,  # TIGER 미국MSCI리츠(H)
    "395400": None,  # SK리츠 (개별 리츠)
    "330590": None,  # 롯데리츠 (개별 리츠)
}


# ─────────────────────────────────────────────────────────────
# 1. 개별 지표 → 점수 변환 함수
# ─────────────────────────────────────────────────────────────

def _score_income_cagr(cagr_pct: Optional[float]) -> float:
    """
    분배금 3년 CAGR → income_score (0~100).
    SCHD 기준: 배당 CAGR 10%+ = 만점.
    마이너스 성장 = 심각한 감점.
    """
    if cagr_pct is None:
        return 50.0  # 데이터 없으면 중립
    if cagr_pct >= 10:  return 100.0
    if cagr_pct >= 7:   return 85.0
    if cagr_pct >= 4:   return 70.0
    if cagr_pct >= 1:   return 55.0
    if cagr_pct >= 0:   return 40.0
    if cagr_pct >= -3:  return 20.0
    return 5.0  # 심각한 분배금 역성장


def _score_price_cagr(cagr_pct: Optional[float]) -> float:
    """
    5년 가격 CAGR → growth_score (0~100).
    채권(TLT, BND)은 가격 성장 기대 안 하므로 보정 필요.
    """
    if cagr_pct is None:
        return 50.0
    if cagr_pct >= 12:  return 100.0
    if cagr_pct >= 8:   return 85.0
    if cagr_pct >= 5:   return 70.0
    if cagr_pct >= 2:   return 55.0
    if cagr_pct >= 0:   return 40.0
    if cagr_pct >= -3:  return 25.0
    return 10.0


def _score_max_drawdown(mdd_pct: Optional[float]) -> float:
    """
    Max Drawdown (음수, 예: -35.2) → stability_score (0~100).
    낮을수록(덜 폭락할수록) 좋다.
    """
    if mdd_pct is None:
        return 50.0
    mdd = abs(mdd_pct)  # 절대값으로 비교
    if mdd <= 10:   return 100.0
    if mdd <= 20:   return 85.0
    if mdd <= 30:   return 65.0
    if mdd <= 40:   return 45.0
    if mdd <= 55:   return 25.0
    return 10.0


def _score_expense_ratio(er_pct: Optional[float]) -> float:
    """
    Expense Ratio (%) → expense_score (0~100).
    수수료가 낮을수록 장기 복리에 유리.
    개별 리츠(O, SK리츠 등)는 수수료 개념 없으므로 None → 중립 75점.
    """
    if er_pct is None:
        return 75.0  # 개별 리츠/종목은 수수료 없으니 감점 안 함
    if er_pct <= 0.07:   return 100.0   # VOO, VYM, SCHD 수준
    if er_pct <= 0.15:   return 85.0
    if er_pct <= 0.30:   return 65.0
    if er_pct <= 0.50:   return 45.0
    if er_pct <= 0.75:   return 25.0
    return 10.0  # 1% 이상은 심각한 비용 부담


# ─────────────────────────────────────────────────────────────
# 2. yfinance로 실시간 지표 수집
# ─────────────────────────────────────────────────────────────

def _fetch_etf_metrics(ticker: str) -> dict:
    """
    yfinance로 ETF 지표 수집.
    실패 시 빈 dict 반환 → 각 점수는 중립값(50) 처리.
    """
    metrics: dict = {}
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np

        t = yf.Ticker(ticker)

        # ── 가격 히스토리 (5년) ──────────────────────────────
        hist = t.history(period="5y", auto_adjust=True)
        if hist is not None and not hist.empty and "Close" in hist.columns:
            prices = hist["Close"].dropna()
            if len(prices) >= 252:  # 최소 1년치
                # 5년 가격 CAGR
                start_p = float(prices.iloc[0])
                end_p   = float(prices.iloc[-1])
                years   = len(prices) / 252
                if start_p > 0 and years > 0:
                    metrics["price_cagr"] = ((end_p / start_p) ** (1 / years) - 1) * 100

                # Max Drawdown
                roll_max = prices.cummax()
                drawdown = (prices - roll_max) / roll_max * 100
                metrics["max_drawdown"] = float(drawdown.min())

        # ── 배당 이력 (분배금 CAGR) ──────────────────────────
        divs = t.dividends
        if divs is not None and not divs.empty:
            import datetime
            current_year = datetime.datetime.now().year
            divs.index = divs.index.tz_localize(None) if divs.index.tzinfo else divs.index
            annual_div = divs.groupby(divs.index.year).sum()
            # 현재 연도 제외: 아직 연간 배당이 완성되지 않아 CAGR이 왜곡됨
            # 예) 5월 기준이면 2번만 지급 → 연간 합산이 절반 → 가짜 -50% 폭락처럼 보임
            annual_div = annual_div[annual_div.index < current_year]
            # 최근 3년 CAGR (완성된 연도 기준)
            recent = annual_div.tail(4)  # 3년 CAGR이면 4개 연도 필요
            if len(recent) >= 2:
                y_start = float(recent.iloc[0])
                y_end   = float(recent.iloc[-1])
                n_years = len(recent) - 1
                if y_start > 0 and n_years > 0:
                    metrics["div_cagr_3y"] = ((y_end / y_start) ** (1 / n_years) - 1) * 100

        # ── Expense Ratio ──────────────────────────────────
        info = t.info or {}
        er   = info.get("annualReportExpenseRatio") or info.get("expenseRatio")
        if er:
            metrics["expense_ratio"] = float(er) * 100  # 소수 → %

    except Exception as e:
        log.debug(f"[etf_quality] {ticker} 지표 수집 실패: {e}")

    return metrics


# ─────────────────────────────────────────────────────────────
# 3. 종합 ETF 품질 스코어 계산
# ─────────────────────────────────────────────────────────────

# 가중치 (합계 = 1.0)
WEIGHTS = {
    "income":    0.35,  # 배당성장 — 현금흐름 설계의 핵심
    "growth":    0.25,  # 가격 성장 — Total Return
    "stability": 0.25,  # Max Drawdown — 위기 내성
    "expense":   0.15,  # 수수료 — 장기 복리 보호
}


def score_etf(ticker: str, use_cache: bool = True) -> dict:
    """
    ETF 품질 스코어링 메인 함수.

    반환값:
    {
        "ticker":           "SCHD",
        "income_score":     88,      # 분배금 성장
        "growth_score":     82,      # 가격 CAGR
        "stability_score":  79,      # Max Drawdown 내성
        "expense_score":    100,     # 수수료 효율
        "etf_quality_score": 86,     # 종합 (가중평균)
        "grade":            "PREMIUM",
        "metrics": { ... }           # 원본 수치
    }
    """
    # 1순위: 인메모리 캐시 (같은 프로세스 내 중복 호출 방지)
    if use_cache and ticker in _score_cache:
        return _score_cache[ticker]

    # 2순위: 디스크 캐시 (서버 재시작 후에도 유지, TTL 24h)
    if use_cache:
        cached = _get_cached_score(ticker)
        if cached:
            result = {**cached, "ticker": ticker, "metrics": {}}
            _score_cache[ticker] = result
            log.debug(f"[etf_quality] {ticker} 디스크 캐시 hit")
            return result

    # 3순위: yfinance 실시간 조회
    metrics = _fetch_etf_metrics(ticker)

    # 수수료: 하드코딩 우선, yfinance 수집값 fallback
    er = KNOWN_EXPENSE_RATIOS.get(ticker)
    if er is None and "expense_ratio" in metrics:
        er = metrics["expense_ratio"]

    # 차원별 점수 계산
    income_s    = _score_income_cagr(metrics.get("div_cagr_3y"))
    growth_s    = _score_price_cagr(metrics.get("price_cagr"))
    stability_s = _score_max_drawdown(metrics.get("max_drawdown"))
    expense_s   = _score_expense_ratio(er)

    # 종합 점수 (가중평균)
    total = (
        income_s    * WEIGHTS["income"]    +
        growth_s    * WEIGHTS["growth"]    +
        stability_s * WEIGHTS["stability"] +
        expense_s   * WEIGHTS["expense"]
    )
    total = round(total, 1)

    # 등급 판정
    if total >= 80:   grade = "PREMIUM"
    elif total >= 60: grade = "PASS"
    elif total >= 40: grade = "CAUTION"
    else:             grade = "REJECT"

    result = {
        "ticker":            ticker,
        "income_score":      round(income_s,    1),
        "growth_score":      round(growth_s,    1),
        "stability_score":   round(stability_s, 1),
        "expense_score":     round(expense_s,   1),
        "etf_quality_score": total,
        "grade":             grade,
        "metrics": {
            "div_cagr_3y_pct":  round(metrics.get("div_cagr_3y",    0), 2),
            "price_cagr_5y_pct": round(metrics.get("price_cagr",    0), 2),
            "max_drawdown_pct":  round(metrics.get("max_drawdown",   0), 2),
            "expense_ratio_pct": round(er, 3) if er else None,
        },
    }

    _score_cache[ticker] = result
    # yfinance로 새로 계산한 스코어는 디스크 캐시에도 저장
    _update_disk_cache(ticker, {
        "etf_quality_score": total,
        "grade":             grade,
        "income_score":      round(income_s,    1),
        "growth_score":      round(growth_s,    1),
        "stability_score":   round(stability_s, 1),
        "expense_score":     round(expense_s,   1),
    })
    log.info(
        f"[etf_quality] {ticker} → {total}점 ({grade}) | "
        f"소득:{income_s:.0f} 성장:{growth_s:.0f} 안정:{stability_s:.0f} 비용:{expense_s:.0f}"
    )
    return result


# 세션 내 캐시 (API 반복 호출 방지)
_score_cache: dict[str, dict] = {}


# ─────────────────────────────────────────────────────────────
# 4. 포트폴리오 필터링 헬퍼
# ─────────────────────────────────────────────────────────────

def filter_etf_universe(etfs: list[dict], min_score: float = 40.0) -> list[dict]:
    """
    ETF 리스트에 품질 스코어를 붙이고 기준 미달은 제외.

    - REJECT(40점 미만): 제외
    - CAUTION(40~60점): 비중 50% 감소 표시
    - PASS / PREMIUM: 정상 편입

    portfolio.py의 pick_etfs()에서 호출.
    """
    result = []
    for etf in etfs:
        ticker = etf.get("ticker", "")
        # 한국 숫자코드 ETF(395400 등)는 yfinance 지원 제한 → 기본 PASS 처리
        if ticker.isdigit():
            scored = {**etf, "etf_quality_score": 65.0, "etf_grade": "PASS", "weight_penalty": 1.0}
            result.append(scored)
            continue

        try:
            qs = score_etf(ticker)
            q  = qs["etf_quality_score"]
            g  = qs["grade"]

            if q < min_score:
                log.info(f"[etf_quality] {ticker} REJECT ({q}점) — 추천 풀 제외")
                continue

            penalty = 0.5 if g == "CAUTION" else 1.0
            scored  = {
                **etf,
                "etf_quality_score": q,
                "etf_grade":         g,
                "weight_penalty":    penalty,   # portfolio.py에서 비중에 곱함
                "income_score":      qs["income_score"],
                "growth_score":      qs["growth_score"],
                "stability_score":   qs["stability_score"],
                "expense_score":     qs["expense_score"],
            }
            result.append(scored)
        except Exception as e:
            log.warning(f"[etf_quality] {ticker} 스코어링 실패({e}) → 기본 PASS")
            result.append({**etf, "etf_quality_score": 60.0, "etf_grade": "PASS", "weight_penalty": 1.0})

    return result


# ─────────────────────────────────────────────────────────────
# 5. 빠른 확인용 CLI
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    tickers = sys.argv[1:] if len(sys.argv) > 1 else ["SCHD", "VYM", "JEPI", "TLT", "BND"]

    print("\n" + "=" * 65)
    print("  ETF Quality Scoring")
    print("=" * 65)
    print(f"  {'티커':<8} {'종합':>5} {'등급':<9} {'소득':>5} {'성장':>5} {'안정':>5} {'비용':>5}")
    print("  " + "-" * 63)

    for tk in tickers:
        r = score_etf(tk)
        print(
            f"  {tk:<8} {r['etf_quality_score']:>5.1f} {r['grade']:<9} "
            f"{r['income_score']:>5.1f} {r['growth_score']:>5.1f} "
            f"{r['stability_score']:>5.1f} {r['expense_score']:>5.1f}"
        )
        m = r["metrics"]
        print(
            f"           배당CAGR:{m['div_cagr_3y_pct']:+.1f}%  "
            f"가격CAGR:{m['price_cagr_5y_pct']:+.1f}%  "
            f"MDD:{m['max_drawdown_pct']:.1f}%  "
            f"수수료:{m['expense_ratio_pct']}%"
        )
    print("=" * 65)

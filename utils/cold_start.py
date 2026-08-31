"""
cold_start.py
=============
신규 상장 / 데이터 부족 종목 처리.

문제: XGBoost 3-class 모델은 최소 3년치 재무데이터가 필요하다.
      배당 이력이 짧은 신규 상장 기업은 모델을 돌릴 수 없다.

해결 전략 (4-단계):
  ① 데이터 부족 감지:  dividend_dataset.csv에서 ticker별 연도 수 확인
  ② ML 예측 제외:       is_cold_start=True 종목에 XGBoost 미적용
  ③ 섹터 Median 대체:   동일 섹터 + 동일 성향 종목들의 overall_score 중앙값 사용
  ④ 데이터 축적 트리거: min_years 이상 쌓이면 자동으로 ML 편입 (flag 제거)

왜 섹터 Median인가:
  - 단순 제외: 신규 고배당주 (ex. 최근 IPO 유틸리티) 못 편입 → 서비스 공백
  - 섹터 평균: 같은 섹터의 검증된 종목들과 유사한 위험 수준으로 보수적 가정
  - 대안 검토:
      * Exclude entirely: 서비스 완전성 훼손
      * Transfer Learning (US 모델 → KR): 구현 복잡도 높음, 발표까지 시간 부족
      * Rule-based score only: 현재 채택 (단순하고 설명 가능)
  - 결론: 섹터 Median rule-score + cold_start 뱃지 표시가 최적

사용 예:
    from utils.cold_start import get_cold_start_info, apply_cold_start_flags

    flags = get_cold_start_info(["005930", "999999"])
    # {"005930": {"is_cold_start": False, "data_years": 10, ...},
    #  "999999": {"is_cold_start": True,  "data_years": 1, ...}}
"""
from __future__ import annotations
import os
import logging
from functools import lru_cache

import pandas as pd

log = logging.getLogger(__name__)

BASE         = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_CSV  = os.path.join(BASE, "data", "dividend_dataset.csv")
RANKING_CSV  = os.path.join(BASE, "data", "ranking.csv")

MIN_YEARS    = 3     # XGBoost 최소 학습 연도 수
SECTOR_COL   = "sector"   # ranking.csv 섹터 컬럼 이름 후보


# ─────────────────────────────────────────────────────────────
# 1. 종목별 데이터 연도 수 (dividend_dataset.csv 기준)
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_data_years() -> dict[str, int]:
    """
    dividend_dataset.csv → {stock_code: n_years}
    파일 없으면 빈 dict (전 종목 cold_start=False로 처리).
    """
    if not os.path.exists(DATASET_CSV):
        return {}
    try:
        df = pd.read_csv(DATASET_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        return df.groupby("stock_code")["year"].nunique().to_dict()
    except Exception as e:
        log.warning("cold_start: dividend_dataset 로드 실패 %s", e)
        return {}


# ─────────────────────────────────────────────────────────────
# 2. 섹터 Median Score (ranking.csv 기준)
# ─────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_sector_medians() -> dict[str, float]:
    """
    ranking.csv에서 섹터별 overall_score 중앙값 계산.
    Cold Start 종목에 섹터 평균 점수를 부여할 때 사용.
    """
    if not os.path.exists(RANKING_CSV):
        return {}
    try:
        df = pd.read_csv(RANKING_CSV, dtype={"stock_code": str})
        df["stock_code"] = df["stock_code"].str.zfill(6)
        # 섹터 컬럼 찾기 (sector / 섹터 / industry)
        sec_col = None
        for c in [SECTOR_COL, "섹터", "industry", "sector_name"]:
            if c in df.columns:
                sec_col = c
                break
        if sec_col is None or "overall_score" not in df.columns:
            return {}
        df["overall_score"] = pd.to_numeric(df["overall_score"], errors="coerce")
        return (
            df.groupby(sec_col)["overall_score"]
            .median()
            .dropna()
            .round(1)
            .to_dict()
        )
    except Exception as e:
        log.warning("cold_start: sector_median 로드 실패 %s", e)
        return {}


# ─────────────────────────────────────────────────────────────
# 3. 종목별 Cold Start 정보 반환
# ─────────────────────────────────────────────────────────────

def get_cold_start_info(
    tickers: list[str],
    sector_map: dict[str, str] | None = None,
) -> dict[str, dict]:
    """
    각 ticker의 Cold Start 여부와 메타 정보를 반환.

    Args:
        tickers:    종목 코드 리스트 (6자리 zero-padded)
        sector_map: {ticker: sector_name} — ranking.csv 없을 때 직접 전달

    Returns:
        {
            "005930": {
                "is_cold_start": False,
                "data_years": 10,
                "min_years": 3,
                "ml_eligible": True,
                "sector_score": None,        # cold start 아니면 None
                "warning": None,
            },
            "999999": {
                "is_cold_start": True,
                "data_years": 1,
                "min_years": 3,
                "ml_eligible": False,
                "sector_score": 62.0,        # 섹터 중앙값 대체 점수
                "warning": "데이터 1년 — ML 예측 제외, 섹터 중앙값 사용",
            },
        }
    """
    data_years    = _load_data_years()
    sector_medians = _load_sector_medians()

    result: dict[str, dict] = {}
    for t in tickers:
        t = str(t).zfill(6)
        n = data_years.get(t, MIN_YEARS)   # 기록 없으면 최소 기준값
        is_cold = n < MIN_YEARS

        sector = (sector_map or {}).get(t, "")
        sec_score = sector_medians.get(sector) if is_cold and sector else None
        if is_cold and sec_score is None:
            # 섹터 모르면 전체 중앙값 (~62점 전후)
            all_scores = list(sector_medians.values())
            sec_score = round(sorted(all_scores)[len(all_scores)//2], 1) if all_scores else 55.0

        result[t] = {
            "is_cold_start": is_cold,
            "data_years":    n,
            "min_years":     MIN_YEARS,
            "ml_eligible":   not is_cold,
            "sector_score":  sec_score if is_cold else None,
            "warning":       (
                f"데이터 {n}년 — ML 예측 제외, 섹터 중앙값({sec_score}점) 사용"
                if is_cold else None
            ),
        }
    return result


# ─────────────────────────────────────────────────────────────
# 4. 추천 목록에 Cold Start 플래그 부착
# ─────────────────────────────────────────────────────────────

def apply_cold_start_flags(stocks: list[dict]) -> list[dict]:
    """
    pick_kr_stocks() 결과에 cold_start 정보를 병합.

    사용:
        stocks = pick_kr_stocks(risk, n)
        stocks = apply_cold_start_flags(stocks)

    각 stock에 추가되는 필드:
        cold_start:      bool   — True이면 ML 미적용
        data_years:      int    — 보유 연도 수
        cold_start_warn: str | None
    """
    tickers = [str(s.get("ticker", "")).zfill(6) for s in stocks]
    sector_map = {str(s.get("ticker","")).zfill(6): s.get("sector","") for s in stocks}
    info = get_cold_start_info(tickers, sector_map)

    result = []
    for s in stocks:
        t = str(s.get("ticker", "")).zfill(6)
        cs = info.get(t, {})
        s = dict(s)
        s["cold_start"]      = cs.get("is_cold_start", False)
        s["data_years"]      = cs.get("data_years", MIN_YEARS)
        s["cold_start_warn"] = cs.get("warning")

        # Cold Start 종목: overall_score를 섹터 중앙값으로 교체
        # ml_status를 "NO_DATA"로 설정해 프론트엔드에서 구분 가능
        if cs.get("is_cold_start"):
            if cs.get("sector_score") is not None:
                s["overall_score"] = cs["sector_score"]
            s["ml_status"] = "NO_DATA"
            log.info("cold_start: %s (%d년) → sector_score=%s",
                     t, cs.get("data_years", 0), cs.get("sector_score"))
        result.append(s)
    return result


# ─────────────────────────────────────────────────────────────
# 5. Pipeline Filter 연동 (pick_kr_stocks 후 호출용)
# ─────────────────────────────────────────────────────────────

def enrich_with_cold_start(
    stocks: list[dict],
    include_cold_start: bool = True,
) -> list[dict]:
    """
    apply_cold_start_flags의 래퍼.
    include_cold_start=False면 cold_start 종목 제외 (보수적 모드).
    """
    flagged = apply_cold_start_flags(stocks)
    if not include_cold_start:
        flagged = [s for s in flagged if not s.get("cold_start", False)]
    return flagged


if __name__ == "__main__":
    # 간단 CLI 테스트
    import sys
    tickers = sys.argv[1:] or ["005930", "024800", "000000"]
    info = get_cold_start_info(tickers)
    for t, v in info.items():
        status = "COLD_START" if v["is_cold_start"] else "ML_OK"
        print(f"{t}: {status} | {v['data_years']}년 | sector_score={v['sector_score']}")

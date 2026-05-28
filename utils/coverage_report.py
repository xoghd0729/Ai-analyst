"""
utils/coverage_report.py
━━━━━━━━━━━━━━━━━━━━━━━━

백테스팅 데이터 가용성 자동 진단.

목적:
  어느 종목이 어느 연도까지 실데이터를 가지고 있는지,
  합성 데이터에 얼마나 의존하는지 한 화면에서 보여준다.

  발표 시: "데이터 정직성"을 정량으로 증명하는 근거.
  운영 시: 새 종목 추가 후 즉시 가용성 검증.

사용:
  from utils.coverage_report import generate_coverage_report
  report = generate_coverage_report(min_real_pct=70)
  # data/historical_coverage_report.json 자동 저장
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = ROOT / "data" / "historical_coverage_report.json"


@dataclass
class TickerCoverage:
    ticker:               str
    name:                 str
    asset_class:          str
    data_start_year:      int | None
    data_end_year:        int | None
    real_years:           int
    synthetic_years:      int
    nan_years:            int
    coverage_pct:         float
    synthetic_pct:        float
    inception_year:       int | None
    has_synthetic_proxy:  bool
    quality_grade:        str  # "A" / "B" / "C" / "D"


def _grade_quality(real_years: int, synth_years: int, nan_years: int) -> str:
    """
    데이터 품질 등급.
    A: 실데이터 ≥ 18년, 합성 0
    B: 실데이터 ≥ 12년, 합성 < 5년
    C: 실데이터 ≥ 6년 또는 합성 가능
    D: NaN 위주
    """
    total = real_years + synth_years + nan_years
    if total == 0:
        return "D"
    if real_years >= 18 and synth_years == 0:
        return "A"
    if real_years >= 12 and synth_years < 5:
        return "B"
    if real_years >= 6 or synth_years > 0:
        return "C"
    return "D"


def _detect_real_years(yearly_returns: dict, inception: int | None,
                       start: int, end: int) -> tuple[int, int, int]:
    """
    yearly_returns 딕셔너리 분석 → (실, 합성, NaN) 연도 수.

    규칙:
      - 값이 NaN 이면 nan_years
      - inception 이전 연도는 synthetic_years (값이 있어도)
      - 나머지는 real_years
    """
    real = synth = nan = 0
    for year in range(start, end + 1):
        val = yearly_returns.get(year) if yearly_returns else None
        if val is None or (isinstance(val, float) and math.isnan(val)):
            nan += 1
        elif inception is not None and year < inception:
            synth += 1
        else:
            real += 1
    return real, synth, nan


def generate_coverage_report(
    start_year: int = 2005,
    end_year:   int = 2024,
    min_real_pct: float = 70.0,
    save_path: Path | None = None,
) -> dict:
    """
    전체 자산에 대해 coverage 리포트 생성.

    Args:
        start_year/end_year: 분석 기간
        min_real_pct: 이 미만이면 ⚠ 경고
        save_path: JSON 저장 위치 (None → 기본 경로)

    Returns:
        {
            "generated_at": ISO timestamp,
            "period": "2005~2024",
            "summary": {
                "total_tickers": int,
                "avg_coverage_pct": float,
                "grade_A_count": int,
                "grade_B_count": int,
                "grade_C_count": int,
                "grade_D_count": int,
                "warnings_below_min": [ticker, ...],
            },
            "by_ticker": [TickerCoverage.asdict(), ...],
        }
    """
    from utils.backtesting import (
        _ASSET_HIST_RETURNS,
        _ASSET_INCEPTION_YEAR,
        _SYNTHETIC_PROXY_MAP,
    )

    # asset_class 매핑 (간단)
    asset_class_map = {
        "SCHD": "us_div_etf", "VYM": "us_div_etf", "DGRO": "us_div_etf",
        "JEPI": "us_div_etf", "JEPQ": "us_div_etf", "SPYD": "us_div_etf",
        "HDV": "us_div_etf",  "NOBL": "us_div_etf", "QYLD": "us_div_etf",
        "KO": "us_stock", "JNJ": "us_stock", "PG": "us_stock",
        "ABBV": "us_stock", "MCD": "us_stock",
        "O": "us_reit", "VNQ": "us_reit",
        "TLT": "bond", "BND": "bond", "AGG": "bond",
    }

    coverages: list[TickerCoverage] = []
    name_map = {
        "279530": "KODEX 고배당", "210780": "TIGER 코스피고배당",
        "161510": "ARIRANG 고배당주", "266390": "KBSTAR 고배당",
        "458730": "TIGER 미국배당다우존스", "329200": "TIGER 리츠부동산인프라",
        "069500": "KODEX 200", "360750": "TIGER 미국S&P500",
        "251600": "KODEX 미국S&P500배당귀족", "360200": "TIGER 코스피",
    }

    for ticker, yearly_data in _ASSET_HIST_RETURNS.items():
        inception = _ASSET_INCEPTION_YEAR.get(ticker)
        proxy_list = _SYNTHETIC_PROXY_MAP.get(ticker, [])

        real, synth, nan = _detect_real_years(
            yearly_data, inception, start_year, end_year
        )
        total = real + synth + nan
        coverage_pct = round(100 * (real + synth) / total, 1) if total else 0.0
        synthetic_pct = round(100 * synth / total, 1) if total else 0.0

        data_years = sorted(
            y for y, v in yearly_data.items()
            if v is not None and not (isinstance(v, float) and math.isnan(v))
        )

        coverages.append(TickerCoverage(
            ticker=ticker,
            name=name_map.get(ticker, ticker),
            asset_class=asset_class_map.get(ticker, "kr_etf" if ticker.isdigit() else "stock"),
            data_start_year=data_years[0] if data_years else None,
            data_end_year=data_years[-1] if data_years else None,
            real_years=real,
            synthetic_years=synth,
            nan_years=nan,
            coverage_pct=coverage_pct,
            synthetic_pct=synthetic_pct,
            inception_year=inception,
            has_synthetic_proxy=len(proxy_list) > 0,
            quality_grade=_grade_quality(real, synth, nan),
        ))

    # 요약 통계
    grades = [c.quality_grade for c in coverages]
    avg_cov = (
        sum(c.coverage_pct for c in coverages) / len(coverages)
        if coverages else 0.0
    )
    warnings = [
        c.ticker for c in coverages
        if (100 * c.real_years / (end_year - start_year + 1)) < min_real_pct
    ]

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "period":       f"{start_year}~{end_year}",
        "summary": {
            "total_tickers":      len(coverages),
            "avg_coverage_pct":   round(avg_cov, 1),
            "grade_A_count":      grades.count("A"),
            "grade_B_count":      grades.count("B"),
            "grade_C_count":      grades.count("C"),
            "grade_D_count":      grades.count("D"),
            "warnings_below_min": warnings,
            "min_real_pct_threshold": min_real_pct,
        },
        "by_ticker": [asdict(c) for c in coverages],
    }

    target = save_path or REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    log.info("Coverage 리포트 저장: %s", target)
    log.info("  종목: %d / 평균 커버리지: %.1f%% / A:%d B:%d C:%d D:%d",
             len(coverages), avg_cov,
             grades.count("A"), grades.count("B"),
             grades.count("C"), grades.count("D"))

    return report


def get_high_quality_tickers(min_grade: str = "B") -> list[str]:
    """
    품질 등급 이상의 티커만 반환.
    백테스팅 시 "고품질만 사용" 옵션에 활용.
    """
    grade_rank = {"A": 4, "B": 3, "C": 2, "D": 1}
    min_rank = grade_rank.get(min_grade, 3)

    try:
        if not REPORT_PATH.exists():
            generate_coverage_report()
        with REPORT_PATH.open(encoding="utf-8") as f:
            report = json.load(f)
        return [
            c["ticker"] for c in report["by_ticker"]
            if grade_rank.get(c["quality_grade"], 1) >= min_rank
        ]
    except Exception as e:
        log.warning("get_high_quality_tickers 실패: %s", e)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    report = generate_coverage_report()
    print("\n━━━ 요약 ━━━")
    for k, v in report["summary"].items():
        print(f"  {k}: {v}")

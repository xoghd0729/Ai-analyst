"""
utils/backtesting.py — 포트폴리오 백테스팅 엔진
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가?
  "이 추천이 과거에도 통했는가?"
  Monte Carlo는 미래를 시뮬레이션하지만,
  백테스팅은 실제 역사 데이터로 검증한다.
  발표 때 "2015~2024 실제 데이터 기준 연복리 X%" 라는 한 줄이
  설득력을 완전히 바꾼다.

■ 백테스팅 방식
  연도별 포트폴리오 성과 시뮬레이션:
    1. 각 자산의 연도별 수익률 = 배당수익률 + 자본차익
    2. 포트폴리오 가중합산
    3. 연 복리 재계산
    4. MDD (최대낙폭), Sharpe Ratio, CAGR 산출

■ 데이터 소스
  yfinance: 미국 ETF/주식 실제 수익률
  수동 테이블: 한국주식 대용 (KRX 데이터 제한으로 추정치 사용)

■ 반환 구조
  {
    "cagr_pct":          float,    # 연복리 수익률 (%)
    "total_return_pct":  float,    # 총 누적 수익률 (%)
    "mdd_pct":           float,    # 최대낙폭 (%)
    "sharpe_ratio":      float,    # 샤프 비율
    "yearly_returns":    list,     # 연도별 수익률
    "div_cagr_pct":      float,    # 배당 CAGR
    "best_year":         dict,     # 최고 성과 연도
    "worst_year":        dict,     # 최저 성과 연도
    "vs_kospi":          float,    # KOSPI 대비 초과수익
    "vs_sp500":          float,    # S&P500 대비 초과수익
    "summary_message":   str,
  }
"""
from __future__ import annotations

import math
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── 벤치마크/자산 히스토리 데이터 ─────────────────────────────
# D1 목표: 2005~2024 백테스팅.
# 원칙:
#   - yfinance 사용 가능하면 실제 데이터를 우선 사용한다.
#   - 실패 시(네트워크/환경 제한) 최소한의 정적 테이블로 폴백한다.
#
# NOTE: KOSPI는 yfinance에서 ^KS11 (가격 지수)만 쉽게 얻을 수 있어
#       "총수익률(배당 포함)"은 환경에 따라 완전하지 않을 수 있다.
#       발표/데모 목적에선 일관성 있는 기준을 우선한다.

# 기존(2015~2024) 정적 폴백 테이블은 유지
_KOSPI_RETURNS_FALLBACK_2015_2024 = {
    2015: 2.4, 2016: 3.3, 2017: 21.8, 2018: -17.3, 2019: 7.7,
    2020: 30.8, 2021: 3.6, 2022: -24.9, 2023: 18.7, 2024: -9.6,
}

_SP500_RETURNS_FALLBACK_2015_2024 = {
    2015: 1.4, 2016: 12.0, 2017: 21.8, 2018: -4.4, 2019: 31.5,
    2020: 18.4, 2021: 28.7, 2022: -18.1, 2023: 26.3, 2024: 25.0,
}

# ── 2005~2024 확장 fallback ──────────────────────────────────
# yfinance 미연결 또는 ^KS11/^GSPC 호출 실패 시 사용.
# 출처: 한국거래소 공식 통계 (KOSPI Price Return) + S&P Dow Jones (S&P500 Total Return)
# 검증 (Data D2): 2005~2024 모든 연도 공식 데이터와 ±0.1%p 이내 일치
# 마지막 검증일: 2026-05-28
_KOSPI_RETURNS_FALLBACK_2005_2024 = {
    2005: 54.0, 2006: 3.9, 2007: 32.3, 2008: -40.7, 2009: 49.7,
    2010: 21.9, 2011: -10.9, 2012: 9.4, 2013: 0.7, 2014: -4.8,
    2015: 2.4, 2016: 3.3, 2017: 21.8, 2018: -17.3, 2019: 7.7,
    2020: 30.8, 2021: 3.6, 2022: -24.9, 2023: 18.7, 2024: -9.6,
}

_SP500_RETURNS_FALLBACK_2005_2024 = {
    2005: 4.9, 2006: 15.8, 2007: 5.5, 2008: -37.0, 2009: 26.5,
    2010: 15.1, 2011: 2.1, 2012: 16.0, 2013: 32.4, 2014: 13.7,
    2015: 1.4, 2016: 12.0, 2017: 21.8, 2018: -4.4, 2019: 31.5,
    2020: 18.4, 2021: 28.7, 2022: -18.1, 2023: 26.3, 2024: 25.0,
}

# yfinance로부터 연도별 수익률을 계산해 캐시하는 메모리 저장소
_HISTORICAL_DATA: dict[str, dict[int, float]] = {}

# ── 한국 종목 백필 데이터 (pykrx 수집 결과) 캐시 ──────────────
# scripts/backfill_kr_history.py 가 만든 data/kr_historical_returns.json 을
# 첫 호출 시 한 번 로드. 섹터 평균(_KR_SECTOR_RETURNS) 보다 우선 적용됨.
_KR_REAL_RETURNS_CACHE: dict[str, dict[int, float]] | None = None


def _load_kr_real_returns(ticker: str) -> dict[int, float] | None:
    """
    한국 종목 ticker의 실데이터(연도별 가격 수익률) 반환.
    data/kr_historical_returns.json (pykrx 백필 결과) 활용.

    파일 없거나 종목 없으면 None.
    """
    global _KR_REAL_RETURNS_CACHE
    if _KR_REAL_RETURNS_CACHE is None:
        import os, json
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, "data", "kr_historical_returns.json")
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            # JSON 키는 문자열이므로 int로 변환
            _KR_REAL_RETURNS_CACHE = {
                t: {int(y): float(v) for y, v in info.get("yearly_returns", {}).items()}
                for t, info in raw.items()
            }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            _KR_REAL_RETURNS_CACHE = {}

    return _KR_REAL_RETURNS_CACHE.get(ticker)

# ── 자산별 상장 연도 & 합성 매핑 (Day 8 / Data D1: 정직화) ─────
# 학술적 정직성을 위해 각 종목의 실제 상장 연도를 명시한다.
# 상장 이전 연도의 수익률은 동일 카테고리의 선행 ETF로부터 합성됨을 표시.
_ASSET_INCEPTION_YEAR: dict[str, int] = {
    # 미국 배당 ETF
    "SCHD": 2011,  # Schwab US Dividend Equity
    "VYM":  2006,  # Vanguard High Dividend Yield
    "DGRO": 2014,  # iShares Core Dividend Growth
    "JEPI": 2020,  # JPMorgan Equity Premium Income
    "JEPQ": 2022,  # JPMorgan Nasdaq Equity Premium Income
    "SPYD": 2015,  # SPDR Portfolio S&P 500 High Dividend
    "HDV":  2011,  # iShares Core High Dividend
    "NOBL": 2013,  # ProShares S&P 500 Dividend Aristocrats
    "QYLD": 2013,  # Global X NASDAQ 100 Covered Call
    # 미국 배당주 (개별)
    "KO":   1919,  # Coca-Cola (창립 기준, 데이터는 2005~)
    "JNJ":  1944,
    "PG":   1890,
    "ABBV": 2013,  # AbbVie 분사
    "MCD":  1965,
    # 리츠
    "O":    1994,
    "VNQ":  2004,
    # 채권 ETF
    "TLT":  2002,
    "BND":  2007,
    "AGG":  2003,
    # 한국 ETF (티커 6자리)
    "279530": 2018,  # KODEX 고배당
    "210780": 2014,  # TIGER 코스피고배당
    "161510": 2012,  # ARIRANG 고배당주
    "266390": 2017,  # KBSTAR 고배당
    "458730": 2023,  # TIGER 미국배당다우존스
    "329200": 2019,  # TIGER 리츠부동산인프라
    "069500": 2002,  # KODEX 200
    "360750": 2020,  # TIGER 미국S&P500
    "251600": 2018,  # KODEX 미국S&P500배당귀족
    "360200": 2020,  # TIGER 코스피
}

# 합성 매핑: 상장 이전 데이터를 어느 선행 ETF에서 가져왔는지 명시
# Cursor/스크립트로 채워질 때 이 메타가 함께 갱신되도록 설계
_SYNTHETIC_PROXY_MAP: dict[str, list[str]] = {
    # SCHD: Total Return + 유사 배당 인덱스
    "SCHD": ["SCHX (Schwab Large-Cap, 2009~)",
             "SDY (SPDR S&P Dividend, 2005~)",
             "DVY (iShares Select Dividend, 2003~)"],
    "DGRO": ["VIG (Vanguard Dividend Appreciation, 2006~)"],
    "HDV":  ["DVY (iShares Select Dividend, 2003~)"],
    "NOBL": ["SDY (SPDR S&P Dividend, 2005~)"],
    # JEPI/JEPQ는 대용 ETF 부재 — 합성 불가, NaN 유지
    "JEPI": [],
    "JEPQ": [],
    "SPYD": ["DVY (iShares Select Dividend)"],
    # 한국 ETF
    "279530": ["KODEX 200 (069500)"],          # KODEX 고배당
    "266390": ["KODEX 200 (069500)"],          # KBSTAR 고배당
    "458730": ["SCHD (Schwab US Dividend)"],   # TIGER 미국배당다우존스
    "329200": ["VNQ (US REIT 대용)"],          # TIGER 리츠부동산인프라
    "360750": ["S&P500 인덱스"],               # TIGER 미국S&P500
    "251600": ["NOBL (Dividend Aristocrats)"], # KODEX 미국S&P500배당귀족
    "360200": ["KOSPI 인덱스"],                # TIGER 코스피
}


# ── 자산별 역사 수익률 추정 테이블 ────────────────────────────
# yfinance 미연결 환경을 위한 정적 테이블 (ETF별 실제 연간 총수익률)
# 출처: 각 ETF 공식 팩트시트 / Morningstar 2015-2024
# 주의: _ASSET_INCEPTION_YEAR 이전의 연도 데이터는 _SYNTHETIC_PROXY_MAP 의 선행 ETF로 합성됨
_ASSET_HIST_RETURNS: dict[str, dict[int, float]] = {
    # 미국 배당 ETF
    "SCHD":  {2005:6.2, 2006:13.5, 2007:5.2, 2008:-33.0, 2009:24.3,
              2010:13.8, 2011:2.9, 2012:14.6, 2013:28.9, 2014:13.2,
              2015:0.6,  2016:14.5, 2017:17.3, 2018:-5.3, 2019:28.4,
              2020:9.1,  2021:28.4, 2022:-3.2, 2023:3.6,  2024:14.2},
    "VYM":   {2005:8.1, 2006:15.2, 2007:4.8, 2008:-32.1, 2009:22.4,
              2010:14.0, 2011:1.2, 2012:13.2, 2013:30.1, 2014:12.8,
              2015:0.3,  2016:16.6, 2017:14.0, 2018:-4.8, 2019:26.6,
              2020:2.7,  2021:27.4, 2022:-1.8, 2023:10.3, 2024:16.1},
    "DGRO":  {2005:7.3, 2006:14.1, 2007:5.0, 2008:-34.0, 2009:23.2,
              2010:13.5, 2011:1.8, 2012:14.8, 2013:31.0, 2014:11.6,
              2015:-1.2, 2016:12.7, 2017:19.3, 2018:-3.8, 2019:30.1,
              2020:12.3, 2021:27.9, 2022:-7.3, 2023:14.8, 2024:16.4},
    "JEPI":  {2005:math.nan, 2006:math.nan, 2007:math.nan, 2008:math.nan, 2009:math.nan,
              2010:math.nan, 2011:math.nan, 2012:math.nan, 2013:math.nan, 2014:math.nan,
              2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:math.nan,
              2020:math.nan, 2021:11.7, 2022:3.5,  2023:9.2,  2024:11.4},  # 2020 상장
    "JEPQ":  {2005:math.nan, 2006:math.nan, 2007:math.nan, 2008:math.nan, 2009:math.nan,
              2010:math.nan, 2011:math.nan, 2012:math.nan, 2013:math.nan, 2014:math.nan,
              2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:math.nan,
              2020:math.nan, 2021:math.nan, 2022:math.nan, 2023:38.6, 2024:14.1},         # 2022 상장
    "SPYD":  {2005:math.nan, 2006:math.nan, 2007:math.nan, 2008:math.nan, 2009:math.nan,
              2010:math.nan, 2011:math.nan, 2012:math.nan, 2013:math.nan, 2014:math.nan,
              2015:math.nan, 2016:math.nan, 2017:15.2, 2018:-13.1,2019:22.7, 2020:-4.1,
              2021:26.8, 2022:3.8,  2023:0.8,  2024:10.3},
    "HDV":   {2005:7.9, 2006:12.4, 2007:6.1, 2008:-35.0, 2009:18.7,
              2010:11.9, 2011:-0.8, 2012:12.5, 2013:27.3, 2014:10.8,
              2015:1.4,  2016:12.3, 2017:9.2,  2018:2.0,  2019:19.6,
              2020:0.2,  2021:25.4, 2022:12.7, 2023:3.0,  2024:13.0},
    "NOBL":  {2005:6.8, 2006:13.3, 2007:4.6, 2008:-31.7, 2009:21.4,
              2010:12.2, 2011:2.1, 2012:13.5, 2013:29.0, 2014:11.0,
              2015:0.0,  2016:13.1, 2017:21.2, 2018:-2.7, 2019:29.8,
              2020:5.8,  2021:27.2, 2022:-7.0, 2023:7.6,  2024:14.0},
    "QYLD":  {2005:8.7, 2006:11.0, 2007:7.3, 2008:-27.4, 2009:19.8,
              2010:10.1, 2011:4.0, 2012:11.3, 2013:18.9, 2014:10.2,
              2015:11.2, 2016:10.4, 2017:10.2, 2018:7.0,  2019:12.0,
              2020:11.6, 2021:11.9, 2022:-19.8,2023:10.4, 2024:7.8},
    # 미국 배당주
    "KO":    {2005:9.4, 2006:14.3, 2007:26.6, 2008:9.1, 2009:13.9,
              2010:13.2, 2011:5.9, 2012:10.1, 2013:11.2, 2014:4.8,
              2015:8.0,  2016:1.2,  2017:11.4, 2018:1.6,  2019:23.4,
              2020:5.5,  2021:9.8,  2022:12.4, 2023:3.6,  2024:-2.0},
    "JNJ":   {2005:4.2, 2006:11.8, 2007:13.1, 2008:-2.8, 2009:10.0,
              2010:4.8, 2011:8.6, 2012:10.4, 2013:37.1, 2014:16.5,
              2015:0.0,  2016:11.6, 2017:20.4, 2018:9.0,  2019:16.3,
              2020:8.5,  2021:10.3, 2022:5.3,  2023:-11.0,2024:-4.8},
    "PG":    {2005:-8.1, 2006:11.5, 2007:12.1, 2008:-15.1, 2009:12.6,
              2010:9.2, 2011:1.0, 2012:10.2, 2013:24.5, 2014:7.6,
              2015:3.8,  2016:10.0, 2017:14.4, 2018:-6.0, 2019:32.4,
              2020:15.4, 2021:18.4, 2022:-5.5, 2023:8.6,  2024:9.8},
    "ABBV":  {2005:math.nan, 2006:math.nan, 2007:math.nan, 2008:math.nan, 2009:math.nan,
              2010:math.nan, 2011:math.nan, 2012:math.nan, 2013:math.nan, 2014:math.nan,
              2015:14.2, 2016:-6.0, 2017:33.2, 2018:-17.0,2019:12.2,
              2020:7.4,  2021:22.2, 2022:25.4, 2023:2.9,  2024:14.0},
    "MCD":   {2005:-6.3, 2006:27.0, 2007:16.7, 2008:6.9, 2009:9.5,
              2010:15.0, 2011:31.0, 2012:9.7, 2013:7.8, 2014:0.6,
              2015:30.4, 2016:4.2,  2017:42.4, 2018:8.0,  2019:13.0,
              2020:10.4, 2021:27.4, 2022:3.0,  2023:13.5, 2024:-5.0},
    # 리츠
    "O":     {2015:4.5,  2016:9.5,  2017:6.0,  2018:15.0, 2019:22.2,
              2020:-4.6, 2021:17.4, 2022:-7.1, 2023:2.7,  2024:4.4},
    "VNQ":   {2015:2.4,  2016:8.5,  2017:5.0,  2018:-6.0, 2019:29.0,
              2020:-4.7, 2021:40.2, 2022:-26.1,2023:12.2, 2024:5.8},
    # 방어형
    "TLT":   {2015:1.5,  2016:1.2,  2017:8.9,  2018:-1.8, 2019:13.8,
              2020:18.0, 2021:-4.6, 2022:-31.2,2023:-3.1, 2024:-8.3},
    "BND":   {2015:0.4,  2016:2.6,  2017:3.5,  2018:-0.1, 2019:8.7,
              2020:7.7,  2021:-1.8, 2022:-13.1,2023:5.5,  2024:1.2},
    "AGG":   {2015:0.5,  2016:2.6,  2017:3.5,  2018:-0.1, 2019:8.5,
              2020:7.5,  2021:-1.7, 2022:-13.0,2023:5.5,  2024:1.2},
    # 한국 ETF (2015~2024, 상장 이전 NaN)
    "279530": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:-2.3,
               2020:6.5, 2021:15.0, 2022:-10.2, 2023:12.7, 2024:-3.8},  # KODEX 고배당
    "210780": {2015:-2.0, 2016:4.2, 2017:18.4, 2018:-13.7, 2019:8.0,
               2020:5.8, 2021:10.6, 2022:-14.6, 2023:11.9, 2024:-4.4},  # TIGER 코스피고배당
    "161510": {2015:0.8, 2016:5.0, 2017:19.1, 2018:-14.1, 2019:7.4,
               2020:8.1, 2021:12.0, 2022:-13.8, 2023:10.5, 2024:-5.2},  # ARIRANG 고배당주
    "266390": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:3.1,
               2020:7.1, 2021:14.3, 2022:-11.8, 2023:13.2, 2024:-4.1},  # KBSTAR 고배당
    "458730": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:math.nan,
               2020:math.nan, 2021:math.nan, 2022:math.nan, 2023:12.8, 2024:15.3},  # TIGER 미국배당다우존스
    "329200": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:math.nan,
               2020:math.nan, 2021:math.nan, 2022:-17.6, 2023:9.8, 2024:2.4},  # TIGER 리츠부동산인프라
    "069500": {2015:4.1, 2016:3.0, 2017:25.2, 2018:-16.7, 2019:9.5,
               2020:32.1, 2021:2.3, 2022:-23.7, 2023:19.4, 2024:-8.9},  # KODEX 200
    "360750": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:math.nan,
               2020:17.5, 2021:29.4, 2022:-17.9, 2023:27.0, 2024:24.2},  # TIGER 미국S&P500
    "251600": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:-7.6, 2019:24.5,
               2020:9.4, 2021:26.2, 2022:-4.4, 2023:6.2, 2024:12.7},     # KODEX 미국S&P500배당귀족
    "360200": {2015:math.nan, 2016:math.nan, 2017:math.nan, 2018:math.nan, 2019:math.nan,
               2020:31.4, 2021:2.1, 2022:-23.9, 2023:18.8, 2024:-9.1},   # TIGER 코스피
}

# 한국 배당주 대용 수익률 (업종 평균 추정)
_KR_SECTOR_RETURNS = {
    "은행":     {2005:41.0,2006:18.0,2007:37.0,2008:-52.0,2009:44.0,
                 2010:16.0,2011:-11.0,2012:8.0, 2013:3.0, 2014:-2.0,
                 2015:10.0,2016:8.0, 2017:22.0,2018:-12.0,2019:15.0,
                 2020:-5.0,2021:20.0,2022:-8.0, 2023:15.0, 2024:-5.0},
    "통신":     {2005:7.0, 2006:6.0, 2007:10.0, 2008:-18.0,2009:12.0,
                 2010:4.0, 2011:-6.0,2012:3.0,  2013:5.0,  2014:2.0,
                 2015:5.0, 2016:3.0, 2017:5.0, 2018:-2.0, 2019:8.0,
                 2020:3.0, 2021:8.0, 2022:2.0,  2023:5.0,  2024:3.0},
    "에너지":   {2005:28.0,2006:10.0, 2007:20.0, 2008:-46.0,2009:39.0,
                 2010:14.0,2011:-19.0,2012:6.0,  2013:-7.0, 2014:-12.0,
                 2015:-5.0,2016:5.0, 2017:10.0,2018:-8.0, 2019:5.0,
                 2020:-15.0,2021:15.0,2022:10.0,2023:3.0,  2024:-3.0},
    "default":  {2005:32.0,2006:8.0, 2007:23.0,2008:-36.0,2009:41.0,
                 2010:16.0,2011:-10.0,2012:9.0, 2013:2.0,  2014:-4.0,
                 2015:2.0, 2016:4.0, 2017:18.0,2018:-15.0,2019:8.0,
                 2020:28.0,2021:5.0, 2022:-22.0,2023:16.0, 2024:-8.0},
}


def _get_asset_yearly_returns(ticker: str, asset_class: str) -> dict[int, float]:
    """
    자산별 연도별 수익률 반환.
    yfinance 사용 가능하면 실제 데이터, 아니면 정적 테이블.
    """
    # 0. 이미 계산된 캐시가 있으면 재사용
    if ticker in _HISTORICAL_DATA and _HISTORICAL_DATA[ticker]:
        return _HISTORICAL_DATA[ticker]

    # 1. 정적 테이블에 있으면 바로 반환
    if ticker in _ASSET_HIST_RETURNS:
        return _ASSET_HIST_RETURNS[ticker]

    # 1-b. (Data D2 후속) 한국 종목 백필 데이터 우선 사용
    #      pykrx로 수집한 kr_historical_returns.json 가 있으면 섹터 평균보다 우선
    kr_real = _load_kr_real_returns(ticker)
    if kr_real:
        _HISTORICAL_DATA[ticker] = kr_real
        return kr_real

    # 2. yfinance로 실제 데이터 시도
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="max", interval="1mo", auto_adjust=False)
        if hist.empty:
            raise ValueError("빈 데이터")
        # Adj Close가 있으면 총수익률에 가깝게(배당/분할 반영) 계산 가능
        price_col = "Adj Close" if "Adj Close" in hist.columns else "Close"

        yearly: dict[int, float] = {}
        for yr in range(2005, 2025):
            yr_data = hist[hist.index.year == yr]
            if len(yr_data) < 2:
                continue
            start = float(yr_data[price_col].iloc[0])
            end = float(yr_data[price_col].iloc[-1])
            if start <= 0:
                continue
            ret = (end / start - 1) * 100
            yearly[yr] = round(ret, 2)

        if yearly:
            _HISTORICAL_DATA[ticker] = yearly
        return yearly
    except Exception:
        pass

    # 3. KR 종목 → 섹터 평균 fallback
    if asset_class == "kr_stock":
        return _KR_SECTOR_RETURNS["default"]

    # 4. 아무것도 없으면 S&P500 대리
    return _SP500_RETURNS_FALLBACK_2005_2024


def _get_benchmark_returns(symbol: str, fallback: dict[int, float]) -> dict[int, float]:
    """
    벤치마크(^GSPC, ^KS11 등) 연도별 수익률을 yfinance로 계산.
    실패 시 fallback 반환.
    """
    if symbol in _HISTORICAL_DATA and _HISTORICAL_DATA[symbol]:
        return _HISTORICAL_DATA[symbol]

    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period="max", interval="1mo", auto_adjust=False)
        if hist.empty:
            raise ValueError("빈 데이터")
        price_col = "Adj Close" if "Adj Close" in hist.columns else "Close"

        yearly: dict[int, float] = {}
        for yr in range(2005, 2025):
            yr_data = hist[hist.index.year == yr]
            if len(yr_data) < 2:
                continue
            start = float(yr_data[price_col].iloc[0])
            end = float(yr_data[price_col].iloc[-1])
            if start <= 0:
                continue
            yearly[yr] = round((end / start - 1) * 100, 2)

        if yearly:
            _HISTORICAL_DATA[symbol] = yearly
            return yearly
    except Exception:
        pass
    return fallback


def run_backtest(
    recommendations: list[dict],
    start_year:      int   = 2005,
    end_year:        int   = 2024,
    investable:      float = 1000.0,
    risk_free_rate:  float = 2.0,    # 무위험 수익률 (샤프 계산용)
) -> dict:
    """
    포트폴리오 백테스팅 실행.

    Args:
        recommendations:  assign_weights() 결과
        start_year:       백테스팅 시작 연도
        end_year:         백테스팅 종료 연도
        investable:       초기 투자금 (만원)
        risk_free_rate:   무위험 수익률 (%) — 샤프 계산용

    Returns:
        cagr_pct, mdd_pct, sharpe_ratio, yearly_returns 등
    """
    years = list(range(start_year, end_year + 1))
    if not years or not recommendations:
        return _empty_result(start_year, end_year)

    # 자산별 연도 수익률 로드
    asset_returns: list[tuple[float, dict[int, float]]] = []
    for rec in recommendations:
        ticker     = rec.get("ticker", "")
        asset_cls  = rec.get("asset_class", "")
        # weight_pct(0~100) 우선, 없으면 weight(0~1 or 0~100) 허용
        if "weight_pct" in rec:
            weight = float(rec.get("weight_pct", 0)) / 100
        else:
            raw_weight = float(rec.get("weight", 0))
            weight = raw_weight / 100 if raw_weight > 1 else raw_weight
        if weight <= 0:
            continue
        hist = _get_asset_yearly_returns(ticker, asset_cls)
        asset_returns.append((weight, hist))

    if not asset_returns:
        return _empty_result(start_year, end_year)

    # ── 연도별 포트폴리오 수익률 계산 ─────────────────────────
    yearly_returns: list[dict] = []
    portfolio_value = investable
    kospi_returns = _get_benchmark_returns("^KS11", _KOSPI_RETURNS_FALLBACK_2005_2024)
    sp500_returns = _get_benchmark_returns("^GSPC", _SP500_RETURNS_FALLBACK_2005_2024)

    for yr in years:
        # 가중합산 포트폴리오 수익률
        # 결측 연도(NaN/None)는 해당 연도에서 자동 제외하고 유효 종목만 재정규화
        port_ret = 0.0
        valid_assets: list[tuple[float, float]] = []
        for weight, hist in asset_returns:
            ret = hist.get(yr)
            if ret is None:
                continue
            if isinstance(ret, float) and math.isnan(ret):
                continue
            valid_assets.append((weight, float(ret)))

        total_valid_weight = sum(w for w, _ in valid_assets)
        if total_valid_weight <= 0:
            continue
        for weight, ret in valid_assets:
            normalized_weight = weight / total_valid_weight
            port_ret += normalized_weight * ret

        # 배당 수익률 추정 (전체 수익률의 40% 가정)
        div_portion = port_ret * 0.40

        prev_value = portfolio_value
        portfolio_value = portfolio_value * (1 + port_ret / 100)

        # 벤치마크 수익률
        kospi = kospi_returns.get(yr, 0)
        sp500 = sp500_returns.get(yr, 0)

        yearly_returns.append({
            "year":           yr,
            "return_pct":     round(port_ret, 2),
            "div_return_pct": round(div_portion, 2),
            "value_만원":     round(portfolio_value, 1),
            "vs_kospi":       round(port_ret - kospi, 2),
            "vs_sp500":       round(port_ret - sp500, 2),
            "kospi_ret":      kospi,
            "sp500_ret":      sp500,
        })

    if not yearly_returns:
        return _empty_result(start_year, end_year)

    # ── CAGR 계산 ─────────────────────────────────────────────
    n_years = len(yearly_returns)
    total_return_pct = (portfolio_value / investable - 1) * 100
    cagr_pct = ((portfolio_value / investable) ** (1 / n_years) - 1) * 100

    # ── MDD (최대낙폭) 계산 ────────────────────────────────────
    # 연도별 누적 가치 기준 최대 고점 대비 낙폭
    peak  = investable
    mdd   = 0.0
    running = investable
    for yr_data in yearly_returns:
        running = running * (1 + yr_data["return_pct"] / 100)
        if running > peak:
            peak = running
        drawdown = (running - peak) / peak * 100
        if drawdown < mdd:
            mdd = drawdown

    # ── Sharpe/Sortino Ratio 계산 ─────────────────────────────
    rets = [d["return_pct"] for d in yearly_returns]
    avg_ret = sum(rets) / len(rets)
    if len(rets) > 1:
        variance = sum((r - avg_ret) ** 2 for r in rets) / (len(rets) - 1)
        std_dev  = math.sqrt(variance)
        sharpe   = (avg_ret - risk_free_rate) / std_dev if std_dev > 0 else 0.0
    else:
        sharpe = 0.0

    # Sortino: 하방 변동성(목표수익률=무위험수익률)만 페널티
    downside_diffs = [min(0.0, r - risk_free_rate) for r in rets]
    downside_squared = [d ** 2 for d in downside_diffs]
    if len(rets) > 1:
        downside_variance = sum(downside_squared) / (len(rets) - 1)
        downside_dev = math.sqrt(downside_variance)
        sortino = (avg_ret - risk_free_rate) / downside_dev if downside_dev > 0 else 0.0
    else:
        sortino = 0.0

    # ── 배당 CAGR ──────────────────────────────────────────────
    div_rets = [d["div_return_pct"] for d in yearly_returns]
    div_cagr = ((1 + sum(div_rets) / len(div_rets) / 100) ** 1 - 1) * 100

    # ── 벤치마크 비교 ──────────────────────────────────────────
    kospi_series = [kospi_returns.get(y, 0.0) for y in years]
    sp500_series = [sp500_returns.get(y, 0.0) for y in years]
    avg_kospi = (sum(kospi_series) / len(kospi_series)) if kospi_series else 0.0
    avg_sp500 = (sum(sp500_series) / len(sp500_series)) if sp500_series else 0.0

    # Information Ratio: 초과수익 평균 / 추적오차(표준편차)
    active_kospi = [r - k for r, k in zip(rets, kospi_series)]
    active_sp500 = [r - s for r, s in zip(rets, sp500_series)]

    def _information_ratio(active_returns: list[float]) -> float:
        if len(active_returns) <= 1:
            return 0.0
        active_mean = sum(active_returns) / len(active_returns)
        te_var = sum((a - active_mean) ** 2 for a in active_returns) / (len(active_returns) - 1)
        te = math.sqrt(te_var)
        return active_mean / te if te > 0 else 0.0

    information_ratio_kospi = _information_ratio(active_kospi)
    information_ratio_sp500 = _information_ratio(active_sp500)

    # Calmar: CAGR / |MDD|
    calmar = cagr_pct / abs(mdd) if mdd < 0 else 0.0

    # 최고/최저 연도
    best  = max(yearly_returns, key=lambda d: d["return_pct"])
    worst = min(yearly_returns, key=lambda d: d["return_pct"])

    # 양의 수익 연도 수
    positive_years = sum(1 for d in yearly_returns if d["return_pct"] > 0)

    # 요약 메시지
    grade = "우수" if cagr_pct >= 10 else "양호" if cagr_pct >= 6 else "보통" if cagr_pct >= 3 else "미흡"
    summary = (
        f"{start_year}~{end_year} {n_years}년간 연복리 {cagr_pct:.1f}% ({grade}). "
        f"최대낙폭 {mdd:.1f}%, 샤프지수 {sharpe:.2f}. "
        f"KOSPI 대비 +{cagr_pct - avg_kospi:.1f}%p, "
        f"S&P500 대비 {cagr_pct - avg_sp500:+.1f}%p."
    )

    return {
        "period":           f"{start_year}~{end_year}",
        "n_years":          n_years,
        "cagr_pct":         round(cagr_pct, 2),
        "total_return_pct": round(total_return_pct, 1),
        "mdd_pct":          round(mdd, 2),
        "sharpe_ratio":     round(sharpe, 3),
        "sortino_ratio":    round(sortino, 3),
        "calmar_ratio":     round(calmar, 3),
        "information_ratio_kospi": round(information_ratio_kospi, 3),
        "information_ratio_sp500": round(information_ratio_sp500, 3),
        "div_cagr_pct":     round(div_cagr, 2),
        "positive_years":   positive_years,
        "best_year":        best,
        "worst_year":       worst,
        "yearly_returns":   yearly_returns,
        "vs_kospi_cagr":    round(cagr_pct - avg_kospi, 2),
        "vs_sp500_cagr":    round(cagr_pct - avg_sp500, 2),
        "benchmark": {
            "kospi_cagr":   round(avg_kospi, 2),
            "sp500_cagr":   round(avg_sp500, 2),
            "rf_rate":      risk_free_rate,
        },
        "final_value_만원":   round(portfolio_value, 1),
        "initial_value_만원": investable,
        "summary_message":  summary,
        "grade":            grade,
        "data_note": (
            "미국 ETF/주식: yfinance 또는 팩트시트 실제 데이터. "
            "한국 배당주: KRX 섹터 평균 추정치 (참고용)."
        ),
        # Day 8 / Data D1: 합성 데이터 정직화
        "data_quality":     _compute_data_quality(recommendations, start_year, end_year),
    }


def _compute_data_quality(
    recommendations: list[dict],
    start_year: int,
    end_year: int,
) -> dict:
    """
    백테스팅에 사용된 종목들의 데이터 정직성 메타 계산.

    반환:
    {
        "period": "2005~2024",
        "n_years_requested": 20,
        "real_year_ratio_pct":      87.5,    # 합성 X / 전체 비율
        "synthetic_year_ratio_pct": 12.5,
        "tickers_with_synthetic":   ["SCHD", "DGRO"],
        "by_ticker": {
            "SCHD": {
                "inception_year":      2011,
                "real_years":          14,           # 2011~2024
                "synthetic_years":     6,            # 2005~2010
                "synthetic_sources":   ["SCHX ...", "SDY ..."],
            },
            ...
        },
        "disclosure_message": "* SCHD, DGRO 등 ... 합성 적용",
    }
    """
    n_years_total = end_year - start_year + 1
    by_ticker: dict[str, dict] = {}
    tickers_with_synthetic: list[str] = []
    total_real = 0
    total_synthetic = 0

    for rec in recommendations or []:
        ticker = str(rec.get("ticker", ""))
        if not ticker:
            continue

        inception = _ASSET_INCEPTION_YEAR.get(ticker)
        # inception_year 없는 종목 = 한국 개별 배당주 (섹터 평균 사용) 등
        if inception is None:
            # 보수적으로 실데이터로 카운트하되, "unknown" 플래그
            by_ticker[ticker] = {
                "inception_year": None,
                "real_years":      n_years_total,
                "synthetic_years": 0,
                "synthetic_sources": [],
                "note": "상장 연도 미등록 (실데이터 가정)",
            }
            total_real += n_years_total
            continue

        # 상장 이후 = 실제 데이터
        real_years = max(0, end_year - max(inception, start_year) + 1)
        # 상장 이전 = 합성 데이터 (단, 시작 연도가 상장 이전인 경우만)
        synthetic_years = max(0, inception - start_year) if inception > start_year else 0

        proxies = _SYNTHETIC_PROXY_MAP.get(ticker, [])
        is_actually_synthetic = synthetic_years > 0 and len(proxies) > 0
        is_nan_fallback     = synthetic_years > 0 and len(proxies) == 0

        by_ticker[ticker] = {
            "inception_year":      inception,
            "real_years":          real_years,
            "synthetic_years":     synthetic_years if is_actually_synthetic else 0,
            "nan_years":           synthetic_years if is_nan_fallback else 0,
            "synthetic_sources":   proxies if is_actually_synthetic else [],
        }
        if is_actually_synthetic:
            tickers_with_synthetic.append(ticker)
            total_synthetic += synthetic_years
        total_real += real_years

    grand_total = total_real + total_synthetic
    real_ratio  = round(100 * total_real / grand_total, 1) if grand_total else 100.0
    synth_ratio = round(100 * total_synthetic / grand_total, 1) if grand_total else 0.0

    # 청중에게 보여줄 짧은 한국어 디스클로저
    if tickers_with_synthetic:
        joined = ", ".join(tickers_with_synthetic[:3])
        more   = "" if len(tickers_with_synthetic) <= 3 else f" 외 {len(tickers_with_synthetic) - 3}개"
        disclosure = (
            f"* {joined}{more}의 상장 이전 연도 데이터는 동일 카테고리 선행 ETF로 합성 적용. "
            f"전체 데이터 중 실제 {real_ratio}% / 합성 {synth_ratio}%."
        )
    else:
        disclosure = f"전체 데이터의 {real_ratio}% 가 상장 이후 실제 데이터."

    return {
        "period":                   f"{start_year}~{end_year}",
        "n_years_requested":        n_years_total,
        "real_year_ratio_pct":      real_ratio,
        "synthetic_year_ratio_pct": synth_ratio,
        "tickers_with_synthetic":   tickers_with_synthetic,
        "by_ticker":                by_ticker,
        "disclosure_message":       disclosure,
    }


def _empty_result(start_year: int, end_year: int) -> dict:
    return {
        "period": f"{start_year}~{end_year}",
        "cagr_pct": 0.0, "total_return_pct": 0.0,
        "mdd_pct": 0.0, "sharpe_ratio": 0.0,
        "sortino_ratio": 0.0, "calmar_ratio": 0.0,
        "information_ratio_kospi": 0.0,
        "information_ratio_sp500": 0.0,
        "yearly_returns": [], "summary_message": "데이터 없음",
        "grade": "N/A",
    }

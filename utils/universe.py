"""
포트폴리오 유니버스 정의 — 5축 철학 기반

철학: "은행보다 높은 실질 수익률을 위험 관리와 함께 달성하는 현금흐름 설계"
  → 배당수익률만 보는 것이 아니라 Total Return (배당 + 자본차익) 으로 평가

┌──────────────────────────────────────────────────────────┐
│  축 1: 한국 배당주      (ranking.csv 기반)               │
│  축 2: 미국 배당 개별주 (KO, JNJ, XOM, ABBV, MCD ...)  │
│  축 3: 미국/국내 배당ETF (SCHD, VYM, DGRO, JEPI ...)   │
│  축 4: 리츠(REITs)      (O, VNQ, SK리츠, 롯데리츠)      │
│  축 5: 방어형 ETF       (TLT, BND, AGG)                  │
└──────────────────────────────────────────────────────────┘

각 자산 필드:
  ticker            : 심볼 (미국 ETF=알파벳, 한국=6자리 코드)
  name              : 표시용 이름
  asset_class       : us_div_etf | us_reit | kr_etf | kr_reit | defensive
  account           : ISA=ISA 편입 가능, 일반=해외주식 계좌
  risk_profile      : stable | moderate | aggressive | defensive
  expected_yield    : 연 배당수익률 근사값 (%, 2025년 기준)
  capital_gain_rate : 연 자본차익(주가상승) 근사값 (%, 5Y CAGR 기준)
    → Total Return = expected_yield + capital_gain_rate
  description       : 선택 이유 한 줄 설명
"""

from __future__ import annotations
import logging

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
ETF_UNIVERSE: list[dict] = [

    # ── 축 2: 미국 배당 개별주 ──────────────────────────────────────
    {
        "ticker":            "KO",
        "name":              "KO (코카콜라)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "stable",
        "expected_yield":    3.1,
        "capital_gain_rate": 4.0,
        "description":       "62년 연속 배당 증가 배당킹. 음료 독점력 — 배당 3.1% + 주가 4% = 총 7.1%",
    },
    {
        "ticker":            "JNJ",
        "name":              "JNJ (존슨앤존슨)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "stable",
        "expected_yield":    3.2,
        "capital_gain_rate": 5.0,
        "description":       "62년 연속 배당 증가 배당킹. 헬스케어 글로벌 1위 — 배당 3.2% + 주가 5% = 총 8.2%",
    },
    {
        "ticker":            "PG",
        "name":              "PG (프록터앤갬블)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "stable",
        "expected_yield":    2.5,
        "capital_gain_rate": 6.0,
        "description":       "67년 연속 배당 증가 배당왕. 생활필수재 독점 — 배당 2.5% + 주가 6% = 총 8.5%",
    },
    {
        "ticker":            "XOM",
        "name":              "XOM (엑손모빌)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    3.4,
        "capital_gain_rate": 5.5,
        "description":       "에너지 섹터 배당귀족. 41년 연속 배당 증가 — 배당 3.4% + 주가 5.5% = 총 8.9%",
    },
    {
        "ticker":            "CVX",
        "name":              "CVX (쉐브론)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    4.1,
        "capital_gain_rate": 4.5,
        "description":       "36년 연속 배당 증가 배당귀족. 에너지 고배당 — 배당 4.1% + 주가 4.5% = 총 8.6%",
    },
    {
        "ticker":            "ABBV",
        "name":              "ABBV (애브비)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    3.8,
        "capital_gain_rate": 6.0,
        "description":       "바이오파마 배당귀족. 휴미라 후속 파이프라인 강력 — 배당 3.8% + 주가 6% = 총 9.8%",
    },
    {
        "ticker":            "MCD",
        "name":              "MCD (맥도날드)",
        "asset_class":       "us_stock",
        "asset_type":        "DIVIDEND_ARISTOCRAT",
        "account":           "일반/연금",
        "risk_profile":      "stable",
        "expected_yield":    2.4,
        "capital_gain_rate": 7.0,
        "description":       "48년 연속 배당 증가 배당귀족. 프랜차이즈 모델 고성장 — 배당 2.4% + 주가 7% = 총 9.4%",
    },
    {
        "ticker":            "T",
        "name":              "T (AT&T)",
        "asset_class":       "us_stock",
        "asset_type":        "HIGH_YIELD",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    6.5,
        "capital_gain_rate": 1.5,
        "description":       "통신 고배당주 (2022년 배당삭감 후 안정화 중). 부채 감축 진행 중 — 배당 6.5%. 회복 기대이나 리스크 존재.",
    },
    {
        "ticker":            "VZ",
        "name":              "VZ (버라이즌)",
        "asset_class":       "us_stock",
        "asset_type":        "HIGH_YIELD",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    6.8,
        "capital_gain_rate": 1.5,
        "description":       "19년 연속 배당 증가. 5G 인프라 고배당 — 배당 6.8% + 주가 1.5% = 총 8.3%",
    },
    {
        "ticker":            "IBM",
        "name":              "IBM (아이비엠)",
        "asset_class":       "us_stock",
        "asset_type":        "HIGH_YIELD",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    3.5,
        "capital_gain_rate": 5.0,
        "description":       "IT전환 진행 중. AI·클라우드 전환으로 주가 회복세 — 배당 3.5% + 주가 5% = 총 8.5%",
    },
    {
        "ticker":            "MO",
        "name":              "MO (알트리아)",
        "asset_class":       "us_stock",
        "asset_type":        "HIGH_YIELD",
        "account":           "일반/연금",
        "risk_profile":      "aggressive",
        "expected_yield":    8.5,
        "capital_gain_rate": 1.0,
        "description":       "담배 고배당 대장주. 규제 리스크 있으나 현금흐름 극강 — 배당 8.5%",
    },
    {
        "ticker":            "PFE",
        "name":              "PFE (화이자)",
        "asset_class":       "us_stock",
        "asset_type":        "HIGH_YIELD",
        "account":           "일반/연금",
        "risk_profile":      "moderate",
        "expected_yield":    6.5,
        "capital_gain_rate": 3.0,
        "description":       "코로나 이후 주가 조정, 배당수익률 급상승. 파이프라인 회복 기대 — 배당 6.5%",
    },

    # ── 축 3: 미국 배당 ETF ─────────────────────────────────────────
    # etf_category 분류:
    #   dividend_growth  : 장기 복리 핵심 (배당 성장률 > yield)
    #   monthly_income   : 월배당 현금흐름 (covered call / high freq)
    #   high_yield       : 현재 배당률 우선
    #
    # 핵심 지표:
    #   div_growth_5y    : 5년 배당성장률 CAGR (%)
    #   mdd              : 최대 낙폭 (%)
    #   volatility       : 연 변동성 (%)
    #   monthly_pay      : 월배당 여부 (True/False)
    #   expense_ratio    : 총보수 (%)
    # ────────────────────────────────────────────────────────────────

    # [ A. Dividend Growth — 장기 복리 핵심 ]
    {
        "ticker":           "SCHD",
        "name":             "SCHD",
        "asset_class":      "us_div_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   3.6,
        "capital_gain_rate": 8.0,
        "div_growth_5y":    10.2,
        "mdd":              -33.0,
        "volatility":       14.5,
        "monthly_pay":      False,
        "expense_ratio":    0.06,
        "description":      "배당성장 ETF의 교과서. 10년+ 배당 증가 우량기업 100선. 배당성장률 10%·변동성 낮아 장기 복리 전략의 핵심 자산.",
    },
    {
        "ticker":           "DGRO",
        "name":             "DGRO",
        "asset_class":      "us_div_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   2.5,
        "capital_gain_rate": 9.0,
        "div_growth_5y":    9.8,
        "mdd":              -32.0,
        "volatility":       15.0,
        "monthly_pay":      False,
        "expense_ratio":    0.08,
        "description":      "5년+ 연속 배당성장 기업 집중. EPS 성장성과 배당 지속성 동시 검증. SCHD 보완재로 함께 보유 시 분산 효과 극대화.",
    },
    {
        "ticker":           "VIG",
        "name":             "VIG",
        "asset_class":      "us_div_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   1.8,
        "capital_gain_rate": 10.0,
        "div_growth_5y":    8.5,
        "mdd":              -29.0,
        "volatility":       14.0,
        "monthly_pay":      False,
        "expense_ratio":    0.06,
        "description":      "뱅가드 배당성장 대표. 10년+ 연속 배당 증가 기업만 편입. S&P500 대비 낮은 MDD(-29%)로 안정성 최우선 포트폴리오에 적합.",
    },
    {
        "ticker":           "DGRW",
        "name":             "DGRW",
        "asset_class":      "us_div_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   2.0,
        "capital_gain_rate": 10.0,
        "div_growth_5y":    8.0,
        "mdd":              -30.0,
        "volatility":       15.5,
        "monthly_pay":      False,
        "expense_ratio":    0.28,
        "description":      "EPS 성장 + 배당성장 동시 선별. SCHD 대비 IT·퀄리티주 비중 높아 성장장에서 강함. 포트폴리오 성장 엔진 역할.",
    },
    {
        "ticker":           "NOBL",
        "name":             "NOBL",
        "asset_class":      "us_div_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   2.2,
        "capital_gain_rate": 8.5,
        "div_growth_5y":    6.0,
        "mdd":              -30.0,
        "volatility":       14.0,
        "monthly_pay":      False,
        "expense_ratio":    0.35,
        "description":      "S&P500 25년+ 연속 배당성장 기업만 선별한 배당귀족 ETF. 역사적으로 하락장 방어력 우수. 장기 신뢰성 최고 등급.",
    },

    # [ B. Monthly Income — 월배당 현금흐름 ]
    {
        "ticker":           "JEPI",
        "name":             "JEPI",
        "asset_class":      "us_div_etf",
        "etf_category":     "monthly_income",
        "asset_type":       "COVERED_CALL",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   7.5,
        "capital_gain_rate": 2.0,
        "div_growth_5y":    0.0,
        "mdd":              -27.0,
        "volatility":       10.5,
        "monthly_pay":      True,
        "expense_ratio":    0.35,
        "description":      "S&P500 + ELN 커버드콜로 월배당 7~9% 실현. S&P500 대비 변동성 낮음(-27% MDD). 매달 현금흐름이 필요한 은퇴·월급형 포트에 핵심.",
    },
    {
        "ticker":           "JEPQ",
        "name":             "JEPQ",
        "asset_class":      "us_div_etf",
        "etf_category":     "monthly_income",
        "asset_type":       "COVERED_CALL",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   9.0,
        "capital_gain_rate": 3.0,
        "div_growth_5y":    0.0,
        "mdd":              -32.0,
        "volatility":       16.0,
        "monthly_pay":      True,
        "expense_ratio":    0.35,
        "description":      "나스닥100 + 커버드콜. JEPI보다 높은 배당(9%+)과 나스닥 성장 일부 참여. 공격형 월배당 포트의 핵심. 변동성은 JEPI보다 높음.",
    },
    {
        "ticker":           "SPYI",
        "name":             "SPYI",
        "asset_class":      "us_div_etf",
        "etf_category":     "monthly_income",
        "asset_type":       "COVERED_CALL",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   12.0,
        "capital_gain_rate": 1.5,
        "div_growth_5y":    0.0,
        "mdd":              -25.0,
        "volatility":       12.0,
        "monthly_pay":      True,
        "expense_ratio":    0.68,
        "description":      "NEOS의 S&P500 고소득 커버드콜 ETF. 세금 효율적 구조로 실수령 수익률이 높음. 월배당 12%+ 목표. 초고배당 현금흐름 전략.",
    },
    {
        "ticker":           "QYLD",
        "name":             "QYLD",
        "asset_class":      "us_div_etf",
        "etf_category":     "monthly_income",
        "asset_type":       "COVERED_CALL",
        "account":          "일반/연금",
        "risk_profile":     "aggressive",
        "expected_yield":   11.5,
        "capital_gain_rate": -1.0,
        "div_growth_5y":    -2.0,
        "mdd":              -35.0,
        "volatility":       18.0,
        "monthly_pay":      True,
        "expense_ratio":    0.60,
        "description":      "나스닥100 전량 커버드콜. 월배당 11%+이나 주가 상승 포기. 원금보전보다 현금흐름이 절대 우선인 포트폴리오에만 편입 권장.",
    },

    # [ C. High Yield — 현재 배당률 우선 ]
    {
        "ticker":           "VYM",
        "name":             "VYM",
        "asset_class":      "us_div_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   3.0,
        "capital_gain_rate": 6.0,
        "div_growth_5y":    6.1,
        "mdd":              -34.0,
        "volatility":       14.8,
        "monthly_pay":      False,
        "expense_ratio":    0.06,
        "description":      "400+ 종목 광범위 분산의 고배당 ETF. SCHD보다 더 넓은 커버리지. 보수 0.06%로 비용 효율 최상. 배당성장보다 현재 배당 안정성 우선.",
    },
    {
        "ticker":           "HDV",
        "name":             "HDV",
        "asset_class":      "us_div_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.0,
        "capital_gain_rate": 4.5,
        "div_growth_5y":    3.5,
        "mdd":              -33.0,
        "volatility":       15.0,
        "monthly_pay":      False,
        "expense_ratio":    0.08,
        "description":      "재무건전성 필터 기반 고배당 75종목. 에너지·헬스케어·통신 비중 높아 경기방어적. VYM 대비 더 높은 현재 배당률.",
    },
    {
        "ticker":           "SPYD",
        "name":             "SPYD",
        "asset_class":      "us_div_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   4.5,
        "capital_gain_rate": 4.0,
        "div_growth_5y":    2.0,
        "mdd":              -38.0,
        "volatility":       17.0,
        "monthly_pay":      False,
        "expense_ratio":    0.07,
        "description":      "S&P500 내 배당수익률 상위 80종목. 배당률 최우선 선별. 경기민감 섹터 비중 높아 변동성은 HDV보다 높음. 고배당 극대화 전략.",
    },
    {
        "ticker":           "SPHD",
        "name":             "SPHD",
        "asset_class":      "us_div_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.8,
        "capital_gain_rate": 3.0,
        "div_growth_5y":    1.5,
        "mdd":              -32.0,
        "volatility":       13.0,
        "monthly_pay":      True,
        "expense_ratio":    0.30,
        "description":      "S&P500 저변동성+고배당 50종목. 월배당. 배당률 높으면서도 변동성이 낮아 은퇴·안정형 포트에 이상적. 하락장 방어력 우수.",
    },

    # ── 축 3: 미국 리츠 ──────────────────────────────────────────────
    {
        "ticker":           "O",
        "name":             "O (Realty Income 월배당)",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",              # 부동산 신탁: FFO/배당성향 기준 평가
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   5.5,
        "capital_gain_rate": 2.0,
        "description":      "30년+ 월배당, 임차인 1000+개. 배당귀족 리츠 표준 — 배당 5.5% + 주가 2% = 총 7.5%",
    },
    {
        "ticker":           "VNQ",
        "name":             "VNQ (뱅가드 부동산 ETF)",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.0,
        "capital_gain_rate": 3.5,
        "description":      "미국 전체 리츠 분산 — 배당 4.0% + 주가 3.5% = 총 7.5%",
    },
    {
        "ticker":           "EQR",
        "name":             "Equity Residential",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.0,
        "capital_gain_rate": 3.5,
        "consecutive_years": 34,
        "description":      "미국 최대 주거용 리츠. 34년 연속 배당. 임대 수요 안정적 — 배당 4.0% + 주가 3.5%",
    },
    {
        "ticker":           "FRT",
        "name":             "Federal Realty Investment Trust",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.2,
        "capital_gain_rate": 3.0,
        "consecutive_years": 40,
        "description":      "리츠 중 가장 긴 40년 연속 배당성장. S&P500 배당귀족 리츠 — 배당 4.2% + 주가 3.0%",
    },
    {
        "ticker":           "SPG",
        "name":             "Simon Property Group",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   5.1,
        "capital_gain_rate": 4.5,
        "consecutive_years": 33,
        "description":      "미국 최대 쇼핑몰 리츠. 33년 배당성장. 오프라인 회복 수혜 — 배당 5.1% + 주가 4.5%",
    },
    {
        "ticker":           "PSA",
        "name":             "Public Storage",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",
        "account":          "일반/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.3,
        "capital_gain_rate": 3.0,
        "consecutive_years": 39,
        "description":      "미국 최대 셀프스토리지 리츠. 39년 배당이력. 경기방어적 — 배당 4.3% + 주가 3.0%",
    },
    {
        "ticker":           "AMT",
        "name":             "American Tower",
        "asset_class":      "us_reit",
        "asset_type":       "REIT",
        "account":          "일반/연금",
        "risk_profile":     "moderate",
        "expected_yield":   3.2,
        "capital_gain_rate": 4.0,
        "consecutive_years": 16,
        "description":      "5G 통신탑 리츠. 글로벌 4만개+ 기지국. 성장형 리츠 — 배당 3.2% + 주가 4.0%",
    },

    # ── 축 3: 한국 리츠 (ISA 가능) ───────────────────────────────────
    {
        "ticker":           "395400",
        "name":             "SK리츠",
        "asset_class":      "kr_reit",
        "etf_category":     "reit",
        "asset_type":       "REIT",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   5.8,
        "capital_gain_rate": 2.5,
        "div_growth_5y":    3.0,
        "mdd":              -28.0,
        "volatility":       15.0,
        "monthly_pay":      False,
        "expense_ratio":    None,
        "description":      "SK 계열 부동산 기반, ISA 편입 가능. 배당 5.8% + 주가 2.5% = 총 8.3%. 비과세 절세 최적.",
    },
    {
        "ticker":           "330590",
        "name":             "롯데리츠",
        "asset_class":      "kr_reit",
        "etf_category":     "reit",
        "asset_type":       "REIT",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   6.2,
        "capital_gain_rate": 2.0,
        "div_growth_5y":    2.0,
        "mdd":              -30.0,
        "volatility":       16.0,
        "monthly_pay":      False,
        "expense_ratio":    None,
        "description":      "롯데 유통망 담보, ISA 비과세 활용. 배당 6.2% + 주가 2% = 총 8.2%. 리테일 리츠 국내 대표.",
    },

    # ── 축 2: 한국 상장 해외 ETF (ISA 핵심 무기) ─────────────────────
    # etf_category: dividend_growth / monthly_income / high_yield / reit
    {
        "ticker":           "448290",
        "name":             "TIGER 미국배당다우존스",
        "asset_class":      "kr_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   3.5,
        "capital_gain_rate": 7.5,
        "div_growth_5y":    9.5,
        "mdd":              -33.0,
        "volatility":       14.5,
        "monthly_pay":      False,
        "expense_ratio":    0.07,
        "description":      "SCHD 전략 국내 상장판. ISA 비과세 + 미국 배당성장 동시 수혜. 배당성장률 9.5%·보수 0.07%. 총 11% 기대.",
    },
    {
        "ticker":           "385720",
        "name":             "TIGER 미국MSCI리츠(H)",
        "asset_class":      "kr_etf",
        "etf_category":     "reit",
        "asset_type":       "REIT",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.0,
        "capital_gain_rate": 3.5,
        "div_growth_5y":    3.5,
        "mdd":              -38.0,
        "volatility":       18.0,
        "monthly_pay":      False,
        "expense_ratio":    0.24,
        "description":      "미국 리츠 전체를 ISA 계좌로. 환헤지(H)로 환율 리스크 제거. 해외 리츠 비과세 최적 경로. 총 7.5% 기대.",
    },
    {
        "ticker":           "279530",
        "name":             "KODEX 고배당",
        "asset_class":      "kr_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   4.5,
        "capital_gain_rate": 3.0,
        "div_growth_5y":    4.0,
        "mdd":              -35.0,
        "volatility":       17.0,
        "monthly_pay":      False,
        "expense_ratio":    0.15,
        "description":      "KRX 고배당 50종목 분산. ISA 비과세 + 한국 고배당. 배당 4.5%·안정적 현금흐름. 총 7.5% 기대.",
    },
    {
        "ticker":           "211560",
        "name":             "TIGER 배당성장",
        "asset_class":      "kr_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   2.8,
        "capital_gain_rate": 5.5,
        "div_growth_5y":    7.0,
        "mdd":              -33.0,
        "volatility":       16.0,
        "monthly_pay":      False,
        "expense_ratio":    0.15,
        "description":      "배당 증가 한국 기업 집중 선별. 한국판 SCHD 개념. ISA에서 배당성장+절세 동시. 총 8.3% 기대.",
    },
    {
        "ticker":           "441680",
        "name":             "TIGER 미국배당귀족",
        "asset_class":      "kr_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   2.5,
        "capital_gain_rate": 7.5,
        "div_growth_5y":    6.0,
        "mdd":              -30.0,
        "volatility":       14.0,
        "monthly_pay":      False,
        "expense_ratio":    0.07,
        "description":      "NOBL 국내 상장판. 미국 25년+ 연속 배당성장 배당귀족을 ISA로. 하락장 방어력 우수. 총 10% 기대.",
    },
    {
        "ticker":           "456680",
        "name":             "KODEX 미국배당프리미엄액티브",
        "asset_class":      "kr_etf",
        "etf_category":     "monthly_income",
        "asset_type":       "COVERED_CALL",
        "account":          "ISA/연금",
        "risk_profile":     "moderate",
        "expected_yield":   8.0,
        "capital_gain_rate": 2.0,
        "div_growth_5y":    0.0,
        "mdd":              -27.0,
        "volatility":       11.0,
        "monthly_pay":      True,
        "expense_ratio":    0.50,
        "description":      "JEPI 전략 국내 상장판. ISA에서 월배당 8%. 커버드콜로 변동성 억제. 현금흐름+절세 동시 달성.",
    },
    {
        "ticker":           "446720",
        "name":             "SOL 미국배당다우존스",
        "asset_class":      "kr_etf",
        "etf_category":     "dividend_growth",
        "asset_type":       "DIVIDEND_GROWTH",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   3.5,
        "capital_gain_rate": 7.0,
        "div_growth_5y":    9.0,
        "mdd":              -32.0,
        "volatility":       14.0,
        "monthly_pay":      True,
        "expense_ratio":    0.05,
        "description":      "SCHD 전략 국내 상장판(월배당). 보수 0.05%로 최저 수준. ISA 비과세 + 미국 배당성장 + 매월 현금흐름.",
    },
    {
        "ticker":           "458730",
        "name":             "TIGER 미국배당+7%프리미엄다우존스",
        "asset_class":      "kr_etf",
        "etf_category":     "monthly_income",
        "asset_type":       "COVERED_CALL",
        "account":          "ISA/연금",
        "risk_profile":     "moderate",
        "expected_yield":   7.5,
        "capital_gain_rate": 3.0,
        "div_growth_5y":    0.0,
        "mdd":              -25.0,
        "volatility":       12.0,
        "monthly_pay":      True,
        "expense_ratio":    0.39,
        "description":      "SCHD 기반에 커버드콜 7% 프리미엄 결합. 월배당 7%대. 배당성장+현금흐름 절충형. ISA 절세.",
    },
    {
        "ticker":           "161510",
        "name":             "PLUS 고배당주",
        "asset_class":      "kr_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   6.0,
        "capital_gain_rate": 3.0,
        "div_growth_5y":    2.0,
        "mdd":              -30.0,
        "volatility":       15.0,
        "monthly_pay":      False,
        "expense_ratio":    0.23,
        "description":      "국내 고배당주 묶음(구 ARIRANG 고배당주). 배당 6%대. 은행·통신·정유 등 전통 고배당 섹터 집중.",
    },
    {
        "ticker":           "210780",
        "name":             "TIGER 코스피고배당",
        "asset_class":      "kr_etf",
        "etf_category":     "high_yield",
        "asset_type":       "HIGH_YIELD",
        "account":          "ISA/연금",
        "risk_profile":     "stable",
        "expected_yield":   5.0,
        "capital_gain_rate": 4.0,
        "div_growth_5y":    3.0,
        "mdd":              -28.0,
        "volatility":       14.0,
        "monthly_pay":      False,
        "expense_ratio":    0.29,
        "description":      "코스피 고배당 50종목. 배당 5%대 + 코스피 동행 자본차익. 국내 대표 배당 ETF.",
    },

    # ── 축 5: 방어형 ETF ─────────────────────────────────────────────
    # etf_category: cash_equivalent / long_bond / agg_bond / tips
    {
        "ticker":           "SGOV",
        "name":             "SGOV (초단기 미국채)",
        "asset_class":      "defensive",
        "etf_category":     "cash_equivalent",
        "asset_type":       "BOND",
        "account":          "일반/연금",
        "risk_profile":     "defensive",
        "expected_yield":   5.2,
        "capital_gain_rate": 0.0,
        "div_growth_5y":    0.0,
        "mdd":              -0.1,
        "volatility":       0.5,
        "monthly_pay":      True,
        "expense_ratio":    0.09,
        "description":      "0~3개월 초단기 미국채. 금리 리스크 제로·MDD 거의 없음. 월배당 5.2%로 CMA 대체재. 포트폴리오 현금성 버퍼 역할.",
    },
    {
        "ticker":           "TLT",
        "name":             "TLT (미국 장기국채)",
        "asset_class":      "defensive",
        "etf_category":     "long_bond",
        "asset_type":       "BOND",
        "account":          "일반/연금",
        "risk_profile":     "defensive",
        "expected_yield":   4.5,
        "capital_gain_rate": 2.0,
        "div_growth_5y":    0.0,
        "mdd":              -46.0,
        "volatility":       18.0,
        "monthly_pay":      False,
        "expense_ratio":    0.15,
        "description":      "20년+ 미국 장기국채. 주식 폭락 시 반등하는 전통적 위기 헤지 자산. 금리 하락 시 강한 자본차익 발생.",
    },
    {
        "ticker":           "BND",
        "name":             "BND (뱅가드 미채권 총합)",
        "asset_class":      "defensive",
        "etf_category":     "agg_bond",
        "asset_type":       "BOND",
        "account":          "일반/연금",
        "risk_profile":     "defensive",
        "expected_yield":   3.5,
        "capital_gain_rate": 0.5,
        "div_growth_5y":    0.0,
        "mdd":              -17.0,
        "volatility":       5.5,
        "monthly_pay":      False,
        "expense_ratio":    0.03,
        "description":      "단기·중기·장기 미국 채권 전체 분산. MDD -17%·변동성 낮음. 보수 0.03% 최저비용. 포트폴리오 안정 쿠션.",
    },
    {
        "ticker":           "AGG",
        "name":             "AGG (iShares 미채권 총합)",
        "asset_class":      "defensive",
        "etf_category":     "agg_bond",
        "asset_type":       "BOND",
        "account":          "일반/연금",
        "risk_profile":     "defensive",
        "expected_yield":   3.8,
        "capital_gain_rate": 0.5,
        "div_growth_5y":    0.0,
        "mdd":              -17.0,
        "volatility":       5.5,
        "monthly_pay":      False,
        "expense_ratio":    0.03,
        "description":      "BND 대안 iShares 운용. 미국 채권 총합 분산. 이자 3.8% + 금리 하락기 자본차익 기대. 포트 방어층 핵심.",
    },
    {
        "ticker":           "SCHP",
        "name":             "SCHP (물가연동국채 TIPS)",
        "asset_class":      "defensive",
        "etf_category":     "tips",
        "asset_type":       "BOND",
        "account":          "일반/연금",
        "risk_profile":     "defensive",
        "expected_yield":   3.2,
        "capital_gain_rate": 1.0,
        "div_growth_5y":    0.0,
        "mdd":              -19.0,
        "volatility":       6.0,
        "monthly_pay":      False,
        "expense_ratio":    0.04,
        "description":      "인플레이션 연동 TIPS ETF. 물가 상승 시 원금·이자 모두 방어. 인플레 헤지 전용. 실질 수익률 보호 총 4.2%.",
    },
]

# ─────────────────────────────────────────────────────────────────────
# 나이·성향별 4축 배분 비율
# ─────────────────────────────────────────────────────────────────────

def get_axis_weights(age: int, risk: str) -> dict:
    """
    나이 + 투자성향 → 5축 배분 비율.
    - 젊을수록: 미국주식·ETF 성장 비중 ↑ (Total Return 극대화)
    - 나이 들수록: 방어 + 한국 배당주 ↑ (현금흐름 안정화)

    키: kr_stock | us_stock | us_etf | reit | defensive
    """
    if age < 30:
        # 젊을수록 성장 중심: 미국주식·ETF 비중 최대
        base = {"kr_stock": 0.25, "us_stock": 0.20, "us_etf": 0.30, "reit": 0.15, "defensive": 0.10}
    elif age < 40:
        base = {"kr_stock": 0.28, "us_stock": 0.17, "us_etf": 0.28, "reit": 0.17, "defensive": 0.10}
    elif age < 50:
        # 40대: 균형. 한국 배당주 주축, 미국주식 병행
        base = {"kr_stock": 0.32, "us_stock": 0.15, "us_etf": 0.23, "reit": 0.17, "defensive": 0.13}
    elif age < 60:
        # 50대: 현금흐름 강화, 방어 비중 상승
        base = {"kr_stock": 0.35, "us_stock": 0.12, "us_etf": 0.18, "reit": 0.17, "defensive": 0.18}
    else:
        # 60대+: 안전 최우선, 방어·한국 배당주 중심
        base = {"kr_stock": 0.33, "us_stock": 0.10, "us_etf": 0.12, "reit": 0.15, "defensive": 0.30}

    if risk == "aggressive":
        base["us_stock"]  += 0.08
        base["us_etf"]    += 0.05
        base["defensive"] -= 0.08
        base["kr_stock"]  -= 0.05
    elif risk == "conservative":
        base["defensive"] += 0.10
        base["us_stock"]  -= 0.05
        base["us_etf"]    -= 0.05

    # 음수 방지 후 정규화
    base = {k: max(0.0, v) for k, v in base.items()}
    total = sum(base.values())
    return {k: round(v / total, 3) for k, v in base.items()}


# ─────────────────────────────────────────────────────────────────────
# ETF 실시간 배당수익률 조회 (yfinance)
# ─────────────────────────────────────────────────────────────────────

def fetch_etf_yields() -> dict[str, float]:
    """
    ETF 실시간 배당수익률 조회.

    우선순위:
      1. data_updater.get_all_yields() — v2.0 yield_cache 읽기
         (내부적으로 yfinance → 네이버 → 캐시 → metadata fallback 순)
      2. yield_cache.json 직접 읽기 (v1/v2 모두 호환)
      3. ETF_UNIVERSE 하드코딩 기본값 (최후 fallback)

    왜 data_updater를 먼저 쓰는가?
      fetch_etf_yields()는 서버 시작 시 1회 호출된다. data_updater는
      한국 ETF 수익률·배당성장률을 포함한 43개 자산의 통합 캐시를 제공하며,
      v1 캐시(yields:{}) 구조와 v2 캐시(assets:{}) 구조를 모두 처리한다.
    """
    import json, os
    from datetime import datetime, timedelta

    # 하드코딩 기본값 (최후 보루)
    defaults = {a["ticker"]: a["expected_yield"] for a in ETF_UNIVERSE}

    # ── 1. data_updater 통합 캐시 ────────────────────────────
    try:
        from utils.data_updater import get_all_yields
        live = get_all_yields()
        if live:
            log.info(f"[universe] data_updater 수익률 로드 ({len(live)}개)")
            return {**defaults, **live}
    except Exception as e:
        log.debug(f"[universe] data_updater 로드 실패: {e}")

    # ── 2. yield_cache.json 직접 읽기 (v1/v2 호환) ───────────
    cache_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "yield_cache.json"
    )
    try:
        with open(cache_path, encoding="utf-8") as f:
            disk = json.load(f)
        updated_str = disk.get("_updated", "2000-01-01")
        updated = datetime.strptime(updated_str[:10], "%Y-%m-%d")
        if datetime.now() - updated < timedelta(hours=48):
            # v2.0 구조: assets.{ticker}.yield_pct
            assets = disk.get("assets", {})
            if assets:
                cached = {k: float(v.get("yield_pct", 0)) for k, v in assets.items()
                          if isinstance(v, dict) and v.get("yield_pct")}
                if cached:
                    log.info(f"[universe] yield_cache v2 사용 ({updated_str}, {len(cached)}개)")
                    return {**defaults, **cached}
            # v1.0 구조: yields.{ticker}: float
            v1_yields = disk.get("yields", {})
            if v1_yields:
                log.info(f"[universe] yield_cache v1 사용 ({updated_str})")
                return {**defaults, **v1_yields}
    except Exception as e:
        log.debug(f"[universe] yield_cache 읽기 실패: {e}")

    # ── 3. 최후 fallback: 하드코딩 기본값 ────────────────────
    log.warning("[universe] 모든 수익률 소스 실패 — ETF_UNIVERSE 기본값 사용")
    return defaults


def load_approved_universe() -> list[dict]:
    """
    approved_universe.json (discover.py가 자동 관리)을 읽어 ETF_UNIVERSE와 병합.

    우선순위: approved_universe.json > ETF_UNIVERSE 하드코딩
    → discover.py를 실행할수록 유니버스가 자동으로 풍부해짐.
    """
    import json, os
    approved_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "approved_universe.json"
    )

    if not os.path.exists(approved_path):
        return list(ETF_UNIVERSE)  # 최초 실행 전이면 하드코딩 기본값

    try:
        with open(approved_path, encoding="utf-8") as f:
            data = json.load(f)
        approved_assets = data.get("assets", [])

        # 기존 ETF_UNIVERSE에 없는 자산만 추가 (중복 방지)
        existing_tickers = {e["ticker"] for e in ETF_UNIVERSE}
        extra = [a for a in approved_assets if a["ticker"] not in existing_tickers]

        log.info(f"[universe] approved_universe.json 로드: 기본 {len(ETF_UNIVERSE)}개 + 자동발굴 {len(extra)}개")
        return list(ETF_UNIVERSE) + extra

    except Exception as e:
        log.warning(f"[universe] approved_universe.json 로드 실패({e}) — 기본값 사용")
        return list(ETF_UNIVERSE)


def get_etf_by_class(asset_class: str) -> list[dict]:
    return [e for e in ETF_UNIVERSE if e["asset_class"] == asset_class]


def get_etf_for_isa() -> list[dict]:
    return [e for e in ETF_UNIVERSE if "ISA" in e["account"]]


ASSET_CLASS_LABEL = {
    "kr_stock":   "🇰🇷 한국배당주",
    "us_stock":   "🇺🇸 미국배당주",
    "us_div_etf": "🇺🇸 미국배당ETF",
    "us_reit":    "🏢 미국리츠",
    "kr_reit":    "🏢 한국리츠",
    "kr_etf":     "🇰🇷 국내상장ETF",
    "defensive":  "🛡️ 방어형",
}

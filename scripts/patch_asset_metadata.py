"""
asset_metadata.json 완전 보강 패치
실행: python scripts/patch_asset_metadata.py

작업 내용:
  1. us_stock 13개 — 누락 필드 전체 추가
     (name_kr, type, yield_pct, consecutive_years, cagr_5y_pct,
      beta, sector_exposure, country, currency, isa_eligible,
      risk_level, description, strengths, weaknesses)
  2. kr_etf 섹션 신설 — 6개 한국 ETF 전체 메타
  3. defensive — AGG, SCHP, SGOV 누락 필드 추가
"""

import json, pathlib

DATA_PATH = pathlib.Path("data/asset_metadata.json")

# ── 1. US 개별주 완전 데이터 ───────────────────────────────────────
US_STOCK_FULL = {
    "KO": {
        "name": "Coca-Cola",
        "name_kr": "코카콜라",
        "type": "dividend_king",
        "type_label": "배당킹 (62년 연속)",
        "yield_pct": 3.1,
        "div_growth_rate_pct": 4.5,
        "consecutive_years": 62,
        "pay_months": [1, 4, 7, 10],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 14.0,
        "max_drawdown_pct": -28.0,
        "cagr_5y_pct": 8.5,
        "beta": 0.60,
        "sector_exposure": {"소비재(필수)": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "low",
        "description": "62년 연속 배당 증가. 전 세계 200+국 판매 브랜드 해자. 경기방어주 대표.",
        "strengths": ["배당킹 62년", "글로벌 브랜드 해자", "경기 방어적"],
        "weaknesses": ["성장성 제한적", "PER 높음"]
    },
    "JNJ": {
        "name": "Johnson & Johnson",
        "name_kr": "존슨앤존슨",
        "type": "dividend_king",
        "type_label": "배당킹 (62년 연속)",
        "yield_pct": 3.2,
        "div_growth_rate_pct": 5.5,
        "consecutive_years": 62,
        "pay_months": [3, 6, 9, 12],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 15.0,
        "max_drawdown_pct": -30.0,
        "cagr_5y_pct": 6.0,
        "beta": 0.55,
        "sector_exposure": {"헬스케어": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "low",
        "description": "62년 연속 배당 증가. 의약품·의료기기 글로벌 1위. 켄뷰 분사 후 순수 헬스케어.",
        "strengths": ["배당킹 62년", "헬스케어 해자", "방어적 수익"],
        "weaknesses": ["성장성 둔화", "소송 리스크"]
    },
    "PG": {
        "name": "Procter & Gamble",
        "name_kr": "프록터앤갬블",
        "type": "dividend_king",
        "type_label": "배당킹 (67년 연속)",
        "yield_pct": 2.5,
        "div_growth_rate_pct": 5.0,
        "consecutive_years": 67,
        "pay_months": [2, 5, 8, 11],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 13.0,
        "max_drawdown_pct": -27.0,
        "cagr_5y_pct": 8.8,
        "beta": 0.60,
        "sector_exposure": {"소비재(필수)": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "low",
        "description": "67년 연속 배당 증가. 타이드·질레트·팸퍼스 등 50+개 글로벌 필수소비재 브랜드.",
        "strengths": ["배당킹 67년", "필수소비재 가격결정력", "인플레 전가력"],
        "weaknesses": ["성장성 제한적", "신흥시장 환율 리스크"]
    },
    "XOM": {
        "name": "ExxonMobil",
        "name_kr": "엑슨모빌",
        "type": "dividend_aristocrat",
        "type_label": "배당귀족 (41년 연속)",
        "yield_pct": 3.4,
        "div_growth_rate_pct": 3.5,
        "consecutive_years": 41,
        "pay_months": [3, 6, 9, 12],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 22.0,
        "max_drawdown_pct": -42.0,
        "cagr_5y_pct": 12.5,
        "beta": 1.00,
        "sector_exposure": {"에너지": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "41년 연속 배당 증가. 세계 최대 민간 에너지 기업. Pioneer 인수로 Permian 강화.",
        "strengths": ["배당귀족 41년", "에너지 최대 규모·현금창출", "Permian 저비용 생산"],
        "weaknesses": ["유가 변동성 노출", "에너지 전환 리스크"]
    },
    "CVX": {
        "name": "Chevron",
        "name_kr": "쉐브론",
        "type": "dividend_aristocrat",
        "type_label": "배당귀족 (36년 연속)",
        "yield_pct": 4.1,
        "div_growth_rate_pct": 4.0,
        "consecutive_years": 36,
        "pay_months": [3, 6, 9, 12],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 21.0,
        "max_drawdown_pct": -40.0,
        "cagr_5y_pct": 11.0,
        "beta": 0.95,
        "sector_exposure": {"에너지": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "36년 연속 배당 증가. XOM 대비 낮은 부채·높은 손익분기점 경쟁력. 자사주 매입 적극적.",
        "strengths": ["배당귀족 36년", "강한 대차대조표", "자사주 매입 적극적"],
        "weaknesses": ["유가 의존", "에너지 전환 리스크"]
    },
    "ABBV": {
        "name": "AbbVie",
        "name_kr": "애브비",
        "type": "dividend_aristocrat",
        "type_label": "배당귀족 (52년 연속 — Abbott 포함)",
        "yield_pct": 3.8,
        "div_growth_rate_pct": 7.0,
        "consecutive_years": 52,
        "pay_months": [2, 5, 8, 11],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 20.0,
        "max_drawdown_pct": -38.0,
        "cagr_5y_pct": 9.5,
        "beta": 0.55,
        "sector_exposure": {"헬스케어": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium-low",
        "description": "52년 연속 배당 증가. 스카이리지·린보크 신약으로 휴미라 특허 만료 성공적 대응. 고배당·고성장.",
        "strengths": ["배당귀족 52년", "강력한 신약 파이프라인", "높은 배당 성장률"],
        "weaknesses": ["휴미라 특허 만료 진행", "바이오시밀러 경쟁"]
    },
    "MCD": {
        "name": "McDonald's",
        "name_kr": "맥도날드",
        "type": "dividend_aristocrat",
        "type_label": "배당귀족 (48년 연속)",
        "yield_pct": 2.4,
        "div_growth_rate_pct": 8.0,
        "consecutive_years": 48,
        "pay_months": [3, 6, 9, 12],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 16.0,
        "max_drawdown_pct": -32.0,
        "cagr_5y_pct": 9.5,
        "beta": 0.75,
        "sector_exposure": {"소비재(경기)": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "low-medium",
        "description": "48년 연속 배당 증가. 부동산+프랜차이즈 복합 모델. 경기침체 내성 강함.",
        "strengths": ["배당귀족 48년", "부동산·프랜차이즈 복합 해자", "침체 내성"],
        "weaknesses": ["성장 포화 시장", "소비자 건강 의식 리스크"]
    },
    "T": {
        "name": "AT&T",
        "name_kr": "AT&T",
        "type": "high_yield",
        "type_label": "고배당 (2022년 배당 삭감)",
        "yield_pct": 6.5,
        "div_growth_rate_pct": 0.0,
        "consecutive_years": 0,
        "pay_months": [2, 5, 8, 11],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 18.0,
        "max_drawdown_pct": -38.0,
        "cagr_5y_pct": 2.5,
        "beta": 0.65,
        "sector_exposure": {"통신": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "2022년 WBD 분사·배당 47% 삭감. 현재 안정화 단계. 통신 인프라 독점적 지위.",
        "strengths": ["높은 배당수익률 6.5%", "통신 인프라 독점 지위", "안정적 가입자 기반"],
        "weaknesses": ["배당 삭감 이력", "높은 부채", "5G 설비투자 부담"]
    },
    "VZ": {
        "name": "Verizon",
        "name_kr": "버라이즌",
        "type": "challenger",
        "type_label": "배당 도전자 (19년 연속)",
        "yield_pct": 6.8,
        "div_growth_rate_pct": 1.5,
        "consecutive_years": 19,
        "pay_months": [2, 5, 8, 11],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 17.0,
        "max_drawdown_pct": -36.0,
        "cagr_5y_pct": 1.5,
        "beta": 0.45,
        "sector_exposure": {"통신": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "19년 연속 배당 증가. 미국 최대 모바일 통신사. 높은 FCF로 배당 지속력 양호.",
        "strengths": ["매우 높은 배당수익률 6.8%", "안정적 통신 현금흐름", "낮은 베타"],
        "weaknesses": ["성장성 제한적", "높은 부채", "T·TMUS 경쟁 심화"]
    },
    "IBM": {
        "name": "IBM",
        "name_kr": "IBM",
        "type": "high_yield",
        "type_label": "고배당 (7년 연속 — Kyndryl 분사 후)",
        "yield_pct": 3.5,
        "div_growth_rate_pct": 1.0,
        "consecutive_years": 7,
        "pay_months": [3, 6, 9, 12],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 20.0,
        "max_drawdown_pct": -38.0,
        "cagr_5y_pct": 5.5,
        "beta": 0.85,
        "sector_exposure": {"IT": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "AI·하이브리드 클라우드 전환 중. Red Hat 인수로 클라우드 입지 강화. Kyndryl 분사 후 순수 SW 기업.",
        "strengths": ["AI·클라우드 전환 스토리", "엔터프라이즈 고객 기반", "꾸준한 배당"],
        "weaknesses": ["레거시 비즈니스 축소", "성장성 빅테크 대비 낮음"]
    },
    "MO": {
        "name": "Altria Group",
        "name_kr": "알트리아",
        "type": "dividend_king",
        "type_label": "배당킹 (54년 연속)",
        "yield_pct": 8.5,
        "div_growth_rate_pct": 3.0,
        "consecutive_years": 54,
        "pay_months": [1, 4, 7, 10],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 22.0,
        "max_drawdown_pct": -45.0,
        "cagr_5y_pct": 3.0,
        "beta": 0.60,
        "sector_exposure": {"소비재(필수)": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "54년 연속 배당 증가. 말보로 브랜드. 담배 시장 점유율 40%+. 극도로 높은 FCF.",
        "strengths": ["배당킹 54년", "극도로 높은 FCF", "강력한 가격 결정력"],
        "weaknesses": ["담배 시장 장기 축소", "규제·소송 리스크", "ESG 배제"]
    },
    "PFE": {
        "name": "Pfizer",
        "name_kr": "화이자",
        "type": "high_yield",
        "type_label": "고배당 (14년 연속)",
        "yield_pct": 6.5,
        "div_growth_rate_pct": 2.5,
        "consecutive_years": 14,
        "pay_months": [3, 6, 9, 12],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 24.0,
        "max_drawdown_pct": -42.0,
        "cagr_5y_pct": -2.0,
        "beta": 0.55,
        "sector_exposure": {"헬스케어": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "medium",
        "description": "14년 연속 배당 증가. 코로나 이후 수익 정상화 단계. Seagen 인수로 항암제 포트폴리오 강화.",
        "strengths": ["높은 배당수익률 6.5%", "글로벌 제약 파이프라인", "M&A 적극적"],
        "weaknesses": ["코로나 수익 급감 정상화 중", "R&D 불확실성"]
    },
}

# ── 2. 한국 ETF 전체 메타 (신규 섹션) ─────────────────────────────
KR_ETF_SECTION = {
    "_comment": "국내 상장 배당 ETF — ISA·연금 편입 가능, 원화 자산",
    "448290": {
        "name": "TIGER 미국배당다우존스",
        "name_kr": "TIGER 미국배당다우존스",
        "type": "dividend_growth",
        "type_label": "배당성장형 (SCHD 추종)",
        "yield_pct": 3.2,
        "div_growth_rate_pct": 9.5,
        "expense_ratio_pct": 0.05,
        "pay_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "pay_frequency": "monthly",
        "volatility_annual_pct": 15.5,
        "max_drawdown_pct": -33.0,
        "cagr_5y_pct": 11.0,
        "beta": 0.88,
        "sector_exposure": {"금융": 25, "헬스케어": 15, "소비재": 14, "IT": 13, "산업재": 12},
        "country": "KR",
        "currency": "KRW",
        "underlying_currency": "USD",
        "isa_eligible": True,
        "pension_eligible": True,
        "risk_level": "medium",
        "etf_category": "dividend_growth",
        "description": "SCHD(슈왑 배당성장 ETF) 추종 국내 상장판. 매월 배당 지급. ISA·연금 편입 가능.",
        "strengths": ["SCHD 동일 전략", "월 배당 지급", "ISA·연금 절세"],
        "weaknesses": ["USD/KRW 환율 노출", "SCHD 대비 소폭 추적 오차"]
    },
    "385720": {
        "name": "TIGER 리츠부동산인프라",
        "name_kr": "TIGER 리츠부동산인프라",
        "type": "reit",
        "type_label": "리츠·부동산 ETF",
        "yield_pct": 5.5,
        "div_growth_rate_pct": 3.0,
        "expense_ratio_pct": 0.29,
        "pay_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "pay_frequency": "monthly",
        "volatility_annual_pct": 16.0,
        "max_drawdown_pct": -38.0,
        "cagr_5y_pct": 6.0,
        "beta": 0.75,
        "sector_exposure": {"리츠": 60, "인프라": 25, "부동산": 15},
        "country": "KR",
        "currency": "KRW",
        "isa_eligible": True,
        "pension_eligible": True,
        "risk_level": "medium",
        "etf_category": "reit",
        "description": "국내·해외 리츠 및 부동산 인프라 ETF. 임대수익 기반 월 배당. 금리 민감형.",
        "strengths": ["높은 배당수익률", "월 배당 지급", "부동산 분산투자"],
        "weaknesses": ["금리 상승 시 NAV 하락", "환율 리스크(해외 리츠)"]
    },
    "279530": {
        "name": "KODEX 고배당",
        "name_kr": "KODEX 고배당",
        "type": "high_yield",
        "type_label": "한국 고배당주 ETF",
        "yield_pct": 4.8,
        "div_growth_rate_pct": 3.5,
        "expense_ratio_pct": 0.25,
        "pay_months": [1, 4, 7, 10],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 16.5,
        "max_drawdown_pct": -35.0,
        "cagr_5y_pct": 7.5,
        "beta": 0.90,
        "sector_exposure": {"금융": 35, "에너지": 20, "통신": 15, "소비재": 12, "산업재": 10},
        "country": "KR",
        "currency": "KRW",
        "isa_eligible": True,
        "pension_eligible": True,
        "risk_level": "medium",
        "etf_category": "high_yield",
        "description": "KRX 고배당지수 추종. 국내 고배당 대형주 중심. 분기 배당 지급.",
        "strengths": ["높은 국내 배당수익률", "ISA·연금 절세", "저렴한 비용"],
        "weaknesses": ["배당 감소 리스크", "코리아 디스카운트 노출"]
    },
    "211560": {
        "name": "TIGER 배당성장",
        "name_kr": "TIGER 배당성장",
        "type": "dividend_growth",
        "type_label": "한국 배당성장주 ETF",
        "yield_pct": 2.8,
        "div_growth_rate_pct": 7.0,
        "expense_ratio_pct": 0.19,
        "pay_months": [1, 4, 7, 10],
        "pay_frequency": "quarterly",
        "volatility_annual_pct": 17.0,
        "max_drawdown_pct": -33.0,
        "cagr_5y_pct": 8.0,
        "beta": 0.95,
        "sector_exposure": {"IT": 25, "금융": 20, "소비재": 18, "헬스케어": 12, "산업재": 10},
        "country": "KR",
        "currency": "KRW",
        "isa_eligible": True,
        "pension_eligible": True,
        "risk_level": "medium",
        "etf_category": "dividend_growth",
        "description": "배당성장 가능성 높은 국내 우량주 중심. 장기 복리 효과 추구. 연금·ISA 최적 조합.",
        "strengths": ["배당성장 중심 우량주", "ISA·연금 절세", "낮은 비용"],
        "weaknesses": ["현재 배당수익률 상대적 낮음", "코스피 연동"]
    },
    "441680": {
        "name": "KODEX 배당성장채권혼합-액티브",
        "name_kr": "KODEX 배당성장채권혼합",
        "type": "dividend_growth",
        "type_label": "배당성장+채권 혼합형",
        "yield_pct": 3.5,
        "div_growth_rate_pct": 5.5,
        "expense_ratio_pct": 0.25,
        "pay_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "pay_frequency": "monthly",
        "volatility_annual_pct": 10.5,
        "max_drawdown_pct": -22.0,
        "cagr_5y_pct": 6.5,
        "beta": 0.55,
        "sector_exposure": {"채권": 40, "금융": 20, "소비재": 15, "IT": 12, "산업재": 8},
        "country": "KR",
        "currency": "KRW",
        "isa_eligible": True,
        "pension_eligible": True,
        "risk_level": "low-medium",
        "etf_category": "dividend_growth",
        "description": "국내 배당성장주 60% + 채권 40% 혼합. 낮은 변동성 + 안정적 월 배당. 은퇴·안정형 최적.",
        "strengths": ["채권 혼합으로 낮은 변동성", "월 배당 지급", "ISA·연금 절세"],
        "weaknesses": ["채권 비중으로 성장성 제한", "금리 상승 시 채권 부분 손실"]
    },
    "456680": {
        "name": "TIGER 미국MSCI리츠(합성H)",
        "name_kr": "TIGER 미국MSCI리츠",
        "type": "reit",
        "type_label": "미국 리츠 ETF (환헤지)",
        "yield_pct": 4.5,
        "div_growth_rate_pct": 3.0,
        "expense_ratio_pct": 0.49,
        "pay_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "pay_frequency": "monthly",
        "volatility_annual_pct": 18.0,
        "max_drawdown_pct": -40.0,
        "cagr_5y_pct": 5.0,
        "beta": 0.70,
        "sector_exposure": {"미국리츠": 100},
        "country": "KR",
        "currency": "KRW",
        "underlying_currency": "USD",
        "hedged": True,
        "isa_eligible": True,
        "pension_eligible": True,
        "risk_level": "medium",
        "etf_category": "reit",
        "description": "미국 MSCI 리츠지수 추종 + 환헤지. 달러 환율 리스크 제거하고 미국 부동산 배당 수취. 월 배당.",
        "strengths": ["환헤지로 환율 리스크 제거", "미국 리츠 분산투자", "월 배당"],
        "weaknesses": ["환헤지 비용", "미국 금리 상승 시 리츠 가격 하락", "비싼 운용보수"]
    },
}

# ── 3. Defensive 보강 데이터 ──────────────────────────────────────
DEFENSIVE_PATCH = {
    "AGG": {
        "cagr_5y_pct": 0.5,
        "beta": 0.03,
        "sector_exposure": {"미국국채": 42, "회사채": 26, "모기지": 23, "기타": 9},
        "strengths": ["초저비용", "매우 낮은 변동성", "월 지급"],
        "weaknesses": ["수익률 낮음", "인플레이션 취약"],
    },
    "SCHP": {
        "cagr_5y_pct": 1.2,
        "beta": 0.10,
        "sector_exposure": {"미국 TIPS": 100},
        "strengths": ["인플레이션 직접 헤지", "초저비용", "월 지급"],
        "weaknesses": ["금리 상승 시에도 가격 하락", "디플레이션 시 수익률 낮음"],
    },
    "SGOV": {
        "name": "iShares 0-3 Month Treasury Bond ETF",
        "name_kr": "초단기 미국채 ETF (0-3개월)",
        "type": "cash_equivalent",
        "type_label": "현금 대등물 (초단기채)",
        "yield_pct": 5.2,
        "div_growth_rate_pct": 0.0,
        "expense_ratio_pct": 0.09,
        "pay_months": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
        "pay_frequency": "monthly",
        "volatility_annual_pct": 0.3,
        "max_drawdown_pct": -0.1,
        "cagr_5y_pct": 3.5,
        "beta": 0.00,
        "sector_exposure": {"미국 T-Bill(0-3개월)": 100},
        "country": "US",
        "currency": "USD",
        "isa_eligible": True,
        "risk_level": "very-low",
        "description": "만기 0-3개월 미국 단기국채. 사실상 무위험. CMA 대체재로 현금 파킹 최적. 현재 금리 ~5.2%.",
        "strengths": ["사실상 무위험 5%+ 수익", "즉시 유동성", "월 이자 지급"],
        "weaknesses": ["금리 하락 시 수익률 감소", "장기 성장성 없음"],
    },
}

# ── 패치 실행 ─────────────────────────────────────────────────────
with open(DATA_PATH) as f:
    meta = json.load(f)

# 1. us_stock 전체 교체
meta["us_stock"] = {
    "_comment": "미국 배당 개별주 — Dividend King/Aristocrat/Challenger/High-Yield 구분",
    **US_STOCK_FULL,
}

# 2. kr_etf 섹션 신설
meta["kr_etf"] = KR_ETF_SECTION

# 3. defensive 보강
for ticker, patch in DEFENSIVE_PATCH.items():
    if ticker in meta["defensive"]:
        meta["defensive"][ticker].update(patch)
    else:
        meta["defensive"][ticker] = patch

# 저장 (백업 먼저)
import shutil
shutil.copy(DATA_PATH, DATA_PATH.with_suffix(".bak.json"))
with open(DATA_PATH, "w", encoding="utf-8") as f:
    json.dump(meta, f, indent=2, ensure_ascii=False)

print("✅ asset_metadata.json 패치 완료")
print(f"  us_stock: {len(meta['us_stock'])-1}개 (완전 보강)")
print(f"  kr_etf:   {len(meta['kr_etf'])-1}개 (신규)")
print(f"  defensive: {len(meta['defensive'])}개")
print()

# 검증
for ticker in ['KO', 'XOM', 'T', 'PFE']:
    s = meta['us_stock'][ticker]
    print(f"  [{ticker}] yield={s['yield_pct']}%  consec={s['consecutive_years']}yr  beta={s['beta']}  cagr5y={s['cagr_5y_pct']}%")
print()
for ticker in ['448290', '385720', '441680']:
    s = meta['kr_etf'][ticker]
    print(f"  [{ticker}] {s['name_kr']}  yield={s['yield_pct']}%  monthly={s['pay_frequency']}")
print()
s = meta['defensive']['SGOV']
print(f"  [SGOV] yield={s['yield_pct']}%  beta={s['beta']}  type={s['type']}")

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

from collectors.price     import collect_price
from collectors.dart      import collect_financials
from collectors.naver     import collect_naver_valuation
from collectors.macro     import collect_macro
from collectors.dividend  import compute_dividend_metrics
from collectors.events    import collect_events
from collectors.llm       import generate_thesis
from collectors.conditions import generate_conditions
from collectors.monitor   import check_conditions
from collectors.action    import generate_action
from analyzers.yield_trap import analyze as yield_trap_analyze, get_metrics_from_db
from analyzers.simulator  import SimulationInput, simulate, format_report
from sqlalchemy import create_engine, text

engine = create_engine("postgresql://localhost/ai_analyst")


def ensure_schema():
    """필요한 테이블 자동 생성"""
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS events (
                id SERIAL PRIMARY KEY,
                stock_code VARCHAR(20) NOT NULL,
                date DATE NOT NULL,
                headline TEXT,
                event_type VARCHAR(50),
                impact VARCHAR(20),
                thesis_relevance VARCHAR(20),
                summary TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                CONSTRAINT uq_events UNIQUE (stock_code, date, headline)
            )
        """))
        conn.commit()


def run(stock_code: str, stock_name: str, corp_code: str,
        monthly_invest: int = 0, target_monthly_div: int = 0,
        current_age: int = 0, retire_age: int = 65,
        monthly_salary: int = 0, existing_assets: float = 0):
    """
    Args:
        monthly_invest:    월 투자금 (원). 0이면 시뮬레이션 생략.
        target_monthly_div: 목표 월 배당금 (원).
        current_age:       현재 나이. 0이면 나이 맥락 무시.
        retire_age:        은퇴 목표 나이 (기본 65).
        monthly_salary:    세후 월 급여 (원). 0이면 선택지 생략.
        existing_assets:   이미 보유한 여유자금 (원). Day 0에 투자 반영.
    """
    ensure_schema()

    print(f"\n{'='*54}")
    print(f"  {stock_name} ({stock_code}) 배당 분석 시작")
    print(f"{'='*54}\n")

    # 종목 등록
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO stocks (code, name, sector)
            VALUES (:code, :name, '배당분석')
            ON CONFLICT (code) DO NOTHING
        """), {"code": stock_code, "name": stock_name})
        conn.commit()

    # ① 데이터 수집
    print("① 기초 데이터 수집 중...")
    collect_price(stock_code)
    collect_financials(corp_code, stock_code, "2025")
    collect_naver_valuation(stock_code)
    collect_macro()

    # ② 배당 파생 지표 계산 (핵심)
    print("\n② 배당 파생 지표 계산 중...")
    print("   (FCF, 배당성향, 커버리지, DPS, 배당수익률, 순이익성장률)")
    compute_dividend_metrics(stock_code, corp_code, "2025")

    # ② Yield Trap 즉시 판정 (룰 엔진)
    metrics = get_metrics_from_db(stock_code)
    trap    = yield_trap_analyze(metrics)
    print(f"\n   [Yield Trap 판정] {trap['summary']}")
    for s in trap["signals"]:
        print(f"   {'⛔' if s['severity']=='DANGER' else '⚠️ '} {s['description']}")

    # ③ 이벤트 수집
    print("\n③ 이벤트 수집 중 (DART 공시 + 뉴스)...")
    collect_events(stock_code, stock_name, corp_code)

    # ④ 배당 thesis 생성
    print("\n④ 배당 thesis 생성 중...")
    thesis_text = generate_thesis(stock_name, stock_code)
    print(thesis_text)

    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE conditions SET is_active = FALSE
            WHERE thesis_id IN (SELECT id FROM thesis WHERE stock_code = :code)
        """), {"code": stock_code})
        result = conn.execute(text("""
            INSERT INTO thesis (stock_code, content)
            VALUES (:code, :content) RETURNING id
        """), {"code": stock_code, "content": thesis_text})
        thesis_id = result.fetchone()[0]
        conn.commit()

    # ⑤ 배당 이탈 조건 생성
    print("\n⑤ 배당 이탈 조건 생성 중...")
    generate_conditions(thesis_id, thesis_text)

    # ⑥ 조건 모니터링
    print("\n⑥ 조건 모니터링 중...")
    check_conditions(stock_code)

    # ⑦ thesis 판정
    print("\n⑦ 배당 thesis 판정 중...")
    generate_action(stock_code, stock_name)

    # ⑧ 나이·월급·여유자금 기반 시뮬레이션 (선택)
    if monthly_invest > 0:
        dy = metrics.get("dividend_yield", 3.5)
        age_label = f"{current_age}세" if current_age > 0 else "나이 미설정"
        print(f"\n⑧ 배당 시뮬레이션 ({age_label}, 월 {monthly_invest//10000}만원 투자)")
        inp = SimulationInput(
            monthly_invest=monthly_invest,
            target_monthly_dividend=target_monthly_div or monthly_invest,
            initial_yield=dy,
            dividend_growth_rate=0.03,
            current_age=current_age,
            retire_age=retire_age,
            monthly_salary=monthly_salary,
            existing_assets=existing_assets,
            use_isa=False,
        )
        results = simulate(inp)
        print(format_report(inp, results))

    print(f"\n{'='*54}")
    print(f"  분석 완료")
    print(f"{'='*54}\n")


if __name__ == "__main__":
    run(
        stock_code="033780",
        stock_name="KT&G",
        corp_code="00140516",
        monthly_invest=500_000,       # 월 50만원 투자
        target_monthly_div=500_000,   # 목표: 월 50만원 배당
        current_age=35,               # 현재 나이 (은퇴까지 30년 자동 계산)
        retire_age=65,                # 은퇴 목표 나이
        monthly_salary=3_000_000,     # 세후 월급 300만원 (선택지 자동 생성)
        existing_assets=10_000_000,   # 이미 있는 여유자금 1000만원
    )

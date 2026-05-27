"""
KRX 고배당 50 전체 종목 일괄 분석 스크립트.

■ 무엇을 하는가
  1. pykrx로 KRX 고배당 50 구성 종목 동적 조회 (실패 시 하드코딩 50종목)
  2. 종목별 전체 파이프라인 순차 실행
       수집(주가/재무/밸류에이션) → Yield Trap → Thesis 생성 → Scoring
  3. 완료된 종목은 체크포인트에 저장 → 중단 후 재실행 시 이어서 처리
  4. 전체 완료 후 점수 순위표 CSV + Excel 저장

■ 실행
  python run_all.py            # 전체 실행
  python run_all.py --reset    # 체크포인트 초기화 후 처음부터

■ 출력 파일
  ranking.csv   /  ranking.xlsx   (전체 순위표)
  run_checkpoint.json            (중단 재시작용 체크포인트)
"""

import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os, sys, json, time
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
engine = create_engine("postgresql://localhost/ai_analyst")

# ─────────────────────────────────────────────────────────────
# KRX 고배당 50 구성 종목 — 하드코딩 fallback
# 출처: KRX 고배당 50 지수 (2024년 기준 구성 종목)
# pykrx 조회 실패 시 이 목록 사용
# ─────────────────────────────────────────────────────────────

KRX_HIGH_DIV_50_FALLBACK = [
    # 금융 (보험)
    ("000810", "삼성화재"),
    ("005830", "DB손해보험"),
    ("001450", "현대해상"),
    ("000060", "메리츠화재"),
    ("082640", "동양생명"),
    # 금융 (은행·지주)
    ("105560", "KB금융"),
    ("055550", "신한지주"),
    ("086790", "하나금융지주"),
    ("316140", "우리금융지주"),
    ("024110", "기업은행"),
    ("138930", "BNK금융지주"),
    ("139130", "DGB금융지주"),
    ("175330", "JB금융지주"),
    # 금융 (증권)
    ("016360", "삼성증권"),
    ("005940", "NH투자증권"),
    ("006800", "미래에셋증권"),
    ("071050", "한국금융지주"),
    ("039490", "키움증권"),
    ("030200", "KT"),
    # 통신
    ("017670", "SK텔레콤"),
    ("032640", "LG유플러스"),
    # 에너지·정유
    ("010950", "S-Oil"),
    ("078930", "GS"),
    ("096770", "SK이노베이션"),
    # 유틸리티
    ("036460", "한국가스공사"),
    ("015760", "한국전력"),
    # 담배·소비재
    ("033780", "KT&G"),
    ("021240", "코웨이"),
    # 카지노·레저
    ("035250", "강원랜드"),
    ("114090", "GKL"),
    # 철강·소재
    ("005490", "POSCO홀딩스"),
    ("003410", "쌍용씨앤이"),
    # 자동차
    ("005380", "현대차"),
    ("000270", "기아"),
    # 반도체·전자
    ("005930", "삼성전자"),
    # 화학·섬유
    ("004800", "효성"),
    ("298020", "효성티앤씨"),
    ("096400", "효성중공업"),
    # 건설
    ("000720", "현대건설"),
    # 지주
    ("000150", "두산"),
    ("001040", "CJ"),
    ("002030", "아세아"),
    # 해운·물류
    ("011200", "HMM"),
    # 기타 고배당주
    ("002960", "한국쉘석유"),
    ("006360", "GS건설"),
    ("009830", "한화솔루션"),
    ("018260", "삼성에스디에스"),
    ("068270", "셀트리온"),
    ("326030", "SK바이오팜"),
]


# ─────────────────────────────────────────────────────────────
# 1. KRX 고배당 50 구성 종목 조회
# ─────────────────────────────────────────────────────────────

def get_krx_high_div_50() -> list[tuple[str, str]]:
    """
    pykrx로 KRX 고배당 50 구성 종목 동적 조회.
    실패하면 하드코딩 목록 반환.

    반환: [(stock_code, name), ...]
    """
    print("📋 KRX 고배당 50 종목 목록 조회 중...")
    try:
        from pykrx import stock

        # KRX 고배당 50 인덱스 코드 탐색
        # 시장별로 인덱스 목록 순회해서 '고배당' 포함 항목 찾기
        for market in ("KRX", "KOSPI", "KOSDAQ"):
            try:
                idx_list = stock.get_index_ticker_list(market=market)
                for idx_code in idx_list:
                    try:
                        idx_name = stock.get_index_ticker_name(idx_code)
                        if "고배당" in idx_name and "50" in idx_name:
                            print(f"  ✅ 인덱스 발견: {idx_code} ({idx_name})")
                            tickers = stock.get_index_portfolio_deposit_file(idx_code)
                            if tickers:
                                result = []
                                for t in tickers:
                                    try:
                                        name = stock.get_market_ticker_name(t)
                                        result.append((t, name))
                                    except Exception:
                                        result.append((t, t))
                                print(f"  → {len(result)}개 종목 동적 로드 완료")
                                return result
                    except Exception:
                        continue
            except Exception:
                continue

    except ImportError:
        print("  ⚠️ pykrx 없음")
    except Exception as e:
        print(f"  ⚠️ 동적 조회 실패: {e}")

    print(f"  → 하드코딩 fallback 사용 ({len(KRX_HIGH_DIV_50_FALLBACK)}개 종목)")
    return KRX_HIGH_DIV_50_FALLBACK


# ─────────────────────────────────────────────────────────────
# 2. corp_code 일괄 조회 (DB corp_code_map)
# ─────────────────────────────────────────────────────────────

def load_corp_codes_from_db(stock_codes: list[str]) -> dict[str, str]:
    """
    DB corp_code_map 테이블에서 stock_code → corp_code 매핑 일괄 조회.
    init_corp_codes.py 실행 후 사용 가능.
    """
    mapping = {}
    try:
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT stock_code, corp_code
                FROM corp_code_map
                WHERE stock_code = ANY(:codes)
            """), {"codes": stock_codes}).fetchall()
        for r in rows:
            mapping[r[0]] = r[1]
        print(f"  DB에서 corp_code 로드: {len(mapping)}/{len(stock_codes)}개")
    except Exception as e:
        print(f"  ⚠️ DB corp_code 조회 실패: {e}")
    return mapping


# ─────────────────────────────────────────────────────────────
# 3. 체크포인트 (중단 재시작)
# ─────────────────────────────────────────────────────────────

CHECKPOINT_FILE = "run_checkpoint.json"

def load_checkpoint() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return {"completed": [], "results": []}


def save_checkpoint(cp: dict):
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────
# 4. 단일 종목 분석 (에러 격리)
# ─────────────────────────────────────────────────────────────

def analyze_one(stock_code: str, stock_name: str, corp_code: str) -> dict | None:
    """
    단일 종목 전체 파이프라인 실행.
    에러 발생 시 None 반환 (전체 중단 없음).

    포함 단계:
      수집(주가/재무/밸류에이션) → Yield Trap → Thesis → Scoring
    시뮬레이션은 제외 (개인 파라미터 필요)
    """
    from collectors.price     import collect_price
    from collectors.dart      import collect_financials
    from collectors.naver     import collect_naver_valuation
    from collectors.dividend  import compute_dividend_metrics
    from collectors.llm       import generate_thesis
    from analyzers.yield_trap import analyze as yield_trap_analyze, get_metrics_from_db
    from analyzers.scorer     import score_thesis

    try:
        # ① 데이터 수집
        collect_price(stock_code)
        collect_financials(corp_code, stock_code, "2025")
        collect_naver_valuation(stock_code)

        # ② 배당 파생 지표
        compute_dividend_metrics(stock_code, corp_code, "2025")

        # ③ Yield Trap 판정
        metrics = get_metrics_from_db(stock_code)
        trap    = yield_trap_analyze(metrics)

        # ④ Thesis 생성
        thesis_text = generate_thesis(stock_name, stock_code)

        # thesis DB 저장
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE conditions SET is_active = FALSE
                WHERE thesis_id IN (SELECT id FROM thesis WHERE stock_code = :code)
            """), {"code": stock_code})
            result = conn.execute(text("""
                INSERT INTO thesis (stock_code, content)
                VALUES (:code, :content) RETURNING id
            """), {"code": stock_code, "content": thesis_text})
            conn.commit()

        # ⑤ Thesis Scoring
        scores = score_thesis(stock_code, stock_name, thesis_text, metrics, trap)

        return {
            "stock_code":    stock_code,
            "name":          stock_name,
            "overall_score": scores.get("overall_score", 0),
            "stability":     scores.get("stability_score", 0),
            "risk":          scores.get("risk_score", 0),
            "momentum":      scores.get("momentum_score", 0),
            "trap_level":    trap.get("level", "UNKNOWN"),
            "yield":         metrics.get("dividend_yield"),
            "coverage":      metrics.get("dividend_coverage"),
            "payout":        metrics.get("payout_ratio"),
            "score_reason":  scores.get("score_reason", ""),
        }

    except Exception as e:
        print(f"\n  ❌ {stock_name} ({stock_code}) 분석 실패: {e}")
        return None


# ─────────────────────────────────────────────────────────────
# 5. 순위표 저장
# ─────────────────────────────────────────────────────────────

GRADE_MAP = {
    lambda s: s >= 70: "🟢 우량",
    lambda s: s >= 50: "🟡 보통",
    lambda s: s  < 50: "🔴 위험",
}

def get_grade(score: int) -> str:
    if score >= 70: return "🟢 우량"
    if score >= 50: return "🟡 보통"
    return "🔴 위험"


def save_ranking(results: list[dict], out_dir: str = "."):
    """점수 기준 내림차순 정렬 후 CSV + Excel 저장."""
    df = pd.DataFrame(results)
    df = df.sort_values("overall_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    df["grade"] = df["overall_score"].apply(get_grade)

    # 수치 포맷
    for col in ("yield", "coverage", "payout"):
        if col in df.columns:
            df[col] = df[col].apply(lambda x: round(x, 2) if pd.notna(x) and x is not None else None)

    col_order = [
        "rank", "name", "stock_code", "grade", "overall_score",
        "stability", "risk", "momentum",
        "trap_level", "yield", "coverage", "payout", "score_reason",
    ]
    df = df[[c for c in col_order if c in df.columns]]

    col_kr = {
        "rank": "순위", "name": "종목명", "stock_code": "종목코드",
        "grade": "등급", "overall_score": "종합점수",
        "stability": "안정성", "risk": "안전도", "momentum": "모멘텀",
        "trap_level": "Yield Trap", "yield": "배당수익률(%)",
        "coverage": "배당커버리지", "payout": "배당성향(%)",
        "score_reason": "AI 평가",
    }

    os.makedirs(out_dir, exist_ok=True)

    # CSV
    csv_path = os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"), "ranking.csv")
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"\n  ✅ CSV 저장: {csv_path}")

    # Excel
    xlsx_path = os.path.join(out_dir, "ranking.xlsx")
    df_kr = df.rename(columns=col_kr)
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        df_kr.to_excel(writer, sheet_name="전체순위", index=False)

        # 등급별 시트
        for grade_label, grade_str in [("우량", "🟢 우량"), ("보통", "🟡 보통"), ("위험", "🔴 위험")]:
            grp = df_kr[df_kr["등급"] == grade_str]
            if not grp.empty:
                grp.to_excel(writer, sheet_name=grade_label, index=False)

        # 간단 통계
        stats = pd.DataFrame({
            "항목": ["분석 종목 수", "우량(70점↑)", "보통(50~69점)", "위험(50점↓)",
                     "평균 종합점수", "평균 배당수익률(%)"],
            "값": [
                len(df),
                int((df["overall_score"] >= 70).sum()),
                int(((df["overall_score"] >= 50) & (df["overall_score"] < 70)).sum()),
                int((df["overall_score"] < 50).sum()),
                round(df["overall_score"].mean(), 1),
                round(df["yield"].dropna().mean(), 2) if "yield" in df.columns else "-",
            ]
        })
        stats.to_excel(writer, sheet_name="요약통계", index=False)

    print(f"  ✅ Excel 저장: {xlsx_path}")

    # 콘솔 순위표 미리보기 (상위 10개)
    print(f"\n{'─'*70}")
    print(f"  {'순위':<4} {'종목명':<12} {'등급':<8} {'종합':<6} {'안정성':<6} {'안전도':<6} {'모멘텀':<6} Trap")
    print(f"{'─'*70}")
    for _, row in df.head(10).iterrows():
        trap = row.get("trap_level", "")[:6]
        print(f"  {int(row['rank']):<4} {str(row['name']):<12} {str(row['grade']):<8} "
              f"{int(row['overall_score']):<6} {int(row['stability']):<6} "
              f"{int(row['risk']):<6} {int(row['momentum']):<6} {trap}")
    if len(df) > 10:
        print(f"  ... 외 {len(df)-10}개 종목 (ranking.xlsx 참조)")
    print(f"{'─'*70}")


# ─────────────────────────────────────────────────────────────
# 6. 메인
# ─────────────────────────────────────────────────────────────

def ensure_schema():
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS scores (
                id              SERIAL PRIMARY KEY,
                stock_code      VARCHAR(20) NOT NULL,
                stability_score INTEGER,
                risk_score      INTEGER,
                momentum_score  INTEGER,
                overall_score   INTEGER,
                score_reason    TEXT,
                created_at      TIMESTAMP DEFAULT NOW()
            )
        """))
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


def main():
    # ── 체크포인트 초기화 옵션 ──
    if "--reset" in sys.argv:
        if os.path.exists(CHECKPOINT_FILE):
            os.remove(CHECKPOINT_FILE)
        print("🔄 체크포인트 초기화 완료. 처음부터 시작합니다.")

    ensure_schema()

    # ① 종목 목록 확보
    stocks = get_krx_high_div_50()
    print(f"\n총 {len(stocks)}개 종목 분석 예정")

    # ② corp_code 매핑
    all_codes = [sc for sc, _ in stocks]
    corp_map  = load_corp_codes_from_db(all_codes)

    # ③ 체크포인트 로드
    cp = load_checkpoint()
    done_set = set(cp["completed"])
    results  = cp["results"]

    if done_set:
        print(f"  이전 체크포인트: {len(done_set)}개 완료, 이어서 시작")

    # ④ 매크로 데이터 1회 수집
    print("\n🌐 거시 데이터 수집 중...")
    try:
        from collectors.macro import collect_macro
        collect_macro()
    except Exception as e:
        print(f"  ⚠️ 거시 데이터 수집 실패 (계속 진행): {e}")

    # ⑤ 종목별 분석 루프
    total   = len(stocks)
    success = 0
    failed  = []

    print(f"\n{'='*54}")
    print(f"  KRX 고배당 50 일괄 분석 시작")
    print(f"{'='*54}\n")

    for i, (stock_code, stock_name) in enumerate(stocks, 1):
        if stock_code in done_set:
            print(f"[{i:>2}/{total}] {stock_name} ({stock_code}) — 이미 완료, 건너뜀")
            continue

        print(f"\n[{i:>2}/{total}] {stock_name} ({stock_code}) 분석 시작...")

        # corp_code 없으면 건너뜀
        corp_code = corp_map.get(stock_code)
        if not corp_code:
            print(f"  ⚠️ corp_code 없음 — init_corp_codes.py를 먼저 실행하세요")
            failed.append(f"{stock_name}({stock_code}): corp_code 없음")
            continue

        # 종목 DB 등록
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO stocks (code, name, sector)
                    VALUES (:code, :name, '배당분석')
                    ON CONFLICT (code) DO NOTHING
                """), {"code": stock_code, "name": stock_name})
                conn.commit()
        except Exception:
            pass

        # 분석 실행
        result = analyze_one(stock_code, stock_name, corp_code)

        if result:
            results.append(result)
            success += 1
            print(f"  ✅ 완료 | 종합 {result['overall_score']}점 {get_grade(result['overall_score'])}")
        else:
            failed.append(f"{stock_name}({stock_code})")

        # 체크포인트 저장 (매 종목 완료 후)
        cp["completed"].append(stock_code)
        cp["results"] = results
        save_checkpoint(cp)

        # API 부하 분산 (종목 간 2초 대기)
        if i < total:
            time.sleep(2)

    # ⑥ 순위표 저장
    if results:
        print(f"\n\n💾 순위표 저장 중... ({len(results)}개 종목)")
        save_ranking(results)
    else:
        print("\n⚠️ 분석 결과가 없습니다.")

    # ⑦ 최종 요약
    print(f"\n{'='*54}")
    print(f"  분석 완료: {success}/{total}개 성공")
    if failed:
        print(f"  실패 ({len(failed)}개): {', '.join(failed)}")
    print(f"{'='*54}\n")


if __name__ == "__main__":
    main()

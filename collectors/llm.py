import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import create_engine, text
from pykrx import stock as krx
from datetime import datetime, timedelta, date
from collectors.macro import get_macro_context
from analyzers.yield_trap import analyze as yield_trap_analyze, get_metrics_from_db

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = "llama-3.3-70b-versatile"
engine = create_engine("postgresql://localhost/ai_analyst")


# ── 주가·기술 지표 ─────────────────────────────────────────────────────────────

def get_price_context(stock_code: str) -> dict:
    today = datetime.today().strftime("%Y%m%d")
    start = (datetime.today() - timedelta(days=120)).strftime("%Y%m%d")
    df = krx.get_market_ohlcv(start, today, stock_code)
    close = df["종가"]

    current   = float(close.iloc[-1])
    high_52w  = float(close.max())
    low_52w   = float(close.min())
    pct_range = (current - low_52w) / (high_52w - low_52w) * 100 if high_52w != low_52w else 50

    chg_20 = (close.iloc[-1]/close.iloc[-21] - 1)*100 if len(close) >= 21 else None
    chg_60 = (close.iloc[-1]/close.iloc[-61] - 1)*100 if len(close) >= 61 else None

    # RSI-14
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(14).mean()
    loss  = delta.clip(upper=0).abs().rolling(14).mean()
    rsi   = float((100 - 100 / (1 + gain / loss)).iloc[-1])

    # 주가 추세: 20일 이동평균 대비 현재가
    ma20 = float(close.rolling(20).mean().iloc[-1])
    trend_pct = (current - ma20) / ma20 * 100

    return {
        "current":   current,
        "high_52w":  high_52w,
        "low_52w":   low_52w,
        "pct_range": pct_range,
        "chg_20":    chg_20,
        "chg_60":    chg_60,
        "rsi":       rsi,
        "ma20":      ma20,
        "trend_pct": trend_pct,   # 양수=MA 위(강세), 음수=MA 아래(약세)
    }


# ── 재무 + 배당 지표 DB 조회 ───────────────────────────────────────────────────

def get_dividend_context(stock_code: str) -> dict:
    """배당 분석에 필요한 모든 지표를 DB에서 최신값으로 가져옴"""
    needed = [
        "dividend_yield", "payout_ratio", "dividend_coverage",
        "free_cash_flow", "earnings_growth", "net_income",
        "dividends_paid", "revenue", "op_income",
        "dividend_per_share", "operating_cf", "capex",
        "per", "market_cap_억",
    ]
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT metric_name, value FROM metric_snapshots
            WHERE stock_code = :code
              AND metric_name = ANY(:metrics)
            ORDER BY date DESC
        """), {"code": stock_code, "metrics": needed}).fetchall()

    result, seen = {}, set()
    for metric, value in rows:
        if metric not in seen:
            result[metric] = float(value)
            seen.add(metric)
    return result


# ── 최근 이벤트 ────────────────────────────────────────────────────────────────

def get_recent_events(stock_code: str) -> list[dict]:
    try:
        since = (date.today() - timedelta(days=14)).isoformat()
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT headline, event_type, impact, thesis_relevance, summary
                FROM events
                WHERE stock_code = :code AND date >= :since
                ORDER BY
                    CASE thesis_relevance WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                    date DESC
                LIMIT 5
            """), {"code": stock_code, "since": since}).fetchall()
        return [{"headline": r[0], "type": r[1], "impact": r[2],
                 "relevance": r[3], "summary": r[4]} for r in rows]
    except Exception:
        return []


# ── thesis 생성 ────────────────────────────────────────────────────────────────

def generate_thesis(stock_name: str, stock_code: str) -> str:
    price   = get_price_context(stock_code)
    div_ctx = get_dividend_context(stock_code)
    macro   = get_macro_context()
    trap    = yield_trap_analyze(div_ctx)
    events  = get_recent_events(stock_code)

    # ── 편의 변수 ──
    dy       = div_ctx.get("dividend_yield",      0)
    payout   = div_ctx.get("payout_ratio",        0)
    coverage = div_ctx.get("dividend_coverage")
    fcf      = div_ctx.get("free_cash_flow")
    eg       = div_ctx.get("earnings_growth")
    net_inc  = div_ctx.get("net_income",          0)
    op_inc   = div_ctx.get("op_income",           0)
    revenue  = div_ctx.get("revenue",             0)
    op_margin = (op_inc / revenue * 100) if revenue else 0
    dps      = div_ctx.get("dividend_per_share")
    per      = div_ctx.get("per")
    mktcap   = div_ctx.get("market_cap_억")

    def fmt(v, unit="", decimals=1):
        if v is None: return "데이터 없음"
        return f"{v:.{decimals}f}{unit}"

    def fmt_krw(v):
        if v is None: return "데이터 없음"
        if abs(v) >= 1e12: return f"{v/1e12:.2f}조원"
        if abs(v) >= 1e8:  return f"{v/1e8:.1f}억원"
        return f"{v:,.0f}원"

    # ── Yield Trap 판정 텍스트 ──
    trap_level = trap["level"]
    trap_signals_text = "\n".join(
        f"  {'⛔' if s['severity']=='DANGER' else '⚠️ '} {s['description']}"
        for s in trap["signals"]
    ) if trap["signals"] else "  (감지된 위험 신호 없음)"

    # ── 주가 안정성 해석 ──
    trend_label = (
        f"MA20 대비 {price['trend_pct']:+.1f}% "
        f"({'강세' if price['trend_pct'] > 2 else '약세' if price['trend_pct'] < -2 else '중립'})"
    )

    price_stability = "주가 하락 중 — 배당수익률이 주가 하락을 반영한 착시일 수 있음" \
        if price['trend_pct'] < -5 else \
        "주가 안정 또는 상승 — 배당수익률 신뢰도 높음" \
        if price['trend_pct'] > 0 else \
        "주가 횡보 — 배당수익률 왜곡 가능성 낮음"

    # ── 국채 대비 배당수익률 스프레드 ──
    bond_10y = macro.get("us_10y_yield", 0)
    spread   = dy - bond_10y if dy and bond_10y else None
    spread_text = f"{spread:+.2f}%p (국채 10년 {bond_10y:.2f}% 대비)" if spread else "계산 불가"

    # ── 이벤트 텍스트 ──
    if events:
        ev_lines = []
        for e in events:
            marker = "⚡" if e["relevance"] == "high" else "·"
            ev_lines.append(f"  {marker} [{e['impact']}] {e['headline']}")
            if e["relevance"] == "high":
                ev_lines.append(f"       → {e['summary']}")
        events_text = "\n".join(ev_lines)
    else:
        events_text = "  (수집된 이벤트 없음)"

    prompt = f"""당신은 배당주 전문 바이사이드 애널리스트입니다.
아래 실제 데이터만을 사용하여 {stock_name}의 배당 투자 thesis를 작성하세요.

══════════════════════════════════════════
 핵심 질문: 이 기업은 왜 배당을 계속 줄 수 있는가?
           그리고 지금 이 배당이 지속 가능한가?
══════════════════════════════════════════

■ 배당 지표
  배당수익률:  {fmt(dy, '%', 2)}
  배당성향:    {fmt(payout, '%', 1)}
  배당커버리지: {fmt(coverage, '배', 2)}
  주당배당금:  {fmt_krw(dps) if dps else '데이터 없음'}
  배당 vs 국채: {spread_text}

■ 현금흐름 (배당 지급 능력)
  잉여현금흐름(FCF): {fmt_krw(fcf)}
  배당지급액:        {fmt_krw(div_ctx.get('dividends_paid'))}
  영업현금흐름:      {fmt_krw(div_ctx.get('operating_cf'))}
  CAPEX:            {fmt_krw(div_ctx.get('capex'))}

■ 실적 (배당 여력)
  매출액:      {fmt_krw(revenue)}
  영업이익:    {fmt_krw(op_inc)} (마진 {fmt(op_margin, '%', 1)})
  당기순이익:  {fmt_krw(net_inc)}
  순이익 성장률: {fmt(eg, '%', 1)}
  PER:         {fmt(per, '배', 1)}

■ 주가 안정성 (총수익률 관점)
  현재가:      {price['current']:,.0f}원
  52주 범위:   {price['low_52w']:,.0f}원 ~ {price['high_52w']:,.0f}원 (현재 상위 {100-price['pct_range']:.0f}%)
  20일 수익률: {fmt(price['chg_20'], '%', 1)}
  60일 수익률: {fmt(price['chg_60'], '%', 1)}
  추세:        {trend_label}
  주가 안정성: {price_stability}

■ Yield Trap 룰 엔진 판정 [{trap_level}]
{trap_signals_text}

■ 최근 이벤트
{events_text}

══════════════════════════════════════════
 [철칙 - 위반 시 분석 전체 무효]
══════════════════════════════════════════
1. 위 데이터에 없는 수치 절대 생성 금지
2. "안정적", "성장 가능성", "장기적으로 유망" 같은 공허한 표현 금지
3. 모든 주장은 위 수치를 직접 인용해야 유효
4. 배당수익률만 높다고 좋다고 쓰면 분석 실격
5. Yield Trap 판정이 DANGER/WARNING이면 반드시 thesis에 반영

---

### 0. 배당 지속성 가설 (2문장 이내)
"이 기업이 배당을 계속 줄 수 있는 구조인가?"에 대한 답.
반드시 포함: FCF 커버리지, 배당성향, 이익 추세 중 2개 이상 수치 인용.
Yield Trap 신호가 있으면 가설에 명시.

### 1. 가설 검증
- **지속 가능 근거 2개** (있다면): FCF, 배당성향, 이익 성장 중 수치 인용 + 인과 설명
- **지속 불가능 근거 1개** (Yield Trap 신호 또는 구조적 문제): 수치 인용 필수
- **총수익률 관점**: 배당수익률 + 주가 추세를 합산하면 실질 수익이 플러스인가?

### 2. 배당 붕괴 조건 (2가지)
형식: "[지표]가 [수치]를 [초과/하회]하면, [어느 전제]가 무효화되어 [결과]가 발생한다."
→ FCF, 배당성향, 순이익, 주가 중 실제 데이터 기반 수치 사용

### 3. 투자 판단
- 배당수익률 {fmt(spread, '%p', 2) if spread else 'N/A'} 국채 스프레드가 투자 매력을 정당화하는가?
- 지금 이 배당주에 투자해야 하는 경우 / 피해야 하는 경우 각 1가지 (수치 근거 포함)
"""

    response = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2500,
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    result = generate_thesis("삼성전자", "005930")
    print(result)

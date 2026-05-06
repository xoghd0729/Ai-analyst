import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import create_engine, text
from analyzers.yield_trap import analyze as yield_trap_analyze, get_metrics_from_db

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"
engine = create_engine("postgresql://localhost/ai_analyst")


def get_alerts(stock_code: str):
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT a.detail, c.description, c.type, t.content
            FROM alerts a
            JOIN conditions c ON a.condition_id = c.id
            JOIN thesis t ON c.thesis_id = t.id
            WHERE t.stock_code = :code
            ORDER BY a.triggered_at DESC
            LIMIT 5
        """), {"code": stock_code}).fetchall()


def parse_recommendation(content: str) -> str:
    if "thesis 붕괴" in content or "붕괴" in content:
        return "thesis 붕괴"
    if "thesis 약화" in content or "약화" in content:
        return "thesis 약화"
    return "thesis 유지"


def save_action(stock_code: str, rec: str, content: str):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO actions (stock_code, recommendation, content)
            VALUES (:code, :rec, :content)
        """), {"code": stock_code, "rec": rec, "content": content})
        conn.commit()


def generate_action(stock_code: str, stock_name: str):
    alerts  = get_alerts(stock_code)
    metrics = get_metrics_from_db(stock_code)
    trap    = yield_trap_analyze(metrics)

    # 이탈 감지 없어도 Yield Trap DANGER이면 판정
    if not alerts and trap["level"] not in ("DANGER", "WARNING"):
        msg = (
            f"이탈 감지 조건 없음. Yield Trap 판정: {trap['level']}.\n"
            f"배당 지속성 구조 현재 유지 — thesis 유지."
        )
        save_action(stock_code, "thesis 유지", msg)
        print("이탈 감지 없음 + Yield Trap SAFE — thesis 유지")
        return

    triggered = [a[1] for a in alerts]
    thesis    = alerts[0][3] if alerts else "(이탈 없음)"

    trap_signals_text = "\n".join(
        f"  {'⛔' if s['severity']=='DANGER' else '⚠️ '} {s['description']}"
        for s in trap["signals"]
    ) if trap["signals"] else "  없음"

    prompt = f"""당신은 배당주 전문 바이사이드 애널리스트입니다.
아래 배당 thesis와 이탈 감지 결과를 보고, 배당 지속성 가설이 여전히 유효한지 판정하세요.

══════════════════════════════════════════
 [원래 배당 thesis]
══════════════════════════════════════════
{thesis}

══════════════════════════════════════════
 [이탈 감지된 조건]
══════════════════════════════════════════
{chr(10).join(f'  ❗ {c}' for c in triggered) if triggered else '  없음'}

══════════════════════════════════════════
 [Yield Trap 룰 엔진 판정: {trap['level']}]
══════════════════════════════════════════
{trap['summary']}
{trap_signals_text}

══════════════════════════════════════════
 [판정 기준]
══════════════════════════════════════════
thesis 유지:  이탈 조건과 Yield Trap 신호가 배당 지속성 가설의 핵심 전제와 무관
thesis 약화:  FCF 여유 감소 또는 배당성향 상승 등 배당 여력이 줄고 있으나 아직 지급 가능
thesis 붕괴:  FCF가 배당 지급액 미달, 또는 배당성향 100% 초과, 또는 순이익 적자
              → 배당 삭감/중단 가능성이 구조적으로 확인됨

철칙:
- 데이터에 없는 수치 생성 금지
- "장기적으로", "가능성이 있음" 같은 모호한 표현 금지
- Yield Trap DANGER 신호 있으면 반드시 thesis 붕괴 또는 약화로 판정
- 판단은 세 단계 중 정확히 하나

---

### 1. 판단
thesis 유지 / thesis 약화 / thesis 붕괴 중 하나만

### 2. 근거
이탈 조건 또는 Yield Trap 신호가 배당 지속성 가설의 어느 전제를 건드리는가?
FCF 커버리지, 배당성향, 순이익 추세 중 수치를 직접 인용하여 설명.

### 3. 총수익률 관점
배당 수익만이 아닌, 주가 추세를 고려한 실질 총수익이 플러스인가?
지금 이 배당주를 보유해야 하는 이유 또는 피해야 하는 이유 1가지.

### 4. 재판정 트리거
① [지표]가 [수치] [초과/하회]할 때
② [지표]가 [수치] [초과/하회]할 때
"""

    result = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1800,
    )
    content = result.choices[0].message.content
    rec     = parse_recommendation(content)
    save_action(stock_code, rec, content)

    print(f"\n=== {stock_name} 배당 thesis 판정 [{rec}] ===")
    print(content)

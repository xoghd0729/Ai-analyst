import ssl
ssl._create_default_https_context = ssl._create_unverified_context

import os, json, re
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import create_engine, text

load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL  = "llama-3.3-70b-versatile"
engine = create_engine("postgresql://localhost/ai_analyst")

# 배당 분석에 실제로 수집되는 지표만
METRIC_REGISTRY = [
    "dividend_yield",     # 배당수익률 (%)
    "payout_ratio",       # 배당성향 (%) — 80% 초과 시 위험
    "dividend_coverage",  # 배당커버리지 (배) — FCF/배당지급액, 1.5배 미만 경고
    "free_cash_flow",     # 잉여현금흐름 (원) — 음수 시 위험
    "earnings_growth",    # 순이익 성장률 (%)
    "net_income",         # 당기순이익 (원)
    "op_income",          # 영업이익 (원)
    "close_price",        # 현재 종가 (원) — 주가 안정성
    "rsi_14",             # RSI (0~100) — 주가 모멘텀
]

METRIC_INFO = {
    "dividend_yield":    "배당수익률(%). 주가 하락 시 수치가 높아 보이는 착시 주의.",
    "payout_ratio":      "배당성향(%). 80% 이상=고위험, 100% 이상=지속 불가.",
    "dividend_coverage": "FCF/배당지급액(배). 1.5배 이상=안전, 1.0 미만=위험.",
    "free_cash_flow":    "잉여현금흐름(원). 음수=배당 지급 위해 외부 자금 필요.",
    "earnings_growth":   "순이익 성장률(%). 음수=배당 여력 감소.",
    "net_income":        "당기순이익(원). 음수=배당 지속 불가.",
    "op_income":         "영업이익(원). 감소 추세=실적 악화 신호.",
    "close_price":       "현재 종가(원). 하락 추세=배당수익률 착시 가능성.",
    "rsi_14":            "RSI(0~100). 30 이하=극과매도(배당 착시 구간).",
}

DEFAULT_CONDITIONS = [
    {
        "type": "composite",
        "description": "배당성향 90% 초과 + 순이익 감소: 배당 여력 고갈로 배당 삭감 임박",
        "logic": {
            "operator": "AND",
            "rules": [
                {"metric": "payout_ratio",   "operator": ">=", "value": 90},
                {"metric": "earnings_growth","operator": "<",  "value": 0},
            ]
        }
    }
]


def clean_json(raw: str):
    raw = re.sub(r'```json|```', '', raw)
    s, e = raw.find('['), raw.rfind(']')
    return raw[s:e+1] if s != -1 and e != -1 else None


def generate_conditions(thesis_id: int, thesis_text: str):
    metric_desc = "\n".join(f"  {k}: {v}" for k, v in METRIC_INFO.items())

    prompt = f"""당신은 배당주 전문 퀀트 애널리스트입니다.
아래 투자 thesis를 읽고, 배당 지속성 가설이 무너지는 이탈 조건 3개를 JSON으로 생성하세요.

[투자 thesis]
{thesis_text}

[사용 가능한 지표]
{metric_desc}

[조건 설계 원칙]
각 조건은 배당 붕괴의 서로 다른 경로를 커버해야 함:

  조건 1 — 현금흐름 위험: FCF 또는 배당커버리지 기반 복합 조건
    예: free_cash_flow < [현재 배당지급액] AND payout_ratio > 85

  조건 2 — 실적 악화: 이익 감소 기반
    예: earnings_growth < -20 AND payout_ratio > 75

  조건 3 — 주가 붕괴 (Yield Trap 확인): 주가 하락 + 배당수익률 급등 패턴
    예: rsi_14 < 35 AND dividend_yield > 8
    (주가가 폭락하면 배당수익률이 착시로 올라가는 패턴 감지)

[출력 형식 - JSON 배열만]
[
  {{
    "type": "composite",
    "description": "이 조건이 배당 지속성 가설의 어느 전제를 무효화하는지 (수치 포함, 1문장)",
    "logic": {{
      "operator": "AND",
      "rules": [
        {{"metric": "지표명", "operator": ">|<|>=|<=", "value": 숫자}}
      ]
    }}
  }}
]

규칙:
- value는 숫자만 (문자열/수식 금지)
- metric은 위 목록에 있는 것만
- 3개 모두 AND 복합 조건 (rules 2개 이상)
- JSON만 출력
"""

    for attempt in range(3):
        try:
            res = client.chat.completions.create(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1000,
            )
            raw     = res.choices[0].message.content
            cleaned = clean_json(raw)
            if not cleaned:
                continue
            conditions = json.loads(cleaned)

            valid = []
            for cond in conditions:
                rules = cond.get("logic", {}).get("rules", [])
                if all(
                    isinstance(r.get("value"), (int, float)) or
                    (isinstance(r.get("value"), str) and r["value"].lstrip('-').replace('.','').isdigit())
                    for r in rules
                ) and len(rules) >= 2:
                    valid.append(cond)

            if not valid:
                continue

            with engine.connect() as conn:
                for cond in valid:
                    conn.execute(text("""
                        INSERT INTO conditions (thesis_id, type, description, logic, is_active)
                        VALUES (:tid, :type, :desc, :logic, TRUE)
                    """), {
                        "tid":   thesis_id,
                        "type":  cond["type"],
                        "desc":  cond["description"],
                        "logic": json.dumps(cond["logic"], ensure_ascii=False),
                    })
                conn.commit()
            print(f"✅ 배당 이탈 조건 {len(valid)}개 생성 완료")
            return

        except Exception as e:
            print(f"  조건 생성 시도 {attempt+1} 실패: {e}")

    # fallback
    with engine.connect() as conn:
        for cond in DEFAULT_CONDITIONS:
            conn.execute(text("""
                INSERT INTO conditions (thesis_id, type, description, logic, is_active)
                VALUES (:tid, :type, :desc, :logic, TRUE)
            """), {
                "tid": thesis_id, "type": cond["type"],
                "desc": cond["description"],
                "logic": json.dumps(cond["logic"], ensure_ascii=False),
            })
        conn.commit()
    print("⚠️  기본 배당 조건으로 대체")

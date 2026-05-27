"""
Thesis Scoring 모듈.

Thesis 텍스트 + Yield Trap 판정 + 재무 지표를 종합해
배당 안정성을 0~100점으로 정량화한다.

점수 구성:
  stability_score  : 배당 안정성 (FCF, 커버리지, 배당성향 기반)
  risk_score       : 위험도 (Yield Trap 신호, 이탈 조건 기반)
  momentum_score   : 주가·실적 모멘텀 (RSI, 순이익 성장률 기반)
  overall_score    : 종합 점수 (가중 평균)

AI 역할:
  룰엔진이 수치로 1차 점수를 계산하고,
  LLaMA가 Thesis 맥락을 반영해 최종 점수를 보정한다.
"""

import os, json, re
from dotenv import load_dotenv
from utils.ollama_client import ollama_call_with_retry as groq_call_with_retry
from sqlalchemy import create_engine, text

load_dotenv()
client = None   # Gemini는 클라이언트 객체 불필요 (호환용으로 None 유지)
MODEL  = "qwen2.5:14b"
engine = create_engine("postgresql://localhost/ai_analyst")


# ─────────────────────────────────────────────────────────────
# 1. 룰 기반 1차 점수 계산 (AI 없음)
# ─────────────────────────────────────────────────────────────

def rule_based_score(metrics: dict, trap: dict) -> dict:
    """
    재무 지표와 Yield Trap 판정으로 1차 점수 계산.
    각 항목 0~100, 높을수록 좋음.
    """

    # ── stability_score: 배당 안정성 ──
    stability = 50  # 기본값

    coverage = metrics.get("dividend_coverage")
    if coverage is not None:
        if coverage >= 2.0:   stability += 25
        elif coverage >= 1.5: stability += 15
        elif coverage >= 1.0: stability += 5
        elif coverage < 0:    stability -= 30
        else:                 stability -= 15

    payout = metrics.get("payout_ratio", 0)
    if payout > 0:
        if payout <= 50:   stability += 15
        elif payout <= 70: stability += 8
        elif payout <= 90: stability -= 5
        else:              stability -= 20

    fcf = metrics.get("free_cash_flow")
    if fcf is not None:
        if fcf > 0:   stability += 10
        else:         stability -= 20

    stability = max(10, min(100, stability))  # 최저 10점

    # ── risk_score: 위험도 (낮을수록 위험) ──
    risk = 50

    trap_level = trap.get("level", "SAFE")
    if trap_level == "DANGER":  risk -= 35
    elif trap_level == "WARNING": risk -= 15
    elif trap_level == "CAUTION": risk -= 5
    else:                        risk += 10

    signals = trap.get("signals", [])
    danger_count = sum(1 for s in signals if s.get("severity") == "DANGER")
    warn_count   = sum(1 for s in signals if s.get("severity") == "WARNING")
    risk -= danger_count * 10
    risk -= warn_count   * 5

    risk = max(10, min(100, risk))  # 최저 10점 (0점은 상장폐지 수준)

    # ── momentum_score: 모멘텀 ──
    momentum = 50

    eg = metrics.get("earnings_growth")
    if eg is not None:
        if eg > 10:    momentum += 20
        elif eg > 0:   momentum += 10
        elif eg > -10: momentum -= 5
        else:          momentum -= 20

    rsi = metrics.get("rsi_14")
    if rsi is not None:
        if 40 <= rsi <= 65:  momentum += 10   # 건강한 범위
        elif rsi < 30:       momentum -= 15   # 극과매도
        elif rsi > 75:       momentum -= 10   # 과매수

    momentum = max(0, min(100, momentum))

    # ── overall_score: 가중 평균 ──
    overall = int(
        stability * 0.5 +
        risk      * 0.35 +
        momentum  * 0.15
    )

    return {
        "stability_score": stability,
        "risk_score":      risk,
        "momentum_score":  momentum,
        "overall_score":   overall,
    }


# ─────────────────────────────────────────────────────────────
# 2. LLM 보정 (Thesis 맥락 반영)
# ─────────────────────────────────────────────────────────────

def llm_adjust_score(thesis: str, rule_scores: dict) -> dict:
    """
    LLaMA가 Thesis 내용을 읽고 룰 기반 점수를 ±15 범위 내에서 보정.
    수치로 설명되지 않는 정성적 맥락 반영.
    """
    prompt = f"""당신은 배당주 전문 퀀트 애널리스트입니다.
아래 배당 Thesis와 룰 기반 점수를 검토하고, 점수를 보정하세요.

[배당 Thesis]
{thesis[:1500]}

[룰 기반 1차 점수]
stability_score (배당 안정성): {rule_scores['stability_score']}
risk_score (안전도):           {rule_scores['risk_score']}
momentum_score (모멘텀):       {rule_scores['momentum_score']}
overall_score (종합):          {rule_scores['overall_score']}

[보정 규칙]
- 각 점수를 -15 ~ +15 범위 내에서만 조정 가능
- Thesis에서 수치로 뒷받침되는 긍정/부정 요소만 반영
- 데이터 없는 주관적 판단 금지
- overall_score = stability*0.5 + risk*0.35 + momentum*0.15 로 재계산

[출력 형식 - JSON만]
{{
  "stability_score": 숫자,
  "risk_score": 숫자,
  "momentum_score": 숫자,
  "overall_score": 숫자,
  "score_reason": "보정 이유 1문장"
}}
"""
    try:
        res = groq_call_with_retry(
            client,
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,   # 300 → 200 (토큰 절감)
        )
        raw = res.choices[0].message.content
        raw = re.sub(r'```json|```', '', raw)
        s, e = raw.find('{'), raw.rfind('}')
        if s != -1 and e != -1:
            adjusted = json.loads(raw[s:e+1])
            # LLM이 rule_scores에서 ±15 이상 벗어나지 못하도록 강제
            for k in ("stability_score", "risk_score", "momentum_score"):
                if k in adjusted:
                    rule_val = rule_scores.get(k, 50)
                    clamped  = max(rule_val - 15, min(rule_val + 15, int(adjusted[k])))
                    adjusted[k] = max(10, min(100, clamped))
            # overall 재계산 (LLM 값 무시, 가중 평균으로 강제)
            adjusted["overall_score"] = int(
                adjusted.get("stability_score", 50) * 0.5 +
                adjusted.get("risk_score",      50) * 0.35 +
                adjusted.get("momentum_score",  50) * 0.15
            )
            return adjusted
    except Exception as e:
        print(f"  LLM 보정 실패: {e}")

    return rule_scores  # 실패 시 룰 점수 그대로


# ─────────────────────────────────────────────────────────────
# 3. DB 저장
# ─────────────────────────────────────────────────────────────

def save_score(stock_code: str, scores: dict):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO scores
                (stock_code, stability_score, risk_score,
                 momentum_score, overall_score, score_reason)
            VALUES
                (:code, :stab, :risk, :mom, :overall, :reason)
        """), {
            "code":    stock_code,
            "stab":    scores.get("stability_score", 0),
            "risk":    scores.get("risk_score",      0),
            "mom":     scores.get("momentum_score",  0),
            "overall": scores.get("overall_score",   0),
            "reason":  scores.get("score_reason",    ""),
        })
        conn.commit()


# ─────────────────────────────────────────────────────────────
# 4. 메인 진입점
# ─────────────────────────────────────────────────────────────

def score_thesis(stock_code: str, stock_name: str,
                 thesis: str, metrics: dict, trap: dict) -> dict:
    """
    룰 기반 1차 점수 → LLM 보정 → DB 저장 → 결과 반환.
    """
    # 1차: 룰 엔진
    rule_scores = rule_based_score(metrics, trap)

    # 2차: LLM 보정
    final_scores = llm_adjust_score(thesis, rule_scores)

    # 저장
    save_score(stock_code, final_scores)

    # 출력
    overall = final_scores.get("overall_score", 0)
    grade = (
        "🟢 우량" if overall >= 70 else
        "🟡 보통" if overall >= 50 else
        "🔴 위험"
    )
    print(f"\n  [{grade}] {stock_name} 종합 점수: {overall}점")
    print(f"    안정성 {final_scores.get('stability_score')}  "
          f"안전도 {final_scores.get('risk_score')}  "
          f"모멘텀 {final_scores.get('momentum_score')}")
    if final_scores.get("score_reason"):
        print(f"    → {final_scores['score_reason']}")

    return final_scores

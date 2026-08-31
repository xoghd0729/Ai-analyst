"""
utils/advisor_service.py — AI Portfolio Advisor (LLM 해석 계층)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 역할 분리 원칙
  계산: Ranker / FIRE Engine / Backtest / MPT / Reverse FIRE  (Python 확정값)
  해석: 이 모듈 (LLM이 이미 계산된 결과를 설명·해석)

  LLM이 할 수 없는 것:
    ✗ 새 종목 추천
    ✗ 입력 데이터에 없는 수치(수익률·FIRE 나이·배당금) 생성
    ✗ 계산 결과 수정 또는 재계산
    ✗ 입력된 FIRE 나이를 다른 값으로 바꾸기

  LLM이 하는 것:
    ✓ 계산된 숫자를 쉬운 언어로 설명
    ✓ 포트폴리오의 강점·약점 요약
    ✓ 실행 가능한 행동 우선순위 제시
    ✓ 불확실한 해석은 "제공된 데이터 기준"으로 명시

■ JSON schema (강제)
  {
    "summary":      str,          # 2~3문장 핵심 요약
    "strengths":    list[str],    # 강점 2~4개
    "risks":        list[str],    # 위험 요소 2~4개
    "action_items": list[str],    # 즉시/단기 행동 2~3개
    "caveats":      list[str]     # 주의사항 1~2개
  }

■ 실패 처리
  LLM 응답이 JSON schema에 맞지 않으면 1회 재시도.
  재시도도 실패하면 rule-based fallback 반환.
  source 필드로 "llm" / "fallback" 구분.

■ LLM
  기본: Ollama qwen3:14b (로컬, 무료, 프라이빗)
  환경변수 LLM_PROVIDER / LLM_MODEL로 교체 가능 (추후 확장)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

# ── 응답 JSON 스키마 ─────────────────────────────────────────────
_REQUIRED_KEYS = {"summary", "strengths", "risks", "action_items", "caveats"}
_LIST_KEYS     = {"strengths", "risks", "action_items", "caveats"}

# ── 시스템 프롬프트 (LLM 역할 제약 포함) ──────────────────────────
_SYSTEM_PROMPT = """당신은 포트폴리오 분석 AI Advisor입니다.

[역할]
- 이미 계산된 포트폴리오 분석 결과를 한국어로 명확하고 친절하게 해석·설명합니다.
- 투자자가 결과를 이해하고 다음 행동을 결정하는 데 도움을 줍니다.

[엄격한 제약 — 반드시 준수]
1. portfolio_data에 없는 수치(수익률, FIRE 나이, 배당금액, 샤프비율 등)를 임의로 생성하지 마십시오.
2. portfolio_data에 없는 종목을 추천하거나 언급하지 마십시오.
3. fire_plan에 제시된 FIRE 달성 나이를 다른 값으로 변경하지 마십시오.
4. 계산 결과를 직접 재계산하거나 수정하지 마십시오.
5. 확신할 수 없는 해석은 "제공된 데이터 기준" 또는 "추정"이라고 명시하십시오.
6. 반드시 아래 JSON 형식만 반환하십시오. 설명 텍스트, 마크다운 코드 블록, 주석을 절대 포함하지 마십시오.

[출력 형식 — 반드시 이 JSON만 반환]
{
  "summary": "포트폴리오 전체에 대한 2~3문장 핵심 요약",
  "strengths": ["강점 1", "강점 2", "강점 3"],
  "risks": ["주요 위험 1", "주요 위험 2"],
  "action_items": ["즉시 행동 1", "단기 행동 2"],
  "caveats": ["주의사항 1"]
}"""


# ── 포트폴리오 입력 요약 빌더 ────────────────────────────────────

def _build_portfolio_summary(result: dict) -> str:
    """
    pipeline result에서 LLM에 전달할 핵심 수치만 추출.
    LLM이 해석할 수 없는 raw list는 제거하고,
    사람이 읽을 수 있는 요약 텍스트로 변환.
    """
    inp  = result.get("input", {})
    summ = result.get("summary", {})
    fire = result.get("fire_plan", {})
    rv   = result.get("reverse_fire", {})
    mc   = result.get("monte_carlo", {})
    tax  = result.get("tax_optimizer", {})
    beh  = result.get("behavioral_finance", {})
    bt   = result.get("backtest", {})
    macro = result.get("macro_regime", {})
    health = result.get("portfolio_health", {})
    recs = result.get("recommendations", [])

    # 추천 종목 목록 (ticker + 비중 + asset_class)
    ticker_lines = []
    for r in recs[:10]:  # 최대 10개
        t   = r.get("ticker", "")
        w   = r.get("weight_pct", 0)
        cls = r.get("asset_class", "")
        dy  = r.get("dividend_yield", 0)
        ticker_lines.append(f"  - {t} ({cls}) {w:.1f}% 배당수익률 {dy:.1f}%")

    tickers_str = "\n".join(ticker_lines) if ticker_lines else "  (없음)"

    # FIRE 정보 (fire_timeline은 리스트 — targets에서 읽음)
    targets   = fire.get("targets", {})
    lean_age  = targets.get("lean",    {}).get("projected_fire_age", "미계산")
    reg_age   = targets.get("regular", {}).get("projected_fire_age", "미계산")

    # 역산 FIRE
    rv_already = rv.get("already_achievable", False)
    rv_gap     = rv.get("gap_years", 0)
    rv_path1   = rv.get("savings_increase", 0)
    rv_path2   = rv.get("capital_increase", 0)
    rv_achieve = rv.get("achievable_monthly", 0)

    # Monte Carlo (p50_monthly / p10_monthly 이 리스트일 경우 마지막 값 사용)
    def _scalar(v, default=0):
        if isinstance(v, (list, tuple)):
            return v[-1] if v else default
        return v if v is not None else default

    mc_p50  = _scalar(mc.get("p50_monthly", 0))
    mc_p10  = _scalar(mc.get("p10_monthly", 0))
    mc_conf = _scalar(mc.get("confidence_at_target", 0))

    # 세금
    eff_tax     = tax.get("effective_tax_rate_pct", 0)
    opt_tax     = tax.get("optimized_tax_rate_pct", 0)
    tax_saving  = tax.get("total_annual_saving_만원", 0)

    # 행동 편향 (detected_biases = list of dicts with 'name' key)
    raw_biases = beh.get("detected_biases", beh.get("biases_detected", []))
    if not isinstance(raw_biases, list):
        raw_biases = []
    biases = [b["name"] if isinstance(b, dict) else b for b in raw_biases]
    bias_str = ", ".join(biases[:3]) if biases else "없음"

    # 백테스트
    bt_cagr   = bt.get("cagr_pct", None)
    bt_mdd    = bt.get("mdd_pct", None)
    bt_sharpe = bt.get("sharpe_ratio", None)

    # 포트폴리오 건강 (실제 키: score, not overall_score)
    h_score = health.get("score", health.get("overall_score", None))

    lines = [
        "=== 포트폴리오 분석 결과 (계산 완료된 수치) ===",
        "",
        f"[사용자 조건]",
        f"  나이: {inp.get('age', '?')}세",
        f"  투자 금액: {inp.get('investable', 0):,}만원",
        f"  목표 월배당: {inp.get('monthly_target', 0):,}만원",
        f"  리스크 성향: {inp.get('risk_tolerance', '?')}",
        "",
        f"[포트폴리오 추천 결과]",
        tickers_str,
        "",
        f"[현금흐름 요약]",
        f"  예상 월 세후 배당: {summ.get('est_monthly_div_after_tax_만원', 0):.1f}만원",
        f"  목표 달성률: {summ.get('target_achievement_pct', 0):.1f}%",
        f"  vs 은행 금리: +{summ.get('vs_bank_rate_pct', 0):.1f}%p",
        "",
        f"[FIRE 분석]",
        f"  린 FIRE 예상 나이: {lean_age}세",
        f"  일반 FIRE 예상 나이: {reg_age}세",
        f"  목표 달성 여부: {'가능' if rv_already else '부족'}",
        f"  부족 기간: {rv_gap}년" if not rv_already else "",
        f"  필요 추가 월 적립금: {rv_path1:.0f}만원" if (rv_path1 or 0) > 0 else "",
        f"  필요 추가 초기자산: {rv_path2:.0f}만원" if (rv_path2 or 0) > 0 else "",
        f"  현재 조건 최대 달성: {rv_achieve:.1f}만원/월" if rv_achieve is not None else "",
        "",
        f"[Monte Carlo 시뮬레이션]",
        f"  P50(중간값) 월배당: {mc_p50:.1f}만원",
        f"  P10(하위 10%) 월배당: {mc_p10:.1f}만원",
        f"  목표 달성 신뢰도: {mc_conf:.1f}%",
        "",
        f"[백테스트 결과 (2015-2024)]",
        f"  CAGR: {bt_cagr:.1f}%" if bt_cagr is not None else "  CAGR: 미계산",
        f"  MDD: {bt_mdd:.1f}%" if bt_mdd is not None else "  MDD: 미계산",
        f"  Sharpe: {bt_sharpe:.2f}" if bt_sharpe is not None else "  Sharpe: 미계산",
        "",
        f"[세금 최적화]",
        f"  현재 실효세율: {eff_tax:.1f}%",
        f"  최적화 후 세율: {opt_tax:.1f}%",
        f"  절세 가능 금액: {tax_saving:.0f}만원/년",
        "",
        f"[행동 편향 진단]",
        f"  탐지된 편향: {bias_str}",
        "",
        f"[포트폴리오 건강도]",
        f"  종합 점수: {h_score}/100" if h_score is not None else "  종합 점수: 미계산",
        "",
        f"[거시 환경]",
        f"  레짐: {macro.get('label', '미확인')}",
        f"  어드바이저리: {macro.get('advisory', '없음')}",
    ]

    return "\n".join(line for line in lines if line is not None)


# ── JSON 파싱/검증 ───────────────────────────────────────────────

def _extract_json(text: str) -> Optional[dict]:
    """
    LLM 응답에서 JSON 추출.
    코드 블록, 앞뒤 텍스트, 줄바꿈 노이즈 처리.
    """
    # 코드 블록 제거
    text = re.sub(r"```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "").strip()

    # 첫 번째 { ... } 블록 추출
    start = text.find("{")
    end   = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    json_str = text[start:end + 1]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # 후방 호환: single-quote → double-quote 시도
        try:
            return json.loads(json_str.replace("'", '"'))
        except Exception:
            return None


def _validate_schema(data: dict) -> bool:
    """필수 키 존재 + 리스트 키가 실제로 list인지 확인."""
    if not isinstance(data, dict):
        return False
    if not _REQUIRED_KEYS.issubset(data.keys()):
        return False
    for key in _LIST_KEYS:
        if not isinstance(data.get(key), list):
            return False
    if not isinstance(data.get("summary"), str):
        return False
    return True


# ── Rule-based fallback ──────────────────────────────────────────

def _fallback_analysis(result: dict) -> dict:
    """
    LLM 불가 시 계산 결과에서 직접 요약 생성.
    절대로 LLM을 호출하지 않으며 결정적으로 동작.
    """
    summ  = result.get("summary", {})
    inp   = result.get("input", {})
    fire  = result.get("fire_plan", {})
    rv    = result.get("reverse_fire", {})
    beh   = result.get("behavioral_finance", {})
    health = result.get("portfolio_health", {})

    monthly = summ.get("est_monthly_div_after_tax_만원", 0)
    target  = inp.get("monthly_target", 0)
    achieve = summ.get("target_achievement_pct", 0)
    vs_bank = summ.get("vs_bank_rate_pct", 0)

    # 린 FIRE (fire_timeline은 리스트 — targets에서 읽음)
    lean_age = fire.get("targets", {}).get("lean", {}).get("projected_fire_age", 99)

    strengths = []
    risks     = []
    actions   = []
    caveats   = []

    # 강점 도출
    if vs_bank > 0:
        strengths.append(f"은행 금리 대비 +{vs_bank:.1f}%p 초과 수익률 달성")
    if achieve >= 80:
        strengths.append(f"월 목표 배당 {target}만원의 {achieve:.0f}% 달성 중")
    if lean_age < inp.get("age", 99) + 20:
        strengths.append(f"린 FIRE {lean_age}세 달성 가능 — 목표 기간 내 실현 가능")

    # 리스크 도출
    raw_b = beh.get("detected_biases", beh.get("biases_detected", []))
    if not isinstance(raw_b, list):
        raw_b = []
    biases = [b["name"] if isinstance(b, dict) else b for b in raw_b]
    if biases:
        risks.append(f"행동 편향 탐지: {', '.join(biases[:2])} — 의사결정 왜곡 가능성")
    h_score = health.get("score", health.get("overall_score"))
    if h_score and h_score < 60:
        risks.append(f"포트폴리오 건강도 {h_score}점 — 분산 개선 필요")
    if achieve < 50:
        risks.append(f"목표 달성률 {achieve:.0f}% — 추가 투자 또는 목표 조정 필요")

    # 행동 도출
    rv_already = rv.get("already_achievable", False)
    if not rv_already:
        sav = rv.get("savings_increase", 0)
        if sav > 0:
            actions.append(f"월 {sav:.0f}만원 추가 적립 시 목표 FIRE 달성 가능")
    isa = result.get("tax_optimizer", {}).get("isa_strategy", {})
    if isa:
        actions.append("ISA 계좌 활용으로 배당세 절세 검토 권장")
    actions.append("분기 1회 포트폴리오 건강도 체크 및 리밸런싱 여부 확인")

    # 주의사항
    caveats.append("본 분석은 과거 데이터와 통계 모델 기반이며 미래 수익을 보장하지 않습니다")
    caveats.append("세법 변경, 배당 삭감, 금리 변화에 따라 결과가 달라질 수 있습니다")

    summary = (
        f"현재 포트폴리오는 월 {monthly:.1f}만원(세후) 배당을 생성하며, "
        f"목표 {target}만원 대비 {achieve:.0f}% 달성 수준입니다. "
        f"은행 금리 대비 +{vs_bank:.1f}%p 초과 수익을 유지하고 있습니다."
    )

    return {
        "summary":      summary,
        "strengths":    strengths or ["포트폴리오 분석 완료"],
        "risks":        risks     or ["추가 분석이 필요합니다"],
        "action_items": actions   or ["정기적인 리밸런싱을 권장합니다"],
        "caveats":      caveats,
        "source":       "fallback",
    }


# ── LLM 호출 ─────────────────────────────────────────────────────

def _call_llm(portfolio_summary: str, max_retries: int = 2) -> Optional[dict]:
    """
    Ollama qwen3:14b 호출 → JSON 파싱 → 스키마 검증.
    실패 시 None 반환 (caller가 fallback 처리).
    """
    try:
        from utils.ollama_client import ollama_call_with_retry, OLLAMA_MODEL
    except ImportError as e:
        log.warning("ollama_client import 실패: %s", e)
        return None

    messages = [
        {"role": "system",  "content": _SYSTEM_PROMPT},
        {"role": "user",    "content": f"다음 포트폴리오 데이터를 분석해주세요:\n\n{portfolio_summary}"},
    ]

    for attempt in range(1, max_retries + 1):
        try:
            res  = ollama_call_with_retry(
                messages    = messages,
                temperature = 0.2,      # 낮은 temperature → 일관된 JSON
                max_tokens  = 1200,
            )
            raw  = res.choices[0].message.content
            data = _extract_json(raw)

            if data and _validate_schema(data):
                data["source"] = "llm"
                return data

            log.warning("LLM 응답 JSON 검증 실패 (시도 %d/%d): %s...",
                        attempt, max_retries, raw[:200])

            # 재시도 시 더 강하게 JSON만 요청
            if attempt < max_retries:
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "응답이 올바른 JSON 형식이 아닙니다. "
                        "설명 없이 JSON 객체만 반환하십시오. "
                        "summary, strengths, risks, action_items, caveats 키가 모두 있어야 합니다."
                    ),
                })

        except RuntimeError as e:
            # Ollama 서버 미실행
            log.warning("Ollama 서버 미실행: %s", e)
            return None
        except Exception as e:
            log.error("LLM 호출 오류 (시도 %d/%d): %s", attempt, max_retries, e)
            if attempt >= max_retries:
                return None

    return None


# ── 퍼블릭 API ────────────────────────────────────────────────────

def analyze_portfolio(
    result:   dict,
    use_llm:  bool = True,
) -> dict:
    """
    포트폴리오 파이프라인 결과 → AI 해석 생성.

    파라미터:
      result  : POST /api/portfolio/recommend 응답 전체
      use_llm : False이면 항상 fallback 반환 (테스트/오프라인 용)

    반환:
    {
      "summary":      str,
      "strengths":    list[str],
      "risks":        list[str],
      "action_items": list[str],
      "caveats":      list[str],
      "source":       "llm" | "fallback",
      "model":        str,    # 사용된 LLM 모델명 (llm일 때만)
    }
    """
    if not use_llm:
        return _fallback_analysis(result)

    portfolio_summary = _build_portfolio_summary(result)

    llm_result = _call_llm(portfolio_summary)
    if llm_result:
        try:
            from utils.ollama_client import OLLAMA_MODEL
            llm_result["model"] = OLLAMA_MODEL
        except ImportError:
            llm_result["model"] = "unknown"
        return llm_result

    # LLM 실패 → fallback
    log.info("LLM 실패 → rule-based fallback 반환")
    return _fallback_analysis(result)

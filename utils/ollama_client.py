"""
Ollama 로컬 LLM 클라이언트 유틸리티.

■ 왜 Ollama인가
  Groq:   100k 토큰/일 → 50종목 분석 중 소진
  Gemini: 지역/계정별 할당량 문제 발생
  Ollama: 완전 로컬, 무제한, API 키 불필요, M4 24GB에서 14B 모델 완벽 구동

■ 사용 모델
  qwen3:14b  — function-calling 강화, 한국어 우수, GPT-4o급 agent 성능
  (대안: qwen3:30b-a3b — MoE 16GB VRAM, 더 강력)
  (구버전: qwen2.5:14b — legacy, 더 이상 기본값 아님)

■ 사전 준비
  1. brew install ollama
  2. ollama serve          (새 터미널 탭에서 계속 실행)
  3. ollama pull qwen3:14b
"""

import requests
import json
import time


OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:14b"


# ─────────────────────────────────────────────────────────────
# Groq 응답 구조를 흉내 내는 래퍼 클래스
# 기존 코드가 res.choices[0].message.content 로 접근하므로
# 동일한 구조를 만들어 줌
# ─────────────────────────────────────────────────────────────

class _Message:
    def __init__(self, content: str):
        self.content = content

class _Choice:
    def __init__(self, content: str):
        self.message = _Message(content)

class OllamaResponse:
    """Groq ChatCompletion 응답과 동일한 인터페이스."""
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


# ─────────────────────────────────────────────────────────────
# 메인 함수: groq_call_with_retry 와 동일한 시그니처
# ─────────────────────────────────────────────────────────────

def ollama_call_with_retry(
    _client_arg=None,      # Groq/Gemini 코드와 호환용 (사용 안 함)
    max_retries: int = 3,
    model: str = OLLAMA_MODEL,
    messages: list = None,
    temperature: float = 0.2,
    max_tokens: int = 1000,
    **kwargs,
) -> OllamaResponse:
    """
    Ollama 로컬 LLM 호출 래퍼.
    - Groq의 groq_call_with_retry 와 동일한 인터페이스
    - 로컬 실행이므로 속도 제한 없음, 실패 시 재시도만 처리

    사용법:
        res = ollama_call_with_retry(
            client,                  # 무시됨 (호환용)
            model="qwen2.5:14b",
            messages=[{"role": "user", "content": "..."}],
            temperature=0.2,
            max_tokens=1000,
        )
        text = res.choices[0].message.content
    """
    if messages is None:
        messages = []

    # 모든 메시지를 하나의 프롬프트로 합침
    prompt = "\n\n".join(
        m.get("content", "") for m in messages
        if m.get("content")
    )

    payload = {
        "model":  model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,  # Ollama의 max_tokens 파라미터
        },
    }

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                OLLAMA_URL,
                json=payload,
                timeout=180,  # 14B 모델은 응답에 최대 2~3분 소요
            )
            resp.raise_for_status()
            content = resp.json().get("response", "")
            return OllamaResponse(content)

        except requests.exceptions.ConnectionError:
            print(f"\n  ❌ Ollama 서버에 연결할 수 없습니다 (시도 {attempt}/{max_retries})")
            print(f"     → 새 터미널 탭에서 'ollama serve' 실행 후 다시 시도하세요")
            if attempt < max_retries:
                time.sleep(5)
            else:
                raise RuntimeError(
                    "Ollama 서버가 실행되지 않았습니다.\n"
                    "새 터미널 탭에서 'ollama serve' 를 먼저 실행하세요."
                )

        except Exception as e:
            print(f"\n  ⚠️  Ollama 오류 (시도 {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(3)
            else:
                raise

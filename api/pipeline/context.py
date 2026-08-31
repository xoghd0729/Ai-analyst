"""
PipelineContext
───────────────
파이프라인 전 단계에 걸쳐 공유되는 단일 상태 컨테이너.

왜 Context 패턴인가?
  각 Filter 함수가 개별 return 값을 다음 함수에 넘기면
  19단계 체인에서 함수 시그니처가 폭발적으로 복잡해진다.
  Context 객체 하나를 공유하면 각 Filter는 필요한 필드만 읽고,
  자신이 계산한 결과만 context에 쓰면 된다.
  → 단계 추가/삭제가 context 필드 추가로만 끝난다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PortfolioRequest:
    age:               int
    annual_income:     int
    monthly_target:    int
    investable_amount: int
    risk_tolerance:    str   = ""      # 빈 문자열이면 __post_init__에서 자동 결정
    archetype:         str   = ""      # 빈 문자열이면 __post_init__에서 자동 결정
    monthly_savings:   float = 100.0
    savings_growth:    float = 0.0     # 적립 연 증가율(%) — 소득 상승 반영
    target_fire_age:   int   = 50

    def __post_init__(self) -> None:
        """
        risk_tolerance / archetype 미입력 시 나이·자본·적립액으로 자동 결정.

        전략표:
          age < 35  → 성장형(aggressive)   : 복리 성장 우선, 적립 비중 높음
          35-50     → 균형형(moderate)     : 배당+성장 혼합
          50+       → 배당안정형(conservative): 안정 현금흐름 우선

        자본 보정:
          investable < 1000만 → 한 단계 더 성장 방향으로 (자본 작으면 적립이 핵심)
          investable >= 5000만 → 한 단계 안정 방향으로 (목돈 방어 우선)
        """
        if not self.risk_tolerance or not self.archetype:
            # 나이 기준 기본값
            if self.age < 35:
                risk, arch = "aggressive", "성장형"
            elif self.age < 50:
                risk, arch = "moderate", "혼합형"
            else:
                risk, arch = "conservative", "안정형"

            # 자본 보정
            inv = self.investable_amount
            if inv < 1000:                      # 1000만 미만 → 더 공격적
                if risk == "moderate":
                    risk, arch = "aggressive", "성장형"
            elif inv >= 5000 and self.age >= 45: # 5000만+ & 45세+ → 더 안정적
                if risk == "moderate":
                    risk, arch = "conservative", "안정형"

            if not self.risk_tolerance:
                self.risk_tolerance = risk
            if not self.archetype:
                self.archetype = arch


@dataclass
class PipelineContext:
    """
    파이프라인 공유 상태.
    각 Filter는 자신이 필요한 필드를 읽고, 결과를 해당 필드에 저장한다.
    None 이면 아직 해당 단계가 실행되지 않은 상태.
    """
    request: PortfolioRequest

    # ── Step 1: 5축 비중 ────────────────────────────────────────
    base_axis_w:  dict = field(default_factory=dict)
    arch_axis_w:  dict = field(default_factory=dict)
    axis_w:       dict = field(default_factory=dict)
    etf_yields:   dict = field(default_factory=dict)
    arch_cfg:     dict = field(default_factory=dict)

    # ── Step 2: 거시 레짐 ───────────────────────────────────────
    macro: dict = field(default_factory=dict)

    # ── Step 3: 자산 선별 ───────────────────────────────────────
    kr_stocks: list = field(default_factory=list)
    us_stocks: list = field(default_factory=list)
    etfs:      list = field(default_factory=list)

    # ── Step 3-b: 개인화 랭킹 ──────────────────────────────────
    target_yield: float = 0.0   # 목표수익률 역산값 (monthly_target/investable_amount)

    # ── Step 4: 비중 배분 결과 ──────────────────────────────────
    recommendations: list = field(default_factory=list)

    # ── Step 5: 포트폴리오 요약 수치 ───────────────────────────
    total_annual:        float = 0.0
    total_annual_net:    float = 0.0
    total_monthly:       float = 0.0
    total_monthly_net:   float = 0.0
    avg_yield:           float = 0.0
    avg_yield_net:       float = 0.0
    avg_cap_gain:        float = 0.0
    avg_total_return:    float = 0.0
    avg_total_return_net:float = 0.0
    vs_bank:             float = 0.0
    achievement:         float = 0.0
    needed_inv:          int   = 0
    monthly_pay_weight:  float = 0.0

    # ── Step 6: 배당 성장 시뮬레이션 ───────────────────────────
    projection:     dict = field(default_factory=dict)
    living_coverage:dict = field(default_factory=dict)

    # ── Step 7: 리밸런싱 ────────────────────────────────────────
    rebalancing_plan: dict = field(default_factory=dict)

    # ── Step 8: 스트레스 테스트 ────────────────────────────────
    stress:    dict = field(default_factory=dict)
    fx_stress: dict = field(default_factory=dict)

    # ── Step 9: 섹터 익스포저 ──────────────────────────────────
    sector_exposure: dict = field(default_factory=dict)

    # ── Step 10: 배당 캘린더 ───────────────────────────────────
    dividend_calendar: dict = field(default_factory=dict)

    # ── Step 11: ISA 전략 + 리스크 경보 ────────────────────────
    isa:         dict = field(default_factory=dict)
    risk_alerts: list = field(default_factory=list)

    # ── Step 12: FIRE 역산 ──────────────────────────────────────
    fire_plan:    dict = field(default_factory=dict)

    # ── Step 12-b: FIRE 역산 (Reverse) ──────────────────────────
    # 현재 조건 → 목표 달성을 위한 필요 적립금/자산/목표 조정 역산
    # 실패해도 pipeline 전체에 영향 없음 (optional 결과)
    reverse_fire: dict = field(default_factory=dict)

    # ── Step 13: Monte Carlo ────────────────────────────────────
    monte_carlo: dict = field(default_factory=dict)

    # ── Step 13-b: 생존확률 (ML+상관충격 통합 헤드라인 지표) ─────
    survival: dict = field(default_factory=dict)

    # ── Step 14: 세금 최적화 ───────────────────────────────────
    tax_optimizer_result: dict = field(default_factory=dict)

    # ── Step 15: 행동편향 ──────────────────────────────────────
    behavioral: dict = field(default_factory=dict)

    # ── Step 16: Yield Trap 탐지 ────────────────────────────────
    yield_traps: list = field(default_factory=list)

    # ── Step 17: Portfolio Health ───────────────────────────────
    health: dict = field(default_factory=dict)

    # ── Step 18: 스토리텔링 ────────────────────────────────────
    storytelling: str = ""

    # ── 메타 ──────────────────────────────────────────────────
    errors: list[str] = field(default_factory=list)

    def add_error(self, step: str, msg: str) -> None:
        self.errors.append(f"[{step}] {msg}")

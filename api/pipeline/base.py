"""
BaseFilter
──────────
모든 파이프라인 단계가 구현해야 하는 추상 인터페이스.

왜 추상 클래스인가?
  각 단계마다 process(ctx) 라는 동일한 인터페이스를 강제함으로써
  파이프라인 runner가 단계 목록을 순서대로 실행할 수 있다.
  새 분석 단계 추가 = BaseFilter 상속 + process() 구현으로 끝.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from .context import PipelineContext


class BaseFilter(ABC):
    """파이프라인의 모든 단계가 구현해야 하는 추상 인터페이스."""

    @property
    @abstractmethod
    def name(self) -> str:
        """단계 이름 (로깅·디버깅용)."""

    @abstractmethod
    def process(self, ctx: PipelineContext) -> None:
        """
        ctx 를 읽고 연산 후 ctx 에 결과를 저장.
        예외 발생 시 ctx.add_error()로 기록하고 continue.
        """

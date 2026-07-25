from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from app.domain.models import ContractModel, OcId
from app.errors import DomainInvariantError


class ScheduledStep(ContractModel):
    step_id: str
    due_tick: int = Field(ge=0)
    priority: int = 0
    actor_id: OcId
    reason: str


class SchedulerSnapshot(ContractModel):
    current_tick: int = Field(ge=0)
    remaining_steps: list[ScheduledStep]


class DeterministicStepScheduler:
    """A finite scheduler whose ordering is independent of insertion order."""

    def __init__(
        self,
        steps: Iterable[ScheduledStep] = (),
        *,
        current_tick: int = 0,
    ) -> None:
        materialized = list(steps)
        step_ids = [step.step_id for step in materialized]
        if len(step_ids) != len(set(step_ids)):
            raise DomainInvariantError("scheduled step ids must be unique")
        self.current_tick = current_tick
        self._remaining = sorted(materialized, key=self._sort_key)

    @staticmethod
    def _sort_key(step: ScheduledStep) -> tuple[int, int, str, str]:
        return (
            step.due_tick,
            -step.priority,
            step.actor_id,
            step.step_id,
        )

    def pop_next(self) -> ScheduledStep | None:
        if not self._remaining:
            return None
        step = self._remaining.pop(0)
        self.current_tick = max(self.current_tick, step.due_tick)
        return step

    def drain(self) -> list[ScheduledStep]:
        drained: list[ScheduledStep] = []
        while (step := self.pop_next()) is not None:
            drained.append(step)
        return drained

    def snapshot(self) -> SchedulerSnapshot:
        return SchedulerSnapshot(
            current_tick=self.current_tick,
            remaining_steps=[
                step.model_copy(deep=True) for step in self._remaining
            ],
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: SchedulerSnapshot,
    ) -> "DeterministicStepScheduler":
        return cls(
            snapshot.remaining_steps,
            current_tick=snapshot.current_tick,
        )

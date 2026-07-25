from __future__ import annotations

import importlib


def test_scheduler_order_is_deterministic_across_insertion_order() -> None:
    scheduler_module = importlib.import_module("app.domain.scheduler")
    ScheduledStep = getattr(scheduler_module, "ScheduledStep")
    DeterministicStepScheduler = getattr(
        scheduler_module,
        "DeterministicStepScheduler",
    )
    steps = [
        ScheduledStep(
            step_id="step-user",
            due_tick=2,
            priority=5,
            actor_id="oc-user",
            reason="goal_due",
        ),
        ScheduledStep(
            step_id="step-devil",
            due_tick=1,
            priority=5,
            actor_id="oc-devil",
            reason="world_clock",
        ),
        ScheduledStep(
            step_id="step-angel",
            due_tick=1,
            priority=8,
            actor_id="oc-angel",
            reason="deadline",
        ),
    ]

    forward = DeterministicStepScheduler(steps)
    reverse = DeterministicStepScheduler(reversed(steps))

    assert [step.step_id for step in forward.drain()] == [
        "step-angel",
        "step-devil",
        "step-user",
    ]
    assert [step.step_id for step in reverse.drain()] == [
        "step-angel",
        "step-devil",
        "step-user",
    ]
    assert forward.current_tick == reverse.current_tick == 2


def test_scheduler_snapshot_replays_only_remaining_finite_steps() -> None:
    scheduler_module = importlib.import_module("app.domain.scheduler")
    ScheduledStep = getattr(scheduler_module, "ScheduledStep")
    DeterministicStepScheduler = getattr(
        scheduler_module,
        "DeterministicStepScheduler",
    )
    scheduler = DeterministicStepScheduler(
        [
            ScheduledStep(
                step_id="step-one",
                due_tick=3,
                priority=1,
                actor_id="oc-user",
                reason="routine",
            ),
            ScheduledStep(
                step_id="step-two",
                due_tick=4,
                priority=1,
                actor_id="oc-angel",
                reason="routine",
            ),
        ]
    )
    assert scheduler.pop_next().step_id == "step-one"

    replay = DeterministicStepScheduler.from_snapshot(scheduler.snapshot())

    assert [step.step_id for step in replay.drain()] == ["step-two"]
    assert replay.pop_next() is None

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.models import WorldDefinition
from app.domain.policies import DeterministicMindPolicy
from app.domain.reducer import canonical_state_checksum
from app.errors import RuntimeExecutionError
from app.runtime import DemoRuntime
from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


class CountingMindPolicy(DeterministicMindPolicy):
    def __init__(self) -> None:
        self.calls = 0

    def interpret(self, observation):
        self.calls += 1
        return super().interpret(observation)


class FailingMindPolicy(DeterministicMindPolicy):
    def interpret(self, observation):
        raise RuntimeError("injected mind failure")


def load_world() -> WorldDefinition:
    return WorldDefinition.model_validate_json(WORLD_PATH.read_text(encoding="utf-8"))


def test_runtime_runs_three_ticks_with_continuous_ordered_events(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    runtime = DemoRuntime(storage, load_world())

    session = runtime.create_and_run(
        session_id="session-runtime-on",
        consent_required=True,
    )
    events = storage.get_events(session["sessionId"])

    assert [event["cursor"] for event in events] == list(range(1, len(events) + 1))
    assert [
        event["tickIndex"]
        for event in events
        if event["type"] == "tick.started"
    ] == [0, 1, 2]
    assert events[-1]["type"] == "session.completed"
    assert session["state"]["objects"]["threshold-key"]["holderId"] == "oc-devil"
    assert session["state"]["thresholdUnlocked"] is False


def test_runtime_preserves_belief_to_utterance_to_fact_order(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    DemoRuntime(storage, load_world()).create_and_run(
        session_id="session-runtime-on",
        consent_required=True,
    )
    events = storage.get_events("session-runtime-on")

    belief_cursor = next(
        event["cursor"]
        for event in events
        if event["type"] == "belief.updated"
        and event["payload"]["belief"]["ocId"] == "oc-angel"
    )
    proposal_cursor = next(
        event["cursor"]
        for event in events
        if event["type"] == "proposal.utterance.created"
        and event["payload"]["proposal"]["actorId"] == "oc-angel"
    )
    decision_cursor = next(
        event["cursor"]
        for event in events
        if event["type"] == "rule.decision.created"
        and event["payload"]["decision"]["proposalId"].endswith("angel-utterance")
    )
    canonical = next(
        event
        for event in events
        if event["type"] == "canonical.event.committed"
        and event["payload"]["event"]["kind"] == "utterance.spoken"
        and event["payload"]["event"]["actorId"] == "oc-angel"
    )

    assert belief_cursor < proposal_cursor < decision_cursor < canonical["cursor"]
    assert canonical["payload"]["event"]["factCodes"] == ["utterance.spoken"]
    assert "偷" not in json.dumps(
        canonical["payload"]["event"]["factCodes"],
        ensure_ascii=False,
    )


def test_reconstruction_uses_canonical_events_without_rerunning_mind_policy(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    mind_policy = CountingMindPolicy()
    runtime = DemoRuntime(storage, load_world(), mind_policy=mind_policy)
    session = runtime.create_and_run(
        session_id="session-runtime-on",
        consent_required=True,
    )
    calls_after_run = mind_policy.calls

    reconstructed = runtime.reconstruct("session-runtime-on")

    assert mind_policy.calls == calls_after_run
    assert reconstructed.model_dump(by_alias=True) == session["state"]
    assert canonical_state_checksum(reconstructed) == session["checksum"]


def test_stored_checksum_equals_a_canonical_only_fold(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    runtime = DemoRuntime(storage, load_world())
    session = runtime.create_and_run(
        session_id="session-runtime-on",
        consent_required=True,
    )
    canonical_events = [
        event["payload"]["event"]
        for event in storage.get_events("session-runtime-on")
        if event["type"] == "canonical.event.committed"
    ]

    folded = runtime.fold_canonical_events(canonical_events)

    assert canonical_state_checksum(folded) == session["checksum"]


def test_consent_off_allows_take_without_opening_the_threshold(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    session = DemoRuntime(storage, load_world()).create_and_run(
        session_id="session-runtime-off",
        consent_required=False,
    )

    take_decision = next(
        event["payload"]["decision"]
        for event in storage.get_events("session-runtime-off")
        if event["type"] == "rule.decision.created"
        and event["payload"]["decision"]["proposalId"].endswith("take-key")
    )
    assert take_decision["outcome"] == "success"
    assert session["state"]["objects"]["threshold-key"]["holderId"] == "oc-devil"
    assert session["state"]["thresholdUnlocked"] is False


def test_private_os_is_not_a_canonical_event_or_checksum_input(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    session = DemoRuntime(storage, load_world()).create_and_run(
        session_id="session-runtime-on",
        consent_required=True,
    )
    events = storage.get_events("session-runtime-on")

    assert any(event["type"] == "privateOs.created" for event in events)
    canonical_payloads = [
        event["payload"]["event"]
        for event in events
        if event["type"] == "canonical.event.committed"
    ]
    assert "privateOs" not in json.dumps(canonical_payloads, ensure_ascii=False)
    assert canonical_state_checksum(
        load_world().initial_state.model_validate(session["state"])
    ) == session["checksum"]


def test_runtime_failure_marks_session_failed_and_appends_runtime_error(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    runtime = DemoRuntime(
        storage,
        load_world(),
        mind_policy=FailingMindPolicy(),
    )

    with pytest.raises(RuntimeExecutionError):
        runtime.create_and_run(
            session_id="session-runtime-failed",
            consent_required=True,
        )

    session = storage.get_session("session-runtime-failed")
    events = storage.get_events("session-runtime-failed")
    assert session["status"] == "failed"
    assert events[-1]["type"] == "runtime.error"
    assert events[-1]["payload"] == {
        "code": "RUNTIME_EXECUTION_FAILED",
        "message": "Runtime execution failed.",
        "recoverable": False,
    }
    assert not any(event["type"] == "session.completed" for event in events)

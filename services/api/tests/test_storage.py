from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.errors import SessionNotFound
from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def initial_state() -> dict:
    return json.loads(WORLD_PATH.read_text(encoding="utf-8"))["initialState"]


def envelope(cursor: int) -> dict:
    return {
        "schemaVersion": 1,
        "eventId": f"event-{cursor}",
        "cursor": cursor,
        "sessionId": "session-storage",
        "tickIndex": 0,
        "emittedAt": "2026-07-24T00:00:00Z",
        "type": "tick.started",
        "visibility": {"scope": "public"},
        "payload": {"actorId": "oc-devil", "worldVersion": 0},
    }


def completion_envelope(cursor: int) -> dict:
    return {
        "schemaVersion": 1,
        "eventId": f"event-{cursor}",
        "cursor": cursor,
        "sessionId": "session-storage",
        "tickIndex": 2,
        "emittedAt": "2026-07-24T00:00:02Z",
        "type": "session.completed",
        "visibility": {"scope": "public"},
        "payload": {
            "worldVersion": 4,
            "lastCanonicalSequence": 4,
            "checksum": "b" * 64,
        },
    }


def test_storage_has_only_sessions_and_append_only_session_events(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    storage = SQLiteStorage(database_path)

    table_names = storage.table_names()

    assert table_names == {"sessions", "session_events"}


def test_event_cursor_must_be_continuous_and_events_cannot_be_updated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite3"
    storage = SQLiteStorage(database_path)
    storage.create_session(
        session_id="session-storage",
        world_id="infinite-apartment",
        seed="fixed-seed",
        consent_required=True,
        state=initial_state(),
    )
    storage.append_event("session-storage", envelope(1))

    with pytest.raises(ValueError, match="expected cursor 2"):
        storage.append_event("session-storage", envelope(3))

    with sqlite3.connect(database_path) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            connection.execute(
                "UPDATE session_events SET event_type = ? WHERE session_id = ?",
                ("runtime.error", "session-storage"),
            )

    assert [event["cursor"] for event in storage.get_events("session-storage")] == [1]


def test_canonical_event_and_objective_state_update_are_atomic(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    storage.create_session(
        session_id="session-storage",
        world_id="infinite-apartment",
        seed="fixed-seed",
        consent_required=True,
        state=initial_state(),
    )
    first_state = initial_state()
    first_state["worldVersion"] = 1
    storage.append_event_and_update_state(
        "session-storage",
        envelope(1),
        state=first_state,
        checksum="checksum-one",
    )

    second_state = initial_state()
    second_state["worldVersion"] = 2
    with pytest.raises(ValueError, match="expected cursor 2"):
        storage.append_event_and_update_state(
            "session-storage",
            envelope(3),
            state=second_state,
            checksum="checksum-two",
        )

    record = storage.get_session("session-storage")
    assert record["state"]["worldVersion"] == 1
    assert record["checksum"] == "checksum-one"
    assert len(storage.get_events("session-storage")) == 1


def test_connection_context_explicitly_closes_sqlite_connection(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")

    with storage.connection() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_finish_event_and_completed_status_are_one_transaction(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    storage.create_session(
        session_id="session-storage",
        world_id="infinite-apartment",
        seed="fixed-seed",
        consent_required=True,
        state=initial_state(),
    )
    completed_state = initial_state()
    completed_state["status"] = "completed"

    with pytest.raises(ValueError, match="expected cursor 1"):
        storage.append_event_and_finish_session(
            "session-storage",
            completion_envelope(2),
            state=completed_state,
            checksum="a" * 64,
        )

    assert storage.get_session("session-storage")["status"] == "running"
    assert storage.get_events("session-storage") == []

    storage.append_event_and_finish_session(
        "session-storage",
        completion_envelope(1),
        state=completed_state,
        checksum="b" * 64,
    )
    assert storage.get_session("session-storage")["status"] == "completed"
    assert storage.get_events("session-storage")[-1]["cursor"] == 1


def test_missing_session_raises_only_the_dedicated_exception(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")

    with pytest.raises(SessionNotFound):
        storage.get_session("missing")


def test_persistence_rejects_invalid_discriminated_payload_and_naive_datetime(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    storage.create_session(
        session_id="session-storage",
        world_id="infinite-apartment",
        seed="fixed-seed",
        consent_required=True,
        state=initial_state(),
    )
    wrong_payload = envelope(1)
    wrong_payload["payload"] = {
        "code": "WRONG",
        "message": "not a tick payload",
        "recoverable": False,
    }
    naive_datetime = envelope(1)
    naive_datetime["emittedAt"] = "2026-07-24T00:00:01"

    with pytest.raises(ValueError):
        storage.append_event("session-storage", wrong_payload)
    with pytest.raises(ValueError):
        storage.append_event("session-storage", naive_datetime)

    assert storage.get_events("session-storage") == []

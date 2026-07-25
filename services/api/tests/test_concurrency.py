from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def initial_state() -> dict:
    return json.loads(WORLD_PATH.read_text(encoding="utf-8"))["initialState"]


def envelope(session_id: str) -> dict:
    return {
        "schemaVersion": 1,
        "eventId": f"{session_id}-event-1",
        "cursor": 1,
        "sessionId": session_id,
        "tickIndex": 0,
        "emittedAt": "2026-07-24T00:00:01Z",
        "type": "tick.started",
        "visibility": {"scope": "public"},
        "payload": {"actorId": "oc-devil", "worldVersion": 0},
    }


def test_sqlite_uses_wal_and_a_nonzero_busy_timeout(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")

    with storage.connection() as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert busy_timeout >= 500


def test_concurrent_writers_do_not_lose_events_or_raise_locked(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime.sqlite3")
    session_ids = [f"session-concurrent-{index}" for index in range(16)]
    for session_id in session_ids:
        storage.create_session(
            session_id=session_id,
            world_id="infinite-apartment",
            seed="fixed-seed",
            consent_required=True,
            state=initial_state(),
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(
            executor.map(
                lambda session_id: storage.append_event(
                    session_id,
                    envelope(session_id),
                ),
                session_ids,
            )
        )

    assert all(
        len(storage.get_events(session_id)) == 1 for session_id in session_ids
    )


def test_locked_writes_are_retried_a_bounded_number_of_times(
    tmp_path: Path,
    monkeypatch,
) -> None:
    storage = SQLiteStorage(
        tmp_path / "runtime.sqlite3",
        write_retries=3,
        retry_delay_seconds=0,
    )
    original_connection = storage.connection
    attempts = 0

    @contextmanager
    def flaky_connection():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise sqlite3.OperationalError("database is locked")
        with original_connection() as connection:
            yield connection

    monkeypatch.setattr(storage, "connection", flaky_connection)

    storage.create_session(
        session_id="session-retry",
        world_id="infinite-apartment",
        seed="fixed-seed",
        consent_required=True,
        state=initial_state(),
    )

    assert attempts == 3

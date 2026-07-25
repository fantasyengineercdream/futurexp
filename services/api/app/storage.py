from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

from app.domain.models import WorldState
from app.domain.reducer import canonical_state_checksum
from app.dto import RuntimeEventAdapter
from app.errors import (
    DomainInvariantError,
    OcImportNotFound,
    RegisteredOcNotFound,
    SessionNotFound,
)


T = TypeVar("T")


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class SQLiteStorage:
    def __init__(
        self,
        database_path: str | Path,
        *,
        write_retries: int = 3,
        retry_delay_seconds: float = 0.02,
        busy_timeout_ms: int = 2_000,
    ) -> None:
        if write_retries < 0:
            raise ValueError("write_retries must be non-negative")
        if busy_timeout_ms < 500:
            raise ValueError("busy_timeout_ms must be at least 500")
        self.database_path = Path(database_path)
        self.write_retries = write_retries
        self.retry_delay_seconds = retry_delay_seconds
        self.busy_timeout_ms = busy_timeout_ms
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_ms / 1_000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    world_id TEXT NOT NULL,
                    seed TEXT NOT NULL,
                    consent_required INTEGER NOT NULL CHECK (consent_required IN (0, 1)),
                    status TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    checksum TEXT NOT NULL,
                    last_cursor INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS session_events (
                    session_id TEXT NOT NULL,
                    cursor INTEGER NOT NULL,
                    event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    envelope_json TEXT NOT NULL,
                    PRIMARY KEY (session_id, cursor),
                    UNIQUE (session_id, event_id),
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE TRIGGER IF NOT EXISTS session_events_no_update
                BEFORE UPDATE ON session_events
                BEGIN
                    SELECT RAISE(ABORT, 'session_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS session_events_no_delete
                BEFORE DELETE ON session_events
                BEGIN
                    SELECT RAISE(ABORT, 'session_events is append-only');
                END;

                """
            )
            session_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(sessions)"
                ).fetchall()
            }
            if "views_json" not in session_columns:
                connection.execute(
                    """
                    ALTER TABLE sessions
                    ADD COLUMN views_json TEXT NOT NULL DEFAULT '{}'
                    """
                )

    def _run_write(
        self,
        operation: Callable[[sqlite3.Connection], T],
    ) -> T:
        for attempt in range(self.write_retries + 1):
            try:
                with self.connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    return operation(connection)
            except sqlite3.OperationalError as error:
                is_transient = any(
                    marker in str(error).lower()
                    for marker in ("locked", "busy")
                )
                if not is_transient or attempt == self.write_retries:
                    raise
                time.sleep(self.retry_delay_seconds)
        raise DomainInvariantError("bounded SQLite retry loop did not terminate")

    def save_oc_import_draft(
        self,
        draft_id: str,
        draft: dict[str, Any],
    ) -> None:
        self.save_living_world_view(
            "system-oc-registry-v01",
            f"oc-import:{draft_id}",
            draft,
        )

    def get_oc_import_draft(self, draft_id: str) -> dict[str, Any]:
        try:
            return self.get_living_world_view(
                "system-oc-registry-v01",
                f"oc-import:{draft_id}",
            )
        except SessionNotFound as error:
            raise OcImportNotFound(draft_id) from error

    def register_oc(
        self,
        oc_id: str,
        registered: dict[str, Any],
    ) -> None:
        self.save_living_world_view(
            "system-oc-registry-v01",
            f"registered-oc:{oc_id}",
            registered,
        )

    def get_registered_oc(self, oc_id: str) -> dict[str, Any]:
        try:
            return self.get_living_world_view(
                "system-oc-registry-v01",
                f"registered-oc:{oc_id}",
            )
        except SessionNotFound as error:
            raise RegisteredOcNotFound(oc_id) from error

    @staticmethod
    def _validated_envelope(envelope: dict[str, Any]) -> dict[str, Any]:
        event = RuntimeEventAdapter.validate_python(envelope)
        return RuntimeEventAdapter.dump_python(
            event,
            mode="json",
            by_alias=True,
        )

    def table_names(self) -> set[str]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        return {row["name"] for row in rows}

    def create_session(
        self,
        *,
        session_id: str,
        world_id: str,
        seed: str,
        consent_required: bool,
        state: dict[str, Any],
    ) -> None:
        validated_state = WorldState.model_validate(state)

        def insert(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO sessions (
                    session_id,
                    world_id,
                    seed,
                    consent_required,
                    status,
                    state_json,
                    checksum,
                    last_cursor
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, 0)
                """,
                (
                    session_id,
                    world_id,
                    seed,
                    int(consent_required),
                    _json_dumps(
                        validated_state.model_dump(
                            mode="json",
                            by_alias=True,
                        )
                    ),
                    canonical_state_checksum(validated_state),
                ),
            )

        self._run_write(insert)

    def append_event(self, session_id: str, envelope: dict[str, Any]) -> None:
        validated = self._validated_envelope(envelope)
        self._run_write(
            lambda connection: self._append_event(
                connection,
                session_id,
                validated,
            )
        )

    def append_event_and_update_state(
        self,
        session_id: str,
        envelope: dict[str, Any],
        *,
        state: dict[str, Any],
        checksum: str,
    ) -> None:
        validated = self._validated_envelope(envelope)
        validated_state = WorldState.model_validate(state).model_dump(
            mode="json",
            by_alias=True,
        )

        def append_and_update(connection: sqlite3.Connection) -> None:
            self._append_event(connection, session_id, validated)
            connection.execute(
                """
                UPDATE sessions
                SET state_json = ?, checksum = ?
                WHERE session_id = ?
                """,
                (_json_dumps(validated_state), checksum, session_id),
            )

        self._run_write(append_and_update)

    def append_event_and_finish_session(
        self,
        session_id: str,
        envelope: dict[str, Any],
        *,
        state: dict[str, Any],
        checksum: str,
    ) -> None:
        validated = self._validated_envelope(envelope)
        if validated["type"] != "session.completed":
            raise DomainInvariantError(
                "completed sessions require a session.completed event"
            )
        validated_state = WorldState.model_validate(state)
        if validated_state.status != "completed":
            raise DomainInvariantError("completed session state must be completed")

        def append_and_finish(connection: sqlite3.Connection) -> None:
            self._append_event(connection, session_id, validated)
            connection.execute(
                """
                UPDATE sessions
                SET status = 'completed', state_json = ?, checksum = ?
                WHERE session_id = ?
                """,
                (
                    _json_dumps(
                        validated_state.model_dump(
                            mode="json",
                            by_alias=True,
                        )
                    ),
                    checksum,
                    session_id,
                ),
            )

        self._run_write(append_and_finish)

    def append_event_and_fail_session(
        self,
        session_id: str,
        envelope: dict[str, Any],
        *,
        state: dict[str, Any],
        checksum: str,
    ) -> None:
        validated = self._validated_envelope(envelope)
        if validated["type"] != "runtime.error":
            raise DomainInvariantError("failed sessions require a runtime.error event")
        validated_state = WorldState.model_validate(state)
        if validated_state.status != "failed":
            raise DomainInvariantError("failed session state must be failed")

        def append_and_fail(connection: sqlite3.Connection) -> None:
            self._append_event(connection, session_id, validated)
            connection.execute(
                """
                UPDATE sessions
                SET status = 'failed', state_json = ?, checksum = ?
                WHERE session_id = ?
                """,
                (
                    _json_dumps(
                        validated_state.model_dump(
                            mode="json",
                            by_alias=True,
                        )
                    ),
                    checksum,
                    session_id,
                ),
            )

        self._run_write(append_and_fail)

    def _append_event(
        self,
        connection: sqlite3.Connection,
        session_id: str,
        envelope: dict[str, Any],
    ) -> None:
        row = connection.execute(
            "SELECT last_cursor FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        expected_cursor = row["last_cursor"] + 1
        actual_cursor = envelope["cursor"]
        if actual_cursor != expected_cursor:
            raise ValueError(
                f"expected cursor {expected_cursor}, got {actual_cursor}"
            )
        if envelope["sessionId"] != session_id:
            raise ValueError("envelope sessionId does not match target session")

        connection.execute(
            """
            INSERT INTO session_events (
                session_id,
                cursor,
                event_id,
                event_type,
                envelope_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                session_id,
                actual_cursor,
                envelope["eventId"],
                envelope["type"],
                _json_dumps(envelope),
            ),
        )
        connection.execute(
            "UPDATE sessions SET last_cursor = ? WHERE session_id = ?",
            (actual_cursor, session_id),
        )

    def get_session(self, session_id: str) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFound(session_id)
        return {
            "sessionId": row["session_id"],
            "worldId": row["world_id"],
            "seed": row["seed"],
            "consentRequired": bool(row["consent_required"]),
            "status": row["status"],
            "state": json.loads(row["state_json"]),
            "checksum": row["checksum"],
            "lastCursor": row["last_cursor"],
        }

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT envelope_json
                FROM session_events
                WHERE session_id = ?
                ORDER BY cursor
                """,
                (session_id,),
            ).fetchall()
        return [json.loads(row["envelope_json"]) for row in rows]

    def save_living_world_views(
        self,
        run_id: str,
        views: dict[str, dict[str, Any]],
    ) -> None:
        def save(connection: sqlite3.Connection) -> None:
            result = connection.execute(
                """
                UPDATE sessions
                SET views_json = ?
                WHERE session_id = ?
                """,
                (_json_dumps(views), run_id),
            )
            if result.rowcount != 1:
                raise SessionNotFound(run_id)

        self._run_write(save)

    def save_living_world_view(
        self,
        run_id: str,
        view_key: str,
        view: dict[str, Any],
    ) -> None:
        def save(connection: sqlite3.Connection) -> None:
            row = connection.execute(
                "SELECT views_json FROM sessions WHERE session_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise SessionNotFound(run_id)
            views = json.loads(row["views_json"])
            views[view_key] = view
            connection.execute(
                """
                UPDATE sessions
                SET views_json = ?
                WHERE session_id = ?
                """,
                (_json_dumps(views), run_id),
            )

        self._run_write(save)

    def get_living_world_view(
        self,
        run_id: str,
        view_key: str,
    ) -> dict[str, Any]:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT views_json FROM sessions WHERE session_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            raise SessionNotFound(run_id)
        views = json.loads(row["views_json"])
        view = views.get(view_key)
        if not isinstance(view, dict):
            raise SessionNotFound(run_id)
        return view

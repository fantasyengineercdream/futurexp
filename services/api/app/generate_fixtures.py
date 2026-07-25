from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from app.domain.models import WorldDefinition
from app.runtime import DemoRuntime
from app.storage import SQLiteStorage
from app.views import (
    build_owner_view,
    build_passport_view,
    build_proof_view,
    build_world_view,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "fixtures" / "infinite-apartment"
VIEW_DIR = FIXTURE_DIR / "views"
WORLD_PATH = FIXTURE_DIR / "world.json"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def generate() -> None:
    world = WorldDefinition.model_validate_json(
        WORLD_PATH.read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory(prefix="kaleidoroom-fixtures-") as directory:
        storage = SQLiteStorage(Path(directory) / "runtime.sqlite3")
        for label, consent_required in (("consent-on", True), ("consent-off", False)):
            session_id = f"fixture-{label}"
            DemoRuntime(storage, world).create_and_run(
                session_id=session_id,
                consent_required=consent_required,
            )
            events = storage.get_events(session_id)
            _write_json(
                FIXTURE_DIR / f"demo-session-{label}.json",
                {
                    "fixtureType": "demoSession",
                    "sessionId": session_id,
                    "worldId": world.world_id,
                    "seed": world.event_seed,
                    "consentRequired": consent_required,
                    "participantIds": ["oc-user", "oc-angel", "oc-devil"],
                    "events": events,
                },
            )
            _write_json(
                VIEW_DIR / f"{label}-world.json",
                build_world_view(storage, world, session_id).model_dump(
                    mode="json",
                    by_alias=True,
                ),
            )
            _write_json(
                VIEW_DIR / f"{label}-owner.json",
                build_owner_view(storage, world, session_id).model_dump(
                    mode="json",
                    by_alias=True,
                ),
            )
            _write_json(
                VIEW_DIR / f"{label}-proof.json",
                build_proof_view(storage, session_id).model_dump(
                    mode="json",
                    by_alias=True,
                ),
            )

        _write_json(
            VIEW_DIR / "passport.json",
            build_passport_view(world).model_dump(
                mode="json",
                by_alias=True,
            ),
        )


if __name__ == "__main__":
    generate()

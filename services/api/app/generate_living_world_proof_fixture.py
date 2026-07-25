from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from app.domain.day_cycle import (
    LivingWorldDayCore,
    LivingWorldDayProjectionDTO,
)
from app.domain.living_world import (
    DeterministicSceneDirector,
    load_preset_runtime_bundle,
)
from app.domain.product_projections import (
    LivingMemoryStoreDTO,
    OwnerPrivateOsDTO,
    OwnerRoomDialogueDTO,
    RoomProjectionDTO,
    WorldProjectionDTO,
    build_dialogue_private_os,
    build_owner_dialogue,
)
from app.domain.transactional_living_world import LivingWorldProofDTO
from app.runtime import TransactionalLivingWorldRuntime
from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "fixtures" / "living-world-v02"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def generate() -> None:
    bundle = load_preset_runtime_bundle()
    day_projection = LivingWorldDayCore(bundle).run_day(
        run_id="fixture-day-loop-v01",
        day_index=1,
        seed="kaleidoroom-day-loop-v01",
        memories={
            profile.oc_id: [] for profile in bundle.actor_profiles
        },
    ).to_product_projection(bundle)
    with tempfile.TemporaryDirectory(
        prefix="kaleidoroom-living-world-v02-"
    ) as directory:
        storage = SQLiteStorage(Path(directory) / "runtime.sqlite3")
        proof = TransactionalLivingWorldRuntime(
            storage,
            bundle,
            director=DeterministicSceneDirector(adventure_published=True),
        ).create_and_run(
            session_id="fixture-transactional-v02",
            seed="kaleidoroom-transactional-v02-proof",
        )
        TransactionalLivingWorldRuntime(
            storage,
            bundle,
        ).create_and_run(
            session_id="fixture-product-v02",
            seed="kaleidoroom-product-projection-v02",
        )
        world_projection = storage.get_living_world_view(
            "fixture-product-v02",
            "world",
        )
        room_projection = storage.get_living_world_view(
            "fixture-product-v02",
            "room:resident-oo",
        )
        room_dto = RoomProjectionDTO.model_validate(room_projection)
        memory_store = LivingMemoryStoreDTO.model_validate(
            storage.get_living_world_view(
                "fixture-product-v02",
                "memory",
            )
        )
        owner_dialogue = build_owner_dialogue(
            bundle,
            room_dto,
            memory_store,
            "今天在外面发生了什么？",
        )
        owner_private_os = build_dialogue_private_os(
            room_dto,
            memory_store,
            owner_dialogue,
        )
    _write_json(
        FIXTURE_DIR / "living-world-proof.schema.json",
        LivingWorldProofDTO.model_json_schema(),
    )
    _write_json(
        FIXTURE_DIR / "living-world-proof.example.json",
        proof.model_dump(mode="json", by_alias=True),
    )
    _write_json(
        FIXTURE_DIR / "world-projection.schema.json",
        WorldProjectionDTO.model_json_schema(),
    )
    _write_json(
        FIXTURE_DIR / "world-projection.example.json",
        world_projection,
    )
    _write_json(
        FIXTURE_DIR / "room-projection.schema.json",
        RoomProjectionDTO.model_json_schema(),
    )
    _write_json(
        FIXTURE_DIR / "room-projection.example.json",
        room_projection,
    )
    _write_json(
        FIXTURE_DIR / "owner-room-dialogue.schema.json",
        OwnerRoomDialogueDTO.model_json_schema(),
    )
    _write_json(
        FIXTURE_DIR / "owner-room-dialogue.example.json",
        owner_dialogue.model_dump(mode="json", by_alias=True),
    )
    _write_json(
        FIXTURE_DIR / "owner-private-os.schema.json",
        OwnerPrivateOsDTO.model_json_schema(),
    )
    _write_json(
        FIXTURE_DIR / "owner-private-os.example.json",
        owner_private_os.model_dump(mode="json", by_alias=True),
    )
    _write_json(
        FIXTURE_DIR / "day-projection.schema.json",
        LivingWorldDayProjectionDTO.model_json_schema(),
    )
    _write_json(
        FIXTURE_DIR / "day-projection.example.json",
        day_projection.model_dump(mode="json", by_alias=True),
    )


if __name__ == "__main__":
    generate()

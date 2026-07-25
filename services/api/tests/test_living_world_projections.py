from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.domain.product_projections import (
    LivingMemoryStoreDTO,
    OwnerPrivateOsDTO,
    OwnerRoomDialogueDTO,
    RoomProjectionDTO,
    WorldProjectionDTO,
)
from app.domain.living_world import load_preset_runtime_bundle
from app.main import create_app
from app.runtime import TransactionalLivingWorldRuntime
from app.storage import SQLiteStorage


def _forbidden_keys(value: Any) -> set[str]:
    forbidden = {
        "proposals",
        "conflictSets",
        "resolutionBatch",
        "effects",
        "privateInnerOs",
        "deterministicEvidence",
    }
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(forbidden & value.keys())
        for child in value.values():
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def create_product_run(api: TestClient) -> dict[str, Any]:
    response = api.post(
        "/api/living-world/world-runs",
        json={"seed": "product-projection-seed"},
    )
    assert response.status_code == 201
    return response.json()


def test_world_projection_is_a_small_product_read_model(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "world-projection.sqlite3")
    api = TestClient(create_app(storage))

    world = create_product_run(api)

    assert WorldProjectionDTO.model_validate(world)
    assert world["worldVersion"] == 1
    assert world["tickIndex"] == 0
    assert world["roundStatus"] == "idle"
    assert {floor["kind"] for floor in world["floors"]} == {
        "safe",
        "neutral",
        "adventure",
    }
    assert len(world["residents"]) == 3
    assert {resident["actorId"] for resident in world["residents"]} == {
        "oc-user",
        "oc-angel",
        "oc-devil",
    }
    assert all(resident["displayName"] for resident in world["residents"])
    assert all(
        resident["presence"]
        in {"home", "public", "adventure", "resting", "away"}
        for resident in world["residents"]
    )
    assert all(
        "speak publicly" not in resident["publicActivitySummary"]
        for resident in world["residents"]
    )
    assert world["publicScenes"] == []
    assert not any(
        resident["newExperience"] for resident in world["residents"]
    )
    assert _forbidden_keys(world) == set()

    fetched = api.get(
        f"/api/living-world/runs/{world['runId']}/world"
    )
    assert fetched.status_code == 200
    assert fetched.json() == world


def test_advance_returns_the_committed_demo_projection(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "advance-projection.sqlite3")
    api = TestClient(create_app(storage))
    before = create_product_run(api)

    response = api.post(
        f"/api/living-world/runs/{before['runId']}/advance"
    )

    assert response.status_code == 200
    after = response.json()
    assert WorldProjectionDTO.model_validate(after)
    assert after["runId"] == before["runId"]
    assert after["worldVersion"] == 2
    assert after["tickIndex"] == 1
    assert after["roundStatus"] == "committed"
    assert after["publicScenes"]
    assert any(
        resident["newExperience"] for resident in after["residents"]
    )
    assert after != before
    fetched = api.get(
        f"/api/living-world/runs/{before['runId']}/world"
    )
    assert fetched.status_code == 200
    assert fetched.json() == after


def test_default_advance_shows_daily_social_life_without_an_adventure(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "demo-event.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    after = api.post(
        f"/api/living-world/runs/{ready['runId']}/advance"
    ).json()
    proof = api.get(
        f"/api/living-world/runs/{ready['runId']}/proof"
    ).json()

    summary = after["publicScenes"][0]["publicSummary"]
    assert "日常" in summary
    assert "交谈" in summary
    assert "保持安静" in summary
    assert "冒险" not in summary
    residents = {
        resident["actorId"]: resident
        for resident in after["residents"]
    }
    assert residents["oc-angel"]["currentLocationId"] == (
        "apartment-library"
    )
    assert residents["oc-devil"]["currentLocationId"] == (
        "apartment-library"
    )
    assert residents["oc-angel"]["presence"] == "public"
    assert residents["oc-devil"]["presence"] == "public"

    assert {
        proposal["intentKind"]
        for proposal in proof["proposals"]
    } <= {"MOVE", "WAIT"}
    assert all(
        receipt["status"] == "applied"
        for receipt in proof["resolutionBatch"]["receipts"]
    )

    room = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo"
    ).json()
    assert "交谈" in room["latestDiary"]["summary"]
    assert "冒险" not in room["latestDiary"]["summary"]
    assert "memory changes" not in room["latestDiary"]["summary"]
    assert room["publicExpression"]
    assert room["relationshipSummaries"]


def test_owner_counsel_changes_the_next_demo_advance(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "owner-counsel.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    event_world = api.post(
        f"/api/living-world/runs/{ready['runId']}/advance"
    ).json()
    room = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo"
    ).json()
    experience_ref = room["recentExperienceRefs"][0]
    world_before_counsel = api.get(
        f"/api/living-world/runs/{ready['runId']}/world"
    ).json()

    counsel = api.post(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo/counsel",
        json={
            "experienceRef": experience_ref,
            "adviceId": "verify-before-judging",
        },
    )

    assert counsel.status_code == 201
    receipt = counsel.json()
    assert receipt["runId"] == ready["runId"]
    assert receipt["residentId"] == "resident-oo"
    assert receipt["experienceRef"] == experience_ref
    assert receipt["adviceId"] == "verify-before-judging"
    assert receipt["disposition"] == "considered"
    assert receipt["summary"]
    assert api.get(
        f"/api/living-world/runs/{ready['runId']}/world"
    ).json() == world_before_counsel

    memory_store = LivingMemoryStoreDTO.model_validate(
        storage.get_living_world_view(ready["runId"], "memory")
    )
    counsel_memories = [
        memory
        for memory in memory_store.memories["oc-angel"]
        if memory.kind == "ownerCounsel"
    ]
    assert len(counsel_memories) == 1
    assert counsel_memories[0].source_observation_ids == [experience_ref]

    next_world = api.post(
        f"/api/living-world/runs/{ready['runId']}/advance"
    ).json()
    assert next_world["worldVersion"] > event_world["worldVersion"]
    assert next_world["tickIndex"] > event_world["tickIndex"]
    oo = next(
        resident
        for resident in next_world["residents"]
        if resident["residentId"] == "resident-oo"
    )
    assert oo["currentLocationId"] == "apartment-library"

    runtime_meta = storage.get_living_world_view(
        ready["runId"],
        "runtime:meta",
    )
    canonical_run_id = runtime_meta["latestCanonicalRunId"]
    assert canonical_run_id != ready["runId"]
    canonical_events = [
        event
        for event in storage.get_events(canonical_run_id)
        if event["type"] == "canonical.event.committed"
    ]
    assert canonical_events
    assert any(
        "actor.waited" in event["payload"]["event"]["factCodes"]
        for event in canonical_events
    )
    proof = api.get(
        f"/api/living-world/runs/{ready['runId']}/proof"
    ).json()
    oo_proposal = next(
        proposal
        for proposal in proof["proposals"]
        if proposal["actorId"] == "oc-angel"
    )
    assert oo_proposal["intentKind"] == "WAIT"
    assert oo_proposal["influencedByMemoryIds"] == [
        counsel_memories[0].memory_id
    ]
    owner_room = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo"
    ).json()
    assert "主人" in owner_room["decisionBasisSummary"]
    assert owner_room["decisionMemoryRefs"] == [
        counsel_memories[0].memory_id
    ]
    latest_memory_store = LivingMemoryStoreDTO.model_validate(
        storage.get_living_world_view(ready["runId"], "memory")
    )
    assert any(
        memory.memory_id == counsel_memories[0].memory_id
        for memory in latest_memory_store.memories["oc-angel"]
    )

    cross_owner = api.post(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-cc/counsel",
        json={
            "experienceRef": experience_ref,
            "adviceId": "verify-before-judging",
        },
    )
    assert cross_owner.status_code == 404


def test_same_next_day_without_owner_counsel_keeps_the_oc_own_plan(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "no-owner-counsel.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    api.post(f"/api/living-world/runs/{ready['runId']}/advance")

    next_world = api.post(
        f"/api/living-world/runs/{ready['runId']}/advance"
    ).json()
    oo = next(
        resident
        for resident in next_world["residents"]
        if resident["residentId"] == "resident-oo"
    )

    assert oo["currentLocationId"] == "apartment-bar"


def test_room_projection_is_owner_safe_and_never_embeds_private_os(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "room-projection.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    world = api.post(
        f"/api/living-world/runs/{ready['runId']}/advance"
    ).json()
    resident = next(
        item
        for item in world["residents"]
        if item["actorId"] == "oc-angel"
    )

    response = api.get(
        f"/api/living-world/runs/{world['runId']}/owner/rooms/"
        f"{resident['residentId']}"
    )

    assert response.status_code == 200
    room = response.json()
    assert RoomProjectionDTO.model_validate(room)
    assert room["runId"] == world["runId"]
    assert room["worldVersion"] == world["worldVersion"]
    assert room["residentId"] == resident["residentId"]
    assert room["roomId"] == resident["roomId"]
    assert room["latestDiary"]["available"] is True
    assert room["privateOsAvailable"] is True
    assert room["privateOsRef"]
    assert room["capabilities"]["privateOs"] is True
    assert room["relationshipSummaries"]
    assert room["recentExperienceRefs"]
    assert _forbidden_keys(room) == set()
    serialized = json.dumps(room, ensure_ascii=False)
    assert "I am carrying" not in serialized
    assert "issuerSignature" not in serialized
    assert "proposal" not in serialized


def test_owner_room_dialogue_uses_only_that_oc_memories(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "owner-dialogue.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    api.post(f"/api/living-world/runs/{ready['runId']}/advance")
    memory_store = LivingMemoryStoreDTO.model_validate(
        storage.get_living_world_view(ready["runId"], "memory")
    )
    oo_memory_ids = {
        memory.memory_id
        for memory in memory_store.memories["oc-angel"]
    }
    other_only_memory_ids = {
        memory.memory_id
        for actor_id, memories in memory_store.memories.items()
        if actor_id != "oc-angel"
        for memory in memories
    } - oo_memory_ids

    response = api.post(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo/talk",
        json={"message": "今天在外面发生了什么？"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runId"] == ready["runId"]
    assert body["residentId"] == "resident-oo"
    assert body["actorId"] == "oc-angel"
    assert body["publicReply"]
    assert body["memoryRefsUsed"]
    assert set(body["memoryRefsUsed"]) <= oo_memory_ids
    assert set(body["memoryRefsUsed"]).isdisjoint(other_only_memory_ids)
    assert body["privateOsAvailable"] is True
    assert body["privateOsRef"]
    assert "privateInnerOs" not in body

    private_response = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo/private-os",
        params={"ref": body["privateOsRef"]},
    )
    assert private_response.status_code == 200
    private_os = private_response.json()
    assert OwnerPrivateOsDTO.model_validate(private_os)
    assert private_os["actorId"] == "oc-angel"
    assert private_os["residentId"] == "resident-oo"
    assert private_os["privateOsRef"] == body["privateOsRef"]
    assert private_os["text"]
    assert private_os["text"] != body["publicReply"]
    assert set(private_os["memoryRefsUsed"]) <= oo_memory_ids

    cc_room = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-cc"
    ).json()
    cross_resident = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo/private-os",
        params={"ref": cc_room["privateOsRef"]},
    )
    assert cross_resident.status_code == 404

    room = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo"
    ).json()
    assert room["capabilities"]["realtimeConversation"] is False


def test_runtime_private_os_is_owner_readable_but_never_in_canon(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "runtime-private-os.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    api.post(f"/api/living-world/runs/{ready['runId']}/advance")
    room = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo"
    ).json()

    response = api.get(
        f"/api/living-world/runs/{ready['runId']}/owner/rooms/"
        "resident-oo/private-os",
        params={"ref": room["privateOsRef"]},
    )

    assert response.status_code == 200
    private_os = response.json()
    assert private_os["actorId"] == "oc-angel"
    assert private_os["privateOsRef"] == room["privateOsRef"]
    assert private_os["text"]
    canonical_payload = json.dumps(
        [
            event["payload"]
            for event in storage.get_events(ready["runId"])
            if event["type"] == "canonical.event.committed"
        ],
        ensure_ascii=False,
    )
    assert private_os["text"] not in canonical_payload


def test_runtime_persists_actor_scoped_pov_memories(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "pov-memory.sqlite3")
    api = TestClient(create_app(storage))
    ready = create_product_run(api)
    api.post(f"/api/living-world/runs/{ready['runId']}/advance")

    memory_store = LivingMemoryStoreDTO.model_validate(
        storage.get_living_world_view(ready["runId"], "memory")
    )

    assert memory_store.day_index == 1
    assert set(memory_store.memories) == {
        "oc-user",
        "oc-angel",
        "oc-devil",
    }
    for actor_id, memories in memory_store.memories.items():
        assert memories
        assert all(memory.actor_id == actor_id for memory in memories)
        assert all(
            memory.kind == "prior"
            or memory.source_observation_ids
            for memory in memories
        )
    serialized = json.dumps(
        memory_store.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
    )
    assert "privateInnerOs" not in serialized


def test_proof_remains_a_separate_read_model(tmp_path: Path) -> None:
    storage = SQLiteStorage(tmp_path / "separate-proof.sqlite3")
    api = TestClient(create_app(storage))
    world = create_product_run(api)

    proof = api.get(
        f"/api/living-world/runs/{world['runId']}/proof"
    )

    assert proof.status_code == 200
    body = proof.json()
    assert body["schemaVersion"] == "0.2"
    assert body["proposals"]
    assert body["resolutionBatch"]["receipts"]
    assert body["replay"]["verified"] is True
    assert "proposals" not in world


def test_projection_schemas_and_examples_come_from_a_real_runtime(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    fixture_dir = root / "fixtures" / "living-world-v02"
    pairs = [
        (
            "world-projection.schema.json",
            "world-projection.example.json",
            WorldProjectionDTO,
        ),
        (
            "room-projection.schema.json",
            "room-projection.example.json",
            RoomProjectionDTO,
        ),
        (
            "owner-room-dialogue.schema.json",
            "owner-room-dialogue.example.json",
            OwnerRoomDialogueDTO,
        ),
        (
            "owner-private-os.schema.json",
            "owner-private-os.example.json",
            OwnerPrivateOsDTO,
        ),
    ]
    for schema_name, example_name, model in pairs:
        schema = json.loads(
            (fixture_dir / schema_name).read_text(encoding="utf-8")
        )
        example = json.loads(
            (fixture_dir / example_name).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(example)
        model.model_validate(example)

    storage = SQLiteStorage(tmp_path / "fixture-runtime.sqlite3")
    TransactionalLivingWorldRuntime(
        storage,
        load_preset_runtime_bundle(),
    ).create_and_run(
        session_id="fixture-product-v02",
        seed="kaleidoroom-product-projection-v02",
    )
    assert storage.get_living_world_view(
        "fixture-product-v02",
        "world",
    ) == json.loads(
        (fixture_dir / "world-projection.example.json").read_text(
            encoding="utf-8"
        )
    )
    assert storage.get_living_world_view(
        "fixture-product-v02",
        "room:resident-oo",
    ) == json.loads(
        (fixture_dir / "room-projection.example.json").read_text(
            encoding="utf-8"
        )
    )

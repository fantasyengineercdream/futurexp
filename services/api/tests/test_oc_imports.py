from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import SQLiteStorage


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(SQLiteStorage(tmp_path / "bring-your-oc.sqlite3")))


def _preview(api: TestClient) -> dict:
    response = api.post(
        "/api/oc-imports/preview",
        json={
            "sourceName": "lan.md",
            "sourceText": (
                "岚\n"
                "她会先核对证据，再保护被遗忘的名字。\n"
                "说话简短，但不会替别人做决定。"
            ),
        },
    )
    assert response.status_code == 201
    return response.json()


def _confirmation_from(draft: dict) -> dict:
    return {
        "roleplayConfig": draft["roleplayConfig"],
        "livingWorldProfile": draft["livingWorldProfile"],
        "rpgStats": draft["rpgStats"],
    }


def test_preview_uses_creator_source_but_does_not_register(tmp_path: Path) -> None:
    api = _client(tmp_path)

    draft = _preview(api)

    assert draft["status"] == "pendingConfirmation"
    assert draft["roleplayConfig"]["displayName"] == "岚"
    assert "核对证据" in draft["roleplayConfig"]["persona"]
    assert len(draft["source"]["contentHash"]) == 64
    assert draft["source"]["sourceName"] == "lan.md"
    assert draft["canonical"] is False
    assert draft["auditNotices"]

    missing = api.get(f"/api/ocs/{draft['suggestedOcId']}")
    assert missing.status_code == 404


def test_confirmation_registers_the_users_edited_profile(tmp_path: Path) -> None:
    api = _client(tmp_path)
    draft = _preview(api)
    confirmation = _confirmation_from(draft)
    confirmation["roleplayConfig"]["publicStyle"] = "只说自己确认过的事"
    confirmation["livingWorldProfile"]["goals"] = ["查明走廊回声的来源"]
    confirmation["rpgStats"]["insight"] = 5

    response = api.post(
        f"/api/oc-imports/{draft['draftId']}/confirm",
        json=confirmation,
    )

    assert response.status_code == 201
    registered = response.json()
    assert registered["status"] == "registered"
    assert registered["ocId"] == draft["suggestedOcId"]
    assert registered["character"]["publicStyle"] == "只说自己确认过的事"
    assert registered["character"]["goals"][0]["text"] == "查明走廊回声的来源"
    assert registered["runtimeProfile"]["rpgStats"]["insight"] == 5
    assert registered["source"]["contentHash"] == draft["source"]["contentHash"]

    fetched = api.get(f"/api/ocs/{registered['ocId']}")
    assert fetched.status_code == 200
    assert fetched.json() == registered


def test_unknown_draft_cannot_be_confirmed(tmp_path: Path) -> None:
    api = _client(tmp_path)

    response = api.post(
        "/api/oc-imports/missing-draft/confirm",
        json={
            "roleplayConfig": {
                "displayName": "岚",
                "role": "住客",
                "persona": "谨慎",
                "publicStyle": "简短",
            },
            "livingWorldProfile": {
                "personaConstraints": ["先核对证据"],
                "goals": ["找到线索"],
                "initialMemories": [],
                "homeLocationId": "mirror-curtain",
                "dailyLocationPreferences": ["apartment-library"],
            },
            "rpgStats": {
                "intellect": 1,
                "athletics": 1,
                "insight": 2,
                "presence": 1,
            },
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "OC_IMPORT_NOT_FOUND"


def test_blank_creator_source_is_rejected(tmp_path: Path) -> None:
    api = _client(tmp_path)

    response = api.post(
        "/api/oc-imports/preview",
        json={"sourceName": "empty.md", "sourceText": " \n\t "},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_confirmation_rejects_a_profile_that_cannot_join_the_world(
    tmp_path: Path,
) -> None:
    api = _client(tmp_path)
    draft = _preview(api)
    confirmation = _confirmation_from(draft)
    confirmation["livingWorldProfile"]["homeLocationId"] = "invented-room"

    response = api.post(
        f"/api/oc-imports/{draft['draftId']}/confirm",
        json=confirmation,
    )

    assert response.status_code == 409
    assert response.json()["code"] == "DOMAIN_INVARIANT_VIOLATION"
    missing = api.get(f"/api/ocs/{draft['suggestedOcId']}")
    assert missing.status_code == 404


def test_registered_oc_joins_and_remains_in_the_day_loop(tmp_path: Path) -> None:
    api = _client(tmp_path)
    draft = _preview(api)
    registered = api.post(
        f"/api/oc-imports/{draft['draftId']}/confirm",
        json=_confirmation_from(draft),
    ).json()

    created = api.post(
        "/api/living-world/day-loop-runs",
        json={
            "seed": "bring-your-oc",
            "additionalOcIds": [registered["ocId"]],
        },
    )

    assert created.status_code == 201
    day_one = created.json()
    assert len(day_one["actors"]) == 4
    assert registered["ocId"] in {
        actor["actorId"] for actor in day_one["actors"]
    }
    assert registered["ocId"] in {
        item["actorId"] for item in day_one["memoryRefs"]
    }
    journal = api.get(
        (
            f"/api/living-world/day-loop-runs/{day_one['runId']}"
            f"/owner/actors/{registered['ocId']}/journal"
        )
    )
    assert journal.status_code == 200
    assert journal.json()["actorId"] == registered["ocId"]
    assert journal.json()["entries"][0]["episodeRef"] == (
        f"memory:day-1:{registered['ocId']}"
    )

    advanced = api.post(
        f"/api/living-world/day-loop-runs/{day_one['runId']}/advance"
    )

    assert advanced.status_code == 200
    day_two = advanced.json()
    assert day_two["dayIndex"] == 2
    assert registered["ocId"] in {
        actor["actorId"] for actor in day_two["actors"]
    }
    assert registered["ocId"] in {
        item["actorId"] for item in day_two["memoryRefs"]
    }


def test_confirmed_oc_can_fill_the_demo_user_slot(tmp_path: Path) -> None:
    api = _client(tmp_path)
    draft = _preview(api)
    registered = api.post(
        f"/api/oc-imports/{draft['draftId']}/confirm",
        json=_confirmation_from(draft),
    ).json()

    response = api.post(
        "/api/living-world/day-loop-runs",
        json={
            "seed": "bring-your-oc-user-slot",
            "userOcId": registered["ocId"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    actors = {actor["actorId"]: actor for actor in body["actors"]}
    assert len(actors) == 3
    assert "oc-user" not in actors
    assert actors[registered["ocId"]]["displayName"] == "岚"
    assert registered["ocId"] in {
        item["actorId"] for item in body["memoryRefs"]
    }


def test_unknown_registered_oc_cannot_start_a_day_loop(tmp_path: Path) -> None:
    api = _client(tmp_path)

    response = api.post(
        "/api/living-world/day-loop-runs",
        json={"additionalOcIds": ["oc-not-registered"]},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "REGISTERED_OC_NOT_FOUND"

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.dto import OwnerSessionView, PassportView, ProofSessionView, WorldSessionView
from app.errors import DomainInvariantError, RuntimeExecutionError
from app.main import create_app
from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"
CONTRACT_PATH = ROOT / "contracts" / "runtime-event.schema.json"


def client(tmp_path: Path) -> TestClient:
    app = create_app(SQLiteStorage(tmp_path / "runtime.sqlite3"))
    return TestClient(app)


def create_session(api: TestClient, *, consent_required: bool = True) -> dict:
    response = api.post(
        "/api/demo/sessions",
        json={"consentRequired": consent_required},
    )
    assert response.status_code == 201
    return response.json()


def test_create_session_returns_one_ordered_public_http_view(
    tmp_path: Path,
) -> None:
    api = client(tmp_path)

    view = create_session(api)

    assert view["worldId"] == "infinite-apartment"
    assert view["status"] == "completed"
    assert view["consentRequired"] is True
    assert [event["cursor"] for event in view["events"]] == sorted(
        event["cursor"] for event in view["events"]
    )
    assert {event["visibility"]["scope"] for event in view["events"]} == {"public"}
    serialized = json.dumps(view, ensure_ascii=False)
    assert "privateOs" not in serialized
    assert "secrets" not in serialized
    WorldSessionView.model_validate(view)


def test_world_view_exposes_only_the_resolved_give_objective_diff(
    tmp_path: Path,
) -> None:
    view = create_session(client(tmp_path))

    give = next(
        event
        for event in view["events"]
        if event["type"] == "canonical.event.committed"
        and event["payload"]["event"]["factCodes"]
        == ["key.transferred.voluntarily"]
    )
    assert give["cursor"] == 12
    assert give["visibility"] == {"scope": "public"}
    assert give["payload"]["event"]["effects"] == [
        {
            "op": "set",
            "path": "/objects/threshold-key/holderId",
            "before": "oc-user",
            "after": "oc-devil",
        }
    ]
    assert not {
        "proposal.character.created",
        "rule.decision.created",
        "observation.created",
        "belief.updated",
        "privateOs.created",
    }.intersection(event["type"] for event in view["events"])


def test_world_route_cannot_be_elevated_with_a_scope_query(
    tmp_path: Path,
) -> None:
    api = client(tmp_path)
    created = create_session(api)

    response = api.get(
        f"/api/demo/sessions/{created['sessionId']}/world?scope=tech"
    )

    assert response.status_code == 200
    view = response.json()
    assert {event["visibility"]["scope"] for event in view["events"]} == {"public"}
    assert "privateOs" not in json.dumps(view, ensure_ascii=False)
    assert view["world"]["name"] == "无限公寓"
    assert view["world"]["rules"][0]["params"]["consentRequired"] is True
    WorldSessionView.model_validate(view)


def test_owner_route_contains_user_private_os_but_not_tech_or_other_actor_events(
    tmp_path: Path,
) -> None:
    api = client(tmp_path)
    created = create_session(api)

    response = api.get(
        f"/api/demo/sessions/{created['sessionId']}/owner/oc-user"
    )

    assert response.status_code == 200
    view = response.json()
    assert any(event["type"] == "privateOs.created" for event in view["events"])
    assert all(
        event["visibility"]["scope"] != "tech" for event in view["events"]
    )
    assert all(
        event["visibility"].get("ocId", "oc-user") == "oc-user"
        for event in view["events"]
        if event["visibility"]["scope"] != "public"
    )
    assert view["oc"]["ocId"] == "oc-user"
    OwnerSessionView.model_validate(view)


def test_proof_route_returns_valid_contract_events_and_one_objective_state(
    tmp_path: Path,
) -> None:
    api = client(tmp_path)
    created = create_session(api)

    response = api.get(f"/api/demo/sessions/{created['sessionId']}/proof")

    assert response.status_code == 200
    proof = response.json()
    assert proof["objectiveState"]["objects"]["threshold-key"]["holderId"] == "oc-devil"
    assert proof["objectiveState"]["thresholdUnlocked"] is False
    assert proof["checksum"]

    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    event_schema = {
        "$schema": contract["$schema"],
        "$ref": "#/$defs/RuntimeEventEnvelope",
        "$defs": contract["$defs"],
    }
    validator = Draft202012Validator(event_schema)
    errors = [
        error.message
        for event in proof["events"]
        for error in validator.iter_errors(event)
    ]
    assert errors == []

    spoken = [
        event["payload"]["event"]
        for event in proof["events"]
        if event["type"] == "canonical.event.committed"
        and event["payload"]["event"]["kind"] == "utterance.spoken"
    ]
    assert spoken
    assert all(event["factCodes"] == ["utterance.spoken"] for event in spoken)
    ProofSessionView.model_validate(proof)


def test_public_passport_never_contains_private_material(tmp_path: Path) -> None:
    api = client(tmp_path)

    response = api.get("/api/public/passports/oc-user")

    assert response.status_code == 200
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert "privateOs" not in serialized
    assert "secrets" not in serialized
    assert "belief" not in serialized.lower()
    assert response.json()["worldId"] == "infinite-apartment"
    PassportView.model_validate(response.json())


def test_api_errors_use_one_error_dto(tmp_path: Path) -> None:
    api = client(tmp_path)

    missing = api.get("/api/demo/sessions/not-found/world")
    invalid = api.post(
        "/api/demo/sessions",
        json={"consentRequired": "definitely"},
    )

    assert missing.status_code == 404
    assert missing.json() == {
        "code": "SESSION_NOT_FOUND",
        "message": "Session not found.",
        "retryable": False,
    }
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("path", "error", "status_code", "expected"),
    [
        (
            "/test/runtime-error",
            RuntimeExecutionError("secret runtime details"),
            500,
            {
                "code": "RUNTIME_EXECUTION_FAILED",
                "message": "Runtime execution failed.",
                "retryable": True,
            },
        ),
        (
            "/test/domain-error",
            DomainInvariantError("secret invariant details"),
            409,
            {
                "code": "DOMAIN_INVARIANT_VIOLATION",
                "message": "Domain invariant violation.",
                "retryable": False,
            },
        ),
        (
            "/test/internal-error",
            ValueError("secret internal details"),
            500,
            {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error.",
                "retryable": True,
            },
        ),
    ],
)
def test_internal_exceptions_use_generic_error_dtos_without_leaking_details(
    tmp_path: Path,
    path: str,
    error: Exception,
    status_code: int,
    expected: dict,
) -> None:
    app = create_app(SQLiteStorage(tmp_path / "runtime.sqlite3"))

    @app.get(path)
    def raise_test_error() -> None:
        raise error

    response = TestClient(app, raise_server_exceptions=False).get(path)

    assert response.status_code == status_code
    assert response.json() == expected
    assert "secret" not in response.text.lower()


def test_create_session_forbids_extra_fields_and_scope_escalation(
    tmp_path: Path,
) -> None:
    api = client(tmp_path)

    response = api.post(
        "/api/demo/sessions",
        json={"consentRequired": True, "scope": "tech"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "INVALID_REQUEST",
        "message": "Request validation failed.",
        "retryable": False,
    }


def test_openapi_declares_explicit_scoped_response_models(tmp_path: Path) -> None:
    api = client(tmp_path)
    openapi = api.get("/openapi.json").json()
    paths = openapi["paths"]

    assert (
        paths["/api/demo/sessions"]["post"]["responses"]["201"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/WorldSessionView"
    )
    assert (
        paths["/api/demo/sessions/{session_id}/owner/oc-user"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/OwnerSessionView"
    )
    assert (
        paths["/api/demo/sessions/{session_id}/proof"]["get"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ProofSessionView"
    )
    assert (
        paths["/api/public/passports/oc-user"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/PassportView"
    )
    assert (
        paths["/api/demo/sessions"]["post"]["responses"]["409"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        == "#/components/schemas/ErrorDto"
    )
    for path, method in (
        ("/api/demo/sessions", "post"),
        ("/api/demo/sessions/{session_id}/world", "get"),
        ("/api/demo/sessions/{session_id}/owner/oc-user", "get"),
        ("/api/demo/sessions/{session_id}/proof", "get"),
        ("/api/public/passports/oc-user", "get"),
    ):
        assert (
            paths[path][method]["responses"]["500"]["content"][
                "application/json"
            ]["schema"]["$ref"]
            == "#/components/schemas/ErrorDto"
        )


def test_unrelated_key_error_is_not_mapped_to_session_not_found(
    tmp_path: Path,
) -> None:
    app = create_app(SQLiteStorage(tmp_path / "runtime.sqlite3"))

    @app.get("/test/key-error")
    def key_error():
        raise KeyError("programming bug")

    api = TestClient(app, raise_server_exceptions=False)
    response = api.get("/test/key-error")

    assert response.status_code == 500
    assert response.text != "Session not found."

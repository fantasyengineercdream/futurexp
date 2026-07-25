from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from app.shared_universe.contracts import (
    CapabilityGrantV1,
    CapabilityRevocationV1,
    CanonRevisionV1,
    CharacterPresenceV1,
    InvitationV1,
    OCIdentityV1,
    PortableMemorySummaryV1,
    ProjectionPolicyV1,
    SharedEventEnvelopeV1,
    WorldInstanceV1,
    adapt_legacy_visibility,
)


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "contracts" / "shared-universe.v1.schema.json"


def ids() -> dict[str, str]:
    return {
        name: str(uuid4())
        for name in (
            "oc",
            "canon",
            "world",
            "world_definition",
            "presence",
            "event",
            "principal",
            "memory",
            "grant",
            "revocation",
            "invitation",
            "operator",
        )
    }


def contract_examples() -> list[dict]:
    now = datetime.now(UTC)
    value = ids()
    identity = OCIdentityV1(
        schema_version="oc.identity/v1",
        oc_id=value["oc"],
        slug="mira",
        created_at=now,
        active_canon_revision_id=value["canon"],
    )
    canon = CanonRevisionV1(
        schema_version="oc.canon-revision/v1",
        canon_revision_id=value["canon"],
        oc_id=value["oc"],
        revision=1,
        display_name="Mira",
        public_profile={"voice": "quiet"},
        created_at=now,
    )
    world = WorldInstanceV1(
        schema_version="world.instance/v1",
        world_instance_id=value["world"],
        world_definition_id=value["world_definition"],
        world_definition_version="1.0.0",
        slug="glass-courtyard",
        created_at=now,
    )
    presence = CharacterPresenceV1(
        schema_version="character.presence/v1",
        presence_id=value["presence"],
        world_instance_id=value["world"],
        oc_id=value["oc"],
        canon_revision_id=value["canon"],
        status="admitted",
        runtime_state_ref=f"world://{value['world']}/presence/{value['presence']}",
        admitted_at=now,
    )
    invitation = InvitationV1(
        schema_version="invitation/v1",
        invitation_id=value["invitation"],
        world_instance_id=value["world"],
        oc_id=value["oc"],
        invited_by_principal_id=value["operator"],
        invited_principal_id=value["principal"],
        status="accepted",
        discovery_source="nfc",
        issued_at=now,
        expires_at=now + timedelta(minutes=10),
        accepted_at=now + timedelta(seconds=1),
    )
    grant = CapabilityGrantV1(
        schema_version="capability.grant/v1",
        grant_id=value["grant"],
        subject_principal_id=value["principal"],
        issuer_principal_id=value["operator"],
        world_instance_id=value["world"],
        invitation_id=value["invitation"],
        capabilities=["event:read"],
        policy_version=1,
        issued_at=now + timedelta(seconds=2),
        expires_at=now + timedelta(minutes=5),
    )
    revocation = CapabilityRevocationV1(
        schema_version="capability.revocation/v1",
        revocation_id=value["revocation"],
        grant_id=value["grant"],
        revoked_by_principal_id=value["operator"],
        reason="left world",
        revoked_at=now + timedelta(minutes=1),
    )
    policy = ProjectionPolicyV1(
        schema_version="projection.policy/v1",
        policy_version=1,
        sensitivity="member",
        data_class="world_observation",
        audience_selector={"kind": "world_members"},
        grant_refs=[],
    )
    event = SharedEventEnvelopeV1(
        schema_version="shared.event/v1",
        event_id=value["event"],
        world_instance_id=value["world"],
        sequence=1,
        occurred_at=now,
        type="world.observation.created",
        subject_oc_id=value["oc"],
        projection_policy=policy,
        capability_version="1",
        idempotency_key="world-event-1",
        cancellation_key="tick-1",
        payload={"summary": "Mira heard a bell."},
    )
    memory = PortableMemorySummaryV1(
        schema_version="portable-memory.summary/v1",
        memory_summary_id=value["memory"],
        oc_id=value["oc"],
        source_world_instance_id=value["world"],
        source_event_ids=[value["event"]],
        summary="Mira remembers hearing a bell.",
        approved_by_principal_id=value["principal"],
        created_at=now + timedelta(seconds=1),
    )
    return [
        model.model_dump(by_alias=True, mode="json", exclude_none=True)
        for model in (
            identity,
            canon,
            world,
            presence,
            invitation,
            grant,
            revocation,
            policy,
            event,
            memory,
        )
    ]


def test_versioned_contract_examples_validate_against_json_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    for example in contract_examples():
        assert list(validator.iter_errors(example)) == []


def test_ids_are_opaque_uuids_and_slug_is_display_only() -> None:
    payload = contract_examples()[0]
    payload["ocId"] = "owner-mira"

    with pytest.raises(ValidationError):
        OCIdentityV1.model_validate(payload)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = list(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    assert errors


@pytest.mark.parametrize(
    "leaked_field",
    ["inventory", "relationships", "injuries", "worldSecrets"],
)
def test_world_scoped_state_cannot_be_written_to_global_identity(
    leaked_field: str,
) -> None:
    payload = contract_examples()[0]
    payload[leaked_field] = {}

    with pytest.raises(ValidationError):
        OCIdentityV1.model_validate(payload)


def test_v2_projection_policy_carries_evolvable_dimensions() -> None:
    grant_id = str(uuid4())
    policy = ProjectionPolicyV1.model_validate(
        {
            "schemaVersion": "projection.policy/v1",
            "policyVersion": 3,
            "sensitivity": "confidential",
            "dataClass": "world_observation",
            "audienceSelector": {
                "kind": "capability_holders",
                "capability": "event:read",
            },
            "grantRefs": [grant_id],
        }
    )

    assert policy.policy_version == 3
    assert policy.grant_refs == [grant_id]
    assert policy.audience_selector.kind == "capability_holders"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schemaVersion": "projection.policy/v1",
            "policyVersion": 1,
            "sensitivity": "restricted",
            "dataClass": "operator_diagnostic",
            "audienceSelector": {"kind": "public"},
            "grantRefs": [],
        },
        {
            "schemaVersion": "projection.policy/v1",
            "policyVersion": 1,
            "sensitivity": "private",
            "dataClass": "private_os",
            "audienceSelector": {"kind": "principals", "principalIds": [str(uuid4())]},
            "grantRefs": [],
        },
    ],
)
def test_projection_policy_rejects_leaky_cross_field_combinations(
    payload: dict,
) -> None:
    with pytest.raises(ValidationError):
        ProjectionPolicyV1.model_validate(payload)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(payload))


@pytest.mark.parametrize(
    ("legacy", "sensitivity", "audience_kind"),
    [
        ({"scope": "public"}, "public", "legacy_demo"),
        ({"scope": "owner", "ocId": "oc-user"}, "private", "legacy_demo"),
        ({"scope": "actor", "ocId": "oc-angel"}, "private", "legacy_demo"),
        ({"scope": "tech"}, "restricted", "legacy_demo"),
    ],
)
def test_legacy_demo_visibility_adapts_without_changing_v1_runtime(
    legacy: dict,
    sensitivity: str,
    audience_kind: str,
) -> None:
    policy = adapt_legacy_visibility(legacy)

    assert policy.sensitivity == sensitivity
    assert policy.audience_selector.kind == audience_kind
    assert policy.compatibility_mode == "demo-v1"


def test_portable_memory_is_a_summary_not_raw_world_state() -> None:
    payload = contract_examples()[-1]
    payload["rawWorldState"] = {"inventory": ["master-key"]}

    with pytest.raises(ValidationError):
        PortableMemorySummaryV1.model_validate(payload)


def test_shared_event_payload_is_not_mutated_during_validation() -> None:
    payload = contract_examples()[-2]
    original = deepcopy(payload)

    SharedEventEnvelopeV1.model_validate(payload)

    assert payload == original

from __future__ import annotations

import json
import re
from pathlib import Path

from copy import deepcopy

from jsonschema import Draft202012Validator

from app.contract_validation import STRICT_FORMAT_CHECKER
from app.dto import OwnerSessionView, PassportView, ProofSessionView, WorldSessionView
from app.domain.models import CanonicalEvent, WorldDefinition
from app.domain.reducer import canonical_state_checksum, reduce_canonical_events


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "contracts" / "runtime-event.schema.json"
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"
CONSENT_ON_PATH = (
    ROOT / "fixtures" / "infinite-apartment" / "demo-session-consent-on.json"
)
CONSENT_OFF_PATH = (
    ROOT / "fixtures" / "infinite-apartment" / "demo-session-consent-off.json"
)
VIEW_PATHS = {
    WorldSessionView: [
        ROOT
        / "fixtures"
        / "infinite-apartment"
        / "views"
        / "consent-on-world.json",
        ROOT
        / "fixtures"
        / "infinite-apartment"
        / "views"
        / "consent-off-world.json",
    ],
    OwnerSessionView: [
        ROOT
        / "fixtures"
        / "infinite-apartment"
        / "views"
        / "consent-on-owner.json",
        ROOT
        / "fixtures"
        / "infinite-apartment"
        / "views"
        / "consent-off-owner.json",
    ],
    ProofSessionView: [
        ROOT
        / "fixtures"
        / "infinite-apartment"
        / "views"
        / "consent-on-proof.json",
        ROOT
        / "fixtures"
        / "infinite-apartment"
        / "views"
        / "consent-off-proof.json",
    ],
    PassportView: [
        ROOT / "fixtures" / "infinite-apartment" / "views" / "passport.json"
    ],
}

EXPECTED_EVENT_TYPES = {
    "session.snapshot",
    "tick.started",
    "proposal.character.created",
    "proposal.dm.created",
    "proposal.utterance.created",
    "rule.decision.created",
    "canonical.event.committed",
    "observation.created",
    "belief.updated",
    "utterance.created",
    "privateOs.created",
    "tick.completed",
    "session.completed",
    "runtime.error",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_schema_and_infinite_apartment_fixtures_validate() -> None:
    schema = load_json(CONTRACT_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(
        schema,
        format_checker=STRICT_FORMAT_CHECKER,
    )

    for fixture_path in (WORLD_PATH, CONSENT_ON_PATH, CONSENT_OFF_PATH):
        errors = sorted(
            validator.iter_errors(load_json(fixture_path)),
            key=lambda error: list(error.absolute_path),
        )
        assert errors == [], "\n".join(error.message for error in errors)


def test_runtime_event_union_is_frozen() -> None:
    schema = load_json(CONTRACT_PATH)
    event_types = set(schema["$defs"]["RuntimeEventType"]["enum"])
    assert event_types == EXPECTED_EVENT_TYPES


def test_demo_fixture_is_three_ticks_in_the_infinite_apartment() -> None:
    world = load_json(WORLD_PATH)

    assert world["worldId"] == "infinite-apartment"
    for session_path in (CONSENT_ON_PATH, CONSENT_OFF_PATH):
        session = load_json(session_path)
        assert session["worldId"] == "infinite-apartment"
        assert session["participantIds"] == ["oc-user", "oc-angel", "oc-devil"]
        assert sorted({event["tickIndex"] for event in session["events"]}) == [
            0,
            1,
            2,
        ]

    serialized = json.dumps(
        [world, load_json(CONSENT_ON_PATH), load_json(CONSENT_OFF_PATH)],
        ensure_ascii=False,
    ).lower()
    assert "小镇" not in serialized
    assert "smallville" not in serialized
    assert "town" not in serialized


def test_public_events_never_contain_private_os() -> None:
    session = load_json(CONSENT_ON_PATH)

    for event in session["events"]:
        if event["visibility"]["scope"] == "public":
            assert event["type"] != "privateOs.created"
            assert "privateOs" not in json.dumps(event["payload"], ensure_ascii=False)


def test_give_canonical_is_the_only_new_public_second_tick_detail() -> None:
    session = load_json(CONSENT_ON_PATH)
    give = next(
        event
        for event in session["events"]
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

    give_proposal = session["events"][9]
    give_decision = session["events"][10]
    assert give_proposal["type"] == "proposal.character.created"
    assert give_proposal["visibility"] == {"scope": "tech"}
    assert give_decision["type"] == "rule.decision.created"
    assert give_decision["visibility"] == {"scope": "tech"}
    assert all(
        event["visibility"]["scope"] in {"owner", "actor"}
        for event in session["events"]
        if event["type"] in {
            "observation.created",
            "belief.updated",
            "privateOs.created",
        }
    )


def test_consent_on_and_off_fixtures_have_deterministic_opposite_take_results() -> None:
    consent_on = load_json(CONSENT_ON_PATH)
    consent_off = load_json(CONSENT_OFF_PATH)

    def take_outcome(session: dict) -> str:
        for event in session["events"]:
            if event["type"] != "rule.decision.created":
                continue
            decision = event["payload"]["decision"]
            if decision["proposalId"].endswith("take-key"):
                return decision["outcome"]
        raise AssertionError("TAKE decision missing")

    assert consent_on["consentRequired"] is True
    assert consent_off["consentRequired"] is False
    assert take_outcome(consent_on) == "blocked"
    assert take_outcome(consent_off) == "success"


def test_utterance_becomes_fact_only_after_proposal_and_rule_decision() -> None:
    for session_path in (CONSENT_ON_PATH, CONSENT_OFF_PATH):
        session = load_json(session_path)
        ordered_types = [event["type"] for event in session["events"]]

        belief_index = ordered_types.index("belief.updated")
        proposal_index = ordered_types.index("proposal.utterance.created")
        decision_index = next(
            index
            for index, event in enumerate(session["events"])
            if event["type"] == "rule.decision.created"
            and event["payload"]["decision"]["proposalId"].endswith(
                "angel-utterance"
            )
        )
        canonical_index = next(
            index
            for index, event in enumerate(session["events"])
            if event["type"] == "canonical.event.committed"
            and event["payload"]["event"]["kind"] == "utterance.spoken"
        )

        assert belief_index < proposal_index < decision_index < canonical_index


def test_all_fixture_checksums_are_real_lowercase_sha256() -> None:
    checksum_pattern = re.compile(r"^[0-9a-f]{64}$")
    schema = load_json(CONTRACT_PATH)
    assert (
        schema["$defs"]["Checksum"]["pattern"]
        == "^[0-9a-f]{64}$"
    )

    for session_path in (CONSENT_ON_PATH, CONSENT_OFF_PATH):
        session = load_json(session_path)
        checksums = [
            event["payload"]["checksum"]
            for event in session["events"]
            if event["type"] in {"tick.completed", "session.completed"}
        ]
        assert checksums
        assert all(checksum_pattern.fullmatch(checksum) for checksum in checksums)


def test_scoped_transport_fixtures_match_the_http_response_dtos() -> None:
    schema = load_json(CONTRACT_PATH)
    validator = Draft202012Validator(schema)
    for response_model, paths in VIEW_PATHS.items():
        for path in paths:
            payload = load_json(path)
            response_model.model_validate(payload)
            errors = list(validator.iter_errors(payload))
            assert errors == [], "\n".join(error.message for error in errors)


def test_fixture_checksums_match_canonical_only_reduction() -> None:
    world = WorldDefinition.model_validate(load_json(WORLD_PATH))
    for session_path in (CONSENT_ON_PATH, CONSENT_OFF_PATH):
        session = load_json(session_path)
        canonical_events: list[CanonicalEvent] = []
        for envelope in session["events"]:
            if envelope["type"] == "canonical.event.committed":
                canonical_events.append(
                    CanonicalEvent.model_validate(envelope["payload"]["event"])
                )
            if envelope["type"] not in {"tick.completed", "session.completed"}:
                continue
            state = reduce_canonical_events(world.initial_state, canonical_events)
            assert (
                envelope["payload"]["checksum"]
                == canonical_state_checksum(state)
            )


def test_schema_rejects_invalid_date_time_and_unknown_oc_recipient() -> None:
    schema = load_json(CONTRACT_PATH)
    event_schema = {
        "$schema": schema["$schema"],
        "$ref": "#/$defs/RuntimeEventEnvelope",
        "$defs": schema["$defs"],
    }
    validator = Draft202012Validator(
        event_schema,
        format_checker=STRICT_FORMAT_CHECKER,
    )
    session = load_json(CONSENT_ON_PATH)
    invalid_date = deepcopy(session["events"][0])
    invalid_date["emittedAt"] = "not-a-date"
    give_event = next(
        deepcopy(event)
        for event in session["events"]
        if event["type"] == "proposal.character.created"
        and event["payload"]["proposal"]["action"]["kind"] == "GIVE"
    )
    give_event["payload"]["proposal"]["action"]["recipientId"] = "oc-ghost"

    assert list(validator.iter_errors(invalid_date))
    assert list(validator.iter_errors(give_event))

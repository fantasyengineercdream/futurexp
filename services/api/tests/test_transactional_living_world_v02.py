from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.domain.living_world import (
    ActorPolicyContext,
    ActorPolicyProvider,
    DeterministicSceneDirector,
    StructuredActorTurn,
    load_preset_runtime_bundle,
)
from app.domain.models import CanonicalEvent, StateEffect
from app.domain.transactional_living_world import (
    AtomicBatchCommitter,
    LivingWorldProofDTO,
    ReplayAuditor,
    TransactionalLivingWorldCore,
)
from app.main import create_app
from app.runtime import TransactionalLivingWorldRuntime
from app.storage import SQLiteStorage


class UnavailableProvider(ActorPolicyProvider):
    provider_id = "unavailable-v02-test-provider"

    def propose_turn(self, context: ActorPolicyContext) -> StructuredActorTurn:
        raise ConnectionError("model endpoint unavailable")


def run_proof(
    tmp_path: Path,
    *,
    session_id: str = "transactional-v02",
    seed: str = "transactional-proof-seed",
    provider: ActorPolicyProvider | None = None,
    reverse_profiles: bool = False,
):
    bundle = load_preset_runtime_bundle()
    if reverse_profiles:
        bundle = bundle.model_copy(
            update={"actor_profiles": list(reversed(bundle.actor_profiles))}
        )
    storage = SQLiteStorage(tmp_path / f"{session_id}.sqlite3")
    proof = TransactionalLivingWorldRuntime(
        storage,
        bundle,
        actor_provider=provider,
        director=DeterministicSceneDirector(adventure_published=True),
    ).create_and_run(session_id=session_id, seed=seed)
    return storage, proof


def test_three_proposals_share_one_snapshot_and_are_order_independent(
    tmp_path: Path,
) -> None:
    _, normal = run_proof(tmp_path, session_id="normal-order")
    _, reversed_order = run_proof(
        tmp_path,
        session_id="reverse-order",
        reverse_profiles=True,
    )

    assert len(normal.proposals) == 3
    assert {
        proposal.based_on_world_version for proposal in normal.proposals
    } == {normal.snapshot.world_version}
    assert all(
        "None" not in proposal.intent_label
        for proposal in normal.proposals
    )
    assert normal.commit.after_hash == reversed_order.commit.after_hash
    assert normal.replay.actual_final_hash == (
        reversed_order.replay.actual_final_hash
    )


def test_conflict_is_rule_resolved_then_committed_as_one_atomic_fact(
    tmp_path: Path,
) -> None:
    storage, proof = run_proof(tmp_path)

    assert proof.conflict_sets
    assert any(
        set(conflict.proposal_ids)
        == {
            "transactional-v02:round-0:oc-angel:proposal",
            "transactional-v02:round-0:oc-devil:proposal",
        }
        for conflict in proof.conflict_sets
    )
    assert proof.resolution_batch.atomic is True
    assert {
        receipt.status for receipt in proof.resolution_batch.receipts
    } <= {"applied", "rejected"}
    assert all(
        receipt.rule_id
        and receipt.rule_label
        and receipt.deterministic_evidence
        for receipt in proof.resolution_batch.receipts
    )
    assert proof.commit.atomic is True
    assert proof.commit.rolled_back is False
    assert proof.commit.from_version == proof.snapshot.world_version
    assert proof.commit.to_version == proof.snapshot.world_version + 1
    assert proof.commit.before_hash == proof.snapshot.world_hash
    assert proof.commit.before_hash != proof.commit.after_hash

    committed = [
        envelope
        for envelope in storage.get_events(proof.session_id)
        if envelope["type"] == "canonical.event.committed"
    ]
    assert len(committed) == 2
    assert committed[0]["payload"]["event"]["canonicalEventId"] == (
        proof.commit.canonical_event_id
    )
    assert committed[0]["payload"]["worldVersion"] == proof.commit.to_version


def test_same_fact_yields_observed_misunderstood_and_unknown_without_os_leak(
    tmp_path: Path,
) -> None:
    storage, proof = run_proof(tmp_path)
    perspectives = {
        perspective.actor_id: perspective
        for perspective in proof.perspectives
    }

    assert {
        perspective.knowledge_state
        for perspective in perspectives.values()
    } == {"observed", "misunderstood", "unknown"}
    assert all(
        perspective.observed_fact_ids or perspective.unknown_fact_ids
        for perspective in perspectives.values()
    )
    assert all(
        perspective.private_os_available
        and perspective.private_os_ref
        and perspective.private_inner_os is None
        for perspective in perspectives.values()
    )
    canonical_payloads = [
        envelope["payload"]
        for envelope in storage.get_events(proof.session_id)
        if envelope["type"] == "canonical.event.committed"
    ]
    assert "privateInnerOs" not in json.dumps(canonical_payloads)
    assert "privateOsRef" not in json.dumps(canonical_payloads)


def test_memory_and_relationship_fallout_explain_the_next_round(
    tmp_path: Path,
) -> None:
    _, proof = run_proof(tmp_path)

    assert proof.persistence.memory_deltas
    assert proof.persistence.relationship_deltas
    evidence = proof.persistence.next_round_evidence
    assert evidence.previous_proposal_id
    assert evidence.next_proposal_id
    assert evidence.previous_proposal_id != evidence.next_proposal_id
    assert evidence.changed_because_memory_ids
    assert set(evidence.changed_because_memory_ids) <= {
        delta.memory_id for delta in proof.persistence.memory_deltas
    }
    resisted_memories = {
        delta.memory_id
        for delta in proof.persistence.memory_deltas
        if delta.actor_id == evidence.actor_id
        and "object.resisted.take" in delta.summary
    }
    assert set(evidence.changed_because_memory_ids) == resisted_memories


def test_replay_is_a_real_audit_and_model_failure_uses_fallback(
    tmp_path: Path,
) -> None:
    _, proof = run_proof(
        tmp_path,
        provider=UnavailableProvider(),
    )

    assert proof.provider_fallback_count == 6
    assert proof.replay.verified is True
    assert proof.replay.expected_final_hash == proof.replay.actual_final_hash
    assert proof.replay.last_canonical_sequence == 2
    tampered = ReplayAuditor().compare_hashes(
        seed=proof.seed,
        expected_final_hash=proof.replay.expected_final_hash,
        actual_final_hash="0" * 64,
        last_canonical_sequence=2,
    )
    assert tampered.verified is False


def test_invalid_transition_rolls_back_the_whole_batch() -> None:
    bundle = load_preset_runtime_bundle()
    before = bundle.world.initial_state.model_copy(deep=True)
    invalid_batch_event = CanonicalEvent(
        canonical_event_id="invalid-batch",
        sequence=1,
        kind="action.resolved",
        decision_id="invalid-batch-decision",
        fact_codes=["batch.invalid"],
        effects=[
            StateEffect(
                op="set",
                path="/actorLocations/oc-user",
                before="mirror-curtain",
                after="adventure-instance-01",
            ),
            StateEffect(
                op="set",
                path="/actorLocations/oc-devil",
                before="not-the-current-location",
                after="adventure-instance-01",
            ),
        ],
        perceptual_atoms=[],
    )

    committer = AtomicBatchCommitter(bundle.world)
    with pytest.raises(
        TypeError,
        match="BatchAdjudication",
    ):
        committer.commit(before, invalid_batch_event)
    valid_adjudication = TransactionalLivingWorldCore(bundle).run(
        run_id="rollback-proof",
        seed="rollback-proof-seed",
    ).rounds[0].adjudication
    invalid_adjudication = valid_adjudication.model_copy(deep=True)
    invalid_adjudication.canonical_event.effects = (
        invalid_batch_event.effects
    )
    rollback = committer.try_commit(
        run_id="rollback-proof",
        round_index=0,
        state=before,
        adjudication=invalid_adjudication,
    )

    assert before.world_version == 0
    assert before.actor_locations["oc-user"] == "mirror-curtain"
    assert before.actor_locations["oc-devil"] == "mirror-curtain"
    assert rollback.state == before
    assert rollback.commit.atomic is True
    assert rollback.commit.rolled_back is True
    assert rollback.commit.failure_reason
    assert rollback.commit.canonical_event_id is None
    assert rollback.commit.before_hash == rollback.commit.after_hash
    assert rollback.commit.from_version == rollback.commit.to_version


@pytest.mark.parametrize("actor_count", [1, 2, 3])
def test_proof_projection_supports_one_to_three_active_actors(
    tmp_path: Path,
    actor_count: int,
) -> None:
    bundle = load_preset_runtime_bundle()
    selected_profiles = sorted(
        bundle.actor_profiles,
        key=lambda profile: profile.oc_id,
    )[:actor_count]
    bundle = bundle.model_copy(
        update={"actor_profiles": selected_profiles}
    )
    proof = TransactionalLivingWorldRuntime(
        SQLiteStorage(tmp_path / f"{actor_count}-actors.sqlite3"),
        bundle,
    ).create_and_run(
        session_id=f"{actor_count}-actors",
        seed="actor-count-proof",
    )

    assert len(proof.actors) == actor_count
    assert len(proof.resident_presence) == actor_count
    assert len(proof.proposals) == actor_count
    assert len(proof.perspectives) == actor_count


def test_proof_api_returns_one_frontend_playable_dto(tmp_path: Path) -> None:
    api = TestClient(
        create_app(SQLiteStorage(tmp_path / "proof-api.sqlite3"))
    )

    response = api.post(
        "/api/living-world/proof-runs",
        json={"seed": "frontend-proof-seed"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["schemaVersion"] == "0.2"
    assert len(body["residentPresence"]) == 3
    assert {actor["actorId"] for actor in body["actors"]} == {
        "oc-user",
        "oc-angel",
        "oc-devil",
    }
    assert all(actor["displayName"] for actor in body["actors"])
    assert {
        "snapshot",
        "proposals",
        "conflictSets",
        "resolutionBatch",
        "commit",
        "perspectives",
        "persistence",
        "replay",
    } <= body.keys()


def test_checked_in_schema_and_example_are_generated_from_the_real_runtime(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[3]
    fixture_dir = root / "fixtures" / "living-world-v02"
    schema = json.loads(
        (fixture_dir / "living-world-proof.schema.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (fixture_dir / "living-world-proof.example.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(schema).validate(example)
    validated = LivingWorldProofDTO.model_validate(example)
    _, generated = run_proof(
        tmp_path,
        session_id="fixture-transactional-v02",
        seed="kaleidoroom-transactional-v02-proof",
    )
    assert validated.model_dump(mode="json", by_alias=True) == (
        generated.model_dump(mode="json", by_alias=True)
    )

from __future__ import annotations

from pathlib import Path

import pytest

from app.domain.models import CharacterProposal, WorldDefinition
from app.domain.rules import RuleKernel
from app.errors import DomainInvariantError
from app.runtime import _RunContext
from app.storage import SQLiteStorage


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def load_world() -> WorldDefinition:
    return WorldDefinition.model_validate_json(WORLD_PATH.read_text(encoding="utf-8"))


def make_run(tmp_path: Path) -> tuple[_RunContext, CharacterProposal]:
    storage = SQLiteStorage(tmp_path / "receipts.sqlite3")
    world = load_world()
    state = world.initial_state.model_copy(deep=True)
    state.status = "running"
    storage.create_session(
        session_id="session-receipt",
        world_id=world.world_id,
        seed=world.event_seed,
        consent_required=True,
        state=state.model_dump(by_alias=True),
    )
    proposal = CharacterProposal.model_validate(
        {
            "proposalId": "proposal-receipt",
            "actorId": "oc-devil",
            "action": {"kind": "TAKE", "objectId": "threshold-key"},
            "motivationRefs": ["goal-devil-open-door"],
        }
    )
    return _RunContext(storage, world, state, "session-receipt"), proposal


def test_commit_resolution_rejects_tampered_effects(tmp_path: Path) -> None:
    run, proposal = make_run(tmp_path)
    kernel = run.rule_kernel()
    run.register_proposal(proposal)
    resolution = kernel.resolve_character(
        proposal,
        run.state,
        sequence=run.next_canonical_sequence,
        decision_id="decision-receipt",
        canonical_event_id="canonical-receipt",
    )
    assert resolution.event is not None
    resolution.event.effects.append(
        {
            "op": "set",
            "path": "/thresholdUnlocked",
            "before": False,
            "after": True,
        }
    )

    with pytest.raises(DomainInvariantError, match="receipt"):
        run.commit_resolution(resolution, visibility={"scope": "public"})

    assert run.last_canonical_sequence == 0
    assert run.state.threshold_unlocked is False


def test_commit_resolution_requires_a_registered_proposal(tmp_path: Path) -> None:
    run, proposal = make_run(tmp_path)
    kernel = run.rule_kernel()
    resolution = kernel.resolve_character(
        proposal,
        run.state,
        sequence=run.next_canonical_sequence,
        decision_id="decision-receipt",
        canonical_event_id="canonical-receipt",
    )

    with pytest.raises(DomainInvariantError, match="registered proposal"):
        run.commit_resolution(resolution, visibility={"scope": "public"})


def test_commit_returns_the_receipt_that_authorized_the_canonical_event(
    tmp_path: Path,
) -> None:
    run, proposal = make_run(tmp_path)
    kernel = run.rule_kernel()
    run.register_proposal(proposal)
    resolution = kernel.resolve_character(
        proposal,
        run.state,
        sequence=run.next_canonical_sequence,
        decision_id="decision-receipt",
        canonical_event_id="canonical-receipt",
    )

    committed_receipt = run.commit_resolution(
        resolution,
        visibility={"scope": "public"},
    )

    committed = next(
        event
        for event in run.storage.get_events("session-receipt")
        if event["type"] == "canonical.event.committed"
    )
    assert committed["causationId"] == committed_receipt.decision_id
    assert committed_receipt.proposal_id == proposal.proposal_id
    assert committed_receipt.input_world_version == 0
    assert committed_receipt.matched_rule_ids == resolution.decision.matched_rule_ids
    assert (
        committed_receipt.effects_fingerprint
        == resolution.receipt.effects_fingerprint
    )


def test_commit_rejects_a_receipt_from_an_unbound_kernel(tmp_path: Path) -> None:
    run, proposal = make_run(tmp_path)
    run.register_proposal(proposal)
    forged_resolution = RuleKernel(run.world).resolve_character(
        proposal,
        run.state,
        sequence=run.next_canonical_sequence,
        decision_id="decision-unbound",
        canonical_event_id="canonical-unbound",
    )

    with pytest.raises(DomainInvariantError, match="issuer"):
        run.commit_resolution(
            forged_resolution,
            visibility={"scope": "public"},
        )

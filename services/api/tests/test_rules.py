from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import CharacterProposal, UtteranceProposal, WorldDefinition
from app.domain.rules import RuleKernel


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def load_world(*, consent_required: bool = True) -> WorldDefinition:
    payload = json.loads(WORLD_PATH.read_text(encoding="utf-8"))
    for rule in payload["rules"]:
        if rule["kind"] == "CONSENTED_TRANSFER_ONLY":
            rule["params"]["consentRequired"] = consent_required
    return WorldDefinition.model_validate(payload)


def test_take_is_blocked_when_consent_is_required() -> None:
    world = load_world(consent_required=True)
    kernel = RuleKernel(world)
    proposal = CharacterProposal.model_validate(
        {
            "proposalId": "proposal-take-key",
            "actorId": "oc-devil",
            "action": {"kind": "TAKE", "objectId": "threshold-key"},
            "motivationRefs": ["goal-devil-open-door"],
        }
    )

    result = kernel.resolve_character(
        proposal,
        world.initial_state,
        sequence=1,
        decision_id="decision-take-key",
        canonical_event_id="canonical-take-key",
    )

    assert result.decision.outcome == "blocked"
    assert result.decision.reason_codes == ["CONSENT_REQUIRED"]
    assert "effects" not in result.decision.model_dump()
    assert result.event is not None
    assert result.event.effects == []
    assert "key.holder.unchanged" in result.event.fact_codes


def test_resolution_receipt_binds_proposal_rules_input_version_and_effects() -> None:
    world = load_world(consent_required=True)
    proposal = CharacterProposal.model_validate(
        {
            "proposalId": "proposal-receipted-take",
            "actorId": "oc-devil",
            "action": {"kind": "TAKE", "objectId": "threshold-key"},
            "motivationRefs": ["goal-devil-open-door"],
        }
    )

    result = RuleKernel(world).resolve_character(
        proposal,
        world.initial_state,
        sequence=1,
        decision_id="decision-receipted-take",
        canonical_event_id="canonical-receipted-take",
    )

    assert result.event is not None
    assert result.receipt.proposal_id == proposal.proposal_id
    assert result.receipt.proposal_fingerprint
    assert result.receipt.input_world_version == world.initial_state.world_version
    assert result.receipt.matched_rule_ids == result.decision.matched_rule_ids
    assert result.receipt.rule_fingerprint
    assert result.receipt.verdict == result.decision.verdict
    assert result.receipt.outcome == result.decision.outcome
    assert result.receipt.effects_fingerprint
    assert result.receipt.canonical_event_fingerprint
    assert result.receipt.receipt_fingerprint


def test_take_succeeds_when_consent_is_not_required() -> None:
    world = load_world(consent_required=False)
    result = RuleKernel(world).resolve_character(
        CharacterProposal.model_validate(
            {
                "proposalId": "proposal-take-key",
                "actorId": "oc-devil",
                "action": {"kind": "TAKE", "objectId": "threshold-key"},
                "motivationRefs": [],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-take-key",
        canonical_event_id="canonical-take-key",
    )

    assert result.decision.outcome == "success"
    assert result.event is not None
    assert [effect.path for effect in result.event.effects] == [
        "/objects/threshold-key/holderId"
    ]
    assert result.event.effects[0].after == "oc-devil"


def test_voluntary_give_only_changes_the_key_holder() -> None:
    world = load_world()
    result = RuleKernel(world).resolve_character(
        CharacterProposal.model_validate(
            {
                "proposalId": "proposal-give-key",
                "actorId": "oc-user",
                "action": {
                    "kind": "GIVE",
                    "objectId": "threshold-key",
                    "recipientId": "oc-devil",
                },
                "motivationRefs": ["owner-advice-trust-devil"],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-give-key",
        canonical_event_id="canonical-give-key",
    )

    assert result.decision.outcome == "success"
    assert result.event is not None
    assert [effect.path for effect in result.event.effects] == [
        "/objects/threshold-key/holderId"
    ]
    assert all("thresholdUnlocked" not in effect.path for effect in result.event.effects)


def test_non_holder_give_is_rejected_without_a_canonical_event() -> None:
    world = load_world()
    result = RuleKernel(world).resolve_character(
        CharacterProposal.model_validate(
            {
                "proposalId": "proposal-invalid-give",
                "actorId": "oc-angel",
                "action": {
                    "kind": "GIVE",
                    "objectId": "threshold-key",
                    "recipientId": "oc-devil",
                },
                "motivationRefs": [],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-invalid-give",
        canonical_event_id="canonical-invalid-give",
    )

    assert result.decision.verdict == "reject_invalid"
    assert result.decision.reason_codes == ["ACTOR_IS_NOT_CURRENT_HOLDER"]
    assert result.event is None


def test_utterance_records_speech_but_does_not_promote_claim_to_fact() -> None:
    world = load_world()
    claim = "恶魔偷走了钥匙。"
    result = RuleKernel(world).resolve_utterance(
        UtteranceProposal.model_validate(
            {
                "proposalId": "proposal-angel-utterance",
                "actorId": "oc-angel",
                "text": claim,
                "audience": "world",
                "basedOnBeliefIds": ["belief-angel-taken"],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-angel-utterance",
        canonical_event_id="canonical-angel-utterance",
    )

    assert result.event is not None
    assert result.event.kind == "utterance.spoken"
    assert result.event.fact_codes == ["utterance.spoken"]
    assert claim not in result.event.fact_codes
    assert result.event.perceptual_atoms[0].data["text"] == claim


def test_tension_at_upper_bound_does_not_emit_an_invalid_increment() -> None:
    world = load_world()
    state = world.initial_state.model_copy(deep=True)
    state.relationships["oc-angel"]["oc-devil"].tension = 3

    result = RuleKernel(world).resolve_utterance(
        UtteranceProposal.model_validate(
            {
                "proposalId": "proposal-angel-utterance",
                "actorId": "oc-angel",
                "text": "我仍然怀疑你。",
                "audience": "world",
                "basedOnBeliefIds": ["belief-angel-taken"],
            }
        ),
        state,
        sequence=1,
        decision_id="decision-angel-utterance",
        canonical_event_id="canonical-angel-utterance",
    )

    assert result.event is not None
    assert result.event.effects == []


def test_wait_is_an_explicit_actor_choice_with_no_world_effects() -> None:
    world = load_world()
    result = RuleKernel(world).resolve_character(
        CharacterProposal.model_validate(
            {
                "proposalId": "proposal-devil-waits",
                "actorId": "oc-devil",
                "action": {
                    "kind": "WAIT",
                    "reason": "I do not want to join this conversation.",
                },
                "motivationRefs": ["boundary:stay-silent"],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-devil-waits",
        canonical_event_id="canonical-devil-waits",
    )

    assert result.decision.outcome == "success"
    assert result.decision.reason_codes == ["ACTOR_CHOSE_TO_WAIT"]
    assert result.event is not None
    assert result.event.fact_codes == ["actor.waited"]
    assert result.event.effects == []
    assert result.receipt.canonical_event_fingerprint


def test_rule_kernel_rejects_nonexistent_recipient() -> None:
    world = load_world()
    result = RuleKernel(world).resolve_character(
        CharacterProposal.model_validate(
            {
                "proposalId": "proposal-invalid-recipient",
                "actorId": "oc-user",
                "action": {
                    "kind": "GIVE",
                    "objectId": "threshold-key",
                    "recipientId": "oc-ghost",
                },
                "motivationRefs": [],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-invalid-recipient",
        canonical_event_id="canonical-invalid-recipient",
    )

    assert result.decision.verdict == "reject_invalid"
    assert result.decision.reason_codes == ["RECIPIENT_NOT_FOUND"]
    assert result.event is None

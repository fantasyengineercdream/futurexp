from __future__ import annotations

import json
from pathlib import Path

from app.domain.models import CharacterProposal, WorldDefinition
from app.domain.perspective import PerspectiveProjector
from app.domain.policies import DeterministicMindPolicy
from app.domain.rules import RuleKernel


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def load_world() -> WorldDefinition:
    return WorldDefinition.model_validate_json(WORLD_PATH.read_text(encoding="utf-8"))


def voluntary_transfer_event(world: WorldDefinition):
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
                "motivationRefs": [],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-give-key",
        canonical_event_id="canonical-give-key",
    )
    assert result.event is not None
    return result.event


def co_located_state(world: WorldDefinition):
    state = world.initial_state.model_copy(deep=True)
    state.actor_locations = {
        "oc-user": "mirror-curtain",
        "oc-devil": "mirror-curtain",
        "oc-angel": "mirror-curtain",
    }
    return state


def test_occluded_angel_receives_sound_without_hidden_transfer_fields() -> None:
    world = load_world()
    event = voluntary_transfer_event(world)
    observations = PerspectiveProjector(world).project(
        event,
        co_located_state(world),
    )
    angel = observations["oc-angel"]

    assert angel.completeness == "partial"
    assert angel.channels == ["hearing"]
    assert [fact.code for fact in angel.facts] == ["key.metal.chime"]
    serialized = json.dumps(angel.model_dump(), ensure_ascii=False)
    assert "recipientId" not in serialized
    assert "voluntary" not in serialized
    assert "oc-user" not in serialized


def test_direct_witnesses_receive_the_voluntary_transfer_atom() -> None:
    world = load_world()
    observations = PerspectiveProjector(world).project(
        voluntary_transfer_event(world),
        co_located_state(world),
    )

    for oc_id in ("oc-user", "oc-devil"):
        observation = observations[oc_id]
        assert observation.completeness == "full"
        sight_fact = next(
            fact for fact in observation.facts if fact.code == "key.transfer.seen"
        )
        assert sight_fact.data["actorId"] == "oc-user"
        assert sight_fact.data["recipientId"] == "oc-devil"
        assert sight_fact.data["voluntary"] is True


def test_hearing_does_not_leak_across_locations() -> None:
    world = load_world()
    state = world.initial_state.model_copy(deep=True)
    state.actor_locations = {
        "oc-user": "mirror-curtain",
        "oc-devil": "mirror-curtain",
        "oc-angel": "grand-foyer",
    }

    observations = PerspectiveProjector(world).project(
        voluntary_transfer_event(world),
        state,
    )

    assert observations["oc-angel"].channels == []
    assert observations["oc-angel"].facts == []


def test_false_belief_remains_a_subjective_artifact() -> None:
    world = load_world()
    event = voluntary_transfer_event(world)
    angel_observation = PerspectiveProjector(world).project(
        event,
        co_located_state(world),
    )["oc-angel"]

    mind = DeterministicMindPolicy().interpret(angel_observation)

    assert mind.belief.predicate == "keyWasTakenBy"
    assert mind.belief.object == "oc-devil"
    assert "key.transferred.voluntarily" in event.fact_codes
    assert "keyWasTakenBy" not in event.fact_codes

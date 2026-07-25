from __future__ import annotations

from pathlib import Path

from app.domain.models import CharacterProposal, WorldDefinition
from app.domain.reducer import canonical_state_checksum, reduce_canonical_events
from app.domain.rules import RuleKernel


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def load_world() -> WorldDefinition:
    return WorldDefinition.model_validate_json(WORLD_PATH.read_text(encoding="utf-8"))


def test_replay_is_deterministic_and_checksum_only_depends_on_objective_state() -> None:
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
                "motivationRefs": [],
            }
        ),
        world.initial_state,
        sequence=1,
        decision_id="decision-give-key",
        canonical_event_id="canonical-give-key",
    )
    assert result.event is not None

    first = reduce_canonical_events(world.initial_state, [result.event])
    second = reduce_canonical_events(world.initial_state, [result.event])

    assert first == second
    assert first.objects["threshold-key"].holder_id == "oc-devil"
    assert first.threshold_unlocked is False
    assert canonical_state_checksum(first) == canonical_state_checksum(second)


def test_checksum_excludes_session_status_and_tick_metadata() -> None:
    world = load_world()
    ready = world.initial_state.model_copy(deep=True)
    completed = world.initial_state.model_copy(deep=True)
    completed.status = "completed"
    completed.tick_index = 2

    assert canonical_state_checksum(ready) == canonical_state_checksum(completed)

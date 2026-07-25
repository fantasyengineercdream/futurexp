from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.domain.encounters import Affordance
from app.domain.living_world import (
    ActorMemory,
    ActorPolicyContext,
    ActorPolicyProvider,
    DeterministicActorPolicyProvider,
    DeterministicSceneDirector,
    StructuredActorTurn,
    load_preset_runtime_bundle,
)
from app.main import create_app
from app.runtime import LivingWorldRuntime
from app.storage import SQLiteStorage


class UnavailableProvider(ActorPolicyProvider):
    provider_id = "unavailable-test-provider"

    def propose_turn(self, context: ActorPolicyContext) -> StructuredActorTurn:
        raise ConnectionError("model endpoint unavailable")


def run_world(
    tmp_path: Path,
    *,
    session_id: str = "living-world-v01",
    seed: str = "living-world-seed-17",
    provider: ActorPolicyProvider | None = None,
    adventure_published: bool = True,
):
    storage = SQLiteStorage(tmp_path / f"{session_id}.sqlite3")
    runtime = LivingWorldRuntime(
        storage,
        load_preset_runtime_bundle(),
        actor_provider=provider,
        director=DeterministicSceneDirector(
            adventure_published=adventure_published
        ),
    )
    return storage, runtime.create_and_run(session_id=session_id, seed=seed)


def test_three_independent_ocs_complete_two_rounds_through_the_rule_kernel(
    tmp_path: Path,
) -> None:
    storage, result = run_world(tmp_path)

    assert result.status == "completed"
    assert len(result.rounds) == 2
    assert [
        sorted(turn.actor_id for turn in round_result.turns)
        for round_result in result.rounds
    ] == [
        ["oc-angel", "oc-devil", "oc-user"],
        ["oc-angel", "oc-devil", "oc-user"],
    ]
    assert all(
        turn.intent.proposed_by == "actorPolicy"
        for round_result in result.rounds
        for turn in round_result.turns
    )
    assert all(
        turn.resolution_receipt.canonical_event_id
        for round_result in result.rounds
        for turn in round_result.turns
    )

    blocked_conflict = next(
        turn
        for round_result in result.rounds
        for turn in round_result.turns
        if turn.resolution_receipt.outcome == "blocked"
    )
    assert blocked_conflict.resolution_receipt.matched_rule_ids == [
        "rule-consented-transfer"
    ]
    assert "CONSENT_REQUIRED" in blocked_conflict.resolution_receipt.reason_codes

    stored = storage.get_events(result.session_id)
    canonical = [
        event
        for event in stored
        if event["type"] == "canonical.event.committed"
    ]
    assert canonical
    assert len(canonical) == len(result.canonical_ledger)


def test_default_dm_frames_daily_life_without_publishing_an_adventure() -> None:
    director = DeterministicSceneDirector()
    planning = director.organize(
        round_index=0,
        actor_id="oc-angel",
        location_id="mirror-curtain",
        participant_ids=["oc-angel", "oc-devil"],
    )

    assert "日常" in planning.hook
    assert "冒险" not in planning.hook
    assert planning.location_ids == ["mirror-curtain"]
    assert set(planning.allowed_action_kinds) == {"MOVE", "WAIT"}
    assert planning.destination_location_ids == [
        "apartment-bar",
        "apartment-library",
        "grand-foyer",
        "mirror-curtain",
    ]

    social = director.organize(
        round_index=1,
        actor_id="oc-angel",
        location_id="apartment-library",
        participant_ids=["oc-angel", "oc-devil"],
    )
    assert set(social.allowed_action_kinds) == {"UTTERANCE", "WAIT"}
    assert "是否交谈" in social.goal_or_conflict


def test_dm_frames_one_specific_infinite_apartment_event() -> None:
    pressure = DeterministicSceneDirector(
        adventure_published=True
    ).organize(
        round_index=0,
        actor_id="oc-user",
        location_id="mirror-curtain",
        participant_ids=["oc-user", "oc-angel", "oc-devil"],
    )

    assert "临时冒险房间" in pressure.hook
    assert "通行牌" in pressure.goal_or_conflict
    assert "夺取" in pressure.failure_condition
    assert pressure.participant_ids == [
        "oc-user",
        "oc-angel",
        "oc-devil",
    ]


def test_daily_actor_outputs_do_not_reuse_the_adventure_script(
    tmp_path: Path,
) -> None:
    _, result = run_world(tmp_path, adventure_published=False)

    public_lines = [
        output.public_expression.text
        for round_result in result.rounds
        for output in round_result.outputs
    ]
    first_kinds = {turn.intent.kind for turn in result.rounds[0].turns}
    second_kinds = {turn.intent.kind for turn in result.rounds[1].turns}
    assert first_kinds <= {"MOVE", "WAIT"}
    assert "MOVE" in first_kinds
    assert second_kinds <= {"UTTERANCE", "WAIT"}
    assert "WAIT" in second_kinds
    assert "UTTERANCE" in second_kinds
    assert not any(
        forbidden in line
        for line in public_lines
        for forbidden in ("通行牌", "进去", "回来")
    )
    assert any("今天" in line or "聊" in line for line in public_lines)


def test_observation_memory_is_the_counterfactual_cause_of_changed_choice() -> None:
    bundle = load_preset_runtime_bundle()
    profile = bundle.actor_profile("oc-devil")
    shared = {
        "pressureId": "pressure-memory-ablation",
        "actorId": "oc-devil",
        "participantIds": ["oc-devil", "oc-angel"],
        "locationId": "mirror-curtain",
        "triggerEvidence": ["location:mirror-curtain"],
        "hook": "A bounded rule test.",
        "goalOrConflict": "Choose whether to repeat the blocked action.",
        "stakes": ["the next choice must be attributable"],
        "failureCondition": "The action may be blocked again.",
        "costOrConsequence": "The choice is recorded.",
        "persistentFallout": "Observation memory remains available.",
    }
    affordances = [
        Affordance.model_validate(
            {
                **shared,
                "affordanceId": "affordance-take",
                "actionKind": "TAKE",
                "constraints": {"objectIds": ["shared-badge"]},
            }
        ),
        Affordance.model_validate(
            {
                **shared,
                "affordanceId": "affordance-speak",
                "actionKind": "UTTERANCE",
                "constraints": {
                    "audience": ["world", "publicUi"],
                    "participantIds": ["oc-devil", "oc-angel"],
                },
            }
        ),
    ]
    base_context = {
        "seed": "memory-ablation",
        "roundIndex": 1,
        "actorId": "oc-devil",
        "ownLocationId": "mirror-curtain",
        "ownLocationLayer": "safe",
        "profile": profile,
        "relationships": bundle.world.initial_state.relationships[
            "oc-devil"
        ],
        "affordances": affordances,
    }
    provider = DeterministicActorPolicyProvider()
    without_memory = provider.propose_turn(
        ActorPolicyContext.model_validate(
            {**base_context, "memories": []}
        )
    )
    memory = ActorMemory(
        memory_id="memory-resisted-take",
        actor_id="oc-devil",
        source_round=0,
        kind="observedFact",
        statement="object.resisted.take",
        source_observation_ids=["observation-blocked-take"],
    )
    with_memory = provider.propose_turn(
        ActorPolicyContext.model_validate(
            {**base_context, "memories": [memory]}
        )
    )

    assert without_memory.intent.kind == "TAKE"
    assert with_memory.intent.kind == "UTTERANCE"
    assert with_memory.influenced_by_memory_ids == [memory.memory_id]


def test_observation_memory_and_expression_keep_epistemic_boundaries_across_rounds(
    tmp_path: Path,
) -> None:
    _, result = run_world(tmp_path)
    first_round = result.rounds[0]
    second_round = result.rounds[1]

    departure_code = "location.departure.seen"
    first_views = {
        view.actor_id: view
        for view in first_round.epistemic_views
    }
    observers = {
        actor_id
        for actor_id, view in first_views.items()
        if departure_code in {fact.code for fact in view.observed_facts}
    }
    assert observers == {"oc-devil"}
    assert first_views["oc-angel"].unknowns
    assert departure_code not in {
        unknown.label for unknown in first_views["oc-angel"].unknowns
    }

    assert all(
        output.public_expression.text != output.private_inner_os.text
        for output in first_round.outputs
    )
    assert all(
        output.public_expression.canonical_event_id
        for output in first_round.outputs
    )
    assert all(
        output.private_inner_os.delivery == "ownerPrivate"
        for output in first_round.outputs
    )
    assert not any(
        "privateInnerOs" in str(event.model_dump(by_alias=True))
        for event in result.canonical_ledger
    )

    assert all(turn.input_memory_count > 0 for turn in second_round.turns)
    first_devil = next(
        turn for turn in first_round.turns if turn.actor_id == "oc-devil"
    )
    second_devil = next(
        turn for turn in second_round.turns if turn.actor_id == "oc-devil"
    )
    assert first_devil.intent.kind == "TAKE"
    assert second_devil.intent.kind == "UTTERANCE"
    assert any(
        memory.source_round == 0
        for view in second_round.epistemic_views
        for memory in view.memories
    )
    assert (
        result.rounds[0].relationship_snapshot["oc-angel"]["oc-devil"].tension
        < result.rounds[1].relationship_snapshot["oc-angel"]["oc-devil"].tension
    )
    angel_outputs = [
        next(
            output
            for output in round_result.outputs
            if output.actor_id == "oc-angel"
        ).public_expression.text
        for round_result in result.rounds
    ]
    assert "先别抢" in angel_outputs[0]
    assert "她回来了" in angel_outputs[1]


def test_safe_adventure_safe_is_a_canonical_state_transition(
    tmp_path: Path,
) -> None:
    _, result = run_world(tmp_path)
    bundle = load_preset_runtime_bundle()

    assert len(bundle.actor_profiles) == 3
    assert all(profile.persona_constraints for profile in bundle.actor_profiles)
    assert all(profile.goal_refs for profile in bundle.actor_profiles)
    assert all(profile.initial_memories for profile in bundle.actor_profiles)
    assert bundle.world.location("mirror-curtain").layer == "safe"
    assert bundle.world.location("adventure-instance-01").layer == "adventure"
    assert result.rounds[0].location_snapshot["oc-user"] == "adventure-instance-01"
    assert result.rounds[1].location_snapshot["oc-user"] == "mirror-curtain"
    move_events = [
        event
        for event in result.canonical_ledger
        if "location.transitioned" in event.fact_codes
    ]
    assert [event.effects[0].before for event in move_events] == [
        "mirror-curtain",
        "adventure-instance-01",
    ]
    assert [event.effects[0].after for event in move_events] == [
        "adventure-instance-01",
        "mirror-curtain",
    ]


def test_same_seed_replays_identically_and_model_failure_uses_no_key_fallback(
    tmp_path: Path,
) -> None:
    _, first = run_world(
        tmp_path,
        session_id="replay-a",
        seed="replay-stable-seed",
    )
    _, second = run_world(
        tmp_path,
        session_id="replay-b",
        seed="replay-stable-seed",
    )
    _, fallback = run_world(
        tmp_path,
        session_id="fallback",
        seed="replay-stable-seed",
        provider=UnavailableProvider(),
    )

    assert first.replay_fingerprint == second.replay_fingerprint
    assert first.semantic_trace == second.semantic_trace
    assert fallback.status == "completed"
    assert fallback.provider_fallback_count == 6
    assert fallback.semantic_trace == first.semantic_trace


def test_living_world_has_a_minimal_callable_api(tmp_path: Path) -> None:
    api = TestClient(
        create_app(SQLiteStorage(tmp_path / "api-living-world.sqlite3"))
    )

    response = api.post(
        "/api/living-world/runs",
        json={"seed": "api-demo-seed"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["bundleId"] == "preset-infinite-apartment-v01"
    assert len(body["rounds"]) == 2
    assert len(body["canonicalLedger"]) >= 6
    assert body["replayFingerprint"]
    assert {
        "publicExpression",
        "privateInnerOs",
    }.issubset(body["rounds"][0]["outputs"][0])

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from app.domain.day_cycle import (
    LivingWorldDayProjectionDTO,
    LivingWorldDayCore,
    ResilientOcaPlanner,
)
from app.domain.living_world import ActorMemory, load_preset_runtime_bundle
from app.domain.reducer import canonical_state_checksum
from app.main import create_app
from app.storage import SQLiteStorage
from app.errors import DomainInvariantError


def test_day_cycle_runs_independent_plans_dm_schedule_rules_and_memories() -> None:
    bundle = load_preset_runtime_bundle()

    result = LivingWorldDayCore(bundle).run_day(
        run_id="day-loop-demo",
        day_index=1,
        seed="day-loop-seed",
        memories={profile.oc_id: [] for profile in bundle.actor_profiles},
    )

    assert len(result.plans) == len(bundle.actor_profiles) == 3
    assert {plan.actor_id for plan in result.plans} == {
        profile.oc_id for profile in bundle.actor_profiles
    }
    assert len({plan.plan_id for plan in result.plans}) == 3
    assert all(plan.proposed_by == "oca" for plan in result.plans)
    assert all("goal-" not in plan.activity_label for plan in result.plans)
    assert all(
        bundle.actor_profile(plan.actor_id).persona_constraints[0]
        in plan.activity_label
        for plan in result.plans
    )

    assert result.schedule.selected_event.event_id
    assert set(result.schedule.selected_event.participant_ids) == {
        profile.oc_id for profile in bundle.actor_profiles
    }
    assert {assignment.actor_id for assignment in result.schedule.assignments} == {
        profile.oc_id for profile in bundle.actor_profiles
    }
    assert result.schedule.decided_by == "dm"

    assert [frame.phase for frame in result.frames] == [
        "planned",
        "travelling",
        "arrived",
        "in_event",
        "complete",
    ]
    assert all(frame.advanced_by == "scheduler" for frame in result.frames)

    assert len(result.intents) == 3
    assert all(intent.proposed_by == "oca" for intent in result.intents)
    assert len(result.checks) == 3
    assert all(1 <= check.die_roll <= 20 for check in result.checks)
    assert all(
        check.total == check.die_roll + check.modifier
        and check.succeeded == (check.total >= check.dc)
        for check in result.checks
    )
    assert result.rule_receipts
    assert all(receipt.rule_id == "rpg-seeded-d20-v1" for receipt in result.rule_receipts)
    assert result.canonical_event.fact_codes
    assert result.final_state.world_version == (
        bundle.world.initial_state.world_version + 1
    )
    assert result.final_world_hash == canonical_state_checksum(result.final_state)
    assert set(result.memories) == {
        profile.oc_id for profile in bundle.actor_profiles
    }
    assert all(result.memories[actor_id] for actor_id in result.memories)
    assert len(
        {
            actor_memories[0].statement
            for actor_memories in result.memories.values()
        }
    ) == 3


def test_runtime_and_day_planner_accept_an_additional_oc_id() -> None:
    bundle = load_preset_runtime_bundle()
    extra_profile = bundle.actor_profile("oc-angel").model_copy(
        update={"oc_id": "oc-extra"}
    )
    expanded = bundle.model_copy(
        update={
            "actor_profiles": [*bundle.actor_profiles, extra_profile],
        }
    )
    extra_character = expanded.world.characters[0].model_copy(
        update={
            "oc_id": "oc-extra",
            "name": "额外测试角色",
            "relationships": {},
        }
    )
    expanded.world.characters.append(extra_character)
    expanded.world.initial_state.actor_locations["oc-extra"] = (
        extra_profile.home_location_id
    )
    for character in expanded.world.characters:
        if character.oc_id == "oc-extra":
            continue
        relation = next(iter(character.relationships.values())).model_copy()
        character.relationships["oc-extra"] = relation
        extra_character.relationships[character.oc_id] = relation.model_copy()
        expanded.world.initial_state.relationships[
            character.oc_id
        ]["oc-extra"] = relation.model_copy()
        expanded.world.initial_state.relationships.setdefault(
            "oc-extra",
            {},
        )[character.oc_id] = relation.model_copy()

    result = LivingWorldDayCore(expanded).run_day(
        run_id="n-oc-run",
        day_index=1,
        seed="n-oc-plan",
        memories={
            profile.oc_id: [] for profile in expanded.actor_profiles
        },
    )

    assert len(result.plans) == 4
    assert expanded.actor_profile("oc-extra").oc_id == "oc-extra"
    assert {plan.actor_id for plan in result.plans} == {
        "oc-user",
        "oc-angel",
        "oc-devil",
        "oc-extra",
    }
    assert set(result.memories) == {
        "oc-user",
        "oc-angel",
        "oc-devil",
        "oc-extra",
    }
    assert result.replay_verified is True


def test_day_loop_falls_back_when_a_model_backed_oca_planner_fails() -> None:
    bundle = load_preset_runtime_bundle()

    class UnavailableModelPlanner:
        provider_id = "unavailable-model"

        def plan(self, **_kwargs):
            raise RuntimeError("model unavailable")

    core = LivingWorldDayCore(
        bundle,
        planner=ResilientOcaPlanner(primary=UnavailableModelPlanner()),
    )
    result = core.run_day(
        run_id="planner-fallback",
        day_index=1,
        seed="planner-fallback",
        memories={
            profile.oc_id: [] for profile in bundle.actor_profiles
        },
    )

    assert len(result.plans) == len(bundle.actor_profiles)
    assert all(plan.proposed_by == "oca" for plan in result.plans)
    assert result.replay_verified is True


def test_day_cycle_is_replayable_and_proposal_order_independent() -> None:
    bundle = load_preset_runtime_bundle()
    memories = {profile.oc_id: [] for profile in bundle.actor_profiles}
    core = LivingWorldDayCore(bundle)

    first = core.run_day(
        run_id="stable-run",
        day_index=1,
        seed="stable-seed",
        memories=memories,
    )
    reversed_bundle = bundle.model_copy(
        update={"actor_profiles": list(reversed(bundle.actor_profiles))}
    )
    second = LivingWorldDayCore(reversed_bundle).run_day(
        run_id="stable-run",
        day_index=1,
        seed="stable-seed",
        memories=memories,
    )

    assert first.final_world_hash == second.final_world_hash
    assert first.checks == second.checks
    assert first.replay_verified is True
    assert second.replay_verified is True


def test_default_demo_seed_gives_oo_and_cc_distinct_real_check_outcomes() -> None:
    bundle = load_preset_runtime_bundle()
    result = LivingWorldDayCore(bundle).run_day(
        run_id="default-demo-checks",
        day_index=1,
        seed=bundle.default_seed,
        memories={profile.oc_id: [] for profile in bundle.actor_profiles},
    )
    checks = {check.actor_id: check for check in result.checks}
    angel = checks["oc-angel"]
    devil = checks["oc-devil"]

    assert angel.die_roll != devil.die_roll
    assert angel.total != devil.total
    assert angel.succeeded != devil.succeeded
    for atom in result.canonical_event.perceptual_atoms:
        assert set(atom.data) == {
            "actorId",
            "observableAction",
            "observableOutcome",
        }


def test_only_event_participants_observe_event_facts() -> None:
    bundle = load_preset_runtime_bundle()

    result = LivingWorldDayCore(bundle, max_event_participants=2).run_day(
        run_id="partial-pov",
        day_index=1,
        seed="partial-pov-seed",
        memories={profile.oc_id: [] for profile in bundle.actor_profiles},
    )

    participants = set(result.schedule.selected_event.participant_ids)
    outsider = next(
        profile.oc_id
        for profile in bundle.actor_profiles
        if profile.oc_id not in participants
    )

    assert result.memories[outsider][0].source_observation_ids == []
    assert "没有亲历共同事件" in result.memories[outsider][0].statement
    assert all(
        result.memories[actor_id][0].source_observation_ids
        for actor_id in participants
    )


def test_one_actor_event_does_not_require_a_self_relationship() -> None:
    bundle = load_preset_runtime_bundle()

    result = LivingWorldDayCore(bundle, max_event_participants=1).run_day(
        run_id="solo-event",
        day_index=1,
        seed="solo-event-seed",
        memories={profile.oc_id: [] for profile in bundle.actor_profiles},
    )

    assert len(result.schedule.selected_event.participant_ids) == 1
    assert len(result.checks) == 1
    assert result.replay_verified is True


def test_dm_cannot_move_an_oc_without_its_plan_or_event_intent() -> None:
    bundle = load_preset_runtime_bundle()
    core = LivingWorldDayCore(bundle)
    memories = {profile.oc_id: [] for profile in bundle.actor_profiles}
    plans = core.plan_day(
        day_index=1,
        seed="dm-boundary",
        memories=memories,
    )
    schedule = core.director.arrange(
        run_id="dm-boundary",
        day_index=1,
        bundle=bundle,
        plans=plans,
    )
    intents = core._event_intents(schedule, memories)
    user_intent = next(
        intent for intent in intents if intent.actor_id == "oc-user"
    )
    user_intent.accepted_location_id = "apartment-bar"
    orders = [
        core.director.order_check(intent, day_index=1)
        for intent in intents
    ]

    with pytest.raises(
        DomainInvariantError,
        match="without its plan or event intent",
    ):
        core.rule_kernel.adjudicate(
            run_id="dm-boundary",
            day_index=1,
            seed="dm-boundary",
            schedule=schedule,
            plans=plans,
            intents=intents,
            orders=orders,
            state=bundle.world.initial_state,
        )


def test_oc_can_decline_the_event_and_keep_its_own_daily_plan() -> None:
    bundle = load_preset_runtime_bundle()
    memories = {profile.oc_id: [] for profile in bundle.actor_profiles}
    memories["oc-user"] = [
        ActorMemory(
            memory_id="memory:decline",
            actor_id="oc-user",
            source_round=0,
            kind="ownerCounsel",
            statement="我不参加今天的共同事件。",
            source_observation_ids=[],
        )
    ]

    result = LivingWorldDayCore(bundle).run_day(
        run_id="declined-event",
        day_index=1,
        seed="declined-event",
        memories=memories,
    )

    assert "oc-user" not in result.schedule.selected_event.participant_ids
    user_assignment = next(
        assignment
        for assignment in result.schedule.assignments
        if assignment.actor_id == "oc-user"
    )
    user_plan = next(
        plan for plan in result.plans if plan.actor_id == "oc-user"
    )
    assert user_assignment.participates_in_event is False
    assert (
        user_assignment.destination_location_id
        == user_plan.desired_location_id
    )


def test_previous_memory_changes_the_next_day_plan() -> None:
    bundle = load_preset_runtime_bundle()
    actor_id = "oc-angel"
    empty = {profile.oc_id: [] for profile in bundle.actor_profiles}
    remembered = {profile.oc_id: [] for profile in bundle.actor_profiles}
    remembered[actor_id] = [
        ActorMemory(
            memory_id="memory:prior:angel",
            actor_id=actor_id,
            source_round=0,
            kind="observedFact",
            statement="昨天的尝试失败了，我今天想换一种安排。",
            source_observation_ids=["observation:yesterday"],
        )
    ]

    without_memory = LivingWorldDayCore(bundle).plan_day(
        day_index=2,
        seed="memory-cause",
        memories=empty,
    )
    with_memory = LivingWorldDayCore(bundle).plan_day(
        day_index=2,
        seed="memory-cause",
        memories=remembered,
    )
    plain_plan = next(plan for plan in without_memory if plan.actor_id == actor_id)
    remembered_plan = next(plan for plan in with_memory if plan.actor_id == actor_id)

    assert remembered_plan.based_on_memory_ids == ["memory:prior:angel"]
    assert (
        remembered_plan.desired_location_id != plain_plan.desired_location_id
        or remembered_plan.activity_label != plain_plan.activity_label
    )


def test_day_loop_api_returns_one_frontend_ready_product_projection(
    tmp_path: Path,
) -> None:
    storage = SQLiteStorage(tmp_path / "day-loop.sqlite3")
    api = TestClient(create_app(storage))

    response = api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "frontend-day-loop"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["schemaVersion"] == "0.1"
    assert body["dayIndex"] == 1
    assert len(body["actors"]) == 3
    assert [frame["phase"] for frame in body["timeline"]] == [
        "planned",
        "travelling",
        "arrived",
        "in_event",
        "complete",
    ]
    assert len(body["event"]["intents"]) == 3
    assert len(body["event"]["checks"]) == 3
    assert len(body["memoryRefs"]) == 3
    assert "memories" not in body
    assert body["replayVerified"] is True
    assert len(body["worldHash"]) == 64
    serialized = response.text
    assert "canonicalEvent" not in serialized
    assert '"effects"' not in serialized
    assert "privateInnerOs" not in serialized

    replay_response = api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "frontend-day-loop"},
    )
    replay_body = replay_response.json()
    assert replay_body["worldHash"] == body["worldHash"]
    assert [
        (
            check["actorId"],
            check["dieRoll"],
            check["modifier"],
            check["total"],
            check["dc"],
            check["succeeded"],
        )
        for check in replay_body["event"]["checks"]
    ] == [
        (
            check["actorId"],
            check["dieRoll"],
            check["modifier"],
            check["total"],
            check["dc"],
            check["succeeded"],
        )
        for check in body["event"]["checks"]
    ]

    advanced = api.post(
        f"/api/living-world/day-loop-runs/{body['runId']}/advance"
    )
    assert advanced.status_code == 200
    advanced_body = advanced.json()
    assert advanced_body["dayIndex"] == 2
    assert advanced_body["worldVersion"] == body["worldVersion"] + 1
    assert len(storage.get_events(body["runId"])) == 2
    stored_memories = storage.get_living_world_view(
        body["runId"],
        "day-loop:memories",
    )
    assert all(
        len(actor_memories) == 2
        for actor_memories in stored_memories.values()
    )
    first_angel = next(
        actor for actor in body["actors"] if actor["actorId"] == "oc-angel"
    )
    next_angel = next(
        actor
        for actor in advanced_body["actors"]
        if actor["actorId"] == "oc-angel"
    )
    assert (
        next_angel["desiredLocationId"]
        != first_angel["desiredLocationId"]
    )


def test_day_loop_schema_and_example_match_a_real_deterministic_run() -> None:
    root = Path(__file__).resolve().parents[3]
    fixture_dir = root / "fixtures" / "living-world-v02"
    schema = json.loads(
        (fixture_dir / "day-projection.schema.json").read_text(
            encoding="utf-8"
        )
    )
    example = json.loads(
        (fixture_dir / "day-projection.example.json").read_text(
            encoding="utf-8"
        )
    )

    Draft202012Validator(schema).validate(example)
    LivingWorldDayProjectionDTO.model_validate(example)
    bundle = load_preset_runtime_bundle()
    real_projection = LivingWorldDayCore(bundle).run_day(
        run_id="fixture-day-loop-v01",
        day_index=1,
        seed="kaleidoroom-day-loop-v01",
        memories={
            profile.oc_id: [] for profile in bundle.actor_profiles
        },
    ).to_product_projection(bundle)
    assert example == real_projection.model_dump(
        mode="json",
        by_alias=True,
    )

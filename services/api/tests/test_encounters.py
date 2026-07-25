from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from app.domain.models import CharacterProposal, UtteranceProposal, WorldDefinition
from app.domain.scheduler import ScheduledStep
from app.errors import DomainInvariantError


ROOT = Path(__file__).resolve().parents[3]
WORLD_PATH = ROOT / "fixtures" / "infinite-apartment" / "world.json"


def load_world() -> WorldDefinition:
    return WorldDefinition.model_validate_json(WORLD_PATH.read_text(encoding="utf-8"))


def make_pressure():
    encounter_module = importlib.import_module("app.domain.encounters")
    DramaticPressure = getattr(encounter_module, "DramaticPressure")
    return DramaticPressure(
        pressure_id="pressure-shared-space-maintenance",
        source_kind="deadline",
        hook="A shared-space maintenance window is about to close.",
        goal_or_conflict="The co-located residents must choose what to report first.",
        eligible_actor_ids=["oc-user"],
        participant_ids=["oc-devil"],
        location_ids=["mirror-curtain"],
        opens_at_tick=1,
        expires_at_tick=3,
        allowed_action_kinds=["UTTERANCE"],
        evidence_refs=["goal-user-open-door", "relationship:oc-devil"],
        stakes=["lose the maintenance window"],
        failure_condition="No report is made before tick 3.",
        cost_or_consequence="Prioritizing one concern delays the other.",
        persistent_fallout="The next maintenance opportunity records the delay.",
    )


def test_encounter_engine_turns_pressure_into_finite_constrained_affordances() -> None:
    encounter_module = importlib.import_module("app.domain.encounters")
    EncounterEngine = getattr(encounter_module, "EncounterEngine")
    world = load_world()
    step = ScheduledStep(
        step_id="step-user-maintenance",
        due_tick=2,
        priority=9,
        actor_id="oc-user",
        reason="deadline",
    )

    frame = EncounterEngine(max_affordances=4).generate(
        world,
        world.initial_state,
        step,
        [make_pressure()],
    )

    assert len(frame.affordances) == 1
    affordance = frame.affordances[0]
    assert affordance.actor_id == "oc-user"
    assert affordance.participant_ids == ["oc-devil"]
    assert affordance.action_kind == "UTTERANCE"
    assert affordance.location_id == "mirror-curtain"
    assert affordance.hook
    assert affordance.goal_or_conflict
    assert affordance.stakes
    assert affordance.failure_condition
    assert affordance.cost_or_consequence
    assert affordance.persistent_fallout
    assert not hasattr(frame, "selected_action")


def test_encounter_engine_does_not_offer_a_storylet_without_legal_co_presence() -> None:
    encounter_module = importlib.import_module("app.domain.encounters")
    EncounterEngine = getattr(encounter_module, "EncounterEngine")
    pressure = make_pressure().model_copy(
        update={
            "eligible_actor_ids": ["oc-angel"],
            "participant_ids": ["oc-devil"],
            "location_ids": ["grand-foyer"],
        }
    )
    world = load_world()

    frame = EncounterEngine().generate(
        world,
        world.initial_state,
        ScheduledStep(
            step_id="step-angel",
            due_tick=2,
            priority=9,
            actor_id="oc-angel",
            reason="deadline",
        ),
        [pressure],
    )

    assert frame.affordances == []


def test_actor_proposal_must_be_one_of_the_encounter_affordances() -> None:
    encounter_module = importlib.import_module("app.domain.encounters")
    EncounterEngine = getattr(encounter_module, "EncounterEngine")
    world = load_world()
    engine = EncounterEngine()
    frame = engine.generate(
        world,
        world.initial_state,
        ScheduledStep(
            step_id="step-user",
            due_tick=2,
            priority=9,
            actor_id="oc-user",
            reason="deadline",
        ),
        [make_pressure()],
    )
    affordance = frame.affordances[0]
    allowed = UtteranceProposal(
        proposal_id="proposal-report-maintenance",
        actor_id="oc-user",
        text="I will report the blocked passage first.",
        audience="world",
        based_on_belief_ids=[],
    )
    invented = CharacterProposal.model_validate(
        {
            "proposalId": "proposal-invented-take",
            "actorId": "oc-user",
            "action": {"kind": "TAKE", "objectId": "threshold-key"},
            "motivationRefs": [],
        }
    )

    engine.assert_proposal_allowed(affordance, allowed)
    with pytest.raises(DomainInvariantError, match="affordance"):
        engine.assert_proposal_allowed(affordance, invented)


def test_encounter_receipt_does_not_copy_private_secret_text() -> None:
    encounter_module = importlib.import_module("app.domain.encounters")
    EncounterEngine = getattr(encounter_module, "EncounterEngine")
    world = load_world()
    private_secret = world.character("oc-user").secrets[0].text

    frame = EncounterEngine().generate(
        world,
        world.initial_state,
        ScheduledStep(
            step_id="step-user",
            due_tick=2,
            priority=9,
            actor_id="oc-user",
            reason="deadline",
        ),
        [make_pressure()],
    )

    assert private_secret not in json.dumps(
        frame.model_dump(by_alias=True),
        ensure_ascii=False,
    )


def test_finite_harness_connects_schedule_affordance_choice_and_adjudication() -> None:
    harness_module = importlib.import_module("app.domain.harness")
    LivingWorldHarness = getattr(harness_module, "LivingWorldHarness")
    scheduler_module = importlib.import_module("app.domain.scheduler")
    DeterministicStepScheduler = getattr(
        scheduler_module,
        "DeterministicStepScheduler",
    )
    world = load_world()
    harness = LivingWorldHarness(
        world,
        DeterministicStepScheduler(
            [
                ScheduledStep(
                    step_id="step-user",
                    due_tick=2,
                    priority=9,
                    actor_id="oc-user",
                    reason="deadline",
                )
            ]
        ),
    )

    frame = harness.next_encounter(world.initial_state, [make_pressure()])
    assert frame is not None
    proposal = UtteranceProposal(
        proposal_id="proposal-maintenance-choice",
        actor_id="oc-user",
        text="I will report the blocked passage first.",
        audience="world",
        based_on_belief_ids=[],
    )
    resolution = harness.adjudicate(
        world.initial_state,
        frame.affordances[0],
        proposal,
        sequence=1,
        decision_id="decision-maintenance-choice",
        canonical_event_id="canonical-maintenance-choice",
    )

    assert resolution.event is not None
    assert resolution.event.kind == "utterance.spoken"
    assert resolution.receipt.proposal_id == proposal.proposal_id
    assert harness.next_encounter(world.initial_state, [make_pressure()]) is None

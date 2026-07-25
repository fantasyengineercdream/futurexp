from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.models import (
    CharacterProposal,
    ContractModel,
    OcId,
    UtteranceProposal,
    WorldDefinition,
    WorldState,
)
from app.domain.scheduler import ScheduledStep
from app.errors import DomainInvariantError


AffordanceAction = Literal["TAKE", "GIVE", "MOVE", "UTTERANCE", "WAIT"]
PressureSource = Literal[
    "desire",
    "relationship",
    "secret",
    "resource",
    "deadline",
    "threat",
]


class DramaticPressure(ContractModel):
    """A storylet seed: pressure and consequences, never a chosen action."""

    pressure_id: str
    source_kind: PressureSource
    hook: str = Field(min_length=1)
    goal_or_conflict: str = Field(min_length=1)
    eligible_actor_ids: list[OcId] = Field(min_length=1)
    participant_ids: list[OcId] = Field(min_length=1)
    location_ids: list[str] = Field(min_length=1)
    opens_at_tick: int = Field(ge=0)
    expires_at_tick: int = Field(ge=0)
    allowed_action_kinds: list[AffordanceAction] = Field(min_length=1)
    destination_location_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(min_length=1)
    stakes: list[str] = Field(min_length=1)
    failure_condition: str = Field(min_length=1)
    cost_or_consequence: str = Field(min_length=1)
    persistent_fallout: str = Field(min_length=1)


class Affordance(ContractModel):
    affordance_id: str
    pressure_id: str
    actor_id: OcId
    participant_ids: list[OcId]
    location_id: str
    action_kind: AffordanceAction
    trigger_evidence: list[str]
    constraints: dict[str, object]
    hook: str
    goal_or_conflict: str
    stakes: list[str]
    failure_condition: str
    cost_or_consequence: str
    persistent_fallout: str


class EncounterFrame(ContractModel):
    encounter_id: str
    scheduled_step_id: str
    tick: int = Field(ge=0)
    actor_id: OcId
    affordances: list[Affordance]


class EncounterEngine:
    """Generates legal opportunities; it never chooses on an actor's behalf."""

    def __init__(self, *, max_affordances: int = 8) -> None:
        if max_affordances < 1:
            raise DomainInvariantError("max_affordances must be positive")
        self.max_affordances = max_affordances

    def generate(
        self,
        world: WorldDefinition,
        state: WorldState,
        step: ScheduledStep,
        pressures: list[DramaticPressure],
    ) -> EncounterFrame:
        actor = world.character(step.actor_id)
        actor_location_id = state.actor_locations.get(
            actor.oc_id,
            actor.location_id,
        )
        affordances: list[Affordance] = []
        for pressure in sorted(pressures, key=lambda item: item.pressure_id):
            if step.actor_id not in pressure.eligible_actor_ids:
                continue
            if not (
                pressure.opens_at_tick
                <= step.due_tick
                <= pressure.expires_at_tick
            ):
                continue
            if actor_location_id not in pressure.location_ids:
                continue
            participants = [
                participant_id
                for participant_id in pressure.participant_ids
                if state.actor_locations.get(
                    participant_id,
                    world.character(participant_id).location_id,
                )
                == actor_location_id
            ]
            if len(participants) != len(pressure.participant_ids):
                continue
            trigger_evidence = list(
                dict.fromkeys(
                    [
                        *pressure.evidence_refs,
                        f"time:{step.due_tick}",
                        f"location:{actor_location_id}",
                        *[
                            f"relationship:{participant_id}"
                            for participant_id in participants
                            if participant_id
                            in state.relationships.get(step.actor_id, {})
                        ],
                    ]
                )
            )
            for action_kind in sorted(set(pressure.allowed_action_kinds)):
                constraints = self._constraints_for(
                    action_kind,
                    step.actor_id,
                    participants,
                    actor_location_id,
                    state,
                    world,
                    pressure,
                )
                if constraints is None:
                    continue
                affordances.append(
                    Affordance(
                        affordance_id=(
                            f"{step.step_id}:{pressure.pressure_id}:{action_kind}"
                        ),
                        pressure_id=pressure.pressure_id,
                        actor_id=step.actor_id,
                        participant_ids=participants,
                        location_id=actor_location_id,
                        action_kind=action_kind,
                        trigger_evidence=trigger_evidence,
                        constraints=constraints,
                        hook=pressure.hook,
                        goal_or_conflict=pressure.goal_or_conflict,
                        stakes=pressure.stakes,
                        failure_condition=pressure.failure_condition,
                        cost_or_consequence=pressure.cost_or_consequence,
                        persistent_fallout=pressure.persistent_fallout,
                    )
                )
        affordances.sort(key=lambda item: item.affordance_id)
        return EncounterFrame(
            encounter_id=f"encounter:{step.step_id}",
            scheduled_step_id=step.step_id,
            tick=step.due_tick,
            actor_id=step.actor_id,
            affordances=affordances[: self.max_affordances],
        )

    @staticmethod
    def _constraints_for(
        action_kind: AffordanceAction,
        actor_id: OcId,
        participants: list[OcId],
        location_id: str,
        state: WorldState,
        world: WorldDefinition,
        pressure: DramaticPressure,
    ) -> dict[str, object] | None:
        if action_kind == "WAIT":
            return {"reason": "actor chose not to take a public action"}
        if action_kind == "UTTERANCE":
            return {
                "audience": ["world", "publicUi"],
                "participantIds": participants,
            }
        if action_kind == "GIVE":
            held_objects = sorted(
                object_id
                for object_id, world_object in state.objects.items()
                if world_object.holder_id == actor_id
                and world_object.location_id == location_id
            )
            if not held_objects or not participants:
                return None
            return {
                "objectIds": held_objects,
                "recipientIds": participants,
            }
        if action_kind == "MOVE":
            rule = world.rule("LOCATION_TRANSITION")
            if rule is None or not rule.enabled:
                return None
            current = world.location(location_id)
            if pressure.destination_location_ids:
                destination_ids = sorted(
                    candidate
                    for candidate in pressure.destination_location_ids
                    if candidate != location_id
                    and any(
                        location.location_id == candidate
                        for location in world.locations
                    )
                )
            elif current.layer == "adventure":
                destination_ids = (
                    [current.return_location_id]
                    if current.return_location_id
                    else sorted(
                        location.location_id
                        for location in world.locations
                        if location.layer == "safe"
                    )
                )
            else:
                destination_ids = sorted(
                    location.location_id
                    for location in world.locations
                    if location.layer == "adventure"
                )
            if not destination_ids:
                return None
            return {"destinationIds": destination_ids}
        available_objects = sorted(
            object_id
            for object_id, world_object in state.objects.items()
            if world_object.location_id == location_id
            and world_object.holder_id != actor_id
        )
        if not available_objects:
            return None
        return {"objectIds": available_objects}

    @staticmethod
    def assert_proposal_allowed(
        affordance: Affordance,
        proposal: CharacterProposal | UtteranceProposal,
    ) -> None:
        if proposal.actor_id != affordance.actor_id:
            raise DomainInvariantError("proposal actor is outside the affordance")
        action_kind = (
            "UTTERANCE"
            if isinstance(proposal, UtteranceProposal)
            else proposal.action.kind
        )
        if action_kind != affordance.action_kind:
            raise DomainInvariantError("proposal action is outside the affordance")
        if isinstance(proposal, UtteranceProposal):
            if proposal.audience not in affordance.constraints.get("audience", []):
                raise DomainInvariantError(
                    "proposal audience is outside the affordance"
                )
            return
        if proposal.action.kind == "WAIT":
            return
        if proposal.action.kind == "MOVE":
            destination_ids = affordance.constraints.get("destinationIds", [])
            if proposal.action.location_id not in destination_ids:
                raise DomainInvariantError(
                    "proposal destination is outside the affordance"
                )
            return
        object_ids = affordance.constraints.get("objectIds", [])
        if proposal.action.kind in ("TAKE", "GIVE"):
            if proposal.action.object_id not in object_ids:
                raise DomainInvariantError(
                    "proposal object is outside the affordance"
                )
        if proposal.action.kind == "GIVE":
            recipient_ids = affordance.constraints.get("recipientIds", [])
            if proposal.action.recipient_id not in recipient_ids:
                raise DomainInvariantError(
                    "proposal recipient is outside the affordance"
                )

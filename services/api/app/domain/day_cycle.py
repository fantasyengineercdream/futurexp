from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol

from pydantic import Field

from app.domain.living_world import (
    ActorMemory,
    RuntimeActorProfile,
    RuntimeBundle,
)
from app.domain.living_memory import (
    LivingMemorySeed,
    PovActionMoment,
    PovEpisodeMaterial,
    PovObservedOutcome,
)
from app.domain.models import (
    CanonicalEvent,
    ContractModel,
    OcId,
    PerceptualAtom,
    StateEffect,
    WorldState,
)
from app.domain.perspective import PerspectiveProjector
from app.domain.reducer import canonical_state_checksum
from app.domain.transactional_living_world import (
    AtomicBatchCommitter,
    BatchAdjudication,
    ResolutionBatchProof,
    RuleReceiptProof,
)
from app.errors import DomainInvariantError


RpgAttribute = Literal["intellect", "athletics", "insight", "presence"]
DayPhase = Literal[
    "planned",
    "travelling",
    "arrived",
    "in_event",
    "complete",
]


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OcaDayPlan(ContractModel):
    plan_id: str
    actor_id: OcId
    day_index: int = Field(ge=1)
    desired_location_id: str
    activity_label: str
    goal_ref: str
    based_on_memory_ids: list[str]
    proposed_by: Literal["oca"] = "oca"


class DayAssignment(ContractModel):
    actor_id: OcId
    plan_id: str
    destination_location_id: str
    activity_label: str
    participates_in_event: bool


class ScheduledDayEvent(ContractModel):
    event_id: str
    location_id: str
    participant_ids: list[OcId] = Field(min_length=1)
    hook: str
    stakes: str


class DmDaySchedule(ContractModel):
    day_index: int = Field(ge=1)
    assignments: list[DayAssignment] = Field(min_length=1)
    selected_event: ScheduledDayEvent
    decided_by: Literal["dm"] = "dm"


class ActorScheduleState(ContractModel):
    actor_id: OcId
    location_id: str
    activity_label: str
    in_shared_event: bool


class DayScheduleFrame(ContractModel):
    phase: DayPhase
    actors: list[ActorScheduleState]
    advanced_by: Literal["scheduler"] = "scheduler"


class EventIntent(ContractModel):
    intent_id: str
    actor_id: OcId
    event_id: str
    goal: str
    approach: str
    requested_attribute: RpgAttribute
    accepted_location_id: str
    proposed_by: Literal["oca"] = "oca"


class DmCheckOrder(ContractModel):
    check_id: str
    intent_id: str
    actor_id: OcId
    day_index: int = Field(ge=1)
    attribute: RpgAttribute
    dc: int = Field(ge=5, le=25)
    ordered_by: Literal["dm"] = "dm"


class RpgCheckResult(ContractModel):
    check_id: str
    actor_id: OcId
    attribute: RpgAttribute
    die_roll: int = Field(ge=1, le=20)
    modifier: int
    total: int
    dc: int
    succeeded: bool
    resolved_by: Literal["ruleEngine"] = "ruleEngine"


class DmNarrative(ContractModel):
    public_summary: str
    generated_after_rule_results: Literal[True] = True


class DayActorProjection(ContractModel):
    actor_id: OcId
    display_name: str
    desired_location_id: str
    activity_label: str


class DayEventProjection(ContractModel):
    event_ref: str
    location_id: str
    participant_ids: list[OcId]
    hook: str
    stakes: str
    intents: list[EventIntent]
    checks: list[RpgCheckResult]
    public_narrative: str


class DayMemoryRefProjection(ContractModel):
    actor_id: OcId
    memory_ref: str
    available: Literal[True] = True


class LivingWorldDayProjectionDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    day_index: int
    actors: list[DayActorProjection]
    timeline: list[DayScheduleFrame]
    event: DayEventProjection
    memory_refs: list[DayMemoryRefProjection]
    world_version: int
    world_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    replay_verified: bool


class LivingWorldDayResult(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    day_index: int
    seed: str
    plans: list[OcaDayPlan]
    schedule: DmDaySchedule
    frames: list[DayScheduleFrame]
    intents: list[EventIntent]
    checks: list[RpgCheckResult]
    rule_receipts: list[RuleReceiptProof]
    narrative: DmNarrative
    canonical_event: CanonicalEvent
    final_state: WorldState
    final_world_hash: str
    memories: dict[OcId, list[ActorMemory]]
    living_memory_seeds: list[LivingMemorySeed]
    replay_verified: bool

    def to_product_projection(
        self,
        bundle: RuntimeBundle,
    ) -> LivingWorldDayProjectionDTO:
        plan_by_actor = {plan.actor_id: plan for plan in self.plans}
        return LivingWorldDayProjectionDTO(
            run_id=self.run_id,
            day_index=self.day_index,
            actors=[
                DayActorProjection(
                    actor_id=profile.oc_id,
                    display_name=bundle.world.character(profile.oc_id).name,
                    desired_location_id=(
                        plan_by_actor[profile.oc_id].desired_location_id
                    ),
                    activity_label=(
                        plan_by_actor[profile.oc_id].activity_label
                    ),
                )
                for profile in sorted(
                    bundle.actor_profiles,
                    key=lambda item: item.oc_id,
                )
            ],
            timeline=self.frames,
            event=DayEventProjection(
                event_ref=self.schedule.selected_event.event_id,
                location_id=self.schedule.selected_event.location_id,
                participant_ids=(
                    self.schedule.selected_event.participant_ids
                ),
                hook=self.schedule.selected_event.hook,
                stakes=self.schedule.selected_event.stakes,
                intents=self.intents,
                checks=self.checks,
                public_narrative=self.narrative.public_summary,
            ),
            memory_refs=[
                DayMemoryRefProjection(
                    actor_id=actor_id,
                    memory_ref=actor_memories[0].memory_id,
                )
                for actor_id, actor_memories in sorted(self.memories.items())
            ],
            world_version=self.final_state.world_version,
            world_hash=self.final_world_hash,
            replay_verified=self.replay_verified,
        )


class OcaPlannerProvider(Protocol):
    provider_id: str

    def plan(
        self,
        *,
        profile: RuntimeActorProfile,
        day_index: int,
        seed: str,
        memories: list[ActorMemory],
    ) -> OcaDayPlan: ...


class DeterministicOcaPlanner:
    """No-key fallback. One call per OC; it never sees another OC's plan."""

    provider_id = "deterministic-oca-day-plan-v01"

    def plan(
        self,
        *,
        profile,
        day_index: int,
        seed: str,
        memories: list[ActorMemory],
    ) -> OcaDayPlan:
        del seed
        preferences = profile.daily_location_preferences
        durable_memory_count = sum(
            memory.kind != "inference" for memory in memories
        )
        index = (
            day_index - 1 + durable_memory_count
        ) % len(preferences)
        location_id = preferences[index]
        memory_ids = [memory.memory_id for memory in memories[-3:]]
        if any(memory.kind == "ownerCounsel" for memory in memories):
            activity = (
                f"守住“{profile.persona_constraints[0]}”，"
                "参考主人建议调整今天的安排"
            )
        elif any(memory.kind == "inference" for memory in memories):
            activity = (
                "带着自己的判断，"
                f"按“{profile.persona_constraints[0]}”安排今天"
            )
        elif memories:
            activity = (
                "带着昨天的记忆，"
                f"按“{profile.persona_constraints[0]}”调整今天的安排"
            )
        else:
            activity = (
                f"按“{profile.persona_constraints[0]}”"
                "安排今天的生活"
            )
        return OcaDayPlan(
            plan_id=f"day-{day_index}:plan:{profile.oc_id}",
            actor_id=profile.oc_id,
            day_index=day_index,
            desired_location_id=location_id,
            activity_label=activity,
            goal_ref=profile.goal_refs[0],
            based_on_memory_ids=memory_ids,
        )


class ResilientOcaPlanner:
    """Use a model-backed planner when available, otherwise keep Demo alive."""

    provider_id = "resilient-oca-day-plan-v01"

    def __init__(
        self,
        *,
        primary: OcaPlannerProvider,
        fallback: OcaPlannerProvider | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or DeterministicOcaPlanner()

    def plan(
        self,
        *,
        profile: RuntimeActorProfile,
        day_index: int,
        seed: str,
        memories: list[ActorMemory],
    ) -> OcaDayPlan:
        try:
            return self.primary.plan(
                profile=profile,
                day_index=day_index,
                seed=seed,
                memories=memories,
            )
        except Exception:
            return self.fallback.plan(
                profile=profile,
                day_index=day_index,
                seed=seed,
                memories=memories,
            )


class DeterministicDailyDirector:
    """DM chooses coordination and pressure, never an OC action or outcome."""

    def __init__(self, *, max_event_participants: int) -> None:
        self.max_event_participants = max_event_participants

    def arrange(
        self,
        *,
        run_id: str,
        day_index: int,
        bundle: RuntimeBundle,
        plans: list[OcaDayPlan],
    ) -> DmDaySchedule:
        by_location: dict[str, list[OcaDayPlan]] = {}
        for plan in plans:
            by_location.setdefault(plan.desired_location_id, []).append(plan)
        event_location_id = min(
            by_location,
            key=lambda location_id: (
                -len(by_location[location_id]),
                location_id,
            ),
        )
        ranked = sorted(
            plans,
            key=lambda plan: (
                plan.desired_location_id != event_location_id,
                plan.actor_id,
            ),
        )
        participant_ids = [
            plan.actor_id
            for plan in ranked[: self.max_event_participants]
        ]
        assignments: list[DayAssignment] = []
        for plan in sorted(plans, key=lambda item: item.actor_id):
            participating = plan.actor_id in participant_ids
            destination = (
                event_location_id
                if participating
                else plan.desired_location_id
            )
            assignments.append(
                DayAssignment(
                    actor_id=plan.actor_id,
                    plan_id=plan.plan_id,
                    destination_location_id=destination,
                    activity_label=(
                        "参与今天的共同事件"
                        if participating
                        else plan.activity_label
                    ),
                    participates_in_event=participating,
                )
            )
        return DmDaySchedule(
            day_index=day_index,
            assignments=assignments,
            selected_event=ScheduledDayEvent(
                event_id=f"{run_id}:day-{day_index}:shared-event",
                location_id=event_location_id,
                participant_ids=participant_ids,
                hook="公共空间出现了一件需要几位 OC 一起处理的小插曲。",
                stakes="不同做法会带来成功、失败和关系变化。",
            ),
        )

    def order_check(
        self,
        intent: EventIntent,
        *,
        day_index: int,
    ) -> DmCheckOrder:
        return DmCheckOrder(
            check_id=f"{intent.intent_id}:check",
            intent_id=intent.intent_id,
            actor_id=intent.actor_id,
            day_index=day_index,
            attribute=intent.requested_attribute,
            dc=10 + ((day_index + len(intent.actor_id)) % 4),
        )

    def apply_actor_responses(
        self,
        *,
        schedule: DmDaySchedule,
        plans: list[OcaDayPlan],
        intents: list[EventIntent],
    ) -> None:
        accepted_ids = {intent.actor_id for intent in intents}
        if not accepted_ids:
            raise DomainInvariantError(
                "the shared event needs at least one willing OC"
            )
        plan_by_actor = {plan.actor_id: plan for plan in plans}
        schedule.selected_event.participant_ids = sorted(accepted_ids)
        for assignment in schedule.assignments:
            if (
                assignment.participates_in_event
                and assignment.actor_id not in accepted_ids
            ):
                plan = plan_by_actor[assignment.actor_id]
                assignment.participates_in_event = False
                assignment.destination_location_id = (
                    plan.desired_location_id
                )
                assignment.activity_label = plan.activity_label

    def narrate(self, checks: list[RpgCheckResult]) -> DmNarrative:
        pieces = [
            (
                f"{check.actor_id} 的{check.attribute}检定"
                f"{'成功' if check.succeeded else '失败'}"
                f"（{check.total} vs DC{check.dc}）"
            )
            for check in checks
        ]
        return DmNarrative(public_summary="；".join(pieces) + "。")


class DeterministicDayScheduler:
    phases: tuple[DayPhase, ...] = (
        "planned",
        "travelling",
        "arrived",
        "in_event",
        "complete",
    )

    def frames(
        self,
        bundle: RuntimeBundle,
        schedule: DmDaySchedule,
    ) -> list[DayScheduleFrame]:
        frames: list[DayScheduleFrame] = []
        for phase in self.phases:
            actors: list[ActorScheduleState] = []
            for assignment in schedule.assignments:
                home = bundle.actor_profile(
                    assignment.actor_id
                ).home_location_id
                at_destination = phase in {"arrived", "in_event", "complete"}
                actors.append(
                    ActorScheduleState(
                        actor_id=assignment.actor_id,
                        location_id=(
                            assignment.destination_location_id
                            if at_destination
                            else home
                        ),
                        activity_label=(
                            "前往目的地"
                            if phase == "travelling"
                            else assignment.activity_label
                        ),
                        in_shared_event=(
                            phase == "in_event"
                            and assignment.participates_in_event
                        ),
                    )
                )
            frames.append(DayScheduleFrame(phase=phase, actors=actors))
        return frames


class DeterministicOcaEventPolicy:
    """Each invited OC independently accepts or declines the event offer."""

    def propose(
        self,
        *,
        bundle: RuntimeBundle,
        schedule: DmDaySchedule,
        memories: dict[OcId, list[ActorMemory]],
    ) -> list[EventIntent]:
        intents: list[EventIntent] = []
        for actor_id in sorted(schedule.selected_event.participant_ids):
            profile = bundle.actor_profile(actor_id)
            declines = any(
                "不参加今天的共同事件" in memory.statement
                for memory in memories.get(actor_id, [])
            )
            if declines:
                continue
            stats = profile.rpg_stats.model_dump()
            attribute = max(
                stats,
                key=lambda key: (stats[key], key),
            )
            intents.append(
                EventIntent(
                    intent_id=(
                        f"{schedule.selected_event.event_id}:{actor_id}"
                    ),
                    actor_id=actor_id,
                    event_id=schedule.selected_event.event_id,
                    goal=profile.goal_refs[0],
                    approach=profile.persona_constraints[0],
                    requested_attribute=attribute,
                    accepted_location_id=(
                        schedule.selected_event.location_id
                    ),
                )
            )
        return intents


class LivingWorldDayCore:
    def __init__(
        self,
        bundle: RuntimeBundle,
        *,
        max_event_participants: int = 3,
        planner: OcaPlannerProvider | None = None,
    ) -> None:
        self.bundle = bundle
        self.planner = planner or DeterministicOcaPlanner()
        self.director = DeterministicDailyDirector(
            max_event_participants=max(
                1,
                min(max_event_participants, len(bundle.actor_profiles)),
            )
        )
        self.scheduler = DeterministicDayScheduler()
        self.event_policy = DeterministicOcaEventPolicy()
        self.rule_kernel = SeededRpgRuleKernel(bundle)
        self.memory_projector = DayMemoryProjector(bundle)

    def plan_day(
        self,
        *,
        day_index: int,
        seed: str,
        memories: dict[OcId, list[ActorMemory]],
    ) -> list[OcaDayPlan]:
        return [
            self.planner.plan(
                profile=profile,
                day_index=day_index,
                seed=seed,
                memories=memories.get(profile.oc_id, []),
            )
            for profile in sorted(
                self.bundle.actor_profiles,
                key=lambda item: item.oc_id,
            )
        ]

    def run_day(
        self,
        *,
        run_id: str,
        day_index: int,
        seed: str,
        memories: dict[OcId, list[ActorMemory]],
        initial_state: WorldState | None = None,
    ) -> LivingWorldDayResult:
        first = self._run_once(
            run_id=run_id,
            day_index=day_index,
            seed=seed,
            memories=memories,
            initial_state=initial_state,
        )
        replay = self._run_once(
            run_id=run_id,
            day_index=day_index,
            seed=seed,
            memories=memories,
            initial_state=initial_state,
        )
        first.replay_verified = (
            first.plans == replay.plans
            and first.schedule == replay.schedule
            and first.intents == replay.intents
            and first.checks == replay.checks
            and first.canonical_event == replay.canonical_event
            and first.final_world_hash == replay.final_world_hash
            and first.memories == replay.memories
            and first.living_memory_seeds == replay.living_memory_seeds
        )
        return first

    def _run_once(
        self,
        *,
        run_id: str,
        day_index: int,
        seed: str,
        memories: dict[OcId, list[ActorMemory]],
        initial_state: WorldState | None,
    ) -> LivingWorldDayResult:
        plans = self.plan_day(
            day_index=day_index,
            seed=seed,
            memories=memories,
        )
        schedule = self.director.arrange(
            run_id=run_id,
            day_index=day_index,
            bundle=self.bundle,
            plans=plans,
        )
        intents = self._event_intents(schedule, memories)
        self.director.apply_actor_responses(
            schedule=schedule,
            plans=plans,
            intents=intents,
        )
        frames = self.scheduler.frames(self.bundle, schedule)
        orders = [
            self.director.order_check(intent, day_index=day_index)
            for intent in intents
        ]
        initial_state = (
            initial_state.model_copy(deep=True)
            if initial_state is not None
            else self.bundle.world.initial_state.model_copy(deep=True)
        )
        checks, adjudication, check_receipts = self.rule_kernel.adjudicate(
            run_id=run_id,
            day_index=day_index,
            seed=seed,
            schedule=schedule,
            plans=plans,
            intents=intents,
            orders=orders,
            state=initial_state,
        )
        final_state = AtomicBatchCommitter(self.bundle.world).commit(
            initial_state,
            adjudication,
        )
        final_hash = canonical_state_checksum(final_state)
        observations = PerspectiveProjector(self.bundle.world).project(
            adjudication.canonical_event,
            final_state,
        )
        day_memories = self.memory_projector.build(
            day_index=day_index,
            schedule=schedule,
            observations=observations,
        )
        living_memory_seeds = self.memory_projector.build_living_seeds(
            day_index=day_index,
            schedule=schedule,
            checks=checks,
            intents=intents,
            canonical_event=adjudication.canonical_event,
            observations=observations,
            memories=day_memories,
        )
        return LivingWorldDayResult(
            run_id=run_id,
            day_index=day_index,
            seed=seed,
            plans=plans,
            schedule=schedule,
            frames=frames,
            intents=intents,
            checks=checks,
            rule_receipts=check_receipts,
            narrative=self.director.narrate(checks),
            canonical_event=adjudication.canonical_event,
            final_state=final_state,
            final_world_hash=final_hash,
            memories=day_memories,
            living_memory_seeds=living_memory_seeds,
            replay_verified=False,
        )

    def _event_intents(
        self,
        schedule: DmDaySchedule,
        memories: dict[OcId, list[ActorMemory]],
    ) -> list[EventIntent]:
        return self.event_policy.propose(
            bundle=self.bundle,
            schedule=schedule,
            memories=memories,
        )


class SeededRpgRuleKernel:
    """The only day-loop component allowed to create effects and Canon."""

    def __init__(self, bundle: RuntimeBundle) -> None:
        self.bundle = bundle

    def resolve_check(
        self,
        seed: str,
        order: DmCheckOrder,
    ) -> RpgCheckResult:
        profile = self.bundle.actor_profile(order.actor_id)
        modifier = getattr(profile.rpg_stats, order.attribute)
        die_roll = (
            int(
                _hash_payload(
                    {
                        "seed": seed,
                        "dayIndex": order.day_index,
                        "actorId": order.actor_id,
                        "attribute": order.attribute,
                        "dc": order.dc,
                    }
                )[:8],
                16,
            )
            % 20
        ) + 1
        total = die_roll + modifier
        return RpgCheckResult(
            check_id=order.check_id,
            actor_id=order.actor_id,
            attribute=order.attribute,
            die_roll=die_roll,
            modifier=modifier,
            total=total,
            dc=order.dc,
            succeeded=total >= order.dc,
        )

    def adjudicate(
        self,
        *,
        run_id: str,
        day_index: int,
        seed: str,
        schedule: DmDaySchedule,
        plans: list[OcaDayPlan],
        intents: list[EventIntent],
        orders: list[DmCheckOrder],
        state: WorldState,
    ) -> tuple[
        list[RpgCheckResult],
        BatchAdjudication,
        list[RuleReceiptProof],
    ]:
        known_locations = {
            location.location_id for location in self.bundle.world.locations
        }
        plan_by_actor = {plan.actor_id: plan for plan in plans}
        intent_by_actor = {intent.actor_id: intent for intent in intents}
        for assignment in schedule.assignments:
            if assignment.destination_location_id not in known_locations:
                raise DomainInvariantError(
                    "DM scheduled an unknown location"
                )
            plan = plan_by_actor.get(assignment.actor_id)
            intent = intent_by_actor.get(assignment.actor_id)
            actor_authorized_destination = (
                plan is not None
                and plan.desired_location_id
                == assignment.destination_location_id
            ) or (
                intent is not None
                and intent.accepted_location_id
                == assignment.destination_location_id
            )
            if not actor_authorized_destination:
                raise DomainInvariantError(
                    "DM cannot move an OC without its plan or event intent"
                )
        intent_by_id = {intent.intent_id: intent for intent in intents}
        for order in orders:
            intent = intent_by_id.get(order.intent_id)
            if (
                intent is None
                or intent.actor_id != order.actor_id
                or intent.requested_attribute != order.attribute
            ):
                raise DomainInvariantError(
                    "DM check order is not bound to an OC intent"
                )
        checks = [self.resolve_check(seed, order) for order in orders]
        checks_by_actor = {check.actor_id: check for check in checks}
        participant_ids = schedule.selected_event.participant_ids
        source_events: dict[str, CanonicalEvent] = {}
        receipts: list[RuleReceiptProof] = []
        check_receipts: list[RuleReceiptProof] = []
        assignment_by_actor = {
            assignment.actor_id: assignment
            for assignment in schedule.assignments
        }
        for actor_id in sorted(assignment_by_actor):
            assignment = assignment_by_actor[actor_id]
            proposal_id = f"{run_id}:day-{day_index}:assignment:{actor_id}"
            effects = [
                StateEffect(
                    op="set",
                    path=f"/actorLocations/{actor_id}",
                    before=state.actor_locations.get(
                        actor_id,
                        self.bundle.actor_profile(actor_id).home_location_id,
                    ),
                    after=assignment.destination_location_id,
                )
            ]
            fact_codes = ["schedule.assignment.completed"]
            atoms: list[PerceptualAtom] = []
            rule_id = "schedule-location-v1"
            rule_label = "日程地点合法性规则"
            outcome: Literal["success", "blocked"] = "success"
            if actor_id in checks_by_actor:
                check = checks_by_actor[actor_id]
                if len(participant_ids) > 1:
                    target_id = self._next_participant(
                        actor_id,
                        participant_ids,
                    )
                    relation = state.relationships[actor_id][target_id]
                    dimension = "trust" if check.succeeded else "tension"
                    before = getattr(relation, dimension)
                    after = min(3, before + 1)
                    effects.append(
                        StateEffect(
                            op="inc",
                            path=(
                                f"/relationships/{actor_id}/"
                                f"{target_id}/{dimension}"
                            ),
                            before=before,
                            after=after,
                            by=after - before,
                        )
                    )
                fact_codes.append(
                    "rpg.check.succeeded"
                    if check.succeeded
                    else "rpg.check.failed"
                )
                atoms.append(
                    PerceptualAtom(
                        atom_id=f"{check.check_id}:result",
                        code=fact_codes[-1],
                        modality="sight",
                        location_id=schedule.selected_event.location_id,
                        line_of_sight_required=True,
                        data={
                            "actorId": check.actor_id,
                            "observableAction": "上前尝试处理眼前的问题",
                            "observableOutcome": (
                                "成功推动了局面"
                                if check.succeeded
                                else "没有成功改变局面"
                            ),
                        },
                    )
                )
                proposal_id = check.check_id
                rule_id = "rpg-seeded-d20-v1"
                rule_label = "种子化 D20 检定"
                outcome = "success" if check.succeeded else "blocked"
            source_event = CanonicalEvent(
                canonical_event_id=f"{proposal_id}:source",
                sequence=day_index,
                kind="action.resolved",
                actor_id=actor_id,
                decision_id=f"{proposal_id}:decision",
                fact_codes=fact_codes,
                effects=effects,
                perceptual_atoms=atoms,
            )
            evidence = _hash_payload(
                {
                    "seed": seed,
                    "dayIndex": day_index,
                    "proposalId": proposal_id,
                    "ruleId": rule_id,
                    "effects": [
                        effect.model_dump(mode="json", by_alias=True)
                        for effect in effects
                    ],
                }
            )
            receipt = RuleReceiptProof(
                proposal_id=proposal_id,
                status="applied",
                outcome=outcome,
                rule_id=rule_id,
                rule_label=rule_label,
                reason_codes=[
                    "CHECK_PASSED" if outcome == "success" else "CHECK_FAILED"
                ],
                deterministic_evidence=evidence,
                evidence_label=(
                    "同一 seed、属性、DC 与世界版本会得到同一裁定。"
                ),
                effects=effects,
            )
            source_events[proposal_id] = source_event
            receipts.append(receipt)
            if rule_id == "rpg-seeded-d20-v1":
                check_receipts.append(receipt)
        ordered_events = [
            source_events[proposal_id]
            for proposal_id in sorted(source_events)
        ]
        canonical_event = CanonicalEvent(
            canonical_event_id=f"{run_id}:day-{day_index}:canonical-event",
            sequence=day_index,
            kind="action.resolved",
            decision_id=f"{run_id}:day-{day_index}:batch-decision",
            fact_codes=list(
                dict.fromkeys(
                    fact
                    for event in ordered_events
                    for fact in event.fact_codes
                )
            ),
            effects=[
                effect
                for event in ordered_events
                for effect in event.effects
            ],
            perceptual_atoms=[
                atom
                for event in ordered_events
                for atom in event.perceptual_atoms
            ],
        )
        return (
            checks,
            BatchAdjudication(
                proof=ResolutionBatchProof(
                    batch_id=f"{run_id}:day-{day_index}:rule-batch",
                    conflict_set_ids=[],
                    seed=seed,
                    receipts=receipts,
                ),
                canonical_event=canonical_event,
                source_event_by_proposal=source_events,
            ),
            check_receipts,
        )

    @staticmethod
    def _next_participant(
        actor_id: OcId,
        participant_ids: list[OcId],
    ) -> OcId:
        ordered = sorted(participant_ids)
        index = ordered.index(actor_id)
        return ordered[(index + 1) % len(ordered)]


class DayMemoryProjector:
    def __init__(self, bundle: RuntimeBundle) -> None:
        self.bundle = bundle

    def build(
        self,
        *,
        day_index: int,
        schedule: DmDaySchedule,
        observations,
    ) -> dict[OcId, list[ActorMemory]]:
        participant_ids = set(schedule.selected_event.participant_ids)
        result: dict[OcId, list[ActorMemory]] = {}
        for profile in self.bundle.actor_profiles:
            observation = observations[profile.oc_id]
            if profile.oc_id in participant_ids:
                own_fact = next(
                    (
                        fact
                        for fact in observation.facts
                        if fact.data.get("actorId") == profile.oc_id
                    ),
                    None,
                )
                own_result = (
                    "成功"
                    if own_fact is not None
                    and own_fact.code == "rpg.check.succeeded"
                    else "失败"
                )
                other_count = sum(
                    fact.data.get("actorId") != profile.oc_id
                    for fact in observation.facts
                )
                statement = (
                    f"我按“{profile.persona_constraints[0]}”处理了"
                    f"今天的共同事件；我的尝试{own_result}，"
                    f"也亲眼看见了另外 {other_count} 个行动结果。"
                )
                source_ids = (
                    [observation.observation_id]
                    if observation.facts
                    else []
                )
            else:
                statement = "我没有亲历共同事件，今天只完成了自己的日常安排。"
                source_ids = []
            result[profile.oc_id] = [
                ActorMemory(
                    memory_id=(
                        f"memory:day-{day_index}:{profile.oc_id}"
                    ),
                    actor_id=profile.oc_id,
                    source_round=day_index - 1,
                    kind="observedFact",
                    statement=statement,
                    source_observation_ids=source_ids,
                )
            ]
        return result

    def build_living_seeds(
        self,
        *,
        day_index: int,
        schedule: DmDaySchedule,
        checks: list[RpgCheckResult],
        intents: list[EventIntent],
        canonical_event: CanonicalEvent,
        observations,
        memories: dict[OcId, list[ActorMemory]],
    ) -> list[LivingMemorySeed]:
        checks_by_actor = {check.actor_id: check for check in checks}
        intents_by_actor = {intent.actor_id: intent for intent in intents}
        attribute_labels = {
            "intellect": "认真",
            "presence": "叛逆",
            "athletics": "体能",
            "insight": "灵感",
        }
        location = self.bundle.world.location(
            schedule.selected_event.location_id
        )

        def goal_text(actor_id: OcId, goal_ref: str) -> str:
            character = self.bundle.world.character(actor_id)
            return next(
                (
                    goal.text.rstrip("。！？")
                    for goal in character.goals
                    if goal.goal_id == goal_ref
                ),
                "推进自己在意的目标",
            )

        def action_moment(
            actor_id: OcId,
            *,
            include_private_motive: bool,
        ) -> PovActionMoment | None:
            check = checks_by_actor.get(actor_id)
            if check is None:
                return None
            intent = intents_by_actor.get(actor_id)
            return PovActionMoment(
                actor_id=actor_id,
                actor_name=self.bundle.world.character(actor_id).name,
                goal_text=(
                    goal_text(actor_id, intent.goal)
                    if include_private_motive and intent is not None
                    else None
                ),
                approach=(
                    intent.approach.rstrip("。！？")
                    if include_private_motive and intent is not None
                    else None
                ),
                attribute_label=attribute_labels[check.attribute],
                die_roll=check.die_roll,
                modifier=check.modifier,
                total=check.total,
                dc=check.dc,
                succeeded=check.succeeded,
            )

        def relationship_consequences(actor_id: OcId) -> list[str]:
            summaries: list[str] = []
            prefix = f"/relationships/{actor_id}/"
            dimension_labels = {
                "trust": "信任",
                "affinity": "亲近",
                "tension": "紧张",
            }
            for effect in canonical_event.effects:
                if not effect.path.startswith(prefix):
                    continue
                _, _, _, target_id, dimension = effect.path.split("/")
                target_name = self.bundle.world.character(target_id).name
                direction = "增加" if effect.after > effect.before else "减少"
                summaries.append(
                    f"我对{target_name} 的{dimension_labels[dimension]}{direction}了"
                )
            return summaries

        def episode_material(actor_id: OcId) -> PovEpisodeMaterial:
            observation = observations[actor_id]
            observed_actor_ids = list(
                dict.fromkeys(
                    fact.data.get("actorId")
                    for fact in observation.facts
                    if fact.data.get("actorId") in checks_by_actor
                    and fact.data.get("actorId") != actor_id
                )
            )
            def observed_outcome(
                observed_actor_id: OcId,
            ) -> PovObservedOutcome | None:
                check = checks_by_actor.get(observed_actor_id)
                if check is None:
                    return None
                return PovObservedOutcome(
                    actor_id=observed_actor_id,
                    actor_name=self.bundle.world.character(
                        observed_actor_id
                    ).name,
                    action_summary="上前尝试处理眼前的问题",
                    outcome_summary=(
                        "成功推动了局面"
                        if check.succeeded
                        else "没有成功改变局面"
                    ),
                )

            return PovEpisodeMaterial(
                location_id=location.location_id,
                location_name=location.name,
                hook=schedule.selected_event.hook,
                stakes=schedule.selected_event.stakes,
                own_action=action_moment(
                    actor_id,
                    include_private_motive=True,
                ),
                witnessed_actions=[
                    action
                    for observed_actor_id in observed_actor_ids
                    if (
                        action := observed_outcome(observed_actor_id)
                    )
                    is not None
                ],
                consequence_summaries=relationship_consequences(actor_id),
            )

        def first_person_summary(material: PovEpisodeMaterial) -> str:
            own_action = material.own_action
            if own_action is None:
                return (
                    f"今天我去了{material.location_name}，没有亲历共同事件，"
                    "只完成了自己的日常安排。"
                )
            result = "成功" if own_action.succeeded else "失败"
            witnessed = "".join(
                (
                    f" 我看见{action.actor_name}"
                    f"{action.action_summary}，"
                    f"{action.outcome_summary}。"
                )
                for action in material.witnessed_actions
            )
            consequences = "".join(
                f" {summary}。"
                for summary in material.consequence_summaries
            )
            return (
                f"今天我到了{material.location_name}。{material.hook}"
                f"事情的风险是：{material.stakes}"
                f"我想{own_action.goal_text}，于是决定{own_action.approach}，"
                f"用{own_action.attribute_label}解决。"
                f"D20 掷出 {own_action.die_roll}，加上"
                f" {own_action.modifier:+d} 修正，总计 {own_action.total}，"
                f"对抗 DC {own_action.dc}，结果{result}。"
                f"{witnessed}{consequences}"
            )

        seeds: list[LivingMemorySeed] = []
        for actor_id, actor_memories in sorted(memories.items()):
            memory = actor_memories[0]
            check = checks_by_actor.get(actor_id)
            intent = intents_by_actor.get(actor_id)
            material = episode_material(actor_id)
            memory.statement = first_person_summary(material)
            fact_codes = (
                [
                    (
                        "rpg.check.succeeded"
                        if check.succeeded
                        else "rpg.check.failed"
                    )
                ]
                if check is not None
                else []
            )
            seeds.append(
                LivingMemorySeed(
                    actor_id=actor_id,
                    day_index=day_index,
                    episode_ref=memory.memory_id,
                    scene_id=schedule.selected_event.event_id,
                    first_person_summary=memory.statement,
                    source_event_ids=[
                        canonical_event.canonical_event_id
                    ],
                    source_observation_ids=(
                        memory.source_observation_ids
                    ),
                    perceived_fact_codes=fact_codes,
                    belief_proposition=(
                        (
                            f"在{material.location_name}遇到类似问题时，"
                            f"用{material.own_action.attribute_label}并坚持"
                            f"“{material.own_action.approach}”能够奏效"
                        )
                        if check is not None
                        and material.own_action is not None
                        else None
                    ),
                    belief_supported=(
                        check.succeeded if check is not None else None
                    ),
                    situation_tag=(
                        "shared-event"
                        if check is not None
                        else "daily-routine"
                    ),
                    behavior_tag=(
                        f"use-{intent.requested_attribute}"
                        if intent is not None
                        else "keep-own-routine"
                    ),
                    emotional_valence=(
                        "confident"
                        if check is not None and check.succeeded
                        else "frustrated"
                        if check is not None
                        else "steady"
                    ),
                    salience=0.8 if check is not None else 0.35,
                    episode_material=material,
                )
            )
        return seeds

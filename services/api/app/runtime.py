from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from app.domain.models import (
    Belief,
    CanonicalEvent,
    CharacterProposal,
    DmProposal,
    OcId,
    RuleDecision,
    Resolution,
    ResolutionReceipt,
    PrivateOs,
    Utterance,
    UtteranceProposal,
    WorldDefinition,
    WorldState,
)
from app.domain.encounters import EncounterEngine
from app.domain.living_world import (
    ActorMemory,
    ActorOutput,
    ActorPolicyContext,
    ActorPolicyProvider,
    DeterministicActorPolicyProvider,
    DeterministicSceneDirector,
    EpistemicView,
    LivingWorldRound,
    LivingWorldRunResult,
    ResilientActorPolicyProvider,
    ResolvedActorTurn,
    RuntimeBundle,
    StructuredActorTurn,
    UnknownArea,
    intent_to_character_action,
)
from app.domain.perspective import PerspectiveProjector
from app.domain.policies import DeterministicMindPolicy
from app.domain.product_projections import (
    LivingMemoryStoreDTO,
    OwnerPrivateOsDTO,
    ProductProjectionBuilder,
)
from app.domain.reducer import canonical_state_checksum, reduce_canonical_events
from app.domain.rules import ResolutionAuthority, RuleKernel, _fingerprint
from app.domain.scheduler import DeterministicStepScheduler, ScheduledStep
from app.domain.transactional_living_world import (
    LivingWorldProofDTO,
    ReplayAuditor,
    TransactionalLivingWorldCore,
)
from app.errors import (
    DomainInvariantError,
    RuntimeExecutionError,
    SessionNotFound,
)
from app.storage import SQLiteStorage


class DemoRuntime:
    def __init__(
        self,
        storage: SQLiteStorage,
        world: WorldDefinition,
        *,
        mind_policy: DeterministicMindPolicy | None = None,
    ) -> None:
        self.storage = storage
        self.base_world = world
        self.mind_policy = mind_policy or DeterministicMindPolicy()

    def create_and_run(
        self,
        *,
        session_id: str,
        consent_required: bool,
    ) -> dict[str, Any]:
        try:
            return self._create_and_run_unchecked(
                session_id=session_id,
                consent_required=consent_required,
            )
        except sqlite3.IntegrityError:
            raise
        except Exception as error:
            try:
                self._mark_failed_session(session_id)
            except SessionNotFound:
                pass
            raise RuntimeExecutionError("Runtime execution failed.") from error

    def _create_and_run_unchecked(
        self,
        *,
        session_id: str,
        consent_required: bool,
    ) -> dict[str, Any]:
        world = self._world_with_consent(consent_required)
        state = world.initial_state.model_copy(deep=True)
        state.status = "running"
        self.storage.create_session(
            session_id=session_id,
            world_id=world.world_id,
            seed=world.event_seed,
            consent_required=consent_required,
            state=state.model_dump(by_alias=True),
        )
        run = _RunContext(self.storage, world, state, session_id)
        kernel = run.rule_kernel()

        run.start_tick(0, "oc-devil")
        dm_proposal = DmProposal(
            proposal_id=f"{session_id}-dm-pressure",
            template_id="closing-threshold",
            kind="PRESSURE",
            params={"countdown": 3},
        )
        run.register_proposal(dm_proposal)
        run.emit(
            "proposal.dm.created",
            {"scope": "tech"},
            {"proposal": dm_proposal.model_dump(by_alias=True)},
        )
        dm_result = kernel.resolve_dm(
            dm_proposal,
            run.state,
            sequence=run.next_canonical_sequence,
            decision_id=f"{session_id}-decision-dm-pressure",
            canonical_event_id=f"{session_id}-canonical-dm-pressure",
        )
        run.emit_decision(dm_result.decision)
        if dm_result.event is None:
            raise DomainInvariantError("demo DM proposal must resolve")
        run.commit_resolution(dm_result, visibility={"scope": "public"})

        take_proposal = CharacterProposal.model_validate(
            {
                "proposalId": f"{session_id}-take-key",
                "actorId": "oc-devil",
                "action": {"kind": "TAKE", "objectId": "threshold-key"},
                "motivationRefs": ["goal-devil-open-door"],
                "proposedPublicLine": "时间不多了，我先拿钥匙。",
            }
        )
        run.register_proposal(take_proposal)
        run.emit(
            "proposal.character.created",
            {"scope": "tech"},
            {"proposal": take_proposal.model_dump(by_alias=True, exclude_none=True)},
        )
        take_result = kernel.resolve_character(
            take_proposal,
            run.state,
            sequence=run.next_canonical_sequence,
            decision_id=f"{session_id}-decision-take-key",
            canonical_event_id=f"{session_id}-canonical-take-key",
        )
        run.emit_decision(take_result.decision)
        if take_result.event is None:
            raise DomainInvariantError("demo TAKE proposal must resolve")
        run.commit_resolution(take_result, visibility={"scope": "public"})
        pivotal_event = take_result.event if take_result.decision.outcome == "success" else None
        run.complete_tick()

        run.start_tick(1, "oc-user")
        give_proposal = CharacterProposal.model_validate(
            {
                "proposalId": f"{session_id}-give-key",
                "actorId": "oc-user",
                "action": {
                    "kind": "GIVE",
                    "objectId": "threshold-key",
                    "recipientId": "oc-devil",
                },
                "motivationRefs": [
                    "goal-user-open-door",
                    "owner-advice-trust-devil",
                ],
                "proposedPublicLine": "这次由我决定把钥匙交给你。",
            }
        )
        run.register_proposal(give_proposal)
        run.emit(
            "proposal.character.created",
            {"scope": "tech"},
            {"proposal": give_proposal.model_dump(by_alias=True, exclude_none=True)},
        )
        give_result = kernel.resolve_character(
            give_proposal,
            run.state,
            sequence=run.next_canonical_sequence,
            decision_id=f"{session_id}-decision-give-key",
            canonical_event_id=f"{session_id}-canonical-give-key",
        )
        run.emit_decision(give_result.decision)
        if give_result.event is not None:
            run.commit_resolution(give_result, visibility={"scope": "public"})
            pivotal_event = give_result.event
        if pivotal_event is None:
            raise DomainInvariantError("demo requires a pivotal key event")

        beliefs: dict[str, Any] = {}
        observations = PerspectiveProjector(world).project(pivotal_event)
        for oc_id in ("oc-user", "oc-angel", "oc-devil"):
            observation = observations[oc_id]
            visibility = (
                {"scope": "owner", "ocId": oc_id}
                if oc_id == "oc-user"
                else {"scope": "actor", "ocId": oc_id}
            )
            run.emit(
                "observation.created",
                visibility,
                {
                    "observation": observation.model_dump(
                        by_alias=True,
                        exclude_none=True,
                    )
                },
                causation_id=pivotal_event.canonical_event_id,
            )
            mind = self.mind_policy.interpret(observation)
            beliefs[oc_id] = mind.belief
            run.emit(
                "belief.updated",
                visibility,
                {"belief": mind.belief.model_dump(by_alias=True)},
                causation_id=observation.observation_id,
            )
            if mind.private_os is not None:
                run.emit(
                    "privateOs.created",
                    {"scope": "owner", "ocId": oc_id},
                    {
                        "privateOs": mind.private_os.model_dump(
                            by_alias=True,
                            exclude_none=True,
                        )
                    },
                    causation_id=mind.belief.belief_id,
                )
        run.complete_tick()

        run.start_tick(2, "oc-angel")
        angel_proposal = UtteranceProposal(
            proposal_id=f"{session_id}-angel-utterance",
            actor_id="oc-angel",
            text="恶魔，你拿走了不属于你的钥匙。",
            audience="world",
            based_on_belief_ids=[beliefs["oc-angel"].belief_id],
        )
        self._resolve_and_emit_utterance(run, kernel, angel_proposal, "uncertain")

        user_proposal = UtteranceProposal(
            proposal_id=f"{session_id}-user-utterance",
            actor_id="oc-user",
            text="钥匙已经处理好了。",
            audience="publicUi",
            based_on_belief_ids=[beliefs["oc-user"].belief_id],
        )
        self._resolve_and_emit_utterance(run, kernel, user_proposal, "withholding")
        run.complete_tick()

        run.finish_session()
        return self.storage.get_session(session_id)

    def _mark_failed_session(self, session_id: str) -> None:
        session = self.storage.get_session(session_id)
        if session["status"] != "running":
            return
        state = WorldState.model_validate(session["state"])
        state.status = "failed"
        cursor = session["lastCursor"] + 1
        emitted_at = datetime(2026, 7, 24, tzinfo=UTC) + timedelta(
            seconds=cursor
        )
        envelope = {
            "schemaVersion": 1,
            "eventId": f"{session_id}-stream-{cursor:03d}",
            "cursor": cursor,
            "sessionId": session_id,
            "tickIndex": state.tick_index,
            "emittedAt": emitted_at.isoformat().replace("+00:00", "Z"),
            "type": "runtime.error",
            "visibility": {"scope": "public"},
            "payload": {
                "code": "RUNTIME_EXECUTION_FAILED",
                "message": "Runtime execution failed.",
                "recoverable": False,
            },
        }
        self.storage.append_event_and_fail_session(
            session_id,
            envelope,
            state=state.model_dump(by_alias=True),
            checksum=canonical_state_checksum(state),
        )

    def reconstruct(self, session_id: str) -> WorldState:
        session = self.storage.get_session(session_id)
        canonical_payloads = [
            event["payload"]["event"]
            for event in self.storage.get_events(session_id)
            if event["type"] == "canonical.event.committed"
        ]
        state = self.fold_canonical_events(canonical_payloads)
        state.tick_index = max(
            event["tickIndex"] for event in self.storage.get_events(session_id)
        )
        state.status = session["status"]
        return state

    def fold_canonical_events(
        self,
        canonical_payloads: list[dict[str, Any]],
    ) -> WorldState:
        initial = self.base_world.initial_state.model_copy(deep=True)
        canonical_events = [
            CanonicalEvent.model_validate(payload)
            for payload in canonical_payloads
        ]
        return reduce_canonical_events(initial, canonical_events)

    def _resolve_and_emit_utterance(
        self,
        run: "_RunContext",
        kernel: RuleKernel,
        proposal: UtteranceProposal,
        truth_posture: str,
    ) -> None:
        run.register_proposal(proposal)
        run.emit(
            "proposal.utterance.created",
            {"scope": "tech"},
            {"proposal": proposal.model_dump(by_alias=True)},
            causation_id=proposal.based_on_belief_ids[0],
        )
        result = kernel.resolve_utterance(
            proposal,
            run.state,
            sequence=run.next_canonical_sequence,
            decision_id=f"{proposal.proposal_id}-decision",
            canonical_event_id=f"{proposal.proposal_id}-canonical",
        )
        run.emit_decision(result.decision)
        if result.event is None:
            raise DomainInvariantError("demo utterance proposal must resolve")
        run.commit_resolution(result, visibility={"scope": "public"})
        utterance = Utterance(
            utterance_id=f"{proposal.proposal_id}-artifact",
            oc_id=proposal.actor_id,
            canonical_event_id=result.event.canonical_event_id,
            audience=proposal.audience,
            text=proposal.text,
            based_on_belief_ids=proposal.based_on_belief_ids,
            truth_posture=truth_posture,
        )
        run.emit(
            "utterance.created",
            {"scope": "public"},
            {"utterance": utterance.model_dump(by_alias=True)},
            causation_id=result.event.canonical_event_id,
        )

    def _world_with_consent(self, consent_required: bool) -> WorldDefinition:
        world = self.base_world.model_copy(deep=True)
        rule = world.rule("CONSENTED_TRANSFER_ONLY")
        if rule is None:
            raise DomainInvariantError("consent rule is required by the demo")
        rule.params["consentRequired"] = consent_required
        return world


class LivingWorldRuntime:
    """Two-round, replayable Living World Core v0.1."""

    def __init__(
        self,
        storage: SQLiteStorage,
        bundle: RuntimeBundle,
        *,
        actor_provider: ActorPolicyProvider | None = None,
        director: DeterministicSceneDirector | None = None,
    ) -> None:
        self.storage = storage
        self.bundle = bundle
        self.primary_provider = (
            actor_provider or DeterministicActorPolicyProvider()
        )
        self.provider = ResilientActorPolicyProvider(self.primary_provider)
        self.director = director or DeterministicSceneDirector()
        self.encounter_engine = EncounterEngine()

    def create_and_run(
        self,
        *,
        session_id: str,
        seed: str | None = None,
    ) -> LivingWorldRunResult:
        selected_seed = seed or self.bundle.default_seed
        world = self.bundle.world.model_copy(deep=True)
        state = world.initial_state.model_copy(deep=True)
        state.status = "running"
        self.storage.create_session(
            session_id=session_id,
            world_id=world.world_id,
            seed=selected_seed,
            consent_required=True,
            state=state.model_dump(by_alias=True),
        )
        run = _RunContext(self.storage, world, state, session_id)
        kernel = run.rule_kernel()
        projector = PerspectiveProjector(world)
        memories = self._initial_memories()
        belief_ids: dict[OcId, list[str]] = {
            actor_id: [] for actor_id in memories
        }
        canonical_ledger: list[CanonicalEvent] = []
        rounds: list[LivingWorldRound] = []
        fallback_count = 0

        for round_index in range(self.bundle.round_count):
            round_facts: dict[OcId, list[Any]] = {
                actor_id: [] for actor_id in memories
            }
            round_inferences: dict[OcId, list[ActorMemory]] = {
                actor_id: [] for actor_id in memories
            }
            round_unknowns: dict[OcId, list[UnknownArea]] = {
                actor_id: [] for actor_id in memories
            }
            turns: list[ResolvedActorTurn] = []
            outputs: list[ActorOutput] = []
            scheduler = self._round_scheduler(round_index)

            for turn_ordinal, step in enumerate(scheduler.drain()):
                tick_index = round_index * len(memories) + turn_ordinal
                run.start_tick(tick_index, step.actor_id)
                frame = self._encounter_for(run, step, round_index)
                context = self._actor_context(
                    run,
                    frame.affordances,
                    memories,
                    step.actor_id,
                    selected_seed,
                    round_index,
                )
                provider_decision = self.provider.propose_turn(context)
                if provider_decision.fallback_used:
                    fallback_count += 1
                actor_turn = provider_decision.turn
                affordance = next(
                    (
                        candidate
                        for candidate in frame.affordances
                        if candidate.affordance_id
                        == actor_turn.intent.affordance_id
                    ),
                    None,
                )
                if affordance is None:
                    raise DomainInvariantError(
                        "provider selected an unknown affordance"
                    )

                if actor_turn.intent.kind == "UTTERANCE":
                    receipt, output, event = self._resolve_expression(
                        run,
                        kernel,
                        actor_turn,
                        belief_ids[step.actor_id],
                        affordance=affordance,
                        intent_is_expression=True,
                    )
                    canonical_ledger.append(event)
                    self._project_event(
                        run,
                        projector,
                        event,
                        round_index,
                        memories,
                        belief_ids,
                        round_facts,
                        round_inferences,
                        round_unknowns,
                    )
                else:
                    receipt, event = self._resolve_character_intent(
                        run,
                        kernel,
                        actor_turn,
                        affordance,
                    )
                    canonical_ledger.append(event)
                    self._project_event(
                        run,
                        projector,
                        event,
                        round_index,
                        memories,
                        belief_ids,
                        round_facts,
                        round_inferences,
                        round_unknowns,
                    )
                    _, output, expression_event = self._resolve_expression(
                        run,
                        kernel,
                        actor_turn,
                        belief_ids[step.actor_id],
                    )
                    canonical_ledger.append(expression_event)
                    self._project_event(
                        run,
                        projector,
                        expression_event,
                        round_index,
                        memories,
                        belief_ids,
                        round_facts,
                        round_inferences,
                        round_unknowns,
                    )

                turns.append(
                    ResolvedActorTurn(
                        actor_id=step.actor_id,
                        intent=actor_turn.intent,
                        resolution_receipt=receipt,
                        input_memory_count=len(context.memories),
                        provider_id=(
                            self.provider.fallback.provider_id
                            if provider_decision.fallback_used
                            else self.primary_provider.provider_id
                        ),
                        fallback_used=provider_decision.fallback_used,
                    )
                )
                outputs.append(output)
                run.complete_tick()

            rounds.append(
                LivingWorldRound(
                    round_index=round_index,
                    turns=turns,
                    epistemic_views=[
                        EpistemicView(
                            actor_id=actor_id,
                            observed_facts=round_facts[actor_id],
                            inferences=round_inferences[actor_id],
                            unknowns=round_unknowns[actor_id],
                            memories=list(memories[actor_id]),
                        )
                        for actor_id in sorted(memories)
                    ],
                    outputs=outputs,
                    relationship_snapshot=run.state.relationships,
                    location_snapshot=run.state.actor_locations,
                )
            )

        run.finish_session()
        session = self.storage.get_session(session_id)
        semantic_trace = self._semantic_trace(rounds)
        replay_fingerprint = hashlib.sha256(
            json.dumps(
                semantic_trace,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return LivingWorldRunResult(
            session_id=session_id,
            bundle_id=self.bundle.bundle_id,
            seed=selected_seed,
            status="completed",
            rounds=rounds,
            canonical_ledger=canonical_ledger,
            final_state=session["state"],
            provider_fallback_count=fallback_count,
            replay_fingerprint=replay_fingerprint,
            semantic_trace=semantic_trace,
        )


    def _initial_memories(self) -> dict[OcId, list[ActorMemory]]:
        return {
            profile.oc_id: [
                ActorMemory(
                    memory_id=f"prior:{profile.oc_id}:{index}",
                    actor_id=profile.oc_id,
                    source_round=-1,
                    kind="prior",
                    statement=statement,
                    source_observation_ids=[],
                )
                for index, statement in enumerate(profile.initial_memories)
            ]
            for profile in self.bundle.actor_profiles
        }

    def _round_scheduler(
        self,
        round_index: int,
    ) -> DeterministicStepScheduler:
        return DeterministicStepScheduler(
            ScheduledStep(
                step_id=f"round-{round_index}:{profile.oc_id}",
                due_tick=round_index,
                priority=1,
                actor_id=profile.oc_id,
                reason="finite-living-world-round",
            )
            for profile in self.bundle.actor_profiles
        )

    def _encounter_for(
        self,
        run: "_RunContext",
        step: ScheduledStep,
        round_index: int,
    ):
        actor = run.world.character(step.actor_id)
        location_id = run.state.actor_locations.get(
            step.actor_id,
            actor.location_id,
        )
        participants = [
            character.oc_id
            for character in run.world.characters
            if run.state.actor_locations.get(
                character.oc_id,
                character.location_id,
            )
            == location_id
        ]
        pressure = self.director.organize(
            round_index=round_index,
            actor_id=step.actor_id,
            location_id=location_id,
            participant_ids=participants,
        )
        frame = self.encounter_engine.generate(
            run.world,
            run.state,
            step,
            [pressure],
        )
        if not frame.affordances:
            raise DomainInvariantError(
                "director produced no legal actor opportunities"
            )
        return frame

    def _actor_context(
        self,
        run: "_RunContext",
        affordances,
        memories: dict[OcId, list[ActorMemory]],
        actor_id: OcId,
        seed: str,
        round_index: int,
    ) -> ActorPolicyContext:
        actor = run.world.character(actor_id)
        location_id = run.state.actor_locations.get(
            actor_id,
            actor.location_id,
        )
        return ActorPolicyContext(
            seed=seed,
            round_index=round_index,
            actor_id=actor_id,
            own_location_id=location_id,
            own_location_layer=run.world.location(location_id).layer,
            profile=self.bundle.actor_profile(actor_id),
            relationships=run.state.relationships.get(actor_id, {}),
            memories=list(memories[actor_id]),
            affordances=affordances,
        )

    def _resolve_character_intent(
        self,
        run: "_RunContext",
        kernel: RuleKernel,
        actor_turn: StructuredActorTurn,
        affordance,
    ) -> tuple[ResolutionReceipt, CanonicalEvent]:
        proposal = CharacterProposal.model_validate(
            {
                "proposalId": (
                    f"{run.session_id}:proposal:"
                    f"{run.next_canonical_sequence}"
                ),
                "actorId": actor_turn.intent.actor_id,
                "action": intent_to_character_action(actor_turn.intent),
                "motivationRefs": actor_turn.intent.motivation_refs,
            }
        )
        self.encounter_engine.assert_proposal_allowed(affordance, proposal)
        run.register_proposal(proposal)
        run.emit(
            "proposal.character.created",
            {"scope": "tech"},
            {"proposal": proposal.model_dump(by_alias=True, exclude_none=True)},
        )
        result = kernel.resolve_character(
            proposal,
            run.state,
            sequence=run.next_canonical_sequence,
            decision_id=f"{proposal.proposal_id}:decision",
            canonical_event_id=f"{proposal.proposal_id}:canonical",
        )
        run.emit_decision(result.decision)
        if result.event is None:
            raise DomainInvariantError(
                "selected character affordance did not resolve"
            )
        receipt = run.commit_resolution(
            result,
            visibility={"scope": "public"},
        )
        return receipt, result.event

    def _resolve_expression(
        self,
        run: "_RunContext",
        kernel: RuleKernel,
        actor_turn: StructuredActorTurn,
        belief_ids: list[str],
        *,
        affordance=None,
        intent_is_expression: bool = False,
    ) -> tuple[ResolutionReceipt, ActorOutput, CanonicalEvent]:
        proposal = UtteranceProposal(
            proposal_id=(
                f"{run.session_id}:expression:"
                f"{run.next_canonical_sequence}"
            ),
            actor_id=actor_turn.intent.actor_id,
            text=actor_turn.public_text,
            audience="publicUi",
            based_on_belief_ids=belief_ids[-3:],
        )
        if intent_is_expression:
            if affordance is None:
                raise DomainInvariantError(
                    "expression intent requires an affordance"
                )
            self.encounter_engine.assert_proposal_allowed(
                affordance,
                proposal,
            )
        run.register_proposal(proposal)
        run.emit(
            "proposal.utterance.created",
            {"scope": "tech"},
            {"proposal": proposal.model_dump(by_alias=True)},
        )
        result = kernel.resolve_utterance(
            proposal,
            run.state,
            sequence=run.next_canonical_sequence,
            decision_id=f"{proposal.proposal_id}:decision",
            canonical_event_id=f"{proposal.proposal_id}:canonical",
        )
        run.emit_decision(result.decision)
        if result.event is None:
            raise DomainInvariantError("public expression did not resolve")
        receipt = run.commit_resolution(
            result,
            visibility={"scope": "public"},
        )
        public_expression = Utterance(
            utterance_id=f"{proposal.proposal_id}:artifact",
            oc_id=proposal.actor_id,
            canonical_event_id=result.event.canonical_event_id,
            audience=proposal.audience,
            text=proposal.text,
            based_on_belief_ids=proposal.based_on_belief_ids,
            truth_posture=actor_turn.truth_posture,
        )
        private_os = PrivateOs(
            private_os_id=f"{proposal.proposal_id}:private-os",
            oc_id=proposal.actor_id,
            canonical_event_id=result.event.canonical_event_id,
            text=actor_turn.private_inner_os_text,
            based_on_belief_ids=proposal.based_on_belief_ids,
        )
        run.emit(
            "utterance.created",
            {"scope": "public"},
            {"utterance": public_expression.model_dump(by_alias=True)},
            causation_id=result.event.canonical_event_id,
        )
        run.emit(
            "privateOs.created",
            {"scope": "owner", "ocId": proposal.actor_id},
            {"privateOs": private_os.model_dump(by_alias=True)},
            causation_id=result.event.canonical_event_id,
        )
        return (
            receipt,
            ActorOutput(
                actor_id=proposal.actor_id,
                public_expression=public_expression,
                private_inner_os=private_os,
            ),
            result.event,
        )

    def _project_event(
        self,
        run: "_RunContext",
        projector: PerspectiveProjector,
        event: CanonicalEvent,
        round_index: int,
        memories: dict[OcId, list[ActorMemory]],
        belief_ids: dict[OcId, list[str]],
        round_facts: dict[OcId, list[Any]],
        round_inferences: dict[OcId, list[ActorMemory]],
        round_unknowns: dict[OcId, list[UnknownArea]],
    ) -> None:
        observations = projector.project(event, run.state)
        for actor_id, observation in observations.items():
            visibility = {"scope": "actor", "ocId": actor_id}
            run.emit(
                "observation.created",
                visibility,
                {"observation": observation.model_dump(by_alias=True)},
                causation_id=event.canonical_event_id,
            )
            round_facts[actor_id].extend(observation.facts)
            for fact in observation.facts:
                memory = ActorMemory(
                    memory_id=(
                        f"memory:{round_index}:{actor_id}:{fact.atom_id}"
                    ),
                    actor_id=actor_id,
                    source_round=round_index,
                    kind="observedFact",
                    statement=fact.code,
                    source_observation_ids=[observation.observation_id],
                )
                memories[actor_id].append(memory)

            belief = Belief(
                belief_id=f"belief:{observation.observation_id}",
                oc_id=actor_id,
                predicate=(
                    "observedEventDetails"
                    if observation.facts
                    else "eventDetailsRemainUnknown"
                ),
                object=[fact.code for fact in observation.facts],
                stance="believed" if observation.facts else "suspected",
                confidence=1.0 if observation.facts else 0.1,
                source_observation_ids=[observation.observation_id],
            )
            run.emit(
                "belief.updated",
                visibility,
                {"belief": belief.model_dump(by_alias=True)},
                causation_id=observation.observation_id,
            )
            belief_ids[actor_id].append(belief.belief_id)
            inference = ActorMemory(
                memory_id=f"inference:{belief.belief_id}",
                actor_id=actor_id,
                source_round=round_index,
                kind="inference",
                statement=belief.predicate,
                source_observation_ids=[observation.observation_id],
            )
            memories[actor_id].append(inference)
            round_inferences[actor_id].append(inference)
            if observation.completeness == "partial":
                round_unknowns[actor_id].append(
                    UnknownArea(
                        label="some event details were not observable",
                        source_event_id=event.canonical_event_id,
                    )
                )

    @staticmethod
    def _semantic_trace(
        rounds: list[LivingWorldRound],
    ) -> list[dict[str, Any]]:
        return [
            {
                "round": round_result.round_index,
                "turns": [
                    {
                        "actor": turn.actor_id,
                        "kind": turn.intent.kind,
                        "outcome": turn.resolution_receipt.outcome,
                        "reasons": turn.resolution_receipt.reason_codes,
                    }
                    for turn in round_result.turns
                ],
                "locations": round_result.location_snapshot,
                "relationships": {
                    actor_id: {
                        target_id: relationship.model_dump(
                            mode="json",
                            by_alias=True,
                        )
                        for target_id, relationship in targets.items()
                    }
                    for actor_id, targets in (
                        round_result.relationship_snapshot.items()
                    )
                },
                "outputs": [
                    {
                        "actor": output.actor_id,
                        "public": output.public_expression.text,
                        "private": output.private_inner_os.text,
                    }
                    for output in round_result.outputs
                ],
            }
            for round_result in rounds
        ]


class TransactionalLivingWorldRuntime:
    """Persists v0.2 atomic batch facts and returns a presentation proof."""

    def __init__(
        self,
        storage: SQLiteStorage,
        bundle: RuntimeBundle,
        *,
        actor_provider: ActorPolicyProvider | None = None,
        director: DeterministicSceneDirector | None = None,
        initial_memories: dict[OcId, list[ActorMemory]] | None = None,
    ) -> None:
        self.storage = storage
        self.bundle = bundle
        self.actor_provider = actor_provider
        self.director = director
        self.initial_memories = initial_memories

    def create_and_run(
        self,
        *,
        session_id: str,
        seed: str | None = None,
    ) -> LivingWorldProofDTO:
        selected_seed = seed or self.bundle.default_seed
        initial_state = self.bundle.world.initial_state.model_copy(deep=True)
        initial_state.status = "running"
        self.storage.create_session(
            session_id=session_id,
            world_id=self.bundle.world.world_id,
            seed=selected_seed,
            consent_required=True,
            state=initial_state.model_dump(by_alias=True),
        )
        core_run = TransactionalLivingWorldCore(
            self.bundle,
            actor_provider=self.actor_provider,
            director=self.director,
            include_private_os=True,
            initial_memories=self.initial_memories,
        ).run(
            run_id=session_id,
            seed=selected_seed,
        )
        latest_perspective_by_actor = {
            perspective.actor_id: perspective
            for perspective in core_run.rounds[-1].perspectives
        }
        private_os_views: dict[str, OwnerPrivateOsDTO] = {}
        for actor in core_run.actors:
            perspective = latest_perspective_by_actor[actor.actor_id]
            if (
                perspective.private_os_ref is None
                or perspective.private_inner_os is None
            ):
                continue
            private_os_views[actor.resident_id] = OwnerPrivateOsDTO(
                run_id=session_id,
                world_version=core_run.final_state.world_version,
                resident_id=actor.resident_id,
                actor_id=actor.actor_id,
                private_os_ref=perspective.private_os_ref,
                text=perspective.private_inner_os,
                memory_refs_used=[
                    memory.memory_id
                    for memory in core_run.memories[actor.actor_id][-3:]
                ],
            )
        for round_execution in core_run.rounds:
            for perspective in round_execution.perspectives:
                perspective.private_inner_os = None
        for cursor, round_execution in enumerate(core_run.rounds, start=1):
            event = round_execution.adjudication.canonical_event
            envelope = {
                "schemaVersion": 1,
                "eventId": f"{session_id}-batch-stream-{cursor:03d}",
                "cursor": cursor,
                "sessionId": session_id,
                "tickIndex": round_execution.round_index,
                "emittedAt": (
                    datetime(2026, 7, 24, tzinfo=UTC)
                    + timedelta(seconds=cursor)
                ).isoformat().replace("+00:00", "Z"),
                "type": "canonical.event.committed",
                "visibility": {"scope": "public"},
                "causationId": event.decision_id,
                "payload": {
                    "event": event.model_dump(
                        mode="json",
                        by_alias=True,
                        exclude_none=True,
                    ),
                    "worldVersion": (
                        round_execution.state_after.world_version
                    ),
                },
            }
            self.storage.append_event_and_update_state(
                session_id,
                envelope,
                state=round_execution.state_after.model_dump(by_alias=True),
                checksum=canonical_state_checksum(
                    round_execution.state_after
                ),
            )

        completed_state = core_run.final_state.model_copy(deep=True)
        completed_state.status = "completed"
        completion_cursor = len(core_run.rounds) + 1
        final_hash = canonical_state_checksum(core_run.final_state)
        completion = {
            "schemaVersion": 1,
            "eventId": (
                f"{session_id}-batch-stream-{completion_cursor:03d}"
            ),
            "cursor": completion_cursor,
            "sessionId": session_id,
            "tickIndex": core_run.rounds[-1].round_index,
            "emittedAt": (
                datetime(2026, 7, 24, tzinfo=UTC)
                + timedelta(seconds=completion_cursor)
            ).isoformat().replace("+00:00", "Z"),
            "type": "session.completed",
            "visibility": {"scope": "public"},
            "payload": {
                "worldVersion": completed_state.world_version,
                "lastCanonicalSequence": (
                    core_run.rounds[-1]
                    .adjudication
                    .canonical_event
                    .sequence
                ),
                "checksum": final_hash,
            },
        }
        self.storage.append_event_and_finish_session(
            session_id,
            completion,
            state=completed_state.model_dump(by_alias=True),
            checksum=final_hash,
        )
        replay = ReplayAuditor().audit(
            world=self.bundle.world,
            seed=selected_seed,
            run_id=session_id,
            rounds=core_run.rounds,
            expected_final_hash=final_hash,
        )
        proof = core_run.to_proof(replay)
        product_views = ProductProjectionBuilder(
            self.bundle.world,
            self.bundle,
        ).build(core_run, proof)
        views = {
            "world": product_views.world.model_dump(
                mode="json",
                by_alias=True,
            ),
            "proof": proof.model_dump(
                mode="json",
                by_alias=True,
            ),
            "memory": LivingMemoryStoreDTO(
                run_id=session_id,
                day_index=(
                    core_run.rounds[-1].round_index // 2 + 1
                ),
                memories=core_run.memories,
            ).model_dump(
                mode="json",
                by_alias=True,
            ),
            **{
                f"room:{resident_id}": room.model_dump(
                    mode="json",
                    by_alias=True,
                )
                for resident_id, room in (
                    product_views.rooms_by_resident_id.items()
                )
            },
            **{
                f"private-os:{resident_id}": private_os.model_dump(
                    mode="json",
                    by_alias=True,
                )
                for resident_id, private_os in private_os_views.items()
            },
        }
        self.storage.save_living_world_views(session_id, views)
        return proof


class _RunContext:
    def __init__(
        self,
        storage: SQLiteStorage,
        world: WorldDefinition,
        state: WorldState,
        session_id: str,
    ) -> None:
        self.storage = storage
        self.world = world
        self.state = state
        self.session_id = session_id
        self.cursor = 0
        self.tick_index = 0
        self.last_canonical_sequence = 0
        self._registered_proposals: dict[str, str] = {}
        self._resolution_authority = ResolutionAuthority()

    @property
    def next_canonical_sequence(self) -> int:
        return self.last_canonical_sequence + 1

    def start_tick(self, tick_index: int, actor_id: OcId) -> None:
        self.tick_index = tick_index
        self.state.tick_index = tick_index
        self.emit(
            "tick.started",
            {"scope": "public"},
            {
                "actorId": actor_id,
                "worldVersion": self.state.world_version,
            },
        )

    def complete_tick(self) -> None:
        self.emit(
            "tick.completed",
            {"scope": "public"},
            {
                "worldVersion": self.state.world_version,
                "lastCanonicalSequence": self.last_canonical_sequence,
                "checksum": canonical_state_checksum(self.state),
            },
        )

    def emit_decision(self, decision: RuleDecision) -> None:
        self.emit(
            "rule.decision.created",
            {"scope": "tech"},
            {"decision": decision.model_dump(by_alias=True, exclude_none=True)},
            causation_id=decision.proposal_id,
        )

    def register_proposal(self, proposal: BaseModel) -> None:
        proposal_id = getattr(proposal, "proposal_id", None)
        if not isinstance(proposal_id, str):
            raise DomainInvariantError("registered proposal requires a proposal_id")
        self._registered_proposals[proposal_id] = _fingerprint(proposal)

    def rule_kernel(self) -> RuleKernel:
        return RuleKernel(
            self.world,
            authority=self._resolution_authority,
        )

    def commit_resolution(
        self,
        resolution: Resolution,
        *,
        visibility: dict[str, str],
    ) -> ResolutionReceipt:
        event = resolution.event
        if event is None:
            raise DomainInvariantError(
                "a rejected resolution cannot commit a canonical event"
            )
        self._validate_resolution_receipt(resolution)
        self.state = reduce_canonical_events(self.state, [event])
        self.last_canonical_sequence = event.sequence
        event_payload = event.model_dump(by_alias=True, exclude_none=True)
        for dumped_effect, effect in zip(
            event_payload["effects"],
            event.effects,
            strict=True,
        ):
            dumped_effect["before"] = effect.before
            dumped_effect["after"] = effect.after
        self.emit(
            "canonical.event.committed",
            visibility,
            {
                "event": event_payload,
                "worldVersion": self.state.world_version,
            },
            causation_id=event.decision_id,
            objective_state=self.state,
        )
        return resolution.receipt

    def _validate_resolution_receipt(self, resolution: Resolution) -> None:
        decision = resolution.decision
        event = resolution.event
        receipt = resolution.receipt
        signature_payload = {
            "receiptId": receipt.receipt_id,
            "proposalId": receipt.proposal_id,
            "proposalFingerprint": receipt.proposal_fingerprint,
            "decisionId": receipt.decision_id,
            "verdict": receipt.verdict,
            "outcome": receipt.outcome,
            "matchedRuleIds": receipt.matched_rule_ids,
            "reasonCodes": receipt.reason_codes,
            "inputWorldVersion": receipt.input_world_version,
            "ruleFingerprint": receipt.rule_fingerprint,
            "effectsFingerprint": receipt.effects_fingerprint,
            "canonicalEventId": receipt.canonical_event_id,
            "canonicalEventFingerprint": receipt.canonical_event_fingerprint,
            "receiptFingerprint": receipt.receipt_fingerprint,
        }
        if not self._resolution_authority.verifies(
            signature_payload,
            receipt.issuer_signature,
        ):
            raise DomainInvariantError("resolution receipt issuer mismatch")
        registered_fingerprint = self._registered_proposals.get(
            decision.proposal_id
        )
        if registered_fingerprint is None:
            raise DomainInvariantError(
                "resolution requires a registered proposal"
            )
        if registered_fingerprint != receipt.proposal_fingerprint:
            raise DomainInvariantError("resolution receipt proposal mismatch")
        if receipt.input_world_version != self.state.world_version:
            raise DomainInvariantError("resolution receipt input version mismatch")
        if (
            receipt.proposal_id != decision.proposal_id
            or receipt.decision_id != decision.decision_id
            or receipt.verdict != decision.verdict
            or receipt.outcome != decision.outcome
            or receipt.matched_rule_ids != decision.matched_rule_ids
            or receipt.reason_codes != decision.reason_codes
        ):
            raise DomainInvariantError("resolution receipt decision mismatch")
        if event is None:
            raise DomainInvariantError("resolution receipt has no canonical event")
        if event.sequence != self.next_canonical_sequence:
            raise DomainInvariantError("resolution receipt sequence mismatch")
        if (
            event.decision_id != decision.decision_id
            or receipt.canonical_event_id != event.canonical_event_id
            or receipt.effects_fingerprint != _fingerprint(event.effects)
            or receipt.canonical_event_fingerprint != _fingerprint(event)
        ):
            raise DomainInvariantError("resolution receipt event mismatch")
        matched_rules = [
            rule
            for rule_id in decision.matched_rule_ids
            for rule in self.world.rules
            if rule.rule_id == rule_id
        ]
        if len(matched_rules) != len(decision.matched_rule_ids):
            raise DomainInvariantError("resolution receipt references unknown rule")
        if receipt.rule_fingerprint != _fingerprint(matched_rules):
            raise DomainInvariantError("resolution receipt rule mismatch")
        receipt_payload = {
            "proposalId": receipt.proposal_id,
            "proposalFingerprint": receipt.proposal_fingerprint,
            "decisionId": receipt.decision_id,
            "verdict": receipt.verdict,
            "outcome": receipt.outcome,
            "matchedRuleIds": receipt.matched_rule_ids,
            "reasonCodes": receipt.reason_codes,
            "inputWorldVersion": receipt.input_world_version,
            "ruleFingerprint": receipt.rule_fingerprint,
            "effectsFingerprint": receipt.effects_fingerprint,
            "canonicalEventId": receipt.canonical_event_id,
            "canonicalEventFingerprint": receipt.canonical_event_fingerprint,
        }
        if receipt.receipt_fingerprint != _fingerprint(receipt_payload):
            raise DomainInvariantError("resolution receipt fingerprint mismatch")

    def emit(
        self,
        event_type: str,
        visibility: dict[str, str],
        payload: dict[str, Any],
        *,
        causation_id: str | None = None,
        objective_state: WorldState | None = None,
    ) -> dict[str, Any]:
        envelope = self._make_envelope(
            event_type,
            visibility,
            payload,
            causation_id=causation_id,
        )
        if objective_state is None:
            self.storage.append_event(self.session_id, envelope)
        else:
            self.storage.append_event_and_update_state(
                self.session_id,
                envelope,
                state=objective_state.model_dump(by_alias=True),
                checksum=canonical_state_checksum(objective_state),
            )
        return envelope

    def finish_session(self) -> None:
        self.state.status = "completed"
        checksum = canonical_state_checksum(self.state)
        envelope = self._make_envelope(
            "session.completed",
            {"scope": "public"},
            {
                "worldVersion": self.state.world_version,
                "lastCanonicalSequence": self.last_canonical_sequence,
                "checksum": checksum,
            },
        )
        self.storage.append_event_and_finish_session(
            self.session_id,
            envelope,
            state=self.state.model_dump(by_alias=True),
            checksum=checksum,
        )

    def _make_envelope(
        self,
        event_type: str,
        visibility: dict[str, str],
        payload: dict[str, Any],
        *,
        causation_id: str | None = None,
    ) -> dict[str, Any]:
        self.cursor += 1
        emitted_at = datetime(2026, 7, 24, tzinfo=UTC) + timedelta(
            seconds=self.cursor
        )
        envelope: dict[str, Any] = {
            "schemaVersion": 1,
            "eventId": f"{self.session_id}-stream-{self.cursor:03d}",
            "cursor": self.cursor,
            "sessionId": self.session_id,
            "tickIndex": self.tick_index,
            "emittedAt": emitted_at.isoformat().replace("+00:00", "Z"),
            "type": event_type,
            "visibility": visibility,
            "payload": payload,
        }
        if causation_id:
            envelope["causationId"] = causation_id
        return envelope

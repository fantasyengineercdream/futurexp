from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.domain.encounters import Affordance, EncounterEngine
from app.domain.living_world import (
    ActorMemory,
    ActorPolicyContext,
    ActorPolicyProvider,
    DeterministicActorPolicyProvider,
    DeterministicSceneDirector,
    ResilientActorPolicyProvider,
    RuntimeBundle,
    StructuredActorTurn,
    StructuredIntent,
    intent_to_character_action,
)
from app.domain.models import (
    CanonicalEvent,
    CharacterProposal,
    ContractModel,
    OcId,
    Resolution,
    ResolutionReceipt,
    StateEffect,
    UtteranceProposal,
    WorldDefinition,
    WorldState,
)
from app.domain.perspective import PerspectiveProjector
from app.domain.reducer import canonical_state_checksum, reduce_canonical_events
from app.domain.rules import ResolutionAuthority, RuleKernel
from app.domain.scheduler import ScheduledStep
from app.errors import DomainInvariantError


class SnapshotProof(ContractModel):
    world_version: int = Field(ge=0)
    world_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    tick_index: int = Field(ge=0)


class ActorRegistryProof(ContractModel):
    actor_id: str
    resident_id: str
    display_name: str
    screen_id: str


class ResidentPresenceProof(ContractModel):
    actor_id: str
    resident_id: str
    display_name: str
    floor_id: str
    room_id: str
    location_id: str
    presence: Literal["home", "away", "adventure", "offline"]
    activity_label: str


class ProposalProof(ContractModel):
    proposal_id: str
    actor_id: str
    intent_label: str
    intent_kind: Literal["TAKE", "GIVE", "MOVE", "UTTERANCE", "WAIT"]
    based_on_world_version: int = Field(ge=0)
    target_label: str | None = None
    target_id: str | None = None
    resource_id: str | None = None
    precondition_labels: list[str]
    influenced_by_memory_ids: list[str] = Field(default_factory=list)
    influenced_by_relationship_ids: list[str] = Field(default_factory=list)


class ConflictSetProof(ContractModel):
    conflict_set_id: str
    kind: str
    proposal_ids: list[str] = Field(min_length=2)
    resource_id: str | None = None
    reason_label: str


class RuleReceiptProof(ContractModel):
    proposal_id: str
    status: Literal["applied", "rejected"]
    outcome: Literal["success", "blocked", "with_cost", "rejected"]
    rule_id: str
    rule_label: str
    reason_codes: list[str]
    deterministic_evidence: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_label: str
    effects: list[StateEffect]


class ResolutionBatchProof(ContractModel):
    batch_id: str
    conflict_set_ids: list[str]
    atomic: Literal[True] = True
    seed: str
    receipts: list[RuleReceiptProof]


class CommitProof(ContractModel):
    commit_id: str
    canonical_event_id: str | None = None
    from_version: int = Field(ge=0)
    to_version: int = Field(ge=0)
    before_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    after_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    committed_at: AwareDatetime
    tick_index: int = Field(ge=0)
    atomic: Literal[True] = True
    rolled_back: bool
    failure_reason: str | None = None


class PerspectiveProof(ContractModel):
    actor_id: str
    canonical_event_id: str
    knowledge_state: Literal["observed", "misunderstood", "unknown"]
    observed_fact_ids: list[str]
    unknown_fact_ids: list[str]
    perspective_label: str
    belief_summary: str
    memory_summary: str
    public_expression: str
    private_os_available: bool
    private_os_ref: str | None = None
    private_inner_os: str | None = None


class MemoryDeltaProof(ContractModel):
    actor_id: str
    memory_id: str
    summary: str
    source_observation_ids: list[str]


class RelationshipDeltaProof(ContractModel):
    delta_id: str
    from_actor_id: str
    to_actor_id: str
    dimension: str
    before: int
    after: int
    cause_canonical_event_id: str


class NextRoundEvidenceProof(ContractModel):
    actor_id: str
    previous_proposal_id: str | None = None
    next_proposal_id: str
    changed_because_memory_ids: list[str]
    changed_because_relationship_ids: list[str]
    summary: str


class PersistenceProof(ContractModel):
    memory_deltas: list[MemoryDeltaProof]
    relationship_deltas: list[RelationshipDeltaProof]
    next_round_evidence: NextRoundEvidenceProof


class ReplayProof(ContractModel):
    verified: bool
    status: Literal["verified", "mismatch"]
    seed: str
    expected_final_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_final_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_canonical_sequence: int = Field(ge=0)


class LivingWorldProofDTO(ContractModel):
    schema_version: Literal["0.2"] = "0.2"
    run_id: str
    session_id: str
    seed: str
    snapshot: SnapshotProof
    actors: list[ActorRegistryProof] = Field(min_length=1, max_length=3)
    resident_presence: list[ResidentPresenceProof] = Field(
        min_length=1,
        max_length=3,
    )
    proposals: list[ProposalProof] = Field(min_length=1, max_length=3)
    conflict_sets: list[ConflictSetProof]
    resolution_batch: ResolutionBatchProof
    commit: CommitProof
    perspectives: list[PerspectiveProof] = Field(min_length=1, max_length=3)
    persistence: PersistenceProof
    replay: ReplayProof
    provider_fallback_count: int = Field(ge=0)


class ConcurrentProposal(ContractModel):
    proposal_id: str
    actor_id: OcId
    based_on_world_version: int = Field(ge=0)
    intent: StructuredIntent
    public_text: str
    private_inner_os_text: str
    truth_posture: Literal[
        "candid",
        "uncertain",
        "withholding",
        "misrepresenting",
    ]
    target_label: str | None = None
    target_id: str | None = None
    resource_id: str | None = None
    precondition_labels: list[str]
    influenced_by_memory_ids: list[str] = Field(default_factory=list)
    influenced_by_relationship_ids: list[str] = Field(default_factory=list)

    def to_proof(self) -> ProposalProof:
        return ProposalProof(
            proposal_id=self.proposal_id,
            actor_id=self.actor_id,
            intent_label=_intent_label(self.intent, self.target_label),
            intent_kind=self.intent.kind,
            based_on_world_version=self.based_on_world_version,
            target_label=self.target_label,
            target_id=self.target_id,
            resource_id=self.resource_id,
            precondition_labels=self.precondition_labels,
            influenced_by_memory_ids=self.influenced_by_memory_ids,
            influenced_by_relationship_ids=(
                self.influenced_by_relationship_ids
            ),
        )


class BatchAdjudication(ContractModel):
    proof: ResolutionBatchProof
    canonical_event: CanonicalEvent
    source_event_by_proposal: dict[str, CanonicalEvent]


class AtomicCommitAttempt(ContractModel):
    state: WorldState
    commit: CommitProof


class RoundExecution(ContractModel):
    round_index: int = Field(ge=0)
    snapshot: SnapshotProof
    proposals: list[ConcurrentProposal]
    conflict_sets: list[ConflictSetProof]
    adjudication: BatchAdjudication
    commit: CommitProof
    state_before: WorldState
    state_after: WorldState
    perspectives: list[PerspectiveProof]
    memory_deltas: list[MemoryDeltaProof]


class CoreRun(ContractModel):
    run_id: str
    seed: str
    actors: list[ActorRegistryProof]
    resident_presence: list[ResidentPresenceProof]
    rounds: list[RoundExecution] = Field(min_length=2)
    final_state: WorldState
    provider_fallback_count: int = Field(ge=0)
    memories: dict[str, list[ActorMemory]]

    def to_proof(self, replay: ReplayProof) -> LivingWorldProofDTO:
        focus = self.rounds[0]
        persistence = _build_persistence(self.rounds)
        return LivingWorldProofDTO(
            run_id=self.run_id,
            session_id=self.run_id,
            seed=self.seed,
            snapshot=focus.snapshot,
            actors=self.actors,
            resident_presence=self.resident_presence,
            proposals=[proposal.to_proof() for proposal in focus.proposals],
            conflict_sets=focus.conflict_sets,
            resolution_batch=focus.adjudication.proof,
            commit=focus.commit,
            perspectives=focus.perspectives,
            persistence=persistence,
            replay=replay,
            provider_fallback_count=self.provider_fallback_count,
        )


class ConflictDetector:
    def detect(
        self,
        proposals: list[ConcurrentProposal],
        world: WorldDefinition,
    ) -> list[ConflictSetProof]:
        ordered = sorted(proposals, key=lambda proposal: proposal.proposal_id)
        conflicts: list[ConflictSetProof] = []
        by_resource: dict[str, list[ConcurrentProposal]] = {}
        for proposal in ordered:
            if proposal.resource_id and proposal.intent.kind in {
                "TAKE",
                "GIVE",
            }:
                by_resource.setdefault(proposal.resource_id, []).append(proposal)
        for resource_id, contenders in sorted(by_resource.items()):
            if len(contenders) < 2:
                continue
            proposal_ids = sorted(item.proposal_id for item in contenders)
            conflicts.append(
                ConflictSetProof(
                    conflict_set_id=_stable_id(
                        "conflict-exclusive-resource",
                        resource_id,
                        *proposal_ids,
                    ),
                    kind="exclusive-resource",
                    proposal_ids=proposal_ids,
                    resource_id=resource_id,
                    reason_label=(
                        "Multiple independent intents target one exclusive "
                        "resource in the same snapshot."
                    ),
                )
            )

        social_rule = world.rule("SOCIAL_CONSEQUENCE")
        if social_rule and social_rule.enabled:
            target_by_actor = social_rule.params.get("targetByActor", {})
            by_actor = {proposal.actor_id: proposal for proposal in ordered}
            for proposal in ordered:
                if proposal.intent.kind != "UTTERANCE":
                    continue
                target_id = target_by_actor.get(proposal.actor_id)
                target = by_actor.get(target_id)
                if target is None:
                    continue
                proposal_ids = sorted(
                    [proposal.proposal_id, target.proposal_id]
                )
                conflicts.append(
                    ConflictSetProof(
                        conflict_set_id=_stable_id(
                            "conflict-social-pressure",
                            *proposal_ids,
                        ),
                        kind="social-pressure",
                        proposal_ids=proposal_ids,
                        resource_id=target.resource_id,
                        reason_label=(
                            "A rule-backed social pressure directly opposes "
                            "another actor's simultaneous intent."
                        ),
                    )
                )
        return sorted(conflicts, key=lambda conflict: conflict.conflict_set_id)


class BatchRuleAdjudicator:
    """Resolves a proposal set against one immutable snapshot."""

    def __init__(self, world: WorldDefinition) -> None:
        self.world = world

    def adjudicate(
        self,
        *,
        run_id: str,
        round_index: int,
        seed: str,
        snapshot: WorldState,
        proposals: list[ConcurrentProposal],
        conflict_sets: list[ConflictSetProof],
    ) -> BatchAdjudication:
        versions = {
            proposal.based_on_world_version for proposal in proposals
        }
        if versions != {snapshot.world_version}:
            raise DomainInvariantError(
                "all batch proposals must reference one snapshot version"
            )
        authority = ResolutionAuthority()
        kernel = RuleKernel(self.world, authority=authority)
        rejected_by_conflict = self._exclusive_resource_losers(
            seed,
            proposals,
            conflict_sets,
        )
        source_events: dict[str, CanonicalEvent] = {}
        receipts: list[RuleReceiptProof] = []
        for proposal in sorted(proposals, key=lambda item: item.proposal_id):
            if proposal.proposal_id in rejected_by_conflict:
                evidence = _hash_payload(
                    {
                        "seed": seed,
                        "proposalId": proposal.proposal_id,
                        "ruleId": "batch-exclusive-resource",
                        "status": "rejected",
                    }
                )
                receipts.append(
                    RuleReceiptProof(
                        proposal_id=proposal.proposal_id,
                        status="rejected",
                        outcome="rejected",
                        rule_id="batch-exclusive-resource",
                        rule_label="Exclusive resource conflict",
                        reason_codes=["EXCLUSIVE_RESOURCE_CONFLICT_LOST"],
                        deterministic_evidence=evidence,
                        evidence_label=(
                            "Stable seed tie-break rejected this contender "
                            "before canonical effects were assembled."
                        ),
                        effects=[],
                    )
                )
                continue
            resolution = self._resolve(
                kernel,
                proposal,
                snapshot,
                round_index,
            )
            self._verify_kernel_receipt(
                authority,
                resolution.receipt,
            )
            event = resolution.event
            if event is not None:
                source_events[proposal.proposal_id] = event
            matched_rule = next(
                (
                    rule
                    for rule in self.world.rules
                    if resolution.decision.matched_rule_ids
                    and rule.rule_id
                    == resolution.decision.matched_rule_ids[0]
                ),
                None,
            )
            receipts.append(
                RuleReceiptProof(
                    proposal_id=proposal.proposal_id,
                    status=(
                        "applied"
                        if event is not None
                        else "rejected"
                    ),
                    outcome=(
                        resolution.decision.outcome
                        if resolution.decision.outcome is not None
                        else "rejected"
                    ),
                    rule_id=(
                        matched_rule.rule_id
                        if matched_rule is not None
                        else "rule-kernel-default"
                    ),
                    rule_label=(
                        matched_rule.label
                        if matched_rule is not None
                        else "Rule Kernel default adjudication"
                    ),
                    reason_codes=resolution.decision.reason_codes,
                    deterministic_evidence=(
                        resolution.receipt.receipt_fingerprint
                    ),
                    evidence_label=(
                        "Rule Kernel receipt binds proposal, snapshot, "
                        "matched rules, verdict and effects."
                    ),
                    effects=list(event.effects) if event else [],
                )
            )

        event = self._aggregate_event(
            run_id,
            round_index,
            source_events,
        )
        batch_id = f"{run_id}:round-{round_index}:resolution-batch"
        return BatchAdjudication(
            proof=ResolutionBatchProof(
                batch_id=batch_id,
                conflict_set_ids=[
                    conflict.conflict_set_id for conflict in conflict_sets
                ],
                seed=seed,
                receipts=receipts,
            ),
            canonical_event=event,
            source_event_by_proposal=source_events,
        )

    def _resolve(
        self,
        kernel: RuleKernel,
        proposal: ConcurrentProposal,
        snapshot: WorldState,
        round_index: int,
    ) -> Resolution:
        decision_id = f"{proposal.proposal_id}:decision"
        event_id = f"{proposal.proposal_id}:provisional"
        sequence = round_index + 1
        if proposal.intent.kind == "UTTERANCE":
            return kernel.resolve_utterance(
                UtteranceProposal(
                    proposal_id=proposal.proposal_id,
                    actor_id=proposal.actor_id,
                    text=proposal.public_text,
                    audience="publicUi",
                    based_on_belief_ids=[],
                ),
                snapshot,
                sequence=sequence,
                decision_id=decision_id,
                canonical_event_id=event_id,
            )
        return kernel.resolve_character(
            CharacterProposal(
                proposal_id=proposal.proposal_id,
                actor_id=proposal.actor_id,
                action=intent_to_character_action(proposal.intent),
                motivation_refs=proposal.intent.motivation_refs,
            ),
            snapshot,
            sequence=sequence,
            decision_id=decision_id,
            canonical_event_id=event_id,
        )

    @staticmethod
    def _verify_kernel_receipt(
        authority: ResolutionAuthority,
        receipt: ResolutionReceipt,
    ) -> None:
        payload = {
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
            "canonicalEventFingerprint": (
                receipt.canonical_event_fingerprint
            ),
            "receiptFingerprint": receipt.receipt_fingerprint,
        }
        if not authority.verifies(payload, receipt.issuer_signature):
            raise DomainInvariantError(
                "batch received a receipt outside its bound Rule Kernel"
            )

    @staticmethod
    def _exclusive_resource_losers(
        seed: str,
        proposals: list[ConcurrentProposal],
        conflicts: list[ConflictSetProof],
    ) -> set[str]:
        by_id = {proposal.proposal_id: proposal for proposal in proposals}
        losers: set[str] = set()
        for conflict in conflicts:
            if conflict.kind != "exclusive-resource":
                continue
            ranked = sorted(
                conflict.proposal_ids,
                key=lambda proposal_id: (
                    _hash_payload(
                        {
                            "seed": seed,
                            "conflictSetId": conflict.conflict_set_id,
                            "proposalId": proposal_id,
                        }
                    ),
                    proposal_id,
                ),
            )
            if any(proposal_id not in by_id for proposal_id in ranked):
                raise DomainInvariantError(
                    "conflict set references an unknown proposal"
                )
            losers.update(ranked[1:])
        return losers

    @staticmethod
    def _aggregate_event(
        run_id: str,
        round_index: int,
        source_events: dict[str, CanonicalEvent],
    ) -> CanonicalEvent:
        ordered = [
            source_events[proposal_id]
            for proposal_id in sorted(source_events)
        ]
        event_id = f"{run_id}:round-{round_index}:canonical-batch"
        return CanonicalEvent(
            canonical_event_id=event_id,
            sequence=round_index + 1,
            kind=(
                "utterance.spoken"
                if ordered
                and all(event.kind == "utterance.spoken" for event in ordered)
                else "action.resolved"
            ),
            decision_id=f"{run_id}:round-{round_index}:batch-decision",
            fact_codes=list(
                dict.fromkeys(
                    code for event in ordered for code in event.fact_codes
                )
            ),
            effects=[
                effect for event in ordered for effect in event.effects
            ],
            perceptual_atoms=[
                atom for event in ordered for atom in event.perceptual_atoms
            ],
        )


class TransitionInvariantValidator:
    def __init__(self, world: WorldDefinition) -> None:
        self.world = world

    def validate(
        self,
        state: WorldState,
        event: CanonicalEvent,
    ) -> WorldState:
        paths = [effect.path for effect in event.effects]
        if len(paths) != len(set(paths)):
            raise DomainInvariantError(
                "one atomic batch cannot write the same state path twice"
            )
        next_state = reduce_canonical_events(state, [event])
        location_ids = {
            location.location_id for location in self.world.locations
        }
        if any(
            location_id not in location_ids
            for location_id in next_state.actor_locations.values()
        ):
            raise DomainInvariantError(
                "batch transition produced an unknown actor location"
            )
        actor_ids = {
            character.oc_id for character in self.world.characters
        }
        if any(
            world_object.holder_id is not None
            and world_object.holder_id not in actor_ids
            for world_object in next_state.objects.values()
        ):
            raise DomainInvariantError(
                "batch transition produced an unknown object holder"
            )
        return next_state


class AtomicBatchCommitter:
    def __init__(self, world: WorldDefinition) -> None:
        self.validator = TransitionInvariantValidator(world)

    def commit(
        self,
        state: WorldState,
        adjudication: BatchAdjudication,
    ) -> WorldState:
        event = self._validated_event(adjudication)
        snapshot = state.model_copy(deep=True)
        return self.validator.validate(snapshot, event)

    @staticmethod
    def _validated_event(
        adjudication: BatchAdjudication,
    ) -> CanonicalEvent:
        if not isinstance(adjudication, BatchAdjudication):
            raise TypeError(
                "AtomicBatchCommitter requires a BatchAdjudication; "
                "a naked CanonicalEvent cannot be committed"
            )
        receipts_by_id = {
            receipt.proposal_id: receipt
            for receipt in adjudication.proof.receipts
        }
        applied_ids = {
            proposal_id
            for proposal_id, receipt in receipts_by_id.items()
            if receipt.status == "applied"
        }
        source_ids = set(adjudication.source_event_by_proposal)
        if applied_ids != source_ids:
            raise DomainInvariantError(
                "canonical batch sources do not match applied rule receipts"
            )
        ordered_source_events = [
            adjudication.source_event_by_proposal[proposal_id]
            for proposal_id in sorted(source_ids)
        ]
        for proposal_id, source_event in (
            adjudication.source_event_by_proposal.items()
        ):
            if (
                receipts_by_id[proposal_id].effects
                != source_event.effects
            ):
                raise DomainInvariantError(
                    "canonical source effects do not match rule receipt"
                )
        event = adjudication.canonical_event
        expected_effects = [
            effect
            for source_event in ordered_source_events
            for effect in source_event.effects
        ]
        expected_fact_codes = list(
            dict.fromkeys(
                code
                for source_event in ordered_source_events
                for code in source_event.fact_codes
            )
        )
        expected_atoms = [
            atom
            for source_event in ordered_source_events
            for atom in source_event.perceptual_atoms
        ]
        if (
            event.effects != expected_effects
            or event.fact_codes != expected_fact_codes
            or event.perceptual_atoms != expected_atoms
        ):
            raise DomainInvariantError(
                "canonical batch does not match its rule-adjudicated sources"
            )
        return event

    def try_commit(
        self,
        *,
        run_id: str,
        round_index: int,
        state: WorldState,
        adjudication: BatchAdjudication,
    ) -> AtomicCommitAttempt:
        try:
            next_state = self.commit(state, adjudication)
        except (DomainInvariantError, TypeError, ValueError) as error:
            state_hash = canonical_state_checksum(state)
            return AtomicCommitAttempt(
                state=state.model_copy(deep=True),
                commit=CommitProof(
                    commit_id=f"{run_id}:round-{round_index}:commit",
                    canonical_event_id=None,
                    from_version=state.world_version,
                    to_version=state.world_version,
                    before_hash=state_hash,
                    after_hash=state_hash,
                    committed_at=(
                        datetime(2026, 7, 24, tzinfo=UTC)
                        + timedelta(seconds=round_index + 1)
                    ),
                    tick_index=round_index,
                    rolled_back=True,
                    failure_reason=str(error),
                ),
            )
        return AtomicCommitAttempt(
            state=next_state,
            commit=_build_commit(
                run_id,
                round_index,
                state,
                next_state,
                adjudication.canonical_event,
            ),
        )


class ReplayAuditor:
    def audit(
        self,
        *,
        world: WorldDefinition,
        seed: str,
        run_id: str,
        rounds: list[RoundExecution],
        expected_final_hash: str,
    ) -> ReplayProof:
        state = world.initial_state.model_copy(deep=True)
        adjudicator = BatchRuleAdjudicator(world)
        committer = AtomicBatchCommitter(world)
        for round_execution in rounds:
            state.tick_index = round_execution.round_index
            conflicts = ConflictDetector().detect(
                round_execution.proposals,
                world,
            )
            adjudication = adjudicator.adjudicate(
                run_id=run_id,
                round_index=round_execution.round_index,
                seed=seed,
                snapshot=state,
                proposals=round_execution.proposals,
                conflict_sets=conflicts,
            )
            state = committer.commit(state, adjudication)
        return self.compare_hashes(
            seed=seed,
            expected_final_hash=expected_final_hash,
            actual_final_hash=canonical_state_checksum(state),
            last_canonical_sequence=(
                rounds[-1].adjudication.canonical_event.sequence
            ),
        )

    def compare_hashes(
        self,
        *,
        seed: str,
        expected_final_hash: str,
        actual_final_hash: str,
        last_canonical_sequence: int,
    ) -> ReplayProof:
        verified = expected_final_hash == actual_final_hash
        return ReplayProof(
            verified=verified,
            status="verified" if verified else "mismatch",
            seed=seed,
            expected_final_hash=expected_final_hash,
            actual_final_hash=actual_final_hash,
            last_canonical_sequence=last_canonical_sequence,
        )


class TransactionalLivingWorldCore:
    """Finite two-round core with a same-snapshot proposal barrier."""

    def __init__(
        self,
        bundle: RuntimeBundle,
        *,
        actor_provider: ActorPolicyProvider | None = None,
        director: DeterministicSceneDirector | None = None,
        include_private_os: bool = False,
        initial_memories: dict[OcId, list[ActorMemory]] | None = None,
    ) -> None:
        if not 1 <= len(bundle.actor_profiles) <= 3:
            raise DomainInvariantError(
                "transactional proof supports one to three actors"
            )
        self.bundle = bundle
        self.primary_provider = (
            actor_provider or DeterministicActorPolicyProvider()
        )
        self.provider = ResilientActorPolicyProvider(self.primary_provider)
        self.director = director or DeterministicSceneDirector()
        self.encounter_engine = EncounterEngine()
        self.include_private_os = include_private_os
        self.initial_memories = initial_memories

    def run(self, *, run_id: str, seed: str) -> CoreRun:
        world = self.bundle.world.model_copy(deep=True)
        state = world.initial_state.model_copy(deep=True)
        state.status = "running"
        memories = self._initial_memories()
        fallback_count = 0
        executions: list[RoundExecution] = []
        actors = self._actor_registry(world)
        initial_snapshot = state.model_copy(deep=True)

        first_round_index = (
            state.tick_index + 1
            if state.world_version > 0
            else state.tick_index
        )
        for round_offset in range(self.bundle.round_count):
            round_index = first_round_index + round_offset
            state.tick_index = round_index
            before = state.model_copy(deep=True)
            snapshot = SnapshotProof(
                world_version=before.world_version,
                world_hash=canonical_state_checksum(before),
                tick_index=round_index,
            )
            proposals: list[ConcurrentProposal] = []
            turns: dict[OcId, StructuredActorTurn] = {}
            for profile in self.bundle.actor_profiles:
                proposal, turn, used_fallback = self._propose(
                    world,
                    before,
                    memories,
                    profile.oc_id,
                    seed,
                    round_index,
                    run_id,
                )
                fallback_count += int(used_fallback)
                proposals.append(proposal)
                turns[profile.oc_id] = turn
            proposals.sort(key=lambda proposal: proposal.proposal_id)
            conflicts = ConflictDetector().detect(proposals, world)
            adjudication = BatchRuleAdjudicator(world).adjudicate(
                run_id=run_id,
                round_index=round_index,
                seed=seed,
                snapshot=before,
                proposals=proposals,
                conflict_sets=conflicts,
            )
            after = AtomicBatchCommitter(world).commit(
                before,
                adjudication,
            )
            commit = _build_commit(
                run_id,
                round_index,
                before,
                after,
                adjudication.canonical_event,
            )
            perspectives, memory_deltas = self._project(
                world,
                after,
                adjudication,
                conflicts,
                turns,
                memories,
                round_index,
            )
            executions.append(
                RoundExecution(
                    round_index=round_index,
                    snapshot=snapshot,
                    proposals=proposals,
                    conflict_sets=conflicts,
                    adjudication=adjudication,
                    commit=commit,
                    state_before=before,
                    state_after=after,
                    perspectives=perspectives,
                    memory_deltas=memory_deltas,
                )
            )
            state = after

        return CoreRun(
            run_id=run_id,
            seed=seed,
            actors=actors,
            resident_presence=self._presence(
                world,
                initial_snapshot,
                actors,
                executions[0].proposals,
            ),
            rounds=executions,
            final_state=state,
            provider_fallback_count=fallback_count,
            memories=memories,
        )

    def _propose(
        self,
        world: WorldDefinition,
        snapshot: WorldState,
        memories: dict[OcId, list[ActorMemory]],
        actor_id: OcId,
        seed: str,
        round_index: int,
        run_id: str,
    ) -> tuple[ConcurrentProposal, StructuredActorTurn, bool]:
        actor = world.character(actor_id)
        location_id = snapshot.actor_locations.get(
            actor_id,
            actor.location_id,
        )
        participants = [
            profile.oc_id
            for profile in self.bundle.actor_profiles
            if snapshot.actor_locations.get(
                profile.oc_id,
                world.character(profile.oc_id).location_id,
            )
            == location_id
        ]
        pressure = self.director.organize(
            round_index=round_index,
            actor_id=actor_id,
            location_id=location_id,
            participant_ids=participants,
        )
        step = ScheduledStep(
            step_id=f"round-{round_index}:{actor_id}",
            due_tick=round_index,
            priority=1,
            actor_id=actor_id,
            reason="same-snapshot-proposal-barrier",
        )
        frame = self.encounter_engine.generate(
            world,
            snapshot,
            step,
            [pressure],
        )
        if not frame.affordances:
            raise DomainInvariantError(
                "actor has no legal affordance in the shared snapshot"
            )
        context = ActorPolicyContext(
            seed=seed,
            round_index=round_index,
            actor_id=actor_id,
            own_location_id=location_id,
            own_location_layer=world.location(location_id).layer,
            profile=self.bundle.actor_profile(actor_id),
            relationships=snapshot.relationships.get(actor_id, {}),
            memories=list(memories[actor_id]),
            affordances=frame.affordances,
        )
        provider_decision = self.provider.propose_turn(context)
        turn = provider_decision.turn
        affordance = next(
            (
                candidate
                for candidate in frame.affordances
                if candidate.affordance_id == turn.intent.affordance_id
            ),
            None,
        )
        if affordance is None:
            raise DomainInvariantError(
                "provider selected an affordance outside the snapshot"
            )
        self._assert_intent_allowed(affordance, turn)
        target_id, target_label, resource_id = _proposal_target(
            turn.intent,
            world,
        )
        proposal = ConcurrentProposal(
            proposal_id=f"{run_id}:round-{round_index}:{actor_id}:proposal",
            actor_id=actor_id,
            based_on_world_version=snapshot.world_version,
            intent=turn.intent,
            public_text=turn.public_text,
            private_inner_os_text=turn.private_inner_os_text,
            truth_posture=turn.truth_posture,
            target_label=target_label,
            target_id=target_id,
            resource_id=resource_id,
            precondition_labels=[
                "Affordance exists in the shared snapshot",
                f"Actor is present at {location_id}",
                f"World version equals {snapshot.world_version}",
            ],
            influenced_by_memory_ids=turn.influenced_by_memory_ids,
            influenced_by_relationship_ids=(
                turn.influenced_by_relationship_ids
            ),
        )
        return proposal, turn, provider_decision.fallback_used

    def _assert_intent_allowed(
        self,
        affordance: Affordance,
        turn: StructuredActorTurn,
    ) -> None:
        if turn.intent.kind == "UTTERANCE":
            proposal = UtteranceProposal(
                proposal_id="affordance-check",
                actor_id=turn.intent.actor_id,
                text=turn.public_text,
                audience="publicUi",
                based_on_belief_ids=[],
            )
        else:
            proposal = CharacterProposal(
                proposal_id="affordance-check",
                actor_id=turn.intent.actor_id,
                action=intent_to_character_action(turn.intent),
                motivation_refs=turn.intent.motivation_refs,
            )
        self.encounter_engine.assert_proposal_allowed(
            affordance,
            proposal,
        )

    def _project(
        self,
        world: WorldDefinition,
        state_after: WorldState,
        adjudication: BatchAdjudication,
        conflicts: list[ConflictSetProof],
        turns: dict[OcId, StructuredActorTurn],
        memories: dict[OcId, list[ActorMemory]],
        round_index: int,
    ) -> tuple[list[PerspectiveProof], list[MemoryDeltaProof]]:
        observations = PerspectiveProjector(world).project(
            adjudication.canonical_event,
            state_after,
        )
        all_atom_ids = {
            atom.atom_id
            for atom in adjudication.canonical_event.perceptual_atoms
        }
        atom_by_id = {
            atom.atom_id: atom
            for atom in adjudication.canonical_event.perceptual_atoms
        }
        conflict_participants = {
            proposal_id
            for conflict in conflicts
            for proposal_id in conflict.proposal_ids
        }
        critical_atom_ids = {
            atom.atom_id
            for proposal_id in conflict_participants
            for event in [
                adjudication.source_event_by_proposal.get(proposal_id)
            ]
            if event is not None
            for atom in event.perceptual_atoms
        }
        conflict_actor_ids = {
            proposal_id.split(":")[-2]
            for proposal_id in conflict_participants
        }
        perspective_proofs: list[PerspectiveProof] = []
        deltas: list[MemoryDeltaProof] = []
        for actor_id in sorted(turns):
            observation = observations[actor_id]
            observed_ids = {fact.atom_id for fact in observation.facts}
            unknown_ids = all_atom_ids - observed_ids
            saw_direct_detail = any(
                atom_by_id[fact_id].modality == "sight"
                for fact_id in observed_ids & critical_atom_ids
            )
            if saw_direct_detail:
                knowledge_state = "observed"
            elif actor_id in conflict_actor_ids and observed_ids:
                knowledge_state = "misunderstood"
            else:
                knowledge_state = "unknown"
            label, belief_summary, public_expression = (
                _perspective_text(knowledge_state)
            )
            observation_id = observation.observation_id
            actor_memory_deltas: list[MemoryDeltaProof] = []
            for fact in observation.facts:
                memory_id = (
                    f"memory:{round_index}:{actor_id}:{fact.atom_id}"
                )
                memory = ActorMemory(
                    memory_id=memory_id,
                    actor_id=actor_id,
                    source_round=round_index,
                    kind="observedFact",
                    statement=fact.code,
                    source_observation_ids=[observation_id],
                )
                memories[actor_id].append(memory)
                actor_memory_deltas.append(
                    MemoryDeltaProof(
                        actor_id=actor_id,
                        memory_id=memory_id,
                        summary=f"Remembered observable fact: {fact.code}",
                        source_observation_ids=[observation_id],
                    )
                )
            if knowledge_state == "misunderstood":
                inference_id = (
                    f"memory:{round_index}:{actor_id}:inference"
                )
                memories[actor_id].append(
                    ActorMemory(
                        memory_id=inference_id,
                        actor_id=actor_id,
                        source_round=round_index,
                        kind="inference",
                        statement="partial evidence may indicate resistance",
                        source_observation_ids=[observation_id],
                    )
                )
                actor_memory_deltas.append(
                    MemoryDeltaProof(
                        actor_id=actor_id,
                        memory_id=inference_id,
                        summary=(
                            "Formed a revisable inference from partial "
                            "evidence."
                        ),
                        source_observation_ids=[observation_id],
                    )
                )
            deltas.extend(actor_memory_deltas)
            private_ref = (
                f"private-os:{adjudication.canonical_event.canonical_event_id}:"
                f"{actor_id}"
            )
            perspective_proofs.append(
                PerspectiveProof(
                    actor_id=actor_id,
                    canonical_event_id=(
                        adjudication.canonical_event.canonical_event_id
                    ),
                    knowledge_state=knowledge_state,
                    observed_fact_ids=sorted(observed_ids),
                    unknown_fact_ids=sorted(unknown_ids),
                    perspective_label=label,
                    belief_summary=belief_summary,
                    memory_summary=(
                        f"{len(actor_memory_deltas)} memory changes were "
                        "derived only from this actor's observation."
                    ),
                    public_expression=public_expression,
                    private_os_available=True,
                    private_os_ref=private_ref,
                    private_inner_os=(
                        turns[actor_id].private_inner_os_text
                        if self.include_private_os
                        else None
                    ),
                )
            )
        return perspective_proofs, deltas

    def _initial_memories(self) -> dict[OcId, list[ActorMemory]]:
        if self.initial_memories is not None:
            return {
                actor_id: [
                    memory.model_copy(deep=True)
                    for memory in actor_memories
                ]
                for actor_id, actor_memories in self.initial_memories.items()
            }
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

    def _actor_registry(
        self,
        world: WorldDefinition,
    ) -> list[ActorRegistryProof]:
        return [
            ActorRegistryProof(
                actor_id=profile.oc_id,
                resident_id=_resident_mapping(profile.oc_id)["residentId"],
                display_name=world.character(profile.oc_id).name,
                screen_id=_resident_mapping(profile.oc_id)["screenId"],
            )
            for profile in sorted(
                self.bundle.actor_profiles,
                key=lambda item: item.oc_id,
            )
        ]

    def _presence(
        self,
        world: WorldDefinition,
        state: WorldState,
        actors: list[ActorRegistryProof],
        proposals: list[ConcurrentProposal],
    ) -> list[ResidentPresenceProof]:
        proposal_by_actor = {
            proposal.actor_id: proposal for proposal in proposals
        }
        return [
            ResidentPresenceProof(
                actor_id=actor.actor_id,
                resident_id=actor.resident_id,
                display_name=actor.display_name,
                floor_id=(
                    "floor-adventure"
                    if world.location(
                        state.actor_locations.get(
                            actor.actor_id,
                            world.character(actor.actor_id).location_id,
                        )
                    ).layer
                    == "adventure"
                    else "floor-safe"
                ),
                room_id=_resident_mapping(actor.actor_id)["roomId"],
                location_id=state.actor_locations.get(
                    actor.actor_id,
                    world.character(actor.actor_id).location_id,
                ),
                presence=_presence_value(world, state, actor.actor_id),
                activity_label=proposal_by_actor[
                    actor.actor_id
                ].to_proof().intent_label,
            )
            for actor in actors
        ]


def _build_commit(
    run_id: str,
    round_index: int,
    before: WorldState,
    after: WorldState,
    event: CanonicalEvent,
) -> CommitProof:
    return CommitProof(
        commit_id=f"{run_id}:round-{round_index}:commit",
        canonical_event_id=event.canonical_event_id,
        from_version=before.world_version,
        to_version=after.world_version,
        before_hash=canonical_state_checksum(before),
        after_hash=canonical_state_checksum(after),
        committed_at=(
            datetime(2026, 7, 24, tzinfo=UTC)
            + timedelta(seconds=round_index + 1)
        ),
        tick_index=round_index,
        rolled_back=False,
    )


def _build_persistence(
    rounds: list[RoundExecution],
) -> PersistenceProof:
    first, second = rounds[0], rounds[1]
    relationship_deltas: list[RelationshipDeltaProof] = []
    for index, effect in enumerate(first.adjudication.canonical_event.effects):
        parts = effect.path.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "relationships":
            continue
        relationship_deltas.append(
            RelationshipDeltaProof(
                delta_id=(
                    f"relationship-delta:{first.round_index}:{index}"
                ),
                from_actor_id=parts[1],
                to_actor_id=parts[2],
                dimension=parts[3],
                before=int(effect.before),
                after=int(effect.after),
                cause_canonical_event_id=(
                    first.adjudication.canonical_event.canonical_event_id
                ),
            )
        )
    first_by_actor = {
        proposal.actor_id: proposal for proposal in first.proposals
    }
    second_by_actor = {
        proposal.actor_id: proposal for proposal in second.proposals
    }
    memory_by_actor: dict[str, list[MemoryDeltaProof]] = {}
    for delta in first.memory_deltas:
        memory_by_actor.setdefault(delta.actor_id, []).append(delta)
    changed_actor = next(
        (
            actor_id
            for actor_id in sorted(first_by_actor)
            if actor_id in second_by_actor
            and (
                first_by_actor[actor_id].intent.kind
                != second_by_actor[actor_id].intent.kind
                or first_by_actor[actor_id].target_id
                != second_by_actor[actor_id].target_id
            )
            and (
                second_by_actor[actor_id].influenced_by_memory_ids
                or second_by_actor[
                    actor_id
                ].influenced_by_relationship_ids
            )
        ),
        sorted(second_by_actor)[0],
    )
    previous = first_by_actor.get(changed_actor)
    next_proposal = second_by_actor[changed_actor]
    related_relationship_ids = list(
        next_proposal.influenced_by_relationship_ids
    )
    return PersistenceProof(
        memory_deltas=first.memory_deltas,
        relationship_deltas=relationship_deltas,
        next_round_evidence=NextRoundEvidenceProof(
            actor_id=changed_actor,
            previous_proposal_id=(
                previous.proposal_id if previous is not None else None
            ),
            next_proposal_id=next_proposal.proposal_id,
            changed_because_memory_ids=list(
                next_proposal.influenced_by_memory_ids
            ),
            changed_because_relationship_ids=related_relationship_ids,
            summary=(
                "The next proposal differs after this actor carried "
                "forward its own observation-derived memory and the "
                "committed relationship state."
            ),
        ),
    )


def _proposal_target(
    intent: StructuredIntent,
    world: WorldDefinition,
) -> tuple[str | None, str | None, str | None]:
    if intent.kind in {"TAKE", "GIVE"} and intent.object_id:
        world_object = world.initial_state.objects[intent.object_id]
        return (
            intent.object_id,
            world_object.name,
            f"object:{intent.object_id}",
        )
    if intent.kind == "MOVE" and intent.location_id:
        return (
            intent.location_id,
            world.location(intent.location_id).name,
            f"actor-location:{intent.actor_id}",
        )
    return (
        intent.recipient_id,
        str(intent.recipient_id) if intent.recipient_id else None,
        f"expression:{intent.actor_id}",
    )


def _intent_label(
    intent: StructuredIntent,
    target_label: str | None,
) -> str:
    verb = {
        "TAKE": "attempt to take",
        "GIVE": "offer",
        "MOVE": "move to",
        "UTTERANCE": "speak publicly",
        "WAIT": "remain quiet",
    }[intent.kind]
    return f"{verb} {target_label}".strip() if target_label else verb


def _perspective_text(
    knowledge_state: str,
) -> tuple[str, str, str]:
    if knowledge_state == "observed":
        return (
            "Direct witness",
            "The actor has direct perceptual evidence for the key fact.",
            "I saw enough to describe what the rules allowed.",
        )
    if knowledge_state == "misunderstood":
        return (
            "Partial evidence, revisable interpretation",
            "The actor inferred more than the partial evidence proves.",
            "I only caught fragments; I suspect something went wrong.",
        )
    return (
        "Key fact remains unknown",
        "The actor lacks direct evidence for the key fact.",
        "I did not witness the crucial part, so I cannot claim it.",
    )


def _presence_value(
    world: WorldDefinition,
    state: WorldState,
    actor_id: str,
) -> Literal["home", "away", "adventure", "offline"]:
    character = world.character(actor_id)
    location_id = state.actor_locations.get(actor_id, character.location_id)
    if world.location(location_id).layer == "adventure":
        return "adventure"
    return "home" if location_id == character.location_id else "away"


def _resident_mapping(actor_id: str) -> dict[str, str]:
    mapping = {
        "oc-angel": {
            "residentId": "resident-oo",
            "roomId": "room-oo",
            "screenId": "screen-oo",
        },
        "oc-devil": {
            "residentId": "resident-cc",
            "roomId": "room-cc",
            "screenId": "screen-cc",
        },
        "oc-user": {
            "residentId": "resident-demo-user",
            "roomId": "room-demo-user",
            "screenId": "screen-demo-user",
        },
    }
    return mapping.get(
        actor_id,
        {
            "residentId": f"resident-{actor_id}",
            "roomId": f"room-{actor_id}",
            "screenId": f"screen-{actor_id}",
        },
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}:{_hash_payload(parts)[:16]}"


def _hash_payload(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

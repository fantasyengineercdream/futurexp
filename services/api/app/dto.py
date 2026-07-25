from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import AwareDatetime, Field, TypeAdapter

from app.domain.models import (
    Belief,
    CanonicalEvent,
    CharacterProposal,
    ContractModel,
    DmProposal,
    Observation,
    OcId,
    PrivateOs,
    RuleDecision,
    Utterance,
    UtteranceProposal,
    WorldState,
)


class PublicVisibility(ContractModel):
    scope: Literal["public"]


class OwnerVisibility(ContractModel):
    scope: Literal["owner"]
    oc_id: OcId


class ActorVisibility(ContractModel):
    scope: Literal["actor"]
    oc_id: OcId


class TechVisibility(ContractModel):
    scope: Literal["tech"]


EventVisibility: TypeAlias = Annotated[
    PublicVisibility | OwnerVisibility | ActorVisibility | TechVisibility,
    Field(discriminator="scope"),
]


class SessionSnapshot(ContractModel):
    session_id: str
    world_version: int = Field(ge=0)
    tick_index: int = Field(ge=0)
    last_canonical_sequence: int = Field(ge=0)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: WorldState


class SessionSnapshotPayload(ContractModel):
    snapshot: SessionSnapshot


class TickStartedPayload(ContractModel):
    actor_id: OcId
    world_version: int = Field(ge=0)


class CharacterProposalPayload(ContractModel):
    proposal: CharacterProposal


class DmProposalPayload(ContractModel):
    proposal: DmProposal


class UtteranceProposalPayload(ContractModel):
    proposal: UtteranceProposal


class RuleDecisionPayload(ContractModel):
    decision: RuleDecision


class CanonicalEventPayload(ContractModel):
    event: CanonicalEvent
    world_version: int = Field(ge=0)


class ObservationPayload(ContractModel):
    observation: Observation


class BeliefPayload(ContractModel):
    belief: Belief


class UtterancePayload(ContractModel):
    utterance: Utterance


class PrivateOsPayload(ContractModel):
    private_os: PrivateOs


class CompletionPayload(ContractModel):
    world_version: int = Field(ge=0)
    last_canonical_sequence: int = Field(ge=0)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class RuntimeErrorPayload(ContractModel):
    code: str
    message: str
    recoverable: bool


class RuntimeEventBase(ContractModel):
    schema_version: Literal[1]
    event_id: str
    cursor: int = Field(ge=1)
    session_id: str
    tick_index: int = Field(ge=0)
    emitted_at: AwareDatetime
    visibility: EventVisibility
    causation_id: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class SessionSnapshotEvent(RuntimeEventBase):
    type: Literal["session.snapshot"]
    payload: SessionSnapshotPayload


class TickStartedEvent(RuntimeEventBase):
    type: Literal["tick.started"]
    payload: TickStartedPayload


class CharacterProposalEvent(RuntimeEventBase):
    type: Literal["proposal.character.created"]
    payload: CharacterProposalPayload


class DmProposalEvent(RuntimeEventBase):
    type: Literal["proposal.dm.created"]
    payload: DmProposalPayload


class UtteranceProposalEvent(RuntimeEventBase):
    type: Literal["proposal.utterance.created"]
    payload: UtteranceProposalPayload


class RuleDecisionEvent(RuntimeEventBase):
    type: Literal["rule.decision.created"]
    payload: RuleDecisionPayload


class CanonicalEventCommitted(RuntimeEventBase):
    type: Literal["canonical.event.committed"]
    payload: CanonicalEventPayload


class ObservationEvent(RuntimeEventBase):
    type: Literal["observation.created"]
    payload: ObservationPayload


class BeliefEvent(RuntimeEventBase):
    type: Literal["belief.updated"]
    payload: BeliefPayload


class UtteranceEvent(RuntimeEventBase):
    type: Literal["utterance.created"]
    payload: UtterancePayload


class PrivateOsEvent(RuntimeEventBase):
    type: Literal["privateOs.created"]
    payload: PrivateOsPayload


class TickCompletedEvent(RuntimeEventBase):
    type: Literal["tick.completed"]
    payload: CompletionPayload


class SessionCompletedEvent(RuntimeEventBase):
    type: Literal["session.completed"]
    payload: CompletionPayload


class RuntimeErrorEvent(RuntimeEventBase):
    type: Literal["runtime.error"]
    payload: RuntimeErrorPayload


RuntimeEvent: TypeAlias = Annotated[
    SessionSnapshotEvent
    | TickStartedEvent
    | CharacterProposalEvent
    | DmProposalEvent
    | UtteranceProposalEvent
    | RuleDecisionEvent
    | CanonicalEventCommitted
    | ObservationEvent
    | BeliefEvent
    | UtteranceEvent
    | PrivateOsEvent
    | TickCompletedEvent
    | SessionCompletedEvent
    | RuntimeErrorEvent,
    Field(discriminator="type"),
]
RuntimeEventAdapter: TypeAdapter[RuntimeEvent] = TypeAdapter(RuntimeEvent)


class WorldRuleView(ContractModel):
    rule_id: str
    kind: str
    label: str
    description: str
    enabled: bool
    params: dict


class WorldInfoView(ContractModel):
    world_id: Literal["infinite-apartment"]
    name: Literal["无限公寓"]
    aesthetic: str
    description: str
    rules: list[WorldRuleView]


class SessionViewBase(ContractModel):
    session_id: str
    world_id: Literal["infinite-apartment"]
    status: Literal["running", "completed", "failed"]
    consent_required: bool
    last_cursor: int = Field(ge=0)
    events: list[RuntimeEvent]


class WorldSessionView(SessionViewBase):
    world: WorldInfoView


class OwnerOcView(ContractModel):
    oc_id: Literal["oc-user"]
    name: str
    role: str
    persona: str
    public_style: str


class OwnerSessionView(SessionViewBase):
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    oc: OwnerOcView


class ProofSessionView(SessionViewBase):
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    objective_state: WorldState


class PassportView(ContractModel):
    oc_id: Literal["oc-user"]
    world_id: Literal["infinite-apartment"]
    name: str
    role: str
    public_style: str
    public_experience: str


class ErrorDto(ContractModel):
    code: str
    message: str
    retryable: bool

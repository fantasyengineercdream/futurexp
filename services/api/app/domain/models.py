from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field


def to_lower_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_lower_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Relationship(ContractModel):
    trust: int = Field(ge=-3, le=3)
    affinity: int = Field(ge=-3, le=3)
    tension: int = Field(ge=-3, le=3)


OcId: TypeAlias = str


class Goal(ContractModel):
    goal_id: str
    text: str


class Secret(ContractModel):
    secret_id: str
    text: str


class Character(ContractModel):
    oc_id: OcId
    name: str
    role: str
    persona: str
    public_style: str
    location_id: str
    goals: list[Goal]
    secrets: list[Secret]
    senses: list[Literal["sight", "hearing", "system"]]
    relationships: dict[OcId, Relationship]


class ExecutableRule(ContractModel):
    rule_id: str
    kind: Literal[
        "CONSENTED_TRANSFER_ONLY",
        "KEY_UNLOCKS_THRESHOLD",
        "COUNTDOWN",
        "SOCIAL_CONSEQUENCE",
        "LOCATION_TRANSITION",
    ]
    label: str
    description: str
    enabled: bool
    params: dict[str, Any]


class Location(ContractModel):
    location_id: str
    name: str
    description: str
    occludes_sight_for: list[str]
    layer: Literal["safe", "adventure"] = "safe"
    persistence: Literal["persistent", "eventInstance"] = "persistent"
    return_location_id: str | None = None


class ScenarioTemplate(ContractModel):
    template_id: str
    kind: Literal["PRESSURE", "REVEAL_CUE", "ADVANCE_CLOCK"]
    description: str
    allowed_params: dict[str, Any]


class WorldObject(ContractModel):
    object_id: str
    name: str
    location_id: str
    holder_id: OcId | None
    tags: list[str]


class WorldState(ContractModel):
    world_id: Literal["infinite-apartment"]
    world_version: int = Field(ge=0)
    tick_index: int = Field(ge=0)
    status: Literal["ready", "running", "completed", "failed"]
    objects: dict[str, WorldObject]
    threshold_unlocked: bool
    countdown: int | None
    relationships: dict[OcId, dict[OcId, Relationship]]
    actor_locations: dict[OcId, str] = Field(
        default_factory=dict,
        exclude_if=lambda value: not value,
    )


class WorldDefinition(ContractModel):
    fixture_type: Literal["world"]
    world_id: Literal["infinite-apartment"]
    world_version: int
    name: Literal["无限公寓"]
    aesthetic: str
    description: str
    rules: list[ExecutableRule]
    locations: list[Location]
    characters: list[Character]
    initial_state: WorldState
    event_seed: str
    scenario_catalog: list[ScenarioTemplate]

    def rule(self, kind: str) -> ExecutableRule | None:
        return next((rule for rule in self.rules if rule.kind == kind), None)

    def character(self, oc_id: OcId) -> Character:
        return next(character for character in self.characters if character.oc_id == oc_id)

    def location(self, location_id: str) -> Location:
        return next(
            location for location in self.locations if location.location_id == location_id
        )


class TakeAction(ContractModel):
    kind: Literal["TAKE"]
    object_id: str


class GiveAction(ContractModel):
    kind: Literal["GIVE"]
    object_id: str
    recipient_id: OcId


class AccuseAction(ContractModel):
    kind: Literal["ACCUSE"]
    target_id: OcId
    claim: str


class MoveAction(ContractModel):
    kind: Literal["MOVE"]
    location_id: str


class WaitAction(ContractModel):
    kind: Literal["WAIT"]
    reason: str


CharacterAction: TypeAlias = Annotated[
    TakeAction | GiveAction | AccuseAction | MoveAction | WaitAction,
    Field(discriminator="kind"),
]


class CharacterProposal(ContractModel):
    proposal_id: str
    actor_id: OcId
    action: CharacterAction
    motivation_refs: list[str]
    proposed_public_line: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class DmProposal(ContractModel):
    proposal_id: str
    template_id: str
    kind: Literal["PRESSURE", "REVEAL_CUE", "ADVANCE_CLOCK"]
    params: dict[str, Any]


class UtteranceProposal(ContractModel):
    proposal_id: str
    actor_id: OcId
    text: str
    audience: Literal["world", "owner", "publicUi"]
    based_on_belief_ids: list[str]


class RuleDecision(ContractModel):
    decision_id: str
    proposal_id: str
    verdict: Literal["reject_invalid", "resolved"]
    outcome: Literal["success", "blocked", "with_cost"] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    matched_rule_ids: list[str]
    reason_codes: list[str]


class StateEffect(ContractModel):
    op: Literal["set", "inc"]
    path: str
    before: Any
    after: Any
    by: int | float | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )


class PerceptualAtom(ContractModel):
    atom_id: str
    code: str
    modality: Literal["sight", "hearing", "system"]
    location_id: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    line_of_sight_required: bool
    data: dict[str, Any]


class CanonicalEvent(ContractModel):
    canonical_event_id: str
    sequence: int = Field(ge=1)
    kind: Literal[
        "dm.intervention.applied",
        "action.resolved",
        "utterance.spoken",
        "session.completed",
    ]
    actor_id: OcId | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    decision_id: str
    fact_codes: list[str]
    effects: list[StateEffect]
    perceptual_atoms: list[PerceptualAtom]


class ObservationFact(ContractModel):
    atom_id: str
    code: str
    data: dict[str, Any]


class Observation(ContractModel):
    observation_id: str
    canonical_event_id: str
    oc_id: OcId
    channels: list[Literal["sight", "hearing", "system"]]
    facts: list[ObservationFact]
    completeness: Literal["full", "partial"]
    source: Literal["direct", "reported"] = "direct"


class Belief(ContractModel):
    belief_id: str
    oc_id: OcId
    predicate: str
    object: Any
    stance: Literal["suspected", "believed", "disbelieved"]
    confidence: float = Field(ge=0, le=1)
    source_observation_ids: list[str]


class Utterance(ContractModel):
    utterance_id: str
    oc_id: OcId
    canonical_event_id: str
    audience: Literal["world", "owner", "publicUi"]
    text: str
    based_on_belief_ids: list[str]
    truth_posture: Literal["candid", "uncertain", "withholding", "misrepresenting"]


class PrivateOs(ContractModel):
    private_os_id: str
    oc_id: OcId
    canonical_event_id: str
    text: str
    based_on_belief_ids: list[str]
    delivery: Literal["ownerPrivate"] = "ownerPrivate"


class MindProjection(ContractModel):
    belief: Belief
    utterance: Utterance | None = None
    private_os: PrivateOs | None = None


class ResolutionReceipt(ContractModel):
    receipt_id: str
    proposal_id: str
    proposal_fingerprint: str
    decision_id: str
    verdict: Literal["reject_invalid", "resolved"]
    outcome: Literal["success", "blocked", "with_cost"] | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    matched_rule_ids: list[str]
    reason_codes: list[str]
    input_world_version: int = Field(ge=0)
    rule_fingerprint: str
    effects_fingerprint: str
    canonical_event_id: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    canonical_event_fingerprint: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    receipt_fingerprint: str
    issuer_signature: str


class Resolution(ContractModel):
    decision: RuleDecision
    event: CanonicalEvent | None
    receipt: ResolutionReceipt

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from app.domain.encounters import Affordance, DramaticPressure
from app.domain.models import (
    CanonicalEvent,
    CharacterAction,
    ContractModel,
    ExecutableRule,
    Location,
    ObservationFact,
    OcId,
    PrivateOs,
    Relationship,
    ResolutionReceipt,
    Utterance,
    WorldDefinition,
    WorldObject,
)
from app.errors import DomainInvariantError


ActionKind = Literal["TAKE", "GIVE", "MOVE", "UTTERANCE", "WAIT"]


class RpgStats(ContractModel):
    intellect: int = Field(default=1, ge=-2, le=5)
    athletics: int = Field(default=1, ge=-2, le=5)
    insight: int = Field(default=1, ge=-2, le=5)
    presence: int = Field(default=1, ge=-2, le=5)


class RuntimeActorProfile(ContractModel):
    oc_id: OcId
    persona_constraints: list[str] = Field(min_length=1)
    goal_refs: list[str] = Field(min_length=1)
    initial_memories: list[str]
    action_preferences: list[ActionKind] = Field(min_length=1)
    home_location_id: str
    daily_location_preferences: list[str] = Field(min_length=1)
    rpg_stats: RpgStats = Field(default_factory=RpgStats)


class PresetRuntimeBundleFixture(ContractModel):
    fixture_type: Literal["living-world-runtime-bundle"]
    bundle_id: str
    bundle_version: Literal["0.1"]
    world_fixture: str
    default_seed: str
    round_count: int = Field(ge=2, le=2)
    initial_locations: dict[OcId, str]
    location_extensions: list[Location]
    object_extensions: list[WorldObject]
    rule_extensions: list[ExecutableRule]
    actor_profiles: list[RuntimeActorProfile] = Field(min_length=1)


class RuntimeBundle(ContractModel):
    """Internal preset adapter, not the future public editor bundle schema."""

    bundle_id: str
    bundle_version: Literal["0.1"]
    default_seed: str
    round_count: int
    world: WorldDefinition
    actor_profiles: list[RuntimeActorProfile]

    def actor_profile(self, actor_id: OcId) -> RuntimeActorProfile:
        return next(
            profile
            for profile in self.actor_profiles
            if profile.oc_id == actor_id
        )


class ActorMemory(ContractModel):
    memory_id: str
    actor_id: OcId
    source_round: int = Field(ge=-1)
    kind: Literal["prior", "observedFact", "inference", "ownerCounsel"]
    statement: str
    source_observation_ids: list[str]


class UnknownArea(ContractModel):
    label: str
    source_event_id: str


class StructuredIntent(ContractModel):
    actor_id: OcId
    affordance_id: str
    kind: ActionKind
    proposed_by: Literal["actorPolicy"] = "actorPolicy"
    motivation_refs: list[str]
    object_id: str | None = None
    recipient_id: OcId | None = None
    location_id: str | None = None
    utterance_text: str | None = None


class StructuredActorTurn(ContractModel):
    intent: StructuredIntent
    public_text: str
    private_inner_os_text: str
    truth_posture: Literal[
        "candid",
        "uncertain",
        "withholding",
        "misrepresenting",
    ]
    influenced_by_memory_ids: list[str] = Field(default_factory=list)
    influenced_by_relationship_ids: list[str] = Field(default_factory=list)


class ActorPolicyContext(ContractModel):
    seed: str
    round_index: int = Field(ge=0)
    actor_id: OcId
    own_location_id: str
    own_location_layer: Literal["safe", "adventure"]
    profile: RuntimeActorProfile
    relationships: dict[OcId, Relationship]
    memories: list[ActorMemory]
    affordances: list[Affordance] = Field(min_length=1)


class ActorPolicyProvider:
    """Provider boundary for a model-backed or deterministic ActorPolicy."""

    provider_id = "abstract-actor-policy"

    def propose_turn(self, context: ActorPolicyContext) -> StructuredActorTurn:
        raise NotImplementedError


class DeterministicSceneDirector:
    """Organizes a finite opportunity frame without selecting actor actions."""

    director_id = "deterministic-scene-director-v01"
    system_prompt = (
        "默认编排 OC 的日常生活与社交机会；"
        "没有明确发布的任务时不得主动生成冒险。"
        "DM 只决定地点、相遇与压力，不替 OC 选择行动，"
        "也不能替 Rule Kernel 宣布结果。"
    )

    def __init__(self, *, adventure_published: bool = False) -> None:
        self.adventure_published = adventure_published

    def organize(
        self,
        *,
        round_index: int,
        actor_id: OcId,
        location_id: str,
        participant_ids: list[OcId],
    ) -> DramaticPressure:
        if self.adventure_published and round_index == 0:
            hook = (
                "公共层短暂开启了一间临时冒险房间；"
                "进入完全自愿，公共空间通行牌仍归原持有人。"
            )
            goal_or_conflict = (
                "是否进入，以及其他人能否在不夺取通行牌的情况下介入。"
            )
            stakes = [
                "进入者会暂时与同伴分离",
                "夺取通行牌会被世界规则阻止",
            ]
            failure_condition = "任何夺取他人通行牌的行动都会被规则阻止。"
            cost_or_consequence = (
                "强行介入会失败，并让目击者之间的关系更加紧张。"
            )
            persistent_fallout = (
                "进入者的经历、目击者的误解和关系变化会被带到幕间。"
            )
            allowed_action_kinds = ["GIVE", "MOVE", "TAKE", "UTTERANCE"]
            destination_location_ids: list[str] = []
        elif location_id == "adventure-instance-01":
            hook = "临时冒险房间即将关闭，进入者必须决定是否返回安全层。"
            goal_or_conflict = "带着经历返回，而不是被留在事件实例中。"
            stakes = ["及时返回安全层", "保留这次经历造成的记忆"]
            failure_condition = "拒绝合法返回会让事件无法正常结束。"
            cost_or_consequence = "返回不会抹去已经发生的关系与认知变化。"
            persistent_fallout = "进入者会把自己的版本带回私人房间。"
            allowed_action_kinds = ["GIVE", "MOVE", "TAKE", "UTTERANCE"]
            destination_location_ids = []
        elif self.adventure_published:
            hook = "进入者即将归来，公共层必须面对刚才留下的冲突。"
            goal_or_conflict = "等待归来，同时决定如何处理刚才的越界行为。"
            stakes = ["关系不会自动恢复", "公开说法可能与内心判断不同"]
            failure_condition = "假装什么都没发生，无法消除已经提交的后果。"
            cost_or_consequence = "角色必须带着新的关系状态继续相处。"
            persistent_fallout = "冲突会进入各自的记忆与幕间表达。"
            allowed_action_kinds = ["GIVE", "MOVE", "TAKE", "UTTERANCE"]
            destination_location_ids = []
        elif round_index % 2 == 0:
            hook = (
                "今天是普通的日常。每个 OC 可以自己安排一个主要去处，"
                "也可以选择留在原地休息。"
            )
            goal_or_conflict = "根据自己的习惯、目标和记忆选择今天的去处。"
            stakes = ["今天的地点会决定可能遇见谁"]
            failure_condition = "DM 不能替 OC 选择目的地。"
            cost_or_consequence = "移动会改变公开位置；等待不会制造额外事实。"
            persistent_fallout = "今天真正经历的内容会进入自己的记忆。"
            allowed_action_kinds = ["MOVE", "WAIT"]
            destination_location_ids = [
                "apartment-bar",
                "apartment-library",
                "grand-foyer",
                "mirror-curtain",
            ]
        else:
            hook = (
                "同处一个空间的 OC 获得了一次日常社交机会。"
                "任何人都可以交谈，也可以保持沉默。"
            )
            goal_or_conflict = (
                "在不强迫任何人的情况下，决定是否交谈。"
            )
            stakes = ["一次回应可能让关系更近，也可能留下新的误会"]
            failure_condition = "DM 不能替任何 OC 决定说什么或做什么。"
            cost_or_consequence = "公开表达会成为其他在场者能够记住的经历。"
            persistent_fallout = "今天的相处会进入各自的记忆，并影响以后。"
            allowed_action_kinds = ["UTTERANCE", "WAIT"]
            destination_location_ids = []
        return DramaticPressure(
            pressure_id=f"round-{round_index}:{actor_id}:living-scene",
            source_kind="relationship",
            hook=hook,
            goal_or_conflict=goal_or_conflict,
            eligible_actor_ids=[actor_id],
            participant_ids=participant_ids,
            location_ids=[location_id],
            opens_at_tick=round_index,
            expires_at_tick=round_index,
            allowed_action_kinds=allowed_action_kinds,
            destination_location_ids=destination_location_ids,
            evidence_refs=[
                f"round:{round_index}",
                f"location:{location_id}",
            ],
            stakes=stakes,
            failure_condition=failure_condition,
            cost_or_consequence=cost_or_consequence,
            persistent_fallout=persistent_fallout,
        )


class DeterministicActorPolicyProvider(ActorPolicyProvider):
    """Credential-free fallback that only chooses from supplied affordances."""

    provider_id = "deterministic-v01"

    def propose_turn(self, context: ActorPolicyContext) -> StructuredActorTurn:
        observed_codes = {
            memory.statement
            for memory in context.memories
            if memory.kind == "observedFact"
        }
        affordances_by_kind = {
            kind: sorted(
                (
                    affordance
                    for affordance in context.affordances
                    if affordance.action_kind == kind
                ),
                key=lambda item: item.affordance_id,
            )
            for kind in {
                affordance.action_kind
                for affordance in context.affordances
            }
        }
        daily_planning = any(
            "安排一个主要去处" in affordance.hook
            for affordance in context.affordances
        )
        daily_social = any(
            "日常社交机会" in affordance.hook
            for affordance in context.affordances
        )
        selected: Affordance | None = None
        chosen_destination: str | None = None
        influenced_by_memory_ids: list[str] = []
        influenced_by_relationship_ids: list[str] = []
        if daily_planning:
            day_index = context.round_index // 2
            owner_counsel = any(
                memory.kind == "ownerCounsel"
                for memory in context.memories
            )
            if owner_counsel:
                influenced_by_memory_ids = [
                    memory.memory_id
                    for memory in context.memories
                    if memory.kind == "ownerCounsel"
                ]
            preferences = context.profile.daily_location_preferences
            chosen_destination = (
                "apartment-library"
                if owner_counsel
                else preferences[day_index % len(preferences)]
            )
            move = next(
                iter(affordances_by_kind.get("MOVE", [])),
                None,
            )
            wait = next(
                iter(affordances_by_kind.get("WAIT", [])),
                None,
            )
            if (
                move is not None
                and chosen_destination != context.own_location_id
                and chosen_destination
                in move.constraints.get("destinationIds", [])
            ):
                selected = move
            else:
                selected = wait
        elif daily_social:
            tense_relationship_ids = [
                f"relationship:{context.actor_id}:{target_id}:tension"
                for target_id, relationship in context.relationships.items()
                if relationship.tension > 0
            ]
            owner_counsel = any(
                memory.kind == "ownerCounsel"
                for memory in context.memories
            )
            if tense_relationship_ids:
                preferred_kind = "WAIT"
                influenced_by_relationship_ids = tense_relationship_ids
            elif context.actor_id == "oc-devil" and not owner_counsel:
                preferred_kind = "WAIT"
            else:
                preferred_kind = "UTTERANCE"
            selected = next(
                iter(affordances_by_kind.get(preferred_kind, [])),
                None,
            )
        else:
            for action_kind in context.profile.action_preferences:
                if (
                    action_kind == "TAKE"
                    and "object.resisted.take" in observed_codes
                ):
                    influenced_by_memory_ids.extend(
                        memory.memory_id
                        for memory in context.memories
                        if memory.statement == "object.resisted.take"
                    )
                    continue
                candidates = affordances_by_kind.get(action_kind, [])
                if candidates:
                    selected = candidates[0]
                    break
        if selected is None:
            raise DomainInvariantError("actor has no selectable affordance")

        relationship_pressure = max(
            (
                abs(relationship.tension)
                for relationship in context.relationships.values()
            ),
            default=0,
        )
        adventure_public_text = {
            (0, "oc-angel"): (
                "先别抢。她是自己进去的，我们至少该等她回来。"
            ),
            (0, "oc-devil"): (
                "那块通行牌不能只由她拿着，我要确认入口到底通向哪里。"
            ),
            (0, "oc-user"): "我自己进去。你们留在外面，等我回来。",
            (1, "oc-angel"): (
                "她回来了。刚才那一下，不代表我们之间的问题消失了。"
            ),
            (1, "oc-devil"): (
                "好，我不再碰那块牌。但我仍然要一个解释。"
            ),
            (1, "oc-user"): (
                "我回来了。里面发生的事，我想先自己理清。"
            ),
        }.get(
            (context.round_index, context.actor_id),
            (
                f"{context.actor_id}在关系压力"
                f"{relationship_pressure}下作出了自己的选择。"
            ),
        )
        adventure_private_text = {
            (0, "oc-angel"): (
                "我没看清入口里发生了什么，但我不想让任何人趁机伤害她。"
            ),
            (0, "oc-devil"): (
                "规则挡住了我。最让我恼火的，是他们会把这理解成恶意。"
            ),
            (0, "oc-user"): (
                "其实我也害怕，但这是我自己决定要进去的。"
            ),
            (1, "oc-angel"): (
                "她平安回来就好，可我还不能相信刚才伸手抢牌的人。"
            ),
            (1, "oc-devil"): (
                "我已经收手了，但他们显然不会立刻原谅我。"
            ),
            (1, "oc-user"): (
                "我还没准备好把里面的一切都告诉他们。"
            ),
        }.get(
            (context.round_index, context.actor_id),
            (
                f"我带着{len(context.memories)}段记忆作出选择，"
                "但没有义务把所有想法都说出口。"
            ),
        )
        is_daily_scene = any(
            "日常" in affordance.hook
            for affordance in context.affordances
        )
        public_text = (
            {
                "oc-angel": "今天没什么大事。要不要坐下来聊一会儿？",
                "oc-devil": "我只是路过，不过听听你们在说什么也无妨。",
                "oc-user": "今天我想慢一点，先和你们聊聊近况。",
            }.get(
                context.actor_id,
                f"{context.actor_id}决定参与今天的日常交谈。",
            )
            if is_daily_scene
            else adventure_public_text
        )
        private_text = (
            {
                "oc-angel": "平静的一天也值得记住，我想知道他们最近过得怎样。",
                "oc-devil": "我没有必要表现得太热情，但我确实有点好奇。",
                "oc-user": "今天不需要解决什么大问题，只想听听他们的近况。",
            }.get(
                context.actor_id,
                f"我带着{len(context.memories)}段记忆参与今天的相处。",
            )
            if is_daily_scene
            else adventure_private_text
        )
        intent = StructuredIntent(
            actor_id=context.actor_id,
            affordance_id=selected.affordance_id,
            kind=selected.action_kind,
            motivation_refs=context.profile.goal_refs,
            utterance_text=(
                public_text if selected.action_kind == "UTTERANCE" else None
            ),
        )
        if selected.action_kind == "MOVE":
            intent.location_id = chosen_destination or str(
                selected.constraints["destinationIds"][0]
            )
        elif selected.action_kind == "TAKE":
            intent.object_id = str(selected.constraints["objectIds"][0])
        elif selected.action_kind == "GIVE":
            intent.object_id = str(selected.constraints["objectIds"][0])
            intent.recipient_id = selected.constraints["recipientIds"][0]
        return StructuredActorTurn(
            intent=intent,
            public_text=public_text,
            private_inner_os_text=private_text,
            truth_posture=(
                "withholding"
                if context.profile.persona_constraints
                else "candid"
            ),
            influenced_by_memory_ids=list(
                dict.fromkeys(influenced_by_memory_ids)
            ),
            influenced_by_relationship_ids=list(
                dict.fromkeys(influenced_by_relationship_ids)
            ),
        )


class ProviderDecision(ContractModel):
    turn: StructuredActorTurn
    fallback_used: bool


class ResilientActorPolicyProvider:
    def __init__(
        self,
        primary: ActorPolicyProvider,
        fallback: ActorPolicyProvider | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback or DeterministicActorPolicyProvider()

    def propose_turn(self, context: ActorPolicyContext) -> ProviderDecision:
        try:
            turn = self.primary.propose_turn(context)
            return ProviderDecision(turn=turn, fallback_used=False)
        except Exception:
            turn = self.fallback.propose_turn(context)
            return ProviderDecision(turn=turn, fallback_used=True)


class ResolvedActorTurn(ContractModel):
    actor_id: OcId
    intent: StructuredIntent
    resolution_receipt: ResolutionReceipt
    input_memory_count: int = Field(ge=0)
    provider_id: str
    fallback_used: bool


class EpistemicView(ContractModel):
    actor_id: OcId
    observed_facts: list[ObservationFact]
    inferences: list[ActorMemory]
    unknowns: list[UnknownArea]
    memories: list[ActorMemory]


class ActorOutput(ContractModel):
    actor_id: OcId
    public_expression: Utterance
    private_inner_os: PrivateOs


class LivingWorldRound(ContractModel):
    round_index: int = Field(ge=0)
    turns: list[ResolvedActorTurn]
    epistemic_views: list[EpistemicView]
    outputs: list[ActorOutput]
    relationship_snapshot: dict[OcId, dict[OcId, Relationship]]
    location_snapshot: dict[OcId, str]


class LivingWorldRunResult(ContractModel):
    session_id: str
    bundle_id: str
    seed: str
    status: Literal["completed"]
    rounds: list[LivingWorldRound]
    canonical_ledger: list[CanonicalEvent]
    final_state: dict[str, Any]
    provider_fallback_count: int = Field(ge=0)
    replay_fingerprint: str
    semantic_trace: list[dict[str, Any]]


def intent_to_character_action(intent: StructuredIntent) -> CharacterAction:
    if intent.kind == "MOVE" and intent.location_id:
        return {
            "kind": "MOVE",
            "locationId": intent.location_id,
        }
    if intent.kind == "TAKE" and intent.object_id:
        return {
            "kind": "TAKE",
            "objectId": intent.object_id,
        }
    if (
        intent.kind == "GIVE"
        and intent.object_id
        and intent.recipient_id
    ):
        return {
            "kind": "GIVE",
            "objectId": intent.object_id,
            "recipientId": intent.recipient_id,
        }
    if intent.kind == "WAIT":
        return {
            "kind": "WAIT",
            "reason": "actor chose not to take a public action",
        }
    raise DomainInvariantError("intent cannot be converted to a character action")


def load_preset_runtime_bundle(
    path: Path | None = None,
) -> RuntimeBundle:
    root = Path(__file__).resolve().parents[4]
    bundle_path = path or (
        root / "fixtures" / "living-world-v01" / "runtime-bundle.json"
    )
    fixture = PresetRuntimeBundleFixture.model_validate_json(
        bundle_path.read_text(encoding="utf-8")
    )
    world_path = (bundle_path.parent / fixture.world_fixture).resolve()
    world = WorldDefinition.model_validate_json(
        world_path.read_text(encoding="utf-8")
    ).model_copy(deep=True)
    known_locations = {location.location_id for location in world.locations}
    for location in fixture.location_extensions:
        if location.location_id in known_locations:
            raise DomainInvariantError("bundle location extension is duplicated")
        world.locations.append(location)
        known_locations.add(location.location_id)
    for rule in fixture.rule_extensions:
        if any(existing.rule_id == rule.rule_id for existing in world.rules):
            raise DomainInvariantError("bundle rule extension is duplicated")
        world.rules.append(rule)
    for world_object in fixture.object_extensions:
        if world_object.object_id in world.initial_state.objects:
            raise DomainInvariantError("bundle object extension is duplicated")
        world.initial_state.objects[world_object.object_id] = world_object
    if set(fixture.initial_locations) != {
        character.oc_id for character in world.characters
    }:
        raise DomainInvariantError("bundle must locate exactly its three actors")
    if any(
        location_id not in known_locations
        for location_id in fixture.initial_locations.values()
    ):
        raise DomainInvariantError("bundle actor location does not exist")
    world.initial_state.actor_locations = dict(fixture.initial_locations)
    if {profile.oc_id for profile in fixture.actor_profiles} != set(
        fixture.initial_locations
    ):
        raise DomainInvariantError("bundle actor profiles do not match its cast")
    return RuntimeBundle(
        bundle_id=fixture.bundle_id,
        bundle_version=fixture.bundle_version,
        default_seed=fixture.default_seed,
        round_count=fixture.round_count,
        world=world,
        actor_profiles=fixture.actor_profiles,
    )


def stable_json(value: Any) -> str:
    if isinstance(value, ContractModel):
        value = value.model_dump(mode="json", by_alias=True)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

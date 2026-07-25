from __future__ import annotations

from datetime import timedelta
from typing import Literal

from pydantic import AwareDatetime, Field

from app.domain.living_world import ActorMemory, RuntimeBundle
from app.domain.models import ContractModel, Relationship, WorldDefinition
from app.domain.transactional_living_world import (
    ConcurrentProposal,
    CoreRun,
    LivingWorldProofDTO,
)


PresenceState = Literal["home", "public", "adventure", "resting", "away"]


class FloorProjection(ContractModel):
    floor_id: str
    label: str
    kind: Literal["safe", "neutral", "adventure"]
    palette_key: str
    status: Literal["active", "quiet", "unavailable"]


class RoomSummaryProjection(ContractModel):
    room_id: str
    floor_id: str
    screen_id: str
    label: str
    room_kind: Literal["private", "public", "adventure"]
    signal_state: PresenceState


class ResidentProductProjection(ContractModel):
    resident_id: str
    actor_id: str
    display_name: str
    room_id: str
    floor_id: str
    current_location_id: str
    presence: PresenceState
    public_activity_summary: str
    new_experience: bool
    room_available: bool
    last_changed_at: AwareDatetime


class PublicSceneProjection(ContractModel):
    scene_id: str
    location_id: str
    participant_ids: list[str]
    public_summary: str
    status: Literal["available", "active", "resolved", "failed"]


class WorldProjectionDTO(ContractModel):
    schema_version: Literal["0.2"] = "0.2"
    run_id: str
    world_version: int
    tick_index: int
    updated_at: AwareDatetime
    floors: list[FloorProjection]
    rooms: list[RoomSummaryProjection]
    residents: list[ResidentProductProjection]
    public_scenes: list[PublicSceneProjection]
    round_status: Literal["idle", "running", "committed", "failed"]
    summary: str | None = None


class LatestDiaryProjection(ContractModel):
    available: bool
    entry_id: str | None = None
    created_at: AwareDatetime | None = None
    summary: str | None = None


class RelationshipSummaryProjection(ContractModel):
    resident_id: str
    display_name: str
    state_label: str
    changed_recently: bool


class RoomCapabilitiesProjection(ContractModel):
    realtime_conversation: bool
    diary: bool
    rest: bool
    private_os: bool


class RoomProjectionDTO(ContractModel):
    schema_version: Literal["0.2"] = "0.2"
    run_id: str
    world_version: int
    resident_id: str
    actor_id: str
    room_id: str
    is_home: bool
    presence: PresenceState
    current_location_id: str
    public_mood: str
    public_activity_summary: str
    public_expression: str | None = None
    latest_diary: LatestDiaryProjection
    relationship_summaries: list[RelationshipSummaryProjection]
    capabilities: RoomCapabilitiesProjection
    private_os_available: bool
    private_os_ref: str | None = None
    recent_experience_refs: list[str]
    decision_basis_summary: str | None = None
    decision_memory_refs: list[str] = Field(default_factory=list)
    updated_at: AwareDatetime


class OwnerCounselRequest(ContractModel):
    experience_ref: str
    advice_id: Literal["verify-before-judging"]


class OwnerCounselReceiptDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    resident_id: str
    experience_ref: str
    advice_id: Literal["verify-before-judging"]
    disposition: Literal["considered"] = "considered"
    summary: str


class OwnerRoomDialogueRequest(ContractModel):
    message: str


class OwnerRoomDialogueDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    resident_id: str
    actor_id: str
    public_reply: str
    memory_refs_used: list[str]
    private_os_available: bool
    private_os_ref: str | None = None


class OwnerPrivateOsDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    world_version: int
    resident_id: str
    actor_id: str
    private_os_ref: str
    text: str
    memory_refs_used: list[str]


class LivingMemoryStoreDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    day_index: int
    memories: dict[str, list[ActorMemory]]


class ProductProjectionSet(ContractModel):
    world: WorldProjectionDTO
    rooms_by_resident_id: dict[str, RoomProjectionDTO]


def build_owner_dialogue(
    bundle: RuntimeBundle,
    room: RoomProjectionDTO,
    memory_store: LivingMemoryStoreDTO,
    message: str,
) -> OwnerRoomDialogueDTO:
    actor_memories = memory_store.memories.get(room.actor_id, [])
    selected_memories = actor_memories[-3:]
    profile = bundle.actor_profile(room.actor_id)
    counsel_remembered = any(
        memory.kind == "ownerCounsel"
        for memory in selected_memories
    )
    diary_summary = room.latest_diary.summary or "今天还没有可讲的经历。"
    if counsel_remembered:
        memory_line = "我记得你提醒过我：先核对证据，再判断别人。"
    else:
        memory_line = "我只会按自己真正看见和记住的部分告诉你。"
    return OwnerRoomDialogueDTO(
        run_id=room.run_id,
        resident_id=room.resident_id,
        actor_id=room.actor_id,
        public_reply=(
            f"{memory_line}{diary_summary}"
            f"至于你问的“{message[:24]}”，"
            f"我仍会守住“{profile.persona_constraints[0]}”这条底线。"
        ),
        memory_refs_used=[
            memory.memory_id for memory in selected_memories
        ],
        private_os_available=room.private_os_available,
        private_os_ref=(
            f"private-os:{room.run_id}:{room.actor_id}:"
            f"dialogue:{room.world_version}"
            if room.private_os_available
            else None
        ),
    )


def build_dialogue_private_os(
    room: RoomProjectionDTO,
    memory_store: LivingMemoryStoreDTO,
    dialogue: OwnerRoomDialogueDTO,
) -> OwnerPrivateOsDTO:
    actor_memories = memory_store.memories.get(room.actor_id, [])
    selected_memories = actor_memories[-3:]
    private_text = {
        "oc-angel": (
            "其实我还在担心自己是不是漏看了什么。"
            "我不想让你担心，所以刚才说得比心里平静。"
        ),
        "oc-devil": (
            "我嘴上说只是路过，其实我很在意他们有没有把我排除在外。"
        ),
        "oc-user": (
            "我还没有整理好全部感受，但我希望主人愿意继续听下去。"
        ),
    }.get(
        room.actor_id,
        "我没有把全部感受说出口，但这段经历确实留在了心里。",
    )
    return OwnerPrivateOsDTO(
        run_id=room.run_id,
        world_version=room.world_version,
        resident_id=room.resident_id,
        actor_id=room.actor_id,
        private_os_ref=str(dialogue.private_os_ref),
        text=private_text,
        memory_refs_used=[
            memory.memory_id for memory in selected_memories
        ],
    )


def build_demo_ready_projection(
    committed: WorldProjectionDTO,
) -> WorldProjectionDTO:
    """Build the deterministic pre-advance frame for the product demo."""

    ready_at = committed.updated_at - timedelta(seconds=1)
    return committed.model_copy(
        update={
            "world_version": max(0, committed.world_version - 1),
            "tick_index": max(0, committed.tick_index - 1),
            "updated_at": ready_at,
            "rooms": [
                room.model_copy(
                    update={
                        "floor_id": "floor-safe",
                        "signal_state": "home",
                    }
                )
                for room in committed.rooms
            ],
            "residents": [
                resident.model_copy(
                    update={
                        "floor_id": "floor-safe",
                        "current_location_id": resident.room_id,
                        "presence": "home",
                        "public_activity_summary": "正在房间里度过幕间",
                        "new_experience": False,
                        "room_available": False,
                        "last_changed_at": ready_at,
                    }
                )
                for resident in committed.residents
            ],
            "public_scenes": [],
            "round_status": "idle",
            "summary": "世界已就绪，等待运行下一轮。",
        }
    )


class ProductProjectionBuilder:
    """Builds public/owner read models without exposing proof internals."""

    def __init__(
        self,
        world: WorldDefinition,
        bundle: RuntimeBundle,
    ) -> None:
        self.world = world
        self.bundle = bundle

    def build(
        self,
        core_run: CoreRun,
        proof: LivingWorldProofDTO,
    ) -> ProductProjectionSet:
        final_state = core_run.final_state
        last_round = core_run.rounds[-1]
        updated_at = last_round.commit.committed_at
        actor_registry = {
            actor.actor_id: actor for actor in core_run.actors
        }
        resident_by_actor = {
            resident.actor_id: resident
            for resident in core_run.resident_presence
        }
        last_proposal_by_actor = {
            proposal.actor_id: proposal
            for proposal in last_round.proposals
        }
        last_perspective_by_actor = {
            perspective.actor_id: perspective
            for perspective in last_round.perspectives
        }
        memory_influence_by_actor: dict[str, list[str]] = {}
        for round_execution in core_run.rounds:
            for proposal in round_execution.proposals:
                refs = memory_influence_by_actor.setdefault(
                    proposal.actor_id,
                    [],
                )
                refs.extend(proposal.influenced_by_memory_ids)
        for actor_id, refs in memory_influence_by_actor.items():
            memory_influence_by_actor[actor_id] = list(
                dict.fromkeys(refs)
            )
        memory_by_id = {
            memory.memory_id: memory
            for actor_memories in core_run.memories.values()
            for memory in actor_memories
        }
        experience_by_actor: dict[str, list[str]] = {}
        for delta in last_round.memory_deltas:
            actor_experiences = experience_by_actor.setdefault(
                delta.actor_id,
                [],
            )
            actor_experiences.append(
                f"experience:{core_run.run_id}:"
                f"{last_round.round_index}:{delta.actor_id}:"
                f"{len(actor_experiences)}"
            )

        residents: list[ResidentProductProjection] = []
        rooms: list[RoomSummaryProjection] = []
        room_details: dict[str, RoomProjectionDTO] = {}
        for actor_id in sorted(actor_registry):
            actor = actor_registry[actor_id]
            resident_seed = resident_by_actor[actor_id]
            location_id = final_state.actor_locations.get(
                actor_id,
                self.world.character(actor_id).location_id,
            )
            presence = self._presence(actor_id, location_id)
            floor_id = (
                "floor-adventure"
                if presence == "adventure"
                else "floor-safe"
            )
            activity = self._activity_label(
                last_proposal_by_actor[actor_id]
            )
            residents.append(
                ResidentProductProjection(
                    resident_id=actor.resident_id,
                    actor_id=actor_id,
                    display_name=actor.display_name,
                    room_id=resident_seed.room_id,
                    floor_id=floor_id,
                    current_location_id=location_id,
                    presence=presence,
                    public_activity_summary=activity,
                    new_experience=bool(
                        experience_by_actor.get(actor_id)
                    ),
                    room_available=True,
                    last_changed_at=updated_at,
                )
            )
            rooms.append(
                RoomSummaryProjection(
                    room_id=resident_seed.room_id,
                    floor_id=floor_id,
                    screen_id=actor.screen_id,
                    label=f"{actor.display_name} 的房间",
                    room_kind="private",
                    signal_state=presence,
                )
            )
            perspective = last_perspective_by_actor[actor_id]
            decision_memory_refs = memory_influence_by_actor.get(
                actor_id,
                [],
            )
            owner_counsel_influenced = any(
                memory_by_id.get(memory_id) is not None
                and memory_by_id[memory_id].kind == "ownerCounsel"
                for memory_id in decision_memory_refs
            )
            room_details[actor.resident_id] = RoomProjectionDTO(
                run_id=core_run.run_id,
                world_version=final_state.world_version,
                resident_id=actor.resident_id,
                actor_id=actor_id,
                room_id=resident_seed.room_id,
                is_home=presence == "home",
                presence=presence,
                current_location_id=location_id,
                public_mood=self._public_mood(
                    perspective.knowledge_state
                ),
                public_activity_summary=activity,
                public_expression=self._public_expression(
                    perspective.knowledge_state
                ),
                latest_diary=LatestDiaryProjection(
                    available=True,
                    entry_id=(
                        f"diary:{core_run.run_id}:{actor_id}:"
                        f"{last_round.round_index}"
                    ),
                    created_at=updated_at,
                    summary=self._diary_summary(
                        perspective.knowledge_state
                    ),
                ),
                relationship_summaries=self._relationships(
                    actor_id,
                    core_run,
                ),
                capabilities=RoomCapabilitiesProjection(
                    realtime_conversation=False,
                    diary=True,
                    rest=True,
                    private_os=True,
                ),
                private_os_available=perspective.private_os_available,
                private_os_ref=perspective.private_os_ref,
                recent_experience_refs=experience_by_actor.get(
                    actor_id,
                    [],
                )[-5:],
                decision_basis_summary=(
                    "记住了主人的建议，因此调整了今天的安排。"
                    if owner_counsel_influenced
                    else (
                        "过去亲历的记忆影响了今天的选择。"
                        if decision_memory_refs
                        else None
                    )
                ),
                decision_memory_refs=decision_memory_refs,
                updated_at=updated_at,
            )

        scene_location = self._scene_location(final_state.actor_locations)
        world_projection = WorldProjectionDTO(
            run_id=core_run.run_id,
            world_version=final_state.world_version,
            tick_index=last_round.round_index,
            updated_at=updated_at,
            floors=[
                FloorProjection(
                    floor_id="floor-safe",
                    label="安全层",
                    kind="safe",
                    palette_key="safe-home",
                    status="active",
                ),
                FloorProjection(
                    floor_id="floor-neutral",
                    label="公共层",
                    kind="neutral",
                    palette_key="neutral-public",
                    status="quiet",
                ),
                FloorProjection(
                    floor_id="floor-adventure",
                    label="冒险层",
                    kind="adventure",
                    palette_key="adventure-signal",
                    status="active",
                ),
            ],
            rooms=rooms,
            residents=residents,
            public_scenes=[
                PublicSceneProjection(
                    scene_id=(
                        f"scene:{core_run.run_id}:"
                        f"{last_round.round_index}"
                    ),
                    location_id=scene_location,
                    participant_ids=[
                        actor.resident_id for actor in core_run.actors
                    ],
                    public_summary=self._public_scene_summary(core_run),
                    status="resolved",
                )
            ],
            round_status="committed",
            summary=(
                "世界已完成一轮原子更新；居民状态和公开经历"
                "可以安全刷新。"
            ),
        )
        return ProductProjectionSet(
            world=world_projection,
            rooms_by_resident_id=room_details,
        )

    def _presence(
        self,
        actor_id: str,
        location_id: str,
    ) -> PresenceState:
        location = self.world.location(location_id)
        if location.layer == "adventure":
            return "adventure"
        if location_id == self.world.character(actor_id).location_id:
            return "home"
        if location_id in {
            "grand-foyer",
            "mirror-curtain",
            "apartment-bar",
            "apartment-library",
        }:
            return "public"
        return "away"

    def _relationships(
        self,
        actor_id: str,
        core_run: CoreRun,
    ) -> list[RelationshipSummaryProjection]:
        final_state = core_run.final_state
        last_event = core_run.rounds[-1].adjudication.canonical_event
        changed_pairs = {
            (parts[1], parts[2])
            for effect in last_event.effects
            for parts in [effect.path.strip("/").split("/")]
            if len(parts) == 4 and parts[0] == "relationships"
        }
        actor_by_id = {
            actor.actor_id: actor for actor in core_run.actors
        }
        summaries: list[RelationshipSummaryProjection] = []
        for target_id, relationship in sorted(
            final_state.relationships.get(actor_id, {}).items()
        ):
            target = actor_by_id.get(target_id)
            if target is None:
                continue
            summaries.append(
                RelationshipSummaryProjection(
                    resident_id=target.resident_id,
                    display_name=target.display_name,
                    state_label=self._relationship_label(relationship),
                    changed_recently=(
                        (actor_id, target_id) in changed_pairs
                    ),
                )
            )
        return summaries

    @staticmethod
    def _relationship_label(relationship: Relationship) -> str:
        if relationship.tension >= 2:
            return "关系紧张"
        if relationship.trust >= 1:
            return "相互信任"
        if relationship.affinity >= 1:
            return "相处亲近"
        if relationship.trust <= -1:
            return "保持戒心"
        return "关系平稳"

    @staticmethod
    def _public_mood(knowledge_state: str) -> str:
        return {
            "observed": "笃定",
            "misunderstood": "迟疑",
            "unknown": "保留",
        }[knowledge_state]

    @staticmethod
    def _public_expression(knowledge_state: str) -> str:
        return {
            "observed": "今天只是普通相处，但我会记得他们说过的话。",
            "misunderstood": "我听见了一些话，还不确定自己有没有理解对。",
            "unknown": "我没有听清全部交谈，暂时不想替别人下结论。",
        }[knowledge_state]

    @staticmethod
    def _diary_summary(knowledge_state: str) -> str:
        return {
            "observed": (
                "今天我和同处的人有过一次日常交谈。"
                "内容并不惊天动地，但我会记得彼此当时的态度。"
            ),
            "misunderstood": (
                "今天的交谈里有些话我没有完全听懂。"
                "我会保留自己的疑问，不急着把猜测当成事实。"
            ),
            "unknown": (
                "今天我没有听清所有人的交谈。"
                "这也是日常生活的一部分，我只能记住自己真正知道的内容。"
            ),
        }[knowledge_state]

    @staticmethod
    def _public_scene_summary(core_run: CoreRun) -> str:
        first_round = core_run.rounds[0]
        last_round = core_run.rounds[-1]
        proposal_by_id = {
            proposal.proposal_id: proposal
            for proposal in first_round.proposals
        }
        daily_planning = bool(first_round.proposals) and all(
            proposal.intent.kind in {"MOVE", "WAIT"}
            for proposal in first_round.proposals
        )
        daily_social = bool(last_round.proposals) and all(
            proposal.intent.kind in {"UTTERANCE", "WAIT"}
            for proposal in last_round.proposals
        )
        if daily_planning and daily_social:
            return (
                "今天是普通的日常；居民按照自己的安排去了不同空间。"
                "同处一地的人获得了交谈机会：有人主动交谈，"
                "也有人选择保持安静。"
            )
        blocked_take = any(
            receipt.outcome == "blocked"
            and proposal_by_id[receipt.proposal_id].intent.kind == "TAKE"
            for receipt in first_round.adjudication.proof.receipts
        )
        applied_move = any(
            receipt.status == "applied"
            and proposal_by_id[receipt.proposal_id].intent.kind == "MOVE"
            for receipt in first_round.adjudication.proof.receipts
        )
        if blocked_take and applied_move:
            return (
                "用户 OC 自愿进入临时冒险房间；恶魔 OC 试图取得"
                "通行牌时被规则阻止，天使 OC 的警告让关系更加紧张。"
            )
        return (
            f"{len(core_run.actors)} 位居民完成了一次"
            "有规则、有后果的共同事件。"
        )

    @staticmethod
    def _activity_label(proposal: ConcurrentProposal) -> str:
        if proposal.intent.kind == "UTTERANCE":
            return "正在与其他居民交谈"
        if proposal.intent.kind == "WAIT":
            return "正在安静地度过自己的时间"
        if proposal.intent.kind == "MOVE":
            return f"正在前往 {proposal.target_label or '另一处空间'}"
        if proposal.intent.kind == "TAKE":
            return f"正在尝试取得 {proposal.target_label or '一个物件'}"
        return f"正在交付 {proposal.target_label or '一个物件'}"

    @staticmethod
    def _scene_location(actor_locations: dict[str, str]) -> str:
        counts: dict[str, int] = {}
        for location_id in actor_locations.values():
            counts[location_id] = counts.get(location_id, 0) + 1
        return min(
            counts,
            key=lambda location_id: (-counts[location_id], location_id),
        )

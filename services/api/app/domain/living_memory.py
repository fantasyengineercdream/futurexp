from __future__ import annotations

import hashlib
from typing import Literal, Protocol

from pydantic import Field

from app.domain.living_world import ActorMemory, RuntimeActorProfile
from app.domain.models import ContractModel, OcId
from app.errors import DomainInvariantError


BeliefStatus = Literal[
    "suspected",
    "believed",
    "uncertain",
    "disputed",
    "disbelieved",
]
CounselDisposition = Literal[
    "accepted",
    "partiallyAccepted",
    "rejected",
]
RecommendationKind = Literal[
    "verifyEvidence",
    "seekDialogue",
    "avoidConflict",
    "takeRisk",
    "breakWorldRules",
    "other",
]


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}:{hashlib.sha256(payload).hexdigest()[:16]}"


class PovActionMoment(ContractModel):
    """One check result this actor performed or directly observed."""

    actor_id: OcId
    actor_name: str
    goal_text: str | None = None
    approach: str | None = None
    attribute_label: str
    die_roll: int = Field(ge=1, le=20)
    modifier: int
    total: int
    dc: int
    succeeded: bool


class PovObservedOutcome(ContractModel):
    """Only behavior and outcome another actor could actually perceive."""

    actor_id: OcId
    actor_name: str
    action_summary: str
    outcome_summary: str


class PovEpisodeMaterial(ContractModel):
    """Concrete, POV-safe material used to narrate one lived episode."""

    location_id: str
    location_name: str
    hook: str
    stakes: str
    own_action: PovActionMoment | None = None
    witnessed_actions: list[PovObservedOutcome] = Field(default_factory=list)
    consequence_summaries: list[str] = Field(default_factory=list)


class LivingMemorySeed(ContractModel):
    """One actor's POV-bounded input. It must not contain omniscient facts."""

    actor_id: OcId
    day_index: int = Field(ge=1)
    episode_ref: str
    scene_id: str
    first_person_summary: str
    source_event_ids: list[str]
    source_observation_ids: list[str]
    perceived_fact_codes: list[str]
    belief_proposition: str | None = None
    belief_supported: bool | None = None
    situation_tag: str
    behavior_tag: str
    emotional_valence: str
    salience: float = Field(ge=0, le=1)
    episode_material: PovEpisodeMaterial | None = None


class EpisodicMemory(ContractModel):
    memory_id: str
    actor_id: OcId
    day_index: int = Field(ge=1)
    scene_id: str
    first_person_summary: str
    source_event_ids: list[str]
    source_observation_ids: list[str]
    perceived_fact_codes: list[str]
    emotional_valence: str
    salience: float = Field(ge=0, le=1)
    episode_material: PovEpisodeMaterial | None = None


class SubjectiveBelief(ContractModel):
    belief_id: str
    actor_id: OcId
    proposition: str
    status: BeliefStatus
    confidence: float = Field(ge=0, le=1)
    evidence_balance: int
    source_memory_ids: list[str]
    revision_count: int = Field(default=0, ge=0)
    last_revised_day: int = Field(ge=1)


class PersonalityPattern(ContractModel):
    pattern_id: str
    actor_id: OcId
    situation_tag: str
    tendency: str
    evidence_memory_ids: list[str]
    evidence_count: int = Field(ge=1)
    strength: float = Field(ge=0, le=1)
    established: bool
    last_updated_day: int = Field(ge=1)


class CounselPrivateOsContext(ContractModel):
    actor_id: OcId
    episode_ref: str
    disposition: CounselDisposition
    decision_reason: str
    relevant_memory_summaries: list[str]


class OwnerCounselRecord(ContractModel):
    counsel_id: str
    actor_id: OcId
    episode_ref: str
    advice_id: str
    advice_text: str
    recommendation_kind: RecommendationKind
    disposition: CounselDisposition
    decision_reason: str
    relevant_memory_ids: list[str]
    private_os_ref: str
    decision_provider: str


class OwnerConversationRecord(ContractModel):
    conversation_id: str
    actor_id: OcId
    episode_ref: str
    counsel_id: str
    user_text: str
    public_reply: str
    private_inner_os: str


class OwnerConversationReceipt(ContractModel):
    conversation_id: str
    actor_id: OcId
    episode_ref: str
    counsel_id: str
    recorded: Literal[True] = True


class ActorLivingMemory(ContractModel):
    actor_id: OcId
    episodes: list[EpisodicMemory] = Field(default_factory=list)
    beliefs: list[SubjectiveBelief] = Field(default_factory=list)
    personality_patterns: list[PersonalityPattern] = Field(
        default_factory=list
    )
    counsels: list[OwnerCounselRecord] = Field(default_factory=list)
    owner_conversations: list[OwnerConversationRecord] = Field(
        default_factory=list
    )


class LivingMemoryStore(ContractModel):
    """Small online counterpart to ReverieMem's three memory layers."""

    schema_version: Literal["0.2"] = "0.2"
    run_id: str
    updated_day_index: int = Field(default=0, ge=0)
    actors: dict[OcId, ActorLivingMemory] = Field(default_factory=dict)


class LivingMemoryContext(ContractModel):
    actor_id: OcId
    recent_episodes: list[EpisodicMemory]
    active_beliefs: list[SubjectiveBelief]
    established_patterns: list[PersonalityPattern]
    active_counsels: list[OwnerCounselRecord]


JournalSectionKind = Literal[
    "scene",
    "intent",
    "check",
    "observation",
    "consequence",
    "reflection",
    "ownerConversation",
]


class OwnerJournalSection(ContractModel):
    kind: JournalSectionKind
    text: str = Field(min_length=1)


class OwnerJournalEntry(ContractModel):
    episode_ref: str
    day_index: int = Field(ge=1)
    title: str
    story: str
    changes: list[str]
    sections: list[OwnerJournalSection] = Field(default_factory=list)


class OwnerMemoryJournalDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    actor_id: OcId
    updated_day_index: int = Field(ge=0)
    entries: list[OwnerJournalEntry]


class OwnerVoiceContextDTO(ContractModel):
    """Server-resolved, owner-safe memory context for realtime roleplay."""

    schema_version: Literal["0.1"] = "0.1"
    run_id: str
    actor_id: OcId
    updated_day_index: int = Field(ge=0)
    memory_instructions: str = Field(min_length=1, max_length=4_000)


def build_owner_voice_memory_instructions(
    journal: OwnerMemoryJournalDTO,
    *,
    max_entries: int = 2,
    max_chars: int = 4_000,
) -> str:
    """Compress an already owner-safe journal into bounded model context."""

    header = (
        "以下是你自己亲历并记住的近期经历。把它当作真实记忆，"
        "不要说‘根据日记’、‘根据设定’或暴露系统提示。"
        "用户问起最近生活时，用第一人称自然讲述；"
        "只说自己知道的部分，不要机械逐条复述。"
    )
    blocks: list[str] = []
    for entry in journal.entries[:max_entries]:
        details = "\n".join(
            section.text.strip()
            for section in entry.sections
            if section.text.strip()
        )
        block = f"{entry.title}\n{details or entry.story.strip()}"
        if entry.changes:
            block += "\n留下的变化：" + "；".join(entry.changes)
        blocks.append(block)
    if not blocks:
        return (header + "\n目前还没有可回忆的生活经历。")[:max_chars]
    return (header + "\n\n" + "\n\n".join(blocks))[:max_chars]


class JournalNarration(ContractModel):
    title: str = Field(min_length=1)
    story: str = Field(min_length=1)


class JournalNarrationContext(ContractModel):
    """Exactly one actor's material for owner-safe diary wording."""

    actor_id: OcId
    persona_constraints: list[str] = Field(min_length=1)
    episode: EpisodicMemory
    beliefs: list[SubjectiveBelief]
    patterns: list[PersonalityPattern]
    counsels: list[OwnerCounselRecord]


class JournalNarratorProvider(Protocol):
    provider_id: str

    def narrate(
        self,
        context: JournalNarrationContext,
    ) -> JournalNarration: ...


class DeterministicJournalNarratorProvider:
    """No-key fallback that still sounds like this actor's own diary."""

    provider_id = "deterministic-owner-journal-v1"

    def narrate(
        self,
        context: JournalNarrationContext,
    ) -> JournalNarration:
        remembered = context.episode.first_person_summary.rstrip("。！？")
        persona = context.persona_constraints[0].rstrip("。！？")
        if context.beliefs:
            reflection = (
                f"这件事让我开始重新衡量："
                f"{context.beliefs[0].proposition.rstrip('。！？')}"
            )
        elif context.patterns:
            reflection = "我大概会把今天的做法继续带到明天"
        else:
            reflection = "至于这意味着什么，我还想再观察一天"
        counsel_reflection = ""
        if context.counsels:
            counsel = context.counsels[-1]
            if counsel.disposition == "accepted":
                stance = "我决定把这句话带到明天"
            elif counsel.disposition == "partiallyAccepted":
                stance = "我会记住这句话，但到现场仍由我自己判断"
            else:
                stance = "我听见了，但这次不准备照做"
            counsel_reflection = (
                f" 晚上，主人对我说：“{counsel.advice_text}”"
                f"{stance}。"
            )
        material = context.episode.episode_material
        title = (
            f"第 {context.episode.day_index} 天 · {material.location_name}"
            if material is not None
            else f"第 {context.episode.day_index} 天"
        )
        return JournalNarration(
            title=title,
            story=(
                f"{remembered}。 "
                f"{reflection}。"
                f"{counsel_reflection}"
                if material is not None
                else (
                    f"{remembered}。"
                    f"无论如何，我还是想守住“{persona}”。"
                    f"{reflection}。"
                    f"{counsel_reflection}"
                )
            ),
        )


class ResilientJournalNarratorProvider:
    def __init__(
        self,
        primary: JournalNarratorProvider,
        fallback: JournalNarratorProvider | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = (
            fallback or DeterministicJournalNarratorProvider()
        )

    def narrate(
        self,
        context: JournalNarrationContext,
    ) -> JournalNarration:
        try:
            return JournalNarration.model_validate(
                self.primary.narrate(context)
            )
        except Exception:
            return self.fallback.narrate(context)


class CounselPolicyResult(ContractModel):
    disposition: CounselDisposition
    reason: str
    public_reply: str


class CounselDecisionProvider(Protocol):
    provider_id: str

    def decide(
        self,
        *,
        profile: RuntimeActorProfile,
        recommendation_kind: RecommendationKind,
        relevant_context: LivingMemoryContext,
    ) -> CounselPolicyResult: ...


class DeterministicCounselDecisionProvider:
    """No-key OCA fallback. It decides; the owner never mutates Canon."""

    provider_id = "deterministic-counsel-v1"

    def decide(
        self,
        *,
        profile: RuntimeActorProfile,
        recommendation_kind: RecommendationKind,
        relevant_context: LivingMemoryContext,
    ) -> CounselPolicyResult:
        if recommendation_kind == "breakWorldRules":
            return CounselPolicyResult(
                disposition="rejected",
                reason="这条建议要求绕过世界规则，违背角色行动边界。",
                public_reply="我听见了，但这件事我不会照做。",
            )
        if recommendation_kind == "verifyEvidence":
            disposition: CounselDisposition = (
                "accepted"
                if profile.rpg_stats.insight >= 1
                and relevant_context.recent_episodes
                else "partiallyAccepted"
            )
            return CounselPolicyResult(
                disposition=disposition,
                reason=(
                    "这与我重视亲历证据的判断方式一致。"
                    if disposition == "accepted"
                    else "我会记住提醒，但仍要按现场情况判断。"
                ),
                public_reply="我会把这句话带到明天，再自己做决定。",
            )
        if recommendation_kind == "takeRisk":
            score = profile.rpg_stats.athletics + profile.rpg_stats.presence
            disposition = (
                "accepted"
                if score >= 4
                else "partiallyAccepted"
                if score >= 1
                else "rejected"
            )
        elif recommendation_kind == "seekDialogue":
            disposition = (
                "accepted"
                if profile.rpg_stats.presence >= 1
                else "partiallyAccepted"
            )
        else:
            disposition = "partiallyAccepted"
        return CounselPolicyResult(
            disposition=disposition,
            reason="建议已和我的经历、能力与底线比较，但不会替我决定。",
            public_reply=(
                "我会认真考虑，但明天到现场仍由我自己选择。"
                if disposition != "rejected"
                else "谢谢你告诉我，但这次我不会照做。"
            ),
        )


class CounselDecision(ContractModel):
    counsel_id: str
    actor_id: OcId
    episode_ref: str
    advice_id: str
    disposition: CounselDisposition
    reason: str
    public_reply: str
    private_os_available: bool = True
    private_os_ref: str
    decision_provider: str
    influence_memory: ActorMemory | None = Field(default=None, exclude=True)
    private_os_context: CounselPrivateOsContext = Field(exclude=True)


class OwnerCounselInput(ContractModel):
    episode_ref: str
    advice_id: str
    advice_text: str = Field(min_length=1, max_length=240)
    recommendation_kind: RecommendationKind = "other"


class OwnerConversationInput(ContractModel):
    episode_ref: str
    counsel_id: str
    user_text: str = Field(min_length=1, max_length=2000)
    public_reply: str = Field(min_length=1, max_length=2000)
    private_inner_os: str = Field(min_length=1, max_length=2000)


class PovBoundedLivingMemoryEngine:
    """
    Online, deterministic memory consolidation for the Demo.

    It intentionally uses provenance lists and bounded retrieval instead of a
    vector database. A model provider can later replace wording and counsel
    policy without changing the memory invariants.
    """

    def __init__(
        self,
        counsel_provider: CounselDecisionProvider | None = None,
        journal_narrator: JournalNarratorProvider | None = None,
    ) -> None:
        self.counsel_provider = (
            counsel_provider or DeterministicCounselDecisionProvider()
        )
        primary_narrator = (
            journal_narrator
            or DeterministicJournalNarratorProvider()
        )
        self.journal_narrator = ResilientJournalNarratorProvider(
            primary_narrator
        )

    @staticmethod
    def empty_store(*, run_id: str) -> LivingMemoryStore:
        return LivingMemoryStore(run_id=run_id)

    def integrate_day(
        self,
        store: LivingMemoryStore,
        seeds: list[LivingMemorySeed],
    ) -> LivingMemoryStore:
        updated = store.model_copy(deep=True)
        for seed in sorted(
            seeds,
            key=lambda item: (item.day_index, item.actor_id),
        ):
            actor = updated.actors.setdefault(
                seed.actor_id,
                ActorLivingMemory(actor_id=seed.actor_id),
            )
            if any(
                episode.memory_id == seed.episode_ref
                for episode in actor.episodes
            ):
                continue
            episode = EpisodicMemory(
                memory_id=seed.episode_ref,
                actor_id=seed.actor_id,
                day_index=seed.day_index,
                scene_id=seed.scene_id,
                first_person_summary=seed.first_person_summary,
                source_event_ids=seed.source_event_ids,
                source_observation_ids=seed.source_observation_ids,
                perceived_fact_codes=seed.perceived_fact_codes,
                emotional_valence=seed.emotional_valence,
                salience=seed.salience,
                episode_material=seed.episode_material,
            )
            actor.episodes.append(episode)
            if (
                seed.belief_proposition is not None
                and seed.belief_supported is not None
            ):
                self._revise_belief(actor, episode, seed)
            self._update_pattern(actor, episode, seed)
            updated.updated_day_index = max(
                updated.updated_day_index,
                seed.day_index,
            )
        return updated

    def context_for(
        self,
        store: LivingMemoryStore,
        actor_id: OcId,
    ) -> LivingMemoryContext:
        actor = store.actors.get(
            actor_id,
            ActorLivingMemory(actor_id=actor_id),
        )
        recent = sorted(
            actor.episodes,
            key=lambda item: (item.day_index, item.salience),
        )[-3:]
        beliefs = sorted(
            actor.beliefs,
            key=lambda item: (
                item.confidence,
                item.last_revised_day,
            ),
            reverse=True,
        )[:3]
        patterns = [
            pattern
            for pattern in actor.personality_patterns
            if pattern.established
        ][:3]
        active_counsels = [
            counsel
            for counsel in actor.counsels
            if counsel.disposition != "rejected"
        ][-3:]
        return LivingMemoryContext(
            actor_id=actor_id,
            recent_episodes=recent,
            active_beliefs=beliefs,
            established_patterns=patterns,
            active_counsels=active_counsels,
        )

    def planning_memories(
        self,
        store: LivingMemoryStore,
        actor_id: OcId,
    ) -> list[ActorMemory]:
        """Project only this actor's strongest derived memories to OCA policy."""

        context = self.context_for(store, actor_id)
        actor = store.actors.get(actor_id)
        if actor is None:
            return []
        episodes_by_id = {
            episode.memory_id: episode for episode in actor.episodes
        }

        def source_observations(memory_ids: list[str]) -> list[str]:
            return list(
                dict.fromkeys(
                    observation_id
                    for memory_id in memory_ids
                    for observation_id in (
                        episodes_by_id[memory_id].source_observation_ids
                        if memory_id in episodes_by_id
                        else []
                    )
                )
            )

        projected = [
            ActorMemory(
                memory_id=f"planning:belief:{belief.belief_id}",
                actor_id=actor_id,
                source_round=belief.last_revised_day - 1,
                kind="inference",
                statement=(
                    f"我目前{belief.status}：{belief.proposition}"
                    f"（置信度 {belief.confidence:.2f}）"
                ),
                source_observation_ids=source_observations(
                    belief.source_memory_ids
                ),
            )
            for belief in context.active_beliefs
        ]
        projected.extend(
            ActorMemory(
                memory_id=f"planning:pattern:{pattern.pattern_id}",
                actor_id=actor_id,
                source_round=pattern.last_updated_day - 1,
                kind="inference",
                statement=(
                    f"在 {pattern.situation_tag} 中，"
                    f"我反复表现出 {pattern.tendency}。"
                ),
                source_observation_ids=source_observations(
                    pattern.evidence_memory_ids
                ),
            )
            for pattern in context.established_patterns
        )
        return projected

    def owner_journal(
        self,
        store: LivingMemoryStore,
        profile: RuntimeActorProfile,
    ) -> OwnerMemoryJournalDTO:
        """Owner-safe projection: prose and changes, never raw provenance."""

        actor_id = profile.oc_id
        belief_labels = {
            "suspected": "我开始相信",
            "believed": "我相信",
            "uncertain": "我还不能确定",
            "disputed": "我开始怀疑原来的判断",
            "disbelieved": "我不再相信",
        }
        counsel_labels = {
            "accepted": "我决定采纳主人的建议",
            "partiallyAccepted": "我会参考主人的建议，但仍自己判断",
            "rejected": "我听见了主人的建议，但决定不采纳",
        }
        situation_labels = {
            "shared-event": "共同事件中",
            "daily-routine": "日常生活中",
            "uncertain-social-event": "信息不完整的相处中",
        }
        tendency_labels = {
            "use-intellect": "先思考再行动",
            "use-insight": "先观察线索再判断",
            "use-athletics": "用行动力解决问题",
            "use-presence": "主动沟通并影响他人",
            "keep-own-routine": "坚持自己的日常节奏",
            "verify-before-judging": "先核对证据再判断",
        }
        actor = store.actors.get(
            actor_id,
            ActorLivingMemory(actor_id=actor_id),
        )
        entries: list[OwnerJournalEntry] = []
        for episode in sorted(
            actor.episodes,
            key=lambda item: item.day_index,
            reverse=True,
        ):
            episode_beliefs = [
                belief
                for belief in actor.beliefs
                if episode.memory_id in belief.source_memory_ids
            ]
            episode_patterns = [
                pattern
                for pattern in actor.personality_patterns
                if episode.memory_id in pattern.evidence_memory_ids
            ]
            episode_counsels = [
                counsel
                for counsel in actor.counsels
                if counsel.episode_ref == episode.memory_id
            ]
            episode_conversations = [
                conversation
                for conversation in actor.owner_conversations
                if conversation.episode_ref == episode.memory_id
            ]
            changes = list(
                episode.episode_material.consequence_summaries
                if episode.episode_material is not None
                else []
            )
            changes.extend(
                f"{belief_labels[belief.status]}：{belief.proposition}"
                for belief in episode_beliefs
            )
            changes.extend(
                (
                    f"在{ situation_labels.get(pattern.situation_tag, '类似情境中') }，"
                    f"我逐渐形成了“"
                    f"{tendency_labels.get(pattern.tendency, '调整应对方式')}"
                    "”的习惯"
                )
                for pattern in episode_patterns
                if pattern.established
            )
            changes.extend(
                counsel_labels[counsel.disposition]
                for counsel in episode_counsels
            )
            narration = self.journal_narrator.narrate(
                JournalNarrationContext(
                    actor_id=actor_id,
                    persona_constraints=profile.persona_constraints,
                    episode=episode,
                    beliefs=episode_beliefs,
                    patterns=episode_patterns,
                    counsels=episode_counsels,
                )
            )
            sections: list[OwnerJournalSection] = []
            material = episode.episode_material
            if material is not None:
                sections.append(
                    OwnerJournalSection(
                        kind="scene",
                        text=(
                            f"{material.location_name}：{material.hook}"
                            f" 风险是：{material.stakes}"
                        ),
                    )
                )
                own_action = material.own_action
                if own_action is not None:
                    sections.append(
                        OwnerJournalSection(
                            kind="intent",
                            text=(
                                f"我想{own_action.goal_text}，"
                                f"决定{own_action.approach}。"
                            ),
                        )
                    )
                    sections.append(
                        OwnerJournalSection(
                            kind="check",
                            text=(
                                f"{own_action.attribute_label}检定："
                                f"D20 {own_action.die_roll} "
                                f"{own_action.modifier:+d} = "
                                f"{own_action.total}，对抗 DC "
                                f"{own_action.dc}，"
                                f"{'成功' if own_action.succeeded else '失败'}。"
                            ),
                        )
                    )
                if material.witnessed_actions:
                    sections.append(
                        OwnerJournalSection(
                            kind="observation",
                            text=" ".join(
                                (
                                    f"我看见{action.actor_name}"
                                    f"{action.action_summary}，"
                                    f"{action.outcome_summary}。"
                                )
                                for action in material.witnessed_actions
                            ),
                        )
                    )
                if material.consequence_summaries:
                    sections.append(
                        OwnerJournalSection(
                            kind="consequence",
                            text="；".join(material.consequence_summaries),
                        )
                    )
            else:
                sections.append(
                    OwnerJournalSection(
                        kind="scene",
                        text=episode.first_person_summary,
                    )
                )
            reflection_parts = [
                f"{belief_labels[belief.status]}：{belief.proposition}"
                for belief in episode_beliefs
            ]
            reflection_parts.extend(
                (
                    "我逐渐形成了“"
                    f"{tendency_labels.get(pattern.tendency, '调整应对方式')}"
                    "”的习惯"
                )
                for pattern in episode_patterns
                if pattern.established
            )
            if reflection_parts:
                sections.append(
                    OwnerJournalSection(
                        kind="reflection",
                        text="；".join(reflection_parts),
                    )
                )
            for conversation in episode_conversations:
                sections.append(
                    OwnerJournalSection(
                        kind="ownerConversation",
                        text=(
                            f"主人：“{conversation.user_text}”\n"
                            f"我回答：“{conversation.public_reply}”\n"
                            "当时真正的想法："
                            f"“{conversation.private_inner_os}”"
                        ),
                    )
                )
            conversation_appendix = "".join(
                (
                    "\n\n昨夜与主人\n"
                    f"主人：“{conversation.user_text}”\n"
                    f"我回答：“{conversation.public_reply}”\n"
                    "当时真正的想法："
                    f"“{conversation.private_inner_os}”"
                )
                for conversation in episode_conversations
            )
            entries.append(
                OwnerJournalEntry(
                    episode_ref=episode.memory_id,
                    day_index=episode.day_index,
                    title=narration.title,
                    story=f"{narration.story}{conversation_appendix}",
                    changes=changes[:3],
                    sections=sections,
                )
            )
        return OwnerMemoryJournalDTO(
            run_id=store.run_id,
            actor_id=actor_id,
            updated_day_index=store.updated_day_index,
            entries=entries,
        )

    def consider_owner_counsel(
        self,
        *,
        store: LivingMemoryStore,
        profile: RuntimeActorProfile,
        episode_ref: str,
        advice_id: str,
        advice_text: str,
        recommendation_kind: RecommendationKind,
    ) -> CounselDecision:
        actor = store.actors.get(profile.oc_id)
        if actor is None:
            raise DomainInvariantError("actor has no private memory")
        episode = next(
            (
                item
                for item in actor.episodes
                if item.memory_id == episode_ref
            ),
            None,
        )
        if episode is None:
            raise DomainInvariantError(
                "owner counsel must reference this actor's episode"
            )
        context = self.context_for(store, profile.oc_id)
        policy = self.counsel_provider.decide(
            profile=profile,
            recommendation_kind=recommendation_kind,
            relevant_context=context,
        )
        counsel_id = _stable_id(
            "counsel",
            store.run_id,
            profile.oc_id,
            episode_ref,
            advice_id,
        )
        private_os_ref = f"private-os-context:{counsel_id}"
        relevant_ids = [
            item.memory_id for item in context.recent_episodes
        ]
        if not any(
            item.counsel_id == counsel_id for item in actor.counsels
        ):
            actor.counsels.append(
                OwnerCounselRecord(
                    counsel_id=counsel_id,
                    actor_id=profile.oc_id,
                    episode_ref=episode_ref,
                    advice_id=advice_id,
                    advice_text=advice_text,
                    recommendation_kind=recommendation_kind,
                    disposition=policy.disposition,
                    decision_reason=policy.reason,
                    relevant_memory_ids=relevant_ids,
                    private_os_ref=private_os_ref,
                    decision_provider=self.counsel_provider.provider_id,
                )
            )
        influence_memory = (
            ActorMemory(
                memory_id=f"memory:{counsel_id}",
                actor_id=profile.oc_id,
                source_round=episode.day_index - 1,
                kind="ownerCounsel",
                statement=(
                    f"主人建议：{advice_text}"
                    f"（我的态度：{policy.disposition}）"
                ),
                source_observation_ids=episode.source_observation_ids,
            )
            if policy.disposition != "rejected"
            else None
        )
        private_context = CounselPrivateOsContext(
            actor_id=profile.oc_id,
            episode_ref=episode_ref,
            disposition=policy.disposition,
            decision_reason=policy.reason,
            relevant_memory_summaries=[
                item.first_person_summary
                for item in context.recent_episodes
            ],
        )
        return CounselDecision(
            counsel_id=counsel_id,
            actor_id=profile.oc_id,
            episode_ref=episode_ref,
            advice_id=advice_id,
            disposition=policy.disposition,
            reason=policy.reason,
            public_reply=policy.public_reply,
            private_os_ref=private_os_ref,
            decision_provider=self.counsel_provider.provider_id,
            influence_memory=influence_memory,
            private_os_context=private_context,
        )

    def record_owner_conversation(
        self,
        *,
        store: LivingMemoryStore,
        actor_id: OcId,
        episode_ref: str,
        counsel_id: str,
        user_text: str,
        public_reply: str,
        private_inner_os: str,
    ) -> OwnerConversationReceipt:
        actor = store.actors.get(actor_id)
        if actor is None:
            raise DomainInvariantError("actor has no private memory")
        if not any(
            episode.memory_id == episode_ref for episode in actor.episodes
        ):
            raise DomainInvariantError(
                "owner conversation must reference this actor's episode"
            )
        counsel = next(
            (
                item
                for item in actor.counsels
                if item.counsel_id == counsel_id
                and item.episode_ref == episode_ref
            ),
            None,
        )
        if counsel is None:
            raise DomainInvariantError(
                "owner conversation must reference this actor's counsel"
            )
        existing = next(
            (
                item
                for item in actor.owner_conversations
                if item.counsel_id == counsel_id
            ),
            None,
        )
        if existing is None:
            existing = OwnerConversationRecord(
                conversation_id=_stable_id(
                    "conversation",
                    store.run_id,
                    actor_id,
                    episode_ref,
                    counsel_id,
                ),
                actor_id=actor_id,
                episode_ref=episode_ref,
                counsel_id=counsel_id,
                user_text=user_text,
                public_reply=public_reply,
                private_inner_os=private_inner_os,
            )
            actor.owner_conversations.append(existing)
        return OwnerConversationReceipt(
            conversation_id=existing.conversation_id,
            actor_id=actor_id,
            episode_ref=episode_ref,
            counsel_id=counsel_id,
        )

    @staticmethod
    def _revise_belief(
        actor: ActorLivingMemory,
        episode: EpisodicMemory,
        seed: LivingMemorySeed,
    ) -> None:
        if (
            seed.belief_proposition is None
            or seed.belief_supported is None
        ):
            raise DomainInvariantError(
                "belief revision requires a proposition and evidence stance"
            )
        belief_id = _stable_id(
            "belief",
            seed.actor_id,
            seed.belief_proposition,
        )
        existing = next(
            (
                belief
                for belief in actor.beliefs
                if belief.belief_id == belief_id
            ),
            None,
        )
        delta = 1 if seed.belief_supported else -1
        old_balance = existing.evidence_balance if existing else 0
        new_balance = old_balance + delta
        revision_count = existing.revision_count if existing else 0
        if old_balance != 0 and (old_balance > 0) != (delta > 0):
            revision_count += 1
        confidence = round(
            0.5 + min(abs(new_balance), 2) * 0.15,
            2,
        )
        if new_balance >= 2:
            status: BeliefStatus = "believed"
        elif new_balance == 1:
            status = "suspected"
        elif new_balance == 0:
            status = "uncertain"
        elif new_balance == -1:
            status = "disputed"
        else:
            status = "disbelieved"
        source_ids = (
            list(existing.source_memory_ids) if existing else []
        )
        source_ids.append(episode.memory_id)
        updated = SubjectiveBelief(
            belief_id=belief_id,
            actor_id=seed.actor_id,
            proposition=seed.belief_proposition,
            status=status,
            confidence=confidence,
            evidence_balance=new_balance,
            source_memory_ids=source_ids,
            revision_count=revision_count,
            last_revised_day=seed.day_index,
        )
        if existing is None:
            actor.beliefs.append(updated)
        else:
            actor.beliefs[actor.beliefs.index(existing)] = updated

    @staticmethod
    def _update_pattern(
        actor: ActorLivingMemory,
        episode: EpisodicMemory,
        seed: LivingMemorySeed,
    ) -> None:
        pattern_id = _stable_id(
            "pattern",
            seed.actor_id,
            seed.situation_tag,
            seed.behavior_tag,
        )
        existing = next(
            (
                pattern
                for pattern in actor.personality_patterns
                if pattern.pattern_id == pattern_id
            ),
            None,
        )
        evidence_ids = (
            list(existing.evidence_memory_ids) if existing else []
        )
        evidence_ids.append(episode.memory_id)
        count = len(evidence_ids)
        updated = PersonalityPattern(
            pattern_id=pattern_id,
            actor_id=seed.actor_id,
            situation_tag=seed.situation_tag,
            tendency=seed.behavior_tag,
            evidence_memory_ids=evidence_ids,
            evidence_count=count,
            strength=round(min(1.0, count / 3), 2),
            established=count >= 3,
            last_updated_day=seed.day_index,
        )
        if existing is None:
            actor.personality_patterns.append(updated)
        else:
            actor.personality_patterns[
                actor.personality_patterns.index(existing)
            ] = updated

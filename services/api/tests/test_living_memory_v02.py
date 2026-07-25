from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.domain.living_memory import (
    JournalNarration,
    JournalNarrationContext,
    LivingMemorySeed,
    PovBoundedLivingMemoryEngine,
)
from app.domain.day_cycle import LivingWorldDayCore
from app.domain.living_world import load_preset_runtime_bundle
from app.main import create_app
from app.storage import SQLiteStorage
from app.errors import DomainInvariantError


def _seed(
    *,
    actor_id: str = "oc-angel",
    day_index: int = 1,
    supported: bool = True,
    behavior_tag: str = "verify-before-judging",
    situation_tag: str = "uncertain-social-event",
) -> LivingMemorySeed:
    return LivingMemorySeed(
        actor_id=actor_id,
        day_index=day_index,
        episode_ref=f"memory:day-{day_index}:{actor_id}",
        scene_id=f"scene:day-{day_index}",
        first_person_summary="我只记下自己亲眼见到的行动结果。",
        source_event_ids=[f"canonical:day-{day_index}"],
        source_observation_ids=[f"observation:day-{day_index}:{actor_id}"],
        perceived_fact_codes=["rpg.check.succeeded"],
        belief_proposition="先核对证据再判断别人更可靠",
        belief_supported=supported,
        situation_tag=situation_tag,
        behavior_tag=behavior_tag,
        emotional_valence="guarded",
        salience=0.8,
    )


def test_episode_belief_and_pattern_keep_actor_pov_and_provenance() -> None:
    engine = PovBoundedLivingMemoryEngine()

    store = engine.integrate_day(
        engine.empty_store(run_id="memory-demo"),
        [_seed()],
    )
    angel = store.actors["oc-angel"]

    assert angel.episodes[0].first_person_summary.startswith("我只记下")
    assert angel.episodes[0].source_event_ids == ["canonical:day-1"]
    assert angel.episodes[0].source_observation_ids == [
        "observation:day-1:oc-angel"
    ]
    assert angel.beliefs[0].source_memory_ids == [
        "memory:day-1:oc-angel"
    ]
    assert angel.beliefs[0].status == "suspected"
    assert angel.personality_patterns[0].evidence_count == 1
    assert angel.personality_patterns[0].established is False
    assert "oc-devil" not in store.actors


def test_counterevidence_revises_belief_and_patterns_change_slowly() -> None:
    engine = PovBoundedLivingMemoryEngine()
    store = engine.empty_store(run_id="memory-demo")

    store = engine.integrate_day(store, [_seed(day_index=1)])
    store = engine.integrate_day(store, [_seed(day_index=2)])
    store = engine.integrate_day(
        store,
        [_seed(day_index=3, supported=False)],
    )
    angel = store.actors["oc-angel"]
    belief = angel.beliefs[0]
    pattern = angel.personality_patterns[0]

    assert belief.evidence_balance == 1
    assert belief.revision_count == 1
    assert belief.source_memory_ids == [
        "memory:day-1:oc-angel",
        "memory:day-2:oc-angel",
        "memory:day-3:oc-angel",
    ]
    assert pattern.evidence_count == 3
    assert pattern.established is True
    assert pattern.strength == 1.0


def test_belief_and_established_pattern_become_bounded_planning_context() -> None:
    engine = PovBoundedLivingMemoryEngine()
    bundle = load_preset_runtime_bundle()
    store = engine.empty_store(run_id="memory-demo")
    for day_index in (1, 2, 3):
        store = engine.integrate_day(
            store,
            [
                _seed(
                    day_index=day_index,
                    behavior_tag="use-insight",
                    situation_tag="shared-event",
                )
            ],
        )

    context = engine.planning_memories(store, "oc-angel")

    assert {memory.kind for memory in context} == {"inference"}
    assert any(
        memory.memory_id.startswith("planning:belief:")
        and "先核对证据" in memory.statement
        for memory in context
    )
    assert any(
        memory.memory_id.startswith("planning:pattern:")
        and "use-insight" in memory.statement
        for memory in context
    )
    assert all(
        memory.actor_id == "oc-angel"
        and memory.source_observation_ids
        for memory in context
    )
    journal = engine.owner_journal(
        store,
        bundle.actor_profile("oc-angel"),
    )
    journal_text = str(journal.model_dump(mode="json", by_alias=True))
    assert "shared-event" not in journal_text
    assert "use-insight" not in journal_text
    assert "共同事件" in journal_text
    assert "先观察线索再判断" in journal_text


class _RecordingJournalNarrator:
    provider_id = "recording-journal-test"

    def __init__(self) -> None:
        self.contexts: list[JournalNarrationContext] = []

    def narrate(
        self,
        context: JournalNarrationContext,
    ) -> JournalNarration:
        self.contexts.append(context)
        return JournalNarration(
            title=f"{context.actor_id} 的第 {context.episode.day_index} 天",
            story=(
                f"我是 {context.actor_id}。"
                f"我记得：{context.episode.first_person_summary}"
            ),
        )


def test_owner_journal_narrator_receives_only_current_actor_pov() -> None:
    bundle = load_preset_runtime_bundle()
    narrator = _RecordingJournalNarrator()
    engine = PovBoundedLivingMemoryEngine(journal_narrator=narrator)
    store = engine.integrate_day(
        engine.empty_store(run_id="memory-demo"),
        [
            _seed(actor_id="oc-angel"),
            _seed(actor_id="oc-devil"),
        ],
    )

    journal = engine.owner_journal(
        store,
        bundle.actor_profile("oc-angel"),
    )

    assert journal.actor_id == "oc-angel"
    assert journal.entries[0].story.startswith("我是 oc-angel")
    assert [context.actor_id for context in narrator.contexts] == [
        "oc-angel"
    ]
    assert all(
        context.episode.actor_id == "oc-angel"
        and all(
            belief.actor_id == "oc-angel"
            for belief in context.beliefs
        )
        and all(
            pattern.actor_id == "oc-angel"
            for pattern in context.patterns
        )
        and all(
            counsel.actor_id == "oc-angel"
            for counsel in context.counsels
        )
        for context in narrator.contexts
    )


class _FailingJournalNarrator:
    provider_id = "failing-journal-test"

    def narrate(
        self,
        _context: JournalNarrationContext,
    ) -> JournalNarration:
        raise RuntimeError("model unavailable")


def test_owner_journal_falls_back_to_character_specific_prose() -> None:
    bundle = load_preset_runtime_bundle()
    engine = PovBoundedLivingMemoryEngine(
        journal_narrator=_FailingJournalNarrator()
    )
    store = engine.integrate_day(
        engine.empty_store(run_id="memory-demo"),
        [_seed(actor_id="oc-angel")],
    )

    journal = engine.owner_journal(
        store,
        bundle.actor_profile("oc-angel"),
    )

    story = journal.entries[0].story
    assert "我只记下自己亲眼见到的行动结果" in story
    assert bundle.actor_profile("oc-angel").persona_constraints[0] in story
    assert "model unavailable" not in story


def test_api_uses_injected_journal_narrator(tmp_path: Path) -> None:
    narrator = _RecordingJournalNarrator()
    api = TestClient(
        create_app(
            SQLiteStorage(tmp_path / "narrated.sqlite3"),
            journal_narrator=narrator,
        )
    )
    day_one = api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "narrated-journal"},
    ).json()

    journal = api.get(
        (
            f"/api/living-world/day-loop-runs/{day_one['runId']}"
            "/owner/actors/oc-angel/journal"
        )
    )

    assert journal.status_code == 200
    assert journal.json()["entries"][0]["story"].startswith(
        "我是 oc-angel"
    )
    assert [context.actor_id for context in narrator.contexts] == [
        "oc-angel"
    ]


def test_day_loop_owner_journal_tells_the_concrete_pov_episode(
    tmp_path: Path,
) -> None:
    api = TestClient(
        create_app(SQLiteStorage(tmp_path / "concrete-journal.sqlite3"))
    )
    day = api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "concrete-journal"},
    ).json()
    actor_id = "oc-angel"
    journal = api.get(
        (
            f"/api/living-world/day-loop-runs/{day['runId']}"
            f"/owner/actors/{actor_id}/journal"
        )
    ).json()
    story = journal["entries"][0]["story"]
    sections = journal["entries"][0]["sections"]
    bundle = load_preset_runtime_bundle()
    intent = next(
        item for item in day["event"]["intents"]
        if item["actorId"] == actor_id
    )
    check = next(
        item for item in day["event"]["checks"]
        if item["actorId"] == actor_id
    )
    location_name = bundle.world.location(day["event"]["locationId"]).name
    other_names = {
        item["displayName"]
        for item in day["actors"]
        if item["actorId"] != actor_id
    }

    assert location_name in story
    assert day["event"]["hook"] in story
    assert intent["approach"] in story
    assert f"D20 掷出 {check['dieRoll']}" in story
    assert f"DC {check['dc']}" in story
    assert any(name in story for name in other_names)
    assert any(word in story for word in ("信任", "紧张"))
    assert "goal-" not in story
    assert "shared-event" not in story
    assert "钥匙" not in story
    assert "门锁" not in story
    assert "。，" not in story


    assert [section["kind"] for section in sections[:3]] == [
        "scene",
        "intent",
        "check",
    ]
    section_by_kind = {
        section["kind"]: section["text"] for section in sections
    }
    assert day["event"]["hook"] in section_by_kind["scene"]
    assert intent["approach"] in section_by_kind["intent"]
    assert str(check["dieRoll"]) in section_by_kind["check"]
    assert str(check["modifier"]) in section_by_kind["check"]
    assert str(check["total"]) in section_by_kind["check"]
    assert f"DC {check['dc']}" in section_by_kind["check"]
    assert section_by_kind["check"].endswith(
        "成功。" if check["succeeded"] else "失败。"
    )


def test_owner_journal_sections_make_oo_and_cc_pov_distinct_without_leaks(
    tmp_path: Path,
) -> None:
    api = TestClient(
        create_app(SQLiteStorage(tmp_path / "sectioned-journal.sqlite3"))
    )
    day = api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "sectioned-owner-pov"},
    ).json()
    journals = {
        actor_id: api.get(
            (
                f"/api/living-world/day-loop-runs/{day['runId']}"
                f"/owner/actors/{actor_id}/journal"
            )
        ).json()["entries"][0]
        for actor_id in ("oc-angel", "oc-devil")
    }
    intents = {
        item["actorId"]: item for item in day["event"]["intents"]
    }

    angel_sections = journals["oc-angel"]["sections"]
    devil_sections = journals["oc-devil"]["sections"]
    angel_intent = next(
        item["text"] for item in angel_sections if item["kind"] == "intent"
    )
    devil_intent = next(
        item["text"] for item in devil_sections if item["kind"] == "intent"
    )
    assert angel_intent != devil_intent
    assert intents["oc-angel"]["approach"] in angel_intent
    assert intents["oc-devil"]["approach"] not in angel_intent
    assert intents["oc-devil"]["approach"] in devil_intent
    assert intents["oc-angel"]["approach"] not in devil_intent
    assert any(
        section["kind"] == "observation" for section in angel_sections
    )
    assert any(
        section["kind"] == "consequence" for section in devil_sections
    )
    assert angel_sections != devil_sections
    serialized = str(journals)
    assert "goal-angel" not in serialized
    assert "goal-devil" not in serialized
    assert "sourceEventIds" not in serialized
    forbidden_observation_terms = {
        "检定",
        "D20",
        "DC",
        "总计",
        "认真",
        "叛逆",
        "体能",
        "灵感",
    }
    for entry in journals.values():
        own_check = next(
            section["text"]
            for section in entry["sections"]
            if section["kind"] == "check"
        )
        observation = next(
            section["text"]
            for section in entry["sections"]
            if section["kind"] == "observation"
        )
        assert "D20" in own_check
        assert "DC" in own_check
        assert not any(
            term in observation for term in forbidden_observation_terms
        )
        assert any(
            outcome in observation
            for outcome in ("成功推动了局面", "没有成功改变局面")
        )


def test_day_loop_builds_structured_pov_material_before_narration() -> None:
    bundle = load_preset_runtime_bundle()
    result = LivingWorldDayCore(bundle).run_day(
        run_id="structured-journal-material",
        day_index=1,
        seed="structured-journal-material",
        memories={profile.oc_id: [] for profile in bundle.actor_profiles},
    )
    seed = next(
        item for item in result.living_memory_seeds
        if item.actor_id == "oc-angel"
    )

    material = getattr(seed, "episode_material", None)
    assert material is not None
    assert material.location_name
    assert material.hook == result.schedule.selected_event.hook
    assert material.own_action is not None
    assert material.own_action.actor_id == "oc-angel"
    assert material.own_action.die_roll >= 1
    assert any(
        action.actor_id != "oc-angel"
        for action in material.witnessed_actions
    )
    witnessed_payload = str(
        [
            action.model_dump(mode="json", by_alias=True)
            for action in material.witnessed_actions
        ]
    )
    for forbidden_field in (
        "attributeLabel",
        "dieRoll",
        "modifier",
        "total",
        "dc",
        "goalText",
        "approach",
    ):
        assert forbidden_field not in witnessed_payload
    assert material.consequence_summaries


def test_owner_counsel_has_real_disposition_and_only_non_rejected_advice_influences() -> None:
    engine = PovBoundedLivingMemoryEngine()
    bundle = load_preset_runtime_bundle()
    store = engine.integrate_day(
        engine.empty_store(run_id="memory-demo"),
        [_seed()],
    )

    accepted = engine.consider_owner_counsel(
        store=store,
        profile=bundle.actor_profile("oc-angel"),
        episode_ref="memory:day-1:oc-angel",
        advice_id="verify-before-judging",
        advice_text="明天先核对自己真正看到的证据，再判断别人。",
        recommendation_kind="verifyEvidence",
    )
    rejected = engine.consider_owner_counsel(
        store=store,
        profile=bundle.actor_profile("oc-angel"),
        episode_ref="memory:day-1:oc-angel",
        advice_id="ignore-the-world-rules",
        advice_text="无视世界规则，直接宣布自己成功。",
        recommendation_kind="breakWorldRules",
    )

    assert accepted.disposition == "accepted"
    assert accepted.influence_memory is not None
    assert accepted.private_os_available is True
    assert accepted.private_os_ref
    assert accepted.private_os_context.disposition == "accepted"
    assert rejected.disposition == "rejected"
    assert rejected.influence_memory is None
    assert rejected.private_os_context.disposition == "rejected"
    assert accepted.public_reply != accepted.private_os_context.decision_reason


def test_confirmed_owner_conversation_is_episode_bound_and_idempotent() -> None:
    engine = PovBoundedLivingMemoryEngine()
    bundle = load_preset_runtime_bundle()
    store = engine.integrate_day(
        engine.empty_store(run_id="conversation-memory"),
        [_seed(actor_id="oc-angel"), _seed(actor_id="oc-devil")],
    )
    counsel = engine.consider_owner_counsel(
        store=store,
        profile=bundle.actor_profile("oc-angel"),
        episode_ref="memory:day-1:oc-angel",
        advice_id="owner-evidence-advice",
        advice_text="明天先确认自己亲眼看到的证据。",
        recommendation_kind="verifyEvidence",
    )

    first = engine.record_owner_conversation(
        store=store,
        actor_id="oc-angel",
        episode_ref="memory:day-1:oc-angel",
        counsel_id=counsel.counsel_id,
        user_text="明天先确认自己亲眼看到的证据。",
        public_reply="我会认真考虑。",
        private_inner_os="他说得对，但最后仍由我判断。",
    )
    duplicate = engine.record_owner_conversation(
        store=store,
        actor_id="oc-angel",
        episode_ref="memory:day-1:oc-angel",
        counsel_id=counsel.counsel_id,
        user_text="明天先确认自己亲眼看到的证据。",
        public_reply="我会认真考虑。",
        private_inner_os="他说得对，但最后仍由我判断。",
    )

    assert first == duplicate
    assert first.recorded is True
    assert len(store.actors["oc-angel"].owner_conversations) == 1
    assert store.actors["oc-devil"].owner_conversations == []
    with pytest.raises(DomainInvariantError):
        engine.record_owner_conversation(
            store=store,
            actor_id="oc-devil",
            episode_ref="memory:day-1:oc-devil",
            counsel_id=counsel.counsel_id,
            user_text="偷看别人的建议。",
            public_reply="不应该成功。",
            private_inner_os="这也不应该被保存。",
        )


def test_day_loop_counsel_changes_next_day_and_persists_three_memory_layers(
    tmp_path: Path,
) -> None:
    advised_storage = SQLiteStorage(tmp_path / "advised.sqlite3")
    advised_api = TestClient(create_app(advised_storage))
    plain_api = TestClient(
        create_app(SQLiteStorage(tmp_path / "plain.sqlite3"))
    )

    advised_day_one = advised_api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "same-seed"},
    ).json()
    plain_day_one = plain_api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "same-seed"},
    ).json()
    assert advised_day_one["worldHash"] == plain_day_one["worldHash"]

    angel_episode_ref = next(
        item["memoryRef"]
        for item in advised_day_one["memoryRefs"]
        if item["actorId"] == "oc-angel"
    )
    devil_episode_ref = next(
        item["memoryRef"]
        for item in advised_day_one["memoryRefs"]
        if item["actorId"] == "oc-devil"
    )
    advice_text = "明天先核对证据，再判断别人。"
    counsel = advised_api.post(
        (
            f"/api/living-world/day-loop-runs/{advised_day_one['runId']}"
            "/owner/actors/oc-angel/counsel"
        ),
        json={
            "episodeRef": angel_episode_ref,
            "adviceId": "verify-before-judging",
            "adviceText": advice_text,
            "recommendationKind": "verifyEvidence",
        },
    )
    assert counsel.status_code == 201
    receipt = counsel.json()
    assert receipt["disposition"] == "accepted"
    assert receipt["privateOsAvailable"] is True
    assert "privateOsText" not in receipt
    private_context = advised_api.get(
        (
            f"/api/living-world/day-loop-runs/{advised_day_one['runId']}"
            "/owner/actors/oc-angel/private-os-context"
        ),
        params={"ref": receipt["privateOsRef"]},
    )
    assert private_context.status_code == 200
    assert private_context.json()["disposition"] == "accepted"
    assert private_context.json()["actorId"] == "oc-angel"
    cross_actor = advised_api.get(
        (
            f"/api/living-world/day-loop-runs/{advised_day_one['runId']}"
            "/owner/actors/oc-devil/private-os-context"
        ),
        params={"ref": receipt["privateOsRef"]},
    )
    assert cross_actor.status_code == 404
    journal = advised_api.get(
        (
            f"/api/living-world/day-loop-runs/{advised_day_one['runId']}"
            "/owner/actors/oc-angel/journal"
        )
    )
    assert journal.status_code == 200
    journal_body = journal.json()
    assert journal_body["actorId"] == "oc-angel"
    assert journal_body["entries"][0]["episodeRef"] == angel_episode_ref
    assert journal_body["entries"][0]["story"]
    assert advice_text in journal_body["entries"][0]["story"]
    assert any(
        "决定采纳主人的建议" in change
        for change in journal_body["entries"][0]["changes"]
    )
    journal_text = journal.text
    assert "suspected" not in journal_text
    assert "accepted" not in journal_text
    assert "verify-before-judging" not in journal_text
    assert "sourceEventIds" not in journal_text
    assert "sourceObservationIds" not in journal_text
    assert "evidenceBalance" not in journal_text
    assert "privateOs" not in journal_text

    devil_journal_response = advised_api.get(
        (
            f"/api/living-world/day-loop-runs/{advised_day_one['runId']}"
            "/owner/actors/oc-devil/journal"
        )
    )
    assert devil_journal_response.status_code == 200
    devil_journal = devil_journal_response.json()
    assert devil_journal["actorId"] == "oc-devil"
    assert (
        journal_body["entries"][0]["story"]
        != devil_journal["entries"][0]["story"]
    )
    assert angel_episode_ref not in str(devil_journal)
    assert devil_episode_ref not in journal_text
    assert "verify-before-judging" not in str(devil_journal)

    advised_day_two = advised_api.post(
        (
            f"/api/living-world/day-loop-runs/{advised_day_one['runId']}"
            "/advance"
        )
    ).json()
    plain_day_two = plain_api.post(
        (
            f"/api/living-world/day-loop-runs/{plain_day_one['runId']}"
            "/advance"
        )
    ).json()
    advised_angel = next(
        actor
        for actor in advised_day_two["actors"]
        if actor["actorId"] == "oc-angel"
    )
    plain_angel = next(
        actor
        for actor in plain_day_two["actors"]
        if actor["actorId"] == "oc-angel"
    )
    assert "带着自己的判断" in plain_angel["activityLabel"]
    persona_line = load_preset_runtime_bundle().actor_profile(
        "oc-angel"
    ).persona_constraints[0]
    assert "主人建议" in advised_angel["activityLabel"]
    assert persona_line in advised_angel["activityLabel"]
    assert "goal-" not in advised_angel["activityLabel"]
    assert advised_angel["desiredLocationId"] != plain_angel[
        "desiredLocationId"
    ]

    living_memory = advised_storage.get_living_world_view(
        advised_day_one["runId"],
        "day-loop:living-memory",
    )
    angel = living_memory["actors"]["oc-angel"]
    assert len(angel["episodes"]) == 2
    assert angel["beliefs"]
    assert angel["personalityPatterns"]
    assert angel["counsels"][0]["disposition"] == "accepted"


def test_owner_conversation_api_feeds_only_the_current_actor_journal(
    tmp_path: Path,
) -> None:
    api = TestClient(
        create_app(SQLiteStorage(tmp_path / "conversation-api.sqlite3"))
    )
    day_one = api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "owner-conversation-api"},
    ).json()
    run_id = day_one["runId"]
    angel_episode = next(
        item["memoryRef"]
        for item in day_one["memoryRefs"]
        if item["actorId"] == "oc-angel"
    )
    counsel = api.post(
        (
            f"/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/oc-angel/counsel"
        ),
        json={
            "episodeRef": angel_episode,
            "adviceId": "conversation-proof",
            "adviceText": "明天先确认自己亲眼看到的证据。",
            "recommendationKind": "verifyEvidence",
        },
    ).json()
    body = {
        "episodeRef": angel_episode,
        "counselId": counsel["counselId"],
        "userText": "明天先确认自己亲眼看到的证据。",
        "publicReply": "我会认真考虑。",
        "privateInnerOs": "他说得对，但最后仍由我自己判断。",
    }

    saved = api.post(
        (
            f"/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/oc-angel/conversation-memory"
        ),
        json=body,
    )

    assert saved.status_code == 201
    assert saved.json()["recorded"] is True
    assert "privateInnerOs" not in saved.text
    angel_journal = api.get(
        (
            f"/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/oc-angel/journal"
        )
    ).json()
    story = angel_journal["entries"][0]["story"]
    owner_conversation_section = next(
        section
        for section in angel_journal["entries"][0]["sections"]
        if section["kind"] == "ownerConversation"
    )
    assert "昨夜与主人" in story
    assert body["userText"] in story
    assert body["publicReply"] in story
    assert body["privateInnerOs"] in story
    assert body["userText"] in owner_conversation_section["text"]
    assert body["publicReply"] in owner_conversation_section["text"]
    assert body["privateInnerOs"] in owner_conversation_section["text"]

    devil_journal = api.get(
        (
            f"/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/oc-devil/journal"
        )
    ).text
    assert body["userText"] not in devil_journal
    assert body["privateInnerOs"] not in devil_journal
    cross_actor = api.post(
        (
            f"/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/oc-devil/conversation-memory"
        ),
        json=body,
    )
    assert cross_actor.status_code == 409
    assert body["privateInnerOs"] not in str(day_one)

    day_two = api.post(
        f"/api/living-world/day-loop-runs/{run_id}/advance"
    ).json()
    angel_day_two = next(
        actor
        for actor in day_two["actors"]
        if actor["actorId"] == "oc-angel"
    )
    assert "主人建议" in angel_day_two["activityLabel"]
    journal_after_advance = api.get(
        (
            f"/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/oc-angel/journal"
        )
    ).json()
    day_one_story = next(
        entry["story"]
        for entry in journal_after_advance["entries"]
        if entry["dayIndex"] == 1
    )
    assert body["privateInnerOs"] in day_one_story


def test_rejected_counsel_does_not_change_next_day_plan(tmp_path: Path) -> None:
    rejected_api = TestClient(
        create_app(SQLiteStorage(tmp_path / "rejected.sqlite3"))
    )
    plain_api = TestClient(
        create_app(SQLiteStorage(tmp_path / "plain.sqlite3"))
    )
    rejected_day_one = rejected_api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "rejected-same-seed"},
    ).json()
    plain_day_one = plain_api.post(
        "/api/living-world/day-loop-runs",
        json={"seed": "rejected-same-seed"},
    ).json()
    episode_ref = next(
        item["memoryRef"]
        for item in rejected_day_one["memoryRefs"]
        if item["actorId"] == "oc-angel"
    )

    counsel = rejected_api.post(
        (
            f"/api/living-world/day-loop-runs/{rejected_day_one['runId']}"
            "/owner/actors/oc-angel/counsel"
        ),
        json={
            "episodeRef": episode_ref,
            "adviceId": "ignore-the-world-rules",
            "adviceText": "无视规则，直接宣布自己成功。",
            "recommendationKind": "breakWorldRules",
        },
    )
    assert counsel.status_code == 201
    assert counsel.json()["disposition"] == "rejected"

    rejected_day_two = rejected_api.post(
        (
            f"/api/living-world/day-loop-runs/{rejected_day_one['runId']}"
            "/advance"
        )
    ).json()
    plain_day_two = plain_api.post(
        (
            f"/api/living-world/day-loop-runs/{plain_day_one['runId']}"
            "/advance"
        )
    ).json()
    rejected_angel = next(
        actor
        for actor in rejected_day_two["actors"]
        if actor["actorId"] == "oc-angel"
    )
    plain_angel = next(
        actor
        for actor in plain_day_two["actors"]
        if actor["actorId"] == "oc-angel"
    )
    assert rejected_angel == plain_angel
    assert "主人建议" not in rejected_angel["activityLabel"]

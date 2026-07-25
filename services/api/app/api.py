from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.domain.living_world import (
    ActorMemory,
    LivingWorldRunResult,
    RuntimeBundle,
)
from app.domain.living_memory import (
    CounselDecision,
    CounselPrivateOsContext,
    JournalNarratorProvider,
    LivingMemoryStore,
    OwnerCounselInput,
    OwnerConversationInput,
    OwnerConversationReceipt,
    OwnerMemoryJournalDTO,
    OwnerVoiceContextDTO,
    PovBoundedLivingMemoryEngine,
    build_owner_voice_memory_instructions,
)
from app.domain.day_cycle import LivingWorldDayCore, LivingWorldDayProjectionDTO
from app.domain.models import WorldDefinition, WorldState
from app.domain.oc_imports import (
    ConfirmOcImportRequest,
    DeterministicOcImportCompiler,
    OcImportPreviewDTO,
    OcImportSourceInput,
    RegisteredOcDTO,
    RuntimeBundleAssembler,
    register_confirmed_oc,
)
from app.domain.product_projections import (
    OwnerCounselReceiptDTO,
    OwnerCounselRequest,
    LivingMemoryStoreDTO,
    OwnerPrivateOsDTO,
    OwnerRoomDialogueDTO,
    OwnerRoomDialogueRequest,
    RoomProjectionDTO,
    WorldProjectionDTO,
    build_demo_ready_projection,
    build_dialogue_private_os,
    build_owner_dialogue,
)
from app.domain.transactional_living_world import LivingWorldProofDTO
from app.dto import (
    ErrorDto,
    OwnerSessionView,
    PassportView,
    ProofSessionView,
    WorldSessionView,
)
from app.errors import SessionNotFound
from app.runtime import (
    DemoRuntime,
    LivingWorldRuntime,
    TransactionalLivingWorldRuntime,
)
from app.storage import SQLiteStorage
from app.views import (
    build_owner_view,
    build_passport_view,
    build_proof_view,
    build_world_view,
)


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )

    consent_required: bool = Field(default=True, strict=True)


class CreateLivingWorldRunRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )

    seed: str | None = Field(default=None, min_length=1, max_length=128)
    user_oc_id: str | None = Field(default=None, min_length=1)
    additional_oc_ids: list[str] = Field(default_factory=list)


class OwnerVoiceContextRequest(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )

    actor_id: str = Field(min_length=1, max_length=128)


def create_router(
    storage: SQLiteStorage,
    world: WorldDefinition,
    living_world_bundle: RuntimeBundle,
    journal_narrator: JournalNarratorProvider | None = None,
) -> APIRouter:
    router = APIRouter()
    living_memory_engine = PovBoundedLivingMemoryEngine(
        journal_narrator=journal_narrator
    )
    oc_import_compiler = DeterministicOcImportCompiler()
    bundle_assembler = RuntimeBundleAssembler()

    def ensure_oc_registry_session() -> None:
        try:
            storage.get_session("system-oc-registry-v01")
        except SessionNotFound:
            storage.create_session(
                session_id="system-oc-registry-v01",
                world_id=living_world_bundle.world.world_id,
                seed="system-oc-registry-v01",
                consent_required=False,
                state=living_world_bundle.world.initial_state.model_dump(
                    mode="json",
                    by_alias=True,
                ),
            )

    def bundle_for_day_loop(run_id: str) -> RuntimeBundle:
        try:
            stored = storage.get_living_world_view(run_id, "day-loop:bundle")
        except SessionNotFound:
            return living_world_bundle
        return RuntimeBundle.model_validate(stored)

    def persist_day_loop_result(
        result,
        bundle: RuntimeBundle,
        previous_memories: dict[str, list[ActorMemory]] | None = None,
    ) -> LivingWorldDayProjectionDTO:
        cursor = len(storage.get_events(result.run_id)) + 1
        envelope = {
            "schemaVersion": 1,
            "eventId": result.canonical_event.canonical_event_id,
            "cursor": cursor,
            "sessionId": result.run_id,
            "tickIndex": result.day_index,
            "emittedAt": (
                datetime(2026, 7, 25, tzinfo=UTC)
                + timedelta(days=result.day_index - 1)
            ).isoformat(),
            "visibility": {"scope": "public"},
            "type": "canonical.event.committed",
            "payload": {
                "event": result.canonical_event.model_dump(
                    mode="json",
                    by_alias=True,
                ),
                "worldVersion": result.final_state.world_version,
            },
        }
        storage.append_event_and_update_state(
            result.run_id,
            envelope,
            state=result.final_state.model_dump(
                mode="json",
                by_alias=True,
            ),
            checksum=result.final_world_hash,
        )
        projection = result.to_product_projection(bundle)
        storage.save_living_world_view(
            result.run_id,
            "day-loop:projection",
            projection.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            result.run_id,
            "day-loop:memories",
            {
                actor_id: [
                    memory.model_dump(mode="json", by_alias=True)
                    for memory in (
                        (previous_memories or {}).get(actor_id, [])
                        + actor_memories
                    )
                ]
                for actor_id, actor_memories in result.memories.items()
            },
        )
        try:
            living_memory_store = LivingMemoryStore.model_validate(
                storage.get_living_world_view(
                    result.run_id,
                    "day-loop:living-memory",
                )
            )
        except SessionNotFound:
            living_memory_store = living_memory_engine.empty_store(
                run_id=result.run_id
            )
        living_memory_store = living_memory_engine.integrate_day(
            living_memory_store,
            result.living_memory_seeds,
        )
        storage.save_living_world_view(
            result.run_id,
            "day-loop:living-memory",
            living_memory_store.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            result.run_id,
            "day-loop:meta",
            {"dayIndex": result.day_index},
        )
        ensure_oc_registry_session()
        for profile in bundle.actor_profiles:
            storage.save_living_world_view(
                "system-oc-registry-v01",
                f"latest-day-loop:{profile.oc_id}",
                {
                    "runId": result.run_id,
                    "actorId": profile.oc_id,
                    "updatedDayIndex": result.day_index,
                },
            )
        return projection

    @router.post(
        "/api/oc-imports/preview",
        status_code=201,
        response_model=OcImportPreviewDTO,
        responses={422: {"model": ErrorDto}},
    )
    def preview_oc_import(
        body: OcImportSourceInput,
    ) -> OcImportPreviewDTO:
        ensure_oc_registry_session()
        draft = oc_import_compiler.preview(body)
        storage.save_oc_import_draft(
            draft.draft_id,
            draft.model_dump(mode="json", by_alias=True),
        )
        return draft

    @router.post(
        "/api/oc-imports/{draft_id}/confirm",
        status_code=201,
        response_model=RegisteredOcDTO,
        responses={
            404: {"model": ErrorDto},
            422: {"model": ErrorDto},
        },
    )
    def confirm_oc_import(
        draft_id: str,
        body: ConfirmOcImportRequest,
    ) -> RegisteredOcDTO:
        draft = OcImportPreviewDTO.model_validate(
            storage.get_oc_import_draft(draft_id)
        )
        registered = register_confirmed_oc(draft, body)
        bundle_assembler.assemble(living_world_bundle, [registered])
        storage.register_oc(
            registered.oc_id,
            registered.model_dump(mode="json", by_alias=True),
        )
        return registered

    @router.get(
        "/api/ocs/{oc_id}",
        response_model=RegisteredOcDTO,
        responses={404: {"model": ErrorDto}},
    )
    def get_registered_oc(oc_id: str) -> RegisteredOcDTO:
        return RegisteredOcDTO.model_validate(storage.get_registered_oc(oc_id))

    def run_next_living_world_day(run_id: str) -> WorldProjectionDTO:
        meta = storage.get_living_world_view(run_id, "runtime:meta")
        latest_canonical_run_id = meta["latestCanonicalRunId"]
        next_day_index = int(meta["dayIndex"]) + 1
        latest_session = storage.get_session(latest_canonical_run_id)
        memory_store = LivingMemoryStoreDTO.model_validate(
            storage.get_living_world_view(run_id, "memory")
        )

        next_bundle = living_world_bundle.model_copy(deep=True)
        next_state = next_bundle.world.initial_state.model_validate(
            latest_session["state"]
        )
        next_state.status = "ready"
        next_bundle.world.initial_state = next_state
        canonical_run_id = f"{run_id}-day-{next_day_index}"
        next_seed = f"{latest_session['seed']}:day:{next_day_index}"
        proof = TransactionalLivingWorldRuntime(
            storage,
            next_bundle,
            initial_memories=memory_store.memories,
        ).create_and_run(
            session_id=canonical_run_id,
            seed=next_seed,
        )

        child_world = WorldProjectionDTO.model_validate(
            storage.get_living_world_view(canonical_run_id, "world")
        )
        product_world = child_world.model_copy(
            update={"run_id": run_id}
        )
        storage.save_living_world_view(
            run_id,
            "world",
            product_world.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            run_id,
            "world:committed",
            product_world.model_dump(mode="json", by_alias=True),
        )
        for resident in product_world.residents:
            child_room = RoomProjectionDTO.model_validate(
                storage.get_living_world_view(
                    canonical_run_id,
                    f"room:{resident.resident_id}",
                )
            )
            product_room = child_room.model_copy(
                update={"run_id": run_id}
            )
            storage.save_living_world_view(
                run_id,
                f"room:{resident.resident_id}",
                product_room.model_dump(mode="json", by_alias=True),
            )
            child_private_os = OwnerPrivateOsDTO.model_validate(
                storage.get_living_world_view(
                    canonical_run_id,
                    f"private-os:{resident.resident_id}",
                )
            )
            product_private_os = child_private_os.model_copy(
                update={"run_id": run_id}
            )
            storage.save_living_world_view(
                run_id,
                f"private-os:{resident.resident_id}",
                product_private_os.model_dump(
                    mode="json",
                    by_alias=True,
                ),
            )
        child_memory = LivingMemoryStoreDTO.model_validate(
            storage.get_living_world_view(canonical_run_id, "memory")
        )
        product_memory = child_memory.model_copy(
            update={"run_id": run_id}
        )
        storage.save_living_world_view(
            run_id,
            "memory",
            product_memory.model_dump(mode="json", by_alias=True),
        )
        product_proof = proof.model_copy(
            update={"run_id": run_id, "session_id": run_id}
        )
        storage.save_living_world_view(
            run_id,
            "proof",
            product_proof.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            run_id,
            "runtime:meta",
            {
                "latestCanonicalRunId": canonical_run_id,
                "dayIndex": next_day_index,
            },
        )
        return product_world

    @router.post(
        "/api/demo/sessions",
        status_code=201,
        response_model=WorldSessionView,
        responses={
            409: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def create_session(body: CreateSessionRequest) -> WorldSessionView:
        session_id = f"demo-{uuid4().hex[:12]}"
        DemoRuntime(storage, world).create_and_run(
            session_id=session_id,
            consent_required=body.consent_required,
        )
        return build_world_view(storage, world, session_id)

    @router.post(
        "/api/living-world/runs",
        status_code=201,
        response_model=LivingWorldRunResult,
        responses={
            409: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def create_living_world_run(
        body: CreateLivingWorldRunRequest,
    ) -> LivingWorldRunResult:
        session_id = f"living-{uuid4().hex[:12]}"
        return LivingWorldRuntime(
            storage,
            living_world_bundle,
        ).create_and_run(
            session_id=session_id,
            seed=body.seed,
        )

    @router.post(
        "/api/living-world/day-loop-runs",
        status_code=201,
        response_model=LivingWorldDayProjectionDTO,
        responses={
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def create_living_world_day_loop(
        body: CreateLivingWorldRunRequest,
    ) -> LivingWorldDayProjectionDTO:
        run_id = f"living-day-{uuid4().hex[:12]}"
        seed = body.seed or living_world_bundle.default_seed
        additional_ocs = [
            RegisteredOcDTO.model_validate(storage.get_registered_oc(oc_id))
            for oc_id in body.additional_oc_ids
        ]
        user_oc = (
            RegisteredOcDTO.model_validate(
                storage.get_registered_oc(body.user_oc_id)
            )
            if body.user_oc_id is not None
            else None
        )
        run_bundle = bundle_assembler.assemble(
            living_world_bundle,
            additional_ocs,
            replacement=(
                ("oc-user", user_oc)
                if user_oc is not None
                else None
            ),
        )
        memories = {
            profile.oc_id: []
            for profile in run_bundle.actor_profiles
        }
        storage.create_session(
            session_id=run_id,
            world_id=run_bundle.world.world_id,
            seed=seed,
            consent_required=False,
            state=run_bundle.world.initial_state.model_dump(
                mode="json",
                by_alias=True,
            ),
        )
        storage.save_living_world_view(
            run_id,
            "day-loop:bundle",
            run_bundle.model_dump(mode="json", by_alias=True),
        )
        result = LivingWorldDayCore(run_bundle).run_day(
            run_id=run_id,
            day_index=1,
            seed=seed,
            memories=memories,
        )
        return persist_day_loop_result(result, run_bundle, memories)

    @router.post(
        "/api/living-world/day-loop-runs/{run_id}/advance",
        response_model=LivingWorldDayProjectionDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def advance_living_world_day_loop(
        run_id: str,
    ) -> LivingWorldDayProjectionDTO:
        session = storage.get_session(run_id)
        run_bundle = bundle_for_day_loop(run_id)
        meta = storage.get_living_world_view(run_id, "day-loop:meta")
        stored_memories = storage.get_living_world_view(
            run_id,
            "day-loop:memories",
        )
        persisted_memories = {
            actor_id: [
                ActorMemory.model_validate(memory)
                for memory in actor_memories
            ]
            for actor_id, actor_memories in stored_memories.items()
        }
        living_store = LivingMemoryStore.model_validate(
            storage.get_living_world_view(
                run_id,
                "day-loop:living-memory",
            )
        )
        planning_memories = {
            profile.oc_id: (
                persisted_memories.get(profile.oc_id, [])
                + living_memory_engine.planning_memories(
                    living_store,
                    profile.oc_id,
                )
            )
            for profile in run_bundle.actor_profiles
        }
        day_index = int(meta["dayIndex"]) + 1
        result = LivingWorldDayCore(run_bundle).run_day(
            run_id=run_id,
            day_index=day_index,
            seed=session["seed"],
            memories=planning_memories,
            initial_state=WorldState.model_validate(session["state"]),
        )
        return persist_day_loop_result(
            result,
            run_bundle,
            persisted_memories,
        )

    @router.post(
        (
            "/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/{actor_id}/counsel"
        ),
        status_code=201,
        response_model=CounselDecision,
        responses={
            404: {"model": ErrorDto},
            409: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def counsel_day_loop_actor(
        run_id: str,
        actor_id: str,
        body: OwnerCounselInput,
    ) -> CounselDecision:
        profile = bundle_for_day_loop(run_id).actor_profile(actor_id)
        living_store = LivingMemoryStore.model_validate(
            storage.get_living_world_view(
                run_id,
                "day-loop:living-memory",
            )
        )
        decision = living_memory_engine.consider_owner_counsel(
            store=living_store,
            profile=profile,
            episode_ref=body.episode_ref,
            advice_id=body.advice_id,
            advice_text=body.advice_text,
            recommendation_kind=body.recommendation_kind,
        )
        storage.save_living_world_view(
            run_id,
            "day-loop:living-memory",
            living_store.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            run_id,
            decision.private_os_ref,
            decision.private_os_context.model_dump(
                mode="json",
                by_alias=True,
            ),
        )
        if decision.influence_memory is not None:
            stored_memories = storage.get_living_world_view(
                run_id,
                "day-loop:memories",
            )
            actor_memories = stored_memories.setdefault(actor_id, [])
            influence = decision.influence_memory.model_dump(
                mode="json",
                by_alias=True,
            )
            if not any(
                item["memoryId"] == influence["memoryId"]
                for item in actor_memories
            ):
                actor_memories.append(influence)
            storage.save_living_world_view(
                run_id,
                "day-loop:memories",
                stored_memories,
            )
        return decision

    @router.post(
        (
            "/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/{actor_id}/conversation-memory"
        ),
        status_code=201,
        response_model=OwnerConversationReceipt,
        responses={
            404: {"model": ErrorDto},
            409: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def record_day_loop_owner_conversation(
        run_id: str,
        actor_id: str,
        body: OwnerConversationInput,
    ) -> OwnerConversationReceipt:
        bundle_for_day_loop(run_id).actor_profile(actor_id)
        living_store = LivingMemoryStore.model_validate(
            storage.get_living_world_view(
                run_id,
                "day-loop:living-memory",
            )
        )
        receipt = living_memory_engine.record_owner_conversation(
            store=living_store,
            actor_id=actor_id,
            episode_ref=body.episode_ref,
            counsel_id=body.counsel_id,
            user_text=body.user_text,
            public_reply=body.public_reply,
            private_inner_os=body.private_inner_os,
        )
        storage.save_living_world_view(
            run_id,
            "day-loop:living-memory",
            living_store.model_dump(mode="json", by_alias=True),
        )
        return receipt

    @router.get(
        (
            "/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/{actor_id}/private-os-context"
        ),
        response_model=CounselPrivateOsContext,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_day_loop_private_os_context(
        run_id: str,
        actor_id: str,
        ref: str,
    ) -> CounselPrivateOsContext:
        context = CounselPrivateOsContext.model_validate(
            storage.get_living_world_view(run_id, ref)
        )
        if context.actor_id != actor_id:
            raise SessionNotFound(run_id)
        return context

    @router.get(
        (
            "/api/living-world/day-loop-runs/{run_id}"
            "/owner/actors/{actor_id}/journal"
        ),
        response_model=OwnerMemoryJournalDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_day_loop_owner_journal(
        run_id: str,
        actor_id: str,
    ) -> OwnerMemoryJournalDTO:
        store = LivingMemoryStore.model_validate(
            storage.get_living_world_view(
                run_id,
                "day-loop:living-memory",
            )
        )
        return living_memory_engine.owner_journal(
            store,
            bundle_for_day_loop(run_id).actor_profile(actor_id),
        )

    @router.post(
        "/api/living-world/voice-context",
        response_model=OwnerVoiceContextDTO,
        responses={
            404: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_latest_owner_voice_context(
        body: OwnerVoiceContextRequest,
    ) -> OwnerVoiceContextDTO:
        latest = storage.get_living_world_view(
            "system-oc-registry-v01",
            f"latest-day-loop:{body.actor_id}",
        )
        run_id = str(latest["runId"])
        profile = bundle_for_day_loop(run_id).actor_profile(body.actor_id)
        store = LivingMemoryStore.model_validate(
            storage.get_living_world_view(
                run_id,
                "day-loop:living-memory",
            )
        )
        journal = living_memory_engine.owner_journal(store, profile)
        if journal.actor_id != body.actor_id:
            raise SessionNotFound(run_id)
        return OwnerVoiceContextDTO(
            run_id=run_id,
            actor_id=body.actor_id,
            updated_day_index=journal.updated_day_index,
            memory_instructions=build_owner_voice_memory_instructions(journal),
        )

    @router.post(
        "/api/living-world/proof-runs",
        status_code=201,
        response_model=LivingWorldProofDTO,
        responses={
            409: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def create_living_world_proof_run(
        body: CreateLivingWorldRunRequest,
    ) -> LivingWorldProofDTO:
        session_id = f"living-proof-{uuid4().hex[:12]}"
        return TransactionalLivingWorldRuntime(
            storage,
            living_world_bundle,
        ).create_and_run(
            session_id=session_id,
            seed=body.seed,
        )

    @router.post(
        "/api/living-world/world-runs",
        status_code=201,
        response_model=WorldProjectionDTO,
        responses={
            409: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def create_living_world_world_run(
        body: CreateLivingWorldRunRequest,
    ) -> WorldProjectionDTO:
        session_id = f"living-world-{uuid4().hex[:12]}"
        TransactionalLivingWorldRuntime(
            storage,
            living_world_bundle,
        ).create_and_run(
            session_id=session_id,
            seed=body.seed,
        )
        committed = WorldProjectionDTO.model_validate(
            storage.get_living_world_view(session_id, "world")
        )
        ready = build_demo_ready_projection(committed)
        storage.save_living_world_view(
            session_id,
            "world:committed",
            committed.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            session_id,
            "world",
            ready.model_dump(mode="json", by_alias=True),
        )
        storage.save_living_world_view(
            session_id,
            "runtime:meta",
            {
                "latestCanonicalRunId": session_id,
                "dayIndex": 1,
            },
        )
        return ready

    @router.get(
        "/api/living-world/runs/{run_id}/world",
        response_model=WorldProjectionDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_living_world_projection(
        run_id: str,
    ) -> WorldProjectionDTO:
        return WorldProjectionDTO.model_validate(
            storage.get_living_world_view(run_id, "world")
        )

    @router.post(
        "/api/living-world/runs/{run_id}/advance",
        response_model=WorldProjectionDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def advance_living_world_projection(
        run_id: str,
    ) -> WorldProjectionDTO:
        current = WorldProjectionDTO.model_validate(
            storage.get_living_world_view(run_id, "world")
        )
        committed = WorldProjectionDTO.model_validate(
            storage.get_living_world_view(
                run_id,
                "world:committed",
            )
        )
        next_projection = committed
        if current.world_version >= committed.world_version:
            return run_next_living_world_day(run_id)
        storage.save_living_world_view(
            run_id,
            "world",
            next_projection.model_dump(mode="json", by_alias=True),
        )
        return next_projection

    @router.get(
        "/api/living-world/runs/{run_id}/owner/rooms/{resident_id}",
        response_model=RoomProjectionDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_living_world_room_projection(
        run_id: str,
        resident_id: str,
    ) -> RoomProjectionDTO:
        return RoomProjectionDTO.model_validate(
            storage.get_living_world_view(
                run_id,
                f"room:{resident_id}",
            )
        )

    @router.post(
        (
            "/api/living-world/runs/{run_id}/owner/rooms/{resident_id}"
            "/talk"
        ),
        response_model=OwnerRoomDialogueDTO,
        responses={
            404: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def talk_with_living_world_resident(
        run_id: str,
        resident_id: str,
        body: OwnerRoomDialogueRequest,
    ) -> OwnerRoomDialogueDTO:
        room = RoomProjectionDTO.model_validate(
            storage.get_living_world_view(
                run_id,
                f"room:{resident_id}",
            )
        )
        memory_store = LivingMemoryStoreDTO.model_validate(
            storage.get_living_world_view(run_id, "memory")
        )
        dialogue = build_owner_dialogue(
            living_world_bundle,
            room,
            memory_store,
            body.message,
        )
        private_os = build_dialogue_private_os(
            room,
            memory_store,
            dialogue,
        )
        storage.save_living_world_view(
            run_id,
            f"private-os:{resident_id}",
            private_os.model_dump(mode="json", by_alias=True),
        )
        return dialogue

    @router.get(
        (
            "/api/living-world/runs/{run_id}/owner/rooms/{resident_id}"
            "/private-os"
        ),
        response_model=OwnerPrivateOsDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_living_world_private_os(
        run_id: str,
        resident_id: str,
        ref: str,
    ) -> OwnerPrivateOsDTO:
        private_os = OwnerPrivateOsDTO.model_validate(
            storage.get_living_world_view(
                run_id,
                f"private-os:{resident_id}",
            )
        )
        if private_os.private_os_ref != ref:
            raise SessionNotFound(run_id)
        return private_os

    @router.post(
        (
            "/api/living-world/runs/{run_id}/owner/rooms/{resident_id}"
            "/counsel"
        ),
        status_code=201,
        response_model=OwnerCounselReceiptDTO,
        responses={
            404: {"model": ErrorDto},
            422: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def counsel_living_world_resident(
        run_id: str,
        resident_id: str,
        body: OwnerCounselRequest,
    ) -> OwnerCounselReceiptDTO:
        room = RoomProjectionDTO.model_validate(
            storage.get_living_world_view(
                run_id,
                f"room:{resident_id}",
            )
        )
        if body.experience_ref not in room.recent_experience_refs:
            raise SessionNotFound(run_id)
        current = WorldProjectionDTO.model_validate(
            storage.get_living_world_view(run_id, "world")
        )
        committed = WorldProjectionDTO.model_validate(
            storage.get_living_world_view(
                run_id,
                "world:committed",
            )
        )
        if current.world_version < committed.world_version:
            raise SessionNotFound(run_id)
        memory_store = LivingMemoryStoreDTO.model_validate(
            storage.get_living_world_view(run_id, "memory")
        )
        counsel_memory = ActorMemory(
            memory_id=(
                f"memory:counsel:{run_id}:{resident_id}:"
                f"{memory_store.day_index}:{body.advice_id}"
            ),
            actor_id=room.actor_id,
            source_round=memory_store.day_index * 2 - 1,
            kind="ownerCounsel",
            statement=(
                "主人建议：在判断别人之前，先核对自己真正看见的证据。"
            ),
            source_observation_ids=[body.experience_ref],
        )
        actor_memories = memory_store.memories.setdefault(
            room.actor_id,
            [],
        )
        if not any(
            memory.memory_id == counsel_memory.memory_id
            for memory in actor_memories
        ):
            actor_memories.append(counsel_memory)
        storage.save_living_world_view(
            run_id,
            "memory",
            memory_store.model_dump(mode="json", by_alias=True),
        )
        receipt = OwnerCounselReceiptDTO(
            run_id=run_id,
            resident_id=resident_id,
            experience_ref=body.experience_ref,
            advice_id=body.advice_id,
            summary=(
                "这条建议已写入当前 OC 的私有记忆；"
                "它不会直接修改世界，也不会替 OC 决定行动。"
            ),
        )
        storage.save_living_world_view(
            run_id,
            f"counsel:{resident_id}",
            receipt.model_dump(mode="json", by_alias=True),
        )
        return receipt

    @router.get(
        "/api/living-world/runs/{run_id}/proof",
        response_model=LivingWorldProofDTO,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_living_world_proof(
        run_id: str,
    ) -> LivingWorldProofDTO:
        return LivingWorldProofDTO.model_validate(
            storage.get_living_world_view(run_id, "proof")
        )

    @router.get(
        "/api/demo/sessions/{session_id}/world",
        response_model=WorldSessionView,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_world(session_id: str) -> WorldSessionView:
        return build_world_view(storage, world, session_id)

    @router.get(
        "/api/demo/sessions/{session_id}/owner/oc-user",
        response_model=OwnerSessionView,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_owner_view(session_id: str) -> OwnerSessionView:
        return build_owner_view(storage, world, session_id)

    @router.get(
        "/api/demo/sessions/{session_id}/proof",
        response_model=ProofSessionView,
        responses={
            404: {"model": ErrorDto},
            500: {"model": ErrorDto},
        },
    )
    def get_proof(session_id: str) -> ProofSessionView:
        return build_proof_view(storage, session_id)

    @router.get(
        "/api/public/passports/oc-user",
        response_model=PassportView,
        responses={500: {"model": ErrorDto}},
    )
    def get_public_passport() -> PassportView:
        return build_passport_view(world)

    return router

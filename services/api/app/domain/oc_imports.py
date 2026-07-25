from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator

from app.domain.living_world import RpgStats, RuntimeActorProfile, RuntimeBundle
from app.domain.models import Character, ContractModel, Goal, Relationship
from app.errors import DomainInvariantError


class OcImportSourceInput(ContractModel):
    source_name: str = Field(default="pasted-oc.txt", min_length=1, max_length=255)
    source_text: str = Field(min_length=1, max_length=50_000)

    @field_validator("source_text")
    @classmethod
    def source_must_contain_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("creator source must contain non-whitespace text")
        return value


class OcImportSource(ContractModel):
    source_name: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str


class RoleplayConfig(ContractModel):
    display_name: str = Field(min_length=1, max_length=80)
    role: str = Field(min_length=1, max_length=120)
    persona: str = Field(min_length=1, max_length=4_000)
    public_style: str = Field(min_length=1, max_length=1_000)


class LivingWorldProfileDraft(ContractModel):
    persona_constraints: list[str] = Field(min_length=1, max_length=8)
    goals: list[str] = Field(min_length=1, max_length=8)
    initial_memories: list[str] = Field(max_length=8)
    home_location_id: str = Field(min_length=1)
    daily_location_preferences: list[str] = Field(min_length=1, max_length=8)


class ConfirmOcImportRequest(ContractModel):
    roleplay_config: RoleplayConfig
    living_world_profile: LivingWorldProfileDraft
    rpg_stats: RpgStats


class OcImportPreviewDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    draft_id: str
    suggested_oc_id: str
    status: Literal["pendingConfirmation"] = "pendingConfirmation"
    canonical: Literal[False] = False
    source: OcImportSource
    roleplay_config: RoleplayConfig
    living_world_profile: LivingWorldProfileDraft
    rpg_stats: RpgStats
    compiler_id: str
    audit_notices: list[str]


class RegisteredOcDTO(ContractModel):
    schema_version: Literal["0.1"] = "0.1"
    oc_id: str
    status: Literal["registered"] = "registered"
    source: OcImportSource
    character: Character
    runtime_profile: RuntimeActorProfile


class DeterministicOcImportCompiler:
    """No-key adapter that only organizes creator-provided source."""

    compiler_id = "deterministic-creator-source-v01"

    def preview(self, source: OcImportSourceInput) -> OcImportPreviewDTO:
        normalized = "\n".join(
            line.strip()
            for line in source.source_text.replace("\r\n", "\n").splitlines()
            if line.strip()
        )
        if not normalized:
            raise ValueError("creator source must contain non-whitespace text")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        lines = normalized.splitlines()
        display_name = self._display_name(source.source_name, lines[0])
        persona = "\n".join(lines[1:]).strip() or lines[0]
        statements = self._statements(persona)
        constraints = statements[:2] or [persona]
        return OcImportPreviewDTO(
            draft_id=f"oc-import-{digest[:16]}",
            suggested_oc_id=f"oc-imported-{digest[:12]}",
            source=OcImportSource(
                source_name=source.source_name,
                content_hash=digest,
                excerpt=normalized[:240],
            ),
            roleplay_config=RoleplayConfig(
                display_name=display_name,
                role="无限公寓住客",
                persona=persona,
                public_style="只表达符合创作者原始设定且由自己掌握的信息",
            ),
            living_world_profile=LivingWorldProfileDraft(
                persona_constraints=constraints,
                goals=[f"按已确认设定推进：{constraints[0]}"],
                initial_memories=[],
                home_location_id="mirror-curtain",
                daily_location_preferences=[
                    "apartment-library",
                    "apartment-bar",
                    "mirror-curtain",
                ],
            ),
            rpg_stats=RpgStats(),
            compiler_id=self.compiler_id,
            audit_notices=[
                "这是待确认草稿，不会进入 Canon 或 Day Loop。",
                "系统只整理创作者提供的内容；请在注册前确认或修改字段。",
            ],
        )

    @staticmethod
    def _display_name(source_name: str, first_line: str) -> str:
        if len(first_line) <= 80:
            return first_line
        return Path(source_name).stem[:80] or "未命名 OC"

    @staticmethod
    def _statements(persona: str) -> list[str]:
        return [
            statement.strip()
            for statement in re.split(r"[\n。！？!?]+", persona)
            if statement.strip()
        ]


def register_confirmed_oc(
    draft: OcImportPreviewDTO,
    confirmation: ConfirmOcImportRequest,
) -> RegisteredOcDTO:
    oc_id = draft.suggested_oc_id
    goals = [
        Goal(goal_id=f"goal-{oc_id}-{index}", text=text)
        for index, text in enumerate(
            confirmation.living_world_profile.goals,
            start=1,
        )
    ]
    character = Character(
        oc_id=oc_id,
        name=confirmation.roleplay_config.display_name,
        role=confirmation.roleplay_config.role,
        persona=confirmation.roleplay_config.persona,
        public_style=confirmation.roleplay_config.public_style,
        location_id=confirmation.living_world_profile.home_location_id,
        goals=goals,
        secrets=[],
        senses=["sight", "hearing"],
        relationships={},
    )
    runtime_profile = RuntimeActorProfile(
        oc_id=oc_id,
        persona_constraints=(
            confirmation.living_world_profile.persona_constraints
        ),
        goal_refs=[goal.goal_id for goal in goals],
        initial_memories=confirmation.living_world_profile.initial_memories,
        action_preferences=["WAIT", "UTTERANCE", "MOVE"],
        home_location_id=confirmation.living_world_profile.home_location_id,
        daily_location_preferences=(
            confirmation.living_world_profile.daily_location_preferences
        ),
        rpg_stats=confirmation.rpg_stats,
    )
    return RegisteredOcDTO(
        oc_id=oc_id,
        source=draft.source,
        character=character,
        runtime_profile=runtime_profile,
    )


class RuntimeBundleAssembler:
    """Adds confirmed OCs to a run-local copy of the preset bundle."""

    def assemble(
        self,
        base: RuntimeBundle,
        registered_ocs: list[RegisteredOcDTO],
        *,
        replacement: tuple[str, RegisteredOcDTO] | None = None,
    ) -> RuntimeBundle:
        bundle = base.model_copy(deep=True)
        additions = list(registered_ocs)
        if replacement is not None:
            replaced_actor_id, replacement_oc = replacement
            self._remove_actor(bundle, replaced_actor_id)
            for world_object in bundle.world.initial_state.objects.values():
                if world_object.holder_id == replaced_actor_id:
                    world_object.holder_id = replacement_oc.oc_id
            additions.insert(0, replacement_oc)
        known_locations = {
            location.location_id for location in bundle.world.locations
        }
        existing_ids = {
            profile.oc_id for profile in bundle.actor_profiles
        }
        for registered in additions:
            profile = registered.runtime_profile.model_copy(deep=True)
            character = registered.character.model_copy(deep=True)
            if profile.oc_id in existing_ids:
                raise DomainInvariantError("OC is already present in runtime bundle")
            requested_locations = {
                profile.home_location_id,
                *profile.daily_location_preferences,
            }
            if not requested_locations <= known_locations:
                raise DomainInvariantError(
                    "registered OC references an unknown runtime location"
                )
            neutral = Relationship(trust=0, affinity=0, tension=0)
            character.relationships = {}
            for existing_character in bundle.world.characters:
                existing_character.relationships[profile.oc_id] = neutral.model_copy()
                character.relationships[existing_character.oc_id] = neutral.model_copy()
                bundle.world.initial_state.relationships.setdefault(
                    existing_character.oc_id,
                    {},
                )[profile.oc_id] = neutral.model_copy()
                bundle.world.initial_state.relationships.setdefault(
                    profile.oc_id,
                    {},
                )[existing_character.oc_id] = neutral.model_copy()
            bundle.world.characters.append(character)
            bundle.world.initial_state.actor_locations[profile.oc_id] = (
                profile.home_location_id
            )
            bundle.actor_profiles.append(profile)
            existing_ids.add(profile.oc_id)
        suffix = "-".join(sorted(item.oc_id for item in additions))
        if suffix:
            bundle.bundle_id = f"{base.bundle_id}+{suffix}"
        return bundle

    @staticmethod
    def _remove_actor(bundle: RuntimeBundle, actor_id: str) -> None:
        if actor_id not in {
            profile.oc_id for profile in bundle.actor_profiles
        }:
            raise DomainInvariantError("runtime replacement actor does not exist")
        bundle.actor_profiles = [
            profile
            for profile in bundle.actor_profiles
            if profile.oc_id != actor_id
        ]
        bundle.world.characters = [
            character
            for character in bundle.world.characters
            if character.oc_id != actor_id
        ]
        bundle.world.initial_state.actor_locations.pop(actor_id, None)
        bundle.world.initial_state.relationships.pop(actor_id, None)
        for relationships in bundle.world.initial_state.relationships.values():
            relationships.pop(actor_id, None)
        for character in bundle.world.characters:
            character.relationships.pop(actor_id, None)

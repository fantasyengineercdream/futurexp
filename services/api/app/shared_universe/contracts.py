from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)


def _to_lower_camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part.capitalize() for part in tail)


def _uuid_string(value: str) -> str:
    UUID(value)
    return value


UuidString: TypeAlias = Annotated[str, AfterValidator(_uuid_string)]
JsonObject: TypeAlias = dict[str, Any]


class SharedContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_to_lower_camel,
        populate_by_name=True,
        extra="forbid",
    )


class OCIdentityV1(SharedContractModel):
    schema_version: Literal["oc.identity/v1"]
    oc_id: UuidString
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    created_at: AwareDatetime
    active_canon_revision_id: UuidString


class CanonRevisionV1(SharedContractModel):
    schema_version: Literal["oc.canon-revision/v1"]
    canon_revision_id: UuidString
    oc_id: UuidString
    revision: int = Field(ge=1)
    display_name: str = Field(min_length=1)
    public_profile: JsonObject
    created_at: AwareDatetime


class WorldInstanceV1(SharedContractModel):
    schema_version: Literal["world.instance/v1"]
    world_instance_id: UuidString
    world_definition_id: UuidString
    world_definition_version: str = Field(min_length=1)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    created_at: AwareDatetime


class CharacterPresenceV1(SharedContractModel):
    schema_version: Literal["character.presence/v1"]
    presence_id: UuidString
    world_instance_id: UuidString
    oc_id: UuidString
    canon_revision_id: UuidString
    status: Literal["invited", "admitted", "departed"]
    runtime_state_ref: str = Field(min_length=1)
    admitted_at: AwareDatetime | None = None
    departed_at: AwareDatetime | None = None


class CapabilityGrantV1(SharedContractModel):
    schema_version: Literal["capability.grant/v1"]
    grant_id: UuidString
    subject_principal_id: UuidString
    issuer_principal_id: UuidString
    world_instance_id: UuidString
    invitation_id: UuidString | None = None
    capabilities: list[str] = Field(min_length=1)
    policy_version: int = Field(ge=1)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_window(self) -> "CapabilityGrantV1":
        if self.expires_at <= self.issued_at:
            raise ValueError("expiresAt must be later than issuedAt")
        return self


class CapabilityRevocationV1(SharedContractModel):
    schema_version: Literal["capability.revocation/v1"]
    revocation_id: UuidString
    grant_id: UuidString
    revoked_by_principal_id: UuidString
    reason: str = Field(min_length=1)
    revoked_at: AwareDatetime


class InvitationV1(SharedContractModel):
    schema_version: Literal["invitation/v1"]
    invitation_id: UuidString
    world_instance_id: UuidString
    oc_id: UuidString
    invited_by_principal_id: UuidString
    invited_principal_id: UuidString
    status: Literal["pending", "accepted", "rejected", "expired", "revoked"]
    discovery_source: Literal["nfc", "qr", "link", "directory"]
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    accepted_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "InvitationV1":
        if self.expires_at <= self.issued_at:
            raise ValueError("expiresAt must be later than issuedAt")
        if self.status == "accepted" and self.accepted_at is None:
            raise ValueError("accepted invitations require acceptedAt")
        if self.status != "accepted" and self.accepted_at is not None:
            raise ValueError("only accepted invitations may have acceptedAt")
        return self


class PublicAudienceSelectorV1(SharedContractModel):
    kind: Literal["public"]


class WorldMembersAudienceSelectorV1(SharedContractModel):
    kind: Literal["world_members"]


class PrincipalsAudienceSelectorV1(SharedContractModel):
    kind: Literal["principals"]
    principal_ids: list[UuidString] = Field(min_length=1)


class CapabilityAudienceSelectorV1(SharedContractModel):
    kind: Literal["capability_holders"]
    capability: str = Field(min_length=1)


class NoneAudienceSelectorV1(SharedContractModel):
    kind: Literal["none"]


class LegacyDemoAudienceSelectorV1(SharedContractModel):
    kind: Literal["legacy_demo"]
    legacy_refs: list[str] = Field(min_length=1)


AudienceSelectorV1: TypeAlias = Annotated[
    PublicAudienceSelectorV1
    | WorldMembersAudienceSelectorV1
    | PrincipalsAudienceSelectorV1
    | CapabilityAudienceSelectorV1
    | NoneAudienceSelectorV1
    | LegacyDemoAudienceSelectorV1,
    Field(discriminator="kind"),
]


class ProjectionPolicyV1(SharedContractModel):
    schema_version: Literal["projection.policy/v1"]
    policy_version: int = Field(ge=1)
    sensitivity: Literal[
        "public",
        "member",
        "confidential",
        "restricted",
        "private",
    ]
    data_class: Literal[
        "world_event",
        "world_observation",
        "portable_memory",
        "private_os",
        "operator_diagnostic",
    ]
    audience_selector: AudienceSelectorV1
    grant_refs: list[UuidString]
    compatibility_mode: Literal["demo-v1"] | None = None

    @model_validator(mode="after")
    def validate_compatibility_mode(self) -> "ProjectionPolicyV1":
        is_legacy = self.audience_selector.kind == "legacy_demo"
        if is_legacy != (self.compatibility_mode == "demo-v1"):
            raise ValueError(
                "legacy_demo audience and demo-v1 compatibility mode must be paired"
            )
        if (
            self.audience_selector.kind == "public"
            and self.sensitivity != "public"
        ):
            raise ValueError("public audience requires public sensitivity")
        if self.data_class == "private_os":
            if self.sensitivity != "private":
                raise ValueError("private OS requires private sensitivity")
            if self.audience_selector.kind != "principals":
                raise ValueError("private OS requires an explicit principal audience")
            if not self.grant_refs:
                raise ValueError("private OS requires at least one grant reference")
        return self


class SharedEventEnvelopeV1(SharedContractModel):
    schema_version: Literal["shared.event/v1"]
    event_id: UuidString
    world_instance_id: UuidString
    sequence: int = Field(ge=1)
    occurred_at: AwareDatetime
    type: str = Field(min_length=1)
    subject_oc_id: UuidString | None = None
    projection_policy: ProjectionPolicyV1
    capability_version: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    cancellation_key: str | None = None
    causation_id: UuidString | None = None
    payload: JsonObject


class PortableMemorySummaryV1(SharedContractModel):
    schema_version: Literal["portable-memory.summary/v1"]
    memory_summary_id: UuidString
    oc_id: UuidString
    source_world_instance_id: UuidString
    source_event_ids: list[UuidString] = Field(min_length=1)
    summary: str = Field(min_length=1)
    approved_by_principal_id: UuidString
    created_at: AwareDatetime


def adapt_legacy_visibility(visibility: dict[str, Any]) -> ProjectionPolicyV1:
    """Map the local v1 Demo scope without granting network authority."""

    scope = visibility.get("scope")
    if scope == "public":
        selector: dict[str, Any] = {
            "kind": "legacy_demo",
            "legacyRefs": ["public"],
        }
        sensitivity = "public"
    elif scope in {"owner", "actor"} and isinstance(visibility.get("ocId"), str):
        selector = {
            "kind": "legacy_demo",
            "legacyRefs": [f"{scope}:{visibility['ocId']}"],
        }
        sensitivity = "private"
    elif scope == "tech":
        selector = {
            "kind": "legacy_demo",
            "legacyRefs": ["tech"],
        }
        sensitivity = "restricted"
    else:
        raise ValueError("unsupported legacy Demo visibility")

    return ProjectionPolicyV1.model_validate(
        {
            "schemaVersion": "projection.policy/v1",
            "policyVersion": 1,
            "sensitivity": sensitivity,
            "dataClass": (
                "operator_diagnostic" if scope == "tech" else "world_event"
            ),
            "audienceSelector": selector,
            "grantRefs": [],
            "compatibilityMode": "demo-v1",
        }
    )

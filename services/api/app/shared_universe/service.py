from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

from app.shared_universe.contracts import (
    CapabilityGrantV1,
    CapabilityRevocationV1,
    CharacterPresenceV1,
    InvitationV1,
    SharedEventEnvelopeV1,
)


class AccessDenied(RuntimeError):
    pass


@dataclass(frozen=True)
class PrincipalContext:
    principal_id: str
    roles: set[Literal["public", "member", "owner", "operator", "tech"]]


@dataclass(frozen=True)
class DiscoveryReceipt:
    discovery_id: str
    oc_id: str
    world_instance_id: str
    source: Literal["nfc", "qr", "link", "directory"]
    source_ref: str
    discovered_at: datetime


class InMemorySharedUniverse:
    """Testable policy boundary; persistence and HTTP transport are future adapters."""

    def __init__(self) -> None:
        self._discoveries: dict[str, DiscoveryReceipt] = {}
        self._invitations: dict[str, InvitationV1] = {}
        self._presences: dict[tuple[str, str], CharacterPresenceV1] = {}
        self._grants: dict[str, CapabilityGrantV1] = {}
        self._revocations: dict[str, CapabilityRevocationV1] = {}

    def discover(
        self,
        *,
        oc_id: str,
        world_instance_id: str,
        source: Literal["nfc", "qr", "link", "directory"],
        source_ref: str,
        discovered_at: datetime,
    ) -> DiscoveryReceipt:
        receipt = DiscoveryReceipt(
            discovery_id=str(uuid4()),
            oc_id=oc_id,
            world_instance_id=world_instance_id,
            source=source,
            source_ref=source_ref,
            discovered_at=discovered_at,
        )
        self._discoveries[receipt.discovery_id] = receipt
        return receipt

    def invite(
        self,
        *,
        discovery_id: str,
        invited_by_principal_id: str,
        invited_principal_id: str,
        expires_at: datetime,
    ) -> InvitationV1:
        discovery = self._discoveries[discovery_id]
        invitation = InvitationV1(
            schema_version="invitation/v1",
            invitation_id=str(uuid4()),
            world_instance_id=discovery.world_instance_id,
            oc_id=discovery.oc_id,
            invited_by_principal_id=invited_by_principal_id,
            invited_principal_id=invited_principal_id,
            status="pending",
            discovery_source=discovery.source,
            issued_at=discovery.discovered_at,
            expires_at=expires_at,
        )
        self._invitations[invitation.invitation_id] = invitation
        return invitation

    def accept_invitation(
        self,
        invitation_id: str,
        *,
        accepted_by_principal_id: str,
        canon_revision_id: str,
        accepted_at: datetime,
    ) -> CharacterPresenceV1:
        invitation = self._invitations[invitation_id]
        if invitation.status != "pending":
            raise AccessDenied("invitation is not pending")
        if accepted_by_principal_id != invitation.invited_principal_id:
            raise AccessDenied("invitation is bound to a different intended principal")
        if accepted_at >= invitation.expires_at:
            raise AccessDenied("invitation has expired")

        accepted = invitation.model_copy(
            update={"status": "accepted", "accepted_at": accepted_at}
        )
        self._invitations[invitation_id] = accepted
        presence_id = str(uuid4())
        presence = CharacterPresenceV1(
            schema_version="character.presence/v1",
            presence_id=presence_id,
            world_instance_id=accepted.world_instance_id,
            oc_id=accepted.oc_id,
            canon_revision_id=canon_revision_id,
            status="admitted",
            runtime_state_ref=(
                f"world://{accepted.world_instance_id}/presence/{presence_id}"
            ),
            admitted_at=accepted_at,
        )
        self._presences[
            (presence.oc_id, presence.world_instance_id)
        ] = presence
        return presence

    def issue_grant(
        self,
        *,
        invitation_id: str,
        issuer_principal_id: str,
        subject_principal_id: str,
        capabilities: list[str],
        expires_at: datetime,
        issued_at: datetime,
    ) -> CapabilityGrantV1:
        invitation = self._invitations[invitation_id]
        if invitation.status != "accepted":
            raise AccessDenied("grant requires an accepted invitation")
        if issuer_principal_id != invitation.invited_by_principal_id:
            raise AccessDenied("grant must be issued by the inviting operator")
        if subject_principal_id != invitation.invited_principal_id:
            raise AccessDenied("grant subject must be the invited principal")
        return self._register_grant(
            subject_principal_id=subject_principal_id,
            issuer_principal_id=issuer_principal_id,
            world_instance_id=invitation.world_instance_id,
            invitation_id=invitation_id,
            capabilities=capabilities,
            issued_at=issued_at,
            expires_at=expires_at,
        )

    def _register_grant(
        self,
        *,
        subject_principal_id: str,
        issuer_principal_id: str,
        world_instance_id: str,
        invitation_id: str | None,
        capabilities: list[str],
        issued_at: datetime,
        expires_at: datetime,
    ) -> CapabilityGrantV1:
        grant = CapabilityGrantV1(
            schema_version="capability.grant/v1",
            grant_id=str(uuid4()),
            subject_principal_id=subject_principal_id,
            issuer_principal_id=issuer_principal_id,
            world_instance_id=world_instance_id,
            invitation_id=invitation_id,
            capabilities=capabilities,
            policy_version=1,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        self._grants[grant.grant_id] = grant
        return grant

    def revoke_grant(
        self,
        grant_id: str,
        *,
        revoked_by_principal_id: str,
        reason: str,
        revoked_at: datetime,
    ) -> CapabilityRevocationV1:
        if grant_id not in self._grants:
            raise KeyError(grant_id)
        grant = self._grants[grant_id]
        if revoked_by_principal_id != grant.issuer_principal_id:
            raise AccessDenied("revocation requires the grant issuer")
        revocation = CapabilityRevocationV1(
            schema_version="capability.revocation/v1",
            revocation_id=str(uuid4()),
            grant_id=grant_id,
            revoked_by_principal_id=revoked_by_principal_id,
            reason=reason,
            revoked_at=revoked_at,
        )
        self._revocations[grant_id] = revocation
        return revocation

    def active_grants_for(
        self,
        principal_id: str,
        *,
        at: datetime | None = None,
    ) -> list[CapabilityGrantV1]:
        grants = [
            grant
            for grant in self._grants.values()
            if grant.subject_principal_id == principal_id
            and grant.grant_id not in self._revocations
        ]
        if at is not None:
            grants = [
                grant
                for grant in grants
                if grant.issued_at <= at < grant.expires_at
            ]
        return grants

    def is_admitted(self, oc_id: str, world_instance_id: str) -> bool:
        return (oc_id, world_instance_id) in self._presences

    def grant_authorizes(
        self,
        grant: CapabilityGrantV1,
        capability: str,
        *,
        at: datetime,
    ) -> bool:
        return (
            grant.grant_id not in self._revocations
            and grant.issued_at <= at < grant.expires_at
            and capability in grant.capabilities
        )

    def project_for(
        self,
        event: SharedEventEnvelopeV1,
        principal: PrincipalContext,
        *,
        at: datetime,
    ) -> dict | None:
        policy = event.projection_policy
        if policy.compatibility_mode == "demo-v1":
            raise AccessDenied(
                "legacy visibility is local Demo compatibility only"
            )
        if policy.data_class == "private_os":
            return self._project_private_os(event, principal, at=at)

        selector = policy.audience_selector
        allowed = selector.kind == "public"
        if selector.kind == "principals":
            allowed = principal.principal_id in selector.principal_ids
        elif selector.kind == "world_members":
            allowed = "member" in principal.roles
        elif selector.kind == "capability_holders":
            allowed = any(
                grant.grant_id in policy.grant_refs
                and grant.world_instance_id == event.world_instance_id
                and self.grant_authorizes(grant, selector.capability, at=at)
                for grant in self.active_grants_for(principal.principal_id, at=at)
            )
        if not allowed:
            return None
        return deepcopy(
            event.model_dump(by_alias=True, mode="json", exclude_none=True)
        )

    def _project_private_os(
        self,
        event: SharedEventEnvelopeV1,
        principal: PrincipalContext,
        *,
        at: datetime,
    ) -> dict | None:
        selector = event.projection_policy.audience_selector
        if selector.kind != "principals":
            return None
        if principal.principal_id not in selector.principal_ids:
            return None
        authorized = any(
            grant.grant_id in event.projection_policy.grant_refs
            and grant.world_instance_id == event.world_instance_id
            and self.grant_authorizes(grant, "private_os:read", at=at)
            for grant in self.active_grants_for(principal.principal_id, at=at)
        )
        if not authorized:
            return None
        return deepcopy(
            event.model_dump(by_alias=True, mode="json", exclude_none=True)
        )

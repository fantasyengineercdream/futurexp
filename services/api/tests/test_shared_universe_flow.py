from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.shared_universe.contracts import (
    CapabilityGrantV1,
    ProjectionPolicyV1,
    SharedEventEnvelopeV1,
)
from app.shared_universe.service import (
    AccessDenied,
    InMemorySharedUniverse,
    PrincipalContext,
)


def uid() -> str:
    return str(uuid4())


def test_discovery_invitation_grant_projection_and_revocation_flow() -> None:
    service = InMemorySharedUniverse()
    now = datetime.now(UTC)
    oc_id = uid()
    owner_principal_id = uid()
    operator_principal_id = uid()
    world_instance_id = uid()

    discovery = service.discover(
        oc_id=oc_id,
        world_instance_id=world_instance_id,
        source="nfc",
        source_ref="tag:atrium-door",
        discovered_at=now,
    )
    assert discovery.source == "nfc"
    assert service.is_admitted(oc_id, world_instance_id) is False
    assert service.active_grants_for(owner_principal_id) == []

    invitation = service.invite(
        discovery_id=discovery.discovery_id,
        invited_by_principal_id=operator_principal_id,
        invited_principal_id=owner_principal_id,
        expires_at=now + timedelta(minutes=10),
    )
    presence = service.accept_invitation(
        invitation.invitation_id,
        accepted_by_principal_id=owner_principal_id,
        canon_revision_id=uid(),
        accepted_at=now + timedelta(seconds=1),
    )
    grant = service.issue_grant(
        invitation_id=invitation.invitation_id,
        issuer_principal_id=operator_principal_id,
        subject_principal_id=owner_principal_id,
        capabilities=["event:read"],
        expires_at=now + timedelta(minutes=5),
        issued_at=now + timedelta(seconds=2),
    )
    event = SharedEventEnvelopeV1(
        schema_version="shared.event/v1",
        event_id=uid(),
        world_instance_id=world_instance_id,
        sequence=1,
        occurred_at=now + timedelta(seconds=3),
        type="world.observation.created",
        subject_oc_id=oc_id,
        projection_policy=ProjectionPolicyV1(
            schema_version="projection.policy/v1",
            policy_version=1,
            sensitivity="member",
            data_class="world_observation",
            audience_selector={
                "kind": "capability_holders",
                "capability": "event:read",
            },
            grant_refs=[grant.grant_id],
        ),
        capability_version="1",
        idempotency_key="observation-1",
        payload={"observed": "a red door opened"},
    )

    projected = service.project_for(
        event,
        PrincipalContext(
            principal_id=owner_principal_id,
            roles={"owner"},
        ),
        at=now + timedelta(seconds=4),
    )
    assert projected is not None
    assert projected["payload"] == {"observed": "a red door opened"}
    assert presence.world_instance_id == world_instance_id

    service.revoke_grant(
        grant.grant_id,
        revoked_by_principal_id=operator_principal_id,
        reason="invitation withdrawn",
        revoked_at=now + timedelta(seconds=5),
    )

    assert (
        service.project_for(
            event,
            PrincipalContext(
                principal_id=owner_principal_id,
                roles={"owner"},
            ),
            at=now + timedelta(seconds=6),
        )
        is None
    )


@pytest.mark.parametrize("role", ["public", "member", "operator", "tech"])
def test_private_os_is_default_deny_for_non_owner_audiences(role: str) -> None:
    service = InMemorySharedUniverse()
    principal_id = uid()
    now = datetime.now(UTC)
    event = SharedEventEnvelopeV1(
        schema_version="shared.event/v1",
        event_id=uid(),
        world_instance_id=uid(),
        sequence=1,
        occurred_at=now,
        type="character.private-os.created",
        subject_oc_id=uid(),
        projection_policy=ProjectionPolicyV1(
            schema_version="projection.policy/v1",
            policy_version=1,
            sensitivity="private",
            data_class="private_os",
            audience_selector={"kind": "principals", "principalIds": [uid()]},
            grant_refs=[uid()],
        ),
        capability_version="1",
        idempotency_key=f"private-os-{role}",
        payload={"text": "I am afraid."},
    )

    assert (
        service.project_for(
            event,
            PrincipalContext(principal_id=principal_id, roles={role}),
            at=now,
        )
        is None
    )


def test_owner_operator_and_platform_tech_capabilities_do_not_inherit() -> None:
    service = InMemorySharedUniverse()
    now = datetime.now(UTC)
    principal_id = uid()
    grant = CapabilityGrantV1(
        schema_version="capability.grant/v1",
        grant_id=uid(),
        subject_principal_id=principal_id,
        issuer_principal_id=uid(),
        world_instance_id=uid(),
        capabilities=["world:operate"],
        policy_version=1,
        issued_at=now,
        expires_at=now + timedelta(minutes=1),
    )

    assert service.grant_authorizes(grant, "world:operate", at=now)
    assert not service.grant_authorizes(grant, "oc:owner", at=now)
    assert not service.grant_authorizes(grant, "platform:diagnose", at=now)


def test_network_projection_rejects_legacy_demo_policy() -> None:
    from app.shared_universe.contracts import adapt_legacy_visibility

    now = datetime.now(UTC)
    event = SharedEventEnvelopeV1(
        schema_version="shared.event/v1",
        event_id=uid(),
        world_instance_id=uid(),
        sequence=1,
        occurred_at=now,
        type="legacy.demo.event",
        projection_policy=adapt_legacy_visibility({"scope": "public"}),
        capability_version="1",
        idempotency_key="legacy-public-1",
        payload={},
    )

    with pytest.raises(AccessDenied, match="local Demo"):
        InMemorySharedUniverse().project_for(
            event,
            PrincipalContext(principal_id=uid(), roles={"public"}),
            at=now,
        )


def test_projection_returns_a_copy_before_serialization() -> None:
    service = InMemorySharedUniverse()
    now = datetime.now(UTC)
    event = SharedEventEnvelopeV1(
        schema_version="shared.event/v1",
        event_id=uid(),
        world_instance_id=uid(),
        sequence=1,
        occurred_at=now,
        type="public.notice",
        projection_policy=ProjectionPolicyV1(
            schema_version="projection.policy/v1",
            policy_version=1,
            sensitivity="public",
            data_class="world_event",
            audience_selector={"kind": "public"},
            grant_refs=[],
        ),
        capability_version="1",
        idempotency_key="notice-1",
        payload={"text": "hello"},
    )

    projected = service.project_for(
        event,
        PrincipalContext(principal_id=uid(), roles={"public"}),
        at=now,
    )
    assert projected is not None
    projected["payload"]["text"] = "tampered"
    assert event.payload == {"text": "hello"}


def test_invitation_id_does_not_authorize_a_different_principal() -> None:
    service = InMemorySharedUniverse()
    now = datetime.now(UTC)
    intended_principal_id = uid()
    discovery = service.discover(
        oc_id=uid(),
        world_instance_id=uid(),
        source="link",
        source_ref="invite-preview",
        discovered_at=now,
    )
    invitation = service.invite(
        discovery_id=discovery.discovery_id,
        invited_by_principal_id=uid(),
        invited_principal_id=intended_principal_id,
        expires_at=now + timedelta(minutes=10),
    )

    with pytest.raises(AccessDenied, match="intended principal"):
        service.accept_invitation(
            invitation.invitation_id,
            accepted_by_principal_id=uid(),
            canon_revision_id=uid(),
            accepted_at=now + timedelta(seconds=1),
        )


def test_only_inviting_operator_can_issue_or_revoke_the_grant() -> None:
    service = InMemorySharedUniverse()
    now = datetime.now(UTC)
    operator_principal_id = uid()
    owner_principal_id = uid()
    discovery = service.discover(
        oc_id=uid(),
        world_instance_id=uid(),
        source="directory",
        source_ref="world-directory",
        discovered_at=now,
    )
    invitation = service.invite(
        discovery_id=discovery.discovery_id,
        invited_by_principal_id=operator_principal_id,
        invited_principal_id=owner_principal_id,
        expires_at=now + timedelta(minutes=10),
    )
    service.accept_invitation(
        invitation.invitation_id,
        accepted_by_principal_id=owner_principal_id,
        canon_revision_id=uid(),
        accepted_at=now + timedelta(seconds=1),
    )

    with pytest.raises(AccessDenied, match="inviting operator"):
        service.issue_grant(
            invitation_id=invitation.invitation_id,
            issuer_principal_id=uid(),
            subject_principal_id=owner_principal_id,
            capabilities=["event:read"],
            issued_at=now + timedelta(seconds=2),
            expires_at=now + timedelta(minutes=5),
        )

    grant = service.issue_grant(
        invitation_id=invitation.invitation_id,
        issuer_principal_id=operator_principal_id,
        subject_principal_id=owner_principal_id,
        capabilities=["event:read"],
        issued_at=now + timedelta(seconds=2),
        expires_at=now + timedelta(minutes=5),
    )
    with pytest.raises(AccessDenied, match="grant issuer"):
        service.revoke_grant(
            grant.grant_id,
            revoked_by_principal_id=uid(),
            reason="not authorized",
            revoked_at=now + timedelta(seconds=3),
        )

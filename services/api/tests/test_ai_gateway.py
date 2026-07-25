from __future__ import annotations

from uuid import uuid4

import pytest

from app.shared_universe.ai_gateway import (
    AiRequestV1,
    DeterministicFallbackGateway,
    FallbackAiGateway,
    RemoteUnavailable,
)


class UnavailableGateway:
    def __init__(self, code: str) -> None:
        self.code = code
        self.requests: list[AiRequestV1] = []

    def generate(self, request: AiRequestV1):
        self.requests.append(request)
        raise RemoteUnavailable(self.code)


@pytest.mark.parametrize("code", ["403", "insufficient_balance"])
def test_remote_authorization_or_balance_failure_uses_deterministic_fallback(
    code: str,
) -> None:
    remote = UnavailableGateway(code)
    gateway = FallbackAiGateway(
        remote=remote,
        fallback=DeterministicFallbackGateway(),
    )
    request = AiRequestV1(
        schema_version="ai.request/v1",
        request_id=str(uuid4()),
        capability="character.dialogue",
        capability_version="1",
        idempotency_key="dialogue-tick-7",
        cancellation_key="session-cancel-1",
        input={"promptClass": "greeting", "actor": "Mira"},
    )

    first = gateway.generate(request)
    second = gateway.generate(request)

    assert first.status == "fallback"
    assert first.remote_error_code == code
    assert first.output == second.output
    assert remote.requests == [request]


def test_ai_request_preserves_a2a_mappable_boundary_fields() -> None:
    request = AiRequestV1(
        schema_version="ai.request/v1",
        request_id=str(uuid4()),
        capability="character.dialogue",
        capability_version="2026-07",
        idempotency_key="request-42",
        cancellation_key="cancel-42",
        input={},
    )

    assert request.capability == "character.dialogue"
    assert request.capability_version == "2026-07"
    assert request.idempotency_key == "request-42"
    assert request.cancellation_key == "cancel-42"

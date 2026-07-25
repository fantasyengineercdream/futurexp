from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Protocol

from pydantic import Field

from app.shared_universe.contracts import SharedContractModel, UuidString


class AiRequestV1(SharedContractModel):
    schema_version: Literal["ai.request/v1"]
    request_id: UuidString
    capability: str = Field(min_length=1)
    capability_version: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    cancellation_key: str | None = None
    input: dict[str, Any]


class AiResultV1(SharedContractModel):
    schema_version: Literal["ai.result/v1"] = "ai.result/v1"
    status: Literal["remote", "fallback"]
    output: dict[str, Any]
    remote_error_code: str | None = None


class AiGateway(Protocol):
    def generate(self, request: AiRequestV1) -> AiResultV1: ...


class RemoteUnavailable(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(f"remote AI unavailable: {code}")
        self.code = code


class DeterministicFallbackGateway:
    def generate(self, request: AiRequestV1) -> AiResultV1:
        canonical = json.dumps(
            {
                "capability": request.capability,
                "capabilityVersion": request.capability_version,
                "idempotencyKey": request.idempotency_key,
                "input": request.input,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return AiResultV1(
            status="fallback",
            output={
                "kind": "deterministic_fallback",
                "fingerprint": digest[:16],
            },
        )


class FallbackAiGateway:
    """Remote adapter wrapper that never reads credentials itself."""

    def __init__(self, *, remote: AiGateway, fallback: AiGateway) -> None:
        self._remote = remote
        self._fallback = fallback
        self._results: dict[str, AiResultV1] = {}

    def generate(self, request: AiRequestV1) -> AiResultV1:
        if request.idempotency_key in self._results:
            return self._results[request.idempotency_key]
        try:
            result = self._remote.generate(request)
        except RemoteUnavailable as error:
            fallback = self._fallback.generate(request)
            result = fallback.model_copy(
                update={"remote_error_code": error.code}
            )
        self._results[request.idempotency_key] = result
        return result

from __future__ import annotations

import asyncio
from typing import Protocol

from .models import DisplayAck, SceneTask


class DisplayTransport(Protocol):
    async def send_task(self, task: SceneTask) -> None: ...

    async def wait_for_ack(
        self, task_id: str, timeout: float
    ) -> DisplayAck | None: ...


class MockDisplayTransport:
    """In-memory display adapter used by demos and hardware conformance tests."""

    def __init__(
        self,
        auto_ack: bool = False,
        auto_ack_status: str = "accepted",
    ):
        self.sent: list[SceneTask] = []
        self.auto_ack = auto_ack
        self.auto_ack_status = auto_ack_status

    async def send_task(self, task: SceneTask) -> None:
        self.sent.append(task)

    async def wait_for_ack(
        self, task_id: str, timeout: float
    ) -> DisplayAck | None:
        if self.auto_ack:
            return DisplayAck.from_dict(
                {
                    "version": 1,
                    "task_id": task_id,
                    "status": self.auto_ack_status,
                }
            )
        await asyncio.sleep(timeout)
        return None

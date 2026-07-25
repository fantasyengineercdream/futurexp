from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

from .models import DisplayAck, SceneTask
from .transports import DisplayTransport


class DisplayTaskOrchestrator:
    def __init__(
        self,
        transport: DisplayTransport,
        *,
        ack_timeout: float = 0.5,
        clock: Callable[[], datetime] | None = None,
    ):
        self.transport = transport
        self.ack_timeout = ack_timeout
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._queue: asyncio.PriorityQueue[
            tuple[int, str, str, SceneTask]
        ] = asyncio.PriorityQueue()
        self._submitted_ids: set[str] = set()
        self._acks: dict[str, DisplayAck] = {}
        self._busy = False
        self._lock = asyncio.Lock()

    async def submit(self, task: SceneTask) -> bool:
        async with self._lock:
            if task.task_id in self._submitted_ids:
                return False
            if task.interrupt == "ignore" and (
                self._busy or not self._queue.empty()
            ):
                return False
            self._submitted_ids.add(task.task_id)
            await self._queue.put(
                (-task.priority, task.created_at, task.task_id, task)
            )
            return True

    def ack_for(self, task_id: str) -> DisplayAck | None:
        return self._acks.get(task_id)

    def _is_expired(self, task: SceneTask) -> bool:
        created_at = datetime.fromisoformat(
            task.created_at.replace("Z", "+00:00")
        )
        age_ms = (self._clock() - created_at).total_seconds() * 1000
        return age_ms > task.ttl_ms

    async def drain_once(self) -> DisplayAck | None:
        if self._queue.empty():
            return None
        _, _, _, task = await self._queue.get()
        try:
            if self._is_expired(task):
                return None
            self._busy = True
            await self.transport.send_task(task)
            ack = await self.transport.wait_for_ack(
                task.task_id, self.ack_timeout
            )
            if ack is None:
                await self.transport.send_task(task)
                ack = await self.transport.wait_for_ack(
                    task.task_id, self.ack_timeout
                )
            if ack is not None:
                self._acks[task.task_id] = ack
            return ack
        finally:
            self._busy = False
            self._queue.task_done()

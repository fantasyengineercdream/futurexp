from datetime import datetime, timedelta, timezone

import pytest

from oc_gateway.display import DisplayTaskOrchestrator
from oc_gateway.models import SceneTask
from oc_gateway.transports import MockDisplayTransport


def task(
    task_id: str,
    priority: int,
    *,
    age_ms: int = 0,
    interrupt: str = "queue",
) -> SceneTask:
    created = datetime.now(timezone.utc) - timedelta(milliseconds=age_ms)
    return SceneTask.from_dict(
        {
            "version": 1,
            "task_id": task_id,
            "type": "scene.render",
            "priority": priority,
            "ttl_ms": 1_000,
            "interrupt": interrupt,
            "duration_ms": 100,
            "created_at": created.isoformat(),
            "scene": {
                "text": {"content": task_id, "style": "default"}
            },
        }
    )


@pytest.mark.asyncio
async def test_sends_higher_priority_first_and_deduplicates():
    transport = MockDisplayTransport(auto_ack=True)
    orchestrator = DisplayTaskOrchestrator(transport)
    assert await orchestrator.submit(task("low", 10)) is True
    assert await orchestrator.submit(task("high", 90)) is True
    assert await orchestrator.submit(task("high", 90)) is False
    await orchestrator.drain_once()
    await orchestrator.drain_once()
    assert [item.task_id for item in transport.sent] == ["high", "low"]


@pytest.mark.asyncio
async def test_drops_expired_task():
    transport = MockDisplayTransport()
    orchestrator = DisplayTaskOrchestrator(transport)
    await orchestrator.submit(task("expired", 50, age_ms=2_000))
    await orchestrator.drain_once()
    assert transport.sent == []


@pytest.mark.asyncio
async def test_retries_once_when_accepted_ack_is_missing():
    transport = MockDisplayTransport()
    orchestrator = DisplayTaskOrchestrator(transport, ack_timeout=0.001)
    await orchestrator.submit(task("retry", 50))
    ack = await orchestrator.drain_once()
    assert ack is None
    assert [item.task_id for item in transport.sent] == ["retry", "retry"]


@pytest.mark.asyncio
async def test_ignore_policy_drops_task_when_work_is_pending():
    transport = MockDisplayTransport(auto_ack=True)
    orchestrator = DisplayTaskOrchestrator(transport)
    await orchestrator.submit(task("existing", 50))
    accepted = await orchestrator.submit(task("ignored", 100, interrupt="ignore"))
    assert accepted is False
    await orchestrator.drain_once()
    assert [item.task_id for item in transport.sent] == ["existing"]


@pytest.mark.asyncio
async def test_records_received_ack_by_task_id():
    transport = MockDisplayTransport(auto_ack=True)
    orchestrator = DisplayTaskOrchestrator(transport)
    await orchestrator.submit(task("done", 50))
    ack = await orchestrator.drain_once()
    assert ack is not None
    assert ack.task_id == "done"
    assert orchestrator.ack_for("done") == ack

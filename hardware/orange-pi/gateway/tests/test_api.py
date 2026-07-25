from datetime import datetime, timezone

from aiohttp.test_utils import TestClient, TestServer
import pytest

from oc_gateway.api import PC_SINK_KEY, create_app
from oc_gateway.audio import PcmFrame
from oc_gateway.cli import build_parser, task_from_args
from oc_gateway.display import DisplayTaskOrchestrator
from oc_gateway.transports import MockDisplayTransport


def payload(task_id: str = "api-001") -> dict:
    return {
        "version": 1,
        "task_id": task_id,
        "type": "scene.render",
        "priority": 50,
        "ttl_ms": 10_000,
        "interrupt": "replace",
        "duration_ms": 5_000,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scene": {"text": {"content": "测试", "style": "default"}},
    }


@pytest.mark.asyncio
async def test_health_reports_protocol_version():
    app = create_app(DisplayTaskOrchestrator(MockDisplayTransport()))
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/health")
        assert response.status == 200
        assert await response.json() == {"status": "ok", "protocol": 1}


@pytest.mark.asyncio
async def test_post_display_task_returns_accepted_then_duplicate():
    app = create_app(DisplayTaskOrchestrator(MockDisplayTransport(auto_ack=True)))
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/display/tasks", json=payload())
        assert response.status == 202
        assert await response.json() == {
            "task_id": "api-001",
            "status": "accepted",
        }
        response = await client.post("/v1/display/tasks", json=payload())
        assert response.status == 200
        assert (await response.json())["status"] == "duplicate"


@pytest.mark.asyncio
async def test_rejects_fifth_task_shape():
    app = create_app(DisplayTaskOrchestrator(MockDisplayTransport()))
    invalid = payload("bad")
    invalid["scene"] = {
        "text": {"content": "x", "style": "default"},
        "image": {"asset_id": "x", "asset_version": 1},
    }
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/display/tasks", json=invalid)
        assert response.status == 400


@pytest.mark.asyncio
async def test_reads_final_display_ack_by_task_id():
    transport = MockDisplayTransport(
        auto_ack=True, auto_ack_status="completed"
    )
    orchestrator = DisplayTaskOrchestrator(transport)
    app = create_app(orchestrator)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/display/tasks", json=payload())
        assert response.status == 202
        await orchestrator.drain_once()
        response = await client.get("/v1/display/tasks/api-001")
        assert response.status == 200
        assert await response.json() == {
            "version": 1,
            "task_id": "api-001",
            "status": "completed",
            "error_code": None,
        }


@pytest.mark.parametrize(
    ("argv", "expected_scene"),
    [
        (
            ["text", "主人，该喝水了", "--style", "devil_reminder"],
            {
                "text": {
                    "content": "主人，该喝水了",
                    "style": "devil_reminder",
                }
            },
        ),
        (
            ["animation", "devil_thinking", "--loop", "2"],
            {
                "animation": {
                    "asset_id": "devil_thinking",
                    "asset_version": 1,
                    "loop": 2,
                }
            },
        ),
        (
            ["image", "devil_low_battery"],
            {
                "image": {
                    "asset_id": "devil_low_battery",
                    "asset_version": 1,
                }
            },
        ),
        (
            [
                "scene",
                "我在想啦",
                "devil_thinking",
                "--style",
                "devil_thinking",
            ],
            {
                "text": {
                    "content": "我在想啦",
                    "style": "devil_thinking",
                },
                "animation": {
                    "asset_id": "devil_thinking",
                    "asset_version": 1,
                    "loop": 1,
                },
            },
        ),
    ],
)
def test_cli_builds_only_the_four_supported_scene_shapes(argv, expected_scene):
    args = build_parser().parse_args(argv)
    assert task_from_args(args).scene == expected_scene


@pytest.mark.asyncio
async def test_serves_pc_speaker_console():
    app = create_app(DisplayTaskOrchestrator(MockDisplayTransport()))
    async with TestClient(TestServer(app)) as client:
        response = await client.get("/speaker/")
        assert response.status == 200
        assert "OC Speaker Sink" in await response.text()
        script = await client.get("/speaker/speaker.js")
        assert script.status == 200
        script_text = await script.text()
        assert "session.busy" in script_text
        assert "戒指正在被其他页面使用" in script_text


@pytest.mark.asyncio
async def test_pc_speaker_sink_sends_pcm_and_clear_to_owner():
    app = create_app(DisplayTaskOrchestrator(MockDisplayTransport()))
    sink = app[PC_SINK_KEY]
    async with TestClient(TestServer(app)) as client:
        socket = await client.ws_connect("/v1/audio-sink")
        assert (await socket.receive_json(timeout=1))["type"] == "session.ready"
        await sink.play(PcmFrame(b"\x01\x02"))
        audio = await socket.receive(timeout=1)
        assert audio.data == b"\x01\x02"
        await sink.clear()
        clear = await socket.receive_json(timeout=1)
        assert clear == {"type": "playback.clear"}
        await sink.state("thinking")
        assert await socket.receive_json(timeout=1) == {
            "type": "state",
            "phase": "thinking",
        }
        await sink.transcript("assistant", "欢迎回来")
        assert await socket.receive_json(timeout=1) == {
            "type": "transcript",
            "role": "assistant",
            "text": "欢迎回来",
        }
        await socket.close()


@pytest.mark.asyncio
async def test_ring_sink_grants_one_owner_and_reports_busy_until_release():
    app = create_app(DisplayTaskOrchestrator(MockDisplayTransport()))
    async with TestClient(TestServer(app)) as client:
        owner = await client.ws_connect("/v1/audio-sink")
        assert await owner.receive_json(timeout=1) == {
            "type": "session.ready",
            "status": "acquired",
        }

        contender = await client.ws_connect("/v1/audio-sink")
        assert await contender.receive_json(timeout=1) == {
            "type": "session.busy",
            "code": "ring_in_use",
        }
        await contender.close()

        await owner.close()
        replacement = await client.ws_connect("/v1/audio-sink")
        assert await replacement.receive_json(timeout=1) == {
            "type": "session.ready",
            "status": "acquired",
        }
        await replacement.close()

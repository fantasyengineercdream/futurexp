from __future__ import annotations

import base64
from datetime import datetime, timezone

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
import pytest

from oc_gateway.hardware_api import (
    AssetStore,
    HardwareServerDisplayTransport,
)
from oc_gateway.models import SceneTask


def make_task(scene, task_id="scene-001"):
    return SceneTask.from_dict(
        {
            "version": 1,
            "task_id": task_id,
            "type": "scene.render",
            "priority": 50,
            "ttl_ms": 10_000,
            "interrupt": "replace",
            "duration_ms": 5_000,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scene": scene,
        }
    )


@pytest.fixture
def asset_tree(tmp_path):
    animation = tmp_path / "devil_wave" / "v1"
    animation.mkdir(parents=True)
    (animation / "frame_001.png").write_bytes(b"one")
    (animation / "frame_000.bmp").write_bytes(b"zero")
    (animation / "notes.txt").write_bytes(b"ignore")

    image = tmp_path / "devil_card" / "v1"
    image.mkdir(parents=True)
    (image / "image.bmp").write_bytes(b"image")
    return tmp_path


@pytest.mark.parametrize(
    ("scene", "expected_type"),
    [
        ({"text": {"content": "你好", "style": "default"}}, "text"),
        (
            {
                "animation": {
                    "asset_id": "devil_wave",
                    "asset_version": 1,
                    "loop": 1,
                }
            },
            "animation",
        ),
        (
            {
                "image": {
                    "asset_id": "devil_card",
                    "asset_version": 1,
                }
            },
            "image",
        ),
        (
            {
                "text": {"content": "回来啦", "style": "default"},
                "animation": {
                    "asset_id": "devil_wave",
                    "asset_version": 1,
                    "loop": 1,
                },
            },
            "text_animation",
        ),
    ],
)
def test_maps_only_the_four_scene_shapes(
    scene, expected_type, asset_tree
):
    transport = HardwareServerDisplayTransport(
        "http://127.0.0.1:8781",
        "server-token",
        "orangepi-3b-01",
        ["left", "right"],
        AssetStore(asset_tree),
        session=None,
    )
    task = make_task(scene)
    payload = transport.build_payload(task)
    assert payload["task_id"] == task.task_id
    assert payload["agent_id"] == "orangepi-3b-01"
    assert payload["task"]["type"] == expected_type
    assert payload["task"]["transport"] == "bluetooth"
    assert payload["task"]["targets"] == ["left", "right"]
    if "text" in scene:
        assert payload["task"]["text"] == scene["text"]["content"]
        assert payload["task"]["stream_text"] is False


def test_animation_loads_only_sorted_frame_files(asset_tree):
    store = AssetStore(asset_tree)
    frames = store.animation("devil_wave", 1)
    assert [base64.b64decode(frame) for frame in frames] == [
        b"zero",
        b"one",
    ]


def test_image_loads_the_exact_versioned_image(asset_tree):
    store = AssetStore(asset_tree)
    assert base64.b64decode(store.image("devil_card", 1)) == b"image"


def test_rejects_missing_asset_version(tmp_path):
    store = AssetStore(tmp_path)
    with pytest.raises(FileNotFoundError, match="missing asset"):
        store.image("missing", 1)


def test_rejects_empty_or_duplicate_only_route(asset_tree):
    with pytest.raises(ValueError, match="target"):
        HardwareServerDisplayTransport(
            "http://127.0.0.1:8781",
            "server-token",
            "orangepi-3b-01",
            [],
            AssetStore(asset_tree),
            session=None,
        )


def test_includes_only_configured_target_screen_tokens(asset_tree):
    transport = HardwareServerDisplayTransport(
        "http://127.0.0.1:8781",
        "server-token",
        "orangepi-3b-01",
        ["left", "right"],
        AssetStore(asset_tree),
        session=None,
        screen_tokens={
            "left": "left-token",
            "right": "",
        },
    )
    payload = transport.build_payload(
        make_task({"text": {"content": "你好", "style": "default"}})
    )
    assert payload["task"]["targets"] == ["left", "right"]
    assert payload["task"]["screen_tokens"] == {
        "left": "left-token"
    }


def test_rejects_screen_token_for_unrouted_target(asset_tree):
    with pytest.raises(ValueError, match="screen token"):
        HardwareServerDisplayTransport(
            "http://127.0.0.1:8781",
            "server-token",
            "orangepi-3b-01",
            ["left"],
            AssetStore(asset_tree),
            session=None,
            screen_tokens={"right": "right-token"},
        )


@pytest.mark.asyncio
async def test_posts_task_and_polls_until_completed(asset_tree):
    received = []
    polls = 0

    async def submit(request):
        received.append(
            {
                "auth": request.headers.get("X-Server-Token"),
                "body": await request.json(),
            }
        )
        return web.json_response(
            {"ok": True, "task_id": "http-001"}, status=202
        )

    async def job(_request):
        nonlocal polls
        polls += 1
        status = "sent" if polls == 1 else "completed"
        return web.json_response(
            {
                "ok": True,
                "job": {
                    "task_id": "http-001",
                    "status": status,
                    "target_results": {
                        "left": {"status": "completed", "ok": True}
                    },
                },
            }
        )

    app = web.Application()
    app.router.add_post("/api/server/tasks", submit)
    app.router.add_get("/api/server/jobs/{task_id}", job)
    async with TestServer(app) as server, ClientSession() as session:
        transport = HardwareServerDisplayTransport(
            str(server.make_url("")).rstrip("/"),
            "server-token",
            "orangepi-3b-01",
            ["left"],
            AssetStore(asset_tree),
            session,
            poll_interval_s=0,
        )
        await transport.send_task(
            make_task(
                {"text": {"content": "你好", "style": "default"}},
                task_id="http-001",
            )
        )
        ack = await transport.wait_for_ack("http-001", timeout=0.2)

    assert ack is not None
    assert ack.status == "completed"
    assert received[0]["auth"] == "server-token"
    assert received[0]["body"]["task_id"] == "http-001"
    assert polls == 2


@pytest.mark.asyncio
async def test_failed_job_names_failed_targets(asset_tree):
    async def job(_request):
        return web.json_response(
            {
                "ok": True,
                "job": {
                    "task_id": "http-002",
                    "status": "failed",
                    "target_results": {
                        "left": {"status": "completed", "ok": True},
                        "right": {
                            "status": "failed",
                            "ok": False,
                            "error": "ACK timeout",
                        },
                    },
                },
            }
        )

    app = web.Application()
    app.router.add_get("/api/server/jobs/{task_id}", job)
    async with TestServer(app) as server, ClientSession() as session:
        transport = HardwareServerDisplayTransport(
            str(server.make_url("")).rstrip("/"),
            "server-token",
            "orangepi-3b-01",
            ["left", "right"],
            AssetStore(asset_tree),
            session,
            poll_interval_s=0,
        )
        ack = await transport.wait_for_ack("http-002", timeout=0.2)

    assert ack is not None
    assert ack.status == "failed"
    assert ack.error_code == "targets_failed:right"


@pytest.mark.asyncio
async def test_authentication_failure_never_falls_back_to_mock(asset_tree):
    async def submit(_request):
        return web.json_response({"error": "unauthorized"}, status=401)

    app = web.Application()
    app.router.add_post("/api/server/tasks", submit)
    async with TestServer(app) as server, ClientSession() as session:
        transport = HardwareServerDisplayTransport(
            str(server.make_url("")).rstrip("/"),
            "wrong-token",
            "orangepi-3b-01",
            ["left"],
            AssetStore(asset_tree),
            session,
        )
        with pytest.raises(RuntimeError, match="authentication"):
            await transport.send_task(
                make_task(
                    {"text": {"content": "你好", "style": "default"}}
                )
            )


@pytest.mark.asyncio
async def test_missing_job_is_a_diagnostic_failed_ack(asset_tree):
    async def job(_request):
        return web.json_response({"error": "not found"}, status=404)

    app = web.Application()
    app.router.add_get("/api/server/jobs/{task_id}", job)
    async with TestServer(app) as server, ClientSession() as session:
        transport = HardwareServerDisplayTransport(
            str(server.make_url("")).rstrip("/"),
            "server-token",
            "orangepi-3b-01",
            ["left"],
            AssetStore(asset_tree),
            session,
        )
        ack = await transport.wait_for_ack("missing", timeout=0.2)

    assert ack is not None
    assert ack.status == "failed"
    assert ack.error_code == "job_not_found"

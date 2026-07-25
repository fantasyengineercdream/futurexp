import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from oc_gateway.models import DisplayAck, SceneTask


def base_task(scene: dict) -> dict:
    return {
        "version": 1,
        "task_id": "task-001",
        "type": "scene.render",
        "priority": 50,
        "ttl_ms": 10_000,
        "interrupt": "replace",
        "duration_ms": 5_000,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scene": scene,
    }


@pytest.mark.parametrize(
    "scene",
    [
        {"text": {"content": "主人，该喝水了。", "style": "devil_reminder"}},
        {"animation": {"asset_id": "devil_wave", "asset_version": 1, "loop": 2}},
        {"image": {"asset_id": "devil_low_battery", "asset_version": 1}},
        {
            "text": {"content": "我在想啦。", "style": "devil_thinking"},
            "animation": {
                "asset_id": "devil_thinking",
                "asset_version": 1,
                "loop": 1,
            },
        },
    ],
)
def test_accepts_exactly_the_four_display_task_shapes(scene):
    task = SceneTask.from_dict(base_task(scene))
    assert task.to_dict()["scene"] == scene


def test_rejects_unsupported_text_image_combination():
    with pytest.raises(ValueError, match="unsupported scene combination"):
        SceneTask.from_dict(
            base_task(
                {
                    "text": {"content": "x", "style": "default"},
                    "image": {"asset_id": "x", "asset_version": 1},
                }
            )
        )


@pytest.mark.parametrize(
    "scene",
    [
        {"text": {"content": "", "style": "default"}},
        {"text": {"content": "x", "style": "default", "color": "red"}},
        {"animation": {"asset_id": "x", "asset_version": 0, "loop": 1}},
        {"animation": {"asset_id": "x", "asset_version": 1, "loop": 0}},
        {"image": {"asset_id": "", "asset_version": 1}},
    ],
)
def test_rejects_invalid_nested_scene_members(scene):
    with pytest.raises(ValueError):
        SceneTask.from_dict(base_task(scene))


def test_rejects_unknown_envelope_members():
    payload = base_task({"text": {"content": "x", "style": "default"}})
    payload["surprise"] = True
    with pytest.raises(ValueError, match="unknown task fields"):
        SceneTask.from_dict(payload)


def test_ack_accepts_only_known_statuses():
    ack = DisplayAck.from_dict(
        {
            "version": 1,
            "task_id": "task-001",
            "status": "completed",
            "error_code": None,
        }
    )
    assert ack.status == "completed"
    with pytest.raises(ValueError, match="unknown ACK status"):
        DisplayAck.from_dict(
            {"version": 1, "task_id": "task-001", "status": "maybe"}
        )


def test_protocol_examples_conform_to_their_json_schemas():
    protocol = Path(__file__).parents[1] / "protocol"
    task_schema = json.loads(
        (protocol / "scene-task.schema.json").read_text(encoding="utf-8")
    )
    manifest_schema = json.loads(
        (protocol / "asset-manifest.schema.json").read_text(encoding="utf-8")
    )
    for name in ("text", "animation", "image", "text-animation"):
        value = json.loads(
            (protocol / "examples" / f"{name}.json").read_text(encoding="utf-8")
        )
        Draft202012Validator(task_schema).validate(value)
    manifest = json.loads(
        (protocol / "examples" / "asset-manifest.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(manifest_schema).validate(manifest)


def test_json_schema_rejects_a_fifth_scene_shape():
    protocol = Path(__file__).parents[1] / "protocol"
    schema = json.loads(
        (protocol / "scene-task.schema.json").read_text(encoding="utf-8")
    )
    payload = base_task(
        {
            "text": {"content": "x", "style": "default"},
            "image": {"asset_id": "x", "asset_version": 1},
        }
    )
    with pytest.raises(ValidationError):
        Draft202012Validator(schema).validate(payload)

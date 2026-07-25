from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ALLOWED_COMBINATIONS = {
    frozenset({"text"}),
    frozenset({"animation"}),
    frozenset({"image"}),
    frozenset({"text", "animation"}),
}
ACK_STATUSES = {"accepted", "rendering", "completed", "failed", "cancelled"}
TASK_FIELDS = {
    "version",
    "task_id",
    "type",
    "priority",
    "ttl_ms",
    "interrupt",
    "duration_ms",
    "created_at",
    "scene",
}


def _non_empty_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _positive_integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _validate_scene(scene: Any) -> dict[str, Any]:
    if not isinstance(scene, dict) or frozenset(scene) not in ALLOWED_COMBINATIONS:
        raise ValueError("unsupported scene combination")

    if "text" in scene:
        text = scene["text"]
        if not isinstance(text, dict) or set(text) != {"content", "style"}:
            raise ValueError("text requires only content and style")
        _non_empty_string(text["content"], "text.content")
        _non_empty_string(text["style"], "text.style")

    if "animation" in scene:
        animation = scene["animation"]
        if not isinstance(animation, dict) or set(animation) != {
            "asset_id",
            "asset_version",
            "loop",
        }:
            raise ValueError(
                "animation requires only asset_id, asset_version and loop"
            )
        _non_empty_string(animation["asset_id"], "animation.asset_id")
        _positive_integer(animation["asset_version"], "animation.asset_version")
        _positive_integer(animation["loop"], "animation.loop")

    if "image" in scene:
        image = scene["image"]
        if not isinstance(image, dict) or set(image) != {
            "asset_id",
            "asset_version",
        }:
            raise ValueError("image requires only asset_id and asset_version")
        _non_empty_string(image["asset_id"], "image.asset_id")
        _positive_integer(image["asset_version"], "image.asset_version")

    return scene


@dataclass(frozen=True)
class SceneTask:
    version: int
    task_id: str
    type: Literal["scene.render"]
    priority: int
    ttl_ms: int
    interrupt: Literal["replace", "queue", "ignore"]
    duration_ms: int
    created_at: str
    scene: dict[str, Any]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SceneTask":
        if not isinstance(value, dict):
            raise ValueError("task must be an object")
        unknown = set(value) - TASK_FIELDS
        missing = TASK_FIELDS - set(value)
        if unknown:
            raise ValueError(f"unknown task fields: {', '.join(sorted(unknown))}")
        if missing:
            raise ValueError(f"missing task fields: {', '.join(sorted(missing))}")
        if value["version"] != 1 or value["type"] != "scene.render":
            raise ValueError("unsupported task protocol version or type")
        if value["interrupt"] not in {"replace", "queue", "ignore"}:
            raise ValueError("unknown interrupt policy")
        task_id = _non_empty_string(value["task_id"], "task_id")
        priority = value["priority"]
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not 0 <= priority <= 100
        ):
            raise ValueError("priority must be an integer from 0 to 100")
        ttl_ms = _positive_integer(value["ttl_ms"], "ttl_ms")
        duration_ms = _positive_integer(value["duration_ms"], "duration_ms")
        created_at = _non_empty_string(value["created_at"], "created_at")
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("created_at must include a timezone")
        scene = _validate_scene(value["scene"])
        return cls(
            version=1,
            task_id=task_id,
            type="scene.render",
            priority=priority,
            ttl_ms=ttl_ms,
            interrupt=value["interrupt"],
            duration_ms=duration_ms,
            created_at=created_at,
            scene=scene,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "task_id": self.task_id,
            "type": self.type,
            "priority": self.priority,
            "ttl_ms": self.ttl_ms,
            "interrupt": self.interrupt,
            "duration_ms": self.duration_ms,
            "created_at": self.created_at,
            "scene": self.scene,
        }


@dataclass(frozen=True)
class DisplayAck:
    version: int
    task_id: str
    status: str
    error_code: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DisplayAck":
        if not isinstance(value, dict):
            raise ValueError("ACK must be an object")
        unknown = set(value) - {"version", "task_id", "status", "error_code"}
        if unknown:
            raise ValueError(f"unknown ACK fields: {', '.join(sorted(unknown))}")
        if value.get("version") != 1:
            raise ValueError("unsupported ACK protocol version")
        status = str(value.get("status"))
        if status not in ACK_STATUSES:
            raise ValueError("unknown ACK status")
        error_code = value.get("error_code")
        if error_code is not None and not isinstance(error_code, str):
            raise ValueError("error_code must be a string or null")
        return cls(
            version=1,
            task_id=_non_empty_string(value.get("task_id"), "task_id"),
            status=status,
            error_code=error_code,
        )

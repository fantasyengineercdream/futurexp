from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import time
from typing import Any

from aiohttp import ClientError, ClientSession

from .models import DisplayAck, SceneTask


class AssetStore:
    """Loads only explicitly versioned e-ink image and animation assets."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _version_dir(self, asset_id: str, version: int) -> Path:
        path = self.root / asset_id / f"v{version}"
        if not path.is_dir():
            raise FileNotFoundError(
                f"missing asset {asset_id} version {version}"
            )
        return path

    @staticmethod
    def _encode(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    def image(self, asset_id: str, version: int) -> str:
        directory = self._version_dir(asset_id, version)
        candidates = [
            path
            for name in ("image.bmp", "image.png")
            if (path := directory / name).is_file()
        ]
        if len(candidates) != 1:
            raise FileNotFoundError(
                f"asset {asset_id} version {version} requires one image"
            )
        return self._encode(candidates[0])

    def animation(self, asset_id: str, version: int) -> list[str]:
        directory = self._version_dir(asset_id, version)
        frames = sorted(
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.name.startswith("frame_")
            and path.suffix.lower() in {".bmp", ".png"}
        )
        if not frames:
            raise FileNotFoundError(
                f"asset {asset_id} version {version} has no frames"
            )
        return [self._encode(path) for path in frames]


class HardwareServerDisplayTransport:
    """Maps OC scenes to the existing ADVX Task Server contract."""

    def __init__(
        self,
        base_url: str,
        server_token: str,
        agent_id: str,
        targets: list[str] | tuple[str, ...],
        asset_store: AssetStore,
        session: ClientSession | None,
        *,
        screen_tokens: dict[str, str] | None = None,
        poll_interval_s: float = 0.1,
    ):
        self.base_url = base_url.strip().rstrip("/")
        self.server_token = server_token.strip()
        self.agent_id = agent_id.strip()
        self.targets = tuple(
            dict.fromkeys(
                str(target).strip()
                for target in targets
                if str(target).strip()
            )
        )
        if not self.base_url:
            raise ValueError("hardware server URL is required")
        if not self.server_token:
            raise ValueError("hardware server token is required")
        if not self.agent_id:
            raise ValueError("hardware agent ID is required")
        if not self.targets:
            raise ValueError("at least one hardware target is required")
        self.screen_tokens = {
            str(target).strip(): str(token)
            for target, token in (screen_tokens or {}).items()
        }
        unknown_token_targets = (
            set(self.screen_tokens) - set(self.targets)
        )
        if unknown_token_targets:
            raise ValueError(
                "screen token configured for unrouted target: "
                + ", ".join(sorted(unknown_token_targets))
            )
        if poll_interval_s < 0:
            raise ValueError("poll interval cannot be negative")
        self.asset_store = asset_store
        self.session = session
        self.poll_interval_s = poll_interval_s

    @property
    def _headers(self) -> dict[str, str]:
        return {"X-Server-Token": self.server_token}

    def build_payload(self, scene_task: SceneTask) -> dict[str, Any]:
        scene = scene_task.scene
        hardware_task: dict[str, Any] = {
            "transport": "bluetooth",
            "targets": list(self.targets),
        }
        supplied_tokens = {
            target: token
            for target, token in self.screen_tokens.items()
            if token
        }
        if supplied_tokens:
            hardware_task["screen_tokens"] = supplied_tokens
        if set(scene) == {"text"}:
            hardware_task.update(
                {
                    "type": "text",
                    "text": scene["text"]["content"],
                    "stream_text": False,
                }
            )
        elif set(scene) == {"animation"}:
            animation = scene["animation"]
            frames = self.asset_store.animation(
                animation["asset_id"], animation["asset_version"]
            )
            hardware_task.update(
                {
                    "type": "animation",
                    "frames": frames * animation["loop"],
                }
            )
        elif set(scene) == {"image"}:
            image = scene["image"]
            hardware_task.update(
                {
                    "type": "image",
                    "image": self.asset_store.image(
                        image["asset_id"], image["asset_version"]
                    ),
                }
            )
        elif set(scene) == {"text", "animation"}:
            animation = scene["animation"]
            frames = self.asset_store.animation(
                animation["asset_id"], animation["asset_version"]
            )
            hardware_task.update(
                {
                    "type": "text_animation",
                    "text": scene["text"]["content"],
                    "stream_text": False,
                    "frames": frames * animation["loop"],
                }
            )
        else:
            raise ValueError("unsupported scene combination")
        return {
            "task_id": scene_task.task_id,
            "agent_id": self.agent_id,
            "task": hardware_task,
        }

    def _require_session(self) -> ClientSession:
        if self.session is None:
            raise RuntimeError("HTTP session is required for hardware I/O")
        return self.session

    async def send_task(self, task: SceneTask) -> None:
        session = self._require_session()
        try:
            async with session.post(
                f"{self.base_url}/api/server/tasks",
                json=self.build_payload(task),
                headers=self._headers,
            ) as response:
                if response.status in {401, 403}:
                    raise RuntimeError(
                        "ADVX server authentication failed"
                    )
                if response.status not in {200, 202}:
                    body = (await response.text())[:200]
                    raise RuntimeError(
                        f"ADVX task submit failed: HTTP "
                        f"{response.status} {body}"
                    )
        except ClientError as exc:
            raise RuntimeError(
                f"ADVX task submit network error: {exc}"
            ) from exc

    @staticmethod
    def _failed_ack(task_id: str, error_code: str) -> DisplayAck:
        return DisplayAck.from_dict(
            {
                "version": 1,
                "task_id": task_id,
                "status": "failed",
                "error_code": error_code,
            }
        )

    async def wait_for_ack(
        self, task_id: str, timeout: float
    ) -> DisplayAck | None:
        session = self._require_session()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                async with session.get(
                    f"{self.base_url}/api/server/jobs/{task_id}",
                    headers=self._headers,
                ) as response:
                    if response.status in {401, 403}:
                        raise RuntimeError(
                            "ADVX server authentication failed"
                        )
                    if response.status == 404:
                        return self._failed_ack(
                            task_id, "job_not_found"
                        )
                    if response.status != 200:
                        return self._failed_ack(
                            task_id, f"http_{response.status}"
                        )
                    try:
                        payload = await response.json()
                    except (ValueError, TypeError):
                        return self._failed_ack(
                            task_id, "invalid_server_response"
                        )
            except ClientError:
                return self._failed_ack(task_id, "network_error")

            job = payload.get("job")
            if not isinstance(job, dict):
                return self._failed_ack(
                    task_id, "invalid_job_response"
                )
            status = job.get("status")
            target_results = job.get("target_results", {})
            failed_targets = [
                str(target)
                for target, value in target_results.items()
                if isinstance(value, dict) and not value.get("ok")
            ]
            if status == "completed" and not failed_targets:
                return DisplayAck.from_dict(
                    {
                        "version": 1,
                        "task_id": task_id,
                        "status": "completed",
                    }
                )
            if status in {"failed", "not_delivered"} or failed_targets:
                suffix = (
                    ",".join(failed_targets)
                    if failed_targets
                    else str(status)
                )
                return self._failed_ack(
                    task_id, f"targets_failed:{suffix}"
                )
            await asyncio.sleep(self.poll_interval_s)
        return None

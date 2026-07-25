from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from typing import Any
import uuid

from aiohttp import ClientSession

from .models import SceneTask

DEFAULT_URL = "http://127.0.0.1:8787/v1/display/tasks"


def _common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--priority", type=int, default=50)
    parser.add_argument("--ttl-ms", type=int, default=10_000)
    parser.add_argument(
        "--interrupt", choices=("replace", "queue", "ignore"), default="replace"
    )
    parser.add_argument("--duration-ms", type=int, default=5_000)
    parser.add_argument("--url", default=DEFAULT_URL)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="oc-display",
        description="Send one of the four supported OC display tasks.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    text = commands.add_parser("text")
    text.add_argument("content")
    text.add_argument("--style", default="default")
    _common_options(text)

    animation = commands.add_parser("animation")
    animation.add_argument("asset_id")
    animation.add_argument("--asset-version", type=int, default=1)
    animation.add_argument("--loop", type=int, default=1)
    _common_options(animation)

    image = commands.add_parser("image")
    image.add_argument("asset_id")
    image.add_argument("--asset-version", type=int, default=1)
    _common_options(image)

    scene = commands.add_parser("scene")
    scene.add_argument("content")
    scene.add_argument("asset_id")
    scene.add_argument("--style", default="default")
    scene.add_argument("--asset-version", type=int, default=1)
    scene.add_argument("--loop", type=int, default=1)
    _common_options(scene)
    return parser


def _scene_from_args(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "text":
        return {"text": {"content": args.content, "style": args.style}}
    if args.command == "animation":
        return {
            "animation": {
                "asset_id": args.asset_id,
                "asset_version": args.asset_version,
                "loop": args.loop,
            }
        }
    if args.command == "image":
        return {
            "image": {
                "asset_id": args.asset_id,
                "asset_version": args.asset_version,
            }
        }
    return {
        "text": {"content": args.content, "style": args.style},
        "animation": {
            "asset_id": args.asset_id,
            "asset_version": args.asset_version,
            "loop": args.loop,
        },
    }


def task_from_args(args: argparse.Namespace) -> SceneTask:
    return SceneTask.from_dict(
        {
            "version": 1,
            "task_id": str(uuid.uuid4()),
            "type": "scene.render",
            "priority": args.priority,
            "ttl_ms": args.ttl_ms,
            "interrupt": args.interrupt,
            "duration_ms": args.duration_ms,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scene": _scene_from_args(args),
        }
    )


async def _post(task: SceneTask, url: str) -> int:
    async with ClientSession() as session:
        async with session.post(url, json=task.to_dict()) as response:
            body = await response.json()
            print(json.dumps(body, ensure_ascii=False))
            return 0 if response.status < 300 else 1


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_post(task_from_args(args), args.url)))

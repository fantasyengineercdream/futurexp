from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
import uuid

from .models import SceneTask
from .voice import VoiceEvent


class GatewayService:
    def __init__(
        self,
        *,
        voice: Any,
        audio_source: Any,
        audio_sinks: list[Any],
        displays: Any,
        character_id: str = "devil",
    ):
        if character_id not in {"devil", "angel"}:
            raise ValueError(f"unknown character: {character_id}")
        self.voice = voice
        self.audio_source = audio_source
        self.audio_sinks = audio_sinks
        self.displays = displays
        self.character_id = character_id
        self._response_had_audio = False
        self._silent_response_retries = 0

    async def _submit_scene(
        self,
        scene: dict[str, Any],
        *,
        priority: int = 50,
        interrupt: str = "replace",
        duration_ms: int = 5_000,
    ) -> bool:
        task = SceneTask.from_dict(
            {
                "version": 1,
                "task_id": str(uuid.uuid4()),
                "type": "scene.render",
                "priority": priority,
                "ttl_ms": 10_000,
                "interrupt": interrupt,
                "duration_ms": duration_ms,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "scene": scene,
            }
        )
        return await self.displays.submit(task)

    def _animation(self, phase: str) -> dict[str, Any]:
        return {
            "animation": {
                "asset_id": f"{self.character_id}_{phase}",
                "asset_version": 1,
                "loop": 1,
            }
        }

    async def handle_voice_event(self, event: VoiceEvent) -> None:
        if event.kind == "audio" and event.audio is not None:
            if not self._response_had_audio:
                await asyncio.gather(
                    *(sink.state("speaking") for sink in self.audio_sinks)
                )
            self._response_had_audio = True
            await asyncio.gather(
                *(sink.play(event.audio) for sink in self.audio_sinks)
            )
            return

        if event.kind == "speech_started":
            await self.cancel_current_response()
            await asyncio.gather(
                *(sink.state("listening") for sink in self.audio_sinks)
            )
            await self._submit_scene(
                self._animation("listening"),
                priority=90,
                interrupt="replace",
                duration_ms=2_000,
            )
            return

        if event.kind == "speech_stopped":
            self._response_had_audio = False
            self._silent_response_retries = 0
            await asyncio.gather(
                *(sink.state("thinking") for sink in self.audio_sinks)
            )
            await self._submit_scene(
                self._animation("thinking"),
                priority=70,
                interrupt="replace",
                duration_ms=3_000,
            )
            return

        if event.kind == "user_transcript" and event.text:
            await asyncio.gather(
                *(
                    sink.transcript("user", event.text)
                    for sink in self.audio_sinks
                )
            )
            return

        if event.kind == "assistant_transcript" and event.text:
            await asyncio.gather(
                *(
                    sink.transcript("assistant", event.text)
                    for sink in self.audio_sinks
                )
            )
            return

        if event.kind == "inner_os" and event.text:
            text = " ".join(event.text.split())
            if len(text) > 24:
                text = text[:23] + "…"
            raw = event.raw or {}
            event_id = str(raw.get("event_id", "")).strip()
            requested_character = str(raw.get("character", ""))
            character_id = (
                requested_character
                if requested_character in {"devil", "angel"}
                else self.character_id
            )
            accepted = await self._submit_scene(
                {
                    "text": {
                        "content": text,
                        "style": f"{character_id}_inner_os",
                    },
                    "animation": {
                        "asset_id": f"{character_id}_thinking",
                        "asset_version": 1,
                        "loop": 1,
                    },
                },
                priority=85,
                interrupt="replace",
                duration_ms=6_000,
            )
            if event_id:
                await self.voice.send_inner_os_ack(
                    event_id,
                    "accepted" if accepted else "rejected",
                )
            return

        if event.kind == "connected":
            await asyncio.gather(
                *(sink.state("idle") for sink in self.audio_sinks)
            )
            await self._submit_scene(
                self._animation("idle"),
                priority=20,
                interrupt="queue",
                duration_ms=5_000,
            )
            return

        if event.kind == "response_done":
            if (
                not self._response_had_audio
                and self._silent_response_retries < 1
            ):
                self._silent_response_retries += 1
                await self.voice.request_response()
                return
            await self._submit_scene(
                self._animation("idle"),
                priority=10,
                interrupt="queue",
                duration_ms=5_000,
            )
            await asyncio.gather(
                *(sink.state("idle") for sink in self.audio_sinks)
            )

    async def cancel_current_response(self) -> None:
        await asyncio.gather(
            *(sink.clear() for sink in self.audio_sinks)
        )
        await self.voice.cancel()

    async def _upload_microphone(self) -> None:
        if self.audio_source is None:
            return
        async for frame in self.audio_source.frames():
            await self.voice.send_audio(frame)

    async def _receive_voice(self) -> None:
        async for event in self.voice.events():
            await self.handle_voice_event(event)

    async def _drain_displays(self) -> None:
        while True:
            await self.displays.drain_once()
            await asyncio.sleep(0.01)

    async def run(self) -> None:
        await self.voice.connect()
        async with asyncio.TaskGroup() as group:
            group.create_task(self._upload_microphone())
            group.create_task(self._receive_voice())
            group.create_task(self._drain_displays())

    async def close(self) -> None:
        await self.voice.close()

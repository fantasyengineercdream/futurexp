from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
import json
import os
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
import uuid

from aiohttp import ClientSession, WSMsgType

from .audio import PcmFrame

CHARACTERS = {"devil", "angel"}
EVENT_KINDS = {
    "session.updated": "connected",
    "input_audio_buffer.speech_started": "speech_started",
    "input_audio_buffer.speech_stopped": "speech_stopped",
    "response.audio.delta": "audio",
    "response.audio_transcript.delta": "assistant_transcript_delta",
    "response.audio_transcript.done": "assistant_transcript",
    "oc.inner_os": "inner_os",
    "conversation.item.input_audio_transcription.completed": "user_transcript",
    "response.done": "response_done",
    "error": "error",
}


@dataclass(frozen=True)
class VoiceEvent:
    kind: str
    text: str | None = None
    audio: PcmFrame | None = None
    raw: dict[str, Any] | None = None


def normalize_realtime_event(raw: dict[str, Any]) -> VoiceEvent:
    raw_type = str(raw.get("type", ""))
    kind = EVENT_KINDS.get(raw_type, "unknown")
    audio = None
    if kind == "audio":
        encoded = raw.get("delta")
        if not isinstance(encoded, str):
            raise ValueError("audio delta must be base64 text")
        audio = PcmFrame(base64.b64decode(encoded, validate=True))
    text_value = raw.get("transcript")
    if text_value is None and kind == "inner_os":
        text_value = raw.get("text")
    if text_value is None and kind == "assistant_transcript_delta":
        text_value = raw.get("delta")
    if text_value is None and kind == "error":
        error = raw.get("error")
        text_value = error.get("message") if isinstance(error, dict) else error
    text = str(text_value) if text_value is not None else None
    return VoiceEvent(kind=kind, text=text, audio=audio, raw=raw)


def reconnect_delays() -> Iterator[int]:
    delay = 1
    while True:
        yield min(delay, 10)
        delay = min(delay * 2, 10)


def _device_websocket_url(
    base_url: str, character_id: str, device_id: str
) -> str:
    parts = urlsplit(base_url.rstrip("/"))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit(
        (
            scheme,
            parts.netloc,
            "/api/device/realtime",
            urlencode(
                {
                    "character": character_id,
                    "deviceId": device_id,
                }
            ),
            "",
        )
    )


class CloudVoiceProvider:
    def __init__(
        self,
        base_url: str,
        device_token: str,
        character_id: str,
        session: ClientSession,
        device_id: str = "orangepi-3b-01",
        inner_os_capability: bool = True,
    ):
        if character_id not in CHARACTERS:
            raise ValueError(f"unknown character: {character_id}")
        token = device_token.strip()
        if not token:
            raise ValueError("device token is required")
        normalized_device_id = device_id.strip().lower()
        if not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{2,63}", normalized_device_id
        ):
            raise ValueError("device id is invalid")
        self.character_id = character_id
        self.device_id = normalized_device_id
        self.session = session
        self.websocket_url = _device_websocket_url(
            base_url, character_id, normalized_device_id
        )
        self.request_headers = {"Authorization": f"Bearer {token}"}
        self.inner_os_capability = inner_os_capability
        self._events: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._socket: Any | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._closed = False

    async def _open_socket(self) -> None:
        self._socket = await self.session.ws_connect(
            self.websocket_url, headers=self.request_headers
        )
        if self.inner_os_capability:
            await self._socket.send_json(
                {
                    "type": "oc.capabilities",
                    "capabilities": ["inner_os.v1"],
                }
            )

    async def connect(self) -> None:
        self._closed = False
        await self._open_socket()
        self._reader_task = asyncio.create_task(self._read_forever())

    async def _handle_raw(self, raw: dict[str, Any]) -> None:
        event = normalize_realtime_event(raw)
        if event.kind != "unknown":
            await self._events.put(event)

    async def _read_socket(self) -> None:
        assert self._socket is not None
        async for message in self._socket:
            if message.type == WSMsgType.TEXT:
                raw = json.loads(message.data)
                if isinstance(raw, dict):
                    await self._handle_raw(raw)
            elif message.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
                break

    async def _read_forever(self) -> None:
        delays = reconnect_delays()
        while not self._closed:
            try:
                await self._read_socket()
            except (OSError, asyncio.TimeoutError, ValueError, json.JSONDecodeError) as error:
                await self._events.put(VoiceEvent("error", text=str(error)))
            if self._closed:
                return
            await asyncio.sleep(next(delays))
            try:
                await self._open_socket()
            except (OSError, asyncio.TimeoutError) as error:
                await self._events.put(VoiceEvent("error", text=str(error)))

    async def send_audio(self, frame: PcmFrame) -> bool:
        if self._socket is None or getattr(self._socket, "closed", False):
            return False
        await self._socket.send_json(
            {
                "event_id": f"audio_{uuid.uuid4()}",
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(frame.data).decode("ascii"),
            }
        )
        return True

    async def cancel(self) -> None:
        if self._socket is not None and not getattr(self._socket, "closed", False):
            await self._socket.send_json(
                {
                    "event_id": f"cancel_{uuid.uuid4()}",
                    "type": "response.cancel",
                }
            )

    async def request_response(self) -> None:
        if self._socket is not None and not getattr(self._socket, "closed", False):
            await self._socket.send_json(
                {
                    "event_id": f"response_{uuid.uuid4()}",
                    "type": "response.create",
                    "response": {"modalities": ["text", "audio"]},
                }
            )

    async def send_inner_os_ack(
        self, event_id: str, status: str
    ) -> None:
        if status not in {"accepted", "rejected"}:
            raise ValueError("unknown inner OS ACK status")
        if self._socket is None or getattr(self._socket, "closed", False):
            return
        await self._socket.send_json(
            {
                "type": "oc.inner_os.ack",
                "event_id": event_id,
                "status": status,
            }
        )

    async def events(self) -> AsyncIterator[VoiceEvent]:
        while not self._closed:
            yield await self._events.get()

    async def close(self) -> None:
        self._closed = True
        if self._reader_task is not None:
            self._reader_task.cancel()
            await asyncio.gather(self._reader_task, return_exceptions=True)
        if self._socket is not None:
            await self._socket.close()


class DirectStepFunProvider(CloudVoiceProvider):
    """Explicit test-only escape hatch; production cloud mode never reads this key."""

    def __init__(self, character_id: str, session: ClientSession):
        if os.getenv("OC_VOICE_PROVIDER") != "direct":
            raise ValueError("DirectStepFunProvider requires OC_VOICE_PROVIDER=direct")
        api_key = os.getenv("OC_STEPFUN_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OC_STEPFUN_API_KEY is required in direct mode")
        super().__init__(
            base_url="https://api.stepfun.com",
            device_token=api_key,
            character_id=character_id,
            session=session,
            inner_os_capability=False,
        )
        self.websocket_url = (
            "wss://api.stepfun.com/step_plan/v1/realtime"
            "?model=stepaudio-2.5-realtime"
        )

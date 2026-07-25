from __future__ import annotations

from pathlib import Path

from aiohttp import web

from .audio import PcmFrame
from .display import DisplayTaskOrchestrator
from .models import SceneTask


class PcWebSocketSink:
    def __init__(self) -> None:
        self.sockets: set[web.WebSocketResponse] = set()

    async def play(self, frame: PcmFrame) -> None:
        for socket in tuple(self.sockets):
            if socket.closed:
                self.sockets.discard(socket)
                continue
            try:
                await socket.send_bytes(frame.data)
            except ConnectionResetError:
                self.sockets.discard(socket)

    async def clear(self) -> None:
        await self._send_json({"type": "playback.clear"})

    async def state(self, phase: str) -> None:
        await self._send_json({"type": "state", "phase": phase})

    async def transcript(self, role: str, text: str) -> None:
        await self._send_json(
            {"type": "transcript", "role": role, "text": text}
        )

    async def _send_json(self, payload: dict[str, str]) -> None:
        for socket in tuple(self.sockets):
            if socket.closed:
                self.sockets.discard(socket)
                continue
            try:
                await socket.send_json(payload)
            except ConnectionResetError:
                self.sockets.discard(socket)


ORCHESTRATOR_KEY = web.AppKey(
    "display_orchestrator", DisplayTaskOrchestrator
)
PC_SINK_KEY = web.AppKey("pc_speaker_sink", PcWebSocketSink)
SPEAKER_DIR = Path(__file__).parents[2] / "speaker"


def create_app(orchestrator: DisplayTaskOrchestrator) -> web.Application:
    app = web.Application()
    app[ORCHESTRATOR_KEY] = orchestrator
    app[PC_SINK_KEY] = PcWebSocketSink()

    async def health(_: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "protocol": 1})

    async def submit(request: web.Request) -> web.Response:
        try:
            task = SceneTask.from_dict(await request.json())
            accepted = await orchestrator.submit(task)
        except (ValueError, KeyError, TypeError) as error:
            return web.json_response({"error": str(error)}, status=400)
        status = "accepted" if accepted else "duplicate"
        return web.json_response(
            {"task_id": task.task_id, "status": status},
            status=202 if accepted else 200,
        )

    async def task_status(request: web.Request) -> web.Response:
        task_id = request.match_info["task_id"]
        ack = orchestrator.ack_for(task_id)
        if ack is None:
            return web.json_response(
                {"task_id": task_id, "status": "pending"}, status=202
            )
        return web.json_response(
            {
                "version": ack.version,
                "task_id": ack.task_id,
                "status": ack.status,
                "error_code": ack.error_code,
            }
        )

    async def speaker(_: web.Request) -> web.FileResponse:
        return web.FileResponse(SPEAKER_DIR / "index.html")

    async def speaker_script(_: web.Request) -> web.FileResponse:
        return web.FileResponse(SPEAKER_DIR / "speaker.js")

    async def audio_sink(request: web.Request) -> web.WebSocketResponse:
        socket = web.WebSocketResponse(heartbeat=20)
        await socket.prepare(request)
        sink = app[PC_SINK_KEY]
        sink.sockets = {
            existing for existing in sink.sockets if not existing.closed
        }
        if sink.sockets:
            await socket.send_json(
                {"type": "session.busy", "code": "ring_in_use"}
            )
            await socket.close(code=4409, message=b"ring_in_use")
            return socket

        sink.sockets.add(socket)
        await socket.send_json(
            {"type": "session.ready", "status": "acquired"}
        )
        try:
            async for _ in socket:
                pass
        finally:
            sink.sockets.discard(socket)
        return socket

    app.router.add_get("/health", health)
    app.router.add_post("/v1/display/tasks", submit)
    app.router.add_get("/v1/display/tasks/{task_id}", task_status)
    app.router.add_get("/speaker/", speaker)
    app.router.add_get("/speaker/speaker.js", speaker_script)
    app.router.add_get("/v1/audio-sink", audio_sink)
    return app

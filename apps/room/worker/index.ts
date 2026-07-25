import { DurableObject } from "cloudflare:workers";
import { getCharacter } from "../src/characters";
import { SessionGate } from "./session-gate";

export interface Env {
  ASSETS: Fetcher;
  REALTIME_ROOM: DurableObjectNamespace<RealtimeRoom>;
  STEPFUN_API_KEY: string;
}

const ALLOWED_CLIENT_EVENTS = new Set([
  "input_audio_buffer.append",
  "input_audio_buffer.clear",
  "conversation.item.create",
  "response.create",
  "response.cancel",
]);

export class RealtimeRoom extends DurableObject<Env> {
  private gate = new SessionGate(8);

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    this.gate.prune();

    if (url.pathname === "/api/status") {
      return Response.json(this.gate.snapshot(), { headers: { "cache-control": "no-store" } });
    }

    if (url.pathname !== "/api/realtime" || request.headers.get("Upgrade")?.toLowerCase() !== "websocket") {
      return Response.json({ error: "websocket_required" }, { status: 426 });
    }

    let character;
    try {
      character = getCharacter(url.searchParams.get("character") ?? "");
    } catch {
      return Response.json({ error: "unknown_character" }, { status: 400 });
    }

    const sessionId = crypto.randomUUID();
    const ip = request.headers.get("x-real-ip") ?? "unknown";
    const admission = this.gate.admit(ip, sessionId);
    if (!admission.ok) return Response.json({ error: admission.reason }, { status: 429 });

    const upstreamResponse = await fetch(
      "https://api.stepfun.com/step_plan/v1/realtime?model=stepaudio-2.5-realtime",
      { headers: { Upgrade: "websocket", Authorization: `Bearer ${this.env.STEPFUN_API_KEY}` } },
    );
    const upstream = upstreamResponse.webSocket;
    if (!upstream) {
      this.gate.release(sessionId);
      return Response.json({ error: "upstream_unavailable" }, { status: 502 });
    }

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair) as [WebSocket, WebSocket];
    server.accept();
    upstream.accept();
    let closed = false;

    const closeBoth = (code = 1000, reason = "session ended") => {
      if (closed) return;
      closed = true;
      this.gate.release(sessionId);
      try { server.close(code, reason); } catch { /* closed */ }
      try { upstream.close(code, reason); } catch { /* closed */ }
    };

    server.addEventListener("message", (event) => {
      this.gate.touch(sessionId);
      if (typeof event.data !== "string") return;
      try {
        const payload = JSON.parse(event.data) as { type?: string };
        if (payload.type && ALLOWED_CLIENT_EVENTS.has(payload.type)) upstream.send(event.data);
      } catch { /* ignore malformed client frames */ }
    });

    upstream.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      try {
        const payload = JSON.parse(event.data) as { type?: string };
        if (payload.type === "session.created") {
          upstream.send(JSON.stringify({
            event_id: `session_${sessionId}`,
            type: "session.update",
            session: {
              modalities: ["text", "audio"],
              instructions: character.instructions,
              voice: character.voice,
              input_audio_format: "pcm16",
              output_audio_format: "pcm16",
              turn_detection: { type: "server_vad", prefix_padding_ms: 300, silence_duration_ms: 350 },
            },
          }));
        }
        if (!payload.type?.startsWith("response.thinking.")) server.send(event.data);
      } catch {
        server.send(event.data);
      }
    });

    server.addEventListener("close", () => closeBoth());
    server.addEventListener("error", () => closeBoth(1011, "browser socket error"));
    upstream.addEventListener("close", () => closeBoth());
    upstream.addEventListener("error", () => closeBoth(1011, "upstream socket error"));
    setTimeout(() => closeBoth(1000, "ten minute demo limit"), 10 * 60_000);

    return new Response(null, { status: 101, webSocket: client });
  }
}

export default {
  fetch(request, env): Response | Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/realtime" || url.pathname === "/api/status") {
      const id = env.REALTIME_ROOM.idFromName("public-demo");
      const headers = new Headers(request.headers);
      headers.set("x-real-ip", request.headers.get("CF-Connecting-IP") ?? "local");
      return env.REALTIME_ROOM.get(id).fetch(new Request(request, { headers }));
    }
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;

import { getCharacter } from "../src/characters";
import {
  parseInnerOsDecisionFrame,
  PendingInnerOsDecision,
} from "../relay-worker/src/inner-os";
import { parseDeviceId } from "../relay-worker/src/protocol";
import { RealtimeTurnContext } from "../relay-worker/src/turn-context";
import { SessionGate } from "../worker/session-gate";

export interface PagesEnv {
  STEPFUN_API_KEY: string;
  DEVICE_RELAY: DurableObjectNamespace;
}

export interface PagesLifecycle {
  waitUntil(promise: Promise<unknown>): void;
}

const gate = new SessionGate(8);
const allowedClientEvents = new Set([
  "input_audio_buffer.append",
  "input_audio_buffer.clear",
  "conversation.item.create",
  "response.create",
  "response.cancel",
]);

export function normalizeSecret(value: string): string {
  return value.trim();
}

export function upstreamUnavailable(status: number, key = ""): {
  error: string;
  upstream_status: number;
  key_present: boolean;
  key_length: number;
} {
  return {
    error: "upstream_unavailable",
    upstream_status: status,
    key_present: key.length > 0,
    key_length: key.length,
  };
}

export async function handlePagesRequest(
  request: Request,
  env: PagesEnv,
  lifecycle?: PagesLifecycle,
): Promise<Response> {
  const url = new URL(request.url);
  gate.prune();

  if (url.pathname === "/api/status") {
    return Response.json(gate.snapshot(), { headers: { "cache-control": "no-store" } });
  }

  if (url.pathname === "/api/device/status" && request.method === "GET") {
    let deviceId;
    try {
      deviceId = parseDeviceId(url.searchParams.get("deviceId"));
    } catch {
      return Response.json({ error: "invalid_device_id" }, { status: 400 });
    }
    const id = env.DEVICE_RELAY.idFromName(deviceId);
    return env.DEVICE_RELAY.get(id).fetch(
      new Request("https://device-relay.internal/internal/inner-os/status"),
    );
  }

  const isBrowserRoute = url.pathname === "/api/realtime";
  const isDeviceRoute =
    url.pathname === "/api/device/realtime"
    || url.pathname === "/api/device/view";
  const isWebSocket = request.headers.get("Upgrade")?.toLowerCase() === "websocket";

  if ((!isBrowserRoute && !isDeviceRoute) || !isWebSocket) {
    return Response.json({ error: "websocket_required" }, { status: 426 });
  }
  if (isDeviceRoute) {
    let deviceId;
    try {
      deviceId = parseDeviceId(url.searchParams.get("deviceId"));
    } catch {
      return Response.json({ error: "invalid_device_id" }, { status: 400 });
    }
    const id = env.DEVICE_RELAY.idFromName(deviceId);
    return env.DEVICE_RELAY.get(id).fetch(request);
  }

  let character;
  try {
    character = getCharacter(url.searchParams.get("character") ?? "");
  } catch {
    return Response.json({ error: "unknown_character" }, { status: 400 });
  }

  let deviceId;
  try {
    deviceId = parseDeviceId(
      url.searchParams.get("deviceId") ?? "orangepi-3b-01",
    );
  } catch {
    return Response.json({ error: "invalid_device_id" }, { status: 400 });
  }
  const relayId = env.DEVICE_RELAY.idFromName(deviceId);
  const relay = env.DEVICE_RELAY.get(relayId);
  const runInBackground = (promise: Promise<unknown>): void => {
    const guarded = promise.catch(() => undefined);
    if (lifecycle) {
      lifecycle.waitUntil(guarded);
      return;
    }
    void guarded;
  };

  const sessionId = crypto.randomUUID();
  const ip = request.headers.get("CF-Connecting-IP") ?? "local";
  const admission = gate.admit(ip, sessionId);
  if (!admission.ok) return Response.json({ error: admission.reason }, { status: 429 });

  const upstreamResponse = await fetch(
    "https://api.stepfun.com/step_plan/v1/realtime?model=stepaudio-2.5-realtime",
    { headers: { Upgrade: "websocket", Authorization: `Bearer ${normalizeSecret(env.STEPFUN_API_KEY)}` } },
  );
  const upstream = upstreamResponse.webSocket;
  if (!upstream) {
    gate.release(sessionId);
    console.error("StepFun websocket upgrade failed", upstreamResponse.status);
    return Response.json(upstreamUnavailable(upstreamResponse.status, env.STEPFUN_API_KEY), { status: 502 });
  }

  const pair = new WebSocketPair();
  const [client, server] = Object.values(pair) as [WebSocket, WebSocket];
  server.accept();
  upstream.accept();
  let closed = false;
  const turnContext = new RealtimeTurnContext();
  const pendingDecision = new PendingInnerOsDecision();

  const closeBoth = (code = 1000, reason = "session ended") => {
    if (closed) return;
    closed = true;
    gate.release(sessionId);
    try { server.close(code, reason); } catch { /* already closed */ }
    try { upstream.close(code, reason); } catch { /* already closed */ }
  };

  server.addEventListener("message", (event) => {
    gate.touch(sessionId);
    if (typeof event.data !== "string") return;
    try {
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      const decisionContext = parseInnerOsDecisionFrame(payload);
      if (decisionContext) {
        pendingDecision.set(decisionContext);
        return;
      }
      turnContext.observeClient(payload);
      if (
        typeof payload.type === "string"
        && allowedClientEvents.has(payload.type)
      ) {
        upstream.send(event.data);
      }
    } catch { /* ignore malformed client frames */ }
  });

  upstream.addEventListener("message", (event) => {
    if (typeof event.data !== "string") return;
    try {
      const payload = JSON.parse(event.data) as Record<string, unknown>;
      turnContext.observeServer(payload);
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
        runInBackground(
          relay.fetch(
            new Request(
              "https://device-relay.internal/internal/inner-os/status",
            ),
          ).then(async (response) => {
            if (closed || server.readyState !== WebSocket.OPEN) return;
            const status = await response.json() as { inner_os?: string };
            server.send(JSON.stringify({
              type: "inner_os.status",
              status: status.inner_os ?? "unavailable",
            }));
          }),
        );
      }
      if (payload.type === "input_audio_buffer.speech_started") {
        runInBackground(
          relay.fetch(
            new Request(
              "https://device-relay.internal/internal/inner-os/cancel",
              { method: "POST" },
            ),
          ),
        );
      }
      if (
        payload.type === "response.audio_transcript.done"
        && typeof payload.transcript === "string"
      ) {
        const publicText = payload.transcript;
        const turn = turnContext.snapshot();
        runInBackground(
          turnContext.waitForUserText(turn).then(async (userText) => {
            if (userText === undefined) return;
            const decisionContext = pendingDecision.take();
            const response = await relay.fetch(
              new Request(
                "https://device-relay.internal/internal/inner-os",
                {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({
                    character: character.id,
                    userText,
                    publicText,
                    ...(decisionContext ? { decisionContext } : {}),
                  }),
                },
              ),
            );
            if (closed || server.readyState !== WebSocket.OPEN) return;
            const result = await response.json() as { status?: string };
            server.send(JSON.stringify({
              type: "inner_os.status",
              status: result.status ?? "unavailable",
            }));
          }),
        );
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

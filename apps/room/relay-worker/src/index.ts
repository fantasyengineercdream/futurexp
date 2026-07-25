import { DurableObject } from "cloudflare:workers";
import {
  getCharacter,
  type CharacterId,
} from "../../src/characters";
import {
  buildInnerOsDeviceEvent,
  generateInnerOs,
  parseInnerOsDecisionContext,
  parseInnerOsDecisionFrame,
  PendingInnerOsDecision,
  type GeneratedInnerOs,
  type InnerOsInput,
} from "./inner-os";
import { RelayPeers } from "./relay-peers";
import {
  authorizeDevice,
  parseDeviceId,
  viewerFramesForStepEvent,
} from "./protocol";
import { RealtimeTurnContext } from "./turn-context";

export interface RelayEnv {
  DEVICE_ROOMS: DurableObjectNamespace<DeviceRelayRoom>;
  DEVICE_TOKEN: string;
  STEPFUN_API_KEY: string;
}

const ALLOWED_DEVICE_EVENTS = new Set([
  "input_audio_buffer.append",
  "input_audio_buffer.clear",
  "conversation.item.create",
  "response.create",
  "response.cancel",
]);
const SESSION_LIMIT_MS = 10 * 60_000;
const INNER_OS_CAPABILITY = "inner_os.v1";

type InnerOsStatus =
  | "unavailable"
  | "ready"
  | "sent"
  | "delivered"
  | "error";

export class DeviceRelayRoom extends DurableObject<RelayEnv> {
  private readonly peers = new RelayPeers();
  private deviceSocket?: WebSocket;
  private upstreamSocket?: WebSocket;
  private viewerSocket?: WebSocket;
  private viewerTimer?: ReturnType<typeof setTimeout>;
  private innerOsSupported = false;
  private innerOsStatus: InnerOsStatus = "unavailable";
  private innerOsRevision = 0;
  private turnContext = new RealtimeTurnContext();
  private pendingDecision = new PendingInnerOsDecision();
  private readonly innerOsTasks = new Set<Promise<void>>();

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/internal/inner-os")) {
      return this.handleInnerOsInternalRequest(request, url);
    }
    if (
      request.headers.get("Upgrade")?.toLowerCase() !== "websocket"
    ) {
      return Response.json(
        { error: "websocket_required" },
        { status: 426 },
      );
    }
    try {
      parseDeviceId(url.searchParams.get("deviceId"));
    } catch {
      return Response.json({ error: "invalid_device_id" }, { status: 400 });
    }

    if (url.pathname === "/api/device/realtime") {
      return this.connectDevice(request, url);
    }
    if (url.pathname === "/api/device/view") {
      return this.connectViewer();
    }
    return Response.json({ error: "not_found" }, { status: 404 });
  }

  private async connectDevice(
    request: Request,
    url: URL,
  ): Promise<Response> {
    if (!authorizeDevice(request, this.env.DEVICE_TOKEN)) {
      return Response.json(
        { error: "device_unauthorized" },
        { status: 401 },
      );
    }

    let character;
    try {
      character = getCharacter(url.searchParams.get("character") ?? "");
    } catch {
      return Response.json(
        { error: "unknown_character" },
        { status: 400 },
      );
    }

    const upstreamResponse = await fetch(
      "https://api.stepfun.com/step_plan/v1/realtime"
        + "?model=stepaudio-2.5-realtime",
      {
        headers: {
          Upgrade: "websocket",
          Authorization: `Bearer ${this.env.STEPFUN_API_KEY.trim()}`,
        },
      },
    );
    const upstream = upstreamResponse.webSocket;
    if (!upstream) {
      return Response.json(
        {
          error: "upstream_unavailable",
          upstream_status: upstreamResponse.status,
        },
        { status: 502 },
      );
    }

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair) as [
      WebSocket,
      WebSocket,
    ];
    server.accept();
    upstream.accept();

    this.upstreamSocket?.close(4001, "device_replaced");
    this.invalidateInnerOs();
    this.setInnerOsStatus("unavailable");
    this.innerOsSupported = false;
    this.turnContext = new RealtimeTurnContext();
    this.pendingDecision = new PendingInnerOsDecision();
    this.deviceSocket = server;
    this.upstreamSocket = upstream;
    this.peers.attachDevice(server);

    const closeDevice = (
      code = 1000,
      reason = "device_session_ended",
    ) => {
      if (this.deviceSocket !== server) return;
      this.deviceSocket = undefined;
      this.upstreamSocket = undefined;
      this.innerOsSupported = false;
      this.invalidateInnerOs();
      this.setInnerOsStatus("unavailable");
      this.peers.detachDevice(server);
      this.viewerSocket = undefined;
      this.clearViewerTimer();
      try {
        server.close(code, reason);
      } catch {
        // already closed
      }
      try {
        upstream.close(code, reason);
      } catch {
        // already closed
      }
    };

    server.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        if (payload.type === "oc.capabilities") {
          const capabilities = payload.capabilities;
          this.innerOsSupported =
            Array.isArray(capabilities)
            && capabilities.includes(INNER_OS_CAPABILITY);
          this.setInnerOsStatus(
            this.innerOsSupported ? "ready" : "unavailable",
          );
          return;
        }
        if (payload.type === "oc.inner_os.ack") {
          const status =
            payload.status === "accepted" ? "delivered" : "error";
          this.setInnerOsStatus(status);
          return;
        }
        if (
          typeof payload.type === "string" &&
          ALLOWED_DEVICE_EVENTS.has(payload.type)
        ) {
          this.turnContext.observeClient(payload);
          upstream.send(event.data);
          if (payload.type === "response.cancel") {
            this.invalidateInnerOs();
            this.peers.sendViewerJson({ type: "playback.clear" });
          }
        }
      } catch {
        // malformed device frames are ignored
      }
    });

    upstream.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      if (server.readyState === WebSocket.OPEN) {
        server.send(event.data);
      }
      try {
        const payload = JSON.parse(event.data) as Record<string, unknown>;
        this.turnContext.observeServer(payload);
        if (payload.type === "session.created") {
          upstream.send(
            JSON.stringify({
              event_id: `session_${crypto.randomUUID()}`,
              type: "session.update",
              session: {
                modalities: ["text", "audio"],
                instructions: character.instructions,
                voice: character.voice,
                input_audio_format: "pcm16",
                output_audio_format: "pcm16",
                turn_detection: {
                  type: "server_vad",
                  prefix_padding_ms: 300,
                  silence_duration_ms: 350,
                },
              },
            }),
          );
        }
        if (payload.type === "input_audio_buffer.speech_started") {
          this.invalidateInnerOs();
        }
        if (
          payload.type === "response.audio_transcript.done"
          && typeof payload.transcript === "string"
        ) {
          const turn = this.turnContext.snapshot();
          this.trackInnerOsTask(
            this.turnContext
              .waitForUserText(turn)
              .then(async (userText) => {
                if (userText === undefined) return;
                const decisionContext = this.pendingDecision.take();
                await this.submitInnerOs({
                  character: character.id,
                  userText,
                  publicText: payload.transcript as string,
                  ...(decisionContext ? { decisionContext } : {}),
                });
              }),
          );
        }
        for (const frame of viewerFramesForStepEvent(payload)) {
          if (frame.kind === "json") {
            this.peers.sendViewerJson(frame.value);
          } else {
            this.peers.sendViewerBinary(frame.value);
          }
        }
      } catch {
        // Orange Pi still receives the original upstream frame.
      }
    });

    server.addEventListener("close", () => closeDevice());
    server.addEventListener("error", () =>
      closeDevice(1011, "device_socket_error"),
    );
    upstream.addEventListener("close", () =>
      closeDevice(1011, "upstream_closed"),
    );
    upstream.addEventListener("error", () =>
      closeDevice(1011, "upstream_socket_error"),
    );

    return new Response(null, { status: 101, webSocket: client });
  }

  private connectViewer(): Response {
    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair) as [
      WebSocket,
      WebSocket,
    ];
    server.accept();
    const admission = this.peers.attachViewer(server);
    if (admission === "ready") {
      this.pendingDecision = new PendingInnerOsDecision();
      this.viewerSocket = server;
      this.clearViewerTimer();
      this.viewerTimer = setTimeout(() => {
        if (this.viewerSocket !== server) return;
        this.peers.detachViewer(server);
        this.viewerSocket = undefined;
        server.close(1000, "viewer_session_limit");
      }, SESSION_LIMIT_MS);
      this.sendInnerOsStatusToViewer();
    }

    const release = () => {
      if (this.viewerSocket !== server) return;
      this.peers.detachViewer(server);
      this.viewerSocket = undefined;
      this.pendingDecision = new PendingInnerOsDecision();
      this.clearViewerTimer();
    };
    server.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      try {
        const context = parseInnerOsDecisionFrame(
          JSON.parse(event.data),
        );
        if (context) this.pendingDecision.set(context);
      } catch {
        // Invalid owner context never reaches the model.
      }
    });
    server.addEventListener("close", release);
    server.addEventListener("error", release);
    return new Response(null, { status: 101, webSocket: client });
  }

  private clearViewerTimer(): void {
    if (this.viewerTimer) clearTimeout(this.viewerTimer);
    this.viewerTimer = undefined;
  }

  private async handleInnerOsInternalRequest(
    request: Request,
    url: URL,
  ): Promise<Response> {
    if (url.pathname === "/internal/inner-os/status") {
      return Response.json(
        { inner_os: this.innerOsStatus },
        { headers: { "cache-control": "no-store" } },
      );
    }
    if (
      url.pathname === "/internal/inner-os/cancel"
      && request.method === "POST"
    ) {
      this.invalidateInnerOs();
      return new Response(null, { status: 204 });
    }
    if (
      url.pathname !== "/internal/inner-os"
      || request.method !== "POST"
    ) {
      return Response.json({ error: "not_found" }, { status: 404 });
    }

    let value: unknown;
    try {
      value = await request.json();
    } catch {
      return Response.json({ error: "invalid_json" }, { status: 400 });
    }
    if (!value || typeof value !== "object") {
      return Response.json({ error: "invalid_inner_os_input" }, { status: 400 });
    }
    const input = value as Record<string, unknown>;
    let character;
    try {
      character = getCharacter(
        typeof input.character === "string" ? input.character : "",
      );
    } catch {
      return Response.json({ error: "unknown_character" }, { status: 400 });
    }
    if (
      typeof input.userText !== "string"
      || typeof input.publicText !== "string"
      || !input.publicText.trim()
    ) {
      return Response.json({ error: "invalid_inner_os_input" }, { status: 400 });
    }

    let decisionContext;
    try {
      decisionContext = parseInnerOsDecisionContext(
        input.decisionContext,
      );
    } catch {
      return Response.json(
        { error: "invalid_decision_context" },
        { status: 400 },
      );
    }

    const result = await this.submitInnerOs({
      character: character.id,
      userText: input.userText,
      publicText: input.publicText,
      ...(decisionContext ? { decisionContext } : {}),
    });
    return Response.json(result, {
      headers: { "cache-control": "no-store" },
    });
  }

  private invalidateInnerOs(): void {
    this.innerOsRevision += 1;
  }

  private setInnerOsStatus(status: InnerOsStatus): void {
    this.innerOsStatus = status;
    this.sendInnerOsStatusToViewer();
  }

  private sendInnerOsStatusToViewer(): void {
    this.peers.sendViewerJson({
      type: "inner_os.status",
      status: this.innerOsStatus,
    });
  }

  private trackInnerOsTask(task: Promise<void>): void {
    this.innerOsTasks.add(task);
    void task
      .catch(() => {
        this.setInnerOsStatus(
          this.innerOsSupported ? "ready" : "unavailable",
        );
      })
      .finally(() => this.innerOsTasks.delete(task));
  }

  private async submitInnerOs(
    input: InnerOsInput,
  ): Promise<{
    status: InnerOsStatus;
    generationSource?: GeneratedInnerOs["source"];
  }> {
    if (
      !this.innerOsSupported
      || !this.deviceSocket
      || this.deviceSocket.readyState !== WebSocket.OPEN
    ) {
      this.setInnerOsStatus("unavailable");
      return { status: "unavailable" };
    }

    const revision = ++this.innerOsRevision;
    const generated = await generateInnerOs(
      this.env.STEPFUN_API_KEY,
      input,
    );
    if (
      revision !== this.innerOsRevision
      || !this.innerOsSupported
      || !this.deviceSocket
      || this.deviceSocket.readyState !== WebSocket.OPEN
    ) {
      return { status: this.innerOsStatus };
    }

    this.deviceSocket.send(JSON.stringify(
      buildInnerOsDeviceEvent(input.character, generated),
    ));
    this.setInnerOsStatus("sent");
    return {
      status: "sent",
      generationSource: generated.source,
    };
  }
}

export default {
  fetch(request, env): Response | Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return Response.json({ status: "ok", service: "oc-device-relay" });
    }
    if (
      url.pathname !== "/api/device/realtime" &&
      url.pathname !== "/api/device/view"
    ) {
      return Response.json({ error: "not_found" }, { status: 404 });
    }
    let deviceId;
    try {
      deviceId = parseDeviceId(url.searchParams.get("deviceId"));
    } catch {
      return Response.json({ error: "invalid_device_id" }, { status: 400 });
    }
    const id = env.DEVICE_ROOMS.idFromName(deviceId);
    return env.DEVICE_ROOMS.get(id).fetch(request);
  },
} satisfies ExportedHandler<RelayEnv>;

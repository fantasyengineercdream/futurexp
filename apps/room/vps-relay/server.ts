import { timingSafeEqual } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { createServer, type IncomingMessage, type Server } from "node:http";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";
import WebSocket, { WebSocketServer } from "ws";
import {
  getCharacter,
  type CharacterConfig,
  type CharacterId,
} from "../src/characters";
import {
  dynamicVoiceInstructions,
  parseDynamicVoiceProfile,
} from "../src/registered-oc";
import {
  buildInnerOsDeviceEvent,
  generateInnerOs,
  parseInnerOsDecisionFrame,
  PendingInnerOsDecision,
  type GeneratedInnerOs,
  type InnerOsInput,
} from "../relay-worker/src/inner-os";
import {
  parseDeviceId,
  viewerFramesForStepEvent,
} from "../relay-worker/src/protocol";
import { RealtimeTurnContext } from "../relay-worker/src/turn-context";
import {
  RoomConnectionPolicy,
  type AudioSourceKind,
} from "./room-policy";
import { resolveStaticFile } from "./static-path";

type InnerOsGenerator = (
  input: InnerOsInput,
) => Promise<GeneratedInnerOs>;

type RealtimeCharacterConfig = Pick<
  CharacterConfig,
  "id" | "name" | "voice" | "instructions"
> & { id: string };

function isStaticCharacterId(value: string): value is CharacterId {
  return value === "angel" || value === "devil";
}

function realtimeCharacterForUrl(
  url: URL,
  kind: AudioSourceKind,
): RealtimeCharacterConfig {
  const fallback = getCharacter(url.searchParams.get("character") ?? "");
  if (kind !== "browser") return fallback;
  const dynamic = parseDynamicVoiceProfile(url.searchParams.get("ocProfile"));
  if (!dynamic) return fallback;
  return {
    id: dynamic.id,
    name: dynamic.name,
    voice: fallback.voice,
    instructions: dynamicVoiceInstructions(dynamic),
  };
}

export interface VpsRelayOptions {
  staticDir: string;
  stepfunUrl: string;
  stepfunApiKey: string;
  deviceToken: string;
  innerOsGenerator: InnerOsGenerator;
}

const FORWARDED_EVENTS = new Set([
  "input_audio_buffer.append",
  "input_audio_buffer.clear",
  "conversation.item.create",
  "response.create",
  "response.cancel",
]);

const MIME_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

function json(
  response: import("node:http").ServerResponse,
  status: number,
  value: unknown,
): void {
  const body = JSON.stringify(value);
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  response.end(body);
}

function authorized(request: IncomingMessage, expected: string): boolean {
  const supplied =
    request.headers.authorization?.replace(/^Bearer\s+/i, "") ?? "";
  const left = Buffer.from(supplied);
  const right = Buffer.from(expected.trim());
  return (
    left.length > 0
    && left.length === right.length
    && timingSafeEqual(left, right)
  );
}

class SharedRealtimeRoom {
  private readonly policy = new RoomConnectionPolicy();
  private upstream?: WebSocket;
  private browser?: WebSocket;
  private device?: WebSocket;
  private browserCharacter?: RealtimeCharacterConfig;
  private deviceCharacter?: RealtimeCharacterConfig;
  private viewer?: WebSocket;
  private innerOsSupported = false;
  private innerOsStatus:
    | "unavailable"
    | "ready"
    | "sent"
    | "delivered"
    | "error" = "unavailable";
  private readonly turnContext = new RealtimeTurnContext();
  private readonly pendingDecision = new PendingInnerOsDecision();
  private readonly pendingInnerOsDeliveries = new Map<
    string,
    {
      character: CharacterId;
      publicReply: string;
      privateInnerOs: string;
    }
  >();
  private readonly queuedUpstreamMessages: string[] = [];
  private reconnectTimer?: ReturnType<typeof setTimeout>;
  private reconnectAttempt = 0;

  constructor(
    private readonly options: VpsRelayOptions,
    private readonly onEmpty: () => void,
  ) {}

  attachSource(
    kind: AudioSourceKind,
    socket: WebSocket,
    character: RealtimeCharacterConfig,
  ): void {
    const connectionId = crypto.randomUUID();
    const admission = this.policy.attachSource(kind, connectionId);
    if (!admission.accepted) {
      socket.send(JSON.stringify({
        type: "session.busy",
        code: admission.reason,
      }));
      socket.close(4409, admission.reason);
      return;
    }

    if (kind === "browser") {
      this.browser = socket;
      this.browserCharacter = character;
    } else {
      this.device = socket;
      this.deviceCharacter = character;
    }
    if (admission.openUpstream) this.openUpstream();
    this.configureCharacter(character);

    socket.on("message", (value, isBinary) => {
      if (isBinary) return;
      const text = String(value);
      try {
        const payload = JSON.parse(text) as Record<string, unknown>;
        if (kind === "device" && payload.type === "oc.capabilities") {
          this.innerOsSupported =
            Array.isArray(payload.capabilities)
            && payload.capabilities.includes("inner_os.v1");
          this.setInnerOsStatus(
            this.innerOsSupported ? "ready" : "unavailable",
          );
          return;
        }
        if (kind === "device" && payload.type === "oc.inner_os.ack") {
          const eventId = typeof payload.event_id === "string"
            ? payload.event_id
            : "";
          const delivery = this.pendingInnerOsDeliveries.get(eventId);
          if (!delivery) return;
          this.pendingInnerOsDeliveries.delete(eventId);
          if (payload.status === "accepted") {
            this.sendInnerOsDelivery(delivery);
            this.setInnerOsStatus("delivered");
          } else {
            this.setInnerOsStatus("error");
          }
          return;
        }
        const decisionContext = parseInnerOsDecisionFrame(payload);
        if (decisionContext) {
          this.pendingDecision.set(decisionContext);
          return;
        }
        if (this.policy.activeSource !== kind) return;
        this.turnContext.observeClient(payload);
        if (payload.type && FORWARDED_EVENTS.has(payload.type)) {
          this.sendUpstream(text);
        }
      } catch {
        // Ignore malformed client frames.
      }
    });
    socket.on("close", () => {
      if (kind === "browser" && this.browser === socket) {
        this.browser = undefined;
        this.browserCharacter = undefined;
      }
      if (kind === "device" && this.device === socket) {
        this.device = undefined;
        this.deviceCharacter = undefined;
        this.innerOsSupported = false;
        this.pendingInnerOsDeliveries.clear();
        this.setInnerOsStatus("unavailable");
        if (this.viewer?.readyState === WebSocket.OPEN) {
          this.viewer.send(JSON.stringify({
            type: "device.offline",
            code: "device_unavailable",
          }));
          this.viewer.close(4410, "device_unavailable");
        }
        this.viewer = undefined;
      }
      const detached = this.policy.detachSource(kind, connectionId);
      if (detached.closeUpstream) {
        this.clearReconnectTimer();
        this.queuedUpstreamMessages.length = 0;
        this.upstream?.close(1000, "room_empty");
        this.upstream = undefined;
        this.onEmpty();
        return;
      }
      const nextCharacter =
        detached.activeSource === "browser"
          ? this.browserCharacter
          : this.deviceCharacter;
      if (nextCharacter) this.configureCharacter(nextCharacter);
    });
  }

  attachViewer(socket: WebSocket): void {
    const connectionId = crypto.randomUUID();
    if (!this.device || this.device.readyState !== WebSocket.OPEN) {
      socket.send(JSON.stringify({
        type: "device.offline",
        code: "device_unavailable",
      }));
      socket.close(4410, "device_unavailable");
      return;
    }
    const admission = this.policy.attachViewer(connectionId);
    if (!admission.accepted) {
      socket.send(JSON.stringify({
        type: "session.busy",
        code: admission.reason,
      }));
      socket.close(4409, admission.reason);
      return;
    }
    this.viewer = socket;
    socket.send(JSON.stringify({
      type: "session.ready",
      status: "acquired",
    }));
    this.sendInnerOsStatus(socket);
    socket.on("message", (value, isBinary) => {
      if (isBinary) return;
      try {
        const decisionContext = parseInnerOsDecisionFrame(
          JSON.parse(String(value)),
        );
        if (decisionContext) this.pendingDecision.set(decisionContext);
      } catch {
        // Invalid private context never reaches a model.
      }
    });
    socket.on("close", () => {
      if (this.viewer === socket) this.viewer = undefined;
      this.policy.detachViewer(connectionId);
    });
  }

  status(): { inner_os: typeof this.innerOsStatus } {
    return { inner_os: this.innerOsStatus };
  }

  private openUpstream(): void {
    if (
      this.upstream
      && (
        this.upstream.readyState === WebSocket.OPEN
        || this.upstream.readyState === WebSocket.CONNECTING
      )
    ) {
      return;
    }
    const upstream = new WebSocket(this.options.stepfunUrl, {
      headers: {
        Authorization: `Bearer ${this.options.stepfunApiKey.trim()}`,
      },
    });
    this.upstream = upstream;
    upstream.on("open", () => {
      this.reconnectAttempt = 0;
      this.clearReconnectTimer();
      for (const message of this.queuedUpstreamMessages.splice(0)) {
        upstream.send(message);
      }
    });
    upstream.on("message", (value, isBinary) => {
      if (isBinary) return;
      const text = String(value);
      try {
        const payload = JSON.parse(text) as Record<string, unknown>;
        this.turnContext.observeServer(payload);
        if (payload.type === "session.created") {
          const character =
            this.policy.activeSource === "browser"
              ? this.browserCharacter
              : this.deviceCharacter;
          if (character) this.configureCharacter(character);
        }
        if (
          payload.type === "response.audio_transcript.done"
          && typeof payload.transcript === "string"
        ) {
          const character =
            this.policy.activeSource === "browser"
              ? this.browserCharacter
              : this.deviceCharacter;
          const turn = this.turnContext.snapshot();
          if (character && isStaticCharacterId(character.id)) {
            void this.turnContext
              .waitForUserText(turn)
              .then(async (userText) => {
                if (userText === undefined) return;
                const decisionContext = this.pendingDecision.take();
                await this.generateAndSendInnerOs({
                  character: character.id,
                  userText,
                  publicText: payload.transcript as string,
                  ...(decisionContext ? { decisionContext } : {}),
                });
              });
          }
        }
        if (
          this.policy.activeSource === "device"
          && this.viewer?.readyState === WebSocket.OPEN
        ) {
          for (const frame of viewerFramesForStepEvent(payload)) {
            this.viewer.send(
              frame.kind === "json"
                ? JSON.stringify(frame.value)
                : frame.value,
            );
          }
        }
      } catch {
        // Raw upstream frames are still forwarded.
      }
      const target =
        this.policy.activeSource === "browser"
          ? this.browser
          : this.device;
      if (target?.readyState === WebSocket.OPEN) target.send(text);
    });
    upstream.on("close", () => {
      if (this.upstream !== upstream) return;
      this.upstream = undefined;
      const character =
        this.policy.activeSource === "browser"
          ? this.browserCharacter
          : this.deviceCharacter;
      if (!character) return;
      this.configureCharacter(character);
      this.scheduleReconnect();
    });
    upstream.on("error", () => {
      const target =
        this.policy.activeSource === "browser"
          ? this.browser
          : this.device;
      if (target?.readyState === WebSocket.OPEN) {
        target.send(JSON.stringify({
          type: "error",
          error: { message: "StepFun Realtime 上游连接失败" },
        }));
      }
    });
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || !this.policy.activeSource) return;
    const delay = Math.min(1_000 * (2 ** this.reconnectAttempt), 10_000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      if (!this.policy.activeSource || this.upstream) return;
      this.openUpstream();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = undefined;
  }

  private async generateAndSendInnerOs(input: InnerOsInput): Promise<void> {
    if (
      !this.innerOsSupported
      || !this.device
      || this.device.readyState !== WebSocket.OPEN
    ) {
      this.setInnerOsStatus("unavailable");
      return;
    }
    try {
      const generated = await this.options.innerOsGenerator(input);
      if (
        !this.innerOsSupported
        || !this.device
        || this.device.readyState !== WebSocket.OPEN
      ) {
        return;
      }
      const deviceEvent = buildInnerOsDeviceEvent(input.character, generated);
      this.pendingInnerOsDeliveries.set(deviceEvent.event_id, {
        character: input.character,
        publicReply: input.publicText,
        privateInnerOs: generated.text,
      });
      this.device.send(JSON.stringify(deviceEvent));
      this.setInnerOsStatus("sent");
    } catch {
      this.setInnerOsStatus("error");
    }
  }

  private setInnerOsStatus(
    status: typeof this.innerOsStatus,
  ): void {
    this.innerOsStatus = status;
    this.sendInnerOsStatus(this.browser);
    this.sendInnerOsStatus(this.viewer);
  }

  private sendInnerOsStatus(socket?: WebSocket): void {
    if (socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({
      type: "inner_os.status",
      status: this.innerOsStatus,
    }));
  }

  private sendInnerOsDelivery(delivery: {
    character: CharacterId;
    publicReply: string;
    privateInnerOs: string;
  }): void {
    const message = JSON.stringify({
      type: "inner_os.delivered",
      ...delivery,
    });
    if (this.browser?.readyState === WebSocket.OPEN) {
      this.browser.send(message);
    }
    if (this.viewer?.readyState === WebSocket.OPEN) {
      this.viewer.send(message);
    }
  }

  private configureCharacter(character: RealtimeCharacterConfig): void {
    this.sendUpstream(JSON.stringify({
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
    }));
  }

  private sendUpstream(message: string): void {
    if (this.upstream?.readyState === WebSocket.OPEN) {
      this.upstream.send(message);
      return;
    }
    this.queuedUpstreamMessages.push(message);
  }
}

async function serveStatic(
  request: IncomingMessage,
  response: import("node:http").ServerResponse,
  staticDir: string,
): Promise<void> {
  if (request.method !== "GET" && request.method !== "HEAD") {
    json(response, 405, { error: "method_not_allowed" });
    return;
  }
  const url = new URL(request.url ?? "/", "http://localhost");
  const pathname = decodeURIComponent(url.pathname);
  let filePath = resolveStaticFile(staticDir, pathname);
  if (!filePath) {
    json(response, 404, { error: "not_found" });
    return;
  }
  try {
    if (!(await stat(filePath)).isFile()) throw new Error("not_file");
  } catch {
    filePath = join(staticDir, "index.html");
  }
  const body = await readFile(filePath);
  response.writeHead(200, {
    "content-type":
      MIME_TYPES[extname(filePath).toLowerCase()]
      ?? "application/octet-stream",
    "content-length": body.length,
  });
  response.end(request.method === "HEAD" ? undefined : body);
}

export function createVpsRelay(options: VpsRelayOptions): Server {
  const rooms = new Map<string, SharedRealtimeRoom>();
  const websocketServer = new WebSocketServer({ noServer: true });
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    if (url.pathname === "/api/health") {
      json(response, 200, {
        status: "ok",
        service: "oc-voice-vps-relay",
      });
      return;
    }
    if (url.pathname === "/api/device/status") {
      try {
        const deviceId = parseDeviceId(url.searchParams.get("deviceId"));
        json(
          response,
          200,
          rooms.get(deviceId)?.status() ?? { inner_os: "unavailable" },
        );
      } catch {
        json(response, 400, { error: "invalid_device_id" });
      }
      return;
    }
    void serveStatic(request, response, options.staticDir).catch(() => {
      if (!response.headersSent) {
        json(response, 500, { error: "static_read_failed" });
      } else {
        response.end();
      }
    });
  });

  server.on("upgrade", (request, socket, head) => {
    const url = new URL(request.url ?? "/", "http://localhost");
    const kind: AudioSourceKind | "viewer" | undefined =
      url.pathname === "/api/realtime"
        ? "browser"
        : url.pathname === "/api/device/realtime"
          ? "device"
          : url.pathname === "/api/device/view"
            ? "viewer"
            : undefined;
    if (!kind) {
      socket.write("HTTP/1.1 404 Not Found\r\nConnection: close\r\n\r\n");
      socket.destroy();
      return;
    }
    if (kind === "device" && !authorized(request, options.deviceToken)) {
      socket.write("HTTP/1.1 401 Unauthorized\r\nConnection: close\r\n\r\n");
      socket.destroy();
      return;
    }

    let deviceId: string;
    let character: RealtimeCharacterConfig | undefined;
    try {
      deviceId = parseDeviceId(
        url.searchParams.get("deviceId") ?? "orangepi-3b-01",
      );
      if (kind !== "viewer") {
        character = realtimeCharacterForUrl(url, kind);
      }
    } catch {
      socket.write("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n");
      socket.destroy();
      return;
    }
    websocketServer.handleUpgrade(request, socket, head, (client) => {
      let room = rooms.get(deviceId);
      if (!room) {
        room = new SharedRealtimeRoom(
          options,
          () => rooms.delete(deviceId),
        );
        rooms.set(deviceId, room);
      }
      if (kind === "viewer") {
        room.attachViewer(client);
      } else {
        room.attachSource(kind, client, character!);
      }
    });
  });
  return server;
}

function runtimeOptions(): VpsRelayOptions {
  const staticDir =
    process.env.OC_STATIC_DIR
    ?? fileURLToPath(new URL("../dist", import.meta.url));
  const stepfunApiKey = process.env.STEPFUN_API_KEY?.trim() ?? "";
  const deviceToken = process.env.OC_DEVICE_TOKEN?.trim() ?? "";
  if (!stepfunApiKey || !deviceToken) {
    throw new Error("STEPFUN_API_KEY and OC_DEVICE_TOKEN are required");
  }
  return {
    staticDir,
    stepfunApiKey,
    deviceToken,
    stepfunUrl:
      process.env.STEPFUN_REALTIME_URL
      ?? "wss://api.stepfun.com/step_plan/v1/realtime"
        + "?model=stepaudio-2.5-realtime",
    innerOsGenerator: (input) => generateInnerOs(stepfunApiKey, input),
  };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT ?? "8765");
  createVpsRelay(runtimeOptions()).listen(port, "127.0.0.1", () => {
    console.log(`oc-voice-vps-relay listening on 127.0.0.1:${port}`);
  });
}

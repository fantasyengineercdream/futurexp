import { PcmPlayback } from "./audio";
import type { InnerOsDecisionContext } from "../relay-worker/src/inner-os";
import { buildDecisionContextEvent } from "./realtime";

export const DEFAULT_DEVICE_ID = "orangepi-3b-01";
export type InnerOsStatus =
  | "unavailable"
  | "ready"
  | "sent"
  | "delivered"
  | "error";

export type RingSinkMessage =
  | { type: "session.ready"; status: "acquired" }
  | { type: "session.busy"; code: "ring_in_use" }
  | { type: "device.offline"; code: "device_unavailable" }
  | { type: "state"; phase: string }
  | {
      type: "transcript";
      role: "user" | "assistant";
      text: string;
    }
  | { type: "inner_os.status"; status: InnerOsStatus }
  | {
      type: "inner_os.delivered";
      character: "angel" | "devil";
      publicReply: string;
      privateInnerOs: string;
    }
  | { type: "playback.clear" };

export interface RingBridgeCallbacks {
  onConnected: () => void;
  onReady: () => void;
  onBusy: () => void;
  onOffline: () => void;
  onClosed: () => void;
  onError: (message: string) => void;
  onState: (phase: string) => void;
  onTranscript: (role: "user" | "assistant", text: string) => void;
  onInnerOsStatus: (status: InnerOsStatus) => void;
  onInnerOsDelivered: (delivery: {
    character: "angel" | "devil";
    publicReply: string;
    privateInnerOs: string;
  }) => void;
}

export function buildRingViewUrl(
  origin: string,
  deviceId: string,
): string {
  const url = new URL(origin);
  if (url.protocol === "http:") url.protocol = "ws:";
  if (url.protocol === "https:") url.protocol = "wss:";
  if (url.protocol !== "ws:" && url.protocol !== "wss:") {
    throw new Error("云端中继地址必须使用 http、https、ws 或 wss");
  }
  url.pathname = "/api/device/view";
  url.search = new URLSearchParams({ deviceId }).toString();
  url.hash = "";
  return url.toString();
}

export function ringReconnectDelayMs(attempt: number): number {
  const safeAttempt = Number.isFinite(attempt)
    ? Math.max(0, Math.floor(attempt))
    : 0;
  return Math.min(1_000 * (2 ** safeAttempt), 10_000);
}

export function resolveDeviceId(search: string): string {
  const value =
    new URLSearchParams(search).get("deviceId")?.trim()
    || DEFAULT_DEVICE_ID;
  if (!/^[a-z0-9][a-z0-9-]{2,63}$/.test(value)) {
    throw new Error("invalid_device_id");
  }
  return value;
}

export function describeRingConnectionError(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return `无法连接云端设备中继：${error.message.trim()}`;
  }
  return "无法连接云端设备中继，请稍后重试。";
}

export function parseRingSinkMessage(
  value: string,
): RingSinkMessage | undefined {
  try {
    const message = JSON.parse(value) as Record<string, unknown>;
    if (
      message.type === "session.ready" &&
      message.status === "acquired"
    ) {
      return { type: "session.ready", status: "acquired" };
    }
    if (
      message.type === "session.busy" &&
      message.code === "ring_in_use"
    ) {
      return { type: "session.busy", code: "ring_in_use" };
    }
    if (
      message.type === "device.offline"
      && message.code === "device_unavailable"
    ) {
      return { type: "device.offline", code: "device_unavailable" };
    }
    if (
      message.type === "state" &&
      typeof message.phase === "string" &&
      message.phase.length > 0
    ) {
      return { type: "state", phase: message.phase };
    }
    if (
      message.type === "transcript" &&
      (message.role === "user" || message.role === "assistant") &&
      typeof message.text === "string"
    ) {
      return {
        type: "transcript",
        role: message.role,
        text: message.text,
      };
    }
    if (message.type === "playback.clear") {
      return { type: "playback.clear" };
    }
    if (
      message.type === "inner_os.status"
      && (
        message.status === "unavailable"
        || message.status === "ready"
        || message.status === "sent"
        || message.status === "delivered"
        || message.status === "error"
      )
    ) {
      return {
        type: "inner_os.status",
        status: message.status,
      };
    }
    if (
      message.type === "inner_os.delivered"
      && (message.character === "angel" || message.character === "devil")
      && typeof message.publicReply === "string"
      && message.publicReply.trim().length > 0
      && typeof message.privateInnerOs === "string"
      && message.privateInnerOs.trim().length > 0
    ) {
      return {
        type: "inner_os.delivered",
        character: message.character,
        publicReply: message.publicReply,
        privateInnerOs: message.privateInnerOs,
      };
    }
  } catch {
    return undefined;
  }
  return undefined;
}

export async function emitRingStateAfterPlayback(
  phase: string,
  waitForPlaybackIdle: () => Promise<void>,
  emit: (phase: string) => void,
): Promise<void> {
  if (phase !== "idle") {
    emit(phase);
    return;
  }
  await waitForPlaybackIdle();
  emit("listening");
}

export class RingAudioBridge {
  private socket?: WebSocket;
  private playback?: PcmPlayback;
  private opened = false;
  private stateRevision = 0;

  constructor(
    private readonly origin: string,
    private readonly deviceId: string,
  ) {}

  connect(callbacks: RingBridgeCallbacks): Promise<void> {
    return new Promise((resolve, reject) => {
      this.playback = new PcmPlayback();
      const socket = new WebSocket(
        buildRingViewUrl(this.origin, this.deviceId),
      );
      socket.binaryType = "arraybuffer";
      this.socket = socket;

      socket.addEventListener("open", () => {
        this.opened = true;
        callbacks.onConnected();
        resolve();
      });
      socket.addEventListener("message", (event) => {
        if (event.data instanceof ArrayBuffer) {
          void this.playback?.enqueuePcm16(event.data);
          return;
        }
        if (typeof event.data !== "string") return;
        const message = parseRingSinkMessage(event.data);
        if (message?.type === "session.ready") {
          callbacks.onReady();
        } else if (message?.type === "session.busy") {
          callbacks.onBusy();
        } else if (message?.type === "device.offline") {
          callbacks.onOffline();
        } else if (message?.type === "playback.clear") {
          this.playback?.clear();
        } else if (message?.type === "state") {
          const revision = ++this.stateRevision;
          void emitRingStateAfterPlayback(
            message.phase,
            () => this.playback?.whenIdle() ?? Promise.resolve(),
            (phase) => {
              if (revision === this.stateRevision) {
                callbacks.onState(phase);
              }
            },
          );
        } else if (message?.type === "transcript") {
          callbacks.onTranscript(message.role, message.text);
        } else if (message?.type === "inner_os.status") {
          callbacks.onInnerOsStatus(message.status);
        } else if (message?.type === "inner_os.delivered") {
          callbacks.onInnerOsDelivered(message);
        }
      });
      socket.addEventListener("error", () => {
        const message =
          "无法连接云端设备中继，请稍后重试。";
        callbacks.onError(message);
        if (!this.opened) reject(new Error(message));
      });
      socket.addEventListener("close", () => {
        this.opened = false;
        callbacks.onClosed();
      });
    });
  }

  async close(): Promise<void> {
    this.stateRevision += 1;
    this.socket?.close(1000, "user ended ring session");
    this.socket = undefined;
    await this.playback?.close();
    this.playback = undefined;
    this.opened = false;
  }

  setDecisionContext(context: InnerOsDecisionContext): void {
    if (this.socket?.readyState !== WebSocket.OPEN) return;
    this.socket.send(JSON.stringify(buildDecisionContextEvent(context)));
  }

}

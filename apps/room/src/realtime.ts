import type { CharacterId } from "./characters";
import type { InnerOsDecisionContext } from "../relay-worker/src/inner-os";
import type { DynamicVoiceProfile } from "./registered-oc";

export type RealtimeEvent = { type: string; [key: string]: unknown };
export type FinalDialogue = {
  role: "user" | "assistant";
  text: string;
};

export function buildDecisionContextEvent(
  decisionContext: InnerOsDecisionContext,
): object {
  return {
    type: "oc.decision_context",
    decisionContext,
  };
}

export function buildOpeningResponseEvent(openingText: string): object {
  return {
    event_id: crypto.randomUUID(),
    type: "response.create",
    session: {
      instructions: `请原样无修改地输出：${openingText.trim()}`,
    },
  };
}

export function buildTextTurnEvents(text: string): [object, object] {
  return [
    {
      event_id: crypto.randomUUID(),
      type: "conversation.item.create",
      item: { type: "message", role: "user", content: [{ type: "input_text", text }] },
    },
    {
      event_id: crypto.randomUUID(),
      type: "response.create",
      response: { modalities: ["text", "audio"] },
    },
  ];
}

export function uiCueForEvent(type: string): { phase: "你在说话" | "思考"; userText: string } | undefined {
  if (type === "input_audio_buffer.speech_started") {
    return { phase: "你在说话", userText: "正在听你说话…" };
  }
  if (type === "input_audio_buffer.speech_stopped") {
    return { phase: "思考", userText: "语音识别中…" };
  }
  return undefined;
}

export function finalDialogueForEvent(
  event: RealtimeEvent,
): FinalDialogue | undefined {
  const text =
    typeof event.transcript === "string"
      ? event.transcript.trim()
      : "";
  if (!text) return undefined;
  if (
    event.type
      === "conversation.item.input_audio_transcription.completed"
  ) {
    return { role: "user", text };
  }
  if (event.type === "response.audio_transcript.done") {
    return { role: "assistant", text };
  }
  return undefined;
}

export function shouldReplaceCurrentSubtitle(
  dialogue: FinalDialogue,
  assistantStarted: boolean,
): boolean {
  return dialogue.role === "assistant" || !assistantStarted;
}

export function describeStartError(error: unknown): string {
  if (error instanceof DOMException) {
    if (error.name === "NotAllowedError") {
      return "麦克风权限未开启。请允许此网站使用麦克风，然后点击“重试连接”。";
    }
    if (error.name === "NotFoundError") {
      return "没有找到可用麦克风。请连接麦克风后重试。";
    }
    if (error.name === "NotReadableError") {
      return "麦克风正被其他应用占用，请关闭占用后重试。";
    }
  }
  return error instanceof Error ? error.message : "无法启动实时语音，请重试。";
}

export function shouldRetrySilentResponse(hasAudio: boolean, retryCount: number): boolean {
  return !hasAudio && retryCount < 1;
}

export function shouldRetryTimedOutResponse(
  requestedAt: number,
  now: number,
  hasAudio: boolean,
  retryCount: number,
): boolean {
  return (
    requestedAt > 0
    && now - requestedAt >= 8_000
    && !hasAudio
    && retryCount < 1
  );
}

export function voiceStartupAfterReady(): {
  requestOpening: false;
  muted: false;
  phase: "正在聆听";
} {
  return {
    requestOpening: false,
    muted: false,
    phase: "正在聆听",
  };
}

export class RealtimeClient {
  private socket?: WebSocket;

  constructor(private readonly sessionReadyTimeoutMs = 12_000) {}

  connect(
    character: CharacterId,
    onEvent: (event: RealtimeEvent) => void,
    onClose: () => void,
    deviceId = "orangepi-3b-01",
    dynamicProfile?: DynamicVoiceProfile,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      let ready = false;
      let failed = false;
      const protocol = location.protocol === "https:" ? "wss:" : "ws:";
      const query = new URLSearchParams({ character, deviceId });
      if (dynamicProfile) {
        query.set("ocProfile", JSON.stringify(dynamicProfile));
      }
      this.socket = new WebSocket(
        `${protocol}//${location.host}/api/realtime?${query}`,
      );
      const socket = this.socket;
      const readyTimer = setTimeout(() => {
        if (ready || failed) return;
        failed = true;
        socket.close(1013, "session ready timeout");
        reject(new Error("语音会话准备超时，请重新连接。"));
      }, this.sessionReadyTimeoutMs);
      this.socket.addEventListener("message", (message) => {
        try {
          const event = JSON.parse(String(message.data)) as RealtimeEvent;
          onEvent(event);
          if (!ready && event.type === "session.updated") {
            ready = true;
            clearTimeout(readyTimer);
            resolve();
          }
        } catch { /* ignore malformed server event */ }
      });
      this.socket.addEventListener("error", () => {
        if (ready || failed) return;
        failed = true;
        clearTimeout(readyTimer);
        reject(new Error("语音网关连接失败"));
      });
      this.socket.addEventListener("close", () => {
        clearTimeout(readyTimer);
        if (!ready && !failed) {
          failed = true;
          reject(new Error("语音网关在会话准备完成前断开"));
          return;
        }
        if (ready) onClose();
      });
    });
  }

  sendAudio(audio: string): void {
    this.send({ event_id: crypto.randomUUID(), type: "input_audio_buffer.append", audio });
  }

  sendText(text: string): void {
    buildTextTurnEvents(text).forEach((event) => this.send(event));
  }

  requestResponse(): void {
    this.send({
      event_id: crypto.randomUUID(),
      type: "response.create",
      response: { modalities: ["text", "audio"] },
    });
  }

  requestOpening(openingText: string): void {
    this.send(buildOpeningResponseEvent(openingText));
  }

  setDecisionContext(context: InnerOsDecisionContext): void {
    this.send(buildDecisionContextEvent(context));
  }

  cancelResponse(): void { this.send({ event_id: crypto.randomUUID(), type: "response.cancel" }); }

  close(): void {
    this.socket?.close(1000, "user ended session");
    this.socket = undefined;
  }

  private send(payload: object): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(payload));
  }
}

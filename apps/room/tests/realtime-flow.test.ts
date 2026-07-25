import { afterEach, describe, expect, test, vi } from "vitest";
import * as realtime from "../src/realtime";

class FakeWebSocket {
  static readonly OPEN = 1;
  static latest?: FakeWebSocket;
  readyState = 0;
  closeCode?: number;
  closeReason?: string;
  private listeners = new Map<string, Array<(event: any) => void>>();

  constructor(public readonly url: string) {
    FakeWebSocket.latest = this;
  }

  addEventListener(type: string, listener: (event: any) => void): void {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type: string, event: any = {}): void {
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  close(code: number, reason: string): void {
    this.closeCode = code;
    this.closeReason = reason;
    this.emit("close", { code, reason });
  }

  send(): void {}
}

describe("realtime browser flow", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    FakeWebSocket.latest = undefined;
  });

  test("explicitly requests audio when a text turn starts", () => {
    expect(realtime.buildTextTurnEvents).toBeTypeOf("function");
    const events = realtime.buildTextTurnEvents("欢迎主人回来");
    expect(events[1]).toMatchObject({
      type: "response.create",
      response: { modalities: ["text", "audio"] },
    });
  });

  test("provides visible feedback while the user is speaking and being recognized", () => {
    expect(realtime.uiCueForEvent).toBeTypeOf("function");
    expect(realtime.uiCueForEvent("input_audio_buffer.speech_started")).toEqual({
      phase: "你在说话",
      userText: "正在听你说话…",
    });
    expect(realtime.uiCueForEvent("input_audio_buffer.speech_stopped")).toEqual({
      phase: "思考",
      userText: "语音识别中…",
    });
  });

  test("extracts only final user and assistant dialogue subtitles", () => {
    expect(
      realtime.finalDialogueForEvent({
        type:
          "conversation.item.input_audio_transcription.completed",
        transcript: "你今天开心吗？",
      }),
    ).toEqual({ role: "user", text: "你今天开心吗？" });
    expect(
      realtime.finalDialogueForEvent({
        type: "response.audio_transcript.done",
        transcript: "才没有特意等你。",
      }),
    ).toEqual({ role: "assistant", text: "才没有特意等你。" });
    expect(
      realtime.finalDialogueForEvent({
        type: "response.created",
      }),
    ).toBeUndefined();
  });

  test("does not let a late user ASR overwrite an assistant subtitle", () => {
    expect(
      realtime.shouldReplaceCurrentSubtitle(
        { role: "user", text: "迟到的用户字幕" },
        true,
      ),
    ).toBe(false);
    expect(
      realtime.shouldReplaceCurrentSubtitle(
        { role: "assistant", text: "角色回答" },
        true,
      ),
    ).toBe(true);
  });

  test("creates the opening without adding a fake user turn to conversation history", () => {
    const event = realtime.buildOpeningResponseEvent(
      "欢迎回来，主人。今天先聊点什么？",
    );
    expect(event).toMatchObject({
      type: "response.create",
      session: {
        instructions: expect.stringContaining(
          "请原样无修改地输出：欢迎回来，主人。今天先聊点什么？",
        ),
      },
    });
    expect(JSON.stringify(event)).not.toContain("conversation.item.create");
  });

  test("turns microphone failures into actionable Chinese messages", () => {
    expect(realtime.describeStartError).toBeTypeOf("function");
    expect(realtime.describeStartError(new DOMException("denied", "NotAllowedError"))).toContain("麦克风权限");
  });

  test("retries one silent response but never loops forever", () => {
    expect(realtime.shouldRetrySilentResponse).toBeTypeOf("function");
    expect(realtime.shouldRetrySilentResponse(false, 0)).toBe(true);
    expect(realtime.shouldRetrySilentResponse(false, 1)).toBe(false);
    expect(realtime.shouldRetrySilentResponse(true, 0)).toBe(false);
  });

  test("retries one response that produces no event before the watchdog expires", () => {
    expect(
      realtime.shouldRetryTimedOutResponse(1_000, 9_000, false, 0),
    ).toBe(true);
    expect(
      realtime.shouldRetryTimedOutResponse(1_000, 8_999, false, 0),
    ).toBe(false);
    expect(
      realtime.shouldRetryTimedOutResponse(1_000, 9_000, true, 0),
    ).toBe(false);
    expect(
      realtime.shouldRetryTimedOutResponse(1_000, 9_000, false, 1),
    ).toBe(false);
  });

  test("closes a half-open gateway session when StepFun never becomes ready", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("location", {
      protocol: "https:",
      host: "oc-voice-lab.pages.dev",
    });
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const client = new realtime.RealtimeClient(12_000);
    const connection = client.connect("devil", () => undefined, () => undefined);
    FakeWebSocket.latest?.emit("open");

    const rejection = expect(connection).rejects.toThrow(
      "语音会话准备超时，请重新连接",
    );
    await vi.advanceTimersByTimeAsync(12_001);
    await rejection;
    expect(FakeWebSocket.latest).toMatchObject({
      closeCode: 1013,
      closeReason: "session ready timeout",
    });
  });

  test("marks the gateway connected only after session.updated", async () => {
    vi.stubGlobal("location", {
      protocol: "https:",
      host: "oc-voice-lab.pages.dev",
    });
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const client = new realtime.RealtimeClient(12_000);
    const events: string[] = [];
    const connection = client.connect(
      "devil",
      (event) => events.push(event.type),
      () => undefined,
    );
    const socket = FakeWebSocket.latest;
    socket?.emit("open");
    socket?.emit("message", {
      data: JSON.stringify({ type: "session.updated" }),
    });

    await expect(connection).resolves.toBeUndefined();
    expect(events).toEqual(["session.updated"]);
  });

  test("hands a confirmed imported persona to the realtime relay", () => {
    vi.stubGlobal("location", {
      protocol: "https:",
      host: "room.example",
    });
    vi.stubGlobal("WebSocket", FakeWebSocket);
    const client = new realtime.RealtimeClient();
    const dynamicProfile = {
      id: "oc-imported-lan",
      name: "岚",
      role: "异常频道记者",
      persona: "认真但叛逆，会先核对证据。",
      publicStyle: "只说确认过的事实。",
      goals: ["调查异常频道"],
    };

    void client.connect(
      "angel",
      () => undefined,
      () => undefined,
      "orangepi-3b-01",
      dynamicProfile,
    );

    const url = new URL(FakeWebSocket.latest?.url ?? "");
    expect(url.searchParams.get("character")).toBe("angel");
    expect(JSON.parse(url.searchParams.get("ocProfile") ?? "{}")).toEqual(
      dynamicProfile,
    );
  });

  test("starts listening immediately instead of spending a realtime request on an opening", () => {
    expect(realtime.voiceStartupAfterReady()).toEqual({
      requestOpening: false,
      muted: false,
      phase: "正在聆听",
    });
  });
});

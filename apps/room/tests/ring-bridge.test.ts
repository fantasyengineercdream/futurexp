import { describe, expect, it } from "vitest";
import {
  buildRingViewUrl,
  describeRingConnectionError,
  emitRingStateAfterPlayback,
  parseRingSinkMessage,
  ringReconnectDelayMs,
  resolveDeviceId,
} from "../src/ring-bridge";

describe("Orange Pi ring bridge", () => {
  it("uses the same-origin cloud viewer route", () => {
    expect(
      buildRingViewUrl(
        "https://oc-voice-lab.pages.dev",
        "orangepi-3b-01",
      ),
    ).toBe(
      "wss://oc-voice-lab.pages.dev/api/device/view?deviceId=orangepi-3b-01",
    );
  });

  it("uses ws only for same-origin local HTTP development", () => {
    expect(
      buildRingViewUrl("http://127.0.0.1:5173", "orangepi-3b-01"),
    ).toBe(
      "ws://127.0.0.1:5173/api/device/view?deviceId=orangepi-3b-01",
    );
  });

  it("uses a stable default device id with a query override", () => {
    expect(resolveDeviceId("")).toBe("orangepi-3b-01");
    expect(resolveDeviceId("?deviceId=orangepi-3b-02")).toBe(
      "orangepi-3b-02",
    );
    expect(() => resolveDeviceId("?deviceId=../bad")).toThrow(
      "invalid_device_id",
    );
  });

  it("turns a synchronous WebSocket failure into a visible room error", () => {
    expect(
      describeRingConnectionError(
        new DOMException("Mixed Content", "SecurityError"),
      ),
    ).toBe("无法连接云端设备中继：Mixed Content");
    expect(describeRingConnectionError("unknown")).toBe(
      "无法连接云端设备中继，请稍后重试。",
    );
  });

  it("normalizes state, transcript, and playback clear messages", () => {
    expect(
      parseRingSinkMessage(
        '{"type":"session.ready","status":"acquired"}',
      ),
    ).toEqual({
      type: "session.ready",
      status: "acquired",
    });
    expect(
      parseRingSinkMessage(
        '{"type":"session.busy","code":"ring_in_use"}',
      ),
    ).toEqual({
      type: "session.busy",
      code: "ring_in_use",
    });
    expect(
      parseRingSinkMessage(
        '{"type":"device.offline","code":"device_unavailable"}',
      ),
    ).toEqual({
      type: "device.offline",
      code: "device_unavailable",
    });
    expect(
      parseRingSinkMessage('{"type":"state","phase":"speaking"}'),
    ).toEqual({
      type: "state",
      phase: "speaking",
    });
    expect(
      parseRingSinkMessage(
        '{"type":"transcript","role":"assistant","text":"欢迎回来"}',
      ),
    ).toEqual({
      type: "transcript",
      role: "assistant",
      text: "欢迎回来",
    });
    expect(parseRingSinkMessage('{"type":"playback.clear"}')).toEqual({
      type: "playback.clear",
    });
    expect(
      parseRingSinkMessage(
        '{"type":"inner_os.status","status":"delivered"}',
      ),
    ).toEqual({
      type: "inner_os.status",
      status: "delivered",
    });
    expect(
      parseRingSinkMessage(
        '{"type":"inner_os.delivered","character":"angel","publicReply":"我会认真考虑。","privateInnerOs":"最后仍由我自己判断。"}',
      ),
    ).toEqual({
      type: "inner_os.delivered",
      character: "angel",
      publicReply: "我会认真考虑。",
      privateInnerOs: "最后仍由我自己判断。",
    });
  });

  it("ignores malformed and unknown gateway messages", () => {
    expect(parseRingSinkMessage("bad json")).toBeUndefined();
    expect(parseRingSinkMessage('{"type":"unknown"}')).toBeUndefined();
    expect(
      parseRingSinkMessage('{"type":"transcript","role":"user","text":3}'),
    ).toBeUndefined();
  });

  it("does not announce listening until queued character audio has played", async () => {
    let releasePlayback!: () => void;
    const playbackDone = new Promise<void>((resolve) => {
      releasePlayback = resolve;
    });
    const phases: string[] = [];

    const pending = emitRingStateAfterPlayback(
      "idle",
      () => playbackDone,
      (phase) => phases.push(phase),
    );

    expect(phases).toEqual([]);
    releasePlayback();
    await pending;
    expect(phases).toEqual(["listening"]);
  });

  it("reports active ring phases immediately", async () => {
    const phases: string[] = [];
    let waited = false;

    await emitRingStateAfterPlayback(
      "speaking",
      async () => {
        waited = true;
      },
      (phase) => phases.push(phase),
    );

    expect(waited).toBe(false);
    expect(phases).toEqual(["speaking"]);
  });

  it("backs off transient ring-view reconnects and caps at ten seconds", () => {
    expect([
      ringReconnectDelayMs(0),
      ringReconnectDelayMs(1),
      ringReconnectDelayMs(2),
      ringReconnectDelayMs(3),
      ringReconnectDelayMs(4),
      ringReconnectDelayMs(9),
    ]).toEqual([1_000, 2_000, 4_000, 8_000, 10_000, 10_000]);
  });

});

import { describe, expect, test } from "vitest";
import {
  authorizeDevice,
  parseDeviceId,
  viewerFramesForStepEvent,
} from "../relay-worker/src/protocol";

describe("device relay protocol", () => {
  test("accepts only the configured bearer token", () => {
    const request = new Request("https://relay/api/device/realtime", {
      headers: { Authorization: "Bearer device-secret" },
    });
    expect(authorizeDevice(request, "device-secret")).toBe(true);
    expect(authorizeDevice(request, "other-secret")).toBe(false);
  });

  test("uses a bounded device id", () => {
    expect(parseDeviceId("orangepi-3b-01")).toBe("orangepi-3b-01");
    expect(() => parseDeviceId("../bad")).toThrow("invalid_device_id");
    expect(() => parseDeviceId(null)).toThrow("invalid_device_id");
  });

  test("maps final transcripts without exposing unrelated events", () => {
    expect(
      viewerFramesForStepEvent({
        type: "conversation.item.input_audio_transcription.completed",
        transcript: "你好",
      }),
    ).toEqual([
      {
        kind: "json",
        value: { type: "transcript", role: "user", text: "你好" },
      },
    ]);
    expect(
      viewerFramesForStepEvent({
        type: "response.audio_transcript.done",
        transcript: "欢迎回来",
      }),
    ).toEqual([
      {
        kind: "json",
        value: {
          type: "transcript",
          role: "assistant",
          text: "欢迎回来",
        },
      },
    ]);
    expect(
      viewerFramesForStepEvent({
        type: "response.thinking.delta",
        delta: "private",
      }),
    ).toEqual([]);
    expect(
      viewerFramesForStepEvent({
        type: "oc.inner_os",
        text: "这句只能发给墨水屏",
      }),
    ).toEqual([]);
  });

  test("maps speech phases and PCM16 audio", () => {
    expect(
      viewerFramesForStepEvent({
        type: "input_audio_buffer.speech_started",
      }),
    ).toEqual([
      {
        kind: "json",
        value: { type: "state", phase: "user_speaking" },
      },
      { kind: "json", value: { type: "playback.clear" } },
    ]);
    expect(
      viewerFramesForStepEvent({
        type: "input_audio_buffer.speech_stopped",
      }),
    ).toEqual([
      { kind: "json", value: { type: "state", phase: "thinking" } },
    ]);
    expect(
      viewerFramesForStepEvent({
        type: "response.audio.delta",
        delta: "AAECAw==",
      }),
    ).toEqual([
      { kind: "json", value: { type: "state", phase: "speaking" } },
      { kind: "binary", value: new Uint8Array([0, 1, 2, 3]) },
    ]);
    expect(viewerFramesForStepEvent({ type: "response.done" })).toEqual([
      { kind: "json", value: { type: "state", phase: "idle" } },
    ]);
  });

  test("rejects malformed Base64 audio", () => {
    expect(() =>
      viewerFramesForStepEvent({
        type: "response.audio.delta",
        delta: "***",
      }),
    ).toThrow("invalid_audio_delta");
  });
});

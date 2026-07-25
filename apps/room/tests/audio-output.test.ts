import { afterEach, describe, expect, test } from "vitest";
import {
  MICROPHONE_PROCESSOR_SIZE,
  PcmPlayback,
  PLAYBACK_GAIN,
} from "../src/audio";

const originalAudioContext = globalThis.AudioContext;

class FakeSource {
  buffer?: AudioBuffer;
  onended?: () => void;

  connect(): void {}
  start(): void {}
  stop(): void {
    this.onended?.();
  }
}

class FakeAudioContext {
  static lastGain = 0;
  static source?: FakeSource;
  static releaseResume?: () => void;

  currentTime = 0;
  destination = {};
  state = "running";

  createGain() {
    return {
      gain: {
        get value() {
          return FakeAudioContext.lastGain;
        },
        set value(value: number) {
          FakeAudioContext.lastGain = value;
        },
      },
      connect() {},
      disconnect() {},
    };
  }

  createBuffer(_channels: number, length: number) {
    return {
      duration: length / 24_000,
      getChannelData: () => new Float32Array(length),
    };
  }

  createBufferSource() {
    const source = new FakeSource();
    FakeAudioContext.source = source;
    return source;
  }

  resume() {
    return new Promise<void>((resolve) => {
      FakeAudioContext.releaseResume = resolve;
    });
  }

  close() {
    this.state = "closed";
    return Promise.resolve();
  }
}

describe("shared realtime audio output", () => {
  afterEach(() => {
    globalThis.AudioContext = originalAudioContext;
    FakeAudioContext.source = undefined;
    FakeAudioContext.releaseResume = undefined;
  });

  test("uses the requested two-times playback gain for both voice modes", async () => {
    globalThis.AudioContext =
      FakeAudioContext as unknown as typeof AudioContext;
    const playback = new PcmPlayback();

    expect(PLAYBACK_GAIN).toBe(2);
    expect(FakeAudioContext.lastGain).toBe(2);
    await playback.close();
  });

  test("captures microphone audio in roughly 20 ms realtime chunks", () => {
    expect(MICROPHONE_PROCESSOR_SIZE).toBe(1_024);
    expect(MICROPHONE_PROCESSOR_SIZE / 48_000 * 1_000)
      .toBeLessThanOrEqual(30);
  });

  test("does not become idle while an audio frame is still being queued", async () => {
    globalThis.AudioContext =
      FakeAudioContext as unknown as typeof AudioContext;
    const playback = new PcmPlayback();
    const enqueue = playback.enqueuePcm16(new ArrayBuffer(4));
    let idle = false;
    const waiting = playback.whenIdle().then(() => {
      idle = true;
    });

    await Promise.resolve();
    expect(idle).toBe(false);
    FakeAudioContext.releaseResume?.();
    await enqueue;
    expect(idle).toBe(false);
    FakeAudioContext.source?.onended?.();
    await waiting;
    expect(idle).toBe(true);
  });
});

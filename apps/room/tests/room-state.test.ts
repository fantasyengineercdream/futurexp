import { describe, expect, it } from "vitest";
import { initialRoomState, reduceRoomState } from "../src/room-state";

describe("room interaction state", () => {
  it("opens device selection through the mirror", () => {
    expect(
      reduceRoomState(initialRoomState, { type: "mirror.open" }),
    ).toMatchObject({
      view: "device-select",
      phase: "选择设备",
      caption: "这次想通过哪一种方式和我说话？",
    });
  });

  it("keeps the selected persona when opening the mirror", () => {
    const angelState = {
      ...initialRoomState,
      speaker: "小天使女仆",
      caption: "欢迎回来。",
    };
    expect(
      reduceRoomState(angelState, { type: "mirror.open" }),
    ).toMatchObject({
      speaker: "小天使女仆",
      view: "device-select",
    });
    expect(
      reduceRoomState(angelState, {
        type: "bed.rest",
        caption: "我只是暂时闭幕，又不是谢幕。",
      }),
    ).toMatchObject({
      speaker: "小天使女仆",
      caption: "我只是暂时闭幕，又不是谢幕。",
      view: "resting",
    });
  });

  it("prepares microphone mode without starting it automatically", () => {
    expect(
      reduceRoomState(initialRoomState, {
        type: "device.select",
        device: "microphone",
      }),
    ).toMatchObject({
      view: "microphone-ready",
      device: "microphone",
      phase: "电脑麦克风",
    });
  });

  it("waits for real Orange Pi events in ring mode", () => {
    expect(
      reduceRoomState(initialRoomState, {
        type: "device.select",
        device: "ring",
      }),
    ).toMatchObject({
      view: "ring-connecting",
      device: "ring",
      phase: "连接指环",
      caption: "正在等待 Zilo 指环连接…",
    });
  });

  it("shows connection progress in the Galgame subtitle immediately", () => {
    const choice = reduceRoomState(initialRoomState, {
      type: "mirror.open",
    });
    const ringConnecting = reduceRoomState(choice, {
      type: "device.select",
      device: "ring",
    });
    const ringLive = reduceRoomState(ringConnecting, {
      type: "session.connected",
    });

    expect(ringConnecting).toMatchObject({
      speaker: "系统",
      caption: "正在等待 Zilo 指环连接…",
      phase: "连接指环",
    });
    expect(ringLive).toMatchObject({
      speaker: "系统",
      caption: "指环已连接，正在聆听。",
      phase: "指环已连接",
    });
  });

  it("only marks a device live after a connection event", () => {
    const waiting = reduceRoomState(initialRoomState, {
      type: "device.select",
      device: "ring",
    });
    expect(
      reduceRoomState(waiting, { type: "session.connected" }),
    ).toMatchObject({
      view: "ring-live",
      phase: "指环已连接",
    });

    const microphone = reduceRoomState(initialRoomState, {
      type: "device.select",
      device: "microphone",
    });
    expect(
      reduceRoomState(microphone, { type: "session.start" }),
    ).toMatchObject({
      view: "microphone-connecting",
      phase: "连接中",
      speaker: "系统",
      caption: "正在连接实时语音，请稍候…",
    });
    expect(
      reduceRoomState(
        reduceRoomState(microphone, { type: "session.start" }),
        { type: "session.connected" },
      ),
    ).toMatchObject({
      view: "microphone-live",
      phase: "正在聆听",
      speaker: "系统",
      caption: "语音已连接，请开始说话。",
    });
  });

  it("returns to device selection when a session ends", () => {
    const waiting = reduceRoomState(initialRoomState, {
      type: "device.select",
      device: "ring",
    });
    expect(
      reduceRoomState(waiting, { type: "session.stopped" }),
    ).toMatchObject({
      view: "device-select",
      device: undefined,
      phase: "选择设备",
    });
  });

  it("surfaces connection errors inside the dialogue", () => {
    expect(
      reduceRoomState(initialRoomState, {
        type: "session.error",
        message: "连接失败",
      }),
    ).toMatchObject({
      view: "error",
      phase: "连接失败",
      caption: "连接失败",
    });
  });

  it("shows a distinct occupied state when another page owns the ring", () => {
    const waiting = reduceRoomState(initialRoomState, {
      type: "device.select",
      device: "ring",
    });
    expect(reduceRoomState(waiting, { type: "session.busy" })).toMatchObject({
      view: "error",
      phase: "戒指已被占用",
      caption: "戒指正在被其他用户使用，请稍后再试。",
    });
  });

  it("shows a distinct offline state when the Orange Pi is absent", () => {
    const waiting = reduceRoomState(initialRoomState, {
      type: "device.select",
      device: "ring",
    });
    expect(
      reduceRoomState(waiting, { type: "session.offline" }),
    ).toMatchObject({
      view: "error",
      phase: "戒指设备离线",
      caption: "Orange Pi 尚未连接云端，请稍后再试。",
    });
  });

  it("keeps bed, journal, captions, and back navigation deterministic", () => {
    const resting = reduceRoomState(initialRoomState, { type: "bed.rest" });
    expect(resting.view).toBe("resting");

    const journal = reduceRoomState(initialRoomState, { type: "journal.open" });
    expect(journal.view).toBe("journal");

    const captioned = reduceRoomState(initialRoomState, {
      type: "caption.set",
      speaker: "你",
      caption: "你好",
      phase: "聆听中",
    });
    expect(captioned).toMatchObject({
      speaker: "你",
      caption: "你好",
      phase: "聆听中",
    });

    expect(
      reduceRoomState(captioned, {
        type: "phase.set",
        phase: "正在思考",
      }),
    ).toMatchObject({
      speaker: "你",
      caption: "你好",
      phase: "正在思考",
    });

    expect(reduceRoomState(journal, { type: "room.back" })).toEqual(
      initialRoomState,
    );
  });
});

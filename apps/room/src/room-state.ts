export type RoomView =
  | "idle"
  | "device-select"
  | "microphone-ready"
  | "microphone-connecting"
  | "microphone-live"
  | "ring-connecting"
  | "ring-live"
  | "resting"
  | "journal"
  | "error";

export type InputDevice = "microphone" | "ring";

export interface RoomState {
  view: RoomView;
  device?: InputDevice;
  speaker: string;
  caption: string;
  phase: string;
}

export type RoomEvent =
  | { type: "mirror.open" }
  | { type: "device.select"; device: InputDevice }
  | { type: "session.start" }
  | { type: "session.connected" }
  | { type: "session.busy" }
  | { type: "session.offline" }
  | { type: "session.stopped"; speaker?: string }
  | { type: "session.error"; message: string }
  | {
      type: "caption.set";
      speaker: string;
      caption: string;
      phase?: string;
    }
  | { type: "phase.set"; phase: string }
  | { type: "bed.rest"; caption?: string }
  | { type: "journal.open" }
  | { type: "room.back" };

export const initialRoomState: RoomState = {
  view: "idle",
  speaker: "小恶魔女仆",
  caption: "房间已连接。点击镜子和她说话。",
  phase: "房间待机",
};

export function reduceRoomState(
  state: RoomState,
  event: RoomEvent,
): RoomState {
  switch (event.type) {
    case "mirror.open":
      return {
        view: "device-select",
        speaker: state.speaker,
        caption: "这次想通过哪一种方式和我说话？",
        phase: "选择设备",
      };
    case "device.select":
      if (event.device === "ring") {
        return {
          ...state,
          view: "ring-connecting",
          device: "ring",
          speaker: "系统",
          caption: "正在等待 Zilo 指环连接…",
          phase: "连接指环",
        };
      }
      return {
        ...state,
        view: "microphone-ready",
        device: "microphone",
        phase: "电脑麦克风",
      };
    case "session.start":
      if (state.device !== "microphone") return state;
      return {
        ...state,
        view: "microphone-connecting",
        speaker: "系统",
        caption: "正在连接实时语音，请稍候…",
        phase: "连接中",
      };
    case "session.connected":
      if (state.device === "ring") {
        return {
          ...state,
          view: "ring-live",
          speaker: "系统",
          caption: "指环已连接，正在聆听。",
          phase: "指环已连接",
        };
      }
      if (state.device === "microphone") {
        return {
          ...state,
          view: "microphone-live",
          speaker: "系统",
          caption: "语音已连接，请开始说话。",
          phase: "正在聆听",
        };
      }
      return state;
    case "session.busy":
      return {
        ...state,
        view: "error",
        speaker: "系统",
        caption: "戒指正在被其他用户使用，请稍后再试。",
        phase: "戒指已被占用",
      };
    case "session.offline":
      return {
        ...state,
        view: "error",
        speaker: "系统",
        caption: "Orange Pi 尚未连接云端，请稍后再试。",
        phase: "戒指设备离线",
      };
    case "session.stopped":
      return {
        view: "device-select",
        device: undefined,
        speaker: event.speaker ?? state.speaker,
        caption: "要换一种方式继续吗？",
        phase: "选择设备",
      };
    case "session.error":
      return {
        ...state,
        view: "error",
        speaker: "系统",
        caption: event.message,
        phase: "连接失败",
      };
    case "caption.set":
      return {
        ...state,
        speaker: event.speaker,
        caption: event.caption,
        phase: event.phase ?? state.phase,
      };
    case "phase.set":
      return {
        ...state,
        phase: event.phase,
      };
    case "bed.rest":
      return {
        view: "resting",
        speaker: state.speaker,
        caption:
          event.caption ?? "恶魔不需要睡觉。这只是盖好被子进行冥想。",
        phase: "休息中",
      };
    case "journal.open":
      return {
        view: "journal",
        speaker: "日记",
        caption: "今天发生的事，都被她悄悄记在这里。",
        phase: "角色日记",
      };
    case "room.back":
      return initialRoomState;
  }
}

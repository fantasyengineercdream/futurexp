import { describe, expect, it } from "vitest";
import { appTitle, roomUiText } from "../src/main";

describe("application shell", () => {
  it("exports the fullscreen room title", () => {
    expect(appTitle).toBe("OC ROOM");
  });

  it("keeps every voice choice inside the game vocabulary", () => {
    expect(roomUiText.deviceRing).toBe("戒指");
    expect(roomUiText.deviceMicrophone).toBe("麦克风");
    expect(roomUiText.start).toBe("开始");
    expect(roomUiText.end).toBe("结束");
    expect(roomUiText.ringWaiting).toContain("Zilo");
  });
});

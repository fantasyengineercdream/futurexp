import { describe, expect, it } from "vitest";
import { RoomConnectionPolicy } from "../vps-relay/room-policy";

describe("VPS room connection policy", () => {
  it("shares one StepFun upstream between one Orange Pi and one browser", () => {
    const room = new RoomConnectionPolicy();

    expect(room.attachSource("device", "orange-pi")).toEqual({
      accepted: true,
      openUpstream: true,
      activeSource: "device",
    });
    expect(room.attachSource("browser", "room-tab")).toEqual({
      accepted: true,
      openUpstream: false,
      activeSource: "browser",
    });
    expect(room.upstreamReserved).toBe(true);
  });

  it("returns to the Orange Pi source when the browser disconnects", () => {
    const room = new RoomConnectionPolicy();
    room.attachSource("device", "orange-pi");
    room.attachSource("browser", "room-tab");

    expect(room.detachSource("browser", "room-tab")).toEqual({
      activeSource: "device",
      closeUpstream: false,
    });
  });

  it("rejects a second browser without opening another upstream", () => {
    const room = new RoomConnectionPolicy();
    room.attachSource("browser", "first-tab");

    expect(room.attachSource("browser", "second-tab")).toEqual({
      accepted: false,
      reason: "browser_in_use",
      openUpstream: false,
      activeSource: "browser",
    });
  });

  it("releases the upstream only after every audio source disconnects", () => {
    const room = new RoomConnectionPolicy();
    room.attachSource("device", "orange-pi");
    room.attachSource("browser", "room-tab");

    room.detachSource("browser", "room-tab");
    expect(room.detachSource("device", "orange-pi")).toEqual({
      activeSource: null,
      closeUpstream: true,
    });
    expect(room.upstreamReserved).toBe(false);
  });

  it("allows only one ring viewer per physical device", () => {
    const room = new RoomConnectionPolicy();

    expect(room.attachViewer("viewer-a")).toEqual({ accepted: true });
    expect(room.attachViewer("viewer-b")).toEqual({
      accepted: false,
      reason: "ring_in_use",
    });
    room.detachViewer("viewer-a");
    expect(room.attachViewer("viewer-b")).toEqual({ accepted: true });
  });
});

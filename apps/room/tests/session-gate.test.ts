import { describe, expect, it } from "vitest";
import { SessionGate } from "../worker/session-gate";

describe("SessionGate", () => {
  it("caps the room at eight sessions", () => {
    const gate = new SessionGate(8);
    for (let index = 0; index < 8; index += 1) {
      expect(gate.admit(`ip-${index}`, `${index}`).ok).toBe(true);
    }
    expect(gate.admit("ip-9", "9")).toEqual({ ok: false, reason: "capacity" });
  });

  it("allows one session per IP and releases it", () => {
    const gate = new SessionGate(8);
    gate.admit("same", "a");
    expect(gate.admit("same", "b")).toEqual({ ok: false, reason: "ip_limit" });
    gate.release("a");
    expect(gate.admit("same", "b").ok).toBe(true);
  });
});

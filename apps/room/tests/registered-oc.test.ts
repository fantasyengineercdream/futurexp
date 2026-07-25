import { describe, expect, test, vi } from "vitest";
import {
  loadRegisteredOc,
  toDynamicRoomCharacter,
  toDynamicVoiceProfile,
} from "../src/registered-oc";

const registeredOc = {
  schemaVersion: "0.1",
  ocId: "oc-imported-lan",
  status: "registered",
  source: {
    sourceName: "lan.md",
    contentHash: "a".repeat(64),
    excerpt: "岚会先核对证据。",
  },
  character: {
    ocId: "oc-imported-lan",
    name: "岚",
    role: "异常频道记者",
    persona: "认真但叛逆，会先核对证据。",
    publicStyle: "克制、直接，只说确认过的事实。",
    locationId: "mirror-curtain",
    goals: [{ goalId: "goal-lan-1", text: "调查异常频道" }],
    secrets: [],
    senses: ["sight", "hearing"],
    relationships: {},
  },
  runtimeProfile: {
    ocId: "oc-imported-lan",
    personaConstraints: ["不把猜测冒充事实"],
    goalRefs: ["goal-lan-1"],
    initialMemories: [],
    actionPreferences: ["WAIT", "UTTERANCE", "MOVE"],
    homeLocationId: "mirror-curtain",
    dailyLocationPreferences: ["apartment-library"],
    rpgStats: {
      intellect: 2,
      athletics: 0,
      insight: 3,
      presence: 1,
    },
  },
};

describe("registered OC Room adapter", () => {
  test("loads exactly the imported resident requested by the Room URL", async () => {
    const fetcher = vi.fn(async () =>
      new Response(JSON.stringify(registeredOc), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    const result = await loadRegisteredOc(
      fetcher as typeof fetch,
      "https://world.example/",
      "oc-imported-lan",
    );

    expect(fetcher).toHaveBeenCalledWith(
      "https://world.example/api/ocs/oc-imported-lan",
      { cache: "no-store" },
    );
    expect(result.character.name).toBe("岚");
    expect(result.ocId).toBe("oc-imported-lan");
  });

  test("refuses identity mismatches instead of showing another OC", async () => {
    const fetcher = vi.fn(async () =>
      new Response(
        JSON.stringify({
          ...registeredOc,
          ocId: "oc-imported-other",
        }),
        { status: 200 },
      ),
    );

    await expect(
      loadRegisteredOc(
        fetcher as typeof fetch,
        "https://world.example/",
        "oc-imported-lan",
      ),
    ).rejects.toThrow("Registered OC identity mismatch");
  });

  test("builds a bounded voice profile from creator-confirmed fields only", () => {
    expect(toDynamicVoiceProfile(registeredOc)).toEqual({
      id: "oc-imported-lan",
      name: "岚",
      role: "异常频道记者",
      persona: "认真但叛逆，会先核对证据。",
      publicStyle: "克制、直接，只说确认过的事实。",
      goals: ["调查异常频道"],
    });
  });

  test("uses an honest temporary visual shell without borrowing OO or CC identity", () => {
    expect(
      toDynamicRoomCharacter(registeredOc, {
        roomImage: "/rooms/angel-room-pixel-v1.webp",
      }),
    ).toMatchObject({
      id: "oc-imported-lan",
      name: "岚",
      serial: "IMPORTED OC / PREVIEW ROOM",
      portraitImage: "",
      roomImage: "/rooms/angel-room-pixel-v1.webp",
    });
  });
});

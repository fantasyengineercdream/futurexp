const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  buildRoomUrl,
  cameraBasisForView,
  coreShowcaseCamera,
  corePresentationForSlotId,
  dayLoopFramesFromProjection,
  fetchAdvanceDayLoopProjection,
  fetchDayLoopProjection,
  loadOrCreateDayLoopProjection,
  playDayLoopOnce,
  previewResidentHomeState,
  residentPresentationForActor,
  scheduledResidentStateFromFrame,
  projectionFromResumeUrl,
  rowHasCoreSlots,
  roomTargetForSlotId,
  storeDayLoopProjection,
  slotIdForPosition
} = require("./room-bridge.js");

const actorIds = ["oc-angel", "oc-devil", "oc-user"];
const actorNames = {
  "oc-angel": "天使 OC",
  "oc-devil": "恶魔 OC",
  "oc-user": "用户 OC"
};
const actorApproaches = {
  "oc-angel": "优先保护同伴",
  "oc-devil": "行动直接",
  "oc-user": "保留自主选择"
};
const phases = ["planned", "travelling", "arrived", "in_event", "complete"];

test("production world root sends room entries to the dedicated room path", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(
    app,
    /new URL\(\s*["']\/room\/["'],\s*window\.location\.origin\s*\)\.href/
  );
});

const dayLoopProjection = {
  schemaVersion: "0.1",
  runId: "living-day-test",
  dayIndex: 1,
  actors: actorIds.map((actorId) => ({
    actorId,
    displayName: actorNames[actorId],
    desiredLocationId: "apartment-library",
    activityLabel: `继续推进 ${actorId} 的目标`
  })),
  timeline: phases.map((phase) => ({
    phase,
    actors: actorIds.map((actorId) => ({
      actorId,
      locationId:
        phase === "planned" || phase === "travelling"
          ? "mirror-curtain"
          : "apartment-library",
      activityLabel:
        phase === "travelling" ? "前往目的地" : "参与今天的共同事件",
      inSharedEvent: phase === "in_event"
    })),
    advancedBy: "scheduler"
  })),
  event: {
    eventRef: "event-1",
    locationId: "apartment-library",
    participantIds: actorIds,
    hook: "公共空间出现了一件小插曲。",
    stakes: "不同做法会产生不同后果。",
    intents: actorIds.map((actorId) => ({
      intentId: `intent:${actorId}`,
      actorId,
      eventId: "event-1",
      goal: `goal:${actorId}`,
      approach: actorApproaches[actorId],
      requestedAttribute: "inspiration",
      proposedBy: "oca"
    })),
    checks: actorIds.map((actorId, index) => ({
      checkId: `check:${actorId}`,
      actorId,
      attribute: "inspiration",
      dieRoll: 7 + index,
      modifier: 4,
      total: 11 + index,
      dc: 11,
      succeeded: true,
      resolvedBy: "ruleEngine"
    })),
    publicNarrative: "三位 OC 完成了各自的行动。"
  },
  memoryRefs: actorIds.map((actorId) => ({
    actorId,
    memoryRef: `memory:day-1:${actorId}`,
    available: true
  })),
  worldVersion: 1,
  worldHash: "a".repeat(64),
  replayVerified: true
};

test("maps the bottom WeirdCore showcase and milk frog route to stable semantic slots", () => {
  assert.equal(slotIdForPosition(3, 3, 7), "transit-01");
  assert.equal(slotIdForPosition(3, 3, 8), "transit-02");
  assert.equal(slotIdForPosition(3, 3, 9), "transit-03");
  assert.equal(slotIdForPosition(3, 3, 10), "core-oo");
  assert.equal(slotIdForPosition(3, 3, 11), "core-cc");
  assert.equal(slotIdForPosition(3, 3, 12), "transit-04");
  assert.equal(slotIdForPosition(3, 3, 13), "transit-05");
  assert.equal(slotIdForPosition(1, 3, 10), null);
  assert.equal(slotIdForPosition(0, 0, 0), null);
});

test("only the two core semantic slots open full Room Views", () => {
  assert.deepEqual(roomTargetForSlotId("core-oo"), {
    displayName: "OO",
    residentId: "oc-angel",
    roomId: "room-oo"
  });
  assert.deepEqual(roomTargetForSlotId("core-cc"), {
    displayName: "CC",
    residentId: "oc-devil",
    roomId: "room-cc"
  });
  assert.equal(roomTargetForSlotId("transit-03"), null);
});

test("gives OO and CC room windows rather than cropped resident art", () => {
  assert.deepEqual(corePresentationForSlotId?.("core-oo"), {
    roleLabel: "OO · 天使",
    roomImagePath: "/rooms/angel-room-pixel-v1.webp"
  });
  assert.deepEqual(corePresentationForSlotId?.("core-cc"), {
    roleLabel: "CC · 恶魔",
    roomImagePath: "/rooms/devil-room-pixel-v1.webp"
  });
  assert.equal(corePresentationForSlotId?.("transit-03"), null);
});

test("identifies the one row that must keep the core residents discoverable", () => {
  assert.equal(rowHasCoreSlots?.(3, 3), true);
  assert.equal(rowHasCoreSlots?.(3, 2), false);
  assert.equal(rowHasCoreSlots?.(1, 3), false);
});

test("keeps WASD movement horizontal when the camera looks up or down", () => {
  assert.deepEqual(cameraBasisForView?.(0, 0), {
    forward: { x: 0, y: 0, z: -1 },
    right: { x: 1, y: 0, z: 0 }
  });
  assert.deepEqual(cameraBasisForView?.(90, 0), {
    forward: { x: 1, y: 0, z: 0 },
    right: { x: 0, y: 0, z: 1 }
  });
  const pitched = cameraBasisForView?.(0, 30);
  assert.deepEqual(pitched, {
    forward: { x: 0, y: 0, z: -1 },
    right: { x: 1, y: 0, z: 0 }
  });
});

test("provides one stable camera preset that reveals the WeirdCore showcase row", () => {
  assert.deepEqual(coreShowcaseCamera?.(), {
    x: 0,
    y: -1100,
    z: 0,
    yaw: 0,
    pitch: -5
  });
});

test("keeps one fixed home registry for the scheduler-driven milk frog", () => {
  assert.deepEqual(
    residentPresentationForActor(
      "oc-user",
      "http://127.0.0.1:5177/"
    ),
    {
      actorId: "oc-user",
      displayName: "奶蛙",
      residentId: "resident-demo-user",
      roomId: "room-demo-user",
      homeSlotId: "transit-01",
      spriteUrl:
        "http://127.0.0.1:5177/assets/demo/milk-frog-v1.png"
    }
  );
});

test("offline preview keeps the milk frog at its fixed home and never invents travel", () => {
  assert.deepEqual(
    previewResidentHomeState("http://127.0.0.1:5177/"),
    {
      actorId: "oc-user",
      displayName: "奶蛙",
      residentId: "resident-demo-user",
      roomId: "room-demo-user",
      homeSlotId: "transit-01",
      spriteUrl:
        "http://127.0.0.1:5177/assets/demo/milk-frog-v1.png",
      slotId: "transit-01",
      mode: "present",
      statusText: "PREVIEW · 奶蛙在自己的房间",
      advancedBy: "preview",
      interactive: false,
      canEnter: false
    }
  );
});

test("moves the resident overlay from its fixed home only when the real scheduler says travelling", () => {
  const planned = scheduledResidentStateFromFrame(
    dayLoopProjection.timeline[0],
    "http://127.0.0.1:5177/"
  );
  const travelling = scheduledResidentStateFromFrame(
    dayLoopProjection.timeline[1],
    "http://127.0.0.1:5177/"
  );
  const arrived = scheduledResidentStateFromFrame(
    dayLoopProjection.timeline[2],
    "http://127.0.0.1:5177/"
  );

  assert.equal(planned.slotId, "transit-01");
  assert.equal(planned.mode, "present");
  assert.equal(planned.roomId, "room-demo-user");
  assert.equal(travelling.slotId, "transit-03");
  assert.equal(travelling.mode, "travelling");
  assert.equal(travelling.advancedBy, "scheduler");
  assert.equal(arrived.slotId, "transit-02");
  assert.equal(arrived.mode, "present");
  assert.equal(arrived.locationId, "apartment-library");
  assert.equal(new Set([planned.actorId, travelling.actorId, arrived.actorId]).size, 1);
});

test("maps one real day-loop projection to six concise exhibition beats", () => {
  const frames = dayLoopFramesFromProjection(
    dayLoopProjection,
    "http://127.0.0.1:5177/"
  );

  assert.deepEqual(
    frames.map((frame) => frame.phase),
    ["planned", "travelling", "arrived", "in_event", "in_event", "complete"]
  );
  assert.deepEqual(
    frames.map((frame) => frame.phaseLabel),
    ["今日计划", "正在路上", "已经抵达", "各自行动", "规则检定", "公共结果"]
  );
  assert.equal(frames[0].coreStates[0].isHome, true);
  assert.equal(frames[1].coreStates[0].isHome, false);
  assert.equal(frames[1].coreStates[1].isHome, false);
  assert.equal(frames[5].coreStates[0].isHome, true);
  assert.equal(frames[5].coreStates[1].isHome, true);
  assert.equal(frames[0].scheduledResidentState.slotId, "transit-01");
  assert.equal(frames[1].scheduledResidentState.slotId, "transit-03");
  assert.equal(frames[1].scheduledResidentState.mode, "travelling");
  assert.equal(frames[2].scheduledResidentState.slotId, "transit-02");
  assert.ok(
    frames.every(
      (frame) => frame.scheduledResidentState.advancedBy === "scheduler"
    )
  );
  assert.deepEqual(frames[0].publicStatusItems, ["今日安排准备中"]);
  assert.deepEqual(frames[3].publicStatusItems, [
    "OO · 优先保护同伴",
    "CC · 行动直接",
    "奶蛙 · 保留自主选择"
  ]);
  assert.deepEqual(frames[4].publicStatusItems, [
    "OO · 灵感 11 / DC 11 · 成功",
    "CC · 灵感 12 / DC 11 · 成功",
    "奶蛙 · 灵感 13 / DC 11 · 成功"
  ]);
  assert.deepEqual(frames[5].publicStatusItems, [
    "三位 OC 完成了各自的行动。",
    "3 位住民获得新经历"
  ]);
  assert.equal(frames[0].publicStatus, "今日安排准备中");
  assert.ok(
    frames.every((frame) =>
      frame.publicStatusItems.every((item) => item.length <= 24)
    )
  );
  assert.doesNotMatch(
    frames.flatMap((frame) => frame.publicStatusItems).join("\n"),
    /goal-|oc-angel|oc-devil|oc-user/
  );
  assert.doesNotMatch(
    frames.flatMap((frame) => frame.coreStates.map((state) => state.statusText)).join("\n"),
    /goal-|oc-angel|oc-devil|oc-user/
  );
  assert.equal(frames[3].publicStatus, frames[3].publicStatusItems[0]);
  assert.equal(frames[4].publicStatus, frames[4].publicStatusItems[0]);
  assert.equal(frames[5].publicStatus, frames[5].publicStatusItems[0]);
});

test("redacts internal goal ids and ellipsizes unexpectedly long public copy", () => {
  const projection = structuredClone(dayLoopProjection);
  projection.event.intents[0].approach =
    "围绕 goal-angel-protect 继续一段非常非常长的内部计划说明";
  projection.event.publicNarrative =
    "三位住民完成了一段明显超过右下角状态卡宽度的公共事件说明文字";

  const frames = dayLoopFramesFromProjection(
    projection,
    "http://127.0.0.1:5177/"
  );
  const publicItems = frames.flatMap((frame) => frame.publicStatusItems);

  assert.doesNotMatch(publicItems.join("\n"), /goal-/);
  assert.ok(publicItems.every((item) => item.length <= 24));
  assert.ok(publicItems.some((item) => item.endsWith("…")));
});

test("rejects an incompatible day-loop payload instead of guessing", () => {
  assert.throws(
    () =>
      dayLoopFramesFromProjection(
        { ...dayLoopProjection, schemaVersion: "9.9" },
        "http://127.0.0.1:5177/"
      ),
    /Unsupported day-loop schema/
  );
});

test("rejects a frontend-authored timeline instead of presenting it as scheduler activity", () => {
  const projection = structuredClone(dayLoopProjection);
  projection.timeline[1].advancedBy = "frontend";

  assert.throws(
    () =>
      dayLoopFramesFromProjection(
        projection,
        "http://127.0.0.1:5177/"
      ),
    /Invalid day-loop scheduler boundary/
  );
});

test("rejects private memory text at the public day-loop boundary", () => {
  assert.throws(
    () =>
      dayLoopFramesFromProjection(
        {
          ...dayLoopProjection,
          memoryRefs: undefined,
          memories: [{ actorId: "oc-angel", summary: "private" }]
        },
        "http://127.0.0.1:5177/"
      ),
    /Invalid day-loop memory boundary/
  );
});

test("posts the frozen seed to the same-origin day-loop endpoint", async () => {
  const requests = [];
  const result = await fetchDayLoopProjection(
    async (url, init) => {
      requests.push({ url: String(url), init });
      return {
        ok: true,
        json: async () => dayLoopProjection
      };
    },
    "http://127.0.0.1:5177/",
    "frontend-day-loop"
  );

  assert.equal(result.runId, "living-day-test");
  assert.equal(requests.length, 1);
  assert.equal(
    requests[0].url,
    "http://127.0.0.1:5177/api/living-world/day-loop-runs"
  );
  assert.equal(requests[0].init.method, "POST");
  assert.equal(
    requests[0].init.body,
    JSON.stringify({ seed: "frontend-day-loop" })
  );
});

test("replaces the preset user slot when a confirmed OC starts the demo", async () => {
  const requests = [];
  await fetchDayLoopProjection(
    async (url, init) => {
      requests.push({ url: String(url), init });
      return {
        ok: true,
        json: async () => ({
          ...structuredClone(dayLoopProjection),
          actors: dayLoopProjection.actors.map((actor) =>
            actor.actorId === "oc-user"
              ? {
                  ...actor,
                  actorId: "oc-imported-lan",
                  displayName: "岚"
                }
              : actor
          ),
          timeline: dayLoopProjection.timeline.map((frame) => ({
            ...frame,
            actors: frame.actors.map((actor) =>
              actor.actorId === "oc-user"
                ? { ...actor, actorId: "oc-imported-lan" }
                : actor
            )
          })),
          event: {
            ...dayLoopProjection.event,
            participantIds: ["oc-angel", "oc-devil", "oc-imported-lan"],
            intents: dayLoopProjection.event.intents.map((intent) =>
              intent.actorId === "oc-user"
                ? { ...intent, actorId: "oc-imported-lan" }
                : intent
            ),
            checks: dayLoopProjection.event.checks.map((check) =>
              check.actorId === "oc-user"
                ? { ...check, actorId: "oc-imported-lan" }
                : check
            )
          },
          memoryRefs: dayLoopProjection.memoryRefs.map((memory) =>
            memory.actorId === "oc-user"
              ? { ...memory, actorId: "oc-imported-lan" }
              : memory
          )
        })
      };
    },
    "http://127.0.0.1:5177/",
    "bring-your-oc-demo",
    "oc-imported-lan"
  );

  assert.equal(
    requests[0].init.body,
    JSON.stringify({
      seed: "bring-your-oc-demo",
      userOcId: "oc-imported-lan"
    })
  );
});

test("maps the imported actor to the one existing user television slot", () => {
  const importedProjection = structuredClone(dayLoopProjection);
  importedProjection.actors = importedProjection.actors.map((actor) =>
    actor.actorId === "oc-user"
      ? { ...actor, actorId: "oc-imported-lan", displayName: "岚" }
      : actor
  );
  importedProjection.timeline = importedProjection.timeline.map((frame) => ({
    ...frame,
    actors: frame.actors.map((actor) =>
      actor.actorId === "oc-user"
        ? { ...actor, actorId: "oc-imported-lan" }
        : actor
    )
  }));
  importedProjection.event.participantIds = [
    "oc-angel",
    "oc-devil",
    "oc-imported-lan"
  ];
  importedProjection.event.intents = importedProjection.event.intents.map(
    (intent) =>
      intent.actorId === "oc-user"
        ? { ...intent, actorId: "oc-imported-lan" }
        : intent
  );
  importedProjection.event.checks = importedProjection.event.checks.map(
    (check) =>
      check.actorId === "oc-user"
        ? { ...check, actorId: "oc-imported-lan" }
        : check
  );
  importedProjection.memoryRefs = importedProjection.memoryRefs.map((memory) =>
    memory.actorId === "oc-user"
      ? { ...memory, actorId: "oc-imported-lan" }
      : memory
  );

  const frames = dayLoopFramesFromProjection(
    importedProjection,
    "http://127.0.0.1:5177/",
    {
      actorId: "oc-imported-lan",
      displayName: "岚",
      rpgSummary: "认真2 叛逆0 体能5 灵感1",
      roomUrl:
        "https://room.example/?residentId=oc-imported-lan&runId=living-day-test"
    }
  );

  assert.equal(frames[0].scheduledResidentState.actorId, "oc-imported-lan");
  assert.equal(frames[0].scheduledResidentState.displayName, "岚");
  assert.match(frames[0].scheduledResidentState.statusText, /^岚 · /);
  assert.equal(
    frames[0].scheduledResidentState.rpgSummary,
    "认真2 叛逆0 体能5 灵感1"
  );
  assert.equal(frames[0].scheduledResidentState.homeSlotId, "transit-01");
  const completed = frames.find((frame) => frame.phase === "complete");
  assert.equal(completed.scheduledResidentState.canEnter, true);
  assert.match(
    completed.scheduledResidentState.roomUrl,
    /residentId=oc-imported-lan/
  );
  assert.equal(frames[0].scheduledResidentState.canEnter, false);
});

test("advances the persisted run without sending private client state", async () => {
  const requests = [];
  const result = await fetchAdvanceDayLoopProjection(
    async (url, init) => {
      requests.push({ url: String(url), init });
      return {
        ok: true,
        json: async () => ({ ...dayLoopProjection, dayIndex: 2 })
      };
    },
    "http://127.0.0.1:5177/",
    "living-day-test"
  );

  assert.equal(result.dayIndex, 2);
  assert.deepEqual(requests, [
    {
      url:
        "http://127.0.0.1:5177/api/living-world/day-loop-runs/living-day-test/advance",
      init: { method: "POST" }
    }
  ]);
});

test("restores the last real projection without creating a new run", async () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value)
  };
  storeDayLoopProjection(
    storage,
    "http://127.0.0.1:5177/",
    "frontend-day-loop",
    dayLoopProjection
  );

  let createCalls = 0;
  const result = await loadOrCreateDayLoopProjection(
    async () => {
      createCalls += 1;
      throw new Error("must not create a second run");
    },
    storage,
    "http://127.0.0.1:5177/",
    "frontend-day-loop"
  );

  assert.equal(createCalls, 0);
  assert.equal(result.runId, "living-day-test");
  assert.equal(result.dayIndex, 1);
});

test("restores the exact public projection advanced inside Room View", () => {
  const dayTwo = {
    ...structuredClone(dayLoopProjection),
    dayIndex: 2,
    worldVersion: 2,
    memoryRefs: actorIds.map((actorId) => ({
      actorId,
      memoryRef: `memory:day-2:${actorId}`,
      available: true
    }))
  };
  const returnUrl = new URL("http://127.0.0.1:5177/");
  returnUrl.searchParams.set("dayLoopResume", JSON.stringify(dayTwo));

  assert.deepEqual(projectionFromResumeUrl(returnUrl.toString()), dayTwo);
  assert.equal(
    projectionFromResumeUrl(
      "http://127.0.0.1:5177/?dayLoopResume=%7B%22runId%22%3A%22bad%22%7D"
    ),
    null
  );
});

test("plays one complete day in order before asking for the next day", () => {
  const applied = [];
  let completeCalls = 0;
  let scheduled = null;
  const frames = dayLoopFramesFromProjection(
    dayLoopProjection,
    "http://127.0.0.1:5177/"
  );

  playDayLoopOnce(
    frames,
    (frame) => applied.push(frame.phase),
    (callback, delay) => {
      assert.equal(delay, 6000);
      scheduled = callback;
    },
    () => {
      completeCalls += 1;
    }
  );

  assert.deepEqual(applied, ["planned"]);
  scheduled();
  scheduled();
  scheduled();
  scheduled();
  scheduled();
  assert.deepEqual(
    applied,
    ["planned", "travelling", "arrived", "in_event", "in_event", "complete"]
  );
  assert.equal(completeCalls, 0);
  scheduled();
  assert.equal(completeCalls, 1);
});

test("passes the same Day Loop run and owner episode into OO Room View", () => {
  assert.equal(
    buildRoomUrl("http://127.0.0.1:4174/", {
      residentId: "oc-angel",
      roomId: "room-oo"
    }, "http://127.0.0.1:5177/?previewMotion=force", "living-day-test", {
      apiBaseUrl: "http://127.0.0.1:5177/",
      dayIndex: 1,
      episodeRef: "memory:day-1:oc-angel"
    }),
    "http://127.0.0.1:4174/?residentId=oc-angel&roomId=room-oo&runId=living-day-test&livingWorldApi=http%3A%2F%2F127.0.0.1%3A5177%2F&dayIndex=1&episodeRef=memory%3Aday-1%3Aoc-angel&returnTo=http%3A%2F%2F127.0.0.1%3A5177%2F%3FpreviewMotion%3Dforce"
  );
});

test("builds the confirmed imported OC Room handoff without changing identity", () => {
  const roomUrl = new URL(
    buildRoomUrl(
      "https://room.example/",
      {
        residentId: "oc-imported-lan",
        roomId: "room-demo-user"
      },
      "https://tower.example/?livingWorldApi=https%3A%2F%2Fapi.example",
      "living-day-imported",
      {
        apiBaseUrl: "https://api.example/",
        dayIndex: 2,
        episodeRef: "episode:oc-imported-lan:day-2"
      }
    )
  );

  assert.equal(roomUrl.searchParams.get("residentId"), "oc-imported-lan");
  assert.equal(roomUrl.searchParams.get("roomId"), "room-demo-user");
  assert.equal(roomUrl.searchParams.get("runId"), "living-day-imported");
  assert.equal(
    roomUrl.searchParams.get("episodeRef"),
    "episode:oc-imported-lan:day-2"
  );
  assert.equal(
    roomUrl.searchParams.get("livingWorldApi"),
    "https://api.example/"
  );
  assert.equal(
    roomUrl.searchParams.get("returnTo"),
    "https://tower.example/?livingWorldApi=https%3A%2F%2Fapi.example"
  );
});

test("decorative floor rings cannot block television clicks", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(
    css,
    /\.floor-core\s*\{[^}]*pointer-events:\s*none;/s
  );
});

test("tower keeps the OO and CC row moving slowly, labeled, and on Room artwork", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(app, /rowHasCoreSlots\(\s*floorIndex,\s*row\s*\)/);
  assert.match(app, /const CORE_SHOWCASE_SPIN = 0\.008;/);
  assert.match(
    app,
    /ring\.dataset\.speed = isCoreRow\s*\?\s*String\(CORE_SHOWCASE_SPIN\)/
  );
  assert.match(app, /ring\.dataset\.coreShowcase = String\(isCoreRow\)/);
  assert.match(app, /corePresentationForSlotId\(slotId\)/);
  assert.match(
    app,
    /new URL\(\s*corePresentation\.roomImagePath,\s*roomAppBaseUrl\s*\)/
  );
  assert.doesNotMatch(app, /AngelDevilCore\/[12]_oc\.png/);
  assert.match(css, /\.tv-slot\[data-role-label\]::after/);
  assert.match(css, /content:\s*attr\(data-role-label\)/);
  assert.match(
    css,
    /\.tv-slot\[data-role-label\]::after\s*\{[^}]*top:\s*auto;[^}]*bottom:\s*-18px;/s
  );
});

test("television faces and wall panels point toward the tower interior", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(
    app,
    /panel\.style\.transform = `rotateY\(\$\{angle\}deg\) translateZ\(\$\{PANEL_RADIUS\}px\) rotateY\(180deg\)`/
  );
  assert.match(
    app,
    /tv\.style\.transform = `rotateY\(\$\{angle\}deg\) translateZ\(\$\{RADIUS\}px\) rotateY\(180deg\)`/
  );
});

test("core residents remain visually identifiable while they are away", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(app, /showResidentScreen\(tv, tv\.dataset\.homeImageUrl\)/);
  assert.match(app, /classList\.add\("tv-content--away"\)/);
  assert.match(css, /\.tv-content--away/);
});

test("tower movement keeps WASD horizontal and reserves vertical movement for Space and Shift", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(
    app,
    /cameraBasisForView\(\s*camera\.yaw\s*\)/
  );
  assert.doesNotMatch(app, /camera\.y [+-]= forward\.y \* step/);
  assert.match(app, /if \(key === " "\) camera\.y \+= step/);
  assert.match(app, /if \(key === "Shift"\) camera\.y -= step/);
});

test("tower movement gives real keyboard taps a visible first-frame nudge", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(app, /function moveCameraForInput\(key, step\)/);
  assert.match(app, /keys\.forEach\(\(key\) => moveCameraForInput\(key, step\)\)/);
  assert.match(
    app,
    /moveCameraForInput\(key, camera\.speed \* 0\.065\)/
  );
});

test("tower starts at and can return to the OO CC and milk frog showcase", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );
  const html = fs.readFileSync(
    path.join(__dirname, "index.html"),
    "utf8"
  );

  assert.match(app, /coreShowcaseCamera\(\)/);
  assert.match(app, /coreLocator\.addEventListener\("click"/);
  assert.match(
    app,
    /document\.querySelector\('\[data-core-showcase="true"\]'\)/
  );
  assert.match(
    app,
    /coreRing\.dataset\.angle = String\(CORE_SHOWCASE_ANGLE\)/
  );
  assert.match(html, /id="coreLocator"/);
  assert.match(html, /寻找OOCC吧/);
});

test("world status card rotates short public items instead of clipping a crowd", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(app, /cycleFramePublicStatus\(frame\.publicStatusItems\)/);
  assert.match(app, /window\.clearInterval\(publicStatusTimer\)/);
});

test("visible controls explain the screen-relative WASD mapping", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "index.html"),
    "utf8"
  );

  assert.match(html, /W\/S 水平前后/);
  assert.match(html, /A\/D 水平左右/);
});

test("production entry and executable assets must revalidate after deployment", () => {
  const headers = fs.readFileSync(
    path.join(__dirname, "_headers"),
    "utf8"
  );

  assert.match(headers, /\/index\.html[\s\S]*Cache-Control: no-cache, no-store, must-revalidate/);
  for (const asset of ["/app.js", "/room-bridge.js", "/styles.css"]) {
    assert.match(
      headers,
      new RegExp(
        `${asset.replace(".", "\\.")}[\\s\\S]*Cache-Control: no-cache, must-revalidate`
      )
    );
  }
});

test("production tower keeps the current Room service on the same origin", () => {
  const app = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );
  const worker = fs.readFileSync(
    path.join(__dirname, "_worker.js"),
    "utf8"
  );

  assert.match(
    app,
    /new URL\(\s*["']\/room\/["'],\s*window\.location\.origin\s*\)\.href/
  );
  assert.doesNotMatch(app, /"https:\/\/oocc-room-demo\.pages\.dev\/"/);
  assert.match(worker, /"https:\/\/oc-voice\.open\.smn\.icu"/);
  assert.doesNotMatch(worker, /"https:\/\/oocc-room-demo\.pages\.dev"/);
});

test("transparent television cutouts never inherit a white button plate", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(
    css,
    /\.tv-slot\s*\{[^}]*appearance:\s*none;[^}]*border:\s*0;[^}]*padding:\s*0;[^}]*background:\s*transparent;/s
  );
});

test("OO and CC show the complete room artwork without cropping it into a portrait", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(
    css,
    /\.tv-slot\[data-variant="angel"\]\s+\.tv-content,\s*\.tv-slot\[data-variant="demon"\]\s+\.tv-content\s*\{[^}]*object-fit:\s*contain;/s
  );
});

test("world status card cannot grow into a clipped text block", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(
    css,
    /\.selection__name\s*\{[^}]*overflow:\s*hidden;[^}]*-webkit-line-clamp:\s*3;/s
  );
});

test("standalone exhibition mode is labeled as a preview", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "index.html"),
    "utf8"
  );

  assert.match(html, />PREVIEW</);
  assert.match(html, /id="selectionLabel"[^>]*>当前状态</);
});

test("transit sprite faces its travel direction and hides the loop reset at both edges", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(
    css,
    /\.tv-transit-resident\s*\{[^}]*animation:\s*transit-pass 18s linear infinite;/s
  );
  assert.match(
    css,
    /\.tv-transit-resident\s*\{[^}]*scale:\s*1\.15;/s
  );
  assert.match(
    css,
    /\.tv-transit-resident\s*\{[^}]*image-rendering:\s*auto;/s
  );
  assert.match(
    css,
    /@keyframes transit-pass\s*\{[^}]*0%\s*\{[^}]*opacity:\s*0;/s
  );
  assert.match(
    css,
    /@keyframes transit-pass[\s\S]*?transform:\s*translateX\(-78%\) translateY\(1px\) scaleX\(-1\);/
  );
  assert.match(
    css,
    /46%\s*\{[^}]*transform:\s*translateX\(46%\) translateY\(-1px\) scaleX\(-1\);/s
  );
  assert.match(
    css,
    /92%,\s*100%\s*\{[^}]*transform:\s*translateX\(178%\) translateY\(1px\) scaleX\(-1\);/s
  );
  assert.match(
    css,
    /92%,\s*100%\s*\{[^}]*opacity:\s*0;/s
  );
});

test("milk frog movement is driven by day-loop frames, never by a frontend route timer", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.doesNotMatch(source, /function startTransitRouteLoop\(\)/);
  assert.doesNotMatch(source, /previewTransitStates\(/);
  assert.doesNotMatch(source, /previewTransitTimer/);
  assert.match(source, /applyScheduledResidentState\(frame\.scheduledResidentState\)/);
  assert.match(source, /clearTransitScreens\(\)/);
});

test("milk frog remains a foreground layer over stable television imagery", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(source, /dataset\.transitBaseImageUrl/);
  assert.match(source, /function showTransitBaseScreen\(tv\)/);
  assert.match(source, /function showTransitResident\(tv, imageUrl\)/);
  assert.match(source, /screen\.appendChild\(resident\)/);
  assert.match(source, /dataset\.homeResidentId\s*=\s*"resident-demo-user"/);
  assert.match(source, /"奶蛙的房间 · 当前外出"/);
  assert.doesNotMatch(
    source,
    /state\.spriteUrl[\s\S]{0,120}transitBaseImageUrl\s*=/
  );
  assert.doesNotMatch(
    source,
    /function clearTransitScreens\(\)[\s\S]*?showSnowScreen\(transitTv\)/
  );
});

test("milk frog exposes hover status without becoming enterable", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "app.js"),
    "utf8"
  );

  assert.match(source, /tv\.addEventListener\("mouseenter"/);
  assert.match(source, /\?\s*"路过状态"\s*:\s*"当前活动"/s);
  assert.match(
    source,
    /state\.canEnter \? "false" : "true"/
  );
  assert.match(source, /getAttribute\("aria-disabled"\) === "true"/);
  assert.match(source, /`\$\{state\.displayName\} · 路过中`/);
  assert.match(source, /`\$\{state\.displayName\} · 在此活动`/);
  assert.match(source, /`\$\{state\.displayName\} · 回到房间`/);
  assert.equal(
    previewResidentHomeState("http://127.0.0.1:5177/").displayName,
    "奶蛙"
  );
  assert.equal(
    previewResidentHomeState("http://127.0.0.1:5177/").canEnter,
    false
  );
  assert.doesNotMatch(source, /dataset\.roleLabel = "奶蛙 · 路过中"/);
});

test("reduced motion keeps the transit resident readable without translation", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "styles.css"),
    "utf8"
  );

  assert.match(
    css,
    /@media \(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*\.tv-transit-resident\s*\{[^}]*animation:\s*none;/s
  );
  assert.match(
    css,
    /html\[data-preview-motion="force"\]\s+\.tv-transit-resident\s*\{[^}]*animation:\s*transit-pass 18s linear infinite;/s
  );
  assert.match(
    css,
    /@media \(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*\.tv-transit-resident\s*\{[^}]*transform:\s*translateX\(34%\) scaleX\(-1\);/s
  );
});

test("public transit copy identifies the provided character as milk frog without inventing a route", () => {
  const bridge = fs.readFileSync(
    path.join(__dirname, "room-bridge.js"),
    "utf8"
  );

  assert.match(bridge, /displayName:\s*"奶蛙"/);
  assert.match(bridge, /homeSlotId:\s*"transit-01"/);
  assert.match(bridge, /advancedBy !== "scheduler"/);
  assert.doesNotMatch(bridge, /奶蛙正在 OO 房间外慢慢走过/);
  assert.doesNotMatch(bridge, /displayName:\s*"奶龙"/);
});

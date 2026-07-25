(function exposeRoomBridge(root, factory) {
  const bridge = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = bridge;
  }
  if (root) {
    root.TvRoomBridge = bridge;
  }
})(typeof window === "undefined" ? globalThis : window, function createRoomBridge() {
  const layoutSlots = {
    "3:3:5": "transit-01",
    "3:3:6": "transit-02",
    "3:3:7": "transit-03",
    "3:3:8": "transit-04",
    "3:3:9": "transit-05",
    "3:3:10": "core-oo",
    "3:3:11": "core-cc"
  };

  const coreRooms = {
    "core-oo": {
      displayName: "OO",
      residentId: "oc-angel",
      roomId: "room-oo"
    },
    "core-cc": {
      displayName: "CC",
      residentId: "oc-devil",
      roomId: "room-cc"
    }
  };

  const corePresentation = {
    "core-oo": {
      roleLabel: "OO · 天使",
      roomImagePath: "/rooms/angel-room-pixel-v1.webp"
    },
    "core-cc": {
      roleLabel: "CC · 恶魔",
      roomImagePath: "/rooms/devil-room-pixel-v1.webp"
    }
  };

  const coreSlotByActor = {
    "oc-angel": "core-oo",
    "oc-devil": "core-cc"
  };

  const residentPresentation = {
    "oc-user": {
      actorId: "oc-user",
      displayName: "奶蛙",
      residentId: "resident-demo-user",
      homeSlotId: "transit-01",
      spritePath: "assets/demo/milk-frog-v1.png"
    }
  };

  const residentLocationSlots = {
    "mirror-curtain": "transit-01",
    "apartment-library": "transit-02",
    "grand-foyer": "transit-04"
  };

  const residentTransitSlot = "transit-03";
  const residentFallbackLocationSlot = "transit-05";
  const residentRouteSlots = [
    "transit-01",
    "transit-02",
    "transit-03",
    "transit-04",
    "transit-05"
  ];

  const dayPhaseStatus = {
    travelling: () => "OC 正在前往各自的目的地。",
    arrived: () => "OC 已抵达今天的地点。"
  };

  const dayPhaseLabel = {
    planned: "今日计划",
    travelling: "正在路上",
    arrived: "已经抵达",
    in_event: "各自行动",
    complete: "公共结果"
  };

  const actorLabel = {
    "oc-angel": "OO",
    "oc-devil": "CC",
    "oc-user": "奶蛙"
  };

  const attributeLabel = {
    seriousness: "认真",
    rebellion: "叛逆",
    fitness: "体能",
    inspiration: "灵感"
  };

  const dayLoopSessionKey = "kaleidoroom.tv-day-loop.v1";

  function slotIdForPosition(floorIndex, row, col) {
    return layoutSlots[`${floorIndex}:${row}:${col}`] ?? null;
  }

  function rowHasCoreSlots(floorIndex, row) {
    const prefix = `${floorIndex}:${row}:`;
    return Object.entries(layoutSlots).some(
      ([position, slotId]) =>
        position.startsWith(prefix) &&
        Object.prototype.hasOwnProperty.call(coreRooms, slotId)
    );
  }

  function roomTargetForSlotId(slotId) {
    return coreRooms[slotId] ?? null;
  }

  function corePresentationForSlotId(slotId) {
    return corePresentation[slotId] ?? null;
  }

  function residentPresentationForActor(actorId, baseUrl, overrides = {}) {
    const resident = residentPresentation[actorId];
    if (!resident) return null;
    const { spritePath, ...publicResident } = resident;
    return {
      ...publicResident,
      ...overrides,
      spriteUrl:
        overrides.spriteUrl === null
          ? null
          : new URL(spritePath, baseUrl).toString()
    };
  }

  function previewResidentHomeState(baseUrl) {
    const resident = residentPresentationForActor("oc-user", baseUrl);
    return {
      ...resident,
      slotId: resident.homeSlotId,
      mode: "present",
      statusText: "PREVIEW · 奶蛙在固定频道",
      advancedBy: "preview",
      interactive: false,
      canEnter: false
    };
  }

  function cameraBasisForView(yawDegrees, pitchDegrees) {
    const yaw = yawDegrees * Math.PI / 180;
    const clean = (value) => Math.abs(value) < 1e-12 ? 0 : value;
    return {
      forward: {
        x: clean(Math.sin(yaw)),
        y: 0,
        z: clean(-Math.cos(yaw))
      },
      right: {
        x: clean(Math.cos(yaw)),
        y: 0,
        z: clean(Math.sin(yaw))
      }
    };
  }

  function coreShowcaseCamera() {
    return {
      x: 0,
      y: -1100,
      z: 0,
      yaw: 0,
      pitch: -5
    };
  }

  function concisePublicText(value, fallback = "公共状态更新中") {
    const normalized =
      (typeof value === "string" ? value : fallback)
        .replace(/\bgoal[-_:][A-Za-z0-9_-]+\b/gi, "当前安排")
        .replace(/\s+/g, " ")
        .trim() || fallback;
    return normalized.length > 24
      ? `${normalized.slice(0, 23).trimEnd()}…`
      : normalized;
  }

  function buildRoomUrl(baseUrl, target, returnTo, runId, livingWorld = {}) {
    const url = new URL(baseUrl);
    url.searchParams.set("residentId", target.residentId);
    url.searchParams.set("roomId", target.roomId);
    if (runId) {
      url.searchParams.set("runId", runId);
    }
    if (livingWorld.apiBaseUrl) {
      url.searchParams.set("livingWorldApi", livingWorld.apiBaseUrl);
    }
    if (Number.isInteger(livingWorld.dayIndex)) {
      url.searchParams.set("dayIndex", String(livingWorld.dayIndex));
    }
    if (livingWorld.episodeRef) {
      url.searchParams.set("episodeRef", livingWorld.episodeRef);
    }
    if (returnTo) {
      url.searchParams.set("returnTo", returnTo);
    }
    return url.toString();
  }

  function scheduledResidentStateFromFrame(
    frame,
    baseUrl,
    activeUserOc = null,
    visualSlotId = null
  ) {
    if (
      !frame ||
      frame.advancedBy !== "scheduler" ||
      !Array.isArray(frame.actors)
    ) {
      throw new Error("Invalid day-loop scheduler boundary");
    }
    const resident = residentPresentationForActor(
      "oc-user",
      baseUrl,
      activeUserOc
        ? {
            actorId: activeUserOc.actorId,
            displayName: activeUserOc.displayName,
            residentId: activeUserOc.actorId,
            rpgSummary: activeUserOc.rpgSummary,
            roomUrl: activeUserOc.roomUrl,
            spriteUrl: activeUserOc.spriteUrl ?? null
          }
        : {}
    );
    const actor = frame.actors.find(
      (candidate) => candidate.actorId === resident.actorId
    );
    if (!actor || typeof actor.locationId !== "string") {
      throw new Error(`Missing day-loop actor: ${resident.actorId}`);
    }
    const isTravelling = frame.phase === "travelling";
    const slotId = visualSlotId ||
      (isTravelling
        ? residentTransitSlot
        : residentLocationSlots[actor.locationId] ||
          residentFallbackLocationSlot);
    return {
      ...resident,
      slotId,
      mode: isTravelling ? "travelling" : "present",
      phase: frame.phase,
      locationId: actor.locationId,
      activityLabel: concisePublicText(actor.activityLabel),
      statusText:
        `${resident.displayName} · ${concisePublicText(actor.activityLabel)}`,
      advancedBy: frame.advancedBy,
      interactive:
        Boolean(activeUserOc?.roomUrl) && frame.phase === "complete",
      canEnter:
        Boolean(activeUserOc?.roomUrl) && frame.phase === "complete"
    };
  }

  function assertDayLoopProjection(projection) {
    if (!projection || projection.schemaVersion !== "0.1") {
      throw new Error("Unsupported day-loop schema");
    }
    if (
      typeof projection.runId !== "string" ||
      !Number.isInteger(projection.dayIndex)
    ) {
      throw new Error("Invalid day-loop identity");
    }
    if (!Array.isArray(projection.actors) || !Array.isArray(projection.timeline)) {
      throw new Error("Invalid day-loop projection");
    }
    if (
      projection.timeline.some(
        (frame) => frame.advancedBy !== "scheduler"
      )
    ) {
      throw new Error("Invalid day-loop scheduler boundary");
    }
    if (
      !projection.event ||
      !Array.isArray(projection.event.participantIds) ||
      !Array.isArray(projection.event.intents) ||
      !Array.isArray(projection.event.checks) ||
      projection.event.checks.some(
        (check) => check.resolvedBy !== "ruleEngine"
      ) ||
      typeof projection.event.publicNarrative !== "string"
    ) {
      throw new Error("Invalid day-loop event projection");
    }
    if (
      !Array.isArray(projection.memoryRefs) ||
      Object.prototype.hasOwnProperty.call(projection, "memories")
    ) {
      throw new Error("Invalid day-loop memory boundary");
    }
  }

  function dayLoopFramesFromProjection(
    projection,
    baseUrl,
    activeUserOc = null
  ) {
    assertDayLoopProjection(projection);
    const nameFor = (actorId) =>
      actorLabel[actorId] ||
      projection.actors.find((actor) => actor.actorId === actorId)
        ?.displayName ||
      actorId;
    const plans = ["今日安排准备中"];
    const intents = projection.event.intents.map(
      (intent) =>
        concisePublicText(
          `${nameFor(intent.actorId)} · ${intent.approach}`
        )
    );
    const checks = projection.event.checks.map(
      (check) =>
        `${nameFor(check.actorId)} · ` +
        `${attributeLabel[check.attribute] || check.attribute} ` +
        `${check.total} / DC ${check.dc} · ` +
        `${check.succeeded ? "成功" : "失败"}`
    );
    const visibleExperienceActors = projection.memoryRefs
      .filter(
        (memory) =>
          memory.available &&
          Object.prototype.hasOwnProperty.call(coreSlotByActor, memory.actorId)
      )
      .map((memory) => nameFor(memory.actorId));

    const plannedFrame = projection.timeline.find(
      (frame) => frame.phase === "planned"
    );
    const arrivedFrame = projection.timeline.find(
      (frame) => frame.phase === "arrived"
    );
    const residentActorId = activeUserOc?.actorId || "oc-user";
    const slotForFrame = (frame) => {
      const actor = frame?.actors?.find(
        (candidate) => candidate.actorId === residentActorId
      );
      return residentLocationSlots[actor?.locationId] ||
        residentFallbackLocationSlot;
    };
    const startSlot = slotForFrame(plannedFrame);
    const destinationSlot = slotForFrame(arrivedFrame);
    const startIndex = residentRouteSlots.indexOf(startSlot);
    const destinationIndex = residentRouteSlots.indexOf(destinationSlot);
    const direction = destinationIndex >= startIndex ? 1 : -1;
    const route = [];
    for (
      let index = startIndex;
      index !== destinationIndex + direction;
      index += direction
    ) {
      route.push(residentRouteSlots[index]);
    }
    const travellingSlots =
      route.length <= 2 ? [destinationSlot] : route.slice(1, -1);

    const frames = projection.timeline.map((frame) => {
      if (!dayPhaseLabel[frame.phase] || !Array.isArray(frame.actors)) {
        throw new Error(`Unsupported day-loop phase: ${frame.phase}`);
      }

      const coreStates = Object.entries(coreSlotByActor).map(
        ([actorId, slotId]) => {
          const actor = frame.actors.find(
            (candidate) => candidate.actorId === actorId
          );
          if (!actor) {
            throw new Error(`Missing day-loop actor: ${actorId}`);
          }
          return {
            slotId,
            actorId,
            isHome: frame.phase === "planned" || frame.phase === "complete",
            statusText:
              `${nameFor(actorId)} · ` +
              ({
                planned: "正在整理今天的计划",
                travelling: "正在前往今天的目的地",
                arrived: "已经抵达今天的地点",
                in_event: "正在参与公共事件",
                complete: "带回了一段新经历"
              })[frame.phase]
          };
        }
      );

      const publicStatusItems =
        frame.phase === "planned"
          ? plans
          : frame.phase === "in_event"
            ? intents
            : frame.phase === "complete"
              ? [
                  concisePublicText(projection.event.publicNarrative),
                  visibleExperienceActors.length === 2
                    ? `${visibleExperienceActors.join(" 与 ")} 带回了新经历`
                    : `${visibleExperienceActors.length} 位可查看住民带回新经历`
                ]
              : [dayPhaseStatus[frame.phase]()];

      return {
        phase: frame.phase,
        phaseLabel: dayPhaseLabel[frame.phase],
        publicStatus: publicStatusItems[0],
        publicStatusItems,
        coreStates,
        scheduledResidentState: scheduledResidentStateFromFrame(
          frame,
          baseUrl,
          activeUserOc
        )
      };
    });

    return frames.flatMap((frame) => {
      if (frame.phase === "travelling") {
        return travellingSlots.map((slotId) => ({
          ...frame,
          scheduledResidentState: scheduledResidentStateFromFrame(
            projection.timeline.find(
              (candidate) => candidate.phase === "travelling"
            ),
            baseUrl,
            activeUserOc,
            slotId
          )
        }));
      }
      if (frame.phase === "in_event") {
        return [
          frame,
          {
            ...frame,
            phaseLabel: "规则检定",
            publicStatus: checks[0],
            publicStatusItems: checks
          }
        ];
      }
      return [frame];
    });
  }

  function projectionSessionIdentity(apiBaseUrl, seed, userOcId = null) {
    return `${new URL(apiBaseUrl).toString()}|${seed}|${userOcId || "preset"}`;
  }

  function storeDayLoopProjection(
    storage,
    apiBaseUrl,
    seed,
    projection,
    userOcId = null
  ) {
    assertDayLoopProjection(projection);
    try {
      storage.setItem(
        dayLoopSessionKey,
        JSON.stringify({
          identity: projectionSessionIdentity(apiBaseUrl, seed, userOcId),
          projection
        })
      );
      return true;
    } catch {
      return false;
    }
  }

  function restoreDayLoopProjection(
    storage,
    apiBaseUrl,
    seed,
    userOcId = null
  ) {
    try {
      const stored = JSON.parse(storage.getItem(dayLoopSessionKey) || "null");
      if (
        !stored ||
        stored.identity !==
          projectionSessionIdentity(apiBaseUrl, seed, userOcId)
      ) {
        return null;
      }
      assertDayLoopProjection(stored.projection);
      return stored.projection;
    } catch {
      return null;
    }
  }

  function projectionFromResumeUrl(locationHref) {
    try {
      const serialized = new URL(locationHref).searchParams.get(
        "dayLoopResume"
      );
      if (!serialized) return null;
      const projection = JSON.parse(serialized);
      assertDayLoopProjection(projection);
      return projection;
    } catch {
      return null;
    }
  }

  async function fetchDayLoopProjection(
    fetchImpl,
    apiBaseUrl,
    seed = "frontend-day-loop",
    userOcId = null
  ) {
    const body = { seed };
    if (userOcId) {
      body.userOcId = userOcId;
    }
    const response = await fetchImpl(
      new URL("/api/living-world/day-loop-runs", apiBaseUrl),
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body)
      }
    );
    if (!response.ok) {
      throw new Error(`Day-loop request failed (${response.status || "unknown"})`);
    }
    const projection = await response.json();
    assertDayLoopProjection(projection);
    return projection;
  }

  async function loadOrCreateDayLoopProjection(
    fetchImpl,
    storage,
    apiBaseUrl,
    seed = "frontend-day-loop",
    userOcId = null
  ) {
    const restored = restoreDayLoopProjection(
      storage,
      apiBaseUrl,
      seed,
      userOcId
    );
    if (restored) {
      return restored;
    }
    const projection = await fetchDayLoopProjection(
      fetchImpl,
      apiBaseUrl,
      seed,
      userOcId
    );
    storeDayLoopProjection(
      storage,
      apiBaseUrl,
      seed,
      projection,
      userOcId
    );
    return projection;
  }

  async function fetchAdvanceDayLoopProjection(
    fetchImpl,
    apiBaseUrl,
    runId
  ) {
    const response = await fetchImpl(
      new URL(
        `/api/living-world/day-loop-runs/${encodeURIComponent(runId)}/advance`,
        apiBaseUrl
      ),
      { method: "POST" }
    );
    if (!response.ok) {
      throw new Error(
        `Day-loop advance failed (${response.status || "unknown"})`
      );
    }
    const projection = await response.json();
    assertDayLoopProjection(projection);
    return projection;
  }

  function playDayLoopOnce(
    frames,
    applyFrame,
    scheduleFrame,
    onComplete,
    delayMs = 6000
  ) {
    if (!Array.isArray(frames) || frames.length === 0) {
      throw new Error("Day-loop playback requires at least one frame");
    }
    let index = 0;
    const showNext = () => {
      if (index >= frames.length) {
        onComplete();
        return;
      }
      applyFrame(frames[index]);
      index += 1;
      scheduleFrame(showNext, delayMs);
    };
    showNext();
  }

  return {
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
    projectionFromResumeUrl,
    residentPresentationForActor,
    rowHasCoreSlots,
    restoreDayLoopProjection,
    roomTargetForSlotId,
    scheduledResidentStateFromFrame,
    storeDayLoopProjection,
    slotIdForPosition
  };
});

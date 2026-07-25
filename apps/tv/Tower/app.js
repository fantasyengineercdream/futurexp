const world = document.querySelector("#world");
const viewport = document.querySelector("#viewport");
const floorReadout = document.querySelector("#floorReadout");
const positionReadout = document.querySelector("#positionReadout");
const selection = document.querySelector("#selection");
const selectionLabel = document.querySelector("#selectionLabel");
const selectionName = document.querySelector("#selectionName");
const sourceMark = document.querySelector("#sourceMark");
const coreLocator = document.querySelector("#coreLocator");
const ocImportOpen = document.querySelector("#ocImportOpen");
const ocImportDialog = document.querySelector("#ocImportDialog");
const ocImportClose = document.querySelector("#ocImportClose");
const ocImportForm = document.querySelector("#ocImportForm");
const ocImportSource = document.querySelector("#ocImportSource");
const ocImportSourceText = document.querySelector("#ocImportSourceText");
const ocImportFile = document.querySelector("#ocImportFile");
const ocImportPreview = document.querySelector("#ocImportPreview");
const ocImportReview = document.querySelector("#ocImportReview");
const ocImportName = document.querySelector("#ocImportName");
const ocImportPersona = document.querySelector("#ocImportPersona");
const ocImportConstraints = document.querySelector("#ocImportConstraints");
const ocImportGoals = document.querySelector("#ocImportGoals");
const ocImportStats = document.querySelector("#ocImportStats");
const ocImportAudit = document.querySelector("#ocImportAudit");
const ocImportBack = document.querySelector("#ocImportBack");
const ocImportConfirm = document.querySelector("#ocImportConfirm");
const ocImportDone = document.querySelector("#ocImportDone");
const ocImportDoneName = document.querySelector("#ocImportDoneName");
const ocImportWatch = document.querySelector("#ocImportWatch");
const ocImportError = document.querySelector("#ocImportError");
const pageParams = new URLSearchParams(window.location.search);
const roomAppBaseUrl =
  pageParams.get("roomApp") ||
  new URL("/room/", window.location.origin).href;
const previewMotionMode = pageParams.get("previewMotion");
const dayLoopApiBaseUrl =
  pageParams.get("livingWorldApi") ||
  window.location.origin;
const dayLoopSeed =
  pageParams.get("dayLoopSeed") ||
  "frontend-day-loop";

if (previewMotionMode === "force") {
  document.documentElement.dataset.previewMotion = "force";
}

const TV_COUNT = 8;
const COLS = 26;
const ROWS = 4;
const RADIUS = 690;
const PANEL_RADIUS = 780;
const ROW_OFFSETS = [-231, -77, 77, 231];
const CORE_SHOWCASE_ANGLE = 35;
const CORE_SHOWCASE_SPIN = 0.008;
const FLOORS = [
  { name: "CuteCore", y: 1140, hue: "cute", folder: "CuteCore", ids: [1], spin: -0.018 },
  { name: "SlimeCore", y: 380, hue: "slime", folder: "SlimeCore", ids: [1, 2, 3, 4, 7, 8], spin: 0.017 },
  { name: "SteamPunkCore", y: -380, hue: "steam", folder: "SteamPunkCore", ids: [1], spin: -0.015 },
  { name: "WeirdCore", y: -1140, hue: "weird", folder: "WeirdCore", ids: [1, 2, 3], spin: 0.018 },
];

const camera = {
  ...window.TvRoomBridge.coreShowcaseCamera(),
  speed: 440,
};

const keys = new Set();
const rings = [];
let selectedTv = null;
let dragging = false;
let lastMouse = { x: 0, y: 0 };
let lastTime = performance.now();
let dayLoopTimer = null;
let publicStatusTimer = null;
let worldLoopGeneration = 0;
let pendingOcDraft = null;
const activeUserOcSessionKey = "kaleidoroom.active-user-oc.v1";
const ocImportEnabled = false;

function restoreActiveUserOc() {
  if (!ocImportEnabled) {
    window.sessionStorage.removeItem(activeUserOcSessionKey);
    return null;
  }
  try {
    const value = JSON.parse(
      window.sessionStorage.getItem(activeUserOcSessionKey) || "null"
    );
    if (
      !value ||
      typeof value.actorId !== "string" ||
      typeof value.displayName !== "string"
    ) {
      return null;
    }
    return value;
  } catch {
    return null;
  }
}

let activeUserOc = restoreActiveUserOc();

function tvImage(index) {
  return `./assets/tv-cutout/${(index % TV_COUNT) + 1}.png?v=3`;
}

function wallpaperImage(folder) {
  return `./assets/residents/${folder}/wallpaper.jpg`;
}

function residentImage(floor, index) {
  const id = floor.ids[index % floor.ids.length];
  return `./assets/tv-content/${floor.folder}/${id}.png`;
}

function hasResident(row, col, floorIndex) {
  return ((row * 7 + col * 5 + floorIndex * 11) % 10) < 4;
}

function isTransitSlot(slotId) {
  return typeof slotId === "string" && slotId.startsWith("transit-");
}

function makeTower() {
  FLOORS.forEach((floor, floorIndex) => {
    const mega = document.createElement("section");
    mega.className = "mega-floor";
    mega.dataset.floor = floorIndex + 1;
    mega.dataset.variant = floor.hue;
    mega.style.setProperty("--wallpaper", `url("${wallpaperImage(floor.folder)}")`);
    mega.style.transform = `translate3d(0px, ${-floor.y}px, 0px)`;
    mega.innerHTML = `
      <div class="floor-core floor-core--top"></div>
      <div class="floor-core floor-core--bottom"></div>
      <div class="floor-label">${floor.name}</div>
    `;

    const backdrop = document.createElement("div");
    backdrop.className = "floor-backdrop";
    for (let col = 0; col < COLS; col++) {
      const angle = col * (360 / COLS);
      const panel = document.createElement("div");
      panel.className = "floor-panel";
      panel.style.transform = `rotateY(${angle}deg) translateZ(${PANEL_RADIUS}px) rotateY(180deg)`;
      backdrop.appendChild(panel);
    }
    mega.appendChild(backdrop);

    for (let row = 0; row < ROWS; row++) {
      const ring = document.createElement("div");
      const isCoreRow = window.TvRoomBridge.rowHasCoreSlots(
        floorIndex,
        row
      );
      ring.className = "row-ring";
      ring.dataset.row = String(row);
      ring.dataset.coreShowcase = String(isCoreRow);
      ring.dataset.angle = isCoreRow ? String(CORE_SHOWCASE_ANGLE) : "0";
      ring.dataset.speed = isCoreRow
        ? String(CORE_SHOWCASE_SPIN)
        : String(floor.spin + [0.008, 0.018, 0.028, 0.038][row]);
      ring.style.transform = `translateY(${ROW_OFFSETS[row]}px)`;

      for (let col = 0; col < COLS; col++) {
        const angle = col * (360 / COLS);
        const roomIndex = row * COLS + col;
        const tvIndex = col + floorIndex + row;
        const tv = document.createElement("button");
        tv.type = "button";
        tv.className = "tv-slot";
        tv.dataset.room = `${floor.name} · R${row + 1}-${col + 1}`;
        tv.dataset.variant = floor.hue;
        tv.dataset.tv = String(tvIndex % TV_COUNT);
        tv.dataset.status = hasResident(row, col, floorIndex) ? "occupied" : "vacant";
        const slotId = window.TvRoomBridge.slotIdForPosition(
          floorIndex,
          row,
          col
        );
        const roomTarget = slotId
          ? window.TvRoomBridge.roomTargetForSlotId(slotId)
          : null;
        const corePresentation = slotId
          ? window.TvRoomBridge.corePresentationForSlotId(slotId)
          : null;
        if (slotId) {
          tv.dataset.slotId = slotId;
        }
        if (isTransitSlot(slotId)) {
          tv.dataset.room = "公共信号 · 暂无路过";
          tv.dataset.status = "vacant";
          tv.dataset.transitBaseImageUrl = residentImage(floor, roomIndex);
          tv.setAttribute("aria-label", "公共信号屏，暂无路过");
          if (slotId === "transit-01") {
            tv.dataset.homeResidentId = "resident-demo-user";
            tv.dataset.room = "奶蛙频道 · 当前外出";
            tv.setAttribute("aria-label", "奶蛙频道，当前外出");
          }
        }
        if (roomTarget) {
          tv.dataset.room = roomTarget.displayName;
          tv.dataset.residentId = roomTarget.residentId;
          tv.dataset.roomId = roomTarget.roomId;
          tv.dataset.roleLabel = corePresentation.roleLabel;
          tv.dataset.variant =
            slotId === "core-oo" ? "angel" : "demon";
          tv.dataset.roomUrl = window.TvRoomBridge.buildRoomUrl(
            roomAppBaseUrl,
            roomTarget,
            window.location.href
          );
          tv.dataset.status = "occupied";
          tv.dataset.homeRoomUrl = tv.dataset.roomUrl;
          tv.dataset.homeImageUrl = new URL(
            corePresentation.roomImagePath,
            roomAppBaseUrl
          ).toString();
          tv.setAttribute("aria-label", `进入 ${roomTarget.displayName} 的房间`);
        }
        tv.style.transform = `rotateY(${angle}deg) translateZ(${RADIUS}px) rotateY(180deg)`;
        if (isTransitSlot(slotId)) {
          tv.innerHTML = `
            <span class="tv-screen tv-screen--transit-base">
              <img class="tv-transit-background" src="${tv.dataset.transitBaseImageUrl}" alt="" draggable="false" />
            </span>
            <img class="tv-frame" src="${tvImage(tvIndex)}" alt="" draggable="false" />
          `;
        } else if (tv.dataset.status === "occupied") {
          const screenImage =
            tv.dataset.homeImageUrl || residentImage(floor, roomIndex);
          tv.innerHTML = `
            <span class="tv-screen">
              <img class="tv-content" src="${screenImage}" alt="" draggable="false" />
            </span>
            <img class="tv-frame" src="${tvImage(tvIndex)}" alt="" draggable="false" />
          `;
        } else {
          tv.innerHTML = `
            <span class="tv-screen tv-screen--vacant"></span>
            <img class="tv-frame" src="${tvImage(tvIndex)}" alt="" draggable="false" />
          `;
        }
        tv.addEventListener("click", (event) => {
          event.stopPropagation();
          selectTv(tv);
        });
        if (isTransitSlot(slotId)) {
          tv.addEventListener("mouseenter", () => {
            if (tv.dataset.residentId !== "resident-demo-user") return;
            window.clearInterval(publicStatusTimer);
            selection.hidden = false;
            selectionLabel.textContent =
              tv.dataset.status === "travelling"
                ? "路过状态"
                : "当前活动";
            selectionName.textContent = tv.dataset.room;
          });
        }
        ring.appendChild(tv);
      }

      mega.appendChild(ring);
      rings.push(ring);
    }

    world.appendChild(mega);
  });

  for (let i = 0; i < 10; i++) {
    const ghost = document.createElement("section");
    ghost.className = "mega-floor";
    const y = -1900 - i * 760;
    ghost.style.opacity = String(Math.max(0.08, 0.34 - i * 0.028));
    ghost.style.transform = `translate3d(0px, ${-y}px, 0px) scale(${1 + i * 0.035})`;
    ghost.innerHTML = `<div class="floor-core floor-core--top"></div><div class="floor-core floor-core--bottom"></div>`;
    world.appendChild(ghost);
  }
}

function televisionForSlot(slotId) {
  return document.querySelector(`[data-slot-id="${slotId}"]`);
}

function showSnowScreen(tv) {
  const screen = tv.querySelector(".tv-screen");
  screen.className = "tv-screen tv-screen--vacant";
  screen.replaceChildren();
}

function showResidentScreen(tv, imageUrl, className = "tv-content") {
  const screen = tv.querySelector(".tv-screen");
  const resident = document.createElement("img");
  resident.className = className;
  resident.src = imageUrl;
  resident.alt = "";
  resident.draggable = false;
  screen.className =
    className === "tv-transit-resident"
      ? "tv-screen tv-screen--transit"
      : "tv-screen";
  screen.replaceChildren(resident);
}

function showTransitBaseScreen(tv) {
  const screen = tv.querySelector(".tv-screen");
  const background = document.createElement("img");
  background.className = "tv-transit-background";
  background.src = tv.dataset.transitBaseImageUrl;
  background.alt = "";
  background.draggable = false;
  screen.className = "tv-screen tv-screen--transit-base";
  screen.replaceChildren(background);
}

function showTransitResident(tv, imageUrl) {
  showTransitBaseScreen(tv);
  const screen = tv.querySelector(".tv-screen");
  const resident = document.createElement("img");
  resident.className = "tv-transit-resident";
  resident.src = imageUrl;
  resident.alt = "";
  resident.draggable = false;
  screen.classList.add("tv-screen--transit");
  screen.appendChild(resident);
}

function showPresentResident(tv, imageUrl) {
  showTransitBaseScreen(tv);
  const screen = tv.querySelector(".tv-screen");
  const resident = document.createElement("img");
  resident.className = "tv-present-resident";
  resident.src = imageUrl;
  resident.alt = "";
  resident.draggable = false;
  screen.classList.add("tv-screen--transit");
  screen.appendChild(resident);
}

function showImportedResident(tv, state) {
  showTransitBaseScreen(tv);
  const screen = tv.querySelector(".tv-screen");
  const resident = document.createElement("span");
  resident.className =
    state.mode === "travelling"
      ? "tv-transit-resident tv-imported-resident"
      : "tv-present-resident tv-imported-resident";
  resident.textContent = "◆";
  resident.setAttribute("aria-hidden", "true");
  screen.classList.add("tv-screen--transit");
  screen.appendChild(resident);
}

function setCorePresence(slotId, isHome, statusText = "") {
  const tv = televisionForSlot(slotId);
  const roomTarget = window.TvRoomBridge.roomTargetForSlotId(slotId);
  if (!tv || !roomTarget) return;

  if (isHome) {
    tv.dataset.status = "occupied";
    tv.dataset.room = roomTarget.displayName;
    tv.dataset.roomUrl = tv.dataset.homeRoomUrl;
    tv.setAttribute(
      "aria-label",
      statusText
        ? `进入 ${roomTarget.displayName} 的房间。${statusText}`
        : `进入 ${roomTarget.displayName} 的房间`
    );
    showResidentScreen(tv, tv.dataset.homeImageUrl);
    return;
  }

  tv.dataset.status = "away";
  tv.dataset.room = statusText || `${roomTarget.displayName} 不在房间`;
  delete tv.dataset.roomUrl;
  tv.setAttribute(
    "aria-label",
    statusText || `${roomTarget.displayName} 不在房间`
  );
  showResidentScreen(tv, tv.dataset.homeImageUrl);
  tv.querySelector(".tv-content")?.classList.add("tv-content--away");
}

function clearTransitScreens() {
  document.querySelectorAll('[data-slot-id^="transit-"]').forEach(
    (transitTv) => {
      const isMilkFrogHome =
        transitTv.dataset.homeResidentId === "resident-demo-user";
      transitTv.dataset.status = isMilkFrogHome ? "home-vacant" : "vacant";
      transitTv.dataset.room = isMilkFrogHome
        ? "奶蛙频道 · 当前外出"
        : "公共信号 · 暂无路过";
      delete transitTv.dataset.residentId;
      delete transitTv.dataset.roomUrl;
      if (isMilkFrogHome) {
        transitTv.dataset.roleLabel = "奶蛙频道 · 外出";
        transitTv.setAttribute("aria-label", "奶蛙频道，当前外出");
      } else {
        delete transitTv.dataset.roleLabel;
        transitTv.setAttribute("aria-label", "公共信号屏，暂无路过");
      }
      transitTv.removeAttribute("aria-disabled");
      transitTv.disabled = true;
      transitTv.tabIndex = -1;
      transitTv.style.pointerEvents = "none";
      showTransitBaseScreen(transitTv);
    }
  );
}

function applyResidentScreenState(state) {
  if (!state || !isTransitSlot(state.slotId)) return;
  if (state.mode !== "travelling" && state.mode !== "present") {
    clearTransitScreens();
    return;
  }

  clearTransitScreens();
  const transitTv = televisionForSlot(state.slotId);
  if (!transitTv) return;

  transitTv.dataset.status = state.mode;
  transitTv.dataset.room = state.rpgSummary
    ? `${state.statusText} · ${state.rpgSummary}`
    : state.statusText;
  transitTv.dataset.residentId = state.residentId;
  if (state.roomId) {
    transitTv.dataset.roomId = state.roomId;
  } else {
    delete transitTv.dataset.roomId;
  }
  transitTv.dataset.roleLabel = state.canEnter
    ? `${state.displayName} · 回到房间`
    : state.mode === "travelling"
      ? `${state.displayName} · 路过中`
      : `${state.displayName} · 在此活动`;
  if (state.canEnter && state.roomUrl) {
    transitTv.dataset.roomUrl = state.roomUrl;
  } else {
    delete transitTv.dataset.roomUrl;
  }
  transitTv.setAttribute("aria-label", transitTv.dataset.room);
  transitTv.setAttribute(
    "aria-disabled",
    state.canEnter ? "false" : "true"
  );
  transitTv.disabled = false;
  transitTv.tabIndex = state.canEnter ? 0 : -1;
  transitTv.style.pointerEvents = "";
  if (!state.spriteUrl) {
    showImportedResident(transitTv, state);
  } else if (state.mode === "travelling") {
    showTransitResident(transitTv, state.spriteUrl);
  } else {
    showPresentResident(transitTv, state.spriteUrl);
  }
}

function applyScheduledResidentState(state) {
  if (!state || state.advancedBy !== "scheduler") return;
  applyResidentScreenState(state);
}

function applyDayLoopFrame(frame) {
  frame.coreStates.forEach((state) => {
    setCorePresence(state.slotId, state.isHome, state.statusText);
  });
  applyScheduledResidentState(frame.scheduledResidentState);
  selection.hidden = false;
  selectionLabel.textContent = `WORLD · ${frame.phaseLabel}`;
  cycleFramePublicStatus(frame.publicStatusItems);
}

function cycleFramePublicStatus(items) {
  window.clearInterval(publicStatusTimer);
  const publicItems =
    Array.isArray(items) && items.length > 0
      ? items
      : ["公共状态更新中"];
  let itemIndex = 0;
  selectionName.textContent = publicItems[itemIndex];
  if (publicItems.length === 1) return;
  publicStatusTimer = window.setInterval(() => {
    itemIndex = (itemIndex + 1) % publicItems.length;
    selectionName.textContent = publicItems[itemIndex];
  }, 1800);
}

function bindRoomLinksToProjection(projection) {
  ["core-oo", "core-cc"].forEach((slotId) => {
    const television = televisionForSlot(slotId);
    const target = window.TvRoomBridge.roomTargetForSlotId(slotId);
    if (!television || !target) return;
    const memory = projection.memoryRefs.find(
      (item) =>
        item.actorId === target.residentId &&
        item.available === true
    );

    const roomUrl = window.TvRoomBridge.buildRoomUrl(
      roomAppBaseUrl,
      target,
      window.location.href,
      projection.runId,
      {
        apiBaseUrl: dayLoopApiBaseUrl,
        dayIndex: projection.dayIndex,
        episodeRef: memory?.memoryRef
      }
    );
    television.dataset.homeRoomUrl = roomUrl;
    if (television.dataset.status === "occupied") {
      television.dataset.roomUrl = roomUrl;
    }
  });
}

async function startLivingWorldLoop(generation = ++worldLoopGeneration) {
  const userOc = activeUserOc;
  const seed = userOc ? "bring-your-oc-demo" : dayLoopSeed;
  const userOcId = userOc?.actorId ?? null;
  try {
    const storedProjection =
      window.TvRoomBridge.restoreDayLoopProjection(
        window.sessionStorage,
        dayLoopApiBaseUrl,
        seed,
        userOcId
      );
    const resumedProjection =
      window.TvRoomBridge.projectionFromResumeUrl(window.location.href);
    const canResume =
      resumedProjection &&
      storedProjection &&
      resumedProjection.runId === storedProjection.runId &&
      resumedProjection.dayIndex === storedProjection.dayIndex + 1;
    let projection = canResume
      ? resumedProjection
      : await window.TvRoomBridge.loadOrCreateDayLoopProjection(
          window.fetch.bind(window),
          window.sessionStorage,
          dayLoopApiBaseUrl,
          seed,
          userOcId
        );
    if (canResume) {
      window.TvRoomBridge.storeDayLoopProjection(
        window.sessionStorage,
        dayLoopApiBaseUrl,
        seed,
        projection,
        userOcId
      );
      const cleanUrl = new URL(window.location.href);
      cleanUrl.searchParams.delete("dayLoopResume");
      window.history.replaceState(null, "", cleanUrl);
    }
    document.documentElement.dataset.worldSource = "api";
    bindRoomLinksToProjection(projection);
    while (generation === worldLoopGeneration) {
      sourceMark.textContent = `DEMO · API · D${projection.dayIndex}`;
      const userMemory = userOc
        ? projection.memoryRefs.find(
            (item) =>
              item.actorId === userOc.actorId &&
              item.available === true
          )
        : null;
      const userOcForProjection = userOc
        ? {
            ...userOc,
            roomUrl: window.TvRoomBridge.buildRoomUrl(
              roomAppBaseUrl,
              {
                residentId: userOc.actorId,
                roomId: "room-demo-user"
              },
              window.location.href,
              projection.runId,
              {
                apiBaseUrl: dayLoopApiBaseUrl,
                dayIndex: projection.dayIndex,
                episodeRef: userMemory?.memoryRef
              }
            )
          }
        : null;
      const frames = window.TvRoomBridge.dayLoopFramesFromProjection(
        projection,
        window.location.href,
        userOcForProjection
      );
      await new Promise((resolve) => {
        window.TvRoomBridge.playDayLoopOnce(
          frames,
          (frame) => {
            if (generation === worldLoopGeneration) {
              applyDayLoopFrame(frame);
            }
          },
          (callback, delay) => {
            dayLoopTimer = window.setTimeout(() => {
              if (generation !== worldLoopGeneration) {
                resolve();
                return;
              }
              callback();
            }, delay);
          },
          resolve
        );
      });
      if (generation !== worldLoopGeneration) return;
      projection =
        await window.TvRoomBridge.fetchAdvanceDayLoopProjection(
          window.fetch.bind(window),
          dayLoopApiBaseUrl,
          projection.runId
        );
      window.TvRoomBridge.storeDayLoopProjection(
        window.sessionStorage,
        dayLoopApiBaseUrl,
        seed,
        projection,
        userOcId
      );
      bindRoomLinksToProjection(projection);
    }
  } catch {
    if (generation !== worldLoopGeneration) return;
    sourceMark.textContent = "PREVIEW · OFFLINE";
    document.documentElement.dataset.worldSource = "fixture";
    applyResidentScreenState(
      window.TvRoomBridge.previewResidentHomeState(
        window.location.href
      )
    );
  }
}

function restartLivingWorldLoop() {
  worldLoopGeneration += 1;
  void startLivingWorldLoop(worldLoopGeneration);
}

const rpgLabels = {
  seriousness: "认真",
  rebellion: "叛逆",
  fitness: "体能",
  inspiration: "灵感"
};
let ocImportFileName = "pasted-oc.txt";

function setOcImportError(message = "") {
  ocImportError.hidden = !message;
  ocImportError.textContent = message;
}

function setOcImportBusy(button, busy, busyLabel, idleLabel) {
  button.disabled = busy;
  button.textContent = busy ? busyLabel : idleLabel;
}

function splitReviewLines(value) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function showImportSource() {
  pendingOcDraft = null;
  ocImportSource.hidden = false;
  ocImportReview.hidden = true;
  ocImportDone.hidden = true;
  setOcImportError();
}

function showImportDraft(draft) {
  pendingOcDraft = draft;
  ocImportName.value = draft.roleplayConfig.displayName;
  ocImportPersona.value = draft.roleplayConfig.persona;
  ocImportConstraints.value =
    draft.livingWorldProfile.personaConstraints.join("\n");
  ocImportGoals.value = draft.livingWorldProfile.goals.join("\n");
  ocImportStats.replaceChildren(
    ...Object.entries(rpgLabels).map(([key, label]) => {
      const wrapper = document.createElement("label");
      wrapper.className = "oc-import-stat";
      wrapper.textContent = label;
      const input = document.createElement("input");
      input.type = "number";
      input.min = "-2";
      input.max = "5";
      input.step = "1";
      input.required = true;
      input.dataset.stat = key;
      input.value = String(draft.rpgStats[key]);
      wrapper.appendChild(input);
      return wrapper;
    })
  );
  ocImportAudit.textContent = draft.auditNotices.join(" · ");
  ocImportSource.hidden = true;
  ocImportReview.hidden = false;
  ocImportDone.hidden = true;
  setOcImportError();
}

function reviewedDraft() {
  const personaConstraints = splitReviewLines(ocImportConstraints.value);
  const goals = splitReviewLines(ocImportGoals.value);
  const rpgStats = Object.fromEntries(
    Array.from(ocImportStats.querySelectorAll("[data-stat]")).map((input) => [
      input.dataset.stat,
      Number(input.value)
    ])
  );
  if (
    !pendingOcDraft ||
    !ocImportName.value.trim() ||
    !ocImportPersona.value.trim() ||
    personaConstraints.length === 0 ||
    goals.length === 0 ||
    Object.values(rpgStats).some(
      (value) => !Number.isInteger(value) || value < -2 || value > 5
    )
  ) {
    throw new Error("请确认角色设定，并将四项 RPG 属性填写为 -2 到 5 的整数");
  }
  return {
    ...pendingOcDraft,
    roleplayConfig: {
      ...pendingOcDraft.roleplayConfig,
      displayName: ocImportName.value.trim(),
      persona: ocImportPersona.value.trim()
    },
    livingWorldProfile: {
      ...pendingOcDraft.livingWorldProfile,
      personaConstraints,
      goals
    },
    rpgStats
  };
}

ocImportOpen.addEventListener("click", () => {
  if (!ocImportEnabled) return;
  showImportSource();
  ocImportDialog.showModal();
});

ocImportClose.addEventListener("click", () => ocImportDialog.close());
ocImportDialog.addEventListener("cancel", () => setOcImportError());
ocImportBack.addEventListener("click", showImportSource);

ocImportFile.addEventListener("change", async () => {
  const [file] = Array.from(ocImportFile.files || []);
  if (!file) return;
  try {
    ocImportFileName = file.name;
    ocImportSourceText.value = await file.text();
    setOcImportError();
  } catch {
    setOcImportError("无法读取这份文字文件，请直接粘贴设定");
  }
});

ocImportForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!ocImportEnabled) return;
  setOcImportError();
  setOcImportBusy(
    ocImportPreview,
    true,
    "正在整理创作者设定…",
    "整理成待确认草稿"
  );
  try {
    const draft = await window.OcImportClient.previewOcImport(
      window.fetch.bind(window),
      dayLoopApiBaseUrl,
      {
        sourceName: ocImportFileName,
        sourceText: ocImportSourceText.value
      }
    );
    showImportDraft(draft);
  } catch (error) {
    setOcImportError(
      error instanceof Error ? error.message : "角色草稿生成失败"
    );
  } finally {
    setOcImportBusy(
      ocImportPreview,
      false,
      "正在整理创作者设定…",
      "整理成待确认草稿"
    );
  }
});

ocImportConfirm.addEventListener("click", async () => {
  if (!ocImportEnabled) return;
  setOcImportError();
  setOcImportBusy(
    ocImportConfirm,
    true,
    "正在注册并启动世界…",
    "确认并加入活世界"
  );
  try {
    const draft = reviewedDraft();
    const registered = await window.OcImportClient.confirmOcImport(
      window.fetch.bind(window),
      dayLoopApiBaseUrl,
      draft
    );
    const stats = registered.runtimeProfile.rpgStats;
    activeUserOc = {
      actorId: registered.ocId,
      displayName: registered.character.name,
      rpgStats: stats,
      rpgSummary: Object.entries(rpgLabels)
        .map(([key, label]) => `${label}${stats[key]}`)
        .join(" "),
      spriteUrl: null
    };
    window.sessionStorage.setItem(
      activeUserOcSessionKey,
      JSON.stringify(activeUserOc)
    );
    ocImportDoneName.textContent =
      `${activeUserOc.displayName} · ${activeUserOc.rpgSummary}`;
    ocImportSource.hidden = true;
    ocImportReview.hidden = true;
    ocImportDone.hidden = false;
    restartLivingWorldLoop();
  } catch (error) {
    setOcImportError(
      error instanceof Error ? error.message : "角色确认失败"
    );
  } finally {
    setOcImportBusy(
      ocImportConfirm,
      false,
      "正在注册并启动世界…",
      "确认并加入活世界"
    );
  }
});

ocImportWatch.addEventListener("click", () => {
  ocImportDialog.close();
  coreLocator.click();
});

function selectTv(tv) {
  if (tv.disabled || tv.getAttribute("aria-disabled") === "true") return;

  window.clearInterval(publicStatusTimer);
  selectedTv?.classList.remove("is-selected");
  selectedTv = tv;
  selectedTv.classList.add("is-selected");
  selection.hidden = false;
  selectionLabel.textContent = tv.dataset.roomUrl ? "进入房间" : "当前状态";
  selectionName.textContent = tv.dataset.room;

  if (tv.dataset.roomUrl) {
    window.location.assign(tv.dataset.roomUrl);
  }
}

function updateCameraTransform() {
  world.style.transform =
    `rotateX(${-camera.pitch}deg) rotateY(${-camera.yaw}deg) ` +
    `translate3d(${-camera.x}px, ${camera.y}px, ${-camera.z}px)`;

  const closest = FLOORS.reduce((best, floor, index) => {
    const dist = Math.abs(camera.y - floor.y);
    return dist < best.dist ? { index, dist } : best;
  }, { index: 0, dist: Infinity });

  floorReadout.textContent = `Near ${FLOORS[closest.index].name}`;
  positionReadout.textContent = `X ${Math.round(camera.x)} · Y ${Math.round(camera.y)} · Z ${Math.round(camera.z)}`;
  document.documentElement.style.setProperty("--sky-opacity", String(Math.max(0.05, Math.min(0.62, (camera.y + 500) / 1800))));
  document.documentElement.style.setProperty("--abyss-opacity", String(Math.max(0.35, Math.min(0.96, (-camera.y + 500) / 1600))));
}

function moveCameraForInput(key, step) {
  const { forward, right } = window.TvRoomBridge.cameraBasisForView(
    camera.yaw
  );

  if (key === "w") {
    camera.x += forward.x * step;
    camera.z += forward.z * step;
  }
  if (key === "s") {
    camera.x -= forward.x * step;
    camera.z -= forward.z * step;
  }
  if (key === "a") {
    camera.x -= right.x * step;
    camera.z -= right.z * step;
  }
  if (key === "d") {
    camera.x += right.x * step;
    camera.z += right.z * step;
  }
  if (key === " ") camera.y += step;
  if (key === "Shift") camera.y -= step;
}

function tick(now) {
  const dt = Math.min(0.05, (now - lastTime) / 1000);
  lastTime = now;

  const boosted = keys.has("Alt") ? 2.1 : 1;
  const step = camera.speed * boosted * dt;

  keys.forEach((key) => moveCameraForInput(key, step));

  rings.forEach((ring) => {
    const angle = Number(ring.dataset.angle) + Number(ring.dataset.speed) * dt * 60;
    ring.dataset.angle = String(angle);
    const rowOffset = ROW_OFFSETS[Number(ring.dataset.row)];
    ring.style.transform = `translateY(${rowOffset}px) rotateY(${angle}deg)`;
  });

  updateCameraTransform();
  requestAnimationFrame(tick);
}

window.addEventListener("keydown", (event) => {
  if (
    event.target instanceof Element &&
    event.target.closest("input, textarea, dialog")
  ) {
    return;
  }
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  if (!keys.has(key) && ["w", "a", "s", "d", " ", "Shift"].includes(key)) {
    moveCameraForInput(key, camera.speed * 0.065);
    event.preventDefault();
  }
  keys.add(key);
});

window.addEventListener("keyup", (event) => {
  keys.delete(event.key.length === 1 ? event.key.toLowerCase() : event.key);
});

viewport.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || event.target.closest(".tv-slot")) return;
  dragging = true;
  lastMouse = { x: event.clientX, y: event.clientY };
  viewport.setPointerCapture(event.pointerId);
});

viewport.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const dx = event.clientX - lastMouse.x;
  const dy = event.clientY - lastMouse.y;
  lastMouse = { x: event.clientX, y: event.clientY };
  camera.yaw += dx * 0.16;
  camera.pitch = Math.max(-62, Math.min(58, camera.pitch + dy * 0.12));
});

viewport.addEventListener("pointerup", (event) => {
  dragging = false;
  try {
    viewport.releasePointerCapture(event.pointerId);
  } catch {}
});

viewport.addEventListener("wheel", (event) => {
  camera.y += event.deltaY > 0 ? -70 : 70;
}, { passive: true });

coreLocator.addEventListener("click", () => {
  const coreRing = document.querySelector('[data-core-showcase="true"]');
  if (coreRing) {
    coreRing.dataset.angle = String(CORE_SHOWCASE_ANGLE);
  }
  Object.assign(camera, window.TvRoomBridge.coreShowcaseCamera());
  updateCameraTransform();
});

makeTower();
updateCameraTransform();
void startLivingWorldLoop();
requestAnimationFrame(tick);

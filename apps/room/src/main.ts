import "./style.css";
import { MicrophoneCapture, PcmPlayback } from "./audio";
import {
  CHARACTERS,
  type CharacterConfig,
  type CharacterId,
} from "./characters";
import { warmPortraitCache } from "./portrait-cache";
import {
  describeStartError,
  finalDialogueForEvent,
  RealtimeClient,
  shouldRetrySilentResponse,
  shouldRetryTimedOutResponse,
  shouldReplaceCurrentSubtitle,
  voiceStartupAfterReady,
  type FinalDialogue,
  type RealtimeEvent,
} from "./realtime";
import {
  initialRoomState,
  reduceRoomState,
  type RoomEvent,
  type RoomState,
  type RoomView,
} from "./room-state";
import {
  describeRingConnectionError,
  type InnerOsStatus,
  resolveDeviceId,
  RingAudioBridge,
  ringReconnectDelayMs,
} from "./ring-bridge";
import {
  resolveRoomCharacter,
  resolveRoomResidentId,
  resolveRoomReturnTarget,
} from "./room-link";
import {
  isImportedOcId,
  loadRegisteredOc,
  toDynamicRoomCharacter,
  type DynamicRoomCharacter,
} from "./registered-oc";
import {
  OwnerAdviceConfirmation,
  OwnerConversationMemoryRecorder,
  counselCurrentOwner,
  loadCurrentOwnerJournal,
  loadCurrentOwnerPrivateOsContext,
  ownerJournalSectionTitle,
  recordOwnerConversationMemory,
  resolveOwnerLivingWorldContext,
  type OwnerDecisionContext,
  type DeliveredInnerOs,
  type OwnerJournalEntry,
} from "./living-world";

export const appTitle = "OC ROOM";
export const appVersion = "BUILD 2026.07.25.13";
export const roomUiText = {
  deviceRing: "戒指",
  deviceMicrophone: "麦克风",
  start: "开始",
  end: "结束",
  back: "返回",
  ringWaiting: "正在等待 Zilo 指环",
} as const;

type ActionSpec = {
  id: string;
  label: string;
  kind?: "primary" | "danger" | "quiet";
  disabled?: boolean;
};

type ActiveRoomCharacter = CharacterConfig | DynamicRoomCharacter;

if (typeof document !== "undefined") {
  const app = document.querySelector<HTMLDivElement>("#app");
  if (!app) throw new Error("Missing #app");

  app.innerHTML = `
    <main class="game-shell" aria-label="OC 语音房间">
      <section class="room-stage" id="room-stage" data-view="idle" data-character="devil">
        <img class="room-art" id="room-art" alt="" decoding="async" fetchpriority="high" loading="eager">

        <header class="game-hud">
          <div class="room-status">
            <span class="status-light" id="status-light"></span>
            <span id="connection">房间在线</span>
            <span class="inner-os-link checking" id="inner-os-link">内心 OS 检查中</span>
            <span id="capacity">0 / 8</span>
            <span class="build-id">${appVersion}</span>
          </div>
          <button class="room-exit" id="room-exit" type="button">← 返回无限电视塔</button>
        </header>

        <button class="scene-object mirror-object" id="mirror" type="button" aria-label="点击镜子选择对话设备">
          <span>镜子</span>
        </button>
        <button class="scene-object bed-object" id="bed" type="button" aria-label="点击床休息">
          <span>休息</span>
        </button>
        <button class="scene-object mailbox-object" id="mailbox" type="button" aria-label="点击信箱打开日记">
          <span>日记</span>
        </button>

        <button class="character-sprite" id="portrait" type="button" aria-label="戳一下当前角色">
          <img id="portrait-art" alt="" decoding="async" fetchpriority="high" loading="eager">
        </button>
        <div class="sleeping-character" aria-hidden="true">
          <span class="sleeping-head"></span>
          <span class="sleeping-body"></span>
          <span class="sleeping-mark"></span>
        </div>

         <aside class="journal-book" id="journal" hidden aria-label="角色日记">
           <div class="book-page book-page-left">
             <span class="book-kicker" id="journal-day-label">DAY —</span>
             <h2 id="journal-title">日志暂不可读取</h2>
             <p id="journal-copy">等待读取当前 OC 的真实经历。</p>
             <div class="journal-sections" id="journal-sections" hidden></div>
             <h3 class="journal-changes-heading" id="journal-changes-heading" hidden>留下的变化</h3>
             <ul class="journal-changes" id="journal-changes" hidden></ul>
           </div>
           <div class="book-page book-page-right">
             <span class="book-kicker">OWNER SAFE</span>
             <h2 id="journal-owner-heading">当前 OC 所经历的版本</h2>
             <p>这里不会出现其他 OC 的视角，也不会读取她没有亲历的事实。</p>
             <nav class="journal-navigation" aria-label="日记日期">
               <button id="journal-newer" type="button" class="game-button quiet" data-action="journal-newer">较新一天</button>
               <span id="journal-position" aria-live="polite">— / —</span>
               <button id="journal-older" type="button" class="game-button quiet" data-action="journal-older">较早一天</button>
             </nav>
             <button type="button" class="game-button quiet" data-action="close-journal">合上日记</button>
           </div>
        </aside>

        <section class="vn-dialogue" aria-live="polite">
          <div class="dialogue-heading">
            <strong id="speaker">小恶魔女仆</strong>
            <span id="phase">房间待机</span>
          </div>
          <p class="previous-user-line" id="previous-user-line" hidden>
            <strong>你</strong>
            <span id="previous-user-text"></span>
           </p>
           <p id="transcript">房间已连接。点击镜子和她说话。</p>
           <section class="advice-confirmation" id="advice-confirmation" hidden aria-label="确认主人建议">
             <p>把这句话作为给 <strong id="advice-resident">OC</strong> 的建议吗？</p>
             <blockquote id="advice-quote"></blockquote>
             <button class="game-button primary" id="confirm-advice" type="button">确认建议</button>
             <p id="advice-result" role="status"></p>
           </section>
           <div class="dialogue-footer">
            <span class="device-note" id="device-note">点击镜子开始对话</span>
            <div class="dialogue-actions" id="dialogue-actions"></div>
          </div>
        </section>

        <div class="scanlines" aria-hidden="true"></div>
      </section>
    </main>`;

  const byId = <T extends HTMLElement>(id: string) =>
    document.getElementById(id) as T;

  const selected: CharacterId = resolveRoomCharacter(location.search);
  const roomResidentId = resolveRoomResidentId(location.search);
  const importedRoom = isImportedOcId(roomResidentId);
  const importedApiBaseUrl = new URLSearchParams(location.search).get(
    "livingWorldApi",
  );
  const livingWorldContext = resolveOwnerLivingWorldContext(location.search);
  const adviceConfirmation = new OwnerAdviceConfirmation();
  const conversationMemoryRecorder = livingWorldContext
    ? new OwnerConversationMemoryRecorder(livingWorldContext)
    : null;
  const roomReturnTarget = resolveRoomReturnTarget(location.search);
  const roomExitButton = byId<HTMLButtonElement>("room-exit");
  roomExitButton.textContent = roomReturnTarget ? "← 返回无限电视塔" : "← 退出房间";
  let roomState: RoomState = { ...initialRoomState };
  let ownerJournalEntries: OwnerJournalEntry[] = [];
  let selectedJournalIndex = 0;
  let microphoneActive = false;
  let muted = false;
  let interruptions = 0;
  let responseRequestedAt = 0;
  let firstAudioSeen = false;
  let silentResponseRetries = 0;
  let assistantBuffer = "";
  let currentUserTranscript = "";
  let assistantTurnStarted = false;
  let openingSent = false;
  let openingInProgress = false;
  let client: RealtimeClient | undefined;
  let microphone: MicrophoneCapture | undefined;
  let playback: PcmPlayback | undefined;
  let ringBridge: RingAudioBridge | undefined;
  let ringSessionWanted = false;
  let ringReconnectAttempt = 0;
  let ringReconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let pendingDecisionContext: OwnerDecisionContext | undefined;
  let activeCharacter: ActiveRoomCharacter = importedRoom
    ? {
        ...CHARACTERS.angel,
        id: roomResidentId,
        name: "正在载入角色…",
        serial: "IMPORTED OC / PREVIEW ROOM",
        summary: "正在读取创作者确认的人设",
        portraitImage: "",
        portraitAlt: "导入角色暂无立绘",
        greeting: "角色资料载入中。",
        poke: "角色资料载入中。",
        instructions: "",
        dynamicVoiceProfile: {
          id: roomResidentId,
          name: "正在载入角色",
          role: "导入角色",
          persona: "等待已确认角色资料",
          publicStyle: "等待已确认角色资料",
          goals: ["等待已确认角色资料"],
        },
      }
    : CHARACTERS[selected];
  let importedCharacterReady = !importedRoom;

  function deliverPendingDecisionContext(): void {
    if (!pendingDecisionContext) return;
    if (client) {
      client.setDecisionContext(pendingDecisionContext);
      pendingDecisionContext = undefined;
      return;
    }
    if (ringBridge) {
      ringBridge.setDecisionContext(pendingDecisionContext);
      pendingDecisionContext = undefined;
    }
  }

  void warmPortraitCache([
    activeCharacter.roomImage,
    activeCharacter.portraitImage,
  ].filter(Boolean));

  function actionsForView(view: RoomView): ActionSpec[] {
    switch (view) {
      case "device-select":
        return [
          ...(
            importedRoom
              ? []
              : [{
                  id: "choose-ring",
                  label: roomUiText.deviceRing,
                  kind: "primary" as const,
                }]
          ),
          {
            id: "choose-microphone",
            label: roomUiText.deviceMicrophone,
            kind: "primary",
          },
          { id: "back-room", label: roomUiText.back, kind: "quiet" },
        ];
      case "microphone-ready":
        return [
          { id: "start-microphone", label: roomUiText.start, kind: "primary" },
          { id: "end-session", label: roomUiText.end, kind: "danger" },
          { id: "back-devices", label: "返回设备", kind: "quiet" },
        ];
      case "microphone-connecting":
      case "microphone-live":
        return [
          {
            id: "start-microphone",
            label: roomUiText.start,
            kind: "primary",
            disabled: true,
          },
          { id: "end-session", label: roomUiText.end, kind: "danger" },
        ];
      case "ring-connecting":
      case "ring-live":
        return [
          { id: "end-session", label: roomUiText.end, kind: "danger" },
          { id: "back-devices", label: "返回设备", kind: "quiet" },
        ];
      case "error":
        return [
          { id: "retry-session", label: "重试", kind: "primary" },
          { id: "back-devices", label: "返回设备", kind: "quiet" },
        ];
      case "resting":
        return [{ id: "back-room", label: "起床", kind: "quiet" }];
      default:
        return [];
    }
  }

  function renderActions(): void {
    const container = byId<HTMLDivElement>("dialogue-actions");
    const actions = actionsForView(roomState.view);
    container.innerHTML = actions
      .map(
        (action) => `
          <button
            type="button"
            class="game-button ${action.kind ?? "quiet"}"
            data-action="${action.id}"
            ${action.disabled ? "disabled" : ""}
          >${action.label}</button>`,
      )
      .join("");

    container
      .querySelectorAll<HTMLButtonElement>("[data-action]")
      .forEach((button) => {
        button.addEventListener("click", () => {
          void handleAction(button.dataset.action ?? "");
        });
      });
  }

  function renderState(): void {
    const stage = byId<HTMLElement>("room-stage");
    stage.dataset.view = roomState.view;
    stage.dataset.character = selected;
    stage.dataset.residentId = activeCharacter.id;
    byId("speaker").textContent = roomState.speaker;
    byId("phase").textContent = roomState.phase;
    byId("transcript").textContent = roomState.caption;
    byId("journal").hidden = roomState.view !== "journal";

    const note = byId("device-note");
    if (roomState.device === "ring") {
      note.textContent = "云端戒指通道";
    } else if (roomState.device === "microphone") {
      note.textContent = "电脑麦克风实时全双工";
    } else {
      note.textContent = "点击镜子开始对话";
    }

    const connected =
      roomState.view === "microphone-live" || roomState.view === "ring-live";
    byId("status-light").classList.toggle("connected", connected);
    renderActions();
  }

  function setInnerOsStatus(status: InnerOsStatus): void {
    const badge = byId("inner-os-link");
    badge.classList.remove(
      "checking",
      "connected",
      "delivered",
      "unavailable",
    );
    if (status === "delivered") {
      badge.textContent = "内心 OS 已下发";
      badge.classList.add("delivered");
    } else if (status === "ready" || status === "sent") {
      badge.textContent = "内心 OS 已接通";
      badge.classList.add("connected");
    } else {
      badge.textContent = "内心 OS 暂未接通";
      badge.classList.add("unavailable");
      if (
        conversationMemoryRecorder?.awaitingDelivery
        && (status === "unavailable" || status === "error")
      ) {
        byId("advice-result").textContent =
          "本轮未写入记忆：OC 签证心声尚未成功送达。";
      }
    }
  }

  async function recordDeliveredInnerOs(
    delivery: DeliveredInnerOs,
  ): Promise<void> {
    if (!conversationMemoryRecorder || !livingWorldContext) return;
    try {
      const result = await conversationMemoryRecorder.recordDelivery(
        delivery,
        (input) =>
          recordOwnerConversationMemory(
            window.fetch.bind(window),
            livingWorldContext,
            input,
          ),
      );
      if (result === "recorded") {
        byId("advice-result").textContent =
          "本轮对话与心声已写入她的记忆。";
      }
    } catch {
      byId("advice-result").textContent =
        "本轮未写入记忆：真实记忆接口提交失败。";
    }
  }

  async function refreshInnerOsStatus(): Promise<void> {
    if (importedRoom) {
      setInnerOsStatus("unavailable");
      return;
    }
    let deviceId;
    try {
      deviceId = ringDeviceId();
    } catch {
      setInnerOsStatus("unavailable");
      return;
    }
    try {
      const response = await fetch(
        `/api/device/status?${new URLSearchParams({ deviceId })}`,
        { cache: "no-store" },
      );
      if (!response.ok) throw new Error("status unavailable");
      const result = await response.json() as { inner_os?: InnerOsStatus };
      setInnerOsStatus(result.inner_os ?? "unavailable");
    } catch {
      setInnerOsStatus("unavailable");
    }
  }

  function dispatch(event: RoomEvent): void {
    roomState = reduceRoomState(roomState, event);
    renderState();
  }

  function idleState(useGreeting = false): RoomState {
    const character = activeCharacter;
    return {
      view: "idle",
      speaker: character.name,
      caption: useGreeting
        ? character.greeting
        : importedRoom
          ? `${character.name} 正在临时房间里。点击镜子和 TA 说话。`
          : selected === "devil"
          ? "CC 正在房间里。点击镜子和她说话。"
          : "OO 正在房间里。点击镜子和她说话。",
      phase: "房间待机",
    };
  }

  function renderCharacter(useGreeting = false): void {
    const character = activeCharacter;
    const roomArt = byId<HTMLImageElement>("room-art");
    roomArt.fetchPriority = "high";
    roomArt.src = character.roomImage;
    const portrait = byId<HTMLImageElement>("portrait-art");
    portrait.fetchPriority = "high";
    portrait.src = character.portraitImage;
    portrait.alt = character.portraitAlt;
    const portraitButton = byId<HTMLButtonElement>("portrait");
    portraitButton.hidden = character.portraitImage.length === 0;
    portraitButton.disabled = character.portraitImage.length === 0;
    portraitButton.ariaLabel = `戳一下${character.name}`;
    const mirror = byId<HTMLButtonElement>("mirror");
    mirror.disabled = importedRoom && !importedCharacterReady;
    mirror.ariaLabel = importedCharacterReady
      ? `点击镜子与${character.name}对话`
      : "导入角色资料载入中";
    roomState = idleState(useGreeting);
    renderState();
  }

  async function loadImportedRoomCharacter(): Promise<void> {
    if (!importedRoom) return;
    if (!importedApiBaseUrl) {
      roomState = {
        view: "idle",
        speaker: "系统",
        caption: "导入角色资料未接通：房间链接缺少 Living World API。",
        phase: "资料不可用",
      };
      renderState();
      return;
    }
    try {
      const registered = await loadRegisteredOc(
        window.fetch.bind(window),
        importedApiBaseUrl,
        roomResidentId,
      );
      activeCharacter = toDynamicRoomCharacter(registered, {
        roomImage: activeCharacter.roomImage,
      });
      importedCharacterReady = true;
      await warmPortraitCache([activeCharacter.roomImage]);
      renderCharacter(true);
      byId("connection").textContent = "房间在线 · 已确认角色";
    } catch {
      importedCharacterReady = false;
      roomState = {
        view: "idle",
        speaker: "系统",
        caption: "导入角色资料未接通，没有使用 OO 或 CC 身份代替。",
        phase: "资料不可用",
      };
      renderState();
    }
  }

  function ringDeviceId(): string {
    return resolveDeviceId(location.search);
  }

  function showJournalUnavailable(message: string): void {
    ownerJournalEntries = [];
    selectedJournalIndex = 0;
    byId("journal-title").textContent = "日志暂不可读取";
    const journalCopy = byId("journal-copy");
    journalCopy.textContent = message;
    journalCopy.hidden = false;
    const sections = byId("journal-sections");
    sections.replaceChildren();
    sections.hidden = true;
    byId("journal-day-label").textContent = "DAY —";
    byId("journal-position").textContent = "— / —";
    byId("journal-changes-heading").hidden = true;
    const changes = byId<HTMLUListElement>("journal-changes");
    changes.replaceChildren();
    changes.hidden = true;
    byId<HTMLButtonElement>("journal-newer").disabled = true;
    byId<HTMLButtonElement>("journal-older").disabled = true;
  }

  function journalOwnerLabel(): string {
    if (livingWorldContext?.actorId === "oc-angel") return "OO";
    if (livingWorldContext?.actorId === "oc-devil") return "CC";
    return activeCharacter.name;
  }

  function renderOwnerJournal(): void {
    const entry = ownerJournalEntries[selectedJournalIndex];
    if (!entry) return;
    byId("journal-title").textContent = entry.title;
    byId("journal-owner-heading").textContent =
      `${journalOwnerLabel()} 所经历的版本`;
    const journalCopy = byId("journal-copy");
    const sections = byId("journal-sections");
    sections.replaceChildren(
      ...entry.sections.map((section) => {
        const block = document.createElement("section");
        block.className = `journal-section journal-section-${section.kind}`;
        const heading = document.createElement("h3");
        heading.textContent = ownerJournalSectionTitle(section.kind);
        const copy = document.createElement("p");
        copy.textContent = section.text;
        block.append(heading, copy);
        return block;
      }),
    );
    if (entry.sections.length > 0) {
      journalCopy.hidden = true;
      sections.hidden = false;
    } else {
      journalCopy.textContent = entry.story;
      journalCopy.hidden = false;
      sections.hidden = true;
    }
    byId("journal-day-label").textContent = `DAY ${entry.dayIndex}`;
    byId("journal-position").textContent =
      `${selectedJournalIndex + 1} / ${ownerJournalEntries.length}`;
    const changes = byId<HTMLUListElement>("journal-changes");
    changes.replaceChildren(
      ...entry.changes.map((change) => {
        const item = document.createElement("li");
        item.textContent = change;
        return item;
      }),
    );
    const showLegacyChanges =
      entry.sections.length === 0 && entry.changes.length > 0;
    byId("journal-changes-heading").hidden = !showLegacyChanges;
    changes.hidden = !showLegacyChanges;
    byId<HTMLButtonElement>("journal-newer").disabled =
      selectedJournalIndex === 0;
    byId<HTMLButtonElement>("journal-older").disabled =
      selectedJournalIndex >= ownerJournalEntries.length - 1;
  }

  async function refreshOwnerJournal(): Promise<void> {
    if (!livingWorldContext) {
      showJournalUnavailable(
        "UNAVAILABLE：当前房间缺少真实日志上下文，没有使用本地故事代替。",
      );
      return;
    }
    try {
      const journal = await loadCurrentOwnerJournal(
        window.fetch.bind(window),
        livingWorldContext,
      );
      ownerJournalEntries = journal.entries;
      selectedJournalIndex = 0;
      renderOwnerJournal();
    } catch {
      showJournalUnavailable(
        "API ERROR：真实日志暂时无法读取，没有使用静态故事代替。",
      );
    }
  }

  async function releaseMicrophone(): Promise<void> {
    microphoneActive = false;
    client?.close();
    await microphone?.stop();
    await playback?.close();
    client = undefined;
    microphone = undefined;
    playback = undefined;
    muted = false;
    openingSent = false;
    openingInProgress = false;
    responseRequestedAt = 0;
    resetDialogueTurn();
    byId("connection").textContent = "房间在线";
  }

  function clearRingReconnect(): void {
    if (ringReconnectTimer) clearTimeout(ringReconnectTimer);
    ringReconnectTimer = undefined;
  }

  function scheduleRingReconnect(): void {
    if (!ringSessionWanted || ringReconnectTimer) return;
    const delay = ringReconnectDelayMs(ringReconnectAttempt);
    ringReconnectAttempt += 1;
    byId("connection").textContent = "语音网关短暂断开，正在自动重连";
    dispatch({
      type: "phase.set",
      phase: `正在重连（${Math.ceil(delay / 1_000)} 秒）`,
    });
    ringReconnectTimer = setTimeout(() => {
      ringReconnectTimer = undefined;
      if (ringSessionWanted) void connectRing(true);
    }, delay);
  }

  async function releaseRing(stopReconnecting = true): Promise<void> {
    if (stopReconnecting) {
      ringSessionWanted = false;
      ringReconnectAttempt = 0;
      clearRingReconnect();
    }
    const current = ringBridge;
    ringBridge = undefined;
    await current?.close();
    byId("connection").textContent = "房间在线";
  }

  async function stopSession(showDeviceSelection = true): Promise<void> {
    await releaseMicrophone();
    await releaseRing();
    if (showDeviceSelection) {
      dispatch({
        type: "session.stopped",
        speaker: activeCharacter.name,
      });
    } else {
      roomState = idleState();
      renderState();
    }
  }

  function phaseCopy(value: string): string {
    const phases: Record<string, string> = {
      idle: "等待指环",
      listening: "正在聆听",
      user_speaking: "你在说话",
      thinking: "正在思考",
      speaking: "角色说话",
    };
    return phases[value] ?? value;
  }

  function renderPreviousUserLine(): void {
    const line = byId<HTMLElement>("previous-user-line");
    line.hidden = !assistantTurnStarted || !currentUserTranscript;
    byId("previous-user-text").textContent = currentUserTranscript;
  }

  function resetDialogueTurn(): void {
    currentUserTranscript = "";
    assistantTurnStarted = false;
    renderPreviousUserLine();
  }

  function showFinalDialogue(
    dialogue: FinalDialogue,
  ): void {
    if (dialogue.role === "user") {
      currentUserTranscript = dialogue.text;
      const ownerContext = livingWorldContext;
      const candidate =
        ownerContext === null
          ? null
          : adviceConfirmation.offerTranscript(dialogue.text);
      if (candidate && ownerContext) {
        const confirmation = byId<HTMLElement>("advice-confirmation");
        confirmation.hidden = false;
        byId("advice-resident").textContent =
          ownerContext.actorId === "oc-angel"
            ? "OO"
            : ownerContext.actorId === "oc-devil"
              ? "CC"
              : activeCharacter.name;
        byId("advice-quote").textContent = candidate.adviceText;
        byId<HTMLButtonElement>("confirm-advice").disabled = false;
        byId("advice-result").textContent = "";
      }
      renderPreviousUserLine();
      if (!shouldReplaceCurrentSubtitle(dialogue, assistantTurnStarted)) {
        return;
      }
      dispatch({
        type: "caption.set",
        speaker: "你",
        caption: dialogue.text,
        phase: "你的发言",
      });
      return;
    }
    assistantTurnStarted = true;
    assistantBuffer = dialogue.text;
    renderPreviousUserLine();
    dispatch({
      type: "caption.set",
      speaker: activeCharacter.name,
      caption: assistantBuffer,
      phase: "角色回复",
    });
  }

  function requestCurrentResponse(): void {
    if (openingInProgress) {
      client?.requestOpening(activeCharacter.greeting);
    } else {
      client?.requestResponse();
    }
  }

  function armResponseWatchdog(): void {
    const watchedRequest = responseRequestedAt;
    setTimeout(() => {
      if (
        !microphoneActive
        || responseRequestedAt !== watchedRequest
        || !shouldRetryTimedOutResponse(
          watchedRequest,
          performance.now(),
          firstAudioSeen,
          silentResponseRetries,
        )
      ) {
        return;
      }
      silentResponseRetries += 1;
      responseRequestedAt = performance.now();
      assistantBuffer = "";
      dispatch({ type: "phase.set", phase: "正在重新连接回应" });
      requestCurrentResponse();
      armResponseWatchdog();
    }, 8_050);
  }

  async function connectRing(reconnecting = false): Promise<void> {
    await releaseMicrophone();
    await releaseRing(false);
    ringSessionWanted = true;
    if (!reconnecting) ringReconnectAttempt = 0;
    dispatch({ type: "device.select", device: "ring" });
    byId("connection").textContent = "连接云端设备";

    let deviceId;
    try {
      deviceId = ringDeviceId();
    } catch (error) {
      dispatch({
        type: "session.error",
        message: describeRingConnectionError(error),
      });
      return;
    }

    const bridge = new RingAudioBridge(location.origin, deviceId);
    ringBridge = bridge;
    try {
      await bridge.connect({
        onConnected: () => {
          if (ringBridge !== bridge) return;
          byId("connection").textContent = "戒指中继已连接";
          dispatch({
            type: "phase.set",
            phase: "等待指环",
          });
        },
        onReady: () => {
          if (ringBridge !== bridge) return;
          ringReconnectAttempt = 0;
          clearRingReconnect();
          dispatch({ type: "session.connected" });
          dispatch({
            type: "phase.set",
            phase: "正在聆听",
          });
        },
        onBusy: () => {
          if (ringBridge !== bridge) return;
          ringSessionWanted = false;
          clearRingReconnect();
          ringBridge = undefined;
          void bridge.close();
          dispatch({ type: "session.busy" });
        },
        onOffline: () => {
          if (ringBridge !== bridge) return;
          ringBridge = undefined;
          void bridge.close();
          setInnerOsStatus("unavailable");
          scheduleRingReconnect();
        },
        onClosed: () => {
          if (ringBridge !== bridge) return;
          ringBridge = undefined;
          scheduleRingReconnect();
        },
        onError: (message) => {
          if (ringBridge !== bridge) return;
          byId("connection").textContent = message;
          ringBridge = undefined;
          void bridge.close();
          scheduleRingReconnect();
        },
        onState: (phase) => {
          if (ringBridge !== bridge) return;
          if (phase === "user_speaking") resetDialogueTurn();
          if (roomState.view === "ring-connecting") {
            dispatch({ type: "session.connected" });
          }
          dispatch({
            type: "phase.set",
            phase: phaseCopy(phase),
          });
        },
        onTranscript: (role, text) => {
          if (ringBridge !== bridge) return;
          if (roomState.view === "ring-connecting") {
            dispatch({ type: "session.connected" });
          }
          showFinalDialogue({ role, text });
        },
         onInnerOsStatus: (status) => {
          if (ringBridge !== bridge) return;
           setInnerOsStatus(status);
         },
         onInnerOsDelivered: (delivery) => {
           if (ringBridge !== bridge) return;
           void recordDeliveredInnerOs(delivery);
         },
      });
      deliverPendingDecisionContext();
    } catch (error) {
      if (ringBridge !== bridge) return;
      ringBridge = undefined;
      byId("connection").textContent = describeRingConnectionError(error);
      scheduleRingReconnect();
    }
  }

  async function handleRealtimeEvent(event: RealtimeEvent): Promise<void> {
    if (
      event.type === "inner_os.delivered"
      && (event.character === "angel" || event.character === "devil")
      && typeof event.publicReply === "string"
      && typeof event.privateInnerOs === "string"
    ) {
      await recordDeliveredInnerOs({
        character: event.character,
        publicReply: event.publicReply,
        privateInnerOs: event.privateInnerOs,
      });
      return;
    }
    if (
      event.type === "inner_os.status"
      && (
        event.status === "unavailable"
        || event.status === "ready"
        || event.status === "sent"
        || event.status === "delivered"
        || event.status === "error"
      )
    ) {
      setInnerOsStatus(event.status);
      return;
    }
    if (event.type === "session.updated") {
      byId("connection").textContent = "语音已连接";
      dispatch({ type: "session.connected" });
      if (!openingSent) {
        const startup = voiceStartupAfterReady();
        openingSent = true;
        openingInProgress = false;
        muted = startup.muted;
        firstAudioSeen = false;
        silentResponseRetries = 0;
        assistantBuffer = "";
        responseRequestedAt = 0;
        dispatch({ type: "phase.set", phase: startup.phase });
      }
      return;
    }

    if (event.type === "input_audio_buffer.speech_started") {
      resetDialogueTurn();
      if (roomState.phase === "角色说话") {
        playback?.clear();
        client?.cancelResponse();
        interruptions += 1;
      }
      dispatch({
        type: "phase.set",
        phase: "正在聆听",
      });
      return;
    }

    if (event.type === "input_audio_buffer.speech_stopped") {
      responseRequestedAt = performance.now();
      firstAudioSeen = false;
      silentResponseRetries = 0;
      assistantBuffer = "";
      dispatch({
        type: "phase.set",
        phase: "正在思考",
      });
      armResponseWatchdog();
      return;
    }

    const finalDialogue = finalDialogueForEvent(event);
    if (finalDialogue) {
      showFinalDialogue(finalDialogue);
      return;
    }

    if (event.type === "response.audio_transcript.delta") {
      assistantTurnStarted = true;
      assistantBuffer += String(event.delta ?? "");
      renderPreviousUserLine();
      dispatch({
        type: "caption.set",
        speaker: activeCharacter.name,
        caption: assistantBuffer,
        phase: "角色回复",
      });
      return;
    }

    if (event.type === "response.audio.delta") {
      firstAudioSeen = true;
      assistantTurnStarted = true;
      responseRequestedAt = 0;
      renderPreviousUserLine();
      dispatch({
        type: "caption.set",
        speaker: activeCharacter.name,
        caption: assistantBuffer || "…",
        phase: "角色说话",
      });
      await playback?.enqueue(String(event.delta ?? ""));
      return;
    }

    if (
      event.type === "response.done" &&
      shouldRetrySilentResponse(firstAudioSeen, silentResponseRetries)
    ) {
      silentResponseRetries += 1;
      responseRequestedAt = performance.now();
      assistantBuffer = "";
      dispatch({
        type: "phase.set",
        phase: "正在思考",
      });
      requestCurrentResponse();
      armResponseWatchdog();
      return;
    }

    if (event.type === "response.done" && !firstAudioSeen) {
      responseRequestedAt = 0;
      openingInProgress = false;
      muted = false;
      dispatch({
        type: "session.error",
        message: "模型这次没有返回语音，请重新连接。",
      });
      return;
    }

    if (event.type === "response.done") {
      responseRequestedAt = 0;
      const finalCaption =
        assistantBuffer || activeCharacter.greeting;
      dispatch({
        type: "caption.set",
        speaker: activeCharacter.name,
        caption: finalCaption,
        phase: "角色说话",
      });
      await playback?.whenIdle();
      if (openingInProgress) {
        openingInProgress = false;
        muted = false;
      }
      if (
        roomState.speaker === activeCharacter.name
        && roomState.caption === finalCaption
      ) {
        dispatch({ type: "phase.set", phase: "正在聆听" });
      }
      return;
    }

    if (event.type === "error") {
      responseRequestedAt = 0;
      const detail = event.error as { message?: string } | undefined;
      dispatch({
        type: "session.error",
        message: detail?.message ?? "语音服务出现错误",
      });
    }
  }

  async function startMicrophone(): Promise<void> {
    await releaseRing();
    roomState = {
      ...roomState,
      device: "microphone",
      view: "microphone-ready",
    };
    dispatch({ type: "session.start" });

    try {
      microphoneActive = true;
      muted = true;
      openingSent = false;
      openingInProgress = false;
      resetDialogueTurn();
      firstAudioSeen = false;
      silentResponseRetries = 0;
      assistantBuffer = "";
      byId("connection").textContent = "请求麦克风";
      client = new RealtimeClient();
      playback = new PcmPlayback();
      microphone = new MicrophoneCapture();

      await microphone.start((frame) => {
        if (!muted) client?.sendAudio(frame);
      });
      byId("connection").textContent = "连接 StepFun";
      await client.connect(
        selected,
        (event) => {
          void handleRealtimeEvent(event);
        },
        () => {
          if (!microphoneActive) return;
          dispatch({
            type: "session.error",
            message: "实时语音连接已断开，请重新连接。",
          });
        },
        ringDeviceId(),
        "dynamicVoiceProfile" in activeCharacter
          ? activeCharacter.dynamicVoiceProfile
          : undefined,
      );
      deliverPendingDecisionContext();
    } catch (error) {
      const message = describeStartError(error);
      await releaseMicrophone();
      dispatch({ type: "session.error", message });
    }
  }

  async function handleAction(action: string): Promise<void> {
    if (action === "journal-newer") {
      selectedJournalIndex = Math.max(0, selectedJournalIndex - 1);
      renderOwnerJournal();
      return;
    }
    if (action === "journal-older") {
      selectedJournalIndex = Math.min(
        ownerJournalEntries.length - 1,
        selectedJournalIndex + 1,
      );
      renderOwnerJournal();
      return;
    }
    if (action === "choose-ring") {
      await connectRing();
      return;
    }
    if (action === "choose-microphone") {
      dispatch({ type: "device.select", device: "microphone" });
      return;
    }
    if (action === "start-microphone") {
      await startMicrophone();
      return;
    }
    if (action === "end-session" || action === "back-devices") {
      await stopSession(true);
      return;
    }
    if (action === "retry-session") {
      if (roomState.device === "ring") await connectRing();
      else await startMicrophone();
      return;
    }
    if (action === "back-room" || action === "close-journal") {
      await stopSession(false);
    }
  }

  byId<HTMLButtonElement>("confirm-advice").addEventListener("click", async () => {
    if (!livingWorldContext) return;
    const button = byId<HTMLButtonElement>("confirm-advice");
    const confirmedUserText = byId("advice-quote").textContent?.trim() ?? "";
    button.disabled = true;
    byId("advice-result").textContent =
      `${livingWorldContext.actorId === "oc-angel"
        ? "OO"
        : livingWorldContext.actorId === "oc-devil"
          ? "CC"
          : activeCharacter.name} 正在按自己的经历判断这条建议。`;
    try {
      const counsel = await adviceConfirmation.confirm((candidate) =>
        counselCurrentOwner(
          window.fetch.bind(window),
          livingWorldContext,
          candidate,
        ),
      );
      if (!counsel) return;
      conversationMemoryRecorder?.arm(counsel.counselId, confirmedUserText);
      const dispositionLabel = {
        accepted: "接受",
        partiallyAccepted: "部分接受",
        rejected: "拒绝",
      }[counsel.disposition];
      byId("advice-result").textContent =
        `${dispositionLabel}：${counsel.publicReply} 下一轮真实心声送达后写入记忆。`;
      button.hidden = true;
      try {
        pendingDecisionContext = await loadCurrentOwnerPrivateOsContext(
          window.fetch.bind(window),
          livingWorldContext,
          counsel.privateOsRef,
        );
        deliverPendingDecisionContext();
      } catch {
        setInnerOsStatus("unavailable");
      }
    } catch {
      button.disabled = false;
      byId("advice-result").textContent =
        "建议没有写入真实世界，请检查 Living World API 后重试。";
    }
  });

  roomExitButton.addEventListener("click", async () => {
    await stopSession(false);
    if (roomReturnTarget) {
      window.location.assign(roomReturnTarget);
    } else {
      window.history.back();
    }
  });

  byId("mirror").addEventListener("click", async () => {
    if (!importedCharacterReady) return;
    await stopSession(false);
    dispatch({ type: "mirror.open" });
  });

  byId("bed").addEventListener("click", async () => {
    await stopSession(false);
    dispatch({
      type: "bed.rest",
      caption:
        importedRoom
          ? `${activeCharacter.name} 暂时休息了一会儿。`
          : selected === "devil"
          ? "恶魔不需要睡觉。这只是盖好被子进行冥想。"
          : "我只是暂时闭幕，又不是谢幕。",
    });
  });

  byId("mailbox").addEventListener("click", async () => {
    await stopSession(false);
    showJournalUnavailable("正在读取当前 OC 自己记得的部分。");
    dispatch({ type: "journal.open" });
    await refreshOwnerJournal();
  });

  byId("portrait").addEventListener("click", () => {
    const character = activeCharacter;
    dispatch({
      type: "caption.set",
      speaker: character.name,
      caption: character.poke,
      phase: "被你戳到了",
    });
    if (microphoneActive) {
      responseRequestedAt = performance.now();
      firstAudioSeen = false;
      silentResponseRetries = 0;
      client?.sendText(
        "我轻轻戳了你一下。请立刻以角色口吻做一句简短回应。",
      );
    }
  });

  byId("journal").addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(
      "[data-action]",
    );
    if (button) void handleAction(button.dataset.action ?? "");
  });

  const refreshCapacity = async (): Promise<void> => {
    try {
      const status = (await fetch("/api/status", { cache: "no-store" }).then(
        (response) => response.json(),
      )) as { active: number; capacity: number };
      byId("capacity").textContent = `${status.active} / ${status.capacity}`;
    } catch {
      byId("capacity").textContent = "LOCAL";
    }
  };

  void refreshCapacity();
  void refreshInnerOsStatus();
  setInterval(() => {
    void refreshCapacity();
    void refreshInnerOsStatus();
  }, 15_000);
  renderCharacter();
  void loadImportedRoomCharacter();
}

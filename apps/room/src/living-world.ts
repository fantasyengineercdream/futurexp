import { isImportedOcId } from "./registered-oc";

export type OwnerActorId = "oc-angel" | "oc-devil" | string;

export type OwnerLivingWorldContext = {
  apiBaseUrl: string;
  runId: string;
  actorId: OwnerActorId;
  episodeRef: string;
  dayIndex: number;
};

export type OwnerAdviceCandidate = {
  adviceText: string;
  recommendationKind: "verifyEvidence";
};

export type CounselReceipt = {
  counselId: string;
  disposition: "accepted" | "partiallyAccepted" | "rejected";
  publicReply: string;
  privateOsRef: string;
};

export type OwnerConversationMemoryInput = {
  counselId: string;
  userText: string;
  publicReply: string;
  privateInnerOs: string;
};

export type OwnerConversationMemoryReceipt = {
  conversationId: string;
  recorded: true;
};

export type DeliveredInnerOs = {
  character: "angel" | "devil";
  publicReply: string;
  privateInnerOs: string;
};

export class OwnerConversationMemoryRecorder {
  private pending?: { counselId: string; userText: string };
  private recording = false;

  constructor(private readonly context: OwnerLivingWorldContext) {}

  get awaitingDelivery(): boolean {
    return this.pending !== undefined;
  }

  arm(counselId: string, userText: string): void {
    if (!nonEmpty(counselId) || !nonEmpty(userText)) {
      throw new Error("Owner conversation memory is incomplete");
    }
    this.pending = { counselId, userText };
  }

  async recordDelivery(
    delivery: DeliveredInnerOs,
    submit: (
      input: OwnerConversationMemoryInput,
    ) => Promise<OwnerConversationMemoryReceipt>,
  ): Promise<"ignored" | "recorded"> {
    const expectedCharacter = this.context.actorId === "oc-angel"
      ? "angel"
      : this.context.actorId === "oc-devil"
        ? "devil"
        : null;
    if (delivery.character !== expectedCharacter) {
      throw new Error("Owner conversation memory actor mismatch");
    }
    if (!this.pending || this.recording) return "ignored";
    const input = {
      ...this.pending,
      publicReply: delivery.publicReply,
      privateInnerOs: delivery.privateInnerOs,
    };
    this.recording = true;
    try {
      await submit(input);
      this.pending = undefined;
      return "recorded";
    } finally {
      this.recording = false;
    }
  }
}

export type OwnerDecisionContext = {
  disposition: CounselReceipt["disposition"];
  reason?: string;
  relevantMemorySummaries?: string[];
  episodeRef: string;
};

export type OwnerJournalEntry = {
  episodeRef: string;
  dayIndex: number;
  title: string;
  story: string;
  changes: string[];
  sections: OwnerJournalSection[];
};

export type OwnerJournalSectionKind =
  | "scene"
  | "intent"
  | "check"
  | "observation"
  | "consequence"
  | "reflection"
  | "ownerConversation";

export type OwnerJournalSection = {
  kind: OwnerJournalSectionKind;
  text: string;
};

export type OwnerJournal = {
  updatedDayIndex: number;
  entries: OwnerJournalEntry[];
};

export type NextDayActivity = {
  dayIndex: number;
  activityLabel: string;
};

export type PublicDayLoopProjection = Record<string, unknown> & {
  runId: string;
  dayIndex: number;
  actors: unknown[];
};

type Fetcher = typeof fetch;

const dispositions = new Set([
  "accepted",
  "partiallyAccepted",
  "rejected",
]);

const ownerJournalSectionKinds = new Set<OwnerJournalSectionKind>([
  "scene",
  "intent",
  "check",
  "observation",
  "consequence",
  "reflection",
  "ownerConversation",
]);

const ownerJournalSectionTitles: Record<OwnerJournalSectionKind, string> = {
  scene: "发生在哪里",
  intent: "我的行动",
  check: "规则判定",
  observation: "我所看见",
  consequence: "留下的变化",
  reflection: "我怎么记住",
  ownerConversation: "昨夜与主人",
};

export function ownerJournalSectionTitle(
  kind: OwnerJournalSectionKind,
): string {
  return ownerJournalSectionTitles[kind];
}

function nonEmpty(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

const internalToken =
  /\b(?:suspected|accepted)\b|\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b/i;

function hasInternalToken(value: string): boolean {
  return internalToken.test(value);
}

function assertProductCopy(value: string, label: string): string {
  if (hasInternalToken(value)) {
    throw new Error(`${label} contains internal tokens`);
  }
  return value;
}

function apiUrl(
  context: OwnerLivingWorldContext,
  action:
    | "counsel"
    | "conversation-memory"
    | "journal"
    | "private-os-context"
    | "advance",
): string {
  const runId = encodeURIComponent(context.runId);
  if (action === "advance") {
    return new URL(
      `/api/living-world/day-loop-runs/${runId}/advance`,
      context.apiBaseUrl,
    ).toString();
  }
  return new URL(
    `/api/living-world/day-loop-runs/${runId}/owner/actors/${encodeURIComponent(context.actorId)}/${action}`,
    context.apiBaseUrl,
  ).toString();
}

async function readJson(response: Response, label: string): Promise<unknown> {
  if (!response.ok) {
    throw new Error(`${label} failed (${response.status})`);
  }
  return response.json();
}

export function resolveOwnerLivingWorldContext(
  search: string,
): OwnerLivingWorldContext | null {
  const params = new URLSearchParams(search);
  const runId = params.get("runId");
  const residentId = params.get("residentId");
  const episodeRef = params.get("episodeRef");
  const dayIndex = Number(params.get("dayIndex"));
  const apiBase = params.get("livingWorldApi");
  const actorId =
    residentId === "oc-angel" || residentId === "oc-devil"
      ? residentId
      : isImportedOcId(residentId)
        ? residentId
        : null;
  if (
    actorId === null ||
    !nonEmpty(runId) ||
    !nonEmpty(episodeRef) ||
    !Number.isInteger(dayIndex) ||
    dayIndex < 1 ||
    episodeRef !== `memory:day-${dayIndex}:${actorId}` ||
    !nonEmpty(apiBase)
  ) {
    return null;
  }
  try {
    const apiBaseUrl = new URL(apiBase);
    if (apiBaseUrl.protocol !== "http:" && apiBaseUrl.protocol !== "https:") {
      return null;
    }
    return {
      apiBaseUrl: apiBaseUrl.toString(),
      runId,
      actorId,
      episodeRef,
      dayIndex,
    };
  } catch {
    return null;
  }
}

export function adviceCandidateFromTranscript(
  transcript: string,
): OwnerAdviceCandidate | null {
  const adviceText = transcript.trim();
  if (!adviceText || adviceText.length > 240) return null;
  const evidenceFirst =
    /(?:核对|确认|查清|弄清).{0,16}(?:证据|事实|看见|看到|观察)/;
  const evidenceLast =
    /(?:证据|事实|看见|看到|观察).{0,16}(?:核对|确认|查清|判断)/;
  if (!evidenceFirst.test(adviceText) && !evidenceLast.test(adviceText)) {
    return null;
  }
  return {
    adviceText,
    recommendationKind: "verifyEvidence",
  };
}

export class OwnerAdviceConfirmation {
  private candidate: OwnerAdviceCandidate | null = null;
  private submitting = false;
  private submitted = false;

  offerTranscript(transcript: string): OwnerAdviceCandidate | null {
    if (this.submitted || this.submitting) return null;
    this.candidate = adviceCandidateFromTranscript(transcript);
    return this.candidate;
  }

  async confirm<T>(
    submit: (candidate: OwnerAdviceCandidate) => Promise<T>,
  ): Promise<T | null> {
    if (!this.candidate || this.submitting || this.submitted) return null;
    const candidate = this.candidate;
    this.submitting = true;
    try {
      const result = await submit(candidate);
      this.submitted = true;
      this.candidate = null;
      return result;
    } finally {
      this.submitting = false;
    }
  }
}

function adviceIdFor(
  context: OwnerLivingWorldContext,
  candidate: OwnerAdviceCandidate,
): string {
  if (candidate.recommendationKind === "verifyEvidence") {
    return `conversation-day-${context.dayIndex}-verify-evidence`;
  }
  throw new Error("Unsupported owner advice kind");
}

export async function counselCurrentOwner(
  fetcher: Fetcher,
  context: OwnerLivingWorldContext,
  candidate: OwnerAdviceCandidate,
): Promise<CounselReceipt> {
  const adviceId = adviceIdFor(context, candidate);
  const response = await fetcher(apiUrl(context, "counsel"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      episodeRef: context.episodeRef,
      adviceId,
      adviceText: candidate.adviceText,
      recommendationKind: candidate.recommendationKind,
    }),
  });
  const raw = (await readJson(response, "Owner counsel")) as Record<
    string,
    unknown
  >;
  if (
    !nonEmpty(raw.counselId) ||
    raw.actorId !== context.actorId ||
    raw.episodeRef !== context.episodeRef ||
    raw.adviceId !== adviceId ||
    !dispositions.has(String(raw.disposition)) ||
    !nonEmpty(raw.publicReply) ||
    raw.privateOsAvailable !== true ||
    !nonEmpty(raw.privateOsRef)
  ) {
    throw new Error("Owner counsel identity mismatch");
  }
  return {
    counselId: raw.counselId as string,
    disposition: raw.disposition as CounselReceipt["disposition"],
    publicReply: raw.publicReply,
    privateOsRef: raw.privateOsRef,
  };
}

export async function recordOwnerConversationMemory(
  fetcher: Fetcher,
  context: OwnerLivingWorldContext,
  input: OwnerConversationMemoryInput,
): Promise<OwnerConversationMemoryReceipt> {
  if (
    !nonEmpty(input.counselId)
    || !nonEmpty(input.userText)
    || !nonEmpty(input.publicReply)
    || !nonEmpty(input.privateInnerOs)
  ) {
    throw new Error("Owner conversation memory is incomplete");
  }
  const response = await fetcher(apiUrl(context, "conversation-memory"), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      episodeRef: context.episodeRef,
      counselId: input.counselId,
      userText: input.userText,
      publicReply: input.publicReply,
      privateInnerOs: input.privateInnerOs,
    }),
  });
  const raw = (await readJson(
    response,
    "Owner conversation memory",
  )) as Record<string, unknown>;
  if (
    !nonEmpty(raw.conversationId)
    || raw.actorId !== context.actorId
    || raw.episodeRef !== context.episodeRef
    || raw.counselId !== input.counselId
    || raw.recorded !== true
  ) {
    throw new Error("Owner conversation memory identity mismatch");
  }
  return {
    conversationId: raw.conversationId,
    recorded: true,
  };
}

export async function loadCurrentOwnerPrivateOsContext(
  fetcher: Fetcher,
  context: OwnerLivingWorldContext,
  privateOsRef: string,
): Promise<OwnerDecisionContext> {
  const url = new URL(apiUrl(context, "private-os-context"));
  url.searchParams.set("ref", privateOsRef);
  const response = await fetcher(url.toString(), { method: "GET" });
  const raw = (await readJson(
    response,
    "Owner private OS context",
  )) as Record<string, unknown>;
  if (
    raw.actorId !== context.actorId ||
    raw.episodeRef !== context.episodeRef ||
    !dispositions.has(String(raw.disposition)) ||
    !nonEmpty(raw.decisionReason) ||
    !Array.isArray(raw.relevantMemorySummaries) ||
    raw.relevantMemorySummaries.some((item) => typeof item !== "string")
  ) {
    throw new Error("Owner private OS context identity mismatch");
  }
  return {
    disposition: raw.disposition as CounselReceipt["disposition"],
    reason: raw.decisionReason,
    relevantMemorySummaries: raw.relevantMemorySummaries as string[],
    episodeRef: context.episodeRef,
  };
}

export async function loadCurrentOwnerJournal(
  fetcher: Fetcher,
  context: OwnerLivingWorldContext,
): Promise<OwnerJournal> {
  const response = await fetcher(apiUrl(context, "journal"), {
    method: "GET",
  });
  const raw = (await readJson(response, "Owner journal")) as Record<
    string,
    unknown
  >;
  if (
    !nonEmpty(raw.schemaVersion) ||
    raw.actorId !== context.actorId ||
    raw.runId !== context.runId ||
    !Number.isInteger(raw.updatedDayIndex) ||
    Number(raw.updatedDayIndex) < 1 ||
    !Array.isArray(raw.entries)
  ) {
    throw new Error("Owner journal identity mismatch");
  }
  const updatedDayIndex = raw.updatedDayIndex as number;
  const seenDays = new Set<number>();
  const entries = raw.entries.map((value) => {
    const entry = value as Record<string, unknown>;
    const dayIndex = entry.dayIndex;
    const rawSections = entry.sections ?? [];
    if (
      !Number.isInteger(dayIndex) ||
      Number(dayIndex) < 1 ||
      Number(dayIndex) > updatedDayIndex ||
      entry.episodeRef !== `memory:day-${dayIndex}:${context.actorId}` ||
      !nonEmpty(entry.title) ||
      !nonEmpty(entry.story) ||
      !Array.isArray(entry.changes) ||
      entry.changes.some((change) => typeof change !== "string") ||
      !Array.isArray(rawSections) ||
      seenDays.has(Number(dayIndex))
    ) {
      throw new Error("Owner journal identity mismatch");
    }
    const sections = rawSections.map((value) => {
      const section = value as Record<string, unknown>;
      if (
        !ownerJournalSectionKinds.has(
          section.kind as OwnerJournalSectionKind,
        ) ||
        !nonEmpty(section.text) ||
        hasInternalToken(section.text)
      ) {
        throw new Error("Owner journal identity mismatch");
      }
      return {
        kind: section.kind as OwnerJournalSectionKind,
        text: assertProductCopy(section.text, "Owner journal section"),
      };
    });
    seenDays.add(Number(dayIndex));
    return {
      episodeRef: entry.episodeRef as string,
      dayIndex: Number(dayIndex),
      title: assertProductCopy(entry.title, "Owner journal title"),
      story: assertProductCopy(entry.story, "Owner journal story"),
      changes: (entry.changes as string[]).filter(
        (change) => !hasInternalToken(change),
      ),
      sections,
    };
  });
  if (entries.length === 0) {
    throw new Error("Owner journal is empty");
  }
  return {
    updatedDayIndex,
    entries: entries.sort((left, right) => right.dayIndex - left.dayIndex),
  };
}

async function advanceLivingWorldProjection(
  fetcher: Fetcher,
  context: OwnerLivingWorldContext,
): Promise<{
  nextDay: NextDayActivity;
  projection: PublicDayLoopProjection;
}> {
  const response = await fetcher(apiUrl(context, "advance"), {
    method: "POST",
  });
  const raw = (await readJson(response, "Living World advance")) as Record<
    string,
    unknown
  >;
  if (
    raw.runId !== context.runId ||
    !Number.isInteger(raw.dayIndex) ||
    raw.dayIndex !== context.dayIndex + 1 ||
    !Array.isArray(raw.actors)
  ) {
    throw new Error("Living World advance identity mismatch");
  }
  const owner = raw.actors.find(
    (actor) =>
      typeof actor === "object" &&
      actor !== null &&
      (actor as Record<string, unknown>).actorId === context.actorId,
  ) as Record<string, unknown> | undefined;
  if (!owner || !nonEmpty(owner.activityLabel)) {
    throw new Error("Owner next-day activity is missing");
  }
  return {
    nextDay: {
      dayIndex: raw.dayIndex as number,
      activityLabel: assertProductCopy(
        owner.activityLabel,
        "Owner next-day activity",
      ),
    },
    projection: raw as PublicDayLoopProjection,
  };
}

export async function advanceLivingWorldDay(
  fetcher: Fetcher,
  context: OwnerLivingWorldContext,
): Promise<NextDayActivity> {
  return (await advanceLivingWorldProjection(fetcher, context)).nextDay;
}

export function returnUrlWithDayLoopResume(
  returnTo: string,
  projection: PublicDayLoopProjection,
): string {
  const url = new URL(returnTo);
  url.searchParams.set("dayLoopResume", JSON.stringify(projection));
  return url.toString();
}

export type DynamicVoiceProfile = {
  id: string;
  name: string;
  role: string;
  persona: string;
  publicStyle: string;
  goals: string[];
};

export type DynamicRoomCharacter = {
  id: string;
  name: string;
  serial: string;
  summary: string;
  voice: string;
  roomImage: string;
  portraitImage: "";
  portraitAlt: string;
  greeting: string;
  poke: string;
  instructions: string;
  dynamicVoiceProfile: DynamicVoiceProfile;
};

export type RegisteredOc = {
  schemaVersion: "0.1";
  ocId: string;
  status: "registered";
  character: {
    ocId: string;
    name: string;
    role: string;
    persona: string;
    publicStyle: string;
    goals: Array<{ goalId: string; text: string }>;
  };
  runtimeProfile: {
    ocId: string;
  } & Record<string, unknown>;
} & Record<string, unknown>;

export function isImportedOcId(value: unknown): value is string {
  return (
    typeof value === "string"
    && /^oc-imported-[a-z0-9-]{1,80}$/.test(value)
  );
}

function nonEmpty(value: unknown, maxLength = 2_000): value is string {
  return (
    typeof value === "string"
    && value.trim().length > 0
    && value.length <= maxLength
  );
}

function assertRegisteredOc(
  value: unknown,
  expectedOcId: string,
): RegisteredOc {
  if (!value || typeof value !== "object") {
    throw new Error("Invalid registered OC");
  }
  const raw = value as Record<string, unknown>;
  const character = raw.character as Record<string, unknown> | undefined;
  const runtimeProfile = raw.runtimeProfile as
    | Record<string, unknown>
    | undefined;
  const goals = character?.goals;
  if (
    raw.schemaVersion !== "0.1"
    || raw.status !== "registered"
    || raw.ocId !== expectedOcId
    || character?.ocId !== expectedOcId
    || runtimeProfile?.ocId !== expectedOcId
    || !nonEmpty(character.name, 120)
    || !nonEmpty(character.role, 240)
    || !nonEmpty(character.persona)
    || !nonEmpty(character.publicStyle, 1_000)
    || !Array.isArray(goals)
    || goals.length === 0
    || goals.length > 8
    || goals.some(
      (goal) =>
        !goal
        || typeof goal !== "object"
        || !nonEmpty((goal as Record<string, unknown>).goalId, 160)
        || !nonEmpty((goal as Record<string, unknown>).text, 500),
    )
  ) {
    if (raw.ocId !== expectedOcId) {
      throw new Error("Registered OC identity mismatch");
    }
    throw new Error("Invalid registered OC");
  }
  return value as RegisteredOc;
}

export async function loadRegisteredOc(
  fetcher: typeof fetch,
  apiBaseUrl: string,
  ocId: string,
): Promise<RegisteredOc> {
  if (!isImportedOcId(ocId)) throw new Error("Invalid imported OC id");
  const base = new URL(apiBaseUrl);
  if (base.protocol !== "http:" && base.protocol !== "https:") {
    throw new Error("Invalid Living World API");
  }
  const response = await fetcher(
    new URL(`/api/ocs/${encodeURIComponent(ocId)}`, base).toString(),
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(`Registered OC unavailable (${response.status})`);
  }
  return assertRegisteredOc(await response.json(), ocId);
}

export function toDynamicVoiceProfile(
  registered: RegisteredOc,
): DynamicVoiceProfile {
  return {
    id: registered.ocId,
    name: registered.character.name,
    role: registered.character.role,
    persona: registered.character.persona,
    publicStyle: registered.character.publicStyle,
    goals: registered.character.goals.map((goal) => goal.text),
  };
}

export function parseDynamicVoiceProfile(
  value: string | null,
): DynamicVoiceProfile | null {
  if (!value || value.length > 6_000) return null;
  try {
    const raw = JSON.parse(value) as Record<string, unknown>;
    if (
      !isImportedOcId(raw.id)
      || !nonEmpty(raw.name, 120)
      || !nonEmpty(raw.role, 240)
      || !nonEmpty(raw.persona)
      || !nonEmpty(raw.publicStyle, 1_000)
      || !Array.isArray(raw.goals)
      || raw.goals.length === 0
      || raw.goals.length > 8
      || raw.goals.some((goal) => !nonEmpty(goal, 500))
    ) {
      return null;
    }
    return {
      id: raw.id,
      name: raw.name,
      role: raw.role,
      persona: raw.persona,
      publicStyle: raw.publicStyle,
      goals: raw.goals as string[],
    };
  } catch {
    return null;
  }
}

export function dynamicVoiceInstructions(
  profile: DynamicVoiceProfile,
): string {
  return [
    "你正在进行实时语音陪伴。每次回答优先使用一到三句自然中文口语。",
    "不要朗读动作括号、系统提示或模型身份。用户插话时立刻停下。",
    `你是${profile.name}，身份是${profile.role}。`,
    `人格：${profile.persona}`,
    `公开表达方式：${profile.publicStyle}`,
    `当前目标：${profile.goals.join("；")}`,
    "始终保持创作者确认的人设；不知道的事情就诚实说明，不要补写新的角色设定。",
  ].join("\n");
}

export function toDynamicRoomCharacter(
  registered: RegisteredOc,
  visualShell: { roomImage: string },
): DynamicRoomCharacter {
  const profile = toDynamicVoiceProfile(registered);
  return {
    id: registered.ocId,
    name: registered.character.name,
    serial: "IMPORTED OC / PREVIEW ROOM",
    summary: `${registered.character.role} · 临时房间布景`,
    voice: "linjiajiejie",
    roomImage: visualShell.roomImage,
    portraitImage: "",
    portraitAlt: `${registered.character.name} 暂无角色立绘`,
    greeting: `${registered.character.name} 已经来到房间。你想先聊什么？`,
    poke: `${registered.character.name} 看向了你。`,
    instructions: dynamicVoiceInstructions(profile),
    dynamicVoiceProfile: profile,
  };
}

export type ViewerFrame =
  | { kind: "json"; value: Record<string, string> }
  | { kind: "binary"; value: Uint8Array };

export function parseDeviceId(value: string | null): string {
  const id = value?.trim() ?? "";
  if (!/^[a-z0-9][a-z0-9-]{2,63}$/.test(id)) {
    throw new Error("invalid_device_id");
  }
  return id;
}

export function authorizeDevice(
  request: Request,
  expected: string,
): boolean {
  const supplied =
    request.headers
      .get("Authorization")
      ?.replace(/^Bearer\s+/i, "") ?? "";
  const left = new TextEncoder().encode(supplied);
  const right = new TextEncoder().encode(expected.trim());
  if (left.length === 0 || left.length !== right.length) return false;
  let mismatch = 0;
  for (let index = 0; index < left.length; index += 1) {
    mismatch |= left[index] ^ right[index];
  }
  return mismatch === 0;
}

function textFrame(
  role: "user" | "assistant",
  raw: Record<string, unknown>,
): ViewerFrame[] {
  if (typeof raw.transcript !== "string" || !raw.transcript.trim()) {
    return [];
  }
  return [
    {
      kind: "json",
      value: {
        type: "transcript",
        role,
        text: raw.transcript,
      },
    },
  ];
}

function decodeAudio(value: unknown): Uint8Array {
  if (
    typeof value !== "string" ||
    !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(
      value,
    )
  ) {
    throw new Error("invalid_audio_delta");
  }
  try {
    return Uint8Array.from(atob(value), (character) =>
      character.charCodeAt(0),
    );
  } catch {
    throw new Error("invalid_audio_delta");
  }
}

export function viewerFramesForStepEvent(
  raw: Record<string, unknown>,
): ViewerFrame[] {
  switch (raw.type) {
    case "input_audio_buffer.speech_started":
      return [
        {
          kind: "json",
          value: { type: "state", phase: "user_speaking" },
        },
        { kind: "json", value: { type: "playback.clear" } },
      ];
    case "input_audio_buffer.speech_stopped":
    case "response.created":
      return [
        {
          kind: "json",
          value: { type: "state", phase: "thinking" },
        },
      ];
    case "response.audio.delta":
      return [
        {
          kind: "json",
          value: { type: "state", phase: "speaking" },
        },
        { kind: "binary", value: decodeAudio(raw.delta) },
      ];
    case "conversation.item.input_audio_transcription.completed":
      return textFrame("user", raw);
    case "response.audio_transcript.done":
      return textFrame("assistant", raw);
    case "response.done":
      return [
        {
          kind: "json",
          value: { type: "state", phase: "idle" },
        },
      ];
    default:
      return [];
  }
}

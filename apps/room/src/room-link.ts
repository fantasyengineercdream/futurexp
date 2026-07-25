import type { CharacterId } from "./characters";
import { isImportedOcId } from "./registered-oc";

type RoomTarget = {
  character: CharacterId;
  residentId: string;
  roomId: string;
};

const TARGETS: Record<CharacterId, RoomTarget> = {
  devil: {
    character: "devil",
    residentId: "oc-devil",
    roomId: "room-cc",
  },
  angel: {
    character: "angel",
    residentId: "oc-angel",
    roomId: "room-oo",
  },
};

export function resolveRoomCharacter(search: string): CharacterId {
  const params = new URLSearchParams(search);
  const residentId = params.get("residentId");
  const roomId = params.get("roomId");
  const character = params.get("character");

  return (
    Object.values(TARGETS).find(
      (target) => target.residentId === residentId,
    )?.character ??
    Object.values(TARGETS).find((target) => target.roomId === roomId)
      ?.character ??
    (character === "angel" || character === "devil" ? character : "devil")
  );
}

export function resolveRoomResidentId(search: string): string {
  const params = new URLSearchParams(search);
  const residentId = params.get("residentId");
  const roomId = params.get("roomId");
  if (isImportedOcId(residentId) && roomId === "room-demo-user") {
    return residentId;
  }
  return TARGETS[resolveRoomCharacter(search)].residentId;
}

export function roomSearchForCharacter(
  character: CharacterId,
  currentSearch: string,
): string {
  const params = new URLSearchParams(currentSearch);
  const target = TARGETS[character];
  params.delete("character");
  params.set("roomId", target.roomId);
  params.set("residentId", target.residentId);
  return `?${params.toString()}`;
}

export function resolveRoomReturnTarget(search: string): string | null {
  const rawTarget = new URLSearchParams(search).get("returnTo");
  if (!rawTarget) return null;

  try {
    const target = new URL(rawTarget);
    if (target.protocol !== "http:" && target.protocol !== "https:") {
      return null;
    }
    return target.toString();
  } catch {
    return null;
  }
}

export function roomEntryIsLocked(search: string): boolean {
  const params = new URLSearchParams(search);
  const residentId = params.get("residentId");
  const roomId = params.get("roomId");
  const hasStableRoomTarget = Object.values(TARGETS).some(
    (target) =>
      target.residentId === residentId || target.roomId === roomId,
  );
  const hasImportedRoomTarget =
    isImportedOcId(residentId) && roomId === "room-demo-user";

  return (
    hasStableRoomTarget
    || hasImportedRoomTarget
    || resolveRoomReturnTarget(search) !== null
  );
}

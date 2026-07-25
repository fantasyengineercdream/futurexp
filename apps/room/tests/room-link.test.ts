import { describe, expect, test } from "vitest";
import {
  resolveRoomReturnTarget,
  roomEntryIsLocked,
  roomSearchForCharacter,
  resolveRoomCharacter,
  resolveRoomResidentId,
} from "../src/room-link";

describe("KaleidoRoom room deep links", () => {
  test("maps the stable OO room contract to the angel", () => {
    expect(
      resolveRoomCharacter("?residentId=oc-angel&roomId=room-oo"),
    ).toBe("angel");
  });

  test("maps the stable CC room contract to the devil", () => {
    expect(
      resolveRoomCharacter("?residentId=oc-devil&roomId=room-cc"),
    ).toBe("devil");
  });

  test("accepts one stable id or the legacy character alias", () => {
    expect(resolveRoomCharacter("?residentId=oc-angel")).toBe("angel");
    expect(resolveRoomCharacter("?roomId=room-cc")).toBe("devil");
    expect(resolveRoomCharacter("?character=angel")).toBe("angel");
  });

  test("defaults unknown links to the existing devil room", () => {
    expect(resolveRoomCharacter("?residentId=unknown")).toBe("devil");
  });

  test("writes a shareable room contract while preserving gateway settings", () => {
    expect(
      roomSearchForCharacter(
        "angel",
        "?gateway=http%3A%2F%2Forangepi.local%3A8787&roomId=room-cc",
      ),
    ).toBe(
      "?gateway=http%3A%2F%2Forangepi.local%3A8787&roomId=room-oo&residentId=oc-angel",
    );
  });

  test("locks platform room entries to one resident and exposes a safe return target", () => {
    const search =
      "?residentId=oc-angel&roomId=room-oo&returnTo="
      + encodeURIComponent("http://127.0.0.1:5177/?previewMotion=force");

    expect(roomEntryIsLocked(search)).toBe(true);
    expect(resolveRoomReturnTarget(search)).toBe(
      "http://127.0.0.1:5177/?previewMotion=force",
    );
  });

  test("locks stable room links while keeping the standalone voice lab switchable", () => {
    expect(roomEntryIsLocked("?residentId=oc-angel&roomId=room-oo")).toBe(
      true,
    );
    expect(roomEntryIsLocked("")).toBe(false);
    expect(roomEntryIsLocked("?character=angel")).toBe(false);
  });

  test("rejects unsafe return schemes", () => {
    expect(
      resolveRoomReturnTarget(
        "?residentId=oc-angel&returnTo=javascript%3Aalert(1)",
      ),
    ).toBeNull();
  });

  test("locks an imported OC to its fixed demo room without aliasing CC", () => {
    const search =
      "?residentId=oc-imported-lan&roomId=room-demo-user"
      + "&runId=living-day-demo";

    expect(resolveRoomResidentId(search)).toBe("oc-imported-lan");
    expect(roomEntryIsLocked(search)).toBe(true);
  });
});

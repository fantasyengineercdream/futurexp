import { describe, expect, it } from "vitest";
import { CHARACTERS, getCharacter } from "../src/characters";

describe("characters", () => {
  it("keeps both layers of each persona", () => {
    expect(CHARACTERS.devil.instructions).toContain("胆小");
    expect(CHARACTERS.angel.instructions).toContain("桀骜不驯");
  });

  it("rejects unknown ids", () => {
    expect(() => getCharacter("unknown")).toThrow("Unknown character");
  });

  it("maps each character to a distinct pixel portrait with accessible text", () => {
    expect(CHARACTERS.devil.portraitImage).toBe(
      "/characters/devil-maid-pixel-v2.webp",
    );
    expect(CHARACTERS.angel.portraitImage).toBe(
      "/characters/angel-maid-pixel-v2.webp",
    );
    expect(CHARACTERS.devil.portraitImage).not.toBe(CHARACTERS.angel.portraitImage);
    expect(CHARACTERS.devil.portraitAlt).toContain("恶魔");
    expect(CHARACTERS.angel.portraitAlt).toContain("天使");
  });

  it("maps each character to its own versioned pixel room", () => {
    expect(CHARACTERS.devil.roomImage).toBe(
      "/rooms/devil-room-pixel-v1.webp",
    );
    expect(CHARACTERS.angel.roomImage).toBe(
      "/rooms/angel-room-pixel-v1.webp",
    );
    expect(CHARACTERS.devil.roomImage).not.toBe(CHARACTERS.angel.roomImage);
  });
});

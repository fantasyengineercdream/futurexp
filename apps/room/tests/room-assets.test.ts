import { stat } from "node:fs/promises";
import { describe, expect, it } from "vitest";

const rooms = [
  "../public/rooms/devil-room-pixel-v1.webp",
  "../public/rooms/angel-room-pixel-v1.webp",
];

describe("room artwork", () => {
  it.each(rooms)("ships a compressed project-owned asset: %s", async (path) => {
    const file = await stat(new URL(path, import.meta.url));
    expect(file.isFile()).toBe(true);
    expect(file.size).toBeGreaterThan(100_000);
    expect(file.size).toBeLessThan(2_000_000);
  });
});

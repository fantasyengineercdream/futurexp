import { readFile, stat } from "node:fs/promises";
import { describe, expect, it } from "vitest";

const sprites = [
  "../public/characters/devil-maid-pixel-v2.webp",
  "../public/characters/angel-maid-pixel-v2.webp",
];

describe("character artwork", () => {
  it.each(sprites)("ships a compact WebP sprite with alpha: %s", async (path) => {
    const url = new URL(path, import.meta.url);
    const [file, bytes] = await Promise.all([stat(url), readFile(url)]);
    expect(file.size).toBeGreaterThan(50_000);
    expect(file.size).toBeLessThan(250_000);
    expect(bytes.includes(Buffer.from("ALPH"))).toBe(true);
  });
});

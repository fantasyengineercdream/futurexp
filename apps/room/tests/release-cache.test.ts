import { readFile } from "node:fs/promises";
import { describe, expect, test } from "vitest";
import { appVersion } from "../src/main";

describe("production release visibility", () => {
  test("publishes a visible build identifier", () => {
    expect(appVersion).toBe("BUILD 2026.07.25.13");
  });

  test("forces the HTML shell to revalidate after a deployment", async () => {
    const headers = await readFile(new URL("../public/_headers", import.meta.url), "utf8").catch(() => "");
    expect(headers).toContain("Cache-Control: no-cache, no-store, must-revalidate");
  });

  test("caches versioned character portraits immutably", async () => {
    const headers = await readFile(new URL("../public/_headers", import.meta.url), "utf8").catch(() => "");
    expect(headers).toMatch(
      /\/characters\/\*[\s\S]*Cache-Control: public, max-age=31536000, immutable/,
    );
  });

  test("caches versioned room artwork immutably", async () => {
    const headers = await readFile(new URL("../public/_headers", import.meta.url), "utf8").catch(() => "");
    expect(headers).toMatch(
      /\/rooms\/\*[\s\S]*Cache-Control: public, max-age=31536000, immutable/,
    );
  });
});

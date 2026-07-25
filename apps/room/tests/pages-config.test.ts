import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

describe("Pages deployment config", () => {
  it("keeps the Pages config at Wrangler's required root filename", async () => {
    const config = await readFile(
      new URL("../wrangler.jsonc", import.meta.url),
      "utf8",
    );

    expect(config).toContain('"pages_build_output_dir": "./dist"');
    expect(config).toContain('"name": "DEVICE_RELAY"');
    expect(config).toContain('"script_name": "oc-device-relay"');
  });
});

import { posix, win32 } from "node:path";
import { describe, expect, it } from "vitest";
import { resolveStaticFile } from "../vps-relay/static-path";

describe("VPS static file resolution", () => {
  it("resolves nested assets on Linux and Windows", () => {
    expect(
      resolveStaticFile("/opt/oc-voice-lab/dist", "/assets/app.js", posix),
    ).toBe("/opt/oc-voice-lab/dist/assets/app.js");
    expect(
      resolveStaticFile(
        "C:\\oc-voice-lab\\dist",
        "/assets/app.js",
        win32,
      ),
    ).toBe("C:\\oc-voice-lab\\dist\\assets\\app.js");
  });

  it("rejects paths outside the deployed dist directory", () => {
    expect(
      resolveStaticFile("/opt/oc-voice-lab/dist", "/../.env", posix),
    ).toBeNull();
    expect(
      resolveStaticFile(
        "C:\\oc-voice-lab\\dist",
        "/../.env",
        win32,
      ),
    ).toBeNull();
  });
});

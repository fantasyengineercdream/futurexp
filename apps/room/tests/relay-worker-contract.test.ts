import { readFile } from "node:fs/promises";
import { describe, expect, test } from "vitest";

const relayFile = (name: string) =>
  new URL(`../relay-worker/${name}`, import.meta.url);

describe("relay worker deployment contract", () => {
  test("declares the durable relay worker and migration", async () => {
    const config = JSON.parse(
      await readFile(relayFile("wrangler.jsonc"), "utf8"),
    ) as {
      name?: string;
      main?: string;
      durable_objects?: {
        bindings?: Array<{ class_name?: string; name?: string }>;
      };
      migrations?: Array<{ new_sqlite_classes?: string[] }>;
    };

    expect(config.name).toBe("oc-device-relay");
    expect(config.main).toBe("src/index.ts");
    expect(config.durable_objects?.bindings).toContainEqual({
      name: "DEVICE_ROOMS",
      class_name: "DeviceRelayRoom",
    });
    expect(config.migrations?.[0]?.new_sqlite_classes).toContain(
      "DeviceRelayRoom",
    );
  });

  test("exposes only the device and viewer WebSocket routes", async () => {
    const source = await readFile(relayFile("src/index.ts"), "utf8");
    const innerOsSource = await readFile(
      relayFile("src/inner-os.ts"),
      "utf8",
    );

    expect(source).toContain("export class DeviceRelayRoom");
    expect(source).toContain('"/api/device/realtime"');
    expect(source).toContain('"/api/device/view"');
    expect(source).toContain("env.STEPFUN_API_KEY");
    expect(source).toContain("env.DEVICE_TOKEN");
    expect(source).toContain('"/internal/inner-os"');
    expect(innerOsSource).toContain('"oc.inner_os"');
    expect(source).toContain('"oc.capabilities"');
    expect(source).toContain('"oc.inner_os.ack"');
    expect(source).not.toMatch(/ocdt_[A-Za-z0-9_-]+/);
    expect(source).not.toContain("55FkND");
  });

  test("waits for the matching turn ASR before generating private OS", async () => {
    const relaySource = await readFile(
      relayFile("src/index.ts"),
      "utf8",
    );
    const pagesSource = await readFile(
      new URL("../pages/realtime-handler.ts", import.meta.url),
      "utf8",
    );

    for (const source of [relaySource, pagesSource]) {
      expect(source).toContain("RealtimeTurnContext");
      expect(source).toContain("waitForUserText");
    }
  });
});

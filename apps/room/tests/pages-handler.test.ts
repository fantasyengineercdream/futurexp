import { describe, expect, test } from "vitest";

function relayBinding(responseStatus = 204): {
  namespace: DurableObjectNamespace;
  state: {
    name?: string;
    request?: Request;
  };
} {
  const state: { name?: string; request?: Request } = {};
  const stub = {
    fetch(request: Request) {
      state.request = request;
      return Promise.resolve(new Response(null, { status: responseStatus }));
    },
  };
  return {
    state,
    namespace: {
      idFromName(name: string) {
        state.name = name;
        return { name } as DurableObjectId;
      },
      get() {
        return stub;
      },
    } as unknown as DurableObjectNamespace,
  };
}

describe("Pages realtime handler", () => {
  test("serves status without requiring the StepFun secret", async () => {
    let module: typeof import("../pages/realtime-handler") | undefined;
    try {
      module = await import("../pages/realtime-handler");
    } catch {
      // The first TDD run intentionally reaches this branch before the handler exists.
    }

    expect(module?.handlePagesRequest).toBeTypeOf("function");
    const response = await module!.handlePagesRequest(
      new Request("https://demo.pages.dev/api/status"),
      {
        STEPFUN_API_KEY: "not-used-for-status",
        DEVICE_RELAY: relayBinding().namespace,
      },
    );
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ capacity: 8, active: 0 });
  });

  test("rejects an unknown character before opening an upstream socket", async () => {
    const { handlePagesRequest } = await import("../pages/realtime-handler");
    const response = await handlePagesRequest(
      new Request("https://demo.pages.dev/api/realtime?character=unknown", {
        headers: { Upgrade: "websocket" },
      }),
      {
        STEPFUN_API_KEY: "unused",
        DEVICE_RELAY: relayBinding().namespace,
      },
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "unknown_character" });
  });

  test("reports the upstream HTTP status without exposing its response body", async () => {
    const module = await import("../pages/realtime-handler");
    expect(module.upstreamUnavailable(403, "test-secret")).toEqual({
      error: "upstream_unavailable",
      upstream_status: 403,
      key_present: true,
      key_length: 11,
    });
  });

  test("normalizes a secret pasted with a trailing newline", async () => {
    const module = await import("../pages/realtime-handler");
    expect(module.normalizeSecret("test-secret\r\n")).toBe("test-secret");
  });

  test("forwards the device route and its authorization header", async () => {
    const { handlePagesRequest } = await import("../pages/realtime-handler");
    const relay = relayBinding();
    const response = await handlePagesRequest(
      new Request("https://demo.pages.dev/api/device/realtime?character=devil&deviceId=orangepi-3b-01", {
        headers: {
          Upgrade: "websocket",
          Authorization: "Bearer device-secret",
        },
      }),
      {
        STEPFUN_API_KEY: "not-used-for-device-route",
        DEVICE_RELAY: relay.namespace,
      },
    );
    expect(response.status).toBe(204);
    expect(relay.state.name).toBe("orangepi-3b-01");
    expect(relay.state.request?.url).toContain("/api/device/realtime");
    expect(relay.state.request?.headers.get("Authorization")).toBe(
      "Bearer device-secret",
    );
  });

  test("forwards the viewer route to the same named device room", async () => {
    const { handlePagesRequest } = await import("../pages/realtime-handler");
    const relay = relayBinding();
    const response = await handlePagesRequest(
      new Request("https://demo.pages.dev/api/device/view?deviceId=orangepi-3b-01", {
        headers: { Upgrade: "websocket" },
      }),
      {
        STEPFUN_API_KEY: "not-used-for-view-route",
        DEVICE_RELAY: relay.namespace,
      },
    );
    expect(response.status).toBe(204);
    expect(relay.state.name).toBe("orangepi-3b-01");
    expect(relay.state.request?.url).toContain("/api/device/view");
  });

  test("reads private OS capability through the existing relay binding", async () => {
    const { handlePagesRequest } = await import("../pages/realtime-handler");
    const relay = relayBinding();
    const response = await handlePagesRequest(
      new Request(
        "https://demo.pages.dev/api/device/status?deviceId=orangepi-3b-01",
      ),
      {
        STEPFUN_API_KEY: "not-used-for-status-route",
        DEVICE_RELAY: relay.namespace,
      },
    );
    expect(response.status).toBe(204);
    expect(relay.state.name).toBe("orangepi-3b-01");
    expect(relay.state.request?.url).toContain("/internal/inner-os/status");
  });

  test("rejects an invalid device id before binding lookup", async () => {
    const { handlePagesRequest } = await import("../pages/realtime-handler");
    const relay = relayBinding();
    const response = await handlePagesRequest(
      new Request("https://demo.pages.dev/api/device/view?deviceId=../bad", {
        headers: { Upgrade: "websocket" },
      }),
      {
        STEPFUN_API_KEY: "unused",
        DEVICE_RELAY: relay.namespace,
      },
    );
    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "invalid_device_id" });
    expect(relay.state.name).toBeUndefined();
  });
});

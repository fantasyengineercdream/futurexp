import { createServer } from "node:http";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import WebSocket, { WebSocketServer } from "ws";
import {
  createVpsRelay,
  loadVoiceContextFromApi,
} from "../vps-relay/server";

const servers: Array<{ close(callback: () => void): void }> = [];
const sockets: WebSocket[] = [];

afterEach(async () => {
  sockets.splice(0).forEach((socket) => socket.close());
  await Promise.all(
    servers.splice(0).map(
      (server) =>
        new Promise<void>((resolve) => server.close(resolve)),
    ),
  );
});

async function listen(server: ReturnType<typeof createServer>): Promise<number> {
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  servers.push(server);
  const address = server.address();
  if (!address || typeof address === "string") throw new Error("missing port");
  return address.port;
}

async function open(socket: WebSocket): Promise<WebSocket> {
  sockets.push(socket);
  await new Promise<void>((resolve, reject) => {
    socket.once("open", resolve);
    socket.once("error", reject);
  });
  return socket;
}

async function waitFor(
  check: () => boolean,
  timeoutMs = 2_000,
): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!check()) {
    if (Date.now() >= deadline) throw new Error("condition timed out");
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
}

async function nextJson(socket: WebSocket): Promise<Record<string, unknown>> {
  return await new Promise((resolve, reject) => {
    socket.once("message", (value) => {
      try {
        resolve(JSON.parse(String(value)) as Record<string, unknown>);
      } catch (error) {
        reject(error);
      }
    });
    socket.once("error", reject);
  });
}

describe("VPS Realtime relay", () => {
  it("loads the active OC memory on the server without room URL state", async () => {
    const upstreamServer = createServer();
    const upstreamWss = new WebSocketServer({ server: upstreamServer });
    const upstreamMessages: string[] = [];
    upstreamWss.on("connection", (socket) => {
      socket.on("message", (value) => upstreamMessages.push(String(value)));
      socket.send(JSON.stringify({ type: "session.created" }));
    });
    const upstreamPort = await listen(upstreamServer);
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-memory-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Room</h1>");
    const requestedBodies: unknown[] = [];
    const memoryApi = createServer((request, response) => {
      let raw = "";
      request.setEncoding("utf8");
      request.on("data", (chunk) => {
        raw += chunk;
      });
      request.on("end", () => {
        requestedBodies.push(JSON.parse(raw));
        response.writeHead(200, { "content-type": "application/json" });
        response.end(JSON.stringify({
          actorId: "oc-devil",
          memoryInstructions:
            "你自己亲历并记住：昨天在异常房间完成了一次检定。",
        }));
      });
    });
    const memoryApiPort = await listen(memoryApi);
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: `ws://127.0.0.1:${upstreamPort}`,
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      voiceContextLoader: (actorId) => loadVoiceContextFromApi(
        `http://127.0.0.1:${memoryApiPort}`,
        actorId,
      ),
      innerOsGenerator: async () => ({
        text: "……",
        source: "fallback",
      }),
    });
    const relayPort = await listen(relay);

    await open(
      new WebSocket(
        `ws://127.0.0.1:${relayPort}/api/realtime?`
          + new URLSearchParams({
            character: "devil",
            deviceId: "orangepi-3b-01",
          }),
      ),
    );

    await waitFor(() =>
      upstreamMessages.some((message) => {
        const event = JSON.parse(message) as {
          type?: string;
          session?: { instructions?: string };
        };
        return (
          event.type === "session.update"
          && event.session?.instructions?.includes("异常房间") === true
        );
      }),
    );
    expect(requestedBodies).toContainEqual({ actorId: "oc-devil" });
  });

  it("configures StepFun from a bounded imported OC profile", async () => {
    const upstreamServer = createServer();
    const upstreamWss = new WebSocketServer({ server: upstreamServer });
    const upstreamMessages: string[] = [];
    upstreamWss.on("connection", (socket) => {
      socket.on("message", (value) => upstreamMessages.push(String(value)));
      socket.send(JSON.stringify({ type: "session.created" }));
    });
    const upstreamPort = await listen(upstreamServer);
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-imported-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Room</h1>");
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: `ws://127.0.0.1:${upstreamPort}`,
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      innerOsGenerator: async () => ({
        text: "……",
        source: "fallback",
      }),
    });
    const relayPort = await listen(relay);
    const profile = {
      id: "oc-imported-lan",
      name: "岚",
      role: "异常频道记者",
      persona: "认真但叛逆，会先核对证据。",
      publicStyle: "只说确认过的事实。",
      goals: ["调查异常频道"],
    };

    await open(
      new WebSocket(
        `ws://127.0.0.1:${relayPort}/api/realtime?`
          + new URLSearchParams({
            character: "angel",
            deviceId: "orangepi-3b-01",
            ocProfile: JSON.stringify(profile),
          }),
      ),
    );

    await waitFor(() =>
      upstreamMessages.some((message) => {
        const event = JSON.parse(message) as {
          type?: string;
          session?: { instructions?: string };
        };
        return (
          event.type === "session.update"
          && event.session?.instructions?.includes("岚") === true
          && event.session.instructions.includes("认真但叛逆")
        );
      }),
    );
  });

  it("uses one StepFun WebSocket for the Orange Pi and browser of one device", async () => {
    const upstreamServer = createServer();
    const upstreamWss = new WebSocketServer({ server: upstreamServer });
    const upstreamMessages: string[] = [];
    let upstreamConnections = 0;
    upstreamWss.on("connection", (socket) => {
      upstreamConnections += 1;
      socket.send(JSON.stringify({ type: "session.created" }));
      socket.on("message", (value) => upstreamMessages.push(String(value)));
    });
    const upstreamPort = await listen(upstreamServer);

    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-relay-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Voice Lab</h1>");
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: `ws://127.0.0.1:${upstreamPort}`,
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      innerOsGenerator: async () => ({
        text: "才不是在担心你。",
        source: "model",
      }),
    });
    const relayPort = await listen(relay);

    await open(
      new WebSocket(
        `ws://127.0.0.1:${relayPort}/api/device/realtime`
          + "?character=devil&deviceId=orangepi-3b-01",
        { headers: { Authorization: "Bearer test-device-token" } },
      ),
    );
    await waitFor(() => upstreamConnections === 1);

    const browser = await open(
      new WebSocket(
        `ws://127.0.0.1:${relayPort}/api/realtime`
          + "?character=devil&deviceId=orangepi-3b-01",
      ),
    );
    expect(upstreamConnections).toBe(1);

    browser.send(JSON.stringify({
      type: "input_audio_buffer.append",
      audio: "AAAA",
    }));
    await waitFor(() =>
      upstreamMessages.some((message) =>
        JSON.parse(message).type === "input_audio_buffer.append"
      )
    );
    expect(upstreamConnections).toBe(1);
  });

  it("reconnects the one shared StepFun socket while room sources remain online", async () => {
    const upstreamServer = createServer();
    const upstreamWss = new WebSocketServer({ server: upstreamServer });
    const upstreamSockets: WebSocket[] = [];
    const upstreamMessages: string[] = [];
    upstreamWss.on("connection", (socket) => {
      upstreamSockets.push(socket);
      socket.send(JSON.stringify({ type: "session.created" }));
      socket.on("message", (value) => upstreamMessages.push(String(value)));
    });
    const upstreamPort = await listen(upstreamServer);
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-reconnect-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Voice Lab</h1>");
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: `ws://127.0.0.1:${upstreamPort}`,
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      innerOsGenerator: async () => ({
        text: "……",
        source: "fallback",
      }),
    });
    const relayPort = await listen(relay);

    await open(
      new WebSocket(
        `ws://127.0.0.1:${relayPort}/api/device/realtime`
          + "?character=devil&deviceId=orangepi-3b-01",
        { headers: { Authorization: "Bearer test-device-token" } },
      ),
    );
    const browser = await open(
      new WebSocket(
        `ws://127.0.0.1:${relayPort}/api/realtime`
          + "?character=devil&deviceId=orangepi-3b-01",
      ),
    );
    await waitFor(() => upstreamSockets.length === 1);

    upstreamSockets[0].close(1011, "simulated upstream outage");
    await waitFor(() => upstreamSockets.length === 2, 2_500);

    browser.send(JSON.stringify({
      type: "input_audio_buffer.append",
      audio: "AAAA",
    }));
    await waitFor(() =>
      upstreamMessages.some((message) =>
        JSON.parse(message).type === "input_audio_buffer.append"
      )
    );
    expect(upstreamSockets).toHaveLength(2);
  });

  it("rejects an invalid Orange Pi token before opening StepFun", async () => {
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-auth-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Voice Lab</h1>");
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: "ws://127.0.0.1:9",
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "correct-device-token",
      innerOsGenerator: async () => ({
        text: "……",
        source: "fallback",
      }),
    });
    const port = await listen(relay);
    const socket = new WebSocket(
      `ws://127.0.0.1:${port}/api/device/realtime`
        + "?character=devil&deviceId=orangepi-3b-01",
      { headers: { Authorization: "Bearer wrong-device-token" } },
    );
    sockets.push(socket);

    const status = await new Promise<number>((resolve, reject) => {
      socket.once("unexpected-response", (_request, response) =>
        resolve(response.statusCode ?? 0)
      );
      socket.once("open", () => reject(new Error("unexpected open")));
      socket.once("error", () => undefined);
    });
    expect(status).toBe(401);
  });

  it("gives one browser viewer exclusive access to the connected ring", async () => {
    const upstreamServer = createServer();
    const upstreamWss = new WebSocketServer({ server: upstreamServer });
    upstreamWss.on("connection", (socket) => {
      socket.send(JSON.stringify({ type: "session.created" }));
    });
    const upstreamPort = await listen(upstreamServer);
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-viewer-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Voice Lab</h1>");
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: `ws://127.0.0.1:${upstreamPort}`,
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      innerOsGenerator: async () => ({
        text: "……",
        source: "fallback",
      }),
    });
    const port = await listen(relay);

    await open(
      new WebSocket(
        `ws://127.0.0.1:${port}/api/device/realtime`
          + "?character=devil&deviceId=orangepi-3b-01",
        { headers: { Authorization: "Bearer test-device-token" } },
      ),
    );
    const viewer = new WebSocket(
      `ws://127.0.0.1:${port}/api/device/view`
        + "?deviceId=orangepi-3b-01",
    );
    const readyPromise = nextJson(viewer);
    await open(viewer);
    await expect(readyPromise).resolves.toEqual({
      type: "session.ready",
      status: "acquired",
    });

    const contender = new WebSocket(
      `ws://127.0.0.1:${port}/api/device/view`
        + "?deviceId=orangepi-3b-01",
    );
    const busyPromise = nextJson(contender);
    await open(contender);
    await expect(busyPromise).resolves.toEqual({
      type: "session.busy",
      code: "ring_in_use",
    });
  });

  it("generates one private OS from the same completed voice turn", async () => {
    const upstreamServer = createServer();
    const upstreamWss = new WebSocketServer({ server: upstreamServer });
    let upstreamSocket: WebSocket | undefined;
    upstreamWss.on("connection", (socket) => {
      upstreamSocket = socket;
      socket.send(JSON.stringify({ type: "session.created" }));
    });
    const upstreamPort = await listen(upstreamServer);
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-inner-os-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Voice Lab</h1>");
    const generatedInputs: Array<{
      character: string;
      userText: string;
      publicText: string;
    }> = [];
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: `ws://127.0.0.1:${upstreamPort}`,
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      innerOsGenerator: async (input) => {
        generatedInputs.push(input);
        return { text: "才不是在担心你。", source: "model" };
      },
    });
    const port = await listen(relay);

    const device = await open(
      new WebSocket(
        `ws://127.0.0.1:${port}/api/device/realtime`
          + "?character=devil&deviceId=orangepi-3b-01",
        { headers: { Authorization: "Bearer test-device-token" } },
      ),
    );
    device.send(JSON.stringify({
      type: "oc.capabilities",
      capabilities: ["inner_os.v1"],
    }));
    const viewerMessages: Record<string, unknown>[] = [];
    const viewer = await open(
      new WebSocket(
        `ws://127.0.0.1:${port}/api/device/view`
          + "?deviceId=orangepi-3b-01",
      ),
    );
    viewer.on("message", (value) => {
      viewerMessages.push(
        JSON.parse(String(value)) as Record<string, unknown>,
      );
    });
    await waitFor(() => upstreamSocket !== undefined);

    const privateOsPromise = new Promise<Record<string, unknown>>(
      (resolve, reject) => {
        const onMessage = (value: WebSocket.RawData) => {
          const message = JSON.parse(String(value)) as Record<string, unknown>;
          if (message.type === "oc.inner_os") {
            device.off("message", onMessage);
            resolve(message);
          }
        };
        device.on("message", onMessage);
        device.once("error", reject);
      },
    );
    upstreamSocket!.send(JSON.stringify({
      type: "conversation.item.input_audio_transcription.completed",
      transcript: "你会陪我吗？",
    }));
    upstreamSocket!.send(JSON.stringify({
      type: "response.audio_transcript.done",
      transcript: "勉强陪你一会儿。",
    }));

    const privateOs = await privateOsPromise;
    expect(privateOs).toMatchObject({
      type: "oc.inner_os",
      character: "devil",
      text: "才不是在担心你。",
      source: "model",
    });
    expect(
      viewerMessages.some((message) => message.type === "inner_os.delivered"),
    ).toBe(false);
    device.send(JSON.stringify({
      type: "oc.inner_os.ack",
      event_id: privateOs.event_id,
      status: "accepted",
    }));
    await waitFor(() =>
      viewerMessages.some((message) => message.type === "inner_os.delivered")
    );
    expect(
      viewerMessages.find((message) => message.type === "inner_os.delivered"),
    ).toEqual({
      type: "inner_os.delivered",
      character: "devil",
      publicReply: "勉强陪你一会儿。",
      privateInnerOs: "才不是在担心你。",
    });
    expect(generatedInputs).toEqual([{
      character: "devil",
      userText: "你会陪我吗？",
      publicText: "勉强陪你一会儿。",
    }]);
  });

  it("serves the built room frontend and a no-cache health endpoint", async () => {
    const staticDir = await mkdtemp(join(tmpdir(), "oc-vps-static-"));
    await writeFile(join(staticDir, "index.html"), "<h1>OC Voice Lab</h1>");
    const relay = createVpsRelay({
      staticDir,
      stepfunUrl: "ws://127.0.0.1:9",
      stepfunApiKey: "test-stepfun-key",
      deviceToken: "test-device-token",
      innerOsGenerator: async () => ({
        text: "……",
        source: "fallback",
      }),
    });
    const port = await listen(relay);

    const page = await fetch(`http://127.0.0.1:${port}/`);
    expect(page.status).toBe(200);
    expect(await page.text()).toContain("OC Voice Lab");

    const health = await fetch(`http://127.0.0.1:${port}/api/health`);
    expect(health.status).toBe(200);
    expect(health.headers.get("cache-control")).toBe("no-store");
    await expect(health.json()).resolves.toEqual({
      status: "ok",
      service: "oc-voice-vps-relay",
    });
  });
});

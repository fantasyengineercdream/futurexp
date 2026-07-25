const WebSocket = require("ws");

const token = process.env.OC_DEVICE_TOKEN?.trim();
if (!token) throw new Error("OC_DEVICE_TOKEN is required");

const baseUrl =
  process.env.SMOKE_BASE_URL?.trim() || "https://oc-voice-lab.pages.dev";
const character = process.env.SMOKE_CHARACTER === "angel" ? "angel" : "devil";
const deviceId =
  process.env.SMOKE_DEVICE_ID
  || `orangepi-smoke-${String(Date.now()).slice(-10)}`;
const wsOrigin = baseUrl.replace(/^http/, "ws").replace(/\/$/, "");

const result = {
  deviceConnected: false,
  upstreamReady: false,
  viewerReady: false,
  capabilityReady: false,
  publicTranscript: false,
  publicAudioBytes: 0,
  privateOsReceived: false,
  privateOsCharacters: 0,
  deliveryAcknowledged: false,
  privateTextLeakedToViewer: false,
};

const device = new WebSocket(
  `${wsOrigin}/api/device/realtime`
    + `?character=${character}&deviceId=${deviceId}`,
  { headers: { Authorization: `Bearer ${token}` } },
);
let viewer;
let privateText = "";
let turnSent = false;
let finished = false;

const timeout = setTimeout(
  () => finish(false, "timeout"),
  45_000,
);

function sendTurn() {
  if (
    turnSent
    || !result.upstreamReady
    || !result.viewerReady
    || !result.capabilityReady
  ) {
    return;
  }
  turnSent = true;
  device.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [
        {
          type: "input_text",
          text: "我今天有点累，但还是想来看看你。",
        },
      ],
    },
  }));
  device.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "response.create",
    response: { modalities: ["text", "audio"] },
  }));
}

function maybeFinish() {
  if (
    result.publicTranscript
    && result.publicAudioBytes > 0
    && result.privateOsReceived
    && result.deliveryAcknowledged
  ) {
    finish(!result.privateTextLeakedToViewer, "complete");
  }
}

function finish(ok, reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.log(JSON.stringify({ ok, reason, deviceId, ...result }));
  try {
    viewer?.close(1000, "smoke complete");
  } catch {
    // already closed
  }
  try {
    device.close(1000, "smoke complete");
  } catch {
    // already closed
  }
  if (!ok) process.exitCode = 1;
}

device.on("open", () => {
  result.deviceConnected = true;
  device.send(JSON.stringify({
    type: "oc.capabilities",
    capabilities: ["inner_os.v1"],
  }));
  viewer = new WebSocket(
    `${wsOrigin}/api/device/view?deviceId=${deviceId}`,
  );
  viewer.on("message", (data, isBinary) => {
    if (isBinary) {
      result.publicAudioBytes += data.length;
      maybeFinish();
      return;
    }
    const message = JSON.parse(data.toString());
    if (message.type === "session.ready") {
      result.viewerReady = true;
    } else if (
      message.type === "inner_os.status"
      && message.status === "ready"
    ) {
      result.capabilityReady = true;
    } else if (
      message.type === "inner_os.status"
      && message.status === "delivered"
    ) {
      result.deliveryAcknowledged = true;
    } else if (
      message.type === "transcript"
      && message.role === "assistant"
      && message.text
    ) {
      result.publicTranscript = true;
    }
    if (
      message.type === "oc.inner_os"
      || (privateText && JSON.stringify(message).includes(privateText))
    ) {
      result.privateTextLeakedToViewer = true;
    }
    sendTurn();
    maybeFinish();
  });
  viewer.on("error", () => finish(false, "viewer error"));
});

device.on("message", (data, isBinary) => {
  if (isBinary) return;
  const message = JSON.parse(data.toString());
  if (message.type === "session.updated") {
    result.upstreamReady = true;
    sendTurn();
  }
  if (message.type === "oc.inner_os") {
    privateText = String(message.text || "");
    result.privateOsReceived = privateText.length > 0;
    result.privateOsCharacters = Array.from(privateText).length;
    device.send(JSON.stringify({
      type: "oc.inner_os.ack",
      event_id: message.event_id,
      status: "accepted",
    }));
  }
  if (message.type === "error") finish(false, "upstream error");
  maybeFinish();
});

device.on("unexpected-response", (_request, response) => {
  finish(false, `device HTTP ${response.statusCode}`);
});
device.on("error", () => finish(false, "device error"));

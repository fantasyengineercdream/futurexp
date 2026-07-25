const WebSocket = require("ws");

const token = process.env.OC_DEVICE_TOKEN?.trim();
if (!token) throw new Error("OC_DEVICE_TOKEN is required");

const baseUrl =
  process.env.SMOKE_BASE_URL?.trim() || "https://oc-voice-lab.pages.dev";
const character = process.env.SMOKE_CHARACTER === "angel" ? "angel" : "devil";
const deviceId =
  process.env.SMOKE_DEVICE_ID
  || `orangepi-computer-${String(Date.now()).slice(-10)}`;
const wsOrigin = baseUrl.replace(/^http/, "ws").replace(/\/$/, "");

const result = {
  deviceConnected: false,
  deviceCapabilityReady: false,
  computerVoiceReady: false,
  publicTranscript: false,
  contextMatched: false,
  publicAudioBytes: 0,
  privateOsReceived: false,
  privateOsCharacters: 0,
  deliveryAcknowledged: false,
  privateTextLeakedToComputer: false,
};

const computerMessages = [];
let privateText = "";
let turnSent = false;
let finished = false;
let computer;
let pollTimer;

const device = new WebSocket(
  `${wsOrigin}/api/device/realtime`
    + `?character=${character}&deviceId=${deviceId}`,
  { headers: { Authorization: `Bearer ${token}` } },
);

const timeout = setTimeout(() => finish(false, "timeout"), 45_000);

function sendTurn() {
  if (
    turnSent
    || !result.deviceCapabilityReady
    || !result.computerVoiceReady
  ) {
    return;
  }
  turnSent = true;
  computer.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [
        {
          type: "input_text",
          text: "请只回答测试暗号“月桂”，不要说别的。",
        },
      ],
    },
  }));
  computer.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "response.create",
    response: { modalities: ["text", "audio"] },
  }));
}

async function pollDeliveryStatus() {
  try {
    const response = await fetch(
      `${baseUrl}/api/device/status?deviceId=${deviceId}`,
      { cache: "no-store" },
    );
    const value = await response.json();
    if (
      value.inner_os === "ready"
      || value.inner_os === "sent"
      || value.inner_os === "delivered"
    ) {
      result.deviceCapabilityReady = true;
      sendTurn();
    }
    if (value.inner_os === "delivered") {
      result.deliveryAcknowledged = true;
      maybeFinish();
    }
  } catch {
    // The next poll can recover; public voice must not depend on this request.
  }
}

function maybeFinish() {
  if (privateText) {
    result.privateTextLeakedToComputer = computerMessages.some((message) =>
      message.includes(privateText),
    );
  }
  if (
    result.publicTranscript
    && result.contextMatched
    && result.publicAudioBytes > 0
    && result.privateOsReceived
    && result.deliveryAcknowledged
  ) {
    finish(!result.privateTextLeakedToComputer, "complete");
  }
}

function finish(ok, reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  clearInterval(pollTimer);
  console.log(JSON.stringify({ ok, reason, deviceId, ...result }));
  try {
    computer?.close(1000, "smoke complete");
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
  pollTimer = setInterval(() => {
    void pollDeliveryStatus();
  }, 500);
});

device.on("message", (data, isBinary) => {
  if (isBinary) return;
  const message = JSON.parse(data.toString());
  if (message.type === "oc.inner_os") {
    privateText = String(message.text || "");
    result.privateOsReceived = privateText.length > 0;
    result.privateOsCharacters = Array.from(privateText).length;
    device.send(JSON.stringify({
      type: "oc.inner_os.ack",
      event_id: message.event_id,
      status: "accepted",
    }));
    maybeFinish();
  }
});

device.on("error", () => finish(false, "device error"));

computer = new WebSocket(
  `${wsOrigin}/api/realtime`
    + `?character=${character}&deviceId=${deviceId}`,
);
computer.on("message", (data, isBinary) => {
  if (isBinary) return;
  const raw = data.toString();
  computerMessages.push(raw);
  const message = JSON.parse(raw);
  if (message.type === "session.updated") {
    result.computerVoiceReady = true;
  } else if (
    message.type === "inner_os.status"
    && (
      message.status === "ready"
      || message.status === "sent"
      || message.status === "delivered"
    )
  ) {
    result.deviceCapabilityReady = true;
  } else if (
    message.type === "response.audio_transcript.done"
    && message.transcript
  ) {
    result.publicTranscript = true;
    result.contextMatched = String(message.transcript).includes("月桂");
  } else if (message.type === "response.audio.delta" && message.delta) {
    result.publicAudioBytes += Buffer.from(message.delta, "base64").length;
  } else if (message.type === "error") {
    finish(false, "computer upstream error");
  }
  sendTurn();
  maybeFinish();
});
computer.on("error", () => finish(false, "computer error"));

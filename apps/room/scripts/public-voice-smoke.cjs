const WebSocket = require("ws");

const baseUrl =
  process.env.SMOKE_BASE_URL?.trim() || "https://oc-voice.open.smn.icu";
const wsOrigin = baseUrl.replace(/^http/, "ws").replace(/\/$/, "");
const deviceId = `public-smoke-${Date.now()}`;
const socket = new WebSocket(
  `${wsOrigin}/api/realtime?character=angel&deviceId=${deviceId}`,
);

let sessionReady = false;
let responseRequested = false;
let audioBytes = 0;
let transcript = "";
let finished = false;

const timeout = setTimeout(() => finish(false, "timeout"), 40_000);

function finish(ok, reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.log(JSON.stringify({
    ok,
    reason,
    sessionReady,
    audioBytes,
    transcript,
  }));
  try {
    socket.close(1000, "public voice smoke complete");
  } catch {
    // The socket may already be closed.
  }
  setTimeout(() => process.exit(ok ? 0 : 1), 100);
}

socket.on("message", (data, isBinary) => {
  if (isBinary) return;
  const message = JSON.parse(data.toString());
  if (message.type === "session.updated") {
    sessionReady = true;
    if (!responseRequested) {
      responseRequested = true;
      socket.send(JSON.stringify({
        event_id: crypto.randomUUID(),
        type: "response.create",
        response: { modalities: ["text", "audio"] },
      }));
    }
  } else if (message.type === "response.audio.delta" && message.delta) {
    audioBytes += Buffer.from(message.delta, "base64").length;
  } else if (message.type === "response.audio_transcript.done") {
    transcript = String(message.transcript || "");
  } else if (message.type === "response.done") {
    finish(sessionReady && audioBytes > 0 && transcript.length > 0, "response.done");
  } else if (message.type === "error") {
    finish(false, message.error?.message || "upstream error");
  }
});

socket.on("error", (error) => finish(false, error.message || "socket error"));

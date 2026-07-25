const WebSocket = require("ws");

const baseUrl =
  process.env.SMOKE_BASE_URL?.trim() || "https://oc-voice-lab.pages.dev";
const wsOrigin = baseUrl.replace(/^http/, "ws").replace(/\/$/, "");
const deviceId = `browser-opening-${String(Date.now()).slice(-10)}`;
const socket = new WebSocket(
  `${wsOrigin}/api/realtime?character=devil&deviceId=${deviceId}`,
);

const result = {
  sessionReady: false,
  openingTranscript: false,
  openingAudioBytes: 0,
  followupTranscript: false,
  followupContextMatched: false,
  followupAudioBytes: 0,
};

let phase = "opening";
let openingSent = false;
let finished = false;
const timeout = setTimeout(() => finish(false, "timeout"), 50_000);

function finish(ok, reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.log(JSON.stringify({ ok, reason, ...result }));
  try {
    socket.close(1000, "opening smoke complete");
  } catch {
    // already closed
  }
  if (!ok) process.exitCode = 1;
}

function sendOpening() {
  socket.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "response.create",
    session: {
      instructions:
        "现在只做一次简短开场。以当前角色身份，用一句自然中文欢迎用户进入房间。",
    },
  }));
}

function sendFollowup() {
  socket.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "conversation.item.create",
    item: {
      type: "message",
      role: "user",
      content: [{
        type: "input_text",
        text: "第二轮只回答测试暗号“松塔”，不要说别的。",
      }],
    },
  }));
  socket.send(JSON.stringify({
    event_id: crypto.randomUUID(),
    type: "response.create",
    response: { modalities: ["text", "audio"] },
  }));
}

socket.on("message", (data, isBinary) => {
  if (isBinary) return;
  const message = JSON.parse(data.toString());
  if (message.type === "session.updated") {
    result.sessionReady = true;
    if (!openingSent) {
      openingSent = true;
      sendOpening();
    }
  } else if (
    message.type === "response.audio_transcript.done"
    && message.transcript
  ) {
    if (phase === "opening") {
      result.openingTranscript = true;
    } else {
      result.followupTranscript = true;
      result.followupContextMatched =
        String(message.transcript).includes("松塔");
    }
  } else if (message.type === "response.audio.delta" && message.delta) {
    const bytes = Buffer.from(message.delta, "base64").length;
    if (phase === "opening") {
      result.openingAudioBytes += bytes;
    } else {
      result.followupAudioBytes += bytes;
    }
  } else if (message.type === "response.done") {
    if (phase === "opening") {
      if (!result.openingTranscript || result.openingAudioBytes === 0) {
        finish(false, "opening failed");
        return;
      }
      phase = "followup";
      sendFollowup();
    } else {
      finish(
        result.followupTranscript
          && result.followupContextMatched
          && result.followupAudioBytes > 0,
        "complete",
      );
    }
  } else if (message.type === "error") {
    finish(false, "upstream error");
  }
});

socket.on("error", () => finish(false, "socket error"));

const fs = require("node:fs");
const WebSocket = require("ws");

const wavPath = process.env.SMOKE_WAV?.trim();
const secondWavPath = process.env.SMOKE_WAV_SECOND?.trim();
if (!wavPath || !secondWavPath) {
  throw new Error("SMOKE_WAV and SMOKE_WAV_SECOND are required");
}

const baseUrl =
  process.env.SMOKE_BASE_URL?.trim() || "https://oc-voice-lab.pages.dev";
const wsOrigin = baseUrl.replace(/^http/, "ws").replace(/\/$/, "");
const deviceId = `browser-audio-${String(Date.now()).slice(-10)}`;

function readPcm16Mono24k(path) {
  const wav = fs.readFileSync(path);
  if (wav.toString("ascii", 0, 4) !== "RIFF"
      || wav.toString("ascii", 8, 12) !== "WAVE") {
    throw new Error("SMOKE_WAV must be a RIFF/WAVE file");
  }
  let offset = 12;
  let format;
  let pcm;
  while (offset + 8 <= wav.length) {
    const id = wav.toString("ascii", offset, offset + 4);
    const size = wav.readUInt32LE(offset + 4);
    const start = offset + 8;
    if (id === "fmt ") {
      format = {
        codec: wav.readUInt16LE(start),
        channels: wav.readUInt16LE(start + 2),
        sampleRate: wav.readUInt32LE(start + 4),
        bits: wav.readUInt16LE(start + 14),
      };
    } else if (id === "data") {
      pcm = wav.subarray(start, start + size);
    }
    offset = start + size + (size % 2);
  }
  if (
    !format
    || format.codec !== 1
    || format.channels !== 1
    || format.sampleRate !== 24_000
    || format.bits !== 16
    || !pcm
  ) {
    throw new Error("SMOKE_WAV must be PCM16 mono 24000 Hz");
  }
  return pcm;
}

const silence = (milliseconds) =>
  Buffer.alloc(Math.round(24_000 * 2 * milliseconds / 1_000));
const turnAudio = [wavPath, secondWavPath].map((path) =>
  Buffer.concat([
    silence(500),
    readPcm16Mono24k(path),
    silence(1_200),
  ]),
);
const expectedWords = ["月桂", "松塔"];
const frameBytes = 24_000 * 2 * 20 / 1_000;

const result = {
  sessionReady: false,
  turnsRequested: turnAudio.length,
  turnsCompleted: 0,
  speechDetectedEveryTurn: true,
  userTranscriptEveryTurn: true,
  contextMatchedEveryTurn: true,
  publicAudioBytes: 0,
};

let finished = false;
let sending = false;
let turnIndex = 0;
let turn = newTurnState();
const socket = new WebSocket(
  `${wsOrigin}/api/realtime?character=devil&deviceId=${deviceId}`,
);
const timeout = setTimeout(() => finish(false, "timeout"), 50_000);

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function newTurnState() {
  return {
    speechStarted: false,
    speechStopped: false,
    userTranscriptPresent: false,
    assistantTranscriptPresent: false,
    contextMatched: false,
    publicAudioBytes: 0,
    finalizing: false,
  };
}

async function sendAudio() {
  if (sending) return;
  sending = true;
  const audio = turnAudio[turnIndex];
  for (let offset = 0; offset < audio.length; offset += frameBytes) {
    const frame = audio.subarray(offset, offset + frameBytes);
    socket.send(JSON.stringify({
      event_id: crypto.randomUUID(),
      type: "input_audio_buffer.append",
      audio: frame.toString("base64"),
    }));
    await sleep(20);
  }
  sending = false;
}

function finish(ok, reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.log(JSON.stringify({ ok, reason, ...result }));
  try {
    socket.close(1000, "audio smoke complete");
  } catch {
    // already closed
  }
  if (!ok) process.exitCode = 1;
}

function finalizeTurn() {
  const detected = turn.speechStarted && turn.speechStopped;
  const contextual =
    turn.assistantTranscriptPresent
    && turn.contextMatched
    && turn.publicAudioBytes > 0;
  result.turnsCompleted += 1;
  result.speechDetectedEveryTurn &&= detected;
  result.userTranscriptEveryTurn &&= turn.userTranscriptPresent;
  result.contextMatchedEveryTurn &&= contextual;
  if (!detected || !turn.userTranscriptPresent || !contextual) {
    finish(false, `turn ${turnIndex + 1} failed`);
    return;
  }
  turnIndex += 1;
  if (turnIndex >= turnAudio.length) {
    finish(true, "complete");
    return;
  }
  turn = newTurnState();
  setTimeout(() => {
    void sendAudio();
  }, 500);
}

socket.on("message", (data, isBinary) => {
  if (isBinary) return;
  const message = JSON.parse(data.toString());
  if (message.type === "session.updated") {
    result.sessionReady = true;
    void sendAudio();
  } else if (message.type === "input_audio_buffer.speech_started") {
    turn.speechStarted = true;
  } else if (message.type === "input_audio_buffer.speech_stopped") {
    turn.speechStopped = true;
  } else if (
    message.type
      === "conversation.item.input_audio_transcription.completed"
    && message.transcript
  ) {
    turn.userTranscriptPresent = true;
  } else if (
    message.type === "response.audio_transcript.done"
    && message.transcript
  ) {
    turn.assistantTranscriptPresent = true;
    turn.contextMatched =
      String(message.transcript).includes(expectedWords[turnIndex]);
  } else if (message.type === "response.audio.delta" && message.delta) {
    const bytes = Buffer.from(message.delta, "base64").length;
    turn.publicAudioBytes += bytes;
    result.publicAudioBytes += bytes;
  } else if (message.type === "response.done") {
    if (turn.finalizing) return;
    turn.finalizing = true;
    if (turn.userTranscriptPresent) {
      finalizeTurn();
    } else {
      setTimeout(finalizeTurn, 800);
    }
  } else if (message.type === "error") {
    finish(false, "upstream error");
  }
});

socket.on("error", () => finish(false, "socket error"));

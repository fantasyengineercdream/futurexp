const fs = require("fs");

const wavPath = process.argv[2];
if (!wavPath) throw new Error("Usage: node scripts/live-voice-smoke.cjs <mono-pcm16.wav>");

const wav = fs.readFileSync(wavPath);
let offset = 12;
let sampleRate = 0;
let channels = 0;
let bits = 0;
let data;

while (offset + 8 <= wav.length) {
  const id = wav.toString("ascii", offset, offset + 4);
  const size = wav.readUInt32LE(offset + 4);
  if (id === "fmt ") {
    channels = wav.readUInt16LE(offset + 10);
    sampleRate = wav.readUInt32LE(offset + 12);
    bits = wav.readUInt16LE(offset + 22);
  }
  if (id === "data") {
    data = wav.subarray(offset + 8, offset + 8 + size);
    break;
  }
  offset += 8 + size + (size % 2);
}

if (!data || channels !== 1 || bits !== 16) {
  throw new Error(`Unsupported WAV ${sampleRate}/${channels}/${bits}`);
}

const source = new Int16Array(data.buffer, data.byteOffset, Math.floor(data.length / 2));
const targetRate = 24_000;
const speech = new Int16Array(Math.round(source.length * targetRate / sampleRate));
for (let index = 0; index < speech.length; index += 1) {
  const position = index * sampleRate / targetRate;
  const left = Math.floor(position);
  const right = Math.min(left + 1, source.length - 1);
  const mix = position - left;
  speech[index] = Math.round(source[left] * (1 - mix) + source[right] * mix);
}

const leadingSilence = new Int16Array(targetRate / 2);
const trailingSilence = new Int16Array(targetRate * 2);
const input = new Int16Array(leadingSilence.length + speech.length + trailingSilence.length);
input.set(leadingSilence);
input.set(speech, leadingSilence.length);
input.set(trailingSilence, leadingSilence.length + speech.length);

const socket = new WebSocket("wss://oc-voice-lab.pages.dev/api/realtime?character=devil");
const events = new Set();
let outputBytes = 0;
let cursor = 0;
let transcript = "";
let retries = 0;
let interval;
let finished = false;

const timeout = setTimeout(() => finish(false, "timeout"), 90_000);

function finish(ok, reason) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  clearInterval(interval);
  console.log(JSON.stringify({
    ok,
    reason,
    inputSampleRate: sampleRate,
    inputSamples: source.length,
    transcript,
    outputBytes,
    retries,
    events: [...events],
  }));
  try { socket.close(); } catch { /* already closed */ }
  if (!ok) process.exitCode = 1;
}

socket.addEventListener("message", ({ data: message }) => {
  const event = JSON.parse(String(message));
  events.add(event.type);

  if (event.type === "session.updated" && !interval) {
    interval = setInterval(() => {
      if (cursor >= input.length) {
        clearInterval(interval);
        interval = undefined;
        return;
      }
      const frame = input.subarray(cursor, Math.min(cursor + 480, input.length));
      cursor += frame.length;
      socket.send(JSON.stringify({
        event_id: crypto.randomUUID(),
        type: "input_audio_buffer.append",
        audio: Buffer.from(frame.buffer, frame.byteOffset, frame.byteLength).toString("base64"),
      }));
    }, 20);
  }

  if (event.type === "conversation.item.input_audio_transcription.completed") {
    transcript = event.transcript ?? "";
  }
  if (event.type === "response.audio.delta") {
    outputBytes += Buffer.from(event.delta, "base64").length;
  }
  if (event.type === "response.done" && outputBytes === 0 && retries < 1) {
    retries += 1;
    socket.send(JSON.stringify({
      event_id: crypto.randomUUID(),
      type: "response.create",
      response: { modalities: ["text", "audio"] },
    }));
  } else if (event.type === "response.done") {
    finish(transcript.length > 0 && outputBytes > 0, "response.done");
  }
  if (event.type === "error") {
    finish(false, event.error?.message ?? "upstream error");
  }
});

socket.addEventListener("error", () => finish(false, "socket error"));

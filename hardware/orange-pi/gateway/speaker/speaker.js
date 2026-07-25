const button = document.querySelector("#connect");
const status = document.querySelector("#status");

let context;
let socket;
let nextTime = 0;
let busy = false;
const sources = new Set();

function clearPlayback() {
  for (const source of sources) {
    try { source.stop(); } catch { /* already ended */ }
  }
  sources.clear();
  nextTime = context?.currentTime ?? 0;
  status.textContent = "已清空（用户正在打断）";
}

function playPcm16(buffer) {
  const samples = new Int16Array(buffer);
  const audio = context.createBuffer(1, samples.length, 24000);
  const channel = audio.getChannelData(0);
  for (let index = 0; index < samples.length; index += 1) {
    channel[index] = samples[index] / 32768;
  }
  const source = context.createBufferSource();
  source.buffer = audio;
  source.connect(context.destination);
  sources.add(source);
  source.onended = () => sources.delete(source);
  nextTime = Math.max(nextTime, context.currentTime + 0.02);
  source.start(nextTime);
  nextTime += audio.duration;
  status.textContent = "角色正在说话";
}

button.addEventListener("click", async () => {
  context ??= new AudioContext({ sampleRate: 24000 });
  await context.resume();
  socket?.close();
  busy = false;
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/v1/audio-sink`);
  socket.binaryType = "arraybuffer";
  socket.onopen = () => { status.textContent = "已连接，正在确认戒指状态"; };
  socket.onclose = () => {
    if (!busy) status.textContent = "连接已断开";
  };
  socket.onerror = () => { status.textContent = "连接失败"; };
  socket.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
      playPcm16(event.data);
      return;
    }
    const message = JSON.parse(event.data);
    if (message.type === "session.ready") {
      status.textContent = "戒指通道已分配，等待角色音频";
    }
    if (message.type === "session.busy") {
      busy = true;
      status.textContent = "戒指正在被其他页面使用";
    }
    if (message.type === "playback.clear") clearPlayback();
    if (message.type === "state") status.textContent = message.phase;
  };
});

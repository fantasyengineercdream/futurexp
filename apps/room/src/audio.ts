import { base64ToPcm16, floatToPcm16, pcm16ToBase64, resampleLinear, STEP_SAMPLE_RATE } from "./pcm";

export const PLAYBACK_GAIN = 2;
export const MICROPHONE_PROCESSOR_SIZE = 1_024;

export class MicrophoneCapture {
  private context?: AudioContext;
  private stream?: MediaStream;
  private processor?: ScriptProcessorNode;

  async start(onFrame: (base64: string, level: number) => void): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.context = new AudioContext();
    await this.context.resume();
    const source = this.context.createMediaStreamSource(this.stream);
    this.processor = this.context.createScriptProcessor(
      MICROPHONE_PROCESSOR_SIZE,
      1,
      1,
    );
    const muted = this.context.createGain();
    muted.gain.value = 0;
    this.processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const samples = resampleLinear(input, event.inputBuffer.sampleRate);
      const level = Math.sqrt(samples.reduce((sum, sample) => sum + sample * sample, 0) / samples.length);
      onFrame(pcm16ToBase64(floatToPcm16(samples)), level);
    };
    source.connect(this.processor);
    this.processor.connect(muted);
    muted.connect(this.context.destination);
  }

  async stop(): Promise<void> {
    if (this.processor) this.processor.onaudioprocess = null;
    this.processor?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.context && this.context.state !== "closed") await this.context.close();
    this.processor = undefined;
    this.stream = undefined;
    this.context = undefined;
  }
}

export class PcmPlayback {
  private context = new AudioContext({ sampleRate: STEP_SAMPLE_RATE });
  private output = this.context.createGain();
  private sources = new Set<AudioBufferSourceNode>();
  private idleWaiters = new Set<() => void>();
  private pendingEnqueues = 0;
  private nextTime = 0;

  constructor() {
    this.output.gain.value = PLAYBACK_GAIN;
    this.output.connect(this.context.destination);
  }

  async enqueue(base64: string): Promise<void> {
    const pcm = base64ToPcm16(base64);
    await this.queueSamples(pcm);
  }

  async enqueuePcm16(value: ArrayBuffer): Promise<void> {
    await this.queueSamples(new Int16Array(value));
  }

  private async queueSamples(pcm: Int16Array): Promise<void> {
    this.pendingEnqueues += 1;
    try {
      await this.enqueueSamples(pcm);
    } finally {
      this.pendingEnqueues -= 1;
      this.resolveIdleWaiters();
    }
  }

  private async enqueueSamples(pcm: Int16Array): Promise<void> {
    await this.context.resume();
    const buffer = this.context.createBuffer(1, pcm.length, STEP_SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < pcm.length; index += 1) channel[index] = pcm[index] / 32768;
    const source = this.context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.output);
    const start = Math.max(this.context.currentTime + 0.015, this.nextTime);
    source.start(start);
    this.nextTime = start + buffer.duration;
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      this.resolveIdleWaiters();
    };
  }

  whenIdle(): Promise<void> {
    if (this.sources.size === 0 && this.pendingEnqueues === 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => this.idleWaiters.add(resolve));
  }

  private resolveIdleWaiters(): void {
    if (this.sources.size > 0 || this.pendingEnqueues > 0) return;
    this.nextTime = this.context.currentTime;
    const waiters = [...this.idleWaiters];
    this.idleWaiters.clear();
    waiters.forEach((resolve) => resolve());
  }

  clear(): void {
    this.sources.forEach((source) => {
      try { source.stop(); } catch { /* already stopped */ }
    });
    this.sources.clear();
    this.resolveIdleWaiters();
  }

  async close(): Promise<void> {
    this.clear();
    this.output.disconnect();
    if (this.context.state !== "closed") await this.context.close();
  }
}

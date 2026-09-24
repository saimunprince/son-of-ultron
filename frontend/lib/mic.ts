/* Hands-free microphone: voice-activity detection + WAV capture.
 *
 * Audio frames come from an AudioWorklet into a ring buffer. When energy rises
 * above an adaptive noise floor, an utterance starts (with ~400 ms of pre-roll
 * so the first syllable is kept). It ends after a stretch of silence and is
 * delivered as 16 kHz mono WAV, ready for Whisper.
 */

export type MicState = "off" | "starting" | "idle" | "hearing" | "error";

export interface MicHandlers {
  onUtterance: (wav: Blob, durationMs: number) => void;
  onSpeechStart?: () => void;
  onLevel?: (level: number) => void; // 0..1, ~30 fps
  onState?: (s: MicState) => void;
}

const TARGET_RATE = 16000;
const BLOCK_MS = 20;
const PREROLL_MS = 400;
const END_SILENCE_MS = 850;
const MIN_SPEECH_MS = 180; // "stop" must survive noise suppression
const MAX_UTTERANCE_MS = 15000;

const WORKLET = `
class Tap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("syrax-tap", Tap);
`;

export class MicListener {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

  private rate = 48000;
  private block: Float32Array[] = [];
  private blockLen = 0;
  private blockSize = 960;
  private preroll: Float32Array[] = [];
  private utter: Float32Array[] = [];
  private speaking = false;
  private speechMs = 0;
  private silenceMs = 0;
  private noise = 0.004;
  private lastLevelAt = 0;
  private peak = 0;

  /** Last utterance decision, for debugging (also on window.__syraxVad). */
  stats = { voicedMs: 0, totalMs: 0, peak: 0, threshold: 0, sent: false };

  /** Raise the bar while SYRAX is talking so its own voice is not picked up. */
  strict = false;
  paused = false;

  constructor(private h: MicHandlers) {}

  get active() {
    return this.ctx !== null;
  }

  async start() {
    if (this.ctx) return;
    this.h.onState?.("starting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      const ctx = new AudioContext();
      this.ctx = ctx;
      this.rate = ctx.sampleRate;
      this.blockSize = Math.round((this.rate * BLOCK_MS) / 1000);
      const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await ctx.audioWorklet.addModule(url);
      URL.revokeObjectURL(url);
      this.source = ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(ctx, "syrax-tap");
      this.node.port.onmessage = (e) => this.onFrame(e.data as Float32Array);
      this.source.connect(this.node);
      this.h.onState?.("idle");
    } catch (err) {
      this.stop();
      this.h.onState?.("error");
      throw err;
    }
  }

  stop() {
    this.node?.port.close();
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.node = null;
    this.source = null;
    this.stream = null;
    this.reset();
    this.h.onState?.("off");
  }

  private reset() {
    this.block = [];
    this.blockLen = 0;
    this.preroll = [];
    this.utter = [];
    this.speaking = false;
    this.speechMs = 0;
    this.silenceMs = 0;
  }

  private onFrame(frame: Float32Array) {
    this.block.push(frame);
    this.blockLen += frame.length;
    if (this.blockLen < this.blockSize) return;
    const block = concat(this.block, this.blockLen);
    this.block = [];
    this.blockLen = 0;
    this.onBlock(block);
  }

  private onBlock(block: Float32Array) {
    let sum = 0;
    for (let i = 0; i < block.length; i++) sum += block[i] * block[i];
    const rms = Math.sqrt(sum / block.length);

    const now = performance.now();
    if (now - this.lastLevelAt > 33) {
      this.lastLevelAt = now;
      this.h.onLevel?.(Math.min(1, rms * 12));
    }
    if (this.paused) return;

    const threshold = Math.max(0.012, this.noise * 3.2) * (this.strict ? 2.6 : 1);
    // Hysteresis: once speech started, softer tails still count as voice.
    const loud = rms > (this.speaking ? threshold * 0.55 : threshold);

    if (!this.speaking) {
      // Track the room's noise floor only while nobody is talking.
      this.noise = this.noise * 0.97 + Math.min(rms, 0.05) * 0.03;
      this.preroll.push(block);
      const maxPre = Math.ceil(PREROLL_MS / BLOCK_MS);
      if (this.preroll.length > maxPre) this.preroll.shift();
      if (loud) {
        this.speechMs += BLOCK_MS;
        if (this.speechMs >= 60) {
          this.speaking = true;
          this.silenceMs = 0;
          this.utter = [...this.preroll];
          this.preroll = [];
          this.h.onState?.("hearing");
          this.h.onSpeechStart?.();
        }
      } else {
        this.speechMs = 0;
      }
      return;
    }

    this.utter.push(block);
    this.peak = Math.max(this.peak, rms);
    if (loud) {
      this.speechMs += BLOCK_MS;
      this.silenceMs = 0;
    } else {
      this.silenceMs += BLOCK_MS;
    }
    const total = this.utter.length * BLOCK_MS;
    if (this.silenceMs >= END_SILENCE_MS || total >= MAX_UTTERANCE_MS) {
      const voiced = this.speechMs;
      const chunks = this.utter;
      this.speaking = false;
      this.speechMs = 0;
      this.silenceMs = 0;
      this.utter = [];
      this.h.onState?.("idle");
      this.stats = { voicedMs: voiced, totalMs: total, peak: +this.peak.toFixed(4), threshold: +threshold.toFixed(4), sent: voiced >= MIN_SPEECH_MS };
      this.peak = 0;
      if (typeof window !== "undefined") (window as unknown as { __syraxVad?: unknown }).__syraxVad = this.stats;
      if (voiced >= MIN_SPEECH_MS) {
        const pcm = concat(chunks, chunks.reduce((n, c) => n + c.length, 0));
        const wav = encodeWav(downsample(pcm, this.rate, TARGET_RATE), TARGET_RATE);
        this.h.onUtterance(wav, total);
      }
    }
  }
}

function concat(parts: Float32Array[], length: number) {
  const out = new Float32Array(length);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function downsample(input: Float32Array, from: number, to: number) {
  if (from === to) return input;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let acc = 0;
    for (let j = start; j < end; j++) acc += input[j];
    out[i] = acc / Math.max(1, end - start);
  }
  return out;
}

function encodeWav(samples: Float32Array, rate: number) {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

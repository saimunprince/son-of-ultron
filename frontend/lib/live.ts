/* Live talk: a real-time spoken conversation through SYRAX's /live socket
 * (Gemini Live behind it; the key stays on the server). The microphone goes up
 * as 16 kHz PCM16 in 40 ms chunks; the answer comes back as 24 kHz PCM16 and is
 * queued without gaps. When the human talks over SYRAX the server says
 * "interrupted" and everything queued stops at once. */

import { downsample, floatToPcm16, pcm16ToFloat, rms } from "@/lib/livePcm";

export type LiveState = "off" | "connecting" | "on" | "error";

export interface LiveEvent {
  type: "live";
  event: "open" | "turn" | "task" | "interrupted" | "ending" | "error" | "closed";
  text?: string;
  model?: string;
  heard?: string;
  said?: string;
  task_id?: string;
}

export interface LiveHandlers {
  onState: (s: LiveState, detail?: string) => void;
  onEvent?: (e: LiveEvent) => void;
  onLevel?: (level: number) => void;
}

const IN_RATE = 16000;
const OUT_RATE = 24000;
const CHUNK_MS = 40;

const WORKLET = `
class LiveTap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) this.port.postMessage(ch.slice(0));
    return true;
  }
}
registerProcessor("syrax-live-tap", LiveTap);
`;

export class LiveTalk {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private node: AudioWorkletNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private chunk: Float32Array[] = [];
  private chunkLen = 0;
  private playHead = 0;
  private playing = new Set<AudioBufferSourceNode>();
  private ended = false;

  constructor(
    private url: string,
    private h: LiveHandlers,
  ) {}

  async start() {
    this.h.onState("connecting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
      const ctx = new AudioContext();
      this.ctx = ctx;
      if (ctx.state === "suspended") await ctx.resume();
      const mod = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
      await ctx.audioWorklet.addModule(mod);
      URL.revokeObjectURL(mod);
      this.source = ctx.createMediaStreamSource(this.stream);
      this.node = new AudioWorkletNode(ctx, "syrax-live-tap");
      this.node.port.onmessage = (e) => this.onMic(e.data as Float32Array);
      this.source.connect(this.node); // never to the speakers: the mic is not played back
    } catch (e) {
      this.finish("error", `microphone: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    const ws = new WebSocket(this.url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") this.onJson(ev.data);
      else this.play(ev.data as ArrayBuffer);
    };
    ws.onerror = () => this.finish("error", "the live connection to SYRAX failed");
    ws.onclose = () => this.finish("off");
  }

  /** End the conversation (the server journals it as closed). */
  stop() {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "stop" }));
    this.finish("off");
  }

  private onJson(raw: string) {
    let e: LiveEvent;
    try {
      e = JSON.parse(raw) as LiveEvent;
    } catch {
      return;
    }
    if (e.event === "open") this.h.onState("on", e.model);
    else if (e.event === "interrupted") this.flush();
    else if (e.event === "error") this.finish("error", e.text);
    this.h.onEvent?.(e);
  }

  private onMic(frame: Float32Array) {
    const ctx = this.ctx;
    if (!ctx || this.ws?.readyState !== WebSocket.OPEN) return;
    this.chunk.push(frame);
    this.chunkLen += frame.length;
    if (this.chunkLen < (ctx.sampleRate * CHUNK_MS) / 1000) return;
    const all = new Float32Array(this.chunkLen);
    let at = 0;
    for (const f of this.chunk) {
      all.set(f, at);
      at += f.length;
    }
    this.chunk = [];
    this.chunkLen = 0;
    if (!this.playing.size) this.h.onLevel?.(Math.min(1, rms(all) * 4));
    this.ws.send(floatToPcm16(downsample(all, ctx.sampleRate, IN_RATE)));
  }

  private play(buf: ArrayBuffer) {
    const ctx = this.ctx;
    if (!ctx || !buf.byteLength) return;
    const samples = pcm16ToFloat(buf);
    const audio = ctx.createBuffer(1, samples.length, OUT_RATE);
    audio.copyToChannel(samples, 0);
    const src = ctx.createBufferSource();
    src.buffer = audio;
    src.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, this.playHead);
    src.start(at);
    this.playHead = at + audio.duration;
    this.playing.add(src);
    src.onended = () => {
      this.playing.delete(src);
      if (!this.playing.size) this.h.onLevel?.(0);
    };
    this.h.onLevel?.(Math.min(1, rms(samples) * 3));
  }

  /** Barge-in: drop everything queued. */
  private flush() {
    for (const src of this.playing) {
      try {
        src.stop();
      } catch {
        /* already ended */
      }
    }
    this.playing.clear();
    this.playHead = 0;
  }

  private finish(state: "off" | "error", detail?: string) {
    if (this.ended) return;
    this.ended = true;
    this.flush();
    if (this.ws) {
      this.ws.onclose = null;
      this.ws.onerror = null;
      if (this.ws.readyState <= WebSocket.OPEN) this.ws.close();
      this.ws = null;
    }
    this.node?.port.close();
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
    this.h.onLevel?.(0);
    this.h.onState(state, detail);
  }
}

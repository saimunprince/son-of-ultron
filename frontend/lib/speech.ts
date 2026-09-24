/* SYRAX's voice: neural TTS from the backend, run through a light metallic
 * "Ultron" chain, with a live level for the orb. Falls back to the browser's
 * own speechSynthesis when the backend voice is unavailable. */

import { API_BASE } from "@/lib/syraxClient";

export interface SpeakHandlers {
  onStart?: () => void;
  onLevel?: (level: number) => void;
  /** neural voice failed; reason is shown to the user */
  onError?: (reason: string) => void;
}

let ctx: AudioContext | null = null;
let current: { stop: () => void } | null = null;
let duckGain: GainNode | null = null;

function audioCtx() {
  if (!ctx) ctx = new AudioContext();
  if (ctx.state === "suspended") void ctx.resume();
  return ctx;
}

/** Call from a user gesture once so later playback is allowed. */
export function unlockAudio() {
  audioCtx();
}

export function isSpeaking() {
  return current !== null;
}

export function stopSpeaking() {
  current?.stop();
  current = null;
  if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
}

/** Lower SYRAX's volume while the human starts talking over it. */
export function duck(on: boolean) {
  if (duckGain && ctx) duckGain.gain.setTargetAtTime(on ? 0.2 : 1, ctx.currentTime, 0.05);
}

let impulse: AudioBuffer | null = null;

/** Synthetic hall reverb: decaying noise, generated once. */
function hallImpulse(c: AudioContext) {
  if (impulse && impulse.sampleRate === c.sampleRate) return impulse;
  const len = Math.floor(c.sampleRate * 1.6);
  impulse = c.createBuffer(2, len, c.sampleRate);
  for (let ch = 0; ch < 2; ch++) {
    const d = impulse.getChannelData(ch);
    for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.2);
  }
  return impulse;
}

function softClip(amount: number) {
  const n = 1024;
  const curve = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const x = (i / (n - 1)) * 2 - 1;
    curve[i] = Math.tanh(x * amount) / Math.tanh(amount);
  }
  return curve;
}

/**
 * Ultron's voice: a machine speaking through a body of metal.
 * low boost -> light saturation -> ring modulation (robotic edge) ->
 * short metallic comb -> hall reverb. Tuned to stay intelligible.
 */
function ultronChain(c: AudioContext, input: AudioNode) {
  const low = c.createBiquadFilter();
  low.type = "lowshelf";
  low.frequency.value = 160;
  low.gain.value = 5;

  const presence = c.createBiquadFilter();
  presence.type = "peaking";
  presence.frequency.value = 2600;
  presence.Q.value = 0.9;
  presence.gain.value = 3;

  const drive = c.createWaveShaper();
  drive.curve = softClip(1.8);
  drive.oversample = "2x";

  // Ring modulator: carrier multiplies the voice for a metallic buzz.
  const ringOut = c.createGain();
  ringOut.gain.value = 0; // driven entirely by the carrier
  const carrier = c.createOscillator();
  carrier.frequency.value = 42;
  const depth = c.createGain();
  depth.gain.value = 0.22;
  carrier.connect(depth);
  depth.connect(ringOut.gain);
  carrier.start();

  const comb = c.createDelay(0.05);
  comb.delayTime.value = 0.009;
  const fb = c.createGain();
  fb.gain.value = 0.28;

  const verb = c.createConvolver();
  verb.buffer = hallImpulse(c);
  const verbWet = c.createGain();
  verbWet.gain.value = 0.16;

  const dry = c.createGain();
  dry.gain.value = 0.85;
  const ringWet = c.createGain();
  ringWet.gain.value = 0.35;
  const combWet = c.createGain();
  combWet.gain.value = 0.22;

  const out = c.createGain();
  input.connect(low);
  low.connect(presence);
  presence.connect(drive);
  drive.connect(dry);
  drive.connect(ringOut);
  ringOut.connect(ringWet);
  drive.connect(comb);
  comb.connect(fb);
  fb.connect(comb);
  comb.connect(combWet);
  for (const n of [dry, ringWet, combWet]) {
    n.connect(out);
    n.connect(verb);
  }
  verb.connect(verbWet);
  verbWet.connect(out);
  (out as GainNode & { _stop?: () => void })._stop = () => {
    try {
      carrier.stop();
    } catch {
      /* already stopped */
    }
  };
  return out;
}

export async function speak(text: string, h: SpeakHandlers = {}): Promise<void> {
  stopSpeaking();
  if (!text.trim()) return;
  try {
    const res = await fetch(`${API_BASE}/tts`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) throw new Error(`tts ${res.status}`);
    const data = await res.arrayBuffer();
    if (!data.byteLength) return;
    const c = audioCtx();
    const buffer = await c.decodeAudioData(data);
    await playBuffer(c, buffer, h);
  } catch (e) {
    h.onError?.(e instanceof Error ? e.message : String(e));
    await browserSpeak(text, h);
  }
}

function playBuffer(c: AudioContext, buffer: AudioBuffer, h: SpeakHandlers) {
  return new Promise<void>((resolve) => {
    const src = c.createBufferSource();
    src.buffer = buffer;
    const fx = ultronChain(c, src);
    duckGain = c.createGain();
    const analyser = c.createAnalyser();
    analyser.fftSize = 512;
    fx.connect(duckGain);
    duckGain.connect(analyser);
    analyser.connect(c.destination);

    const samples = new Uint8Array(analyser.fftSize);
    let raf = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(samples);
      let sum = 0;
      for (const v of samples) sum += ((v - 128) / 128) ** 2;
      h.onLevel?.(Math.min(1, Math.sqrt(sum / samples.length) * 4));
      raf = requestAnimationFrame(tick);
    };

    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      cancelAnimationFrame(raf);
      h.onLevel?.(0);
      try {
        src.disconnect();
        duckGain?.disconnect();
        (fx as GainNode & { _stop?: () => void })._stop?.();
      } catch {
        /* already gone */
      }
      duckGain = null;
      if (current === handle) current = null;
      resolve();
    };
    const handle = {
      stop: () => {
        try {
          src.stop();
        } catch {
          /* not started */
        }
        finish();
      },
    };
    current = handle;
    src.onended = finish;
    src.start();
    h.onStart?.();
    tick();
  });
}

function browserSpeak(text: string, h: SpeakHandlers) {
  return new Promise<void>((resolve) => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      h.onError?.("no browser voice available");
      return resolve();
    }
    const synth = window.speechSynthesis;
    const u = new SpeechSynthesisUtterance(text.replace(/```[\s\S]*?```/g, " code on screen ").replace(/[`*_#>]/g, ""));
    const voices = synth.getVoices();
    const pick =
      voices.find((v) => /en-(US|GB)/.test(v.lang) && /male|daniel|david|guy|george|christopher/i.test(v.name)) ??
      voices.find((v) => v.lang.startsWith("en"));
    if (pick) u.voice = pick;
    u.pitch = 0.6;
    u.rate = 0.98;
    let pulse = 0;
    const handle = {
      stop: () => {
        synth.cancel();
        end();
      },
    };
    const end = () => {
      clearInterval(pulse);
      h.onLevel?.(0);
      if (current === handle) current = null;
      resolve();
    };
    u.onstart = () => {
      h.onStart?.();
      pulse = window.setInterval(() => h.onLevel?.(0.3 + Math.random() * 0.5), 90);
    };
    u.onend = end;
    u.onerror = end;
    current = handle;
    synth.speak(u);
  });
}

/** Short two-tone chirp: "I'm listening". */
export function chirp() {
  const c = audioCtx();
  const t = c.currentTime;
  const osc = c.createOscillator();
  const g = c.createGain();
  osc.type = "sine";
  osc.frequency.setValueAtTime(660, t);
  osc.frequency.setValueAtTime(990, t + 0.08);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(0.12, t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t + 0.2);
  osc.connect(g);
  g.connect(c.destination);
  osc.start(t);
  osc.stop(t + 0.22);
}

// Theme sound effects, synthesised with WebAudio (no files), off unless the human turns them on (2026-11-03).
// ULTRON: a low thrum and a glitch crackle. JARVIS: a soft two-note chime and a light sweep.

export type SfxTheme = "ultron" | "jarvis";
export type SfxEvent = "reply" | "tool" | "theme" | "ask";

let ctx: AudioContext | null = null;

function audio(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    ctx = ctx ?? new AudioContext();
    if (ctx.state === "suspended") void ctx.resume();
    return ctx;
  } catch {
    return null;
  }
}

function tone(c: AudioContext, type: OscillatorType, freq: number, at: number, dur: number, gain: number, to?: number) {
  const o = c.createOscillator();
  const g = c.createGain();
  o.type = type;
  o.frequency.setValueAtTime(freq, at);
  if (to) o.frequency.exponentialRampToValueAtTime(to, at + dur);
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(gain, at + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  o.connect(g).connect(c.destination);
  o.start(at);
  o.stop(at + dur + 0.05);
}

function noise(c: AudioContext, at: number, dur: number, gain: number, band: number, sweepTo?: number) {
  const buf = c.createBuffer(1, Math.ceil(c.sampleRate * dur), c.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  const src = c.createBufferSource();
  src.buffer = buf;
  const f = c.createBiquadFilter();
  f.type = "bandpass";
  f.frequency.setValueAtTime(band, at);
  if (sweepTo) f.frequency.exponentialRampToValueAtTime(sweepTo, at + dur);
  const g = c.createGain();
  g.gain.setValueAtTime(gain, at);
  g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
  src.connect(f).connect(g).connect(c.destination);
  src.start(at);
}

/** Play the sound of `event` in `theme`. Silent when audio is unavailable. */
export function sfx(theme: SfxTheme, event: SfxEvent): void {
  const c = audio();
  if (!c) return;
  const t = c.currentTime + 0.01;
  if (theme === "ultron") {
    if (event === "reply") {
      tone(c, "sawtooth", 62, t, 0.45, 0.08, 48);
      noise(c, t, 0.12, 0.05, 2400);
    } else if (event === "tool") {
      noise(c, t, 0.05, 0.04, 3200);
    } else if (event === "ask") {
      tone(c, "square", 220, t, 0.18, 0.04);
      tone(c, "square", 220, t + 0.24, 0.18, 0.04);
    } else {
      noise(c, t, 0.6, 0.09, 400, 3000);
      tone(c, "sawtooth", 55, t, 0.6, 0.07, 40);
    }
  } else {
    if (event === "reply") {
      tone(c, "sine", 880, t, 0.35, 0.05);
      tone(c, "sine", 1320, t + 0.09, 0.4, 0.04);
    } else if (event === "tool") {
      tone(c, "sine", 1760, t, 0.08, 0.02);
    } else if (event === "ask") {
      tone(c, "triangle", 660, t, 0.25, 0.05);
      tone(c, "triangle", 990, t + 0.15, 0.3, 0.04);
    } else {
      noise(c, t, 0.7, 0.04, 800, 6000);
      tone(c, "sine", 440, t + 0.1, 0.5, 0.03, 880);
    }
  }
}

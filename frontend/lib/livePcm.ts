/* PCM helpers for live talk: the microphone goes to the server as 16 kHz
 * PCM16 and the answer comes back as 24 kHz PCM16 (little-endian, mono). Pure
 * functions, so they are tested without a browser. */

/** Average each window of input samples down to the target rate. */
export function downsample(input: Float32Array, from: number, to: number): Float32Array {
  if (from === to) return input;
  const ratio = from / to;
  const n = Math.floor(input.length / ratio);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const start = Math.floor(i * ratio);
    const end = Math.min(input.length, Math.floor((i + 1) * ratio));
    let sum = 0;
    for (let j = start; j < end; j++) sum += input[j];
    out[i] = end > start ? sum / (end - start) : input[start];
  }
  return out;
}

/** Float samples (-1..1, clipped) to PCM16 bytes. */
export function floatToPcm16(f: Float32Array): ArrayBuffer {
  const out = new Int16Array(f.length);
  for (let i = 0; i < f.length; i++) {
    const s = Math.max(-1, Math.min(1, f[i]));
    out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
  }
  return out.buffer;
}

/** PCM16 bytes to float samples; a trailing odd byte is ignored. */
export function pcm16ToFloat(buf: ArrayBuffer): Float32Array {
  const pcm = new Int16Array(buf, 0, Math.floor(buf.byteLength / 2));
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) out[i] = pcm[i] / 0x8000;
  return out;
}

/** Loudness 0..1 for the orb. */
export function rms(f: Float32Array): number {
  if (!f.length) return 0;
  let sum = 0;
  for (let i = 0; i < f.length; i++) sum += f[i] * f[i];
  return Math.sqrt(sum / f.length);
}

/** The /live socket next to the /ws one. */
export function liveUrl(wsUrl: string): string {
  return wsUrl.replace(/\/ws\/?(\?.*)?$/, "/live");
}

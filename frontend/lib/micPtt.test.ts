// Push-to-talk (2026-11-26): a held key records through the same MicListener as hands-free. While held the VAD
// does not decide (no utterance fires on a pause); the release hands back the whole held stretch as WAV.
import assert from "node:assert/strict";
import { test } from "node:test";
import { MicListener } from "./mic.ts";

function stubBrowser() {
  const seen = { constraints: null as unknown, port: null as null | { onmessage: ((e: { data: Float32Array }) => void) | null } };
  const stream = { getTracks: () => [{ stop: () => {} }] };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: {
      mediaDevices: {
        getUserMedia: async (c: { audio: unknown }) => {
          seen.constraints = c.audio;
          return stream;
        },
      },
    },
  });
  (globalThis as unknown as Record<string, unknown>).AudioContext = class {
    sampleRate = 48000;
    audioWorklet = { addModule: async () => undefined };
    close = async () => {};
    createMediaStreamSource = () => ({ connect: () => {}, disconnect: () => {} });
  };
  (globalThis as unknown as Record<string, unknown>).AudioWorkletNode = class {
    port = { onmessage: null, close: () => {} };
    disconnect = () => {};
    constructor() {
      seen.port = this.port;
    }
  };
  return seen;
}

/** n blocks of 20 ms at 48 kHz: loud speech or near silence */
function feed(seen: ReturnType<typeof stubBrowser>, n: number, loud: boolean) {
  for (let b = 0; b < n; b++) {
    const frame = new Float32Array(960);
    for (let i = 0; i < frame.length; i++) frame[i] = loud ? 0.3 * Math.sin(i / 5) : 0.0005;
    seen.port?.onmessage?.({ data: frame });
  }
}

test("the chosen microphone's constraints reach getUserMedia", async () => {
  const seen = stubBrowser();
  const mic = new MicListener({ onUtterance: () => {}, constraints: () => ({ deviceId: { ideal: "usb" } }) });
  await mic.start();
  assert.deepEqual(seen.constraints, { deviceId: { ideal: "usb" } });
  mic.stop();
});

test("held: a pause does not end it, the release returns all of it as 16 kHz WAV", async () => {
  const seen = stubBrowser();
  let utterances = 0;
  const states: string[] = [];
  const mic = new MicListener({ onUtterance: () => utterances++, onState: (s) => states.push(s) });
  await mic.start();
  mic.beginManual();
  feed(seen, 20, true);
  feed(seen, 60, false); // 1.2 s of silence would end a hands-free utterance
  feed(seen, 20, true);
  const wav = mic.endManual();
  assert.equal(utterances, 0, "the VAD never fired while held");
  assert.ok(wav);
  assert.equal(wav.type, "audio/wav");
  assert.equal(wav.size, 44 + 100 * 320 * 2, "100 blocks of 20 ms, 320 samples each at 16 kHz");
  assert.deepEqual(states.slice(-2), ["hearing", "idle"]);
  mic.stop();
});

test("a tap is not speech, and a release without a press returns nothing", async () => {
  const seen = stubBrowser();
  const mic = new MicListener({ onUtterance: () => {} });
  await mic.start();
  assert.equal(mic.endManual(), null);
  mic.beginManual();
  feed(seen, 5, true);
  assert.equal(mic.endManual(), null);
  mic.stop();
});

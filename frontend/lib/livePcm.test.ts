import assert from "node:assert/strict";
import { test } from "node:test";
import { downsample, floatToPcm16, liveUrl, pcm16ToFloat, rms } from "./livePcm.ts";

test("48 kHz becomes 16 kHz by averaging each window of three", () => {
  const out = downsample(new Float32Array([0, 0.3, 0.6, 1, 1, 1, -1, -1, -1]), 48000, 16000);
  assert.equal(out.length, 3);
  assert.ok(Math.abs(out[0] - 0.3) < 1e-6 && out[1] === 1 && out[2] === -1);
  const same = new Float32Array([0.5]);
  assert.equal(downsample(same, 16000, 16000), same);
});

test("PCM16 round trip keeps the signal and clips what is too loud", () => {
  const pcm = new Int16Array(floatToPcm16(new Float32Array([0, 1, -1, 2, -2, 0.5])));
  assert.deepEqual([...pcm], [0, 32767, -32768, 32767, -32768, 16384]);
  const back = pcm16ToFloat(pcm.buffer);
  assert.ok(Math.abs(back[1] - 1) < 1e-4 && back[2] === -1 && Math.abs(back[5] - 0.5) < 1e-4);
  assert.equal(pcm16ToFloat(new Uint8Array([0, 64, 7]).buffer).length, 1); // a stray odd byte is ignored
});

test("loudness and the live socket address", () => {
  assert.equal(rms(new Float32Array([])), 0);
  assert.ok(Math.abs(rms(new Float32Array([0.5, -0.5])) - 0.5) < 1e-9);
  assert.equal(liveUrl("ws://127.0.0.1:8765/ws"), "ws://127.0.0.1:8765/live");
  assert.equal(liveUrl("wss://host/ws?probe=1"), "wss://host/live");
});

// Hands-free turned off while MicListener.start() still awaited the mic or the worklet: stop() ran before the stream
// existed, start() went on and wired the mic, and nothing referenced that listener any more, so its utterances kept
// reaching submit (2026-10-27 review). A stop at any await of start() now leaves no track running.
import assert from "node:assert/strict";
import { test } from "node:test";
import { MicListener } from "./mic.ts";

function stubBrowser(waitFor: "mic" | "worklet") {
  const seen = { tracksStopped: 0, connected: 0, states: [] as string[] };
  let release = () => {};
  const pending = new Promise<void>((r) => (release = r));
  const track = { stop: () => seen.tracksStopped++ };
  const stream = { getTracks: () => [track] };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => (waitFor === "mic" ? (await pending, stream) : stream) } },
  });
  (globalThis as unknown as Record<string, unknown>).AudioContext = class {
    sampleRate = 48000;
    audioWorklet = { addModule: async () => (waitFor === "worklet" ? pending : undefined) };
    close = async () => {};
    createMediaStreamSource = () => ({ connect: () => void seen.connected++, disconnect: () => {} });
  };
  (globalThis as unknown as Record<string, unknown>).AudioWorkletNode = class {
    port = { onmessage: null, close: () => {} };
    disconnect = () => {};
  };
  return { seen, release };
}

for (const waitFor of ["mic", "worklet"] as const) {
  test(`a stop while start() awaits the ${waitFor} leaves the mic off`, async () => {
    const { seen, release } = stubBrowser(waitFor);
    const mic = new MicListener({ onState: (s) => seen.states.push(s) });
    const started = mic.start();
    await new Promise((r) => setTimeout(r, 0));
    mic.stop();
    release();
    await started;
    assert.equal(seen.tracksStopped, 1, "the mic track is stopped");
    assert.equal(seen.connected, 0, "the mic is never wired to the listener");
    assert.equal(mic.active, false);
    assert.equal(seen.states.at(-1), "off");
  });
}

test("a start that is not stopped listens", async () => {
  const { seen, release } = stubBrowser("mic");
  const mic = new MicListener({ onState: (s) => seen.states.push(s) });
  const started = mic.start();
  release();
  await started;
  assert.equal(seen.connected, 1);
  assert.equal(seen.tracksStopped, 0);
  assert.equal(mic.active, true);
  assert.deepEqual(seen.states, ["starting", "idle"]);
});

// Live talk stopped while the browser was still asking for the mic: finish() ran before the stream existed, then
// start() went on, opened the mic and the /live socket, and streamed audio with the UI showing "off" (2026-10-27
// review). A stop at any await of start() now releases whatever start() got, and no socket is opened.
import assert from "node:assert/strict";
import { register } from "node:module";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const pcm = pathToFileURL(new URL("./livePcm.ts", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1")).href;
register(
  "data:text/javascript," +
    encodeURIComponent(
      `export async function resolve(s, c, next) { return s === "@/lib/livePcm" ? { url: ${JSON.stringify(pcm)}, shortCircuit: true } : next(s, c); }`,
    ),
);

type Gate = { resolve: () => void; promise: Promise<void> };
function gate(): Gate {
  let resolve = () => {};
  const promise = new Promise<void>((r) => (resolve = r));
  return { resolve, promise };
}

function stubBrowser(waitFor: "mic" | "worklet") {
  const seen = { tracksStopped: 0, sockets: 0, ctxClosed: 0, states: [] as string[] };
  const mic = gate();
  const worklet = gate();
  const track = { stop: () => seen.tracksStopped++ };
  const stream = { getTracks: () => [track] };
  Object.defineProperty(globalThis, "navigator", {
    configurable: true,
    value: { mediaDevices: { getUserMedia: async () => (waitFor === "mic" ? (await mic.promise, stream) : stream) } },
  });
  (globalThis as any).AudioContext = class {
    state = "running";
    sampleRate = 48000;
    audioWorklet = { addModule: async () => (waitFor === "worklet" ? worklet.promise : undefined) };
    resume = async () => {};
    close = async () => void seen.ctxClosed++;
    createMediaStreamSource = () => ({ connect: () => {}, disconnect: () => {} });
  };
  (globalThis as any).AudioWorkletNode = class {
    port = { onmessage: null, close: () => {} };
    disconnect = () => {};
  };
  (globalThis as any).WebSocket = class {
    static OPEN = 1;
    readyState = 0;
    constructor() {
      seen.sockets++;
    }
    close() {}
    send() {}
  };
  return { seen, mic, worklet };
}

for (const waitFor of ["mic", "worklet"] as const) {
  test(`a stop while start() awaits the ${waitFor} leaves no mic and no socket`, async () => {
    const { LiveTalk } = await import("./live.ts");
    const { seen, mic, worklet } = stubBrowser(waitFor);
    const talk = new LiveTalk("ws://x/live", { onState: (s) => seen.states.push(s) });
    const started = talk.start();
    await new Promise((r) => setTimeout(r, 0));
    talk.stop();
    mic.resolve();
    worklet.resolve();
    await started;
    assert.equal(seen.tracksStopped, 1, "the mic track is stopped");
    assert.equal(seen.sockets, 0, "no live socket is opened after the stop");
    assert.equal(seen.ctxClosed, waitFor === "worklet" ? 1 : 0);
    assert.deepEqual(seen.states, ["connecting", "off"]);
  });
}

test("a start that is not stopped still opens the socket", async () => {
  const { LiveTalk } = await import("./live.ts");
  const { seen, mic } = stubBrowser("mic");
  const talk = new LiveTalk("ws://x/live", { onState: (s) => seen.states.push(s) });
  const started = talk.start();
  mic.resolve();
  await started;
  assert.equal(seen.sockets, 1);
  assert.equal(seen.tracksStopped, 0);
});

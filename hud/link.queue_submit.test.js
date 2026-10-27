// A command typed on the HUD while SYRAX works waits its turn. link.ask sent {type: "task"} without queue, so the
// server refused it ("Already executing. Stop it first.", server.py task), while hud.html had already cleared the
// cognition panel and shown THINKING. The web UI sends queue: true (Syrax.tsx submit); the HUD now does too.
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./link.js");

function linked() {
  const sockets = [];
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(m) { this.sent.push(JSON.parse(m)); }
    close() { this.readyState = 3; }
  }
  const link = L.connect({ url: "ws://127.0.0.1:8765/ws", WebSocket: FakeWS, setTimeout: () => 0, clearTimeout: () => {}, now: () => 5 });
  sockets[0].readyState = 1; sockets[0].onopen();
  return { link, ws: sockets[0] };
}

test("link.ask with queue sends queue: true, as server.py task expects for a request that may wait", () => {
  const { link, ws } = linked();
  assert.ok(link.ask("tidy the downloads folder", false, true));
  assert.deepEqual(ws.sent.at(-1), { type: "task", text: "tidy the downloads folder", voice: false, queue: true });
  assert.ok(link.ask("open notepad", true));
  assert.deepEqual(ws.sent.at(-1), { type: "task", text: "open notepad", voice: true }, "without the flag the message is as before");
  link.close();
});

test("isBusy: thinking and acting mean a task runs (a queued command must not wipe its cognition)", () => {
  const s = L.initial();
  assert.equal(L.isBusy(s), false, "offline");
  L.reduce(s, { type: "hello", name: "SYRAX", tools: [], running: null }, 1);
  assert.equal(L.isBusy(s), false, "idle");
  L.reduce(s, { type: "state", state: "thinking", step: 1 }, 2);
  assert.equal(L.isBusy(s), true);
  L.reduce(s, { type: "state", state: "acting", tool: "desktop" }, 3);
  assert.equal(L.isBusy(s), true);
  L.reduce(s, { type: "state", state: "idle" }, 4);
  assert.equal(L.isBusy(s), false);
});

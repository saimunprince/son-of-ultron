import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { SyraxClient, type LinkState } from "./syraxClient.ts";

// The UI's only link to SYRAX: it must come back after every drop, slow down
// while the backend is away, keep the connection alive, and stop for good when
// closed. A fake WebSocket stands in; timers are mocked.
class FakeSocket {
  static OPEN = 1;
  static all: FakeSocket[] = [];
  readyState = 0;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }
  send(data: string) {
    this.sent.push(data);
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
}

function setup() {
  FakeSocket.all = [];
  (globalThis as { WebSocket: unknown }).WebSocket = FakeSocket;
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const links: LinkState[] = [];
  const events: unknown[] = [];
  const client = new SyraxClient("ws://syrax/ws", { onEvent: (e) => events.push(e), onLink: (s) => links.push(s) });
  return { client, links, events };
}

test("it goes online, delivers events and ignores malformed frames", () => {
  const { client, links, events } = setup();
  assert.equal(client.send({ type: "ping" }), false); // nothing is open yet
  client.connect();
  const ws = FakeSocket.all[0];
  ws.open();
  assert.deepEqual(links, ["connecting", "online"]);
  ws.onmessage?.({ data: JSON.stringify({ type: "state", state: "idle" }) });
  ws.onmessage?.({ data: "{not json" });
  assert.deepEqual(events, [{ type: "state", state: "idle" }]);
  assert.equal(client.send({ type: "ping" }), true);
  assert.deepEqual(ws.sent, ['{"type":"ping"}']);
  client.close();
  mock.timers.reset();
});

test("a dropped link comes back, slower each time, and fast again once it is up", () => {
  const { client, links } = setup();
  client.connect();
  FakeSocket.all[0].close(); // backend down
  assert.equal(links.at(-1), "offline");
  const waits: number[] = [];
  for (let i = 0; i < 6; i++) {
    const before = FakeSocket.all.length;
    let waited = 0;
    while (FakeSocket.all.length === before) {
      mock.timers.tick(100);
      waited += 100;
    }
    waits.push(waited);
    FakeSocket.all.at(-1)!.close();
  }
  assert.deepEqual(waits, [800, 1600, 3200, 6400, 12800, 15000]); // doubling, capped at 15 s
  mock.timers.tick(15000);
  FakeSocket.all.at(-1)!.open(); // back up: the next drop retries quickly again
  FakeSocket.all.at(-1)!.close();
  const before = FakeSocket.all.length;
  mock.timers.tick(800);
  assert.equal(FakeSocket.all.length, before + 1);
  client.close();
  mock.timers.reset();
});

test("a ping keeps the link alive, and close stops everything", () => {
  const { client, links } = setup();
  client.connect();
  const ws = FakeSocket.all[0];
  ws.open();
  mock.timers.tick(25000 * 2);
  assert.deepEqual(ws.sent, ['{"type":"ping"}', '{"type":"ping"}']);
  client.close();
  const after = FakeSocket.all.length;
  mock.timers.tick(60000);
  assert.equal(FakeSocket.all.length, after); // no reconnect after close
  assert.equal(ws.sent.length, 2); // and no more pings
  assert.equal(links.at(-1), "offline");
  mock.timers.reset();
});

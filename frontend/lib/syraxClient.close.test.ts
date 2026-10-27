// Closing a client left the socket's onclose attached. A browser fires that event after close() returns, when
// Syrax.tsx has already built the next client (its effect re-runs: close, new client, connect) and that one is
// online: the late event called onLink("offline") and the UI showed the link down while it was up (2026-10-27
// review). close() now detaches the old socket's handlers and reports "offline" itself, once.
import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { SyraxClient, type LinkState } from "./syraxClient.ts";

// a socket whose close event arrives later, as a browser's does
class LateSocket {
  static OPEN = 1;
  static all: LateSocket[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((m: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    LateSocket.all.push(this);
  }
  send() {}
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = LateSocket.OPEN;
    this.onopen?.();
  }
  closedByBrowser() {
    this.onclose?.();
  }
}

test("the old socket's late close does not mark the next client's link offline", () => {
  LateSocket.all = [];
  (globalThis as { WebSocket: unknown }).WebSocket = LateSocket;
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const links: LinkState[] = []; // one React state, as in Syrax.tsx: both clients report into it
  const handlers = { onEvent: () => {}, onLink: (s: LinkState) => links.push(s) };
  const first = new SyraxClient("ws://syrax/ws", handlers);
  first.connect();
  LateSocket.all[0].open();
  first.close();
  assert.equal(links.at(-1), "offline", "close() says the link is down");
  const second = new SyraxClient("ws://syrax/ws", handlers);
  second.connect();
  LateSocket.all[1].open();
  assert.equal(links.at(-1), "online");
  LateSocket.all[0].closedByBrowser(); // the browser delivers the first socket's close now
  assert.equal(links.at(-1), "online", "the new link is still up");
  mock.timers.tick(60000);
  assert.equal(LateSocket.all.length, 2, "the closed client never reconnects");
  second.close();
  mock.timers.reset();
});

test("a client opened again after close() keeps its new socket when the old one closes late", () => {
  LateSocket.all = [];
  (globalThis as { WebSocket: unknown }).WebSocket = LateSocket;
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const links: LinkState[] = [];
  const client = new SyraxClient("ws://syrax/ws", { onEvent: () => {}, onLink: (s) => links.push(s) });
  client.connect();
  LateSocket.all[0].open();
  client.close();
  client.connect();
  LateSocket.all[1].open();
  LateSocket.all[0].closedByBrowser();
  assert.equal(links.at(-1), "online");
  assert.equal(client.send({ type: "ping" }), true, "the new socket is still the one in use");
  client.close();
  mock.timers.reset();
});

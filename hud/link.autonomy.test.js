// AUTONOMY ON/OFF on the HUD follows a switch made on another UI. autonomy.py set_enabled journals
// autonomy.toggled {enabled} -> {type: "autonomy", event: "toggled", enabled, event_id, ts} to every session; only
// the session that flipped it gets a fresh autonomy_status, and link.js had no `autonomy` case, so the HUD row
// (hud.html: AUTONOMY ON/OFF from s.autonomy.enabled) stayed stale.
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./link.js");

test("autonomy.toggled updates s.autonomy.enabled and keeps the rest of the status", () => {
  const s = L.initial();
  L.reduce(s, { type: "hello", name: "SYRAX", tools: [], running: null, autonomy: { enabled: true, running_loop: true, interval_s: 900, cycles: 3 } }, 1);
  const fx = L.reduce(s, { type: "autonomy", event: "toggled", enabled: false, event_id: 41, ts: 1761400000.5 }, 2);
  assert.equal(s.autonomy.enabled, false);
  assert.equal(s.autonomy.cycles, 3);
  assert.deepEqual(fx.filter(f => f.kind === "log").map(f => f.text), ["AUTONOMY OFF"]);
  L.reduce(s, { type: "autonomy", event: "toggled", enabled: true, event_id: 42, ts: 1761400001.5 }, 3);
  assert.equal(s.autonomy.enabled, true);
});

test("a toggle before hello still records the switch; other autonomy events change nothing", () => {
  const s = L.initial();
  L.reduce(s, { type: "autonomy", event: "toggled", enabled: true }, 1);
  assert.deepEqual(s.autonomy, { enabled: true });
  assert.deepEqual(L.reduce(s, { type: "autonomy", event: "other" }, 2), []);
  assert.deepEqual(s.autonomy, { enabled: true });
});

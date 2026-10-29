import assert from "node:assert/strict";
import { test } from "node:test";

import { estopLabel, estopMessage, estopOn, estopTitle } from "./estop.ts";
import type { AutonomyStatus } from "./syraxClient.ts";

const base = { enabled: true, objectives: { OPEN: 0 } } as unknown as AutonomyStatus;

test("off: the button stops everything", () => {
  assert.equal(estopOn(base), false);
  assert.equal(estopLabel(base), "E-STOP");
  assert.deepEqual(estopMessage(base), { type: "estop", on: true, note: "pressed in the HUD" });
  assert.match(estopTitle(null), /survives restarts/);
});

test("on: the button clears it and says since when and why", () => {
  const on = { ...base, estop: { at: 1793180462, note: "smoke test", by: "ws" } } as AutonomyStatus;
  assert.equal(estopOn(on), true);
  assert.equal(estopLabel(on), "E-STOP ON · CLEAR");
  assert.deepEqual(estopMessage(on), { type: "estop", on: false, note: "cleared from the HUD" });
  assert.match(estopTitle(on), /smoke test/);
});

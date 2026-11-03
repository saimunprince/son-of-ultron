import assert from "node:assert/strict";
import { test } from "node:test";

import { FIST_COOLDOWN_MS, HAND_CONNECTIONS, fistFires, isFist, palmCenter, reach, type HandPoint } from "./gestures.ts";

// A hand with the wrist at (0.5, 0.9) and the middle knuckle 0.2 above it; fingertips `tipY` high
function hand(tipY: number): HandPoint[] {
  const lm: HandPoint[] = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.8 }));
  lm[0] = { x: 0.5, y: 0.9 };
  lm[9] = { x: 0.5, y: 0.7 };
  for (const i of [8, 12, 16, 20]) lm[i] = { x: 0.5, y: tipY };
  return lm;
}

const OPEN = hand(0.52); // tips 0.38 from the wrist: 1.9 palms
const FIST = hand(0.72); // 0.18: 0.9 palms
const HALF = hand(0.62); // 0.28: 1.4 palms, between the thresholds

test("an open hand reaches about two palms, a fist under one", () => {
  assert.ok(Math.abs((reach(OPEN) ?? 0) - 1.9) < 1e-9);
  assert.ok(Math.abs((reach(FIST) ?? 0) - 0.9) < 1e-9);
  assert.equal(reach(Array.from({ length: 21 }, () => ({ x: 0, y: 0 }))), null);
});

test("the fist has hysteresis, so it does not flicker at the edge", () => {
  assert.equal(isFist(OPEN, false), false);
  assert.equal(isFist(FIST, false), true);
  assert.equal(isFist(HALF, false), false); // not closed enough to start
  assert.equal(isFist(HALF, true), true); // not open enough to end
  assert.equal(isFist(OPEN, true), false);
});

test("a fist fires once when it closes, and not again within the cooldown", () => {
  assert.equal(fistFires(false, true, 0, 5000), true);
  assert.equal(fistFires(true, true, 0, 5000), false); // held: one burst
  assert.equal(fistFires(false, true, 5000, 5000 + FIST_COOLDOWN_MS - 1), false);
  assert.equal(fistFires(false, false, 0, 5000), false);
});

test("the skeleton covers all 21 points and the palm center is between wrist and knuckle", () => {
  assert.equal(new Set(HAND_CONNECTIONS.flat()).size, 21);
  assert.deepEqual(palmCenter(OPEN), { x: 0.5, y: 0.8 });
});

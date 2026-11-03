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

// ——— poses ———
import { Hold, Swipe, fingersOut, nextPanel, pose, thumbOut } from "./gestures.ts";

/** A right hand, palm to the camera: wrist at (0.5, 0.9), palm 0.2 tall. `out` says which of index..little stretch. */
function shaped(out: [boolean, boolean, boolean, boolean], thumb: "in" | "up" | "down" | "side" = "in"): HandPoint[] {
  const lm: HandPoint[] = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.8 }));
  lm[0] = { x: 0.5, y: 0.9 };
  const xs = [0.44, 0.49, 0.54, 0.59];
  [[5, 6, 8], [9, 10, 12], [13, 14, 16], [17, 18, 20]].forEach(([mcp, pip, tip], f) => {
    lm[mcp] = { x: xs[f], y: 0.7 };
    lm[pip] = { x: xs[f], y: 0.62 };
    lm[pip + 1] = { x: xs[f], y: out[f] ? 0.56 : 0.66 };
    lm[tip] = { x: xs[f], y: out[f] ? 0.5 : 0.72 }; // curled: back down by the palm
  });
  lm[2] = { x: 0.4, y: 0.8 };
  lm[3] = { x: 0.38, y: 0.76 };
  lm[4] = {
    in: { x: 0.45, y: 0.72 },
    up: { x: 0.4, y: 0.4 },
    down: { x: 0.4, y: 1.15 },
    side: { x: 0.15, y: 0.8 },
  }[thumb];
  return lm;
}

test("fingers out, and the thumb", () => {
  assert.deepEqual(fingersOut(shaped([true, false, true, false])), [true, false, true, false]);
  assert.equal(thumbOut(shaped([false, false, false, false])), false);
  assert.equal(thumbOut(shaped([false, false, false, false], "up")), true);
});

test("each pose is told apart", () => {
  assert.equal(pose(shaped([false, false, false, false])), "fist");
  assert.equal(pose(shaped([true, true, true, true])), "open");
  assert.equal(pose(shaped([true, false, false, false])), "point");
  assert.equal(pose(shaped([true, true, false, false])), "two");
  assert.equal(pose(shaped([true, true, true, false])), "three");
  assert.equal(pose(shaped([false, false, false, false], "up")), "thumbs_up");
  assert.equal(pose(shaped([false, false, false, false], "down")), "thumbs_down");
  assert.equal(pose(shaped([false, false, false, false], "side")), "other");
  assert.equal(pose(shaped([false, true, false, true])), "other");
});

test("a hold fires once, after its time, and again only after a change", () => {
  const h = new Hold();
  assert.equal(h.feed("open", 0, 1000), null);
  assert.equal(h.feed("open", 500, 1000), null);
  assert.ok(Math.abs(h.progress(500, 1000) - 0.5) < 1e-9);
  assert.equal(h.feed("open", 1000, 1000), "open");
  assert.equal(h.feed("open", 3000, 1000), null); // still held: no second time
  assert.equal(h.feed(null, 3100, 1000), null);
  assert.equal(h.feed("open", 3200, 1000), null);
  assert.equal(h.feed("open", 4200, 1000), "open");
});

test("a quick sweep is a swipe, a slow drift is not", () => {
  const s = new Swipe();
  assert.equal(s.feed(0.3, 0), null);
  assert.equal(s.feed(0.4, 100), null);
  assert.equal(s.feed(0.6, 200), "right");
  assert.equal(s.feed(0.2, 300), null); // cooldown
  const slow = new Swipe();
  let got = null;
  for (let t = 0, x = 0.2; t <= 3000; t += 100, x += 0.01) got = got ?? slow.feed(x, t);
  assert.equal(got, null);
  const left = new Swipe();
  left.feed(0.7, 0);
  left.feed(0.6, 100);
  assert.equal(left.feed(0.45, 200), "left");
});

test("swipes cycle the panels both ways", () => {
  assert.equal(nextPanel("none", "right"), "brain");
  assert.equal(nextPanel("mind", "right"), "none");
  assert.equal(nextPanel("none", "left"), "mind");
});

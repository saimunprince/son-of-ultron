import assert from "node:assert/strict";
import { test } from "node:test";

import { ease, targetTilt } from "./parallax.ts";

const MAX = (5 * Math.PI) / 180;

test("centre means no tilt", () => {
  assert.deepEqual(targetTilt(0, 0, MAX), { x: 0, y: 0 });
});

test("the orb looks toward the pointer: right turns +y, down tilts +x", () => {
  const r = targetTilt(1, 0, MAX);
  assert.equal(r.y, MAX);
  assert.equal(r.x, 0);
  assert.equal(targetTilt(0, 0.5, MAX).x, MAX / 2);
  assert.equal(targetTilt(-1, -1, MAX).y, -MAX);
});

test("input is clamped to -1..1 and junk is ignored", () => {
  assert.deepEqual(targetTilt(7, -9, MAX), { x: -MAX, y: MAX });
  assert.deepEqual(targetTilt(Number.NaN, Infinity, MAX), { x: 0, y: 0 });
  assert.deepEqual(targetTilt(1, 1, Number.NaN), { x: 0, y: 0 });
});

test("ease glides toward the target and settles exactly", () => {
  assert.equal(ease(0, 1, 0.5), 0.5);
  assert.equal(ease(1, 1, 0.06), 1);
  let v = 0;
  for (let i = 0; i < 400; i++) v = ease(v, MAX, 0.06);
  assert.equal(v, MAX);
  assert.equal(ease(0, 1, 2), 1); // k clamped
  assert.equal(ease(0.3, 1, -1), 0.3);
});

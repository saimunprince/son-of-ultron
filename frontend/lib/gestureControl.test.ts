import assert from "node:assert/strict";
import { test } from "node:test";

import { DWELL_MS, GestureControl, type GestureAction, type HandInfo } from "./gestureControl.ts";
import type { Pose } from "./gestures.ts";

function rig(pick: (x: number, y: number) => unknown = () => null) {
  const acts: GestureAction[] = [];
  const pulses: number[] = [];
  const pulls: unknown[] = [];
  const c = new GestureControl({
    view: () => ({ w: 1000, h: 800 }),
    pick,
    act: (a) => acts.push(a),
    scene: { pulse: (s) => pulses.push(s ?? 1), setAttractor: (a) => pulls.push(a) },
  });
  return { c, acts, pulses, pulls };
}

const hand = (pose: Pose, x = 0.5, y = 0.5, extra: Partial<HandInfo> = {}): HandInfo => ({
  palm: { x, y }, index: { x, y: y - 0.1 }, pose, pinching: false, ...extra,
});

function holdFor(c: GestureControl, hands: HandInfo[], ms: number, from = 0) {
  for (let t = from; t <= from + ms; t += 50) c.frame(hands, t);
}

test("a thumbs up held says yes once; a thumbs down says no", () => {
  const { c, acts } = rig();
  holdFor(c, [hand("thumbs_up")], 2000);
  assert.deepEqual(acts, [{ kind: "yes" }]);
  c.frame([], 2100);
  holdFor(c, [hand("thumbs_down")], 700, 2200);
  assert.deepEqual(acts.at(-1), { kind: "no" });
});

test("a still open palm hushes; a waving one does not", () => {
  const { c, acts } = rig();
  holdFor(c, [hand("open")], 1100);
  assert.deepEqual(acts, [{ kind: "hush" }]);
  const waving = rig();
  for (let t = 0, i = 0; t <= 2000; t += 50, i++) waving.c.frame([hand("open", 0.5 + (i % 2) * 0.03)], t);
  assert.ok(!waving.acts.some((a) => a.kind === "hush"));
});

test("two fingers toggle the mic, three the log; a short flash does nothing", () => {
  const { c, acts } = rig();
  holdFor(c, [hand("two")], 300);
  assert.deepEqual(acts, []);
  holdFor(c, [hand("two")], 1000, 400);
  c.frame([], 1500);
  holdFor(c, [hand("three")], 1000, 1600);
  assert.deepEqual(acts, [{ kind: "mic" }, { kind: "console" }]);
});

test("two fists held two seconds is the E-STOP, one fist is not", () => {
  const one = rig();
  holdFor(one.c, [hand("fist")], 3000);
  assert.deepEqual(one.acts, []);
  const two = rig();
  holdFor(two.c, [hand("fist", 0.3), hand("fist", 0.7)], 1500);
  assert.deepEqual(two.acts, []);
  holdFor(two.c, [hand("fist", 0.3), hand("fist", 0.7)], 600, 1550);
  assert.deepEqual(two.acts, [{ kind: "estop" }]);
});

test("pointing at a button long enough clicks it once", () => {
  const button = { id: "brain" };
  const { c, acts } = rig((x) => (x > 400 ? button : null));
  holdFor(c, [hand("point", 0.2)], 2000); // nothing under the finger
  assert.deepEqual(acts, []);
  holdFor(c, [hand("point", 0.6)], DWELL_MS + 1000, 2100);
  assert.deepEqual(acts, [{ kind: "click", target: button }]);
});

test("a quick sweep of the open hand swipes, and does not also hush", () => {
  const { c, acts } = rig();
  c.frame([hand("open", 0.3)], 0);
  c.frame([hand("open", 0.4)], 100);
  c.frame([hand("open", 0.6)], 200);
  holdFor(c, [hand("open", 0.6)], 500, 250);
  assert.deepEqual(acts, [{ kind: "swipe", dir: "right" }]);
});

test("an open hand is a magnet, and a fast hand stirs the orb", () => {
  const { c, pulses, pulls } = rig();
  c.frame([hand("open", 0.4, 0.5)], 0);
  assert.deepEqual(pulls.at(-1), { x: 0.4, y: 0.5, strength: 0.6 });
  c.frame([hand("fist", 0.5, 0.5)], 50);
  assert.equal(pulls.at(-1), null);
  assert.ok(pulses.length >= 1 && pulses[0] > 0); // the palm jumped 0.1 in one frame
});

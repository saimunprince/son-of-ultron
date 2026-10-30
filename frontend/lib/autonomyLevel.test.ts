import assert from "node:assert/strict";
import { test } from "node:test";

import { levelOf, levelStep, levelTitle } from "./autonomyLevel.ts";
import type { AutonomyStatus } from "./syraxClient.ts";

const at = (level?: number) => ({ enabled: false, level }) as unknown as AutonomyStatus;

test("unset is 5, values are clamped", () => {
  assert.equal(levelOf(null), 5);
  assert.equal(levelOf(at(9)), 5);
  assert.equal(levelOf(at(0)), 1);
});

test("one step at a time, never past the ends", () => {
  assert.deepEqual(levelStep(at(3), -1), { type: "autonomy_level", level: 2 });
  assert.deepEqual(levelStep(at(1), -1), { type: "autonomy_level", level: 1 });
  assert.deepEqual(levelStep(at(5), 1), { type: "autonomy_level", level: 5 });
  assert.match(levelTitle(at(1)), /observe and research/);
});

test("the title carries the suggested level when it differs, and only then", () => {
  const a = { ...at(3), suggested_level: { level: 2, current: 3, reasons: ["own tasks succeeded 8/22 (36%)"] } } as AutonomyStatus;
  assert.match(levelTitle(a), /suggests level 2 \(experiment\): own tasks succeeded 8\/22/);
  const same = { ...at(3), suggested_level: { level: 3, current: 3, reasons: ["keep"] } } as AutonomyStatus;
  assert.doesNotMatch(levelTitle(same), /suggests/);
});

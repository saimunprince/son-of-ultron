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

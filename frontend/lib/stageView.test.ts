import assert from "node:assert/strict";
import { test } from "node:test";

import { stageElements } from "./stageView.ts";
import type { PresentationElement } from "./syraxClient.ts";

const el = (id: string, slot: string | null, priority: number, created: number) =>
  ({ id, slot, priority, created }) as unknown as PresentationElement;

test("the reply card is left out, beside the live log it repeats the answer", () => {
  const out = stageElements([el("r", "reply", 3, 1), el("t", "tool", 2, 2), el("a", "alert", 4, 3)]);
  assert.deepEqual(out.map((e) => e.id), ["a", "t"]);
});

test("the rest keeps priority, then age", () => {
  const out = stageElements([el("x", null, 2, 5), el("y", "tool", 2, 1), el("z", "tool", 5, 9)]);
  assert.deepEqual(out.map((e) => e.id), ["z", "y", "x"]);
});

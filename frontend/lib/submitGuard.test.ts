import assert from "node:assert/strict";
import { test } from "node:test";

import { RESUBMIT_MS, isResubmit } from "./submitGuard.ts";

test("the same text again at once is the same press", () => {
  assert.equal(isResubmit({ text: "open notepad", at: 1000 }, "open notepad", 1000 + 200, false), true);
});

test("after the window, or with other text, it is a new request", () => {
  assert.equal(isResubmit({ text: "open notepad", at: 1000 }, "open notepad", 1000 + RESUBMIT_MS, false), false);
  assert.equal(isResubmit({ text: "open notepad", at: 1000 }, "close notepad", 1100, false), false);
  assert.equal(isResubmit(null, "open notepad", 1100, false), false);
});

test("an answer to SYRAX's question is never held back", () => {
  assert.equal(isResubmit({ text: "yes", at: 1000 }, "yes", 1100, true), false);
});

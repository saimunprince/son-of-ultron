import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createLatencyTracker,
  failoverActive,
  failoverText,
  formatLatency,
  latencyTone,
  shortModel,
} from "./brainChip.ts";

test("model ids lose their vendor path, snapshot date and tags", () => {
  assert.equal(shortModel("models/gemini-2.5-flash-preview-05-20"), "gemini-2.5-flash");
  assert.equal(shortModel("meta-llama/llama-3.3-70b-instruct:free"), "llama-3.3-70b-instruct");
  assert.equal(shortModel("claude-sonnet-4-20250514"), "claude-sonnet-4");
  assert.equal(shortModel("gpt-4o-2024-08-06"), "gpt-4o");
  assert.equal(shortModel("gemini-2.0-flash-latest"), "gemini-2.0-flash");
  assert.equal(shortModel("qwen2.5:7b"), "qwen2.5");
  assert.equal(shortModel(null), "");
  assert.equal(shortModel("a-really-long-model-name-that-goes-on", 12), "a-really-lo…");
});

test("latency reads in ms below a second, seconds above", () => {
  assert.equal(formatLatency(null), "");
  assert.equal(formatLatency(-1), "");
  assert.equal(formatLatency(842.4), "842 ms");
  assert.equal(formatLatency(2_460), "2.4 s");
  assert.equal(formatLatency(14_200), "14 s");
  assert.equal(latencyTone(null), "none");
  assert.equal(latencyTone(900), "fast");
  assert.equal(latencyTone(3000), "ok");
  assert.equal(latencyTone(9000), "slow");
});

test("failover line names both brains and lasts three seconds", () => {
  assert.equal(failoverText("gemini", "Groq"), "GEMINI FAILED → GROQ");
  assert.equal(failoverText("gemini", null), "GEMINI FAILED");
  assert.equal(failoverText("gemini", "gemini"), "GEMINI FAILED");
  assert.equal(failoverActive(null, 10), false);
  assert.equal(failoverActive({ at: 1000 }, 1000), true);
  assert.equal(failoverActive({ at: 1000 }, 3999), true);
  assert.equal(failoverActive({ at: 1000 }, 4000), false);
});

test("tracker measures from the first open mark to the answer", () => {
  let t = 0;
  const tr = createLatencyTracker(() => t);
  assert.equal(tr.answered(), null);
  tr.mark();
  t = 300;
  tr.mark(); // a second mark does not restart the clock
  t = 1250;
  assert.equal(tr.answered(), 1250);
  assert.equal(tr.answered(), null);
  tr.mark(2000);
  tr.reset();
  assert.equal(tr.answered(2500), null);
  tr.mark(5000);
  assert.equal(tr.answered(4000), 0);
});

test("a failover without a provider still reads, it never throws (live 2026-11-04 the page went blank)", () => {
  assert.equal(failoverText(undefined, "groq"), "BRAIN FAILED → GROQ");
  assert.equal(failoverText(null), "BRAIN FAILED");
});

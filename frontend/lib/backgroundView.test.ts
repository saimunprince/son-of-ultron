import assert from "node:assert/strict";
import { test } from "node:test";

import {
  activeCount,
  budgetLine,
  elapsedSeconds,
  formatElapsed,
  isActive,
  sortTasks,
  stateClass,
  stateLabel,
  type BackgroundTask,
} from "./backgroundView.ts";

const task = (over: Partial<BackgroundTask>): BackgroundTask => ({
  id: "bg-1",
  instruction: "research X",
  state: "running",
  step: 3,
  steps: 30,
  minutes: 20,
  elapsed_min: 1.5,
  notes_waiting: 0,
  finishing: false,
  folder: "/tmp/bg-1",
  report: null,
  error: null,
  refused: 0,
  started_at: 100,
  ended_at: null,
  ...over,
});

test("a running task's time keeps counting from when the list came; paused and ended ones do not", () => {
  assert.equal(elapsedSeconds(task({}), 1000, 11000), 100);
  assert.equal(elapsedSeconds(task({ state: "paused" }), 1000, 11000), 90);
  assert.equal(elapsedSeconds(task({ state: "done" }), 1000, 999999), 90);
  assert.equal(elapsedSeconds(task({}), 5000, 1000), 90); // a clock that went back never subtracts
});

test("elapsed and budget read as clock and fractions", () => {
  assert.equal(formatElapsed(0), "0:00");
  assert.equal(formatElapsed(245.9), "4:05");
  assert.equal(formatElapsed(3725), "1:02:05");
  assert.equal(budgetLine(task({}), 245), "3 / 30 steps · 4:05 / 20 min");
});

test("states: labels and row classes", () => {
  assert.equal(stateLabel(task({})), "RUNNING");
  assert.equal(stateLabel(task({ finishing: true })), "WRITING UP");
  assert.equal(stateLabel(task({ state: "paused" })), "PAUSED · BRAINS OUT");
  assert.equal(stateLabel(task({ state: "cancelled" })), "CANCELLED");
  assert.match(stateClass("running"), /active/);
  assert.equal(stateClass("failed"), "status-failed");
  assert.ok(isActive(task({ state: "paused" })) && !isActive(task({ state: "done" })));
});

test("running ones come first, then the newest", () => {
  const items = [
    task({ id: "old-done", state: "done", started_at: 50 }),
    task({ id: "new-done", state: "done", started_at: 300 }),
    task({ id: "run", state: "running", started_at: 10 }),
    task({ id: "paused", state: "paused", started_at: 20 }),
  ];
  assert.deepEqual(sortTasks(items).map((t) => t.id), ["paused", "run", "new-done", "old-done"]);
  assert.equal(activeCount(items), 2);
});

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  TOAST_TEXT_MAX,
  addToast,
  classifyError,
  classifyNotice,
  dismissToast,
  expire,
  makeToast,
  ttlFor,
  type Toast,
} from "./toasts.ts";

const t = (id: number, text = `t${id}`, createdAt = 0): Toast => makeToast(id, { kind: "info", title: "X", text }, createdAt);

test("ttl: 6 s by default, 9 s for errors and alerts", () => {
  assert.equal(ttlFor("reminder"), 6000);
  assert.equal(ttlFor("news"), 6000);
  assert.equal(ttlFor("alert"), 9000);
  assert.equal(ttlFor("error"), 9000);
  assert.deepEqual(makeToast(7, { kind: "error", title: "E", text: "x" }, 100), {
    id: 7,
    kind: "error",
    title: "E",
    text: "x",
    ttlMs: 9000,
    createdAt: 100,
  });
});

test("addToast: newest last, at most 3, oldest dropped, input untouched", () => {
  const start = [t(1), t(2), t(3)];
  const next = addToast(start, t(4));
  assert.deepEqual(
    next.map((x) => x.id),
    [2, 3, 4],
  );
  assert.equal(start.length, 3);
  assert.deepEqual(
    addToast([t(1)], t(2), 1).map((x) => x.id),
    [2],
  );
  assert.deepEqual(addToast([t(1)], t(2), 0), []);
});

test("addToast: the same card again replaces the older copy (no stacked duplicates)", () => {
  const next = addToast([t(1, "same"), t(2, "other")], t(3, "same"));
  assert.deepEqual(
    next.map((x) => x.id),
    [2, 3],
  );
  // same id is replaced too
  assert.deepEqual(
    addToast([t(1, "a")], t(1, "b")).map((x) => x.text),
    ["b"],
  );
});

test("dismissToast and expire", () => {
  const list = [t(1, "a", 0), makeToast(2, { kind: "alert", title: "A", text: "b" }, 0)];
  assert.deepEqual(
    dismissToast(list, 1).map((x) => x.id),
    [2],
  );
  assert.equal(expire(list, 5999).length, 2);
  assert.deepEqual(
    expire(list, 6000).map((x) => x.id),
    [2],
  );
  assert.deepEqual(expire(list, 9000), []);
});

test("classifyNotice: the alerts that deserve a glance", () => {
  assert.deepEqual(classifyNotice("REMINDER · call mum (late by 3 min)"), { kind: "reminder", title: "REMINDER", text: "call mum (late by 3 min)" });
  assert.deepEqual(classifyNotice("CHECK-IN · You have been at it for two hours."), {
    kind: "checkin",
    title: "CHECK-IN",
    text: "You have been at it for two hours.",
  });
  assert.deepEqual(classifyNotice("SYSTEM ALERT · disk 95% full"), { kind: "alert", title: "ALERT", text: "disk 95% full" });
  assert.deepEqual(classifyNotice("OBJECTIVE DONE · #12 · tests green"), { kind: "done", title: "DONE", text: "Objective #12 · tests green" });
  assert.deepEqual(classifyNotice("OBJECTIVE DONE · #12 · "), { kind: "done", title: "DONE", text: "Objective #12" });
  assert.deepEqual(classifyNotice("OBJECTIVE BLOCKED · #4 · needs a key"), { kind: "alert", title: "BLOCKED", text: "Objective #4 · needs a key" });
  assert.deepEqual(classifyNotice("NEWS · rust: 2 new · Rust 2.0 released"), { kind: "news", title: "NEWS", text: "rust: 2 new · Rust 2.0 released" });
  assert.deepEqual(classifyNotice("CAMERA USED · one photo saved to /tmp/a.jpg"), {
    kind: "camera",
    title: "CAMERA",
    text: "Camera used · one photo saved to /tmp/a.jpg",
  });
  assert.deepEqual(classifyNotice("LESSON · read the error before retrying"), { kind: "lesson", title: "LESSON", text: "read the error before retrying" });
  assert.equal(classifyNotice("ROLLED BACK · tests failed · restored 2, removed 1")?.kind, "alert");
  assert.equal(classifyNotice('RECOVERED · "x" was interrupted at step 3 · UNCERTAIN')?.title, "RECOVERED");
  assert.deepEqual(classifyNotice("SKILL BUILT · weather v2 · 4 tests passed · now a tool"), {
    kind: "done",
    title: "SKILL",
    text: "weather v2 · 4 tests passed · now a tool",
  });
  assert.equal(classifyNotice("SKILL FAILED · weather · 1 failing test(s) · not registered")?.kind, "error");
  assert.deepEqual(classifyNotice("PUSHED · main"), { kind: "done", title: "PUSHED", text: "main" });
  assert.deepEqual(classifyNotice("PUSH FAILED · "), { kind: "error", title: "PUSH FAILED", text: "push failed" });
  assert.equal(classifyNotice("COMMIT FAILED · nothing to commit")?.kind, "error");
  assert.equal(classifyNotice("Memory exported (12 facts): /tmp/m.json")?.title, "EXPORTED");
});

test("classifyNotice: autonomy and boot switches read as short sentences", () => {
  assert.deepEqual(classifyNotice("AUTONOMY ON · SYRAX will pursue its own objectives when idle."), {
    kind: "info",
    title: "AUTONOMY",
    text: "On · SYRAX will pursue its own objectives when idle.",
  });
  assert.deepEqual(classifyNotice("AUTONOMY OFF."), { kind: "info", title: "AUTONOMY", text: "Off." });
  assert.deepEqual(classifyNotice("BOOT ON · SYRAX starts with Windows."), { kind: "info", title: "BOOT", text: "On · SYRAX starts with Windows." });
  assert.deepEqual(classifyNotice("BOOT OFF · SYRAX will not start with Windows."), {
    kind: "info",
    title: "BOOT",
    text: "Off · SYRAX will not start with Windows.",
  });
});

test("classifyNotice: benchmark and quality only when they regress", () => {
  assert.equal(classifyNotice("BENCHMARK · PASS"), null);
  assert.deepEqual(classifyNotice("BENCHMARK · REGRESSION · regressed: speed"), { kind: "alert", title: "BENCHMARK", text: "REGRESSION · regressed: speed" });
  assert.equal(classifyNotice("QUALITY · PASS · 92.5% (+1 pp)"), null);
  assert.equal(classifyNotice("QUALITY · REGRESSION · 80% (-12 pp) · failed: a, b")?.title, "QUALITY");
});

test("classifyNotice: progress chatter stays in the log", () => {
  for (const line of [
    'RUNNING · "do x" · step 3',
    'QUEUED · "do y" · position 2',
    "CYCLE · reviewing objectives",
    "CYCLE · RAN · idle",
    "LIVE TALK ON · gemini · the microphone streams to Google until TALK is pressed again",
    "LIVE TALK OFF · closed · 12s, 1 task(s)",
    "OBJECTIVE · P2 · learn rust",
    "RESEARCH · 4 sources · 3 fetched · 2 stored",
    "LEARNED · fact · 90% · water is wet",
    "CODE · edit backend/x.py",
    "COMMITTED · abc1234567 · fix",
    "EXPERIMENT · KEEP · faster",
    "QUALITY RUN · 12 cases",
    "MAINTENANCE · pruned 3 events · trimmed 1 contexts",
    "FAILOVER · GROQ · rate limit",
    "RESUMING interrupted task.",
    "FILE · a.png saved to /tmp/a.png",
    "GESTURE · pinch",
    "some generic status line from the server",
    "",
    "   ",
  ]) {
    assert.equal(classifyNotice(line), null, line);
  }
});

test("classifyNotice: long text is clipped with an ellipsis and whitespace collapsed", () => {
  const out = classifyNotice(`REMINDER · ${"a ".repeat(200)}`);
  assert.ok(out);
  assert.equal(out.text.length, TOAST_TEXT_MAX);
  assert.ok(out.text.endsWith("…"));
  assert.equal(classifyNotice("REMINDER ·   two\n\nlines  ")?.text, "two lines");
  assert.equal(classifyNotice("REMINDER · "), null);
});

test("classifyError: a prefix becomes the label, otherwise ERROR", () => {
  assert.deepEqual(classifyError("VOICE OUTPUT · neural voice failed (x); using browser voice"), {
    kind: "error",
    title: "VOICE OUTPUT",
    text: "neural voice failed (x); using browser voice",
  });
  assert.deepEqual(classifyError("LINK OFFLINE: task was not sent. Start the SYRAX backend."), {
    kind: "error",
    title: "LINK OFFLINE",
    text: "task was not sent. Start the SYRAX backend.",
  });
  assert.deepEqual(classifyError("LINK OFFLINE. Start the SYRAX backend."), { kind: "error", title: "ERROR", text: "LINK OFFLINE. Start the SYRAX backend." });
  assert.deepEqual(classifyError("Brain call failed: timeout"), { kind: "error", title: "ERROR", text: "Brain call failed: timeout" });
  assert.equal(classifyError(""), null);
});

// The live console's decisions about the running task (lib/taskView.ts), on the payloads the backend really sends.
import assert from "node:assert/strict";
import { test } from "node:test";
import { pendingAskFrom, settlesPendingAsk } from "./taskView.ts";
import type { JournalEvent } from "./syraxClient.ts";

// journal.py events(): rows {id, ts, task_id, type, seq, payload}, oldest first; server.py boot sends them as task_events
let seq = 0;
const ev = (type: string, payload: Record<string, unknown> = {}): JournalEvent => ({ id: ++seq, ts: 1761400000 + seq, task_id: "t-1", type, seq, payload });
const STEP = [ev("task.started", { goal: "tidy the downloads folder", kind: "conversation" }), ev("think", { step: 1, content: "I will ask first", tools: [{ name: "ask_human" }] }), ev("tool.started", { name: "ask_human", step: 1 })];

test("a reload while SYRAX waits on a question gets the question back (server.py boot -> task_events)", () => {
  // tools.py:51 {"type": "ask", "question": inquire} journaled as "ask" (core.py _journal_type)
  assert.equal(pendingAskFrom([...STEP, ev("ask", { question: "Delete the old backups too?" })]), "Delete the old backups too?");
  // a permission question rides the same ask tool while another tool waits (agent.py:1521)
  assert.equal(
    pendingAskFrom([ev("tool.started", { name: "desktop" }), ev("permission.refused", { tool: "desktop" }), ev("ask", { question: "Allow desktop once?" }), ev("intent.recorded", {})]),
    "Allow desktop once?",
    "events that do not settle the question leave it waiting",
  );
});

test("an answered, timed-out or ended question is not restored", () => {
  // core.py answer: journal.record("answer", {"text": text, "session_id": ...})
  assert.equal(pendingAskFrom([...STEP, ev("ask", { question: "Which folder?" }), ev("answer", { text: "Downloads" })]), null);
  // tools.py: a timeout returns into the tool's result and the next step thinks
  assert.equal(pendingAskFrom([...STEP, ev("ask", { question: "Which folder?" }), ev("tool.completed", { name: "ask_human", ok: true })]), null);
  assert.equal(pendingAskFrom([...STEP, ev("ask", { question: "Which folder?" }), ev("think", { step: 2 })]), null);
  assert.equal(pendingAskFrom([...STEP, ev("ask", { question: "Which folder?" }), ev("task.cancelled", { error: "aborted by human" })]), null);
  assert.equal(pendingAskFrom([...STEP, ev("ask", { question: "Which folder?" }), ev("final", { text: "Done." })]), null);
  // a second question after the first was answered is the one that waits
  assert.equal(
    pendingAskFrom([...STEP, ev("ask", { question: "Which folder?" }), ev("answer", { text: "Downloads" }), ev("tool.completed", {}), ev("tool.started", { name: "ask_human" }), ev("ask", { question: "And the backups?" })]),
    "And the backups?",
  );
  assert.equal(pendingAskFrom([]), null);
  assert.equal(pendingAskFrom(undefined), null);
});

test("a question that timed out or was answered elsewhere does not take the next command as its answer", () => {
  // agent.py: the next step starts with {"type": "state", "state": "thinking", "step": n}; a timed-out question ends up there too
  assert.equal(settlesPendingAsk("state", { state: "thinking" }), true);
  assert.equal(settlesPendingAsk("state", { state: "idle" }), true);
  // agent.py: tool_start -> {"type": "state", "state": "acting", "tool": name} -> the tool asks: acting comes BEFORE the
  // question, and server.py boot replays it after task_events on a reconnect, so it must keep the question
  assert.equal(settlesPendingAsk("state", { state: "acting" }), false);
  // the HUD answered: core.py answer journals "answer" -> {type: "user", text, session_id, task_id} to every UI
  assert.equal(settlesPendingAsk("user", { task_id: "t-1" }), true);
  // server.py task: {type: "user", text, voice} echoes a new request, no task_id: SYRAX still waits
  assert.equal(settlesPendingAsk("user", {}), false);
  assert.equal(settlesPendingAsk("notice", { task_id: "t-1" }), false);
});

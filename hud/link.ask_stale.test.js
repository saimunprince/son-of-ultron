// A question that no longer waits must not capture the next command. The HUD cleared pendingAsk only on idle
// and final: after a question timed out (tools.py returns "did not answer in time" and the agent goes on) or
// was answered on the web UI, the next command went out as link.answer -> server "No pending question." and
// was lost. Fixtures are the payloads the backend sends.
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("./link.js");

const asking = () => {
  const s = L.initial();
  L.reduce(s, { type: "hello", name: "SYRAX", tools: [], running: { task_id: "t-1", goal: "tidy", step: 1 } }, 1);
  // agent.py: tool_start -> state acting (tool) -> the tool asks (tools.py:51, journaled: task_id rides along)
  L.reduce(s, { type: "tool_start", id: "c1", name: "ask_human", args: { inquire: "Which folder?" }, step: 1 }, 2);
  L.reduce(s, { type: "state", state: "acting", tool: "ask_human" }, 2);
  L.reduce(s, { type: "ask", question: "Which folder?", event_id: 7, ts: 1761400001, task_id: "t-1" }, 3);
  return s;
};

test("the question timed out: the next step clears it, so the next command is a new request", () => {
  const s = asking();
  assert.equal(s.pendingAsk, "Which folder?");
  // tools.py timeout -> tool_result for ask_human, then agent.py the next step: state thinking
  L.reduce(s, { type: "tool_result", id: "c1", name: "ask_human", ok: true, output: "The human did not answer in time.", step: 1 }, 4);
  const fx = L.reduce(s, { type: "state", state: "thinking", step: 2 }, 5);
  assert.equal(s.pendingAsk, null, "hud.html would send the next command as link.answer");
  assert.equal(fx.at(-1).mode, "THINKING");
});

test("answered on the web UI: the journaled answer (type user with task_id) clears it here", () => {
  const s = asking();
  // core.py answer -> journal "answer" -> journal.py _WIRE "user": {type: "user", text, session_id, event_id, ts, task_id}
  const fx = L.reduce(s, { type: "user", text: "Downloads", session_id: "sess-web", event_id: 8, ts: 1761400002, task_id: "t-1" }, 4);
  assert.equal(s.pendingAsk, null);
  assert.equal(s.waiting, null);
  assert.deepEqual(fx, [{ kind: "mode", mode: "THINKING" }], "no longer listening for an answer");
});

test("acting on the asking tool and a new request's echo keep the question", () => {
  const s = asking();
  L.reduce(s, { type: "state", state: "acting", tool: "ask_human" }, 4);  // what server.py boot replays on a reconnect
  L.reduce(s, { type: "user", text: "also tidy downloads", voice: false }, 5);  // server.py task echo: no task_id
  assert.equal(s.pendingAsk, "Which folder?");
  assert.equal(s.waiting, "Which folder?");
});

// HUD truth for the intent ledger (backend/syrax/intent.py): every fixture is the payload the backend REALLY sends,
// copied from the emitting Python line (cited beside it) and shaped on the wire by journal.py Event.wire()
// ("intent.<event>" -> {type: "intent", event, ...payload, event_id, ts, task_id}; "intent" is in journal.py _GROUPED).
// test_intent_ledger.py pins the same shapes on the Python side.
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('./link.js');

const wire = (type, event, payload, extra) => ({ type, event, ...payload, event_id: 9101, ts: 1761408000.5, task_id: 'b7e2d4f1-task', ...(extra || {}) });
const fx = (s, e) => L.reduce(s, e, 1);
const logs = (s, e) => fx(s, e).filter(f => f.kind === 'log').map(f => f.text);

// agent.py _execute_guarded: ledger = intent.entry(name, args, step) -> {tool, args_hash, summary, step}
const ENTRY = { tool: 'notify', args_hash: '8292bd5be3720850', summary: 'notify: the build is green, ship it', step: 1 };

test('intent recorded logs INTENT · <summary>; done logs INTENT DONE or INTENT FAILED (agent.py _execute_guarded)', () => {
  const s = L.initial();
  // agent.py  await self._send({"type": "intent", "event": "recorded", **ledger})
  assert.deepEqual(logs(s, wire('intent', 'recorded', ENTRY)), ['INTENT · NOTIFY: THE BUILD IS GREEN, SHIP IT']);
  // agent.py  await self._send({"type": "intent", "event": "done", "tool": name, "args_hash": ..., "ok": _succeeded(result), "step": ...})
  assert.deepEqual(logs(s, wire('intent', 'done', { tool: 'notify', args_hash: ENTRY.args_hash, ok: true, step: 1 })), ['INTENT DONE · NOTIFY']);
  assert.deepEqual(logs(s, wire('intent', 'done', { tool: 'notify', args_hash: ENTRY.args_hash, ok: false, step: 1 })), ['INTENT FAILED · NOTIFY']);
  assert.equal(s.counters.refused, 0, 'a recorded or done intent is not a refusal');
});

test('a held intent (the same send again, intent.HELD) logs INTENT HELD and its refused tool_result counts no guard refusal', () => {
  const s = L.initial();
  // agent.py  await self._send({"type": "intent", "event": "refused", **ledger, "first_step": held.get("step")})
  const held = wire('intent', 'refused', { ...ENTRY, step: 4, first_step: 2 });
  const out = fx(s, held);
  assert.deepEqual(out.filter(f => f.kind === 'log').map(f => f.text), ['INTENT HELD · NOTIFY · MAY ALREADY HAVE GONE OUT (STEP 2)']);
  assert.deepEqual(out.filter(f => f.kind === 'cog').map(f => f.text), ['⊘ notify: the build is green, ship it · NOT REPEATED']);
  // agent.py execute_tool: the refusal text starts with "Error: refused" so the tool_result carries refused: true
  fx(s, { type: 'tool_result', id: 'c4', name: 'notify', ok: false, refused: true, step: 4, truncated: false, event_id: 9102, ts: 1761408001, task_id: 'b7e2d4f1-task',
    output: 'Error: refused: the same notify action may already have gone out (step 2): check what happened first; do not repeat it blindly. This is final: do not retry it; do the rest or report.' });
  assert.equal(s.counters.refused, 0, 'the guard counter is permission.refused only (replay seeds it from those): a held intent is paired, not counted');
  assert.equal(s.lastRefusal, null);
});

test('an interrupted send says an external action may have happened (core.py _interrupted_summary.intent, journal.py recovery.intent)', () => {
  const s = L.initial();
  // core.py _interrupted_summary -> {..., "recovery_state": "UNCERTAIN", "operation_state": "EXTERNAL_UNCERTAIN", "intent": {tool, args_hash, summary, step}}
  const hello = {
    type: 'hello', name: 'SYRAX', tools: ['notify'], tool_levels: { notify: 'EXTERNAL_WRITE' },
    interrupted: [{ task_id: 'b7e2d4f1-task', goal: 'tell prince the build is green', step: 2, stage: 'tool:notify', tool: 'notify', question: null,
      recovery_state: 'UNCERTAIN', operation_state: 'EXTERNAL_UNCERTAIN', intent: { ...ENTRY, step: 2 }, when: 1761408000.1 }],
    running: null, queue: [], recent: [], presentation: { elements: [] },
  };
  const lines = logs(s, hello);
  assert.ok(lines.includes('INTERRUPTED · TELL PRINCE THE BUILD IS GREEN · UNCERTAIN · NOTIFY EXTERNAL_UNCERTAIN · EXTERNAL ACTION MAY HAVE HAPPENED: NOTIFY: THE BUILD IS GREEN, SHIP IT'), lines);
  // journal.py recover_interrupted task.interrupted {error, goal, step, stage, tool, question, recovery_state, recovery: {state, operation_state, operation, intent, checks, ...}}
  const interrupted = wire('task', 'interrupted', {
    error: 'interrupted at step 2 during tool:notify (operation notify: EXTERNAL_UNCERTAIN)', goal: 'tell prince the build is green', step: 2, stage: 'tool:notify',
    tool: 'notify', question: null, recovery_state: 'UNCERTAIN',
    recovery: { state: 'UNCERTAIN', operation_state: 'EXTERNAL_UNCERTAIN', operation: { id: 'e1', name: 'notify', args: { to: 'prince', text: 'the build is green, ship it' }, step: 2 },
      intent: { ...ENTRY, step: 2 }, checks: { journal_consistent: true, git_head_unchanged: true, workspace_present: true, operation: { level: 'EXTERNAL_WRITE', targets: [], harm: [] } } },
  });
  assert.deepEqual(logs(s, interrupted), ['INTERRUPTED · TELL PRINCE THE BUILD IS GREEN · UNCERTAIN · NOTIFY EXTERNAL_UNCERTAIN · EXTERNAL ACTION MAY HAVE HAPPENED: NOTIFY: THE BUILD IS GREEN, SHIP IT']);
  // a task interrupted in anything else reads exactly as before: `intent` is null (core.py _interrupted_summary, journal.py _recovery_report)
  assert.equal(L.interruptedLine({ goal: 'count lines', recovery_state: 'UNCERTAIN', tool: 'python_execute', operation_state: 'UNCERTAIN', intent: null }),
    'INTERRUPTED · COUNT LINES · UNCERTAIN · PYTHON_EXECUTE UNCERTAIN');
});

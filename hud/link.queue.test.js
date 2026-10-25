// HUD truth for the request queue, the guard's reasons and the question SYRAX waits on. Every fixture is
// the payload the backend REALLY sends, copied from the emitting Python line (cited beside it) and shaped
// on the wire by journal.py Event.wire() (journal.py:267-279: "<group>.<event>" ->
// {type: group, event, ...payload, event_id, ts, task_id}). link.test.js and link.contract.test.js stay as they are.
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('./link.js');

const wire = (type, event, payload, extra) => ({ type, event, ...payload, event_id: 9101, ts: 1761400000.5, ...(extra || {}) });
const of = (fx, kind) => fx.filter(f => f.kind === kind).map(f => f.text);
const logs = (s, e, now) => of(L.reduce(s, e, now || 1), 'log');

// core.py:342-347 queued(): the PENDING tasks oldest first -> {task_id, goal, created, session_id, position}; task_id is journal.py:686 uuid4().hex[:12]
const QUEUE = [
  { task_id: '3f9c1e2ab7d4', goal: 'tidy the downloads folder', created: 1761400000.1, session_id: 'sess-hud', position: 1 },
  { task_id: '8d2e3f4a5b6c', goal: 'open notepad and write the plan', created: 1761400030.2, session_id: 'sess-web', position: 2 },
];
// server.py:388-400 hello {name, tools, tool_levels, interrupted, running, queue, recent, autonomy, startup, voice, presentation, presence};
// queue is snap["queue"] (core.py:730) and running is the core.py snapshot's {task_id, goal, step, stage, status, phase, kind}
const hello = (queue, running) => ({
  type: 'hello', name: 'SYRAX', tools: ['desktop', 'disk_usage', 'release'], tool_levels: { desktop: 'SYSTEM', disk_usage: 'READ_ONLY', release: 'WRITE' },
  interrupted: [], running: running || null, queue, recent: [],
  autonomy: { enabled: true, running_loop: true, interval_s: 900, last_cycle: null, cycles: 3, objectives: {}, resources: {}, pressure: null, last_maintenance: null },
  presentation: { slots: [] }, presence: { visibility: 'visible' },
});
const RUNNING = { task_id: 'a1b2c3d4e5f6', goal: 'Memory expiry for inferences', step: 2, stage: 'act', status: 'IN_PROGRESS', phase: 'act', kind: 'conversation' };

test('hello.queue: two waiting requests give the TASK row a QUEUE 2 suffix and one QUEUED line each (server.py:396, core.py:342-347)', () => {
  const s = L.initial();
  assert.deepEqual(s.queue, []);
  assert.equal(L.taskRow(s), '—', 'no task, no queue: the row is as it was');
  const fx = L.reduce(s, hello(QUEUE, RUNNING), 1);
  assert.deepEqual(s.queue, QUEUE);
  assert.deepEqual(of(fx, 'log'), [
    'SYRAX LINK ESTABLISHED · 3 TOOLS',
    'QUEUED · TIDY THE DOWNLOADS FOLDER · POSITION 1',
    'QUEUED · OPEN NOTEPAD AND WRITE THE PLAN · POSITION 2',
  ]);
  assert.equal(fx.at(-1).mode, 'THINKING');
  assert.equal(L.taskRow(s), 'MEMORY EXPIRY FOR INFERENC · QUEUE 2', 'the goal keeps its 26 characters (hud.html), then the queue');
  s.task = null;  // between tasks the row still says what waits
  assert.equal(L.taskRow(s), '— · QUEUE 2');
  assert.equal(L.queuedLine(QUEUE[0].goal, QUEUE[0].position), 'QUEUED · TIDY THE DOWNLOADS FOLDER · POSITION 1');
});

test('a `queue` event replaces the list; [] clears the suffix without a log line (core.py:338, core.py:355, core.py:370)', () => {
  const s = L.initial();
  L.reduce(s, hello(QUEUE), 1);
  assert.equal(L.taskRow(s), '— · QUEUE 2');
  // core.py:370  await self.broadcast({"type": "queue", "items": self.queued()})  once _start_next began the oldest one
  assert.deepEqual(L.reduce(s, { type: 'queue', items: [{ ...QUEUE[1], position: 1 }] }, 2), [], 'a queue change is state, not a log line');
  assert.equal(s.queue.length, 1);
  assert.equal(L.taskRow(s), '— · QUEUE 1');
  // core.py:355  cancel_queued -> await self.broadcast({"type": "queue", "items": self.queued()})  with nothing left
  L.reduce(s, { type: 'queue', items: [] }, 3);
  assert.deepEqual(s.queue, []);
  assert.equal(L.taskRow(s), '—', 'an empty queue leaves the row as it was');
  L.reduce(s, wire('task', 'started', { goal: 'hi', kind: 'conversation' }, { task_id: 'c0ffee000009' }), 4);
  assert.equal(L.taskRow(s), 'HI');
  L.offline(s, 5, '');
  assert.deepEqual(s.queue, [], 'offline, nothing is known to wait; hello refills it');
});

test('task.queued logs the request with its position; the notices around it read as they are sent (journal.py:706, server.py:453, core.py:368)', () => {
  const s = L.initial();
  L.reduce(s, hello([], { ...RUNNING, goal: 'first' }), 1);
  // journal.py:706-707  type_ = "task.queued" if pending else "task.started"; self._insert_event(cur, ts, task_id, type_, {"goal": goal, "kind": kind})
  assert.deepEqual(logs(s, wire('task', 'queued', { goal: 'tidy the downloads folder', kind: 'conversation' }, { task_id: '3f9c1e2ab7d4' })), ['QUEUED · TIDY THE DOWNLOADS FOLDER · POSITION 1']);
  assert.equal(s.task.goal, 'first', 'a queued request is not the running task');
  // core.py:338  await self.broadcast({"type": "queue", "items": self.queued()})  right after start_task(pending=True)
  L.reduce(s, { type: 'queue', items: [QUEUE[0]] }, 2);
  assert.equal(L.taskRow(s), 'FIRST · QUEUE 1');
  // the next one lands behind the queue the HUD knows
  assert.deepEqual(logs(s, wire('task', 'queued', { goal: 'open notepad and write the plan', kind: 'conversation' }, { task_id: '8d2e3f4a5b6c' })), ['QUEUED · OPEN NOTEPAD AND WRITE THE PLAN · POSITION 2']);
  // a goal is cut at 40 like the other lines
  assert.deepEqual(logs(s, wire('task', 'queued', { goal: 'what is the weather in Dhaka tomorrow morning please', kind: 'conversation' }, { task_id: 'c0ffee000001' })),
    ['QUEUED · WHAT IS THE WEATHER IN DHAKA TOMORROW M… · POSITION 2']);
  // server.py:453-454  self.send({"type": "notice", "text": f"Queued (position {waiting['position']}): it runs when the current task ends.",
  //                               "action": {"label": "REMOVE", "msg": {"type": "queue_cancel", "task_id": started}}})
  assert.deepEqual(logs(s, { type: 'notice', text: 'Queued (position 1): it runs when the current task ends.', action: { label: 'REMOVE', msg: { type: 'queue_cancel', task_id: '3f9c1e2ab7d4' } } }),
    ['QUEUED (POSITION 1): IT RUNS WHEN THE CURRENT TASK ENDS.']);
  // core.py:368  await self.broadcast({"type": "notice", "text": f"Queued request starting: {str(said or goal)[:80]}"})
  assert.deepEqual(logs(s, { type: 'notice', text: 'Queued request starting: tidy the downloads folder' }), ['QUEUED REQUEST STARTING: TIDY THE DOWNLOADS FOLDER']);
  // core.py:353  journal.record("task.cancelled", {"error": f"removed from the queue: {note}"}, task_id=task_id)  (note: server.py:458 "removed by human")
  assert.deepEqual(logs(s, wire('task', 'cancelled', { error: 'removed from the queue: removed by human' }, { task_id: '8d2e3f4a5b6c' })), ['TASK ABORTED · REMOVED FROM THE QUEUE: REMOVED BY HUMAN']);
});

test('guard refused: the verdict is the log line, the reason and first target are the cognition line (agent.py:657-664)', () => {
  const s = L.initial();
  // agent.py:658-659  payload = {"type": "permission", "event": event, "tool": name, "level": decision.level, "task_kind": self.task_kind,
  //                    "reason": verdict.reason, "targets": decision.targets[:6], "authorized_by": authorized_by, "step": self.current_step}
  const refused = wire('permission', 'refused', {
    tool: 'desktop', level: 'DESTRUCTIVE', task_kind: 'autonomous', reason: 'autonomous work may not run DESTRUCTIVE calls',
    targets: ['C:\\Users\\prince\\Documents', 'C:\\Users\\prince\\Pictures'], authorized_by: null, step: 3,
  }, { task_id: 't-1' });
  const fx = L.reduce(s, refused, 1);
  assert.deepEqual(of(fx, 'log'), ['GUARD REFUSED DESKTOP · DESTRUCTIVE'], 'the line link.contract.test.js pins');
  assert.deepEqual(of(fx, 'cog'), ['⊘ GUARD · autonomous work may not run DESTRUCTIVE calls · C:\\Users\\prince\\Documents']);
  assert.equal(L.permissionLine(refused), 'GUARD REFUSED DESKTOP · DESTRUCTIVE');
  assert.equal(L.permissionDetail(refused), 'GUARD · autonomous work may not run DESTRUCTIVE calls · C:\\Users\\prince\\Documents');
  assert.equal(s.counters.refused, 1);
  // agent.py:619-630  the refused tool_result of the same call counts once with it
  L.reduce(s, { type: 'tool_result', id: 'call_01', name: 'desktop', ok: false, output: 'Error: refused: autonomous work may not run DESTRUCTIVE calls. This is final: do not retry it; do the rest or report.', truncated: false, step: 3, refused: true, event_id: 9102, ts: 1761400000.6, task_id: 't-1' }, 2);
  assert.equal(s.counters.refused, 1);
  // a long reason and target are cut at 60 and 40
  const long = L.permissionDetail({ event: 'refused', tool: 'python_execute', reason: 'x'.repeat(70), targets: ['y'.repeat(50)] });
  assert.equal(long, 'GUARD · ' + 'x'.repeat(59) + '… · ' + 'y'.repeat(39) + '…');
  // no reason, no target (the shape link.test.js uses): nothing is invented for the cognition panel
  assert.deepEqual(of(L.reduce(s, { type: 'permission', event: 'refused', tool: 'python_execute', level: 'DESTRUCTIVE' }, 3), 'cog'), []);
});

test('a host-harm refusal says HOST HARM first (agent.py:660-661, permissions.py:99, permissions.py:342)', () => {
  const s = L.initial();
  // permissions.py:341-342  if decision.harm: return Verdict("refuse", None, f"the code {'; '.join(decision.harm)}; SYRAX must not harm the host")
  // agent.py:660-661  if decision.harm: payload["harm"] = decision.harm   (Decision.harm: List[str], permissions.py:99)
  const harm = wire('permission', 'refused', {
    tool: 'python_execute', level: 'DESTRUCTIVE', task_kind: 'conversation', reason: 'the code kills processes; SYRAX must not harm the host',
    targets: [], authorized_by: null, step: 2, harm: ['kills processes'],
  }, { task_id: 't-2' });
  const fx = L.reduce(s, harm, 1);
  assert.deepEqual(of(fx, 'log'), ['GUARD REFUSED PYTHON_EXECUTE · DESTRUCTIVE']);
  assert.deepEqual(of(fx, 'cog'), ['⊘ HOST HARM · the code kills processes; SYRAX must not harm the host']);
  assert.match(L.permissionDetail(harm), /^HOST HARM · /);
  assert.equal(s.counters.refused, 1);
});

test('authorized by the human names the target; by the goal it reads as before (agent.py:664, agent.py:668, permissions.py:367-376)', () => {
  const s = L.initial();
  // agent.py:662-664  payload["answer"] = answer[:120]; await tell("authorized" if ok else "refused", "human" if ok else None, answer)
  // the verdict that led to the question: permissions.py:376  Verdict("ask", None, f"{decision.reason} ({level}) was not named in the request")
  const human = wire('permission', 'authorized', {
    tool: 'desktop', level: 'DESTRUCTIVE', task_kind: 'conversation', reason: 'deletes files (DESTRUCTIVE) was not named in the request',
    targets: ['C:\\Users\\prince\\Documents'], authorized_by: 'human', step: 4, answer: 'yes',
  }, { task_id: 't-3' });
  assert.deepEqual(logs(s, human), ['AUTHORIZED DESKTOP BY HUMAN · C:\\Users\\prince\\Documents']);
  assert.equal(L.permissionLine(human), 'AUTHORIZED DESKTOP BY HUMAN · C:\\Users\\prince\\Documents');
  // agent.py:667-668  if verdict.authorized_by in ("goal", "human"): await tell("authorized", verdict.authorized_by)
  // permissions.py:367  Verdict("allow", "goal", "the request names this action and target"): no targets on a release, no suffix (as link.contract.test.js pins)
  assert.deepEqual(logs(s, wire('permission', 'authorized', { tool: 'release', level: 'WRITE', task_kind: 'conversation', reason: 'the request names this action and target', targets: [], authorized_by: 'goal', step: 6 }, { task_id: 't-3' })),
    ['AUTHORIZED RELEASE BY GOAL']);
  assert.equal(s.counters.refused, 0);
});

test('ask: WAITING FOR YOU carries the question and s.waiting; final clears it (tools.py:51, core.py:74, permissions.py:291-294)', () => {
  const s = L.initial();
  L.reduce(s, hello([]), 1);
  // permissions.py:291-294 question(decision); tools.py:51  await self.emit({"type": "ask", "question": inquire});
  // core.py:74 journals "ask", so event_id/ts/task_id ride along on the wire
  const q = 'Permission: `desktop` would delete files -> C:\\Users\\prince\\Documents. Your request did not name it. Answer yes to allow exactly this once; anything else refuses it.';
  const fx = L.reduce(s, { type: 'ask', question: q, event_id: 9103, ts: 1761400001.0, task_id: 't-1' }, 2);
  assert.deepEqual(fx.map(f => f.kind), ['mode', 'log', 'ask'], 'one log line; hud.html speaks the question from the ask effect, not from the log');
  assert.equal(fx[1].text, 'WAITING FOR YOU · PERMISSION: `DESKTOP` WOULD DELETE FILES -> C:\\USERS\\PRINCE…');
  assert.equal(fx[1].text, 'WAITING FOR YOU · ' + L.short(q, 60).toUpperCase());
  assert.equal(fx[2].question, q, 'the spoken question is whole');
  assert.equal(s.waiting, q);
  assert.equal(s.pendingAsk, q);
  const fin = L.reduce(s, { type: 'final', text: 'Done.', event_id: 9104, ts: 1761400002.0, task_id: 't-1' }, 3);
  assert.deepEqual(fin, [{ kind: 'say', text: 'Done.' }]);
  assert.equal(s.waiting, null);
  assert.equal(s.pendingAsk, null);
});

test('the answer, the next step, idle and the link going down clear s.waiting; a new request does not (journal.py:249, agent.py:548, core.py:529)', () => {
  const s = L.initial();
  L.reduce(s, { type: 'ask', question: 'Delete the folder too?', event_id: 1, ts: 1761400001.0, task_id: 't-1' }, 1);
  assert.equal(s.waiting, 'Delete the folder too?');
  // core.py:623-625  journal.record("answer", {"text": text, "session_id": session_id}, task_id=self.current.task_id)
  //   -> journal.py:249 _WIRE {"answer": "user"} -> {type: "user", text, session_id, event_id, ts, task_id}
  L.reduce(s, { type: 'user', text: 'yes', session_id: 'sess-hud', event_id: 2, ts: 1761400003.0, task_id: 't-1' }, 2);
  assert.equal(s.waiting, null);
  L.reduce(s, { type: 'ask', question: 'And the backups?', event_id: 3, ts: 1761400004.0, task_id: 't-1' }, 3);
  // server.py:440  await self.core.broadcast({"type": "user", "text": text, "voice": bool(msg.get("voice"))}): a request that will queue, not an answer
  L.reduce(s, { type: 'user', text: 'also tidy downloads', voice: false }, 4);
  assert.equal(s.waiting, 'And the backups?', 'SYRAX still waits');
  // agent.py:548  {"type": "state", "state": "thinking", "step": self.current_step}: the next step means the question was answered
  L.reduce(s, { type: 'state', state: 'thinking', step: 5 }, 5);
  assert.equal(s.waiting, null);
  L.reduce(s, { type: 'ask', question: 'Really?', event_id: 4, ts: 1761400005.0, task_id: 't-1' }, 6);
  L.reduce(s, { type: 'answer', text: 'yes' }, 7);  // no such wire type today (an answer comes back as `user`); harmless if one appears
  assert.equal(s.waiting, null);
  L.reduce(s, { type: 'ask', question: 'Once more?', event_id: 5, ts: 1761400006.0, task_id: 't-1' }, 8);
  L.reduce(s, { type: 'state', state: 'idle' }, 9);  // core.py:529  await self.broadcast({"type": "state", "state": "idle"})
  assert.equal(s.waiting, null);
  L.reduce(s, { type: 'ask', question: 'Still there?', event_id: 6, ts: 1761400007.0, task_id: 't-1' }, 10);
  L.offline(s, 11, '');
  assert.equal(s.waiting, null);
});

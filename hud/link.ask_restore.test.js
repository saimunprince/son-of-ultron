// A question SYRAX waits on survives a HUD reconnect. The hello snapshot carries no pending question; it is
// only in the task_events replay server.py boot sends while a task runs (server.py:430-435), which the HUD
// dropped, so after a reconnect the typed answer went out as a new task ("Already executing").
// Fixtures are the payloads the backend sends: journal.py events() rows {id, ts, task_id, type, seq, payload}.
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('./link.js');

const RUNNING = { task_id: 'a1b2c3d4e5f6', goal: 'tidy the downloads folder', step: 2, stage: 'asking', status: 'BLOCKED', phase: 'act', kind: 'conversation' };
const hello = running => ({ type: 'hello', name: 'SYRAX', tools: ['desktop'], tool_levels: {}, interrupted: [], running, queue: [], recent: [], autonomy: { enabled: false }, presentation: { slots: [] }, presence: { visibility: 'visible' } });
let seq = 0;
const row = (type, payload, task_id) => ({ id: ++seq, ts: 1761400000 + seq, task_id: task_id || RUNNING.task_id, type, seq, payload: payload || {} });
const asked = q => [row('task.started', { goal: RUNNING.goal, kind: 'conversation' }), row('tool.started', { name: 'ask_human', step: 2 }), row('ask', { question: q })];

test('reconnect while SYRAX waits: task_events gives the question back, then the next command is its answer', () => {
  const s = L.initial();
  L.reduce(s, hello(RUNNING), 1);
  const fx = L.reduce(s, { type: 'task_events', task_id: RUNNING.task_id, events: asked('Delete the old backups too?') }, 2);
  assert.equal(s.pendingAsk, 'Delete the old backups too?', 'hud.html sends the next command as link.answer');
  assert.equal(s.waiting, 'Delete the old backups too?');
  assert.deepEqual(fx.map(f => f.kind), ['mode', 'log', 'ask']);
  assert.equal(fx[0].mode, 'LISTENING');
  assert.equal(fx[1].text, 'WAITING FOR YOU · DELETE THE OLD BACKUPS TOO?');
  // server.py:435 then sends the live state: SYRAX is still in the ask_human tool
  const st = L.reduce(s, { type: 'state', state: 'acting', tool: 'ask_human' }, 3);
  assert.equal(s.pendingAsk, 'Delete the old backups too?');
  assert.equal(st.at(-1).mode, 'LISTENING');
  // the same replay again (another reconnect) does not repeat the question
  assert.deepEqual(L.reduce(s, { type: 'task_events', task_id: RUNNING.task_id, events: asked('Delete the old backups too?') }, 4).filter(f => f.kind === 'ask'), []);
});

test("an answered question, another task's events or no running task restore nothing", () => {
  const s = L.initial();
  L.reduce(s, hello(RUNNING), 1);
  L.reduce(s, { type: 'task_events', task_id: RUNNING.task_id, events: [...asked('Which folder?'), row('answer', { text: 'Downloads' })] }, 2);
  assert.equal(s.pendingAsk, null);
  L.reduce(s, { type: 'task_events', task_id: 'ffffffffffff', events: asked('Old question?').map(r => ({ ...r, task_id: 'ffffffffffff' })) }, 3);
  assert.equal(s.pendingAsk, null, "a history view asking for another task's events is not the running task");
  const idle = L.initial();
  L.reduce(idle, hello(null), 1);
  L.reduce(idle, { type: 'task_events', task_id: RUNNING.task_id, events: asked('Which folder?') }, 2);
  assert.equal(idle.pendingAsk, null);
});

test('pendingAskFrom: a question that timed out or whose task ended no longer waits', () => {
  assert.equal(L.pendingAskFrom([...asked('Which folder?'), row('tool.completed', { name: 'ask_human', ok: true })]), null);
  assert.equal(L.pendingAskFrom([...asked('Which folder?'), row('task.cancelled', { error: 'aborted by human' })]), null);
  assert.equal(L.pendingAskFrom([...asked('Which folder?'), row('permission.authorized', {})]), 'Which folder?');
  assert.equal(L.pendingAskFrom(null), null);
});

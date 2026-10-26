// HUD truth for an uncertain intent (backend/syrax/intent.py uncertain, agent.py _execute_guarded): a send that timed out
// or lost its connection while it ran may have gone out; the backend journals intent.uncertain and keeps the entry open.
// The fixture is the payload the backend really sends (test_intent_timeout.py pins it on the Python side).
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('./link.js');

const wire = (type, event, payload) => ({ type, event, ...payload, event_id: 9201, ts: 1761408100.5, task_id: 'c8f3e5a2-task' });
const logs = (s, e) => L.reduce(s, e, 1).filter(f => f.kind === 'log').map(f => f.text);

// agent.py  await self._send({"type": "intent", "event": "uncertain", **ledger, "why": why, "step": self.current_step})
const ENTRY = { tool: 'notify', args_hash: '8292bd5be3720850', summary: 'notify: the build is green, ship it', step: 1 };

test('an uncertain intent logs INTENT UNCERTAIN with why and that it may have gone out', () => {
  const s = L.initial();
  assert.deepEqual(logs(s, wire('intent', 'uncertain', { ...ENTRY, why: 'timed out' })), ['INTENT UNCERTAIN · NOTIFY · TIMED OUT · MAY HAVE GONE OUT']);
  assert.deepEqual(logs(s, wire('intent', 'uncertain', { ...ENTRY, why: 'connection lost' })), ['INTENT UNCERTAIN · NOTIFY · CONNECTION LOST · MAY HAVE GONE OUT']);
  assert.equal(s.counters.refused, 0, 'an uncertain intent is not a guard refusal');
});

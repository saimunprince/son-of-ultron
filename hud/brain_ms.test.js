// Every answered brain event carries how long the answer took (SYRAX's own change 09e97df);
// the HUD keeps the last one, so the BRAIN row shows the brain and its latency live.
const test = require('node:test');
const assert = require('node:assert');
const L = require('./link.js');

test('the last answer time is kept, and an event without one changes nothing', () => {
  const s = L.initial();
  assert.equal(s.brain.ms, null);
  L.reduce(s, { type: 'brain', event: 'answered', provider: 'gemini', model: 'gemini-3.5-flash-lite', ms: 1234 }, 1);
  assert.equal(s.brain.ms, 1234);
  assert.equal(s.brain.model, 'gemini-3.5-flash-lite');
  L.reduce(s, { type: 'brain', event: 'answered', provider: 'upstage', model: 'solar-pro' }, 2);
  assert.equal(s.brain.ms, 1234);
  L.reduce(s, { type: 'brain', event: 'failover', provider: 'gemini', reason: 'rate limited' }, 3);
  assert.equal(s.brain.ms, 1234);
});

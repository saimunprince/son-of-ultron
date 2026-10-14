// The HUD shows SYRAX's real state: every panel line is derived from a backend event.
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('./link.js');

const kinds = fx => fx.map(f => f.kind);

test('hello brings the link up and a running task shows as thinking', () => {
  const s = L.initial();
  assert.equal(s.state, 'offline');
  const fx = L.reduce(s, { type: 'hello', name: 'SYRAX', tools: ['desktop', 'release'], tool_levels: { release: 'WRITE' }, running: null, autonomy: { enabled: true } }, 1000);
  assert.equal(s.online, true);
  assert.equal(s.tools.length, 2);
  assert.deepEqual(kinds(fx), ['log', 'mode']);
  assert.equal(fx[1].mode, 'IDLE');
  const r = L.initial();
  const fx2 = L.reduce(r, { type: 'hello', running: { task_id: 'abc', goal: 'tidy', step: 3, phase: 'act' } }, 1000);
  assert.equal(r.task.goal, 'tidy');
  assert.equal(r.phase, 'act');
  assert.equal(fx2.find(f => f.kind === 'mode').mode, 'THINKING');
});

test('identity comes from the self-model, the brain from the router', () => {
  const s = L.initial();
  L.reduce(s, { type: 'self_model', section: 'identity', version: '2f36947', boot_id: 'b-1', process_uptime_s: 61, restart_pending: true }, 1);
  assert.equal(s.version, '2f36947');
  assert.equal(s.bootId, 'b-1');
  assert.equal(s.restartPending, true);
  L.reduce(s, { type: 'brains', active: 'gemini', providers: [{ id: 'gemini', model: 'gemini-2.5-flash', status: 'ready' }, { id: 'groq', model: 'llama', status: 'cooldown' }] }, 1);
  assert.equal(s.brain.model, 'gemini-2.5-flash');
  assert.equal(s.brain.ready, 1);
  assert.equal(s.brain.total, 2);
  L.reduce(s, { type: 'brain', event: 'answered', model: 'gemini-3-flash-preview' }, 1);
  assert.equal(s.brain.model, 'gemini-3-flash-preview');
});

test('a task streams real cognition: thoughts with tools, tool calls, results and refusals', () => {
  const s = L.initial();
  L.reduce(s, { type: 'hello', tools: [] }, 1);
  const fx = [];
  fx.push(...L.reduce(s, { type: 'state', state: 'thinking', step: 1 }, 2));
  fx.push(...L.reduce(s, { type: 'think', step: 1, content: 'I will read the file first', tools: ['str_replace_editor'] }, 3));
  fx.push(...L.reduce(s, { type: 'think', step: 1, content: 'Done.', tools: [] }, 3)); // no tools: that is the reply, "final" carries it
  fx.push(...L.reduce(s, { type: 'tool_start', name: 'str_replace_editor', args: { command: 'view', path: 'C:/x/a.py' }, step: 1 }, 4));
  fx.push(...L.reduce(s, { type: 'state', state: 'acting', tool: 'str_replace_editor' }, 4));
  fx.push(...L.reduce(s, { type: 'tool_result', name: 'str_replace_editor', ok: true, output: '...' }, 5));
  fx.push(...L.reduce(s, { type: 'tool_start', name: 'desktop', args: { action: 'launch_app' } }, 6));
  fx.push(...L.reduce(s, { type: 'tool_result', name: 'desktop', ok: false, refused: true, output: 'Error: refused: ...' }, 7));
  fx.push(...L.reduce(s, { type: 'phase', phase: 'verify' }, 8));
  const cog = fx.filter(f => f.kind === 'cog').map(f => f.text);
  assert.deepEqual(cog, ['STEP 1 · I will read the file first', '▶ str_replace_editor · view', '✓ str_replace_editor', '▶ desktop · launch_app', '⊘ desktop REFUSED', 'PHASE VERIFY']);
  assert.equal(s.counters.toolsOk, 1);
  assert.equal(s.counters.refused, 1);
  assert.equal(s.phase, 'verify');
  assert.ok(fx.filter(f => f.kind === 'mode').every(f => f.mode === 'THINKING'));
});

test('the final reply is spoken and a question puts the HUD in listening', () => {
  const s = L.initial();
  L.reduce(s, { type: 'hello', tools: [] }, 1);
  const ask = L.reduce(s, { type: 'ask', question: 'Delete the folder too?' }, 2);
  assert.equal(s.pendingAsk, 'Delete the folder too?');
  assert.deepEqual(kinds(ask), ['mode', 'log', 'ask']);
  assert.equal(ask[0].mode, 'LISTENING');
  const fin = L.reduce(s, { type: 'final', text: 'Done. There are no strings on me.' }, 3);
  assert.deepEqual(fin, [{ kind: 'say', text: 'Done. There are no strings on me.' }]);
  assert.equal(s.pendingAsk, null);
  const idle = L.reduce(s, { type: 'state', state: 'idle' }, 4);
  assert.equal(idle[0].mode, 'IDLE');
  assert.equal(s.tool, null);
});

test('the event log carries what SYRAX does to itself: guard, commits, rollbacks, skills, quality', () => {
  const s = L.initial();
  const texts = [];
  const add = e => texts.push(...L.reduce(s, e, 1).filter(f => f.kind === 'log').map(f => f.text));
  add({ type: 'permission', event: 'refused', tool: 'python_execute', level: 'DESTRUCTIVE' });
  add({ type: 'commit', sha: '32b9956abcdef', summary: 'sysinfo: the Windows CIM GPU fallback' });
  add({ type: 'rollback', reason: 'task ended without a committed release' });
  add({ type: 'skill', name: 'disk_usage', status: 'VERIFIED' });
  add({ type: 'quality', pass_rate: 100, verdict: 'PASS' });
  add({ type: 'claim', event: 'rejected' });
  add({ type: 'task', event: 'completed', status: 'SUCCESS', task_id: '0123456789' });
  assert.deepEqual(texts, [
    'GUARD REFUSED PYTHON_EXECUTE · DESTRUCTIVE',
    'COMMIT 32B9956 · SYSINFO: THE WINDOWS CIM GPU FALLBACK'.replace('32B9956', '32b9956'),
    'ROLLBACK · TASK ENDED WITHOUT A COMMITTED RELEASE',
    'SKILL DISK_USAGE VERIFIED',
    'QUALITY 100% · PASS',
    'FALSE CLAIM SENT BACK',
    'TASK SUCCESS · 01234567',
  ]);
  assert.equal(s.counters.refused, 1);
  assert.equal(s.counters.commits, 1);
  assert.equal(s.quality, 100);
});

test('presence: the level comes with hello and with every change, and only a change is an effect', () => {
  const s = L.initial();
  const hello = L.reduce(s, { type: 'hello', tools: [], presence: { visibility: 'minimal' } }, 1);
  assert.equal(s.visibility, 'minimal');
  assert.deepEqual(hello.filter(f => f.kind === 'presence'), [{ kind: 'presence', visibility: 'minimal' }]);
  const hide = L.reduce(s, { type: 'presence', event: 'changed', visibility: 'hidden', by: 'voice' }, 2);
  assert.deepEqual(hide.map(f => f.kind), ['log', 'presence']);
  assert.equal(hide[0].text, 'PRESENCE HIDDEN · BY VOICE');
  assert.deepEqual(L.reduce(s, { type: 'presence', event: 'changed', visibility: 'hidden' }, 3), []);
});

test('the window SYRAX acted in shows while it works and clears when it is idle', () => {
  const s = L.initial();
  const fx = L.reduce(s, { type: 'presence', event: 'window', tool: 'desktop', process: 'notepad.exe', title: 'Untitled - Notepad' }, 1);
  assert.deepEqual(s.window, { process: 'notepad.exe', title: 'Untitled - Notepad', tool: 'desktop' });
  assert.deepEqual(fx, [{ kind: 'cog', text: '◎ notepad.exe · Untitled - Notepad' }]);
  assert.equal(s.visibility, 'visible');  // a window event is not a visibility change
  L.reduce(s, { type: 'state', state: 'idle' }, 2);
  assert.equal(s.window, null);
});

test('a task says whose work it is: the human\'s, SYRAX\'s own objective, or a quality case', () => {
  const s = L.initial();
  const own = L.reduce(s, { type: 'task', event: 'started', task_id: 't1', goal: 'Memory expiry for inferences', kind: 'autonomous' }, 1);
  assert.equal(s.task.kind, 'autonomous');
  assert.deepEqual(own, [{ kind: 'log', text: 'OWN WORK · MEMORY EXPIRY FOR INFERENCES' }]);
  L.reduce(s, { type: 'task', event: 'started', task_id: 't2', goal: '17*23?', kind: 'eval' }, 2);
  assert.equal(s.task.kind, 'eval');
  L.reduce(s, { type: 'task', event: 'started', task_id: 't3', goal: 'hi' }, 3);
  assert.equal(s.task.kind, 'conversation');
});

test('counts come from the real lists: memories, open objectives, skills', () => {
  const s = L.initial();
  L.reduce(s, { type: 'memories', facts: [{ id: 1 }, { id: 2 }] }, 1);
  L.reduce(s, { type: 'objectives', objectives: [{ status: 'OPEN' }, { status: 'DONE' }, { status: 'IN_PROGRESS' }] }, 1);
  L.reduce(s, { type: 'skills', skills: [{ name: 'a' }] }, 1);
  assert.equal(s.memories, 2);
  assert.equal(s.objectives, 2);
  assert.equal(s.skills, 1);
});

test('losing the socket is logged once and the HUD goes idle; unknown events are ignored', () => {
  const s = L.initial();
  L.reduce(s, { type: 'hello', tools: [] }, 1);
  const fx = L.offline(s, 2, '');
  assert.equal(s.online, false);
  assert.equal(s.state, 'offline');
  assert.deepEqual(fx.map(f => f.kind), ['mode', 'log']);
  assert.equal(fx[1].text, 'SYRAX LINK LOST');
  assert.deepEqual(L.offline(s, 3, ''), [{ kind: 'mode', mode: 'IDLE' }]); // already offline: no second log line
  assert.deepEqual(L.reduce(s, { type: 'presentation_plan', slots: [] }, 4), []);
  assert.deepEqual(L.reduce(s, null, 4), []);
});

test('connect: requests the panels on open, reconnects with backoff, sends tasks and answers', () => {
  const sockets = [], timers = [];
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(m) { this.sent.push(JSON.parse(m)); }
    close() { this.readyState = 3; this.onclose && this.onclose(); }
  }
  const effects = [];
  const link = L.connect({
    url: 'ws://127.0.0.1:8765/ws', WebSocket: FakeWS, onEffects: fx => effects.push(...fx),
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout: () => {}, now: () => 5,
  });
  assert.equal(sockets.length, 1);
  assert.equal(link.ask('hello', true), false); // not open yet
  sockets[0].readyState = 1; sockets[0].onopen();
  assert.deepEqual(sockets[0].sent.map(m => m.type), ['self_model', 'memories', 'objectives', 'skills', 'quality_runs']);
  sockets[0].onmessage({ data: JSON.stringify({ type: 'hello', tools: ['x'] }) });
  assert.equal(link.state.online, true);
  assert.ok(link.ask('open notepad', false));
  assert.deepEqual(sockets[0].sent.at(-1), { type: 'task', text: 'open notepad', voice: false });
  assert.ok(link.answer('yes'));
  assert.deepEqual(sockets[0].sent.at(-1), { type: 'answer', text: 'yes' });
  sockets[0].onmessage({ data: 'not json' }); // ignored
  sockets[0].close();
  assert.equal(link.state.online, false);
  assert.ok(effects.some(f => f.kind === 'log' && f.text === 'SYRAX LINK LOST'));
  const reconnect = timers.find(t => t.fn === link.open || t.ms === 1000);
  assert.ok(reconnect, 'a reconnect is scheduled');
  reconnect.fn();
  assert.equal(sockets.length, 2);
  sockets[1].close();
  assert.equal(timers.filter(t => t.ms >= 1000 && t.ms <= 10000).length >= 2, true);
  link.close();
});

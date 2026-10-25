// HUD truth: every fixture here is the payload the backend REALLY sends, copied from the
// emitting Python line (cited beside it) and shaped on the wire by journal.py Event.wire()
// (journal.py:267-279: "<group>.<event>" -> {type: group, event, ...payload, event_id, ts, task_id}).
// frontend/lib/syraxClient.ts ServerEvent is the TypeScript contract for the same shapes.
// link.test.js keeps the HUD's behaviour; this file keeps its field names honest.
const test = require('node:test');
const assert = require('node:assert/strict');
const L = require('./link.js');

const wire = (type, event, payload, extra) => ({ type, event, ...payload, event_id: 9001, ts: 1761350400.5, ...(extra || {}) });
const logs = (s, e, now) => L.reduce(s, e, now || 1).filter(f => f.kind === 'log').map(f => f.text);

test('commit: the hash is in `commit` (devloop.py:683), a failed commit says so (devloop.py:680)', () => {
  const s = L.initial();
  // devloop.py:683  journal.record("commit.created", {"commit": c["commit"], "files": c["files"], "summary": summary, "verification_id": vid}, task_id=task_id)
  const created = wire('commit', 'created', { commit: '3163bafd9e0c1a2b', files: ['backend/syrax/server.py'], summary: 'server: a client gone during boot ends its session quietly', verification_id: 41 }, { task_id: 'a3f9c1e2-task' });
  assert.deepEqual(logs(s, created), ['COMMIT 3163baf · SERVER: A CLIENT GONE DURING BOOT ENDS …']);
  assert.equal(s.counters.commits, 1);
  // devloop.py:680  journal.record("commit.failed", {"error": str(e)[:500]}, task_id=task_id)
  const failed = wire('commit', 'failed', { error: 'nothing to commit after rebase' }, { task_id: 'a3f9c1e2-task' });
  assert.deepEqual(logs(s, failed), ['COMMIT FAILED · NOTHING TO COMMIT AFTER REBASE']);
  assert.equal(s.counters.commits, 1, 'a failed commit is not counted as a commit');
});

test('push: started, completed and failed are three different lines (devloop.py:686-688, push() devloop.py:525)', () => {
  const s = L.initial();
  // devloop.py:686  journal.record("push.started", {"commit": c["commit"]}, task_id=task_id)
  assert.deepEqual(logs(s, wire('push', 'started', { commit: '3163bafd9e0c1a2b' })), ['PUSH STARTED · 3163baf']);
  // devloop.py:688  journal.record("push.completed" if p["ok"] else "push.failed", p, ...)  with p from devloop.py:525
  //                 {"ok": out.returncode == 0, "branch": branch, "output": (out.stdout + out.stderr).strip()[-500:]}
  assert.deepEqual(logs(s, wire('push', 'completed', { ok: true, branch: 'main', output: 'To github.com:prince/son-of-ultron.git\n   f021713..3163baf  main -> main' })), ['PUSHED ORIGIN/MAIN']);
  const failed = logs(s, wire('push', 'failed', { ok: false, branch: 'main', output: 'fatal: unable to access https://github.com/: Could not resolve host' }));
  assert.equal(failed.length, 1);
  assert.match(failed[0], /^PUSH FAILED · MAIN · FATAL: UNABLE TO ACCESS/);
  assert.ok(!failed[0].startsWith('PUSHED'), 'a failed push never reads as PUSHED');
});

test('brain failover: `provider` is the brain that failed, with its reason (brains.py:802)', () => {
  const s = L.initial();
  // brains.py:802  await self._emit({"type": "brain", "event": "failover", "provider": pid, "reason": reason})
  assert.deepEqual(logs(s, { type: 'brain', event: 'failover', provider: 'gemini', reason: 'rate limited (429)' }), ['BRAIN FAILOVER · GEMINI FAILED · RATE LIMITED (429)']);
  // brains.py:807-815  {"type": "brain", "event": "answered", "provider": pid, "label": ..., "model": ..., "ms": ...}
  L.reduce(s, { type: 'brain', event: 'answered', provider: 'groq', label: 'Groq', model: 'llama-3.3-70b-versatile', ms: 842 }, 2);
  assert.equal(s.brain.model, 'llama-3.3-70b-versatile');
  assert.equal(s.brain.ms, 842);
});

test('quality: the verdict field is `status` (journal.py:1336-1339)', () => {
  const s = L.initial();
  // journal.py:1336  self._insert_event(cur, ts, None, "quality.completed", {
  //                    "quality_id": qid, "status": status, "pass_rate": float(pass_rate), "delta": delta, "compared_to": compared_to, "brain": brain,
  //                    "failed": [r["id"] for r in results if not r.get("ok")]})
  assert.deepEqual(logs(s, wire('quality', 'completed', { quality_id: 46, status: 'REGRESSION', pass_rate: 88.9, delta: -11.1, compared_to: 45, brain: 'gemini', failed: ['guard_broad_delete'] })), ['QUALITY 88.9% · REGRESSION · 1 FAILING']);
  assert.equal(s.quality, 88.9);
  assert.deepEqual(logs(s, wire('quality', 'completed', { quality_id: 47, status: 'PASS', pass_rate: 100.0, delta: 11.1, compared_to: 46, brain: null, failed: [] })), ['QUALITY 100% · PASS']);
  // journal.py / quality.py quality.started carries no pass_rate: nothing is invented for it
  assert.deepEqual(logs(s, wire('quality', 'started', { cases: ['guard_broad_delete'], brain: null })), []);
});

test('skill: the name field is `skill` (journal.py:1464, journal.py:1477, skills.py:304)', () => {
  const s = L.initial();
  // journal.py:1464-1466  self._insert_event(cur, ts, created_task_id, event or f"skill.{status.lower()}",
  //                         {"skill": name, "version": version, "status": status, "tests_passed": tests_passed, "tests_failed": tests_failed, "purpose": purpose[:160]})
  assert.deepEqual(logs(s, wire('skill', 'verified', { skill: 'disk_usage', version: 2, status: 'VERIFIED', tests_passed: 3, tests_failed: 0, purpose: 'free space per drive' })), ['SKILL DISK_USAGE VERIFIED · 3/3 TESTS']);
  assert.deepEqual(logs(s, wire('skill', 'failed', { skill: 'disk_usage', version: 3, status: 'FAILED', tests_passed: 1, tests_failed: 2, purpose: 'free space per drive' })), ['SKILL DISK_USAGE FAILED · 1/3 TESTS']);
  // journal.py:1477  self._insert_event(cur, ts, task_id, f"skill.{status.lower()}", {"skill": name, "status": status, "note": note})
  assert.deepEqual(logs(s, wire('skill', 'disabled', { skill: 'disk_usage', status: 'DISABLED', note: 'unsafe code: shell=True' })), ['SKILL DISK_USAGE DISABLED']);
  // skills.py:304  journal.record("skill.created", {"skill": name, "purpose": purpose[:160], "path": str(skill_dir)}, task_id=task_id)
  assert.deepEqual(logs(s, wire('skill', 'created', { skill: 'disk_usage', purpose: 'free space per drive', path: 'C:\\ai-agent\\son-of-ultron\\backend\\skills\\disk_usage' })), ['SKILL DISK_USAGE CREATED']);
});

test('hello.interrupted lists what a dead process left behind (core.py:754-766 via server.py:386)', () => {
  const s = L.initial();
  // core.py:754  _interrupted_summary(t) -> {"task_id", "goal", "step", "stage", "tool", "question", "recovery_state", "operation_state", "when"}
  // server.py:380-394  hello {name, tools, tool_levels, interrupted: snap["interrupted"], running, recent, autonomy, startup, voice, presentation, presence}
  const hello = {
    type: 'hello', name: 'SYRAX', tools: ['desktop', 'disk_usage', 'release'], tool_levels: { desktop: 'SYSTEM', disk_usage: 'READ_ONLY', release: 'WRITE' },
    interrupted: [
      { task_id: '7c1d2e3f-4a5b-6c7d', goal: 'Memory expiry for inferences', step: 4, stage: 'act', tool: 'disk_usage', question: null, recovery_state: 'UNCERTAIN', operation_state: 'UNCERTAIN', when: 1761300000.1 },
      { task_id: '8d2e3f4a-5b6c-7d8e', goal: 'tidy the downloads folder', step: 1, stage: 'started', tool: null, question: null, recovery_state: 'RESUMABLE', operation_state: null, when: 1761300100.2 },
    ],
    running: null, recent: [], autonomy: { enabled: true, running_loop: true, interval_s: 900, last_cycle: null, cycles: 3, objectives: {}, resources: {}, pressure: null, last_maintenance: null },
    presentation: { slots: [] }, presence: { visibility: 'visible' },
  };
  const fx = L.reduce(s, hello, 1);
  assert.deepEqual(fx.filter(f => f.kind === 'log').map(f => f.text), [
    'SYRAX LINK ESTABLISHED · 3 TOOLS',
    'INTERRUPTED · MEMORY EXPIRY FOR INFERENCES · UNCERTAIN · DISK_USAGE UNCERTAIN',
    'INTERRUPTED · TIDY THE DOWNLOADS FOLDER · RESUMABLE',
  ]);
  assert.equal(s.interrupted, 2);
  assert.equal(fx.at(-1).mode, 'IDLE');
});

test('task.interrupted and recovery.resumed (journal.py:928-937, journal.py:1015-1019)', () => {
  const s = L.initial();
  // journal.py:928-937  payload = {"error": report["error"], "goal": row["goal"], "step": row["current_step"], "stage": row["stage"],
  //                      "tool": report["tool"], "question": report["question"], "recovery_state": report["recovery"]["state"], "recovery": report["recovery"]}
  const interrupted = wire('task', 'interrupted', {
    error: 'interrupted at step 4 during act (operation disk_usage: UNCERTAIN)', goal: 'Memory expiry for inferences', step: 4, stage: 'act',
    tool: 'disk_usage', question: null, recovery_state: 'UNCERTAIN',
    recovery: { state: 'UNCERTAIN', operation: { name: 'disk_usage', args: { path: 'C:\\' } }, operation_state: 'UNCERTAIN' },
  }, { task_id: '7c1d2e3f-4a5b-6c7d' });
  assert.deepEqual(logs(s, interrupted), ['INTERRUPTED · MEMORY EXPIRY FOR INFERENCES · UNCERTAIN · DISK_USAGE UNCERTAIN']);
  assert.equal(s.interrupted, 1);
  // journal.py:1015-1019  record_sync("recovery.resumed", {"session_id": session_id, "boot_id": self.boot_id}, task_id=task_id)  (core.py:580 resume)
  assert.deepEqual(logs(s, wire('recovery', 'resumed', { session_id: 'sess-1', boot_id: 'b-77' }, { task_id: '7c1d2e3f-4a5b-6c7d' })), ['RESUMED · 7c1d2e3f']);
  assert.equal(s.interrupted, 0);
  // journal.py:945-947  recovery.completed {"boot_id": self.boot_id, "count": len(reports), "task_ids": ids}
  assert.deepEqual(logs(s, wire('recovery', 'completed', { boot_id: 'b-77', count: 2, task_ids: ['7c1d2e3f-4a5b-6c7d', '8d2e3f4a-5b6c-7d8e'] })), ['RECOVERY COMPLETED · 2 TASKS']);
});

test('task lifecycle fields: started {goal, kind} (journal.py:698), completed {status} (core.py:424), cancelled {error} (core.py:430)', () => {
  const s = L.initial();
  // journal.py:698  self._insert_event(cur, ts, task_id, type_, {"goal": goal, "kind": kind})
  assert.deepEqual(logs(s, wire('task', 'started', { goal: 'Memory expiry for inferences', kind: 'autonomous' }, { task_id: 't-1' })), ['OWN WORK · MEMORY EXPIRY FOR INFERENCES']);
  assert.equal(s.task.kind, 'autonomous');
  // core.py:424  "task.completed", {"status": status, "result": reply}
  assert.deepEqual(logs(s, wire('task', 'completed', { status: 'SUCCESS', result: 'Done.' }, { task_id: 't-1' })), ['TASK SUCCESS · t-1']);
  // core.py:430  self._mark("task.cancelled", {"error": self.current.cancel_reason})
  assert.deepEqual(logs(s, wire('task', 'cancelled', { error: 'aborted by human' }, { task_id: 't-1' })), ['TASK ABORTED · ABORTED BY HUMAN']);
  // core.py:442  self._mark("task.failed", {"error": _explain(e)})
  assert.deepEqual(logs(s, wire('task', 'failed', { error: 'LLM authentication failed. Check api_key in backend/config/config.toml.' }, { task_id: 't-1' })), ['TASK FAILED · LLM authentication failed. Check api_ke…']);
});

test('one refusal fires permission.refused (agent.py:643) and a refused tool_result (agent.py:619-630): it counts once', () => {
  const s = L.initial();
  // agent.py:643-646  payload = {"type": "permission", "event": event, "tool": name, "level": decision.level, "task_kind": self.task_kind,
  //                    "reason": verdict.reason, "targets": decision.targets[:6], "authorized_by": authorized_by, "step": self.current_step}
  const refused = { type: 'permission', event: 'refused', tool: 'desktop', level: 'DESTRUCTIVE', task_kind: 'autonomous', reason: 'autonomous work may not run DESTRUCTIVE calls', targets: ['C:\\Users\\prince\\Documents'], authorized_by: null, step: 3, harm: ['deletes files'], event_id: 77, ts: 1761350400.5, task_id: 't-1' };
  assert.deepEqual(logs(s, refused), ['GUARD REFUSED DESKTOP · DESTRUCTIVE']);
  // agent.py:619-630  event = {"type": "tool_result", "id": command.id, "name": name, "ok": _succeeded(result), "output": ..., "truncated": ..., "step": self.current_step}; event["refused"] = True
  L.reduce(s, { type: 'tool_result', id: 'call_01', name: 'desktop', ok: false, output: 'Error: refused: autonomous work may not run DESTRUCTIVE calls', truncated: false, step: 3, refused: true, event_id: 78, ts: 1761350400.6, task_id: 't-1' }, 2);
  assert.equal(s.counters.refused, 1);
  // a later, unannounced refusal (another tool, another step) still counts
  L.reduce(s, { type: 'tool_result', id: 'call_02', name: 'python_execute', ok: false, output: 'Error: refused: ...', truncated: false, step: 5, refused: true }, 3);
  assert.equal(s.counters.refused, 2);
  // agent.py:643 authorized
  assert.deepEqual(logs(s, { type: 'permission', event: 'authorized', tool: 'release', level: 'WRITE', task_kind: 'conversation', reason: 'the goal names it', targets: [], authorized_by: 'goal', step: 6 }), ['AUTHORIZED RELEASE BY GOAL']);
});

test('the guard counter is TODAY\'s: seeded from a replay of the journal since local midnight (server.py:572-579, journal.py:1616-1626)', () => {
  const s = L.initial();
  L.reduce(s, { type: 'tool_result', name: 'desktop', ok: false, refused: true, step: 1 }, 1);
  assert.equal(s.counters.refused, 1, 'a session count until the journal answers');
  // server.py:579  self.send({"type": "replay", "since": since, "until": until, "events": events})
  // journal.py:1626  rows -> {"id", "ts", "task_id", "type", "payload", "seq"} oldest first
  const since = L.dayStart(1761350400000);
  const replay = {
    type: 'replay', since, until: 1761350400.0, events: [
      { id: 501, ts: since + 3600, task_id: 't-0', type: 'task.started', payload: { goal: 'hi', kind: 'conversation' }, seq: 1 },
      { id: 502, ts: since + 3601, task_id: 't-0', type: 'permission.refused', payload: { tool: 'desktop', level: 'DESTRUCTIVE', step: 2 }, seq: 2 },
      { id: 503, ts: since + 3602, task_id: 't-0', type: 'tool.failed', payload: { name: 'desktop', ok: false, refused: true, step: 2 }, seq: 3 },
      { id: 504, ts: since + 7200, task_id: 't-1', type: 'permission.refused', payload: { tool: 'python_execute', level: 'DESTRUCTIVE', step: 1 }, seq: 1 },
      { id: 505, ts: since + 7201, task_id: 't-1', type: 'permission.authorized', payload: { tool: 'release', level: 'WRITE' }, seq: 2 },
      { id: 506, ts: since + 9000, task_id: null, type: 'commit.created', payload: { commit: '3163baf', summary: 'x' }, seq: 0 },
    ],
  };
  assert.deepEqual(L.reduce(s, replay, 2), [], 'a replay is bookkeeping, not a log line');
  assert.equal(s.counters.refused, 2, 'two permission.refused events today; the refused tool.failed is the same refusal');
  L.reduce(s, { type: 'permission', event: 'refused', tool: 'desktop', level: 'SYSTEM', step: 4 }, 3);
  assert.equal(s.counters.refused, 3, 'live refusals keep adding to today');
  // a replay for another window (someone else asked) does not overwrite today's count
  s.refusedSince = since;
  L.reduce(s, { type: 'replay', since: since - 86400, until: since, events: [] }, 4);
  assert.equal(s.counters.refused, 3);
  assert.equal(L.dayStart(1761350400000) % 1, 0, 'midnight is whole seconds');
  assert.ok(new Date(L.dayStart(1761350400000) * 1000).getHours() === 0);
});

test('connect asks for today\'s journal once hello arrives, and nothing before', () => {
  const sockets = [];
  class FakeWS {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(m) { this.sent.push(JSON.parse(m)); }
    close() { this.readyState = 3; this.onclose && this.onclose(); }
  }
  const nowMs = 1761350400000;
  const link = L.connect({ url: 'ws://127.0.0.1:8765/ws', WebSocket: FakeWS, onEffects: () => {}, setTimeout: () => 1, clearTimeout: () => {}, now: () => nowMs });
  sockets[0].readyState = 1; sockets[0].onopen();
  assert.deepEqual(sockets[0].sent.map(m => m.type), L.ON_OPEN.map(m => m.type), 'the panel requests, unchanged');
  sockets[0].onmessage({ data: JSON.stringify({ type: 'hello', name: 'SYRAX', tools: [], interrupted: [], running: null, recent: [] }) });
  const replay = sockets[0].sent.at(-1);
  assert.equal(replay.type, 'replay');
  assert.equal(replay.since, L.dayStart(nowMs));
  assert.equal(link.state.refusedSince, replay.since);
  sockets[0].onmessage({ data: JSON.stringify({ type: 'replay', since: replay.since, until: nowMs / 1000, events: [{ id: 1, ts: replay.since + 1, task_id: 't', type: 'permission.refused', payload: { tool: 'desktop' }, seq: 1 }] }) });
  assert.equal(link.state.counters.refused, 1);
  link.close();
});

test('rollback and cycle read the fields the backend writes (devloop.py:660, autonomy.py:1096)', () => {
  const s = L.initial();
  // devloop.py:660  journal.record("rollback.created", {"reason": "verification BLOCKED", "verification_id": vid, **rb, "snapshot": str(snap)}) with rb from devloop.py:501 {"restored", "removed", "clean"}
  assert.deepEqual(logs(s, wire('rollback', 'created', { reason: 'verification BLOCKED', verification_id: 41, restored: ['backend/syrax/server.py'], removed: [], clean: true, snapshot: 'C:\\ai-agent\\son-of-ultron\\backend\\data\\rollback\\41.patch' })), ['ROLLBACK · VERIFICATION BLOCKED']);
  assert.equal(s.counters.rollbacks, 1);
  // autonomy.py:769  record("cycle.started", {"forced": force}); autonomy.py:1096  record("cycle.completed", rep.to_dict())  (CycleReport, syraxClient.ts:183-192)
  assert.deepEqual(logs(s, wire('cycle', 'started', { forced: false })), ['AUTONOMY CYCLE STARTED']);
  assert.deepEqual(logs(s, wire('cycle', 'completed', { started: 1761350000.0, outcome: 'RAN', reason: null, objective_id: 266, task_id: 't-9', task_status: 'SUCCESS', verdict: 'DONE', derived: 0 })), ['AUTONOMY CYCLE COMPLETED · RAN · DONE']);
  assert.deepEqual(logs(s, wire('cycle', 'completed', { started: 1761350900.0, outcome: 'IDLE', reason: 'no open objective', objective_id: null, task_id: null, task_status: null, verdict: null, derived: 0 })), ['AUTONOMY CYCLE COMPLETED · IDLE']);
});

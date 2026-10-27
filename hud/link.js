// SYRAX link: the HUD's line to the backend (ws://127.0.0.1:8765/ws) and the state it
// keeps from what SYRAX reports about itself. Nothing in the HUD's SYRAX panels is
// invented: every line comes through here from a backend event.
//
// reduce(state, event) is pure (no I/O), so `node --test` covers the whole mapping;
// connect() wires it to a WebSocket with reconnect and hands the HUD "effects":
//   {kind:'mode', mode}   the AI state the HUD should show (IDLE/THINKING/LISTENING)
//   {kind:'say', text}    SYRAX's final reply, to be spoken and typed in
//   {kind:'ask', question} SYRAX needs an answer before it continues
//   {kind:'cog', text}    one line of real reasoning or a tool call, for the cognition panel
//   {kind:'log', text}    one line for the event log
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.SyraxLink = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const MAX_COG = 7, MAX_LOG = 40;
  const STATE_MODE = { idle: 'IDLE', thinking: 'THINKING', acting: 'THINKING', offline: 'IDLE' };

  function initial() {
    return {
      online: false, name: 'SYRAX', version: null, bootId: null, uptimeS: 0, restartPending: false, visibility: 'visible', window: null,
      state: 'offline', tool: null, phase: null, step: 0, task: null, pendingAsk: null,
      // queue: the human requests waiting for the running task (core.py queued(): {task_id, goal, created, session_id, position});
      // waiting: the question SYRAX is blocked on (tools.py:51 ask), cleared once the task moves on or ends
      queue: [], waiting: null,
      lastReply: null, lastReplyAt: 0,
      cog: [], log: [],
      brain: { active: null, model: null, ready: 0, total: 0, ms: null },
      autonomy: null, tools: [], toolLevels: {},
      memories: null, objectives: null, skills: null, quality: null, interrupted: null,
      // refused is TODAY's count: seeded from the journal (replay since local midnight) and kept live.
      // One refusal fires permission.refused AND a refused tool_result; lastRefusal pairs them so it counts once.
      counters: { tasks: 0, toolsOk: 0, toolsFailed: 0, refused: 0, commits: 0, rollbacks: 0, claims: 0 },
      lastRefusal: null, refusedSince: null,
    };
  }

  function short(s, n) { s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n - 1) + '…' : s; }
  function argSummary(args) {
    if (!args || typeof args !== 'object') return '';
    const keys = ['command', 'path', 'query', 'url', 'name', 'code', 'text', 'inquire', 'action', 'summary'];
    const k = keys.find(k => args[k] != null) || Object.keys(args)[0];
    return k ? short(args[k], 48) : '';
  }
  function push(arr, item, max) { arr.push(item); while (arr.length > max) arr.shift(); }
  // local midnight before `nowMs`, in epoch seconds: the journal's clock (journal.py _now) and replay's `since`
  function dayStart(nowMs) { const d = new Date(nowMs); d.setHours(0, 0, 0, 0); return d.getTime() / 1000; }
  // one interrupted task, as hello.interrupted (core.py _interrupted_summary) and task.interrupted
  // (journal.py recover_interrupted) both describe it: goal + how recovery classified it
  // + the intent ledger (intent.py): `intent` {tool, args_hash, summary, step} when the operation was a send or payment
  // that may have gone out (operation_state EXTERNAL_UNCERTAIN); core.py _interrupted_summary and recovery.intent carry it
  function interruptedLine(t) {
    const sent = t.intent && t.intent.summary ? ' · EXTERNAL ACTION MAY HAVE HAPPENED: ' + short(t.intent.summary, 40).toUpperCase() : '';
    return 'INTERRUPTED · ' + short(t.goal, 40).toUpperCase() + ' · ' + String(t.recovery_state || 'UNKNOWN').toUpperCase()
      + (t.tool ? ' · ' + String(t.tool).toUpperCase() + (t.operation_state ? ' ' + String(t.operation_state).toUpperCase() : '') : '') + sent;
  }
  // one waiting request: a hello.queue item (core.py queued(): {task_id, goal, created, session_id, position}) or task.queued (journal.py:706 {goal, kind})
  function queuedLine(goal, position) { return 'QUEUED · ' + short(goal, 40).toUpperCase() + ' · POSITION ' + position; }
  // the SYRAX panel's TASK row (hud.html): the running goal, then how many human requests wait behind it; nothing when none do
  function taskRow(s) {
    return (s.task ? String(s.task.goal || '').toUpperCase().slice(0, 26) : '—') + (s.queue && s.queue.length ? ' · QUEUE ' + s.queue.length : '');
  }
  // agent.py:657-664 tell(): {type:"permission", event, tool, level, task_kind, reason, targets, authorized_by, step, harm?, answer?}
  // permissionLine is the event-log line (the refusal's text is pinned by link.contract.test.js); permissionDetail says why and on
  // what (reason, first target), HOST HARM first when permissions.py refused for host harm (Decision.harm, permissions.py:99)
  function firstTarget(e) { return Array.isArray(e.targets) && e.targets.length ? short(e.targets[0], 40) : ''; }
  function permissionLine(e) {
    const tool = String(e.tool || '').toUpperCase();
    if (e.event === 'refused') return 'GUARD REFUSED ' + tool + (e.level ? ' · ' + e.level : '');
    return 'AUTHORIZED ' + tool + ' BY ' + String(e.authorized_by || 'human').toUpperCase() + (firstTarget(e) ? ' · ' + firstTarget(e) : '');
  }
  function permissionDetail(e) {
    const harm = Array.isArray(e.harm) ? e.harm.length > 0 : !!e.harm;
    const parts = [harm ? 'HOST HARM' : 'GUARD'];
    if (e.reason) parts.push(short(e.reason, 60));
    if (firstTarget(e)) parts.push(firstTarget(e));
    return parts.length === 1 && !harm ? '' : parts.join(' · ');
  }
  // the question a running task still waits on, from its journal events: server.py boot sends them as `task_events`
  // ([{id, ts, task_id, type, seq, payload}], journal.py events) when the HUD connects while a task runs, and the hello
  // snapshot itself carries no pending question. An answer, the agent moving on (a question that timed out returns
  // into the ask_human tool's result) or the task ending settles it. null when nothing waits.
  const SETTLES_ASK = ['answer', 'think', 'final', 'tool.started', 'tool.completed', 'tool.failed'];
  function pendingAskFrom(events) {
    let q = null;
    (Array.isArray(events) ? events : []).forEach(ev => {
      if (!ev || typeof ev.type !== 'string') return;
      if (ev.type === 'ask') q = ev.payload && typeof ev.payload.question === 'string' ? ev.payload.question : '';
      else if (SETTLES_ASK.includes(ev.type) || ev.type.startsWith('task.')) q = null;
    });
    return q;
  }

  // one backend event -> state change + effects for the HUD
  function reduce(s, e, now) {
    now = now || Date.now();
    const fx = [], log = t => { push(s.log, { t: now, text: t }, MAX_LOG); fx.push({ kind: 'log', text: t }); };
    const cog = t => { push(s.cog, { t: now, text: t }, MAX_COG); fx.push({ kind: 'cog', text: t }); };
    const mode = m => fx.push({ kind: 'mode', mode: m });
    const t = e && e.type;
    switch (t) {
      case 'hello':
        s.online = true; s.name = e.name || 'SYRAX';
        s.tools = e.tools || []; s.toolLevels = e.tool_levels || {};
        s.autonomy = e.autonomy || s.autonomy;
        if (e.presence && e.presence.visibility) { s.visibility = e.presence.visibility; fx.push({ kind: 'presence', visibility: s.visibility }); }
        log('SYRAX LINK ESTABLISHED · ' + s.tools.length + ' TOOLS');
        // tasks a dead process left behind (server.py boot -> core.py snapshot -> _interrupted_summary)
        if (Array.isArray(e.interrupted)) { s.interrupted = e.interrupted.length; e.interrupted.slice(0, 3).forEach(t => log(interruptedLine(t))); }
        // human requests waiting for the running task (server.py:396 <- core.py:730 snapshot <- core.py:342 queued(), oldest first)
        s.queue = Array.isArray(e.queue) ? e.queue : [];
        s.queue.forEach(q => log(queuedLine(q.goal, q.position)));
        if (e.running) { s.task = { id: e.running.task_id, goal: e.running.goal, step: e.running.step || 0, kind: e.running.kind || 'conversation' }; s.phase = e.running.phase || null; s.state = 'thinking'; mode('THINKING'); }
        else { s.state = 'idle'; mode('IDLE'); }
        break;
      case 'queue':
        // core.py:338/355/370 broadcast {"type": "queue", "items": self.queued()} whenever the queue changes; server.py:456 answers a `queue` request the same way
        s.queue = Array.isArray(e.items) ? e.items : [];
        break;
      case 'self_model': {
        const id = e.identity || (e.section === 'identity' ? e : null);
        if (id) { s.version = id.version || s.version; s.bootId = id.boot_id || s.bootId; s.uptimeS = id.process_uptime_s || 0; s.restartPending = !!id.restart_pending; }
        break;
      }
      case 'brains': {
        const ps = e.providers || [];
        s.brain.total = ps.length; s.brain.ready = ps.filter(p => p.status === 'ready').length;
        s.brain.active = e.active || s.brain.active;
        const a = ps.find(p => p.id === s.brain.active); if (a) s.brain.model = a.model || a.label || a.id;
        break;
      }
      case 'brain':
        if (e.event === 'answered' && e.model) s.brain.model = e.model;
        if (e.event === 'answered' && typeof e.ms === 'number') s.brain.ms = e.ms;  // how long that answer took (09e97df)
        // brains.py Router._emit {"type":"brain","event":"failover","provider": pid,"reason"}: `provider` is the brain that FAILED, the router moves on to the next
        if (e.event === 'failover') log('BRAIN FAILOVER · ' + String(e.provider || '?').toUpperCase() + ' FAILED' + (e.reason ? ' · ' + short(e.reason, 40).toUpperCase() : ''));
        break;
      case 'state':
        s.state = e.state || 'idle'; s.tool = e.tool || null; if (e.step) s.step = e.step;
        if (s.state === 'idle') { s.tool = null; s.task = null; s.phase = null; s.pendingAsk = null; s.window = null; }
        // a new step (agent.py: state thinking) or the end of the task means the question was answered or timed out (tools.py
        // returns "did not answer in time" and the agent goes on): it must not take the next command as its answer.
        // `acting` does not: the agent reports acting on a tool BEFORE that tool asks, and a reconnect replays it while SYRAX waits
        if (/^(thinking|idle)$/.test(s.state)) { s.waiting = null; s.pendingAsk = null; }
        mode(s.pendingAsk ? 'LISTENING' : STATE_MODE[s.state] || 'IDLE');
        break;
      case 'phase':
        s.phase = e.phase || null; if (e.phase) cog('PHASE ' + e.phase.toUpperCase());
        break;
      case 'task':
        if (e.event === 'started' || e.event === 'created') {
          // whose work it is: the human's (conversation), SYRAX's own objective (autonomous), or a quality case (eval)
          s.task = { id: e.task_id, goal: e.goal || '', step: 0, kind: e.kind || 'conversation' }; s.counters.tasks++;
          if (e.kind === 'autonomous') log('OWN WORK · ' + short(e.goal, 40).toUpperCase());
        }
        // journal.py:706 task.queued {goal, kind}: a request made while SYRAX was busy waits (core.py:336); the `queue` broadcast with its position follows (core.py:338)
        else if (e.event === 'queued') { const q = s.queue.find(i => i.task_id === e.task_id); log(queuedLine(e.goal, q ? q.position : s.queue.length + 1)); }
        else if (e.event === 'completed') log('TASK ' + (e.status || 'DONE') + (e.task_id ? ' · ' + String(e.task_id).slice(0, 8) : ''));  // core.py _mark task.completed {status, result}
        else if (e.event === 'failed') log('TASK FAILED · ' + short(e.error, 40));  // core.py _mark task.failed {error}
        else if (e.event === 'cancelled') log('TASK ABORTED' + (e.error ? ' · ' + short(e.error, 40).toUpperCase() : ''));  // core.py _mark task.cancelled {error: cancel_reason}
        else if (e.event === 'blocked') log('TASK BLOCKED · ' + short(e.reason || e.error, 40).toUpperCase());
        else if (e.event === 'unknown') log('TASK OUTCOME UNKNOWN' + (e.error ? ' · ' + short(e.error, 40).toUpperCase() : ''));
        // journal.py recover_interrupted task.interrupted {error, goal, step, stage, tool, question, recovery_state, recovery}
        else if (e.event === 'interrupted') { s.interrupted = (s.interrupted || 0) + 1; log(interruptedLine({ goal: e.goal, recovery_state: e.recovery_state, tool: e.tool, operation_state: e.recovery && e.recovery.operation_state, intent: e.recovery && e.recovery.intent })); }
        break;
      case 'think':
        if (e.tools && e.tools.length && e.content) cog('STEP ' + (e.step || '?') + ' · ' + short(e.content, 70));
        break;
      case 'tool_start':
        s.tool = e.name; if (e.step) s.step = e.step;
        cog('▶ ' + e.name + (argSummary(e.args) ? ' · ' + argSummary(e.args) : ''));
        break;
      case 'tool_result':
        if (e.refused) {  // agent.py tool_result {id, name, ok, output, truncated, step, refused: true}: the same refusal the guard just announced
          const paired = s.lastRefusal && s.lastRefusal.tool === e.name && (s.lastRefusal.step == null || e.step == null || s.lastRefusal.step === e.step);
          if (!paired) s.counters.refused++;
          s.lastRefusal = null; cog('⊘ ' + e.name + ' REFUSED');
        }
        else if (e.ok) { s.counters.toolsOk++; cog('✓ ' + e.name); }
        else { s.counters.toolsFailed++; cog('✗ ' + e.name + (e.output ? ' · ' + short(e.output, 40) : '')); }
        break;
      case 'ask':
        // tools.py:51 {"type": "ask", "question": inquire}, journaled by the core (core.py:74) so event_id/ts/task_id ride along; hud.html speaks it from the `ask` effect
        s.pendingAsk = e.question || ''; s.waiting = s.pendingAsk; mode('LISTENING'); log('WAITING FOR YOU · ' + short(s.pendingAsk, 60).toUpperCase()); fx.push({ kind: 'ask', question: s.pendingAsk });
        break;
      case 'final':
        s.lastReply = e.text || ''; s.lastReplyAt = now; s.pendingAsk = null; s.waiting = null;
        fx.push({ kind: 'say', text: s.lastReply });
        break;
      case 'user':
        // the HUD already shows what it sent; the human's answer comes back as `user` with the task's id (journal.py:249 _WIRE "answer" -> "user", journal.py:277)
        // an answer from any UI (this HUD or the web UI) settles the question; a new request's echo has no task_id
        if (e.task_id) { if (s.pendingAsk !== null) mode(STATE_MODE[s.state] || 'IDLE'); s.waiting = null; s.pendingAsk = null; }
        break;
      case 'answer':
        s.waiting = null; break;
      case 'notice':
        if (e.text) log(short(e.text, 60).toUpperCase());
        break;
      case 'error':
        log('ERROR · ' + short(e.message, 50).toUpperCase());
        break;
      case 'permission':
        // agent.py tell(): {type:"permission", event, tool, level, task_kind, reason, targets, authorized_by, step, harm?, answer?}
        // the log line is the verdict; why and on what go to the cognition panel, which shows 60 characters to the log's 40 (hud.html)
        if (e.event === 'refused') { s.counters.refused++; s.lastRefusal = { tool: e.tool, step: e.step == null ? null : e.step }; log(permissionLine(e)); const why = permissionDetail(e); if (why) cog('⊘ ' + why); }
        else if (e.event === 'authorized') log(permissionLine(e));
        break;
      case 'claim':
        if (e.event === 'rejected') { s.counters.claims++; log('FALSE CLAIM SENT BACK'); }
        break;
      case 'intent':
        // the intent ledger, agent.py _execute_guarded: recorded {tool, args_hash, summary, step} before an EXTERNAL_WRITE call
        // runs, done {tool, args_hash, ok, step} after it, refused {tool, args_hash, summary, step, first_step} when the same send
        // is asked again while the first was never seen to finish (intent.HELD). A refused intent is followed by a refused
        // tool_result (agent.py execute_tool): lastRefusal pairs them so the guard counter (permission.refused only) stays true.
        if (e.event === 'recorded') log('INTENT · ' + short(e.summary || e.tool, 50).toUpperCase());
        else if (e.event === 'done') log((e.ok ? 'INTENT DONE' : 'INTENT FAILED') + ' · ' + String(e.tool || '').toUpperCase());
        // uncertain {tool, args_hash, summary, step, why}: the call timed out or lost its connection while it ran, so it
        // may have gone out; the entry stays open and the same send is held (intent.uncertain)
        else if (e.event === 'uncertain') log('INTENT UNCERTAIN · ' + String(e.tool || '').toUpperCase() + ' · ' + String(e.why || 'timed out').toUpperCase() + ' · MAY HAVE GONE OUT');
        else if (e.event === 'refused') { s.lastRefusal = { tool: e.tool, step: e.step == null ? null : e.step }; log('INTENT HELD · ' + String(e.tool || '').toUpperCase() + ' · MAY ALREADY HAVE GONE OUT' + (e.first_step != null ? ' (STEP ' + e.first_step + ')' : '')); cog('⊘ ' + short(e.summary || e.tool, 60) + ' · NOT REPEATED'); }
        break;
      case 'commit':
        // devloop.py commit.created {commit, files, summary, verification_id} / commit.failed {error}; the hash field is `commit`
        if (e.event === 'failed') { log('COMMIT FAILED · ' + short(e.error, 40).toUpperCase()); break; }
        s.counters.commits++; log('COMMIT ' + String(e.commit || e.sha || e.head || '').slice(0, 7) + ' · ' + short(e.summary || e.message, 40).toUpperCase());
        break;
      case 'rollback':
        s.counters.rollbacks++; log('ROLLBACK · ' + short(e.reason, 40).toUpperCase());
        break;
      case 'push':
        // devloop.py push.started {commit}; push.completed / push.failed carry push() -> {ok, branch, output} (pushed to `origin`, devloop.py push)
        if (e.event === 'started') log('PUSH STARTED' + (e.commit ? ' · ' + String(e.commit).slice(0, 7) : ''));
        else if (e.event === 'failed' || e.ok === false) log('PUSH FAILED' + (e.branch ? ' · ' + String(e.branch).toUpperCase() : '') + (e.output ? ' · ' + short(e.output, 40).toUpperCase() : ''));
        else if (e.event === 'completed' || e.ok === true) log('PUSHED ORIGIN' + (e.branch ? '/' + String(e.branch).toUpperCase() : ''));
        break;
      case 'skill': {
        // journal.py upsert_skill_sync skill.<status> {skill, version, status, tests_passed, tests_failed, purpose}; set_skill_status_sync {skill, status, note}; skills.py skill.created {skill, purpose, path}
        const tests = typeof e.tests_passed === 'number' && typeof e.tests_failed === 'number' ? ' · ' + e.tests_passed + '/' + (e.tests_passed + e.tests_failed) + ' TESTS' : '';
        log('SKILL ' + String(e.skill || e.name || '').toUpperCase() + ' ' + String(e.status || e.event || '').toUpperCase() + tests);
        break;
      }
      case 'objective':
        log('OBJECTIVE ' + String(e.event || '').toUpperCase() + (e.goal ? ' · ' + short(e.goal, 36).toUpperCase() : ''));
        break;
      case 'cycle':
        // autonomy.py cycle.started {forced} / cycle.completed CycleReport.to_dict() {outcome, reason, verdict, ...}
        log('AUTONOMY CYCLE ' + String(e.event || '').toUpperCase() + (e.outcome ? ' · ' + String(e.outcome).toUpperCase() : '') + (e.verdict ? ' · ' + String(e.verdict).toUpperCase() : ''));
        break;
      case 'quality':
        // journal.py add_quality_run_sync quality.completed {quality_id, status: BASELINE|PASS|REGRESSION, pass_rate, delta, compared_to, brain, failed}
        if (e.pass_rate != null) {
          s.quality = e.pass_rate;
          const failed = Array.isArray(e.failed) && e.failed.length ? ' · ' + e.failed.length + ' FAILING' : '';
          log('QUALITY ' + e.pass_rate + '% · ' + String(e.status || e.verdict || '').toUpperCase() + failed);
        }
        break;
      case 'quality_runs':
        if (e.runs && e.runs.length) s.quality = e.runs[0].pass_rate;
        break;
      case 'autonomy_status':
        s.autonomy = e; break;
      case 'autonomy':
        // autonomy.py set_enabled -> autonomy.toggled {enabled}, sent to every UI; only the one that flipped it gets a fresh
        // autonomy_status, so the HUD's AUTONOMY ON/OFF follows the event
        if (e.event === 'toggled' && typeof e.enabled === 'boolean') {
          s.autonomy = Object.assign({}, s.autonomy || {}, { enabled: e.enabled });
          log('AUTONOMY ' + (e.enabled ? 'ON' : 'OFF'));
        }
        break;
      case 'memories':
        s.memories = (e.facts || []).length; break;
      case 'objectives':
        s.objectives = (e.objectives || []).filter(o => !/^(DONE|DROPPED)$/.test(o.status || '')).length; break;
      case 'skills':
        s.skills = (e.skills || []).length; break;
      case 'presence':
        if (e.event === 'window') {  // the application SYRAX just acted in (observed by the core, title redacted)
          s.window = { process: e.process || '', title: e.title || '', tool: e.tool || '' };
          cog('◎ ' + (e.process || '?') + (e.title ? ' · ' + short(e.title, 40) : ''));
          break;
        }
        if (e.visibility && e.visibility !== s.visibility) {
          s.visibility = e.visibility;
          log('PRESENCE ' + e.visibility.toUpperCase() + (e.by ? ' · BY ' + String(e.by).toUpperCase() : ''));
          fx.push({ kind: 'presence', visibility: e.visibility });
        }
        break;
      case 'recovery':
        // journal.py recovery.started {boot_id, task_ids} / recovery.verified {recovery} / recovery.completed {boot_id, count, task_ids};
        // mark_resumed_sync recovery.resumed {session_id, boot_id} + task_id (core.py resume): the interrupted task runs again
        if (e.event === 'resumed') { if (s.interrupted) s.interrupted--; log('RESUMED' + (e.task_id ? ' · ' + String(e.task_id).slice(0, 8) : '')); }
        else log('RECOVERY ' + String(e.event || '').toUpperCase() + (typeof e.count === 'number' ? ' · ' + e.count + ' TASK' + (e.count === 1 ? '' : 'S') : ''));
        break;
      case 'task_events': {
        // a reconnect while a task runs: without this the question is lost and the typed answer goes out as a new task
        if (!s.task || !e.task_id || e.task_id !== s.task.id || !Array.isArray(e.events)) break;
        const q = pendingAskFrom(e.events);
        if (q === null) { s.pendingAsk = null; s.waiting = null; break; }
        if (q === s.pendingAsk) break;
        s.pendingAsk = q; s.waiting = q; mode('LISTENING'); log('WAITING FOR YOU · ' + short(q, 60).toUpperCase()); fx.push({ kind: 'ask', question: q });
        break;
      }
      case 'replay': {
        // server.py replay -> journal.events_between(since, until): {type, since, until, events: [{id, ts, task_id, type, seq, payload}]}
        // connect() asks for today's events once hello arrives; the refusals in it make `counters.refused` a true count for TODAY
        if (!Array.isArray(e.events)) break;
        if (s.refusedSince != null && Math.abs((Number(e.since) || 0) - s.refusedSince) > 1) break;  // someone else's window
        s.counters.refused = e.events.filter(ev => ev && ev.type === 'permission.refused').length;
        s.lastRefusal = null;
        break;
      }
      default:
        break;
    }
    return fx;
  }

  function offline(s, now, reason) {
    const was = s.online;
    s.online = false; s.state = 'offline'; s.tool = null; s.pendingAsk = null; s.task = null; s.queue = []; s.waiting = null;
    const fx = [{ kind: 'mode', mode: 'IDLE' }];
    if (was || reason) { const text = was ? 'SYRAX LINK LOST' : 'SYRAX OFFLINE · ' + reason; push(s.log, { t: now, text }, MAX_LOG); fx.push({ kind: 'log', text }); }
    return fx;
  }

  // requests sent once the link is up, so the panels fill without the HUD asking
  const ON_OPEN = [{ type: 'self_model', section: 'identity' }, { type: 'memories' }, { type: 'objectives' }, { type: 'skills' }, { type: 'quality_runs' }];

  function connect(opts) {
    const WS = opts.WebSocket || (typeof WebSocket !== 'undefined' ? WebSocket : null);
    const setTimer = opts.setTimeout || setTimeout, clearTimer = opts.clearTimeout || clearTimeout;
    const now = opts.now || (() => Date.now());
    const state = initial();
    const link = { state, ws: null, attempts: 0, closed: false };
    const emit = fx => { if (fx.length && opts.onEffects) opts.onEffects(fx, state); };
    let reconnectTimer = null, pingTimer = null;

    function open() {
      if (link.closed || !WS) return;
      let ws;
      try { ws = new WS(opts.url); } catch (e) { return schedule(String(e)); }
      link.ws = ws;
      ws.onopen = () => {
        link.attempts = 0;
        ON_OPEN.forEach(m => send(m));
        pingTimer = setTimer(function ping() { send({ type: 'ping' }); pingTimer = setTimer(ping, 20000); }, 20000);
      };
      ws.onmessage = ev => {
        let msg; try { msg = JSON.parse(ev.data); } catch (_) { return; }
        if (!msg || typeof msg !== 'object') return;
        emit(reduce(state, msg, now()));
        // the guard counter says TODAY, so it is seeded from today's journal, not from this HUD session
        if (msg.type === 'hello') { state.refusedSince = dayStart(now()); send({ type: 'replay', since: state.refusedSince }); }
      };
      ws.onclose = () => { link.ws = null; if (pingTimer) clearTimer(pingTimer); emit(offline(state, now(), '')); schedule(''); };
      ws.onerror = () => { /* onclose follows */ };
    }
    function schedule(reason) {
      if (link.closed) return;
      const delay = Math.min(10000, 1000 * Math.pow(2, Math.min(link.attempts++, 4)));
      reconnectTimer = setTimer(open, delay);
    }
    function send(msg) {
      if (!link.ws || link.ws.readyState !== 1) return false;
      link.ws.send(JSON.stringify(msg)); return true;
    }
    link.send = send;
    link.ask = (text, voice) => send({ type: 'task', text, voice: !!voice });
    link.answer = text => send({ type: 'answer', text });
    link.stop = () => send({ type: 'stop', reason: 'hud' });
    link.refresh = () => ON_OPEN.forEach(m => send(m));
    link.presence = visibility => send({ type: 'presence', visibility, by: 'hud' });
    link.close = () => { link.closed = true; if (reconnectTimer) clearTimer(reconnectTimer); if (pingTimer) clearTimer(pingTimer); if (link.ws) link.ws.close(); };
    link.open = open;
    open();
    return link;
  }

  return { initial, reduce, offline, connect, argSummary, short, dayStart, interruptedLine, queuedLine, taskRow, permissionLine, permissionDetail, pendingAskFrom, ON_OPEN };
});

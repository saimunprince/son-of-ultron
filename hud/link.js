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
      lastReply: null, lastReplyAt: 0,
      cog: [], log: [],
      brain: { active: null, model: null, ready: 0, total: 0, ms: null },
      autonomy: null, tools: [], toolLevels: {},
      memories: null, objectives: null, skills: null, quality: null,
      counters: { tasks: 0, toolsOk: 0, toolsFailed: 0, refused: 0, commits: 0, rollbacks: 0, claims: 0 },
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
        if (e.running) { s.task = { id: e.running.task_id, goal: e.running.goal, step: e.running.step || 0, kind: e.running.kind || 'conversation' }; s.phase = e.running.phase || null; s.state = 'thinking'; mode('THINKING'); }
        else { s.state = 'idle'; mode('IDLE'); }
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
        if (e.event === 'failover') log('BRAIN FAILOVER → ' + (e.to || e.brain || '?').toUpperCase());
        break;
      case 'state':
        s.state = e.state || 'idle'; s.tool = e.tool || null; if (e.step) s.step = e.step;
        if (s.state === 'idle') { s.tool = null; s.task = null; s.phase = null; s.pendingAsk = null; s.window = null; }
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
        else if (e.event === 'completed') log('TASK ' + (e.status || 'DONE') + (e.task_id ? ' · ' + String(e.task_id).slice(0, 8) : ''));
        else if (e.event === 'failed') log('TASK FAILED · ' + short(e.error, 40));
        else if (e.event === 'cancelled') log('TASK ABORTED');
        break;
      case 'think':
        if (e.tools && e.tools.length && e.content) cog('STEP ' + (e.step || '?') + ' · ' + short(e.content, 70));
        break;
      case 'tool_start':
        s.tool = e.name; if (e.step) s.step = e.step;
        cog('▶ ' + e.name + (argSummary(e.args) ? ' · ' + argSummary(e.args) : ''));
        break;
      case 'tool_result':
        if (e.refused) { s.counters.refused++; cog('⊘ ' + e.name + ' REFUSED'); }
        else if (e.ok) { s.counters.toolsOk++; cog('✓ ' + e.name); }
        else { s.counters.toolsFailed++; cog('✗ ' + e.name + (e.output ? ' · ' + short(e.output, 40) : '')); }
        break;
      case 'ask':
        s.pendingAsk = e.question || ''; mode('LISTENING'); log('SYRAX ASKS'); fx.push({ kind: 'ask', question: s.pendingAsk });
        break;
      case 'final':
        s.lastReply = e.text || ''; s.lastReplyAt = now; s.pendingAsk = null;
        fx.push({ kind: 'say', text: s.lastReply });
        break;
      case 'user':
        break; // the HUD already shows what it sent
      case 'notice':
        if (e.text) log(short(e.text, 60).toUpperCase());
        break;
      case 'error':
        log('ERROR · ' + short(e.message, 50).toUpperCase());
        break;
      case 'permission':
        if (e.event === 'refused') { s.counters.refused++; log('GUARD REFUSED ' + String(e.tool || '').toUpperCase() + (e.level ? ' · ' + e.level : '')); }
        else if (e.event === 'authorized') log('AUTHORIZED ' + String(e.tool || '').toUpperCase() + ' BY ' + String(e.authorized_by || 'human').toUpperCase());
        break;
      case 'claim':
        if (e.event === 'rejected') { s.counters.claims++; log('FALSE CLAIM SENT BACK'); }
        break;
      case 'commit':
        s.counters.commits++; log('COMMIT ' + String(e.sha || e.head || '').slice(0, 7) + ' · ' + short(e.summary || e.message, 40).toUpperCase());
        break;
      case 'rollback':
        s.counters.rollbacks++; log('ROLLBACK · ' + short(e.reason, 40).toUpperCase());
        break;
      case 'push':
        log('PUSHED ' + String(e.remote || 'ORIGIN').toUpperCase());
        break;
      case 'skill':
        log('SKILL ' + String(e.name || '').toUpperCase() + ' ' + String(e.status || e.event || '').toUpperCase());
        break;
      case 'objective':
        log('OBJECTIVE ' + String(e.event || '').toUpperCase() + (e.goal ? ' · ' + short(e.goal, 36).toUpperCase() : ''));
        break;
      case 'cycle':
        log('AUTONOMY CYCLE ' + String(e.event || e.outcome || '').toUpperCase());
        break;
      case 'quality':
        if (e.pass_rate != null) { s.quality = e.pass_rate; log('QUALITY ' + e.pass_rate + '% · ' + String(e.verdict || '').toUpperCase()); }
        break;
      case 'quality_runs':
        if (e.runs && e.runs.length) s.quality = e.runs[0].pass_rate;
        break;
      case 'autonomy_status':
        s.autonomy = e; break;
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
        log('RECOVERY · ' + short(e.state || e.event, 30).toUpperCase()); break;
      default:
        break;
    }
    return fx;
  }

  function offline(s, now, reason) {
    const was = s.online;
    s.online = false; s.state = 'offline'; s.tool = null; s.pendingAsk = null; s.task = null;
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

  return { initial, reduce, offline, connect, argSummary, short, ON_OPEN };
});

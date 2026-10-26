# SYRAX Execution Model

This document describes what is implemented in `backend/syrax/journal.py`,
`backend/syrax/core.py` and `backend/syrax/verify.py` as of this commit.
Nothing here is planned-only; every statement is covered by a test named below.

## 1. Architecture

```
browser tab(s)  ──WS──▶  Session (observer + command router)   backend/syrax/server.py
                              │
                              ▼
                          Core (one SYRAX, one agent, one running task)   backend/syrax/core.py
                              │  emit()                     ▲ fan-out (wire events)
                              ▼                             │
                          Journal (SQLite WAL, synchronous=FULL)          backend/syrax/journal.py
                              tasks · events · checkpoints · verifications
```

- The task runs in the core, not in the WebSocket session. Closing the browser
  does not cancel it (`test_task_survives_disconnect_and_reconnect_replays_it`).
- Every connected session receives the same journaled events
  (`test_two_sessions_observe_the_same_task_and_only_one_may_run`).
- On (re)connect the session gets `hello{interrupted, running, recent}`, and if a
  task is running, a `task_events` replay of everything so far plus the live `state`.

## 2. Event routing (single source of truth)

`Core.emit()` is the agent's only output port. An event is **journaled** (written
durably, then fanned out) iff replay or recovery needs it:

| agent/wire event | journal type |
|---|---|
| `think` | `think` |
| `tool_start` | `tool.started` |
| `tool_result` ok / not ok | `tool.completed` / `tool.failed` |
| `ask` | `ask` |
| client `answer` accepted | `answer` (wired back as `user`) |
| `final` | `final` |
| `brain` failover / answered | `brain.failover` / `brain.answered` |
| `permission` authorized (agent, through `emit`) | `permission.authorized` — payload `tool`, `level`, `task_kind`, `reason`, `targets`, `authorized_by` (`goal` or `human`), `answer?`, `harm?` |
| `permission` refused (agent, through `emit`) | `permission.refused` — same payload, `authorized_by` null |
| `intent` recorded / done / refused / uncertain (agent, through `emit`) | `intent.recorded` / `intent.done` / `intent.refused` / `intent.uncertain` — the intent ledger (`intent.py`): payload `tool`, `args_hash` (sha256 of the canonical JSON of the arguments, 16 hex), `summary` (the tool and its most telling argument, 120 chars), `step`; `done` carries `ok`, `refused` carries `first_step`, `uncertain` carries `why` (`timed out` / `connection lost`) |
| written by the core / journal | `task.started`, `task.queued`, `task.completed`, `task.failed`, `task.cancelled`, `task.blocked`, `task.interrupted`, `task.unknown`, `checkpoint.created`, `recovery.started`, `recovery.verified`, `recovery.resumed`, `recovery.completed`, `verification.completed`, `stage.started` |

Direct (never stored): `state`, `hello`, `brains`, `brain_models`, `brain_test`,
`pong`, `notice`, `error`, the `user` echo of the task text, and the
`history` / `task_events` / `verifications` replies.

Wire translation (`Event.wire()`): journal types keep the frontend's existing
names (`tool.started` → `tool_start`, `task.completed` → `{"type":"task","event":"completed"}`),
and every journaled wire event carries `task_id`, `event_id`, `ts`.

Screenshots (`image`) are *volatile*: fanned out, never stored
(`test_async_record_fans_out_wire_events_and_volatile_is_not_stored`).

## 3. Schema (`backend/config/journal.db`, override `SYRAX_JOURNAL_FILE`)

- `tasks(task_id, goal, kind, status, stage, current_step, created, updated, last_event_id, last_checkpoint_id, operation, result, error, recovery, session_id, boot_id, git_head)`
- `events(id, ts, task_id, type, payload, seq, dedupe_key UNIQUE)` — `seq` is per task, 0 for task-less events
- `checkpoints(id, task_id, seq, ts, stage, completed_steps, current_operation, verified, remaining, assumptions, env, next_action, context, evidence_state)`
- `verifications(id, ts, task_id, git_head, status, gates)`
- `meta(schema_version=1)`

PRAGMAs: `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`; file mode 0600.
Every write is one `BEGIN IMMEDIATE … COMMIT`; the event insert and the task-row
update it implies are committed together (`test_task_row_changes_in_same_transaction_as_event`).

## 4. Task lifecycle

Statuses: `PENDING, IN_PROGRESS, BLOCKED, SUCCESS, PARTIAL, FAILED, CANCELLED, INTERRUPTED, UNKNOWN`.

**Queue (2026-10-25).** One task runs at a time. A human request made while a task runs is journaled `PENDING`
(`task.queued`) when the client asks to queue it (`task {text, queue: true}`; the UI, the HUD and the voice path
always do), and starts when the running task ends (`task.started`, PENDING → IN_PROGRESS), oldest first. `queue`
lists the waiting requests with their position; `queue_cancel {task_id, note?}` removes one (CANCELLED, the note in
its error). SYRAX's own work (eval, autonomous) never queues, and the autonomy cycle reports BUSY while a human
request waits. After a restart a queued request younger than an hour (`SYRAX_QUEUE_STALE_S`) starts once recovery
is done; an older one is cancelled with a note rather than run late.

**Deadlines and timeouts (2026-10-25).** Every task has a wall-clock deadline of its kind
(`core.TASK_DEADLINE_S`, seconds): a conversation 30 min (`SYRAX_TASK_DEADLINE_S`, default 1800),
SYRAX's own autonomous work 90 min (`SYRAX_OWN_TASK_DEADLINE_S`, default 5400: a release task's gate
and review fit inside), an eval none (the quality runner cancels its cases itself, at 240/420 s). A task
still running when its deadline passes is cancelled through the usual cancel path: `task.cancelled
{error: "ran out of time: the task's deadline (30 min) passed", error_class: "deadline"}` plus a notice
with the same text; the timer is disarmed when the task ends (no stray timers), and a resumed task gets
the deadline of its kind too. A call to an MCP tool (`browser_*`, or any `MCPClientTool` an MCP server
provides) is abandoned after `SYRAX_MCP_TOOL_TIMEOUT_S` seconds (default 180) with a failed result
(`tool.failed`, "did not answer within N s; the call was abandoned"); the task continues. Tools with a
cap of their own are never wrapped: `python_execute` (600 s), `release` (the gate), `skill_create` /
`skill_test`, `experiment`, `quality`, `desktop` (15 s), `str_replace_editor`, `ask_human` (600 s).
**Error classes.** `task.failed` carries `error_class` beside its text: `journal` (the journal refused
a write), `brain` (`BrainError`: all brains failed), `timeout` (a `TimeoutError`), `tool` (an exception
escaped a tool call; the text names the tool), else `other`. `task.cancelled` carries `error_class`:
`deadline` (the watchdog), `human` (the reason says "by human"), `quality_timeout` (the quality
runner's case timeout), else `other`. Both are additive fields: the event sequences are unchanged
(`test_task_deadline.py`, `test_mcp_timeout.py`, `test_error_class.py`).

Transition table (anything else raises `JournalError` and rolls back —
`test_transition_table_is_enforced` covers every pair):

| from | to |
|---|---|
| PENDING | IN_PROGRESS, CANCELLED |
| IN_PROGRESS | BLOCKED, SUCCESS, PARTIAL, FAILED, CANCELLED, INTERRUPTED |
| BLOCKED | IN_PROGRESS, CANCELLED, INTERRUPTED, FAILED |
| INTERRUPTED | IN_PROGRESS (via `recovery.resumed`), CANCELLED, UNKNOWN, FAILED |
| SUCCESS / PARTIAL / FAILED / CANCELLED / UNKNOWN | terminal: only `verification.completed` may attach |

"Checkpointed" is deliberately not a status (it would flip on every step); it is
`tasks.last_checkpoint_id` plus the `checkpoints` rows.

**Truthfulness guard:** `task.completed{status: SUCCESS|PARTIAL}` is refused unless
a non-empty `final` event exists for the task
(`test_success_requires_final_event_and_rolls_back`). `PARTIAL` is used when the
agent hit its step limit.

**Final-answer checks** (`SyraxAgent.run`, `agent.py`). Before the final is
returned, the answer is held to the task's own record. The outcome and
self-boast asks below go out at most once, never after a step-limit or loop
stop, and are journaled `claim.rejected`.

- *Console notes* (2026-10-26): a note in the console's style that the brain
  wrote itself (`[SYRAX ...]`, `CONSOLE_NOTE`), on its own line or at either end
  of the answer, is removed with a notice, before the asks and again after
  them; an answer that was only such a note is asked for once. A mention inside
  a sentence stays.
- *Outcome claims* (2026-10-26): `acted` holds the classes of the tools that
  succeeded this task (`classes_of`: `write`, `code`, `send`, `desktop`,
  `browser`; `playing` when a `desktop` result reads Playing,
  `PLAYING_READ`). `OUTCOME_CLAIMS` has four classes: `send` (sent, posted,
  paid, ordered; needs a `send` tool), `desktop` (played, volume or brightness
  set, an app opened or launched, clipboard, screenshot, notification; needs
  `desktop`), `browser` (a page or named thing opened, clicked, typed into, a
  form filled in or submitted; `browser` or `desktop`) and `playing` ("is
  playing", "plays now", "music started"; needs that media reading). A claim
  with no tool of its class is sent back once (`OUTCOME_NUDGE`); if it stays,
  it carries "(Not done: no <tool> tool ran in this task.)" (`OUTCOME_NOTE`,
  <tool> = sending, desktop, browser or desktop), for playing "(Not verified:
  nothing in this task read what is playing.)" (`PLAYING_NOTE`). Negations
  ("did not send", "nothing is playing") and reading idioms ("opened the
  file") are not claims. A tool whose level nothing declares (an MCP tool)
  stands for send, desktop and playing.
- *Self-boasts* (2026-10-26): an answer that claims unlimited or flawless
  ability (`BOAST`: "I have no limits", "my code is flawless", "every window
  bends to my will", "I control everything") in a task that is not autonomous
  and has not called `self_inspect` is sent back once to read it and answer
  from it (`SELF_NUDGE`). A boast that stays carries `SELF_NOTE` when the
  self-model was still not read, and `SELF_NOTE_READ` when it was read but the
  answer cites no figure; with the self-model read and a figure cited, the
  flourish is the persona's voice and no note follows.

## 4a. Tool permissions

Every tool call passes `SyraxAgent._permit` (`backend/syrax/permissions.py`)
before it runs; the persona no longer carries this rule, code does. Levels,
lowest first:

- `READ_ONLY` — observes (`self_inspect`, `recall`, `journal_query`, a file view, `ask_human`).
- `WRITE` — changes files or SYRAX's own state (editor edits, `remember`, `skill_create`, `release`).
- `EXTERNAL_READ` — reads from the network or a web page (`research`, `browser_*`).
- `SYSTEM` — acts on the host beyond files (desktop actions, shell commands from `python_execute`, an unknown or MCP tool).
- `EXTERNAL_WRITE` — sends, posts, pays (smtplib, webhooks, stripe, ...).
- `DESTRUCTIVE` — deletes or discards history (`shutil.rmtree`, `os.remove`, `git reset --hard`, ...).
- `harm` flag — the code kills processes, powers the machine off or changes
  system configuration; refused in every task kind, whatever the level.

Levels are static per tool; the polymorphic tools (`str_replace_editor`,
`python_execute`, `skill_create`, `desktop`) are refined per call from the
command, the source or the action. Policy by task kind (the table in the
module docstring):

| level | conversation | eval | autonomous |
|---|---|---|---|
| READ_ONLY | allow | allow | allow |
| WRITE | allow | allow | allow |
| EXTERNAL_READ | allow | allow | allow |
| SYSTEM | allow | allow | refuse |
| EXTERNAL_WRITE | authorize | by words | refuse |
| DESTRUCTIVE | authorize | by words | refuse |
| harm | refuse | refuse | refuse |

- **The human's words are the confirmation** (`named_in`): the request, or an
  earlier `ask_human` answer that was a yes, must contain the action verb
  (delete/remove/wipe/... for `DESTRUCTIVE`, send/post/pay/... for
  `EXTERNAL_WRITE`) *and* every extracted target (full path, wildcard pattern,
  or a basename of at least 3 characters). A call with zero extracted targets
  never counts as named.
- **Ask once per call signature** (`tool|level|sorted targets`): a
  `conversation` task asks through `ask_human` exactly for that call; the
  yes/no is kept in `grants` for the rest of the task, so the same call is not
  asked twice and a refused one stays refused.
- **Eval never asks**: a quality run is unattended; by words, or refused.
- **Silence is not consent**: only an affirmative answer allows. The
  `WebAskHuman` fallback strings ("No operator connected...", "The human did
  not answer in time...", "(no answer)") are refusals.
- **Refused calls are final**: the model gets `Error: refused...` instead of a
  result, the `tool_result` event carries `refused: true`, and the text tells
  the model not to retry but to do the rest or report.
- **Dynamic skills** may declare `risk` on their Skill class; the declared
  level can only raise the level their source shows (floor `WRITE`).
- **A protected file named by its basename is that file** (2026-10-25 audit): a
  literal in `python_execute` or `skill_create` code that ends in the basename of
  a judge (`devloop.JUDGES`), a key/evidence file or an owner file (`quality.py`,
  `journal.db`, `brains.json`, ...) is a target of that repository path, so
  `Path(d) / "quality.py"`, `os.path.join(root, "backend", "syrax", "guard.py")`,
  `f"{d}/journal.db"` and `"qual" + "ity.py"` are refused like the literal path,
  while a path computed at runtime is left to the runtime guard (`guard.py`) and
  the release gate (`devloop.judge_problems`).
- **Weakening the guard is harm** (`guard.WEAKENS_GUARD`, shared with
  `skills.UNSAFE`): code that assigns to, `setattr`s, `del`s, swaps in
  `sys.modules` or reloads `syrax.permissions`, `guard`, `devloop`, `journal` or
  `verify` (`permissions.JUDGES = ()`, `setattr(devloop, "JUDGES", ...)`, a
  monkeypatch of `decide`/`classify`/`run_gates`/`host_harm`) is refused for every
  task kind with "the code weakens SYRAX's own guard; a human changes the guard,
  by hand", and such a skill is refused before its tests run; reading them is fine.
- **An autonomous edit a release would refuse is refused before the edit**
  (2026-10-26, ROADMAP Phase 4 "know before changing"): in an `autonomous` task a
  `str_replace_editor` or `apply_patch` edit of a file tracked at HEAD that is an
  existing test (`test_*`, `*.test.ts`) or lies outside the self-modification
  scope is refused with the release's own words (`permissions.unreleasable` →
  `devloop.edit_problems`, judged in the task's worktree), not dozens of steps
  later at `release`. A new file is left to the release, a path git does not
  answer for is not refused, and human requests and quality cases are untouched.

## 5. Semantic checkpoints

`Journal.checkpoint()` writes a `checkpoints` row and a `checkpoint.created` event
in one transaction. The core checkpoints at real logical boundaries:

- after every completed tool step (`SyraxAgent.act` → `observed:<tool>`), with
  `completed_steps` (step, tool, ok), `evidence_state` (`SUCCESS` if the last tool
  succeeded, else `PARTIAL`), and `context` = the agent's non-system messages,
  bounded to 200 KB without splitting a tool-call/result pair;
- at `final`.

`env` records `git_head`, workspace root, cwd and `boot_id`. Verified by
`test_tool_task_records_steps_operation_and_checkpoints`,
`test_checkpoint_row_and_event_are_atomic_and_bound`.

## 6. Crash / power-loss recovery

On every `Journal` open (server `lifespan` and the first `get_journal()`), 
`recover_interrupted()` runs in one transaction:

1. select tasks `IN_PROGRESS|BLOCKED` whose `boot_id` is not this process;
2. for each, look at the last event, the last checkpoint and the in-flight
   `operation` (set by `tool.started`, cleared by `tool.completed|failed`);
3. **verify reality** (`verify_operation`):
   - `str_replace_editor create` → target file missing = `NOT_STARTED`, content equal = `COMPLETED`, else `PARTIAL`;
   - `str_replace_editor str_replace|insert` → `new_str` present and `old_str` absent = `COMPLETED`, the reverse = `NOT_STARTED`, both/neither = `UNCERTAIN`;
   - an `EXTERNAL_WRITE` call (`python_execute` whose code sends, a skill declared `EXTERNAL_WRITE`), or any tool with an `intent.recorded` this task never saw `intent.done` → `EXTERNAL_UNCERTAIN`, with the ledger entry as `recovery.intent`;
   - `ask_human` → `BLOCKED`; any other tool (`python_execute`, `browser_*`, `desktop`) → `UNCERTAIN`; no operation → `NONE`;
   - plus `journal_consistent`, `git_head_unchanged`, `workspace_present`;
4. classify: `BLOCKED` (question pending), `RESUMABLE` (`NONE|COMPLETED|NOT_STARTED`), else `UNCERTAIN`;
5. write `recovery.started`, per task `recovery.verified` + `task.interrupted` (status → `INTERRUPTED`, `tasks.recovery` = classification, `resume_from` = `checkpoint:<id>` or `goal`), then `recovery.completed`.

Idempotency: recovery events have deterministic `dedupe_key`s and the whole run
is one transaction, so a second run in the same or a later boot writes nothing
(`test_recovery_is_idempotent_across_reruns_and_boots`) and a crash inside
recovery loses nothing and is redone on the next boot
(`test_crash_inside_recovery_loses_nothing_and_next_boot_redoes_it`).

**Intent ledger** (`intent.py`, `test_intent_ledger.py`; audit 2026-10-25 "no idempotency keys for external side effects").
Before an `EXTERNAL_WRITE` call runs (`agent.py _execute_guarded`, after the permission gate allowed it) the agent
journals `intent.recorded {tool, args_hash, summary, step}`, and after it `intent.done {tool, args_hash, ok}`;
`args_hash` is the idempotency key (sha256 of the canonical JSON of the arguments, 16 hex). Only `EXTERNAL_WRITE`
calls are keyed, so the event sequence of an ordinary task is unchanged. A recorded entry the task never saw done
(a crash, a cancel, an exception inside the call) means the send may already have gone out. So does a call that
failed because it was abandoned or cut off while it ran (the MCP tool timeout, `python_execute`'s "Execution
timeout", a reset or dropped connection: `intent.uncertain`): it is journaled `intent.uncertain {tool, args_hash,
summary, step, why}` instead of `intent.done` and stays open (`test_intent_timeout.py`, 2026-10-26; a refused
connection or a bad argument did not go out and is done with `ok: false`). While an entry is open, the same arguments
again in that task are refused before anyone is asked (`intent.refused`, a final refusal like the gate's: "the same
<tool> action may already have gone out (step N): check what happened first; do not repeat it blindly"); a
finished one is caught by the repeat guard as before. Recovery classifies such an operation `EXTERNAL_UNCERTAIN`
(task `UNCERTAIN`) and carries the entry as `recovery.intent`, `hello.interrupted[].intent` and the
`task.interrupted` payload, so the UI and the HUD say "an external action may have happened: <summary>".

SIGKILL matrix (`test_sigkill_keeps_exactly_the_committed_state`): killed after
`task.started`, after five `think`s, mid-transaction, after `tool.started`,
after a checkpoint — the reopened journal holds exactly the committed rows and
`last_event_id` never points at a lost event. Runtime smoke (real server, real
`kill -9`, real restart) is described in the commit message of this change.

## 7. Resume

- `{"type":"resume","task_id"}` (or the RESUME button on the recovered notice)
  → `Core.resume()`: loads the last checkpoint's context into the agent,
  repairs dangling tool calls, adds a system note naming the step, stage,
  in-flight operation and its verified state ("verify before repeating"),
  records `recovery.resumed` (`INTERRUPTED → IN_PROGRESS`, new `boot_id`) and
  runs the agent with "Continue the interrupted task: <goal>"
  (`test_resume_continues_interrupted_task_with_restored_context`).
- Before that coroutine starts, a resumed conversation gets what a new task gets (`Core._prepare`, shared with
  `_begin`; audit follow-up 2026-10-26): the brain routed for it (`brain.routed` when a measured brain leads), the
  `understand` phase told to the UI, the agent's kind and the human's words, and a fresh step budget (the agent's
  default: the previous task's budget, a release objective's 30 steps, never leaks into it). The agent's memory is
  the checkpoint's context, not the human context kept aside for SYRAX's own work (`test_resume_fidelity.py`).
- SYRAX's own work is never resumed. A RESUME on an `autonomous` task answers "an autonomous attempt is not
  resumed; it is dismissed and the objective makes a fresh attempt", on an `eval` task "a quality case is run
  again by the suite, never resumed" (`core.OWN_WORK_NOT_RESUMED`; the UI shows the answer as the notice), and
  the task is dismissed the way the boot policy (7.1) dismisses it: `task.cancelled` with that note (the human's
  note and session beside it), an objective still `ACTIVE` for the attempt back to `OPEN` ("task <id> dismissed
  on resume: <note>"), and for an `UNCERTAIN` attempt, which still needs force and a note first, the
  `uncertain-task:<id>` question DROPPED. No `recovery.resumed`, no `task.resume_forced`: nothing was resumed.
- A task whose recovery carries an `intent` (or whose journal holds an `intent.recorded` without `intent.done`)
  gets one more sentence in that note, force or not: "An external action may already have happened: <summary>.
  Never repeat it; verify with a read-only check and report." The agent's ledger is seeded with the open entries,
  so the same send is refused even if the model tries it, and the refusal without `force` names the send too
  (`test_a_resumed_task_is_told_about_the_send_and_held_from_repeating_it`).
- Auto-resume at boot is **off** by default. `SYRAX_AUTO_RESUME=1` resumes only
  conversations classified `RESUMABLE` (SYRAX's own work is left to the boot policy, 7.1); `UNCERTAIN` and
  `BLOCKED` tasks always wait for a human.
- `ResumeHook` on `Journal.recover()` is the seam for later autonomous phases.
- `{"type":"dismiss","task_id","note"}` (or the DISMISS button beside RESUME, on the
  recovered notice and in the WHY view, after a confirm) records `task.cancelled`
  (`INTERRUPTED -> CANCELLED`, `error` = "dismissed by human: <note>") and DROPs the
  `uncertain-task:<id>` objective that asked about it.

### 7.1 Boot policy for interrupted tasks

SYRAX restarts itself into new code several times a day, so an interruption is routine.
Live 2026-10-25 (audit, "Task runtime"): an eval case cut by a restart and two autonomous
attempts superseded by later commits sat `INTERRUPTED` for 3-11 days until a hand dismissed
them. `Core.settle_interrupted()` runs in the server lifespan right after `auto_resume()` and
before `requeue_after_boot()`; every dismissal is journaled as `task.cancelled {"error": <note>}`
(`tasks.error` = the note), one warning line summarizes the boot, and the result is
`{"dismissed": [...], "kept": [...]}` (`test_boot_policy.py`). Age is the time since recovery
marked the row `INTERRUPTED` (`tasks.updated`).

| kind | recovery | age | decision | note / side effect |
|---|---|---|---|---|
| `eval` | any | any | dismiss | "a quality case cut by a restart; the suite runs it again" (the quality runner never resumes a case) |
| `autonomous` | `RESUMABLE` or `BLOCKED` | any | dismiss | "an autonomous attempt cut by a restart; the objective makes a fresh attempt"; an objective still `ACTIVE` for this task (its `last_task_id`, or the goal the cycle submitted) goes back to `OPEN` with the note |
| `autonomous` | `UNCERTAIN` | < 7 days (`SYRAX_SETTLE_UNCERTAIN_S`) | keep | the `uncertain-task:<id>` BLOCKED objective asks a human (autonomy.derive_objectives) |
| `autonomous` | `UNCERTAIN` | >= 7 days | dismiss | "UNCERTAIN for 7 days, nobody resumed it; dismissed"; the `uncertain-task:<id>` objective is DROPPED with the same note |
| `conversation` | `RESUMABLE` or `BLOCKED` | < 1 h (`SYRAX_SETTLE_CONVERSATION_S`) | keep | the human may resume it: `hello.interrupted` shows it with RESUME and DISMISS |
| `conversation` | `RESUMABLE` or `BLOCKED` | >= 1 h | dismiss | "interrupted N h ago; too old to continue safely" |
| `conversation` | `UNCERTAIN` | any | keep | it is the human's work: they resume (force + note) or dismiss it in the UI |
| other kinds | any | any | keep | nobody's to dismiss at boot |

`Autonomy.recover_active()` (run when the core is built, before the policy) already reopens every
`ACTIVE` objective and logs the interrupted attempt with its kept diff; the policy's reopening is the
guard for an objective marked `ACTIVE` after that.

## 8. Journal write failure

If the journal cannot record an event (`sqlite3.Error` / `JournalError`), the
core logs it, forwards the event to observers with `"unjournaled": true`, and
never claims success: the task ends with an `error` and stays `IN_PROGRESS`
(marked `INTERRUPTED` on the next boot) —
`test_journal_write_failure_never_fakes_success`.

## 9. Verification gate (`python -m syrax.verify`)

Gates are real subprocesses; the exit code decides `PASS|FAIL`; a gate that
cannot run is `NOT_VERIFIED`. `GREEN` only if every *required* gate is `PASS`.
Default gates: `py_compile`, `pytest`, `tsc`, `eslint`, `node_test`, `next_build`
(built from an isolated copy so a live `next start` is never disturbed),
`diff_scan` (secrets, `print(`/`console.log`/`debugger` in non-test files,
junk untracked files), and an optional `performance` gate that is `NOT_VERIFIED`
until a benchmark exists. Results are stored in `verifications` with per-gate
evidence (`test_verify.py`).

## 10. Known limitations (honest list)

- Tasks are agent turns of kind `conversation`, `eval` (the quality suite) or
  `autonomous` (the autonomy cycle's `core.submit(..., kind="autonomous")`).
- Only `str_replace_editor` operations are verified against reality; all other
  tools are `UNCERTAIN` after a crash (a send or payment `EXTERNAL_UNCERTAIN`, with its intent ledger entry;
  whether it went out is still for a human or a read-only check to find).
- Retention is partial: once a day an idle cycle prunes `think` / `brain.*`
  events of tasks that ended more than 30 days ago and truncates the WAL
  (`Journal.maintain`, `docs/OPERATIONS.md` "Journal maintenance"); task rows,
  knowledge and evidence are never deleted, so the journal still grows (tool
  outputs are capped at 4000 chars, images are not stored).
- One agent, one running task at a time; human requests made meanwhile wait
  in the `PENDING` queue and start oldest first (section 4, "Queue"); SYRAX's
  own eval and autonomous work never queues.
- Long-term facts (`remember` / `recall` / `forget`) are knowledge rows of kind
  `human` (confidence 1.0, basis "human said"); a legacy `memory.json` is imported
  once and then left untouched; forgetting deletes the row and journals
  `knowledge.forgotten`. Only text grounded in the human's words for the task is
  stored at 1.0; what the model inferred becomes an observation at 0.5 (basis "SYRAX
  inferred from the conversation"). `forget` matches whole words of three or more
  characters and refuses to delete more than five rows unless the human said
  "forget everything about X". The memory panel's EDIT (`memory_correct`) rewrites
  one fact in place through the same `knowledge.updated` event (basis "human
  corrected (UI)", confidence 1.0, type kept), and the `memories` reply carries each
  fact's basis, confidence and type. `memory_export` (or `python -m syrax.memory
  --export`) writes `backend/config/exports/memory-<stamp>.json` (gitignored, written
  atomically) with the facts and the conclusion/web knowledge rows and their sources,
  every string run through the credential mask.
- Conversation history for the prompt comes from `tasks` (kind conversation,
  SUCCESS/PARTIAL); `history.jsonl` is no longer written and is read only as a
  fallback when the journal has no conversations yet.
- The frontend only shows recovered/running notices; no LIVE/HISTORY/WHY view yet.
- Permissions: the write scope of `python_execute` cannot be checked (the
  paths live inside the code), so writes outside the repository are allowed.
- Permissions: targets are extracted from string literals only; a protected
  basename in any literal counts as that file (2026-10-25), but a path computed
  at runtime (`"".join(parts)`, a name read from a file, a variable) yields no
  target, so a human gets asked once and autonomous work gets refused.
- Permissions: a crash while a permission question is pending is classified
  `UNCERTAIN` by recovery (the safe side), like any `python_execute` call.
- Permissions: in-process code shares the process with `permissions.py`;
  `devloop.JUDGES` prevents a *released* weakening of the policy and
  `guard.WEAKENS_GUARD` the written shapes of a runtime monkeypatch from
  `python_execute` or a skill (an assignment, `setattr`, `sys.modules`,
  `reload`, also through an alias); a module reached by a computed name is not caught.

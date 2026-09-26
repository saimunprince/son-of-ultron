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
   - `ask_human` → `BLOCKED`; any other tool (`python_execute`, `browser_*`, `desktop`) → `UNCERTAIN`; no operation → `NONE`;
   - plus `journal_consistent`, `git_head_unchanged`, `workspace_present`;
4. classify: `BLOCKED` (question pending), `RESUMABLE` (`NONE|COMPLETED|NOT_STARTED`), else `UNCERTAIN`;
5. write `recovery.started`, per task `recovery.verified` + `task.interrupted` (status → `INTERRUPTED`, `tasks.recovery` = classification, `resume_from` = `checkpoint:<id>` or `goal`), then `recovery.completed`.

Idempotency: recovery events have deterministic `dedupe_key`s and the whole run
is one transaction, so a second run in the same or a later boot writes nothing
(`test_recovery_is_idempotent_across_reruns_and_boots`) and a crash inside
recovery loses nothing and is redone on the next boot
(`test_crash_inside_recovery_loses_nothing_and_next_boot_redoes_it`).

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
- Auto-resume at boot is **off** by default. `SYRAX_AUTO_RESUME=1` resumes only
  tasks classified `RESUMABLE`; `UNCERTAIN` and `BLOCKED` tasks always wait for a human.
- `ResumeHook` on `Journal.recover()` is the seam for later autonomous phases.

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

- Tasks are conversational agent turns; `kind='autonomous'` is accepted by the
  schema but nothing creates such tasks yet.
- Only `str_replace_editor` operations are verified against reality; all other
  tools are `UNCERTAIN` after a crash.
- No retention policy: the journal grows (tool outputs are capped at 4000 chars,
  images are not stored).
- One agent, one running task at a time; `PENDING` queueing exists in the
  journal but the core does not schedule queued tasks.
- `history.jsonl` is still written for prompt injection; it is now derivable
  from `tasks` and can be retired later.
- The frontend only shows recovered/running notices; no LIVE/HISTORY/WHY view yet.

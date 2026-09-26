# SYRAX Autonomy (objectives + bounded cycle)

Implemented in `backend/syrax/autonomy.py`; tests in `backend/syrax/test_autonomy.py`
and the autonomy section of `backend/syrax/test_bridge.py`.

## Objectives

Table `objectives` in the journal: `goal, reason, priority (1 = highest), status,
source (human | selfmodel), check_spec, evidence, progress, dependencies,
next_action, attempts, last_task_id, key (unique, for idempotent derivation)`.

Status transitions (anything else is refused):

| from | to |
|---|---|
| OPEN | ACTIVE, BLOCKED, DROPPED, DONE |
| ACTIVE | OPEN, DONE, BLOCKED, DROPPED |
| BLOCKED | OPEN, DROPPED, DONE |
| DROPPED | OPEN |
| DONE | terminal |

Events: `objective.created / updated / completed / blocked / dropped`,
`cycle.started / completed`, `reflection.created`, `autonomy.toggled`.

### Where objectives come from

- **Human**: WebSocket `objective_add {goal, reason?, priority?}` (check = `task_success`).
- **Self-model weaknesses** (`derive_objectives`, run at the start of every cycle, idempotent by key):
  - a registered tool with no journal evidence → `verify-capability:<tool>` (P5, check `tool_verified`);
  - a tool whose last use failed → `repair-capability:<tool>:<failures>` (P2, check `tool_verified`);
  - last verification BLOCKED → `verification-blocked:<ts>` (P1, check `verification_green`);
  - an interrupted task with an UNCERTAIN operation → `uncertain-task:<id>`, created **BLOCKED** with check `human`;
  - a quality case that failed in the last two runs → `quality-case:<case>:<run>` (P2, check `quality_case_passes`): read the case and the journaled task, fix SYRAX's code or prompts, `release`;
  - a tool that raised a traceback inside `backend/syrax/` → `tool-bug:<tool>:<file>:<line>` (P2, check `tool_verified`): fix the bug, add a test, `release`, call the tool again.
  These two are how SYRAX turns measured weaknesses into code changes of its own; the change only exists if `release` reports COMMITTED.
  - At most one live (OPEN/ACTIVE/BLOCKED) objective per tool.
  - Never for tools that cannot be exercised harmlessly without a real need
    (`release`, `skill_create`, `skill_test`, `learn`, `remember`, `forget`,
    `experiment`, `present`, `terminate`, `ask_human`): verifying them on their
    own would mean junk releases, junk skills or fake memories. Their evidence
    comes from real use; stale objectives of that kind are DROPPED.

## The cycle (`Autonomy.run_once`)

```
enabled?  ──no──▶ DISABLED
core busy? ─yes─▶ BUSY            (a human task always wins)
resource pressure? ─yes─▶ SKIPPED (load per core > 1.5 or < 1 GB RAM free)
derive objectives from the self-model
pick highest-priority OPEN objective whose dependencies are DONE   ── none ──▶ IDLE
already satisfied by evidence? ──yes──▶ DONE, no task run
mark ACTIVE, submit ONE autonomous task through the core (kind = "autonomous")
wait for it
judge from journal evidence  →  DONE | RETRY | BLOCKED
reflect: reflection.created {expected, actual, verdict, lesson, attempt}
```

**Judging is evidence-only.** `tool_verified` needs the tool to have run *after*
the objective was created and its last outcome to be ok; the model saying
"I verified it" without a tool call is a RETRY with the lesson "the task never
called the tool" (`test_model_claiming_success_without_evidence_is_not_done`).
`verification_green` needs a GREEN verification newer than the objective.
`task_success` (human goals) needs the task to end SUCCESS, which itself needs
a journaled final. `human` is never auto-completed.

Bounds: one cycle at a time (a second `cycle_now` or loop tick reports BUSY); turning AUTO off does not reopen the objective of a cycle that is still running; one task per cycle; `MAX_ATTEMPTS = 3` then BLOCKED with
`next_action = "needs a different strategy or a human"`; interval
`SYRAX_CYCLE_INTERVAL` (default 120 s) after a run, 600 s when idle; blocked
objectives are never retried blindly.

## Switching it on

- Off by default. WebSocket `autonomy {enabled: true|false}` persists the flag in
  the journal (`meta.autonomy_enabled`) and starts/stops the background loop.
  `SYRAX_AUTONOMY=1|0` overrides the stored flag. The AUTO button in the HUD
  toggles it.
- `cycle_now` runs one cycle immediately (ignores the enabled flag, still refuses
  while a task runs).
- `objectives {limit}` lists objectives; `hello` carries `autonomy` status.

## What this is not (yet)

- No research engine: the agent works only with its current tools.
- No self-modification: autonomous tasks do not change the codebase; the
  verification gate exists but no objective type drives code changes through it.
- No natural-language planning beyond the single autonomous brief; lessons are
  derived strings, not model reflections.
- Resource gate looks at CPU load and free RAM only.

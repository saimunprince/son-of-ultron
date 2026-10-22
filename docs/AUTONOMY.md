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

- **Human**: WebSocket `objective_add {goal, reason?, priority?, check}`; the check is required (a check-less
  objective is BLOCKED without a task), see `server.OBJECTIVE_CHECKS`.
- **Human, with a proven repro** (`brief_add`, below): a `change_released` objective pinned to a test that
  judge code saw fail on a clean tree of HEAD.
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

### Briefs with a proven repro (`backend/syrax/repro.py`, 2026-10-22)

Measured 2026-10-19: 208 of 243 DONE objectives changed nothing; all 23 that changed the code came from a
human's brief, and the briefs that landed first time carried a test the human had run on a clean tree and
seen fail. `repro.py` (a judge: in `devloop.JUDGES`) does that part without trusting any model:

- `brief_check {test_path, test_code, files?, fix_diff?}` / `brief_add {goal, test_path, test_code, files,
  fix_diff?, reason?, priority?}` over the WebSocket, or `python -m syrax.repro --check TEST --as
  backend/syrax/test_x.py --files ... [--fix DIFF]` read-only.
- `screen`: a new `backend/syrax/test_*.py` that asserts something other than a constant, imports the module
  the brief changes, holds no secret-shaped literal and does nothing above WRITE; the brief changes only
  non-judge modules in `backend/syrax`.
- `prove`: pytest in a throwaway worktree of HEAD under `%TEMP%`, with the tracked secret-free config: RED
  (assertions failed twice the same way), RED_ERROR (only errors, e.g. a name the change adds), NOT_RED or
  INVALID; with a fix diff, PROVEN (the test and every test importing a changed module pass), NOT_FIXED,
  CONTRACT (an existing test pins the old behaviour: a human decides) or FIX_DOES_NOT_APPLY.
- `file_brief`: P1 `change_released` objective, key `repro-brief:<sha256[:16]>`, check `{files, repro: {test,
  sha256, base, verdict, text}}`, the verbatim test in the goal.
- The cycle writes the test into the task's worktree (`core.write_seed`); the release refuses a missing,
  changed or no-longer-red test and any file outside the brief (`repro.release_problems`, called by
  `DevLoop.inspect`); the `change_released` judge needs the newest commit holding the test to match the
  pinned sha256 (`repro.fidelity`).
- `python -m syrax.repro --replay <commit>...` proves a commit's added test against its parent with the
  rest of the commit as the fix: the acceptance run for this module.

**Repro hunts (phase 2).** In the service (`SYRAX_ISOLATE=1`; `SYRAX_REPRO=1/0` overrides) the cycle derives
at most one `repro_proven` objective at a time, three a day, key `repro:<signal>:g1`, P2, source `repro`, from
failures after the `repro_since` watermark (set on the first cycle) and within a week:

- a tool's own error (not refused, not a caller's mistake, not the environment) in two tasks, for a tool
  implemented in a non-judge module, whose module has not changed since;
- a quality case that failed twice the same way, after SYRAX's own claim check, nudge, guard refusal or tool
  error in the trace (a failure with none of these is the model's choice);
- the same exception in two tasks ([MAINTENANCE] tasks run judge code and are left to the human).

The hunt's task never releases (`repro.release_problems` refuses it): it leaves one new test and the fix in
its worktree, or answers `NO CODE CAUSE` (BLOCKED, no follow-up). After it, `repro.harvest` reads the kept
snapshot, screens the test, requires it to quote 12+ characters of the evidence and to fail on HEAD by an
assertion (an ImportError of a name the fix adds proves nothing), proves test and fix, refuses files a
quality case names, and files the P1 brief (source `repro`) that lands like any other; `repro.proven` makes
the hunt DONE.

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

- Hunts read the journal's failures only: a defect nobody's task ran into is not found, and a failure in a
  judge file (python_execute, release, the ledger) is left to the human.
- No natural-language planning beyond the single autonomous brief; lessons are
  derived strings, not model reflections.
- Resource gate looks at CPU load and free RAM only.

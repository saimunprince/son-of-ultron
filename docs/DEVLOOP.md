# SYRAX Autonomous Development Loop

Implemented in `backend/syrax/devloop.py`; tests in `backend/syrax/test_devloop.py`
(throwaway git repositories, fake gates) and the release section of
`test_bridge.py` (the agent edits, releases, is rolled back, changes approach,
and the second release commits).

## Flow

```
model edits files (str_replace_editor, skill_create)     → code.changed {path, command} per repo edit
release {summary}
  inspect   git status/diff; refuse: empty diff, files outside SCOPE, FORBIDDEN
            paths, secret/debug findings from the diff scan
  snapshot  full diff + new files → backend/config/rollback/<ts>-<head>.patch
            (kept for study even when the release succeeds); code.changed {files, stat}
  gate      verify.run_gates (py_compile, pytest, tsc, eslint, node test, isolated
            next build, diff_scan) → verification.completed (journaled with evidence)
  GREEN     git add <files>; git commit "syrax: <summary>" with
            "Verified-By: syrax.verify #<id>"; commit.created
            push only when SYRAX_AUTOPUSH=1 → push.started / push.completed / push.failed
  BLOCKED   git checkout -- <tracked>; delete new files; rollback.created with the
            failing gates' evidence; the tool output tells the model to change approach
```

Scope (`SCOPE`): `backend/syrax/`, `backend/skills/`, `backend/requirements-syrax.txt`,
`frontend/components/`, `frontend/lib/`, `frontend/app/`, `docs/`, `README.md`.
Forbidden anywhere: `.env`, `config/config.toml`, `config/brains.json`,
`journal.db`, `.git/`, `node_modules/`, `.venv/`, `.next/`.

## Truthfulness

- COMMITTED only after the same gate a human release uses returned GREEN;
  the verification id is in the commit message and the `verifications` table.
- ROLLED_BACK is verified by re-reading `git status` (`clean: true/false` in the event).
- The report is built from exit codes and git output only.

## Objectives

An objective with check `change_released` is DONE only when a `commit.created`
event exists after the objective was created; a rolled-back attempt counts as
RETRY with the lesson "the gate rolled it back".

## Defaults and limits

- `SYRAX_AUTOPUSH` is off: SYRAX commits locally, a human pushes.
- The gate runs the whole suite (about a minute); one release per task step.
- Commits are authored as `SYRAX <syrax@localhost>`.
- No benchmark gate yet (performance stays NOT_VERIFIED, optional).
- Rollback restores tracked files and removes new ones; it does not undo
  side effects outside the repository (installed packages, files elsewhere).

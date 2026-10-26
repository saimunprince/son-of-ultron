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
  GREEN     own work (autonomous/eval task): a different brain reviews the diff,
            new files whole (review.py) → review.completed; rejected → rollback,
            REVIEW_REJECTED; no brain could review it → review.unavailable, rollback,
            REVIEW_UNAVAILABLE (held, nothing committed, the objective stays open)
            git add <files>; git commit "syrax: <summary>" with
            "Verified-By: syrax.verify #<id>"; commit.created
            push only when SYRAX_AUTOPUSH=1 → push.started / push.completed / push.failed
  BLOCKED   git checkout -- <tracked>; delete new files; rollback.created with the
            failing gates' evidence; the tool output tells the model to change approach
```

Scope (`SCOPE`): `backend/syrax/`, `backend/skills/`, `frontend/components/`,
`frontend/lib/`, `frontend/app/`, `docs/`, `README.md`.
`backend/requirements-syrax.txt` (`DEPENDENCIES`) is out of scope since the 2026-10-25
audit: a release touching it is refused with "dependencies are the owner's decision:
propose, do not change" (radar proposes upgrades; the human installs them).
Forbidden anywhere: `.env`, `config/config.toml`, `config/brains.json`,
`journal.db`, `.git/`, `node_modules/`, `.venv/`, `.next/`.

Known before the edit (2026-10-26): `edit_problems(path, root)` answers what a
release would refuse about one path tracked at HEAD (an existing test, a file
outside the scope), and `permissions` refuses an autonomous `str_replace_editor`
/ `apply_patch` edit on that answer, so the task learns it at the first edit,
not at `release`. A new file is left to the release.

## A task owns only its own changes

When a task starts, the working tree's pre-existing modifications are recorded
(`DevLoop.begin_task`). `release` considers only files changed since then; if
the only changes predate the task it refuses ("a human's uncommitted work"),
and rollback restores only the task's files. Before the gate runs, every
changed Python file must compile (a pure syntax check) — a broken file is
refused in seconds instead of blocking the gate after two minutes.

When an autonomous or eval task ends without a COMMITTED release — step limit,
failure, cancel — the core rolls back the task's own edits (snapshot kept,
`rollback.created` with reason "task ended without a committed release"), so a
restart can never load half-finished code. Human conversations are left alone.

Learned from the first live self-modification run: the model's edit broke a
string literal, the gate correctly rolled it back twice, the task hit its step
limit with the broken file still on disk, and the rollback had restored every
modified file in the tree, including an operator's unrelated work.

## Cross-brain review (own work)

After a GREEN gate, an autonomous or eval release is read by a brain that did
not write it (`review.py`, reviewer set by `core._cross_review`). Three rules
closed by the 2026-10-25 audit:

- A review that could not happen is not an approval. When no other brain is
  enabled, or every one of them errored or answered unreadably, `review.review`
  returns `available: False` with `brains_tried`, and the release is HELD:
  outcome `REVIEW_UNAVAILABLE`, the edits rolled back exactly like a rejection
  (snapshot kept, `rollback.created`), `review.unavailable {reason, brains_tried}`
  journaled, nothing committed; the report tells the brain the objective stays
  open. Before, one enabled brain meant the review was skipped and the change
  landed unreviewed. A conversation's release (the human is its reviewer) and
  the human's explicit opt-out `SYRAX_REVIEW=0` commit as before.
- The reviewer reads new files whole, as `/dev/null` diffs (`inspect` hands their
  content over as `new_files`), not their names alone; the diff is capped at
  `review.MAX_DIFF` (24,000 chars, a module change plus its new test) and, when
  cut, says "… N more lines not shown: reject if you cannot judge it".
- `backend/syrax/selfedit.py` (it chooses which tests the preflight runs) and
  `backend/syrax/conftest.py` (the environment the pytest gate runs in) are in
  `JUDGES`: only a human commit changes them.

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

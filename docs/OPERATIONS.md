# SYRAX 24/7 Operation

What keeps SYRAX safe to leave running on the owner's laptop. Implemented in
`backend/syrax/resources.py`, `Journal.maintain()` and the autonomy cycle;
tests in `backend/syrax/test_resources.py`.

## Resource gate (`resources.pressure`)

Measured every cycle and shown in the AUTO button, `autonomy_status` and the
self-model runtime. Optional work (autonomous cycles) is skipped when any of
these holds; a human's `cycle_now` and human tasks are never blocked by it:

| signal | threshold |
|---|---|
| quiet hours | `SYRAX_QUIET_HOURS="23-7"` (wraps midnight) |
| CPU | 1-minute load per core > 1.5 |
| RAM | MemAvailable < 1024 MB |
| disk | free space under the backend < 2 GB |
| battery | discharging and < 30 % |

Unmeasurable values (no battery, no /proc) are never treated as pressure.

## Long-running behaviour

- The core keeps running when the browser is closed; sessions replay on reconnect.
- The autonomy loop runs one bounded cycle per interval (`SYRAX_CYCLE_INTERVAL`,
  default 120 s after work, 600 s when idle) and never starts a cycle while a
  task is running.
- Interrupted tasks are recovered at boot; `SYRAX_AUTO_RESUME=1` resumes the
  RESUMABLE ones.
- systemd user service (`syrax.sh --install-service`) restarts on failure.

## Journal maintenance (real idle work)

When a cycle finds no open objective and maintenance is due (once per 24 h,
`meta.last_maintenance`), `Journal.maintain(retain_days=30)`:

- for tasks that ended more than 30 days ago: deletes `think` and `brain.*`
  events and empties the saved checkpoint context;
- keeps task rows, tool/ask/final/checkpoint events, verifications, knowledge,
  objectives and skills;
- truncates the WAL (`PRAGMA wal_checkpoint(TRUNCATE)`);
- journals `maintenance.completed` with measured counts and sizes.

Running tasks and recent tasks are untouched; a second run prunes nothing.

## Backups and restore (`backend/syrax/backup.py`)

What: `backend/config/journal.db` (the whole evidence: tasks, events, verifications,
objectives, knowledge, skills), `brains.json` (the API keys), `memory.json` and
`config.toml`. None of them is in git; the journal was lost once when the project
moved to Windows (2026-09-30).

Where: `backend/config/backups/<YYYYMMDD-HHMMSS>/` with a `manifest.json` (created,
git head, size and sha256 of every file, row counts and `integrity_check` of the
copied journal). The folder is gitignored and **holds the API keys**: keep it as
private as `brains.json` itself. The journal is copied with SQLite's online backup
API on the live connection (`Journal.backup_to`), so the copy is one consistent
state while SYRAX keeps writing, written as a plain database file (no `-wal`/`-shm`
beside it). `ws.token`, `mcp.json`, the workspace, skills, logs and rollback
patches are not copied.

When: an idle autonomy cycle once per 24 h (`meta.last_backup`), before journal
maintenance prunes anything; the newest 7 snapshots are kept, older stamped
folders with a manifest are removed and nothing else in the folder is touched.
`backup.completed` / `backup.failed` are journaled. By hand at any time, SYRAX
running or not:

    python syrax.py --backup

prints the folder and the verdict of `verify` (sha256, integrity, counts) and
exits 1 when the copy does not verify. Beside a running SYRAX the copy is made
through a read-only handle and is not journaled.

How to restore (a human act; there is no agent tool for it and none may be added):

    python syrax.py --stop
    python syrax.py --restore backend/config/backups/<stamp>
    python syrax.py

Restore refuses while SYRAX runs (pid file, backend port, journal owner lock) and
refuses a snapshot that does not verify. The current files, with the journal's
`-wal`/`-shm`, are moved to `backend/config/backups/_replaced-<stamp>/` first, so
a restore can itself be undone. On a new machine: clone the repository, copy one
snapshot folder into `backend/config/backups/`, run the three commands above.

Checked by `backend/syrax/test_backup.py`: manifest counts match, a flipped byte
is caught, prune keeps 7, due follows the meta key, restore reproduces the rows
and refuses while running, the idle cycle backs up before maintenance.

## Known-good fallback after a restart (`syrax.py`, `backend/syrax/knowngood.py`)

SYRAX restarts itself into new code (`syrax.py --respawn`, then `--restart`), and
every start runs the core from the repository at main's HEAD. New code lands on
main only after a GREEN gate; if the new core still does not come up, the launcher
brings back the last commit that did. It never resets, checks out or reverts main
or the repository's working tree.

**Known-good.** When a core started from main answers `/health` and is still
running `KNOWN_GOOD_SETTLE_S` (120 s) after its first answer, the launcher writes
that commit to `backend/config/known_good.json` (`{"commit", "at"}`, written to a
temporary file and renamed; gitignored).

**Fallback** (service starts only: the login service, `--restart`, a self-restart;
a foreground `python syrax.py` behaves as before). The core from main has not come
up when it exits before it is known-good, or when it has not answered `/health`
within `CORE_BOOT_DEADLINE_S` (180 s). If `known_good.json` names a different
commit K, the launcher:

1. makes or reuses a git worktree of K at `.syrax/known-good`
   (`git worktree add --force --detach .syrax/known-good K`, or
   `git -C .syrax/known-good checkout --detach K` when it is at another commit;
   if that checkout fails it keeps the earlier known-good commit it is at);
2. stops the failed core;
3. hard-links `backend/config/config.toml` and `mcp.json` into the worktree (the
   same files, not copies) and points the rest at the live files through the
   environment: `SYRAX_JOURNAL_FILE`, `SYRAX_TOKEN_FILE`, `SYRAX_BRAINS_FILE`,
   `SYRAX_MEMORY_FILE`, `SYRAX_HISTORY_FILE`, `SYRAX_EXPORT_DIR`,
   `SYRAX_SKILLS_DIR`, `SYRAX_BROWSER_PROFILE`;
4. records the failed commit X in `known_good.json` (`bad`, `bad_at`, `bad_why`);
5. runs `python -m syrax.knowngood` from the worktree (K's code, while no core owns
   the journal), which journals `restart.fallback` `{from: X, to: K, why}` and a
   reminder due 120 s later;
6. starts the core from `.syrax/known-good/backend` with the live venv, on the same
   port. The UI keeps running from the repository.

The fallback core's own reminder loop fires that reminder: a notice the UI shows
and speaks, and a desktop notification, also when no UI was connected at boot.
`syrax.log` has a line for each step.

**While on the fallback** the core serves the human but does no work on its own
code: `SYRAX_AUTONOMY`, `SYRAX_SELF_RESTART`, `SYRAX_ISOLATE`,
`SYRAX_PUBLISH_RISE`, `SYRAX_CODEBENCH`, `SYRAX_FEATURES` and `SYRAX_AUTOPUSH` are
0 for it (a release there would commit to the detached worktree). There is no
loop: the fallback is tried once per launch, a fallback core that fails is not
followed by another, and a later service start (login) whose HEAD is still the
known-bad X starts K straight away instead of failing again. A new commit on main
is tried at the next start; a human `python syrax.py --restart` clears the
known-bad mark and tries main again whatever it holds (SYRAX's own restart passes
`--self-restart` and keeps the mark). When main comes up and settles, it becomes
the known-good commit and the mark goes.

Back to normal after a fallback: fix main, then

    python syrax.py --restart

Checked by `backend/syrax/test_knowngood_launcher.py` (the decisions, the marker
file, the git commands, a real worktree in a temporary repository, the loop with
fake processes and clock, who clears the mark) and `test_knowngood.py` (the
journal event and the notice).

## What is not covered

- GPU, network bandwidth and temperature are not measured.
- No disk quota for `backend/workspace/`, `backend/skills/` or rollback snapshots.
- Maintenance never deletes tasks or knowledge; there is no full-history compaction.
- Backups stay on the same disk; copying a snapshot folder somewhere else is the owner's job.
- The known-good fallback swaps only the core: a broken UI or launcher (`syrax.py` itself) in the
  new commit is not covered, and the fallback core uses its own `backend/workspace` and logs.
  It needs at least one start that came up after this feature landed (the first known-good).
- Credential masking happens when the journal writes: the agent's live memory, the
  `user` echo to connected UIs and a `final` the human asked a key for keep the real
  text, and a task resumed from a checkpoint reads `[credential masked]` where a key was.

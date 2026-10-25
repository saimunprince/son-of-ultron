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

## What is not covered

- GPU, network bandwidth and temperature are not measured.
- No disk quota for `backend/workspace/`, `backend/skills/` or rollback snapshots.
- Maintenance never deletes tasks or knowledge; there is no full-history compaction.
- Backups stay on the same disk; copying a snapshot folder somewhere else is the owner's job.
- Credential masking happens when the journal writes: the agent's live memory, the
  `user` echo to connected UIs and a `final` the human asked a key for keep the real
  text, and a task resumed from a checkpoint reads `[credential masked]` where a key was.

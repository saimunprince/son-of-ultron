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

## What is not covered

- GPU, network bandwidth and temperature are not measured.
- No disk quota for `backend/workspace/`, `backend/skills/` or rollback snapshots.
- Maintenance never deletes tasks or knowledge; there is no full-history compaction.

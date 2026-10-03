# SYRAX — Handover and setup

Read this on a fresh machine: how to set SYRAX up again, what to back up before
wiping an OS, and the operating rules that proved necessary. What exists and
how well it is verified lives in the documents linked below.

**2026-09-30 — moved to Windows 11.** The OS was wiped; the repo now runs
natively on Windows (no WSL). What changed: `syrax/sysinfo.py` answers RAM,
load, battery and uptime on both platforms; `desktop.py` has a Windows backend
(Start Menu apps, `os.startfile`, media/volume keys, PIL screenshots,
PowerShell clipboard and tray notifications, `LockWorkStation`); `browser.py`
finds Chrome/Edge/Brave under Program Files and kills the tree with
`taskkill`; `verify.py` copies the scratch build with `shutil` and a junction
instead of `rsync`/`cp -al`, and resolves `.venv/Scripts/python.exe`;
`syrax.py` is the one launcher for Windows, Linux and macOS (it also installs
what is missing; `syrax.sh` / `syrax.ps1` just call it), with a login service
on each OS (systemd / launchd / Task Scheduler). macOS backends exist in
`sysinfo.py`, `desktop.py` and `browser.py` but have not been run on a Mac.
Linux paths are untouched. The journal, brain keys and skills from the old laptop
were **not** carried over (see §5): SYRAX starts here with an empty history.


> Status moved on 2026-10-03: the measured snapshot is [`SYRAX_STATUS.md`](../SYRAX_STATUS.md), the per-capability evidence is
> [`CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md) (generated), the phase plan is [`ROADMAP.md`](ROADMAP.md), the architecture is
> [`ARCHITECTURE.md`](ARCHITECTURE.md). What remains here is how to set SYRAX up, back it up and operate it.

## 4. Setting up on a new machine

Prerequisites: Linux with a GNOME/Wayland session, Windows 11 or macOS
(desktop tool), Python 3.12 or `uv`, Node 22+, Chrome/Chromium/Edge (browser
tool), git. `python syrax.py` does the whole setup below by itself; the manual
steps remain for reference. On Windows use `.venv\Scripts\python.exe`
wherever the commands say `.venv/bin/python`.

```bash
git clone git@github.com:saimunprince/son-of-ultron.git
cd son-of-ultron

# backend
cd backend
uv venv .venv --python 3.12            # or: python3.12 -m venv .venv
uv pip install --python .venv/bin/python -r requirements-syrax.txt   # or .venv/bin/pip install -r requirements-syrax.txt
cp config/config.syrax.example.toml config/config.toml   # [llm] is a dummy; [daytona] must exist for OpenManus to boot
cd ..

# frontend
cd frontend && npm install && cd ..

# run once by hand
./syrax.sh --dev          # backend :8765, UI :3000
# or install the login service
./syrax.sh --install-service && systemctl --user status syrax
```

Then in the UI: BRAIN → paste the Gemini and Groq keys (they are stored only
in `backend/config/brains.json`, mode 0600, never in git). Groq's model must be
`openai/gpt-oss-120b` (default in code). Press AUTO to enable autonomy (off by
default). `S` opens the SELF panel; the console has LIVE / HISTORY / TODAY.

Verify the install: `cd backend && .venv/bin/python -m pytest syrax -q` and
`.venv/bin/python -m syrax.verify` (both must be green), then `curl
http://127.0.0.1:8765/self?section=summary`.

Environment variables (all optional): `SYRAX_PORT`, `SYRAX_JOURNAL_FILE`,
`SYRAX_AUTONOMY`, `SYRAX_AUTO_RESUME`, `SYRAX_AUTOPUSH`, `SYRAX_QUIET_HOURS`,
`SYRAX_CYCLE_INTERVAL`, `SYRAX_SKILLS_DIR`, `OPENMANUS_DISABLE_BROWSER_USE`,
`SYRAX_DISABLE_WHISPER_WARMUP`. See README for the table.

## 5. Back up before wiping the OS (not in git)

| What | Where | Why |
|---|---|---|
| Brain keys | `backend/config/brains.json` | Gemini + Groq keys, provider order and models |
| OpenManus config | `backend/config/config.toml` | needed to boot; no secrets in the SYRAX setup |
| The journal | `backend/config/journal.db` (+ `-wal`, `-shm`) | every task, objective, knowledge row, skill, benchmark, quality run and SYRAX's lessons; ~3 MB |
| Skills SYRAX built | `backend/skills/` | none yet besides README |
| Legacy memory | `backend/config/memory.json`, `history.jsonl` | already migrated into the journal; optional |
| Rollback snapshots | `backend/config/rollback/` | optional |
| Claude Code memory | `~/.claude/projects/-home-prince-son-of-ultron/memory/`, `~/CLAUDE.md` | the assistant's notes about this project and preferences |
| systemd unit | `~/.config/systemd/user/syrax.service` | regenerate with `./syrax.sh --install-service` |

Without the journal SYRAX starts with no history: it will re-derive
verify-capability objectives and rebuild its evidence within a few cycles.

## 6. Operating rules that proved necessary

- Nothing is pushed without a GREEN gate; a failed gate is BLOCKED, not "probably fine".
- Never leave uncommitted work in the tree while SYRAX may run `release`: commit or stash first anyway. Post-task cleanup now rolls back only files the task's own tools could have written (editor paths from `code.changed`; any non-baseline change after `python_execute`/`skill_create`; nothing after a task that wrote no files). Lesson of 2026-09-30: a human edit made *while* an autonomous task ran was reverted; the patch survived in `backend/config/rollback/`.
- Never run `next build` inside `frontend/` while the login service serves `frontend/.next`; the gate builds from a scratch copy.
- Smoke-test changes on `SYRAX_PORT=8766` with a temporary `SYRAX_JOURNAL_FILE`, not on the live instance.
- Ollama (7B on CPU) plus Whisper can thrash a 14 GB laptop; do not run brain comparisons with Ollama while the owner is working.
- Keys go into the brain store through the UI or `brains_save`; never into files, docs, tests or commit messages (the diff scan blocks key-shaped literals).

## 7. Where to look when something is wrong

- What SYRAX is doing: the LIVE tab, `GET /self?section=summary`, `journalctl --user -u syrax`.
- Why a task did what it did: HISTORY → task → WHY (events, checkpoints, objective, lesson).
- Why a release failed: the `verifications` table (`{"type":"verifications"}` over WebSocket) and `backend/config/rollback/*.patch`.
- Why a cycle did nothing: `autonomy_status.pressure` (quiet hours, CPU, RAM, disk, battery) and the last cycle's `reason`.

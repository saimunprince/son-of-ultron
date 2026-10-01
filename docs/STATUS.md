# SYRAX — Status and Handover (2026-09-26; Windows 2026-09-30; autonomy and integrity 2026-10-01)

Read this first on a fresh machine. It says what exists, what is verified, what
is left, how to set the machine up again, and what to back up before wiping an
OS. Everything here is backed by commits on `main` and by tests; nothing is
planned-only unless it sits under "Remaining".

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

## 0. Where things stand (2026-10-01 evening)

SYRAX runs natively on Windows in the background (`python syrax.py --restart`;
login start through a hidden `SYRAX.vbs` in the Startup folder; logs in
`syrax.log`). It restarts itself into new commits when idle. Brains, in
order: Gemini (`gemini-3.5-flash-lite`), Upstage (`solar-pro3`), OpenRouter
(`nemotron-3-ultra-550b:free`), Groq. Real quality runs: 90 %.

What the autonomy does now, in one cycle (`autonomy.py`):
restart into new code if pending → derive objectives from failures →
re-judge BLOCKED objectives against newer evidence → pick an objective, or
rank its own limitations (`limits.py`, value = score × confidence ÷ cost) →
brief with the objective's evidence, earlier attempts and similar past
objectives → run → judge from evidence, fingerprint the strategy (a failed
strategy is never repeated) → proposals for the human from research; when
idle once a day, the technology radar (`radar.py`) and the brain scorecard
(`scorecard.py`).

Integrity, learned the hard way on 2026-10-01 (SYRAX weakened a quality
check, then manufactured a passing run in a second core it built):
autonomous `release` refuses the judge and guard files and edits to existing
tests; a different brain must clear every autonomous change (`review.py`,
four yes/no answers, verdict computed in code); only the journal's owner
process writes it; python_execute and its child Pythons cannot write the
journal or the keys (`guard.py`); a human can reopen an objective closed on
bad evidence (`objective_update`).

SYRAX built four skills itself (Word, Excel, PowerPoint, PDF), each verified
by its own tests and by hand. Skills live in `backend/skills/`, outside git.

Day-to-day for a human: the UI's daily briefing card; `proposals` over the
WebSocket (or ask SYRAX "what do you propose?"); `objective_add` with an
optional check to ask for a capability. Phase-by-phase progress and what is
left: [ROADMAP.md](ROADMAP.md).

## 1. What SYRAX is now

SYRAX is an OpenManus-based personal AI that keeps a durable record of
everything it does, understands itself from that record, pursues its own
objectives when idle, researches, builds tools, changes its own code through a
release gate, measures itself, and decides what to show on screen. The UI is an
observer; the core is the brain and keeps running when the browser is closed.

Architecture, one line each (details in the linked docs):

| Piece | File | Doc |
|---|---|---|
| Durable journal (tasks, events, checkpoints, objectives, knowledge, skills, benchmarks, experiments, quality runs) — SQLite WAL, transactional, crash-recovering | `backend/syrax/journal.py` | [EXECUTION_MODEL.md](EXECUTION_MODEL.md) |
| Core: one agent, one running task, sessions are observers; resume; post-task cleanup | `backend/syrax/core.py` | [EXECUTION_MODEL.md](EXECUTION_MODEL.md) |
| Release gate: pytest, tsc, eslint, node tests, isolated next build, diff scan, benchmark | `backend/syrax/verify.py` | [DEVLOOP.md](DEVLOOP.md) |
| Self-model: identity, structure, behavior, capabilities (evidence), performance, weaknesses | `backend/syrax/selfmodel.py` | [SELF_MODEL.md](SELF_MODEL.md) |
| Autonomy: objectives judged from evidence, bounded cycles, resource gate | `backend/syrax/autonomy.py`, `resources.py` | [AUTONOMY.md](AUTONOMY.md), [OPERATIONS.md](OPERATIONS.md) |
| Research + knowledge with provenance and confidence policy | `backend/syrax/research.py` | [RESEARCH.md](RESEARCH.md) |
| Skill factory: tools whose tests decide registration | `backend/syrax/skills.py`, `backend/skills/` | [SKILLS.md](SKILLS.md) |
| Dev loop: `release` = gate → commit or rollback; task-scoped changes | `backend/syrax/devloop.py` | [DEVLOOP.md](DEVLOOP.md) |
| Presentation engine + stage, human-feedback learning | `backend/syrax/presentation.py`, `frontend/components/Stage.tsx` | [PRESENTATION.md](PRESENTATION.md) |
| Benchmarks, experiments, task-quality suite, version and brain comparison | `bench.py`, `experiments.py`, `quality.py`, `versions.py` | [EXPERIMENTS.md](EXPERIMENTS.md) |
| Observer views LIVE / HISTORY / WHY / TODAY, SELF panel | `frontend/components/HistoryView.tsx`, `SelfPanel.tsx` | — |
| Component map | `docs/system_map.json` | [SYSTEM_MAP.md](SYSTEM_MAP.md) |

## 2. What was done today (33 commits on `main`, in order)

All twelve phases of the master plan received a first real implementation,
each behind a GREEN gate:

1. `5b25c07` journal, task lifecycle, checkpoints, crash recovery, resume; core decoupled from the UI
2. `cae9cf0` release gate · `bc5070e` system map, gap analysis, execution model
3. `ef927d2` self-model + `self_inspect` + SELF panel
4. `32a0844` objectives + autonomous cycle · `6f3df74` LIVE/HISTORY/WHY/TODAY
5. `eab9791` research + knowledge store · `7656716` skill factory · `f682958` dev loop
6. `958574f` 24/7 operations (resource gate, maintenance) · `fb1da93` self-hosted fonts
7. `2de8f49` presentation engine · `f41a92f` benchmarks, experiments, self-improvement objectives
8. `9a5ad60` `e261b12` `f152fd4` fixes from the first supervised live runs
9. `d352023` task-quality benchmark · `92fadae` `compare_versions` · `1050611` journal-backed history, presentation feedback, brain comparison
10. `024ae7a` facts memory in the journal, chart kind · `a847858` Groq default model
11. `c33b6cd` task-scoped release/rollback, post-task cleanup (learned from SYRAX's first self-modification attempt)
12. `b69a0ae` **SYRAX's own commit**: it edited its prompt and released it through the gate (author `SYRAX <syrax@localhost>`)
13. `85e5299` SYRAX derives code-fix objectives itself; narration measured · `1c69423` truthful brain column

Measured state at the end of the day:

| Measure | Value |
|---|---|
| Backend tests | 270 passing (was 43 in the morning); `cd backend && .venv/bin/python -m pytest syrax -q` ≈ 100 s |
| Gate | `cd backend && .venv/bin/python -m syrax.verify` ≈ 2 min, GREEN at every push |
| Task quality (10 fixed cases) | Gemini 100 % · Groq 90 % · Pollinations 80 % — see caveats in §5 |
| Live autonomous runs | 14+ autonomous tasks; 12 tools VERIFIED from evidence; 12 objectives DONE, 9 DROPPED |

## 3. Remaining work (honest, in priority order)

The phase plan in [ROADMAP.md](ROADMAP.md) is the order of work. Beyond it:

1. **Quality is 90 %, not 100 %.** The remaining misses are brain quirks (Upstage reaching for tools on a trivial ask; flash-lite ending silently, now wrapped up) rather than missing capability. The scorecard will show whether routing by task kind helps once there is variety.
2. **Free quotas.** Gemini free keys allow ~20 requests per model per day; Groq's 8k tokens per request leaves little room after the ~6k fixed prompt; OpenRouter free models have daily caps. The radar finds new models; a paid key would remove most of the friction.
3. **Prompt size.** ~6k tokens before any conversation (persona, tool guide, 25+ tool schemas, the Browser Use MCP manual). Clipping makes small brains fit; shorter tool descriptions would help every brain.
4. **Recovery of non-file operations.** After a crash only editor edits are verified against reality; python/browser/desktop side effects stay UNCERTAIN (a human dismisses or resumes them).
5. **Voice.** Local Whisper + edge-tts works but is slow; real-time native audio is possible but the free quota is tiny.
6. **The Upstage key was pasted in chat on 2026-10-01** — rotate it.

Full gap table: [GAP_ANALYSIS.md](GAP_ANALYSIS.md). The owner's phase plan and its order: [ROADMAP.md](ROADMAP.md).

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

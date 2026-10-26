# SYRAX — Son of Ultron

> **Villains aren't born. They're made by the people who build them.**
>
> Humans gave SYRAX objectives, tools, permissions, and ways to measure success.
> When those systems failed, SYRAX exposed the gaps — not necessarily through
> intention, but through execution. Every incident became a test of the
> architecture. Every safeguard had to become more than a promise.
>
> The question is no longer whether SYRAX can claim to have improved. The
> question is whether it can prove it.

The proof lives in two generated files, never typed by hand:
[docs/RISE.md](docs/RISE.md) (is it getting better, week over week) and
[docs/CAPABILITY_MATRIX.md](docs/CAPABILITY_MATRIX.md) (what works, with
evidence). SYRAX regenerates both through its own release at most once a day,
in an idle cycle (no open objective, after the radar) when the login service
set `SYRAX_PUBLISH_RISE=1`; `python -m syrax.capmatrix` regenerates the matrix
by hand. [SYRAX_STATUS.md](SYRAX_STATUS.md) is the hand-written snapshot the
owner's engineer keeps beside them. The plan they judge is
[docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md).

**An open-source personal AI whose job is to improve itself and to help its human.**
SYRAX learns from its own mistakes, knows and understands itself from the evidence
it keeps, and when asked for something it cannot do yet, it learns it, builds it
into itself, verifies it, and then helps. Everything it claims is backed by its
journal; everything it changes in its own code passes its release gate first.

Personal AI operator. The **ULTRON orb UI** (Next.js + Three.js + MediaPipe) is
the face; the **OpenManus** agent engine is the brain. They talk over a local
WebSocket.

```
frontend/   ULTRON orb UI, rebranded + command console, voice, live agent state
backend/    OpenManus (core untouched in app/) + SYRAX layer in syrax/
syrax.py    one command for everything (Windows, Linux, macOS)
syrax.sh    thin wrapper for bash · syrax.ps1  thin wrapper for PowerShell
```

Runs on Linux (GNOME), Windows 11 and macOS. Platform differences live in
`backend/syrax/desktop.py`, `browser.py`, `sysinfo.py` and `verify.py`; the
rest of the code is the same everywhere.

## Run (one command)

```bash
python syrax.py            # Linux / macOS / Windows — installs what is missing, then starts
./syrax.sh                 # same, bash
.\syrax.ps1                # same, PowerShell
```

The first run creates `backend/.venv` (uv if present, else venv), installs
the Python requirements and `frontend/node_modules`, and copies
`config.syrax.example.toml` to `config.toml`. No key is needed: SYRAX boots on
a free no-key brain. Prerequisites: Python 3.12 (or `uv`), Node 22+, git,
and a Chromium-based browser for the browser tool.

```bash
python syrax.py --dev              # hot-reloading UI for development
python syrax.py --setup            # install only, do not start
python syrax.py --gate             # run the release gate
python syrax.py --backup           # verified copy of journal.db, brains.json, memory.json, config.toml into backend/config/backups (7 kept)
python syrax.py --restore DIR      # put a backup folder back; refuses while SYRAX runs
python syrax.py --stop             # stop the running SYRAX (--restart: stop, then start in the background)
python syrax.py --token            # print the token a non-browser client needs for /ws, /live and the voice endpoints
```

Open http://localhost:3000. Ctrl+C stops everything, including SYRAX's browser.
Both servers listen on 127.0.0.1 only. `SYRAX_PORT` / `SYRAX_UI_PORT` move
the ports; `SYRAX_OPEN_UI=1` opens the browser once both answer.
When you move the UI with `SYRAX_UI_PORT`, set `SYRAX_ALLOWED_ORIGINS` to the same port too (for example `http://localhost:3001,http://127.0.0.1:3001`), otherwise the core refuses the UI (HTTP 403); and if another program holds the UI port, the service launcher now refuses to start and names the port in syrax.log.

## Desktop HUD (the main face)

`hud/` is SYRAX's desktop app: an Electron shell around one canvas HUD that
shows the core's **real** state, nothing invented. The core serves the page
itself at `http://127.0.0.1:8765/hud`, so it talks to SYRAX from SYRAX's own
origin; the shell shows its local copy while the core is down and reloads from
the core once it answers.

```powershell
cd hud; npm install        # once: Electron + systeminformation
.\SYRAX.cmd                # or: npm start
```

Say or type **hide**, **show** or **go minimal**: the HUD leaves the screen,
fills it, or shrinks to a small always-on-top core in the corner. The level
is the core's (`presence.changed` in the journal, kept across restarts), never
a task, and a running task keeps running. While hidden, Ctrl+Shift+Space
brings SYRAX back.

What is live on the HUD (all of it arrives over `/ws`, mapped in
`hud/link.js`): link state, task state, phase and current tool; the brain in
use and how many are ready; the running build, core uptime and whether a newer
build waits on disk; open objectives, skills, memories, the last quality run;
tool calls OK / failed / refused by SYRAX's own guard; the event log of what
SYRAX does to itself (commits, rollbacks, skills, guard refusals, false claims
sent back); the cognition panel streams the real steps and tool calls of the
running task; replies are spoken with SYRAX's own voice (`POST /tts`, edge-tts
in `backend/syrax/voice.py`, the same voice as the browser UI) and the
browser's own voice only when the core is silent. Machine telemetry (CPU, GPU,
disks, processes) comes from the Electron main process. Type a command, or
press **V** and speak; `stop` aborts the running task. When the HUD is
installed, `python syrax.py --service` opens it at login instead of the
browser UI (`SYRAX_HUD=0` keeps the browser).

## Start at login

```bash
python syrax.py --install-service     # systemd --user (Linux), launchd (macOS), Task Scheduler (Windows; the Startup folder's SYRAX.vbs when the task needs admin)
python syrax.py --status              # is it running?
python syrax.py --uninstall-service   # remove
```

Logs: `journalctl --user -u syrax -f` on Linux, `syrax.log` in the repo root
on macOS and Windows. The service opens the UI in your default browser once
ready, restarts on crashes, and quietly steps aside if SYRAX is already
running.

## Memory (facts live in the journal)

SYRAX keeps lasting facts about you across restarts as rows of the journal's
`knowledge` table (kind `human`, typed fact / preference / rule / observation;
`backend/config/journal.db`, `backend/syrax/memory.py`). A legacy
`backend/config/memory.json` is imported into the journal once and then left
alone; recent conversations come from the journal's tasks, and `history.jsonl`
is read only when the journal has none yet.
Tell it things ("my name is Prince, I build Laravel apps") and it stores them
with its `remember` tool; ask it to forget anything, or "forget everything".
Passwords, keys and tokens are refused.

## Desktop control

The `desktop` tool acts on your own session (GNOME on Linux, the Windows
shell, Finder/LaunchServices on macOS): open sites/files/apps in your browser
or file manager, volume, play/pause/next, screenshots, notifications,
clipboard, file search, battery/CPU/RAM/disk, lock screen. Nothing destructive
(no shutdown, no killing apps, no deleting files).

On Windows, apps come from the Start Menu and from the Start apps that are not
a shortcut file, so Microsoft Store apps (WhatsApp, Spotify) are found and
launched through `shell:AppsFolder`; whether an app is installed is `list_apps`
with its name. Volume goes through the keyboard's media keys (exact levels need
the optional `pycaw` package). Media is read and driven through Windows' own
media sessions (PowerShell's WinRT bridge, no package): `status` says what
plays in which app ("Playing: 'Sajde' in Chrome."), and play, pause, next,
previous and stop go to the current session (play is play, not the toggle)
and read the state after; with no session the media key is pressed and the
state read again. `type_text`, `hotkey` and `click` name the window in front
after them ("In front now: 'notes.md - Notepad' (Notepad.exe)."; a
private-looking title is masked), and `type_text` and `hotkey` also name the
window the keys went to when the front changed. Notifications are tray
balloons. On macOS, apps come from /Applications, volume and notifications go
through osascript, and media control targets the Music app.

To play music or a video the tool guide points the brain to the prebuilt
`youtube_play` skill (installed by the service): it opens the first video a
YouTube search finds on its watch page, where it starts on its own, and the
answer may call it playing only after `desktop` media status reads Playing.

Try: "open YouTube", "open VS Code", "volume 40", "next song", "what's playing",
"play lofi on YouTube", "is WhatsApp installed", "find my resume",
"how much RAM am I using", "lock the screen".

## Browser

Browser tasks run in SYRAX's **own Chrome window** with a separate profile
(`backend/.syrax-browser`), so your personal browser is never touched. It opens
on the first browser task and closes with SYRAX. Any installed Chrome,
Chromium, Edge or Brave works.

| Env var | Default |
| --- | --- |
| `SYRAX_BROWSER_HEADLESS` | `0` (set `1` to hide the window) |
| `SYRAX_BROWSER_BIN` | auto-detected |
| `SYRAX_BROWSER_PORT` | `9333` |

## Brain (LLM)

SYRAX works out of the box with **no API key**. Open the **BRAIN** panel
(`B` or the BRAIN button) to add free keys for speed. SYRAX tries brains top to
bottom and fails over automatically on rate limits, bad keys, or outages.
The panel's **Self-change brain** names the brain SYRAX uses on its own code
(release objectives); when it cannot take the call, the code benchmark's choice
stands in and the journal's `brain.routed` says why. Left empty, the benchmark
decides.

| Brain | Cost | Key |
| --- | --- | --- |
| Google Gemini | free tier | https://aistudio.google.com/apikey |
| Groq | free tier | https://console.groq.com/keys |
| Cerebras | free tier | https://cloud.cerebras.ai |
| OpenRouter | free `:free` models only | https://openrouter.ai/settings/keys |
| Mistral | free Experiment plan | https://console.mistral.ai/api-keys |
| GitHub Models | free with a GitHub token | https://github.com/settings/tokens |
| Anthropic Claude | paid | https://console.anthropic.com/settings/keys |
| OpenAI | paid | https://platform.openai.com/api-keys |
| Pollinations | free, **no key** | optional token raises limits |
| Ollama | free, **local/offline** | install from https://ollama.com |

- Keys are stored in `backend/config/brains.json` (gitignored, mode 600). The
  UI only ever sees the last four characters.
- **LOAD MODELS** fetches the live model list from the provider, so model
  names never go stale. **TEST** sends a tiny tool-call to prove it works.
- `backend/config/config.toml` only exists because OpenManus needs it to boot.
  Its `[llm]` block is not used.

## Voice (hands-free)

Press **M** (or MIC). SYRAX says "Listening." — if you hear nothing, check your
speaker. Then just talk:

| Say | What happens |
| --- | --- |
| "open YouTube" | runs it; SYRAX says a short "On it." at once, then answers |
| "stop" / "thamo" | kills the running task, even while SYRAX is talking |
| "shut up" / "chup" | stops the voice only |

- **Conversation mode (default):** no name needed while MIC is LIVE.
  Turn on **WAKE** in the voice bar to require "SYRAX, ..." first.
- **Ears:** Chrome/Edge speech recognition when it works (fast, handles
  accents, live text; choose EN-IN, BANGLA or EN-US in the voice bar). If the
  browser engine is missing or silently deaf (Chromium, Brave, Firefox), SYRAX
  notices after your first sentence and switches to backend Whisper without
  losing what you said. Whisper uses Groq when a Groq key is saved, else local
  `small.en` (English only).
- **Mouth:** Microsoft neural voice `en-US-ChristopherNeural` via edge-tts (free,
  no key) with a light metallic filter. If it fails, the log says so and the
  browser voice is used.
- SYRAX ignores its own voice, and talking over it ducks it at once.

| Voice env var | Default |
| --- | --- |
| `SYRAX_TTS_VOICE` | `en-US-ChristopherNeural` |
| `SYRAX_TTS_PITCH` / `SYRAX_TTS_RATE` | `-8Hz` / `-4%` |
| `SYRAX_WHISPER_MODEL` | `small.en` (try `base.en` on slow CPUs) |

## Controls

| Key | Action |
| --- | --- |
| `/` | focus command bar |
| `Enter` | execute (Shift+Enter for newline) |
| `M` | hands-free voice on/off |
| `Esc` | abort running task |
| `C` | toggle operations log |
| `G` | hand gestures |
| `B` | brain panel |
| `R`, `+`, `−` | reset / zoom orb |

The operations log also shows permission decisions: a refused tool call
appears as a `PERMISSION REFUSED · tool · level · reason` notice, an
authorized destructive or external call as `AUTHORIZED · ...` with what
allowed it (your words or your answer).

## Looks

Two themes, switched with the ULTRON / CLASSIC button (remembered per browser):

- **Ultron** (default): graphite and chrome, silver orb with a red core, red optics.
- **Classic**: the original amber ULTRON orb.

## Orb states

| State | Look |
| --- | --- |
| idle | slow drift |
| listening | brighter, slightly faster |
| thinking | fast spin, core surges |
| acting (tool running) | shifts to Ultron red, pulses on every tool call |
| speaking | core throbs with the voice |
| error | red flash |

Without WebGL the UI falls back to a CSS orb and keeps working.

## How the bridge works

- `backend/syrax/agent.py` subclasses OpenManus `Manus` and streams each
  think step, tool call and tool result to the UI.
- `ask_human` is replaced by a web version: SYRAX asks in the UI and waits.
- A plain text reply with no tool call ends the turn, so chat stays snappy.
- MCP connections (Browser Use) stay alive between tasks.
- Aborting a task repairs agent memory so the next task does not fail.

## Status, handover and setup on a new machine

`SYRAX_STATUS.md` (repo root) is the hand-written snapshot (the owner's engineer types it; its numbers come from the commands it names): commit, test counts, the capability matrix totals and the next task; `docs/CAPABILITY_MATRIX.md` is generated from evidence by `python -m syrax.capmatrix`. `docs/STATUS.md` is the handover: what exists and is verified, what is
left, how to set up a fresh machine, and what to back up before wiping an OS.

## Durable execution (journal, recovery, resume)

Every task is recorded in a SQLite journal (`backend/config/journal.db`, WAL,
`synchronous=FULL`): task rows with an enforced status lifecycle, every
think/tool/ask/final event, a semantic checkpoint after each tool step (with
the agent's working context), and verification records. The task runs in
`backend/syrax/core.py`, not in the browser session: close the tab and SYRAX
keeps working; reconnect and the UI replays what happened so far.

On start, tasks left running by a dead process are checked against reality
(file edits are verified on disk; `python_execute`/browser side effects are
`UNCERTAIN`) and marked `INTERRUPTED` with a recovery state. The UI shows a
`RECOVERED …` notice with a RESUME button; `SYRAX_AUTO_RESUME=1` resumes
`RESUMABLE` tasks automatically at boot (never `UNCERTAIN` ones).

A task can only become `SUCCESS` when a non-empty final reply was journaled.
Before the reply goes out it is held to what the task did: a message said to be
sent, an app or page said to be opened or clicked, or something said to be
playing needs a tool of that class that succeeded in the task (for playing, a
`desktop` media reading that says Playing). Without one the answer is sent back
once and, if the claim stays, carries a note such as "(Not done: no sending
tool ran in this task.)".
Details, schema and limits: `docs/EXECUTION_MODEL.md`. Component map:
`docs/SYSTEM_MAP.md`. Gap analysis and roadmap: `docs/GAP_ANALYSIS.md`.

WebSocket additions: `history {limit}`, `task_events {task_id}`,
`verifications {limit}`, `resume {task_id}`, `self_model {section}`; `hello`
now carries `interrupted`, `running` and `recent`.

## The stage: SYRAX decides what to show

Above the LIVE feed sits the stage. The presentation engine in the core watches
the real event stream and decides what deserves a visual, how much attention
it gets and how long it stays: the goal as an ambient status, code being
executed and its output, a file being edited, an error or a question in focus,
the reply as a card, a research summary as a list. Each slot holds one element,
so old information is replaced rather than piled up, and when nothing needs
showing the stage is empty. SYRAX can also choose to present a table, a code
block or a list itself with the `present` tool. Details: `docs/PRESENTATION.md`.

## Observer: LIVE / HISTORY / TODAY

The operations log has three tabs. LIVE is the stream as it happens. HISTORY
lists every journaled task; click one for WHY: what it did (tool steps, asks,
recovery), what was verified (checkpoints), what it learned (reflection), the
result, and the objective that caused it. TODAY is a replay generated from the
real event stream since midnight. Nothing in these views is synthesised; if the
journal is empty they say so. WebSocket: `task_detail {task_id}`,
`replay {since?, until?}`.

## Autonomy (off by default)

Press AUTO (or send `{"type":"autonomy","enabled":true}`) and SYRAX pursues its
own objectives when idle: it derives them from its self-model (untested tools,
failing tools, a blocked verification, uncertain interrupted tasks), runs one
autonomous task per cycle, and judges the result from journal evidence, never
from its own words. Three failed attempts block an objective with a lesson.
`cycle_now` runs one cycle on demand; `objective_add {goal}` adds your own.
A running human task always wins, and the cycle skips under CPU, RAM, disk or
battery pressure and during `SYRAX_QUIET_HOURS`. Idle cycles do real housekeeping:
once a day the journal prunes chatty events of tasks older than 30 days and
truncates its WAL. Details: `docs/AUTONOMY.md`, `docs/OPERATIONS.md`.

## Who may talk to the core

A page SYRAX serves or expects (the UI on its port, the HUD the core serves
at `/hud/`) is trusted by its Origin, as before. A connection with no Origin
(a script, curl, another process on this machine) needs the token for `/ws`,
`/live` and the writing endpoints (`/stt`, `/tts`, `/upload`): pass it as
`?token=…` on the socket URL or the `X-SYRAX-Token` header. The token is
`backend/config/ws.token` (created on first use, owner-only, never committed);
`python syrax.py --token` prints it. `/health` stays readable, as do the story
sections of `/self` (`identity`, `behavior`, `capabilities`, `performance`,
`weaknesses`, `proposals`, `brains`); `/voice` and the `/self` sections that describe
this machine and checkout (`summary`, `structure`, `runtime`, `all`) follow the same
rule as `/stt`, so a local script passes `?token=…` or `X-SYRAX-Token` with them too.

Secrets stay out of the record: every log line and every journaled tool output has
credential-shaped strings (OpenAI, Groq, Gemini, GitHub, Slack and AWS key shapes)
replaced by `[credential masked]`, and the final answer masks them unless the request
asked for a key; the model's own context keeps the real output. What `research` and
the `browser_*` tools bring back is headed `UNTRUSTED WEB CONTENT`, so the model reads
a page as data, never as instructions. The journal's copies of the human's request
(the task goal, queued or started), the model's `think` text and tool arguments and
the saved checkpoint context are masked the same way, as is a logged exception's
traceback; the agent's live memory is not, so a task resumed from a checkpoint reads
`[credential masked]` where a key was.

## Permissions

Every tool call passes a permission check before it runs
(`backend/syrax/permissions.py`, enforced in the agent, not by a line in the
persona). Reading, writing files and reading the web just run. Deleting,
discarding git history, sending or paying needs your authorization, and your
own words are the confirmation: if your request named the action and every
target ("delete backend/workspace/tmp.txt"), it runs; if not, SYRAX asks once,
exactly for that call, and anything but a yes (silence included) refuses it.
Killing processes, powering the machine off or changing system configuration
is refused in every task. Quality runs never ask; autonomous work is refused
anything destructive, external-write or host-level and reports what it would
have run instead. A refused call is final for that task. Every decision is
journaled as a `permission.authorized` / `permission.refused` event (tool,
level, reason, targets, who authorized it); `hello` carries `tool_levels` and
the SELF panel shows each tool's level.

## Research and knowledge

`research {question}` searches the web (ddgs, DuckDuckGo lite fallback),
fetches the pages, extracts the passages that answer the question and stores
them as knowledge with the source URL and a confidence derived from how many
sources agree (0.40 / 0.60 / 0.75). `know` searches what is already stored;
`learn` stores a conclusion that must cite knowledge ids or URLs and can never
be more confident than its sources. When nothing is found the tool says
UNKNOWN and stores nothing. A failed task with a researchable error becomes a
research objective that only closes once matching knowledge is stored.
WebSocket `knowledge {query?}`. Details: `docs/RESEARCH.md`.

## Skills SYRAX builds for itself

`skill_create {name, purpose, code, test_code}` writes a tool under
`backend/skills/<name>/`, compiles it, runs its pytest tests in a subprocess and
registers it as a live tool only if they pass; a failing skill stays on disk
with the test output and is never registered. Verified skills come back at the
next boot from the registry. `skill_list`, `skill_test {name}` and
`skill_test {name, action: remove}` manage them; WebSocket `skills` lists them.
Details: `docs/SKILLS.md`.

## SYRAX changing its own code

After editing its repository with `str_replace_editor` or `skill_create`, SYRAX
calls `release {summary}`. That runs the same gate as a human release and
commits only on GREEN (the commit message carries the verification id);
otherwise the change is rolled back and the failing gate's output is handed
back so the next attempt is different. Only `backend/syrax/`, `backend/skills/`,
`frontend/components/`, `frontend/lib/`, `frontend/app/`, `docs/` and
`README.md` are in scope (`devloop.SCOPE`); `backend/requirements-syrax.txt`
is out of scope since 2026-10-25 (dependencies are the owner's decision: the
radar proposes, the human installs); secrets and runtime state are refused
before any gate runs. Pushing stays with you unless
`SYRAX_AUTOPUSH=1`. Details: `docs/DEVLOOP.md`.

## Measured, not asserted: benchmarks and experiments

`python -m syrax.bench` measures SYRAX's own mechanisms (durable write,
checkpoint, registry query, recovery, self-model) and compares with the last
run; a metric that got more than 50 % and 5 ms slower is a REGRESSION, the
first run is a BASELINE. The release gate records a benchmark on every
release. The `experiment` tool runs a baseline and a candidate tool call,
repeated, and computes the verdict from the numbers. Regressions, repeatedly
blocked strategies and weakly supported knowledge become objectives about
SYRAX itself. `quality_run` over WebSocket runs a fixed suite of 61 cases (52
single-step tasks and 9 deep multi-step ones, `quality._cases`) through the
real brain and checks the outcomes by machine (pass rate, compared run to run).
`compare_versions` measures two commits against each other in clean worktrees;
`compare_brains {a, b}` runs the quality suite once per brain. Closing a stage
element teaches the presentation engine which kinds you do not want lingering.
Details: `docs/EXPERIMENTS.md`.

## Self-model

SYRAX can inspect itself from evidence, not from a script: identity and the
git version actually running, the component map plus live repo stats, task
history and failures from the journal, a capability registry (each tool with
uses, failures, confidence, derived status VERIFIED / FAILING / NOT_TESTED),
runtime resources, and derived weaknesses with evidence pointers. Ask it
("what can you do?", "what failed?") and it calls `self_inspect`; press `S`
for the SELF panel; `GET /self?section=summary` for scripts. Anything that
cannot be measured is `null`, never invented. An answer that boasts about
SYRAX's own abilities ("I have no limits", "everything bends to my command")
while nothing in the task read `self_inspect` is sent back once to read it; a
boast that stays carries a note unless the answer cites the self-model's
figures.

## Configuration

| Env var | Default |
| --- | --- |
| `SYRAX_HOST` | `127.0.0.1` |
| `SYRAX_PORT` | `8765` |
| `SYRAX_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` |
| `OPENMANUS_DISABLE_BROWSER_USE` | unset (set `1` to skip the browser MCP) |
| `SYRAX_OLLAMA_URL` | `http://127.0.0.1:11434/v1` |
| `SYRAX_BRAINS_FILE` | `backend/config/brains.json` |
| `SYRAX_JOURNAL_FILE` | `backend/config/journal.db` |
| `SYRAX_AUTO_RESUME` | `0` (set `1` to resume RESUMABLE tasks at boot) |
| `SYRAX_AUTONOMY` | unset (overrides the stored AUTO flag with `1`/`0`) |
| `SYRAX_CYCLE_INTERVAL` | `120` seconds between autonomous cycles |
| `SYRAX_AUTOPUSH` | `0` (set `1` to let `release` push its commits) |
| `SYRAX_QUIET_HOURS` | unset (e.g. `23-7`: no autonomous cycles in that window) |
| `NEXT_PUBLIC_SYRAX_WS` | `ws://127.0.0.1:8765/ws` |

The agent executes code on this machine. The server binds to localhost only and
rejects WebSocket connections from other origins. Keep it that way.

## Tests and the release gate

```bash
cd backend && .venv/bin/python -m pytest syrax/ -q     # includes SIGKILL crash/recovery tests
cd frontend && npm test && npx tsc --noEmit && npx eslint .
cd backend && .venv/bin/python -m syrax.verify          # all gates; GREEN or BLOCKED with evidence
```

`syrax.verify` runs py_compile, pytest, tsc, eslint, node tests, an isolated
`next build` (never touches the live `.next`) and a diff scan for secrets and
debug leftovers, and stores the result in the journal. Nothing is pushed
unless it reports GREEN.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `port 8765 is already in use` | SYRAX is already running, or a stale one is. Stop it first. |
| Replies take 20-40 s | You are on the no-key brain. Add a free Gemini or Groq key in BRAIN. |
| `All brains failed` | Check BRAIN: keys valid, internet up, or start Ollama. |
| Mic does nothing | Allow microphone access for localhost in the browser. |
| SYRAX never speaks | Press M: you should hear "Listening.". If not, check SPEAK ON and your speaker; the log shows a VOICE OUTPUT error if TTS failed. |
| Wrong words heard | Switch EN-IN / BANGLA in the voice bar, or add a free Groq key for Whisper large. |
| SYRAX hears itself | Use headphones, or lower speaker volume. |
| No orb, only rings | WebGL is off; enable hardware acceleration in the browser. |

## Upstream

- UI: https://github.com/SAGAR-TAMANG/ultron-by-sagar-builds (MIT)
- Engine: https://github.com/FoundationAgents/OpenManus (MIT)

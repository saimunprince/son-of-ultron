# SYRAX — Son of Ultron

Personal AI operator. The **ULTRON orb UI** (Next.js + Three.js + MediaPipe) is
the face; the **OpenManus** agent engine is the brain. They talk over a local
WebSocket.

```
frontend/   ULTRON orb UI, rebranded + command console, voice, live agent state
backend/    OpenManus (core untouched in app/) + SYRAX layer in syrax/
syrax.sh    starts both
```

## Setup

```bash
# backend
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-syrax.txt
# no key needed: SYRAX boots on a free no-key brain

# frontend
cd ../frontend && npm install
```

## Run

```bash
./syrax.sh          # production UI, rebuilt automatically when sources change
./syrax.sh --dev    # hot-reloading UI for development
```

Open http://localhost:3000. Ctrl+C stops everything, including SYRAX's browser.
Both servers listen on 127.0.0.1 only.

## Start at login

```bash
./syrax.sh --install-service     # enable (systemd --user, starts after GNOME login)
./syrax.sh --status              # is it running?
journalctl --user -u syrax -f    # live logs
./syrax.sh --uninstall-service   # remove
```

The service opens the UI in your default browser once ready, restarts on
crashes, and quietly steps aside if SYRAX is already running.

## Memory

SYRAX keeps lasting facts about you and your recent conversations across
restarts (`backend/config/memory.json`, `history.jsonl`, gitignored, mode 600).
Tell it things ("my name is Prince, I build Laravel apps") and it stores them
with its `remember` tool; ask it to forget anything, or "forget everything".
Passwords, keys and tokens are refused.

## Desktop control

The `desktop` tool acts on your own GNOME session: open sites/files/apps in
your browser or file manager, volume, play/pause/next, screenshots, notifications,
clipboard, file search, battery/CPU/RAM/disk, lock screen. Nothing destructive
(no shutdown, no killing apps, no deleting files).

Try: "open YouTube", "open VS Code", "volume 40", "next song", "what's playing",
"find my resume", "how much RAM am I using", "lock the screen".

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
Details, schema and limits: `docs/EXECUTION_MODEL.md`. Component map:
`docs/SYSTEM_MAP.md`. Gap analysis and roadmap: `docs/GAP_ANALYSIS.md`.

WebSocket additions: `history {limit}`, `task_events {task_id}`,
`verifications {limit}`, `resume {task_id}`, `self_model {section}`; `hello`
now carries `interrupted`, `running` and `recent`.

## Autonomy (off by default)

Press AUTO (or send `{"type":"autonomy","enabled":true}`) and SYRAX pursues its
own objectives when idle: it derives them from its self-model (untested tools,
failing tools, a blocked verification, uncertain interrupted tasks), runs one
autonomous task per cycle, and judges the result from journal evidence, never
from its own words. Three failed attempts block an objective with a lesson.
`cycle_now` runs one cycle on demand; `objective_add {goal}` adds your own.
A running human task always wins, and the cycle skips under CPU/RAM pressure.
Details: `docs/AUTONOMY.md`.

## Self-model

SYRAX can inspect itself from evidence, not from a script: identity and the
git version actually running, the component map plus live repo stats, task
history and failures from the journal, a capability registry (each tool with
uses, failures, confidence, derived status VERIFIED / FAILING / NOT_TESTED),
runtime resources, and derived weaknesses with evidence pointers. Ask it
("what can you do?", "what failed?") and it calls `self_inspect`; press `S`
for the SELF panel; `GET /self?section=summary` for scripts. Anything that
cannot be measured is `null`, never invented.

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

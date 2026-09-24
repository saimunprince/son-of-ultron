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

## Configuration

| Env var | Default |
| --- | --- |
| `SYRAX_HOST` | `127.0.0.1` |
| `SYRAX_PORT` | `8765` |
| `SYRAX_ALLOWED_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` |
| `OPENMANUS_DISABLE_BROWSER_USE` | unset (set `1` to skip the browser MCP) |
| `SYRAX_OLLAMA_URL` | `http://127.0.0.1:11434/v1` |
| `SYRAX_BRAINS_FILE` | `backend/config/brains.json` |
| `NEXT_PUBLIC_SYRAX_WS` | `ws://127.0.0.1:8765/ws` |

The agent executes code on this machine. The server binds to localhost only and
rejects WebSocket connections from other origins. Keep it that way.

## Tests

```bash
cd backend && .venv/bin/python -m pytest syrax/ -q
cd frontend && npm test
```

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

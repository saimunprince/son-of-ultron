# SYRAX System Map

Rendered from `docs/system_map.json` (audit of 2026-09-26; phases 1–9 and 11 landed the same day). Every entry was checked against the source files it names.

## Frontend HUD

ULTRON orb UI: Three.js orb, operations log feed, voice pipeline, brain panel, boot sequence.

| | |
|---|---|
| Dependencies | next 16; react 19; three; @mediapipe/tasks-vision; lib/syraxClient.ts |
| Inputs | ServerEvent JSON over WebSocket; /stt and /tts HTTP; microphone, camera |
| Outputs | ClientMessage JSON over WebSocket; speech (edge-tts audio or browser voice) |
| State | React useState in components/Syrax.tsx (entries[] capped at 300, agent state, brains, voice flags); localStorage syrax.* for preferences |
| Persistence | none (observer only) |
| Capabilities | render journaled events as feed entries; RECOVERED/RUNNING notices with RESUME action; hands-free voice, wake word, gestures; console tabs LIVE / HISTORY / TODAY: history list, WHY view per task (steps, checkpoints, objective, lesson, result, RESUME), daily replay rendered from real events |
| Limitations | hardcoded HUD regions; no dynamic presentation engine; history/today views are polled on tab open and refreshed on task events, not streamed row by row |
| Code | frontend/components/Syrax.tsx; frontend/components/HistoryView.tsx; frontend/lib/syraxClient.ts; frontend/lib/*.ts; frontend/app/globals.css |
| Tests | frontend/lib/wake.test.ts (node --test); npx tsc --noEmit; npx eslint . |
| Failure Modes | WebGL missing → CSS fallback orb; WS offline → exponential reconnect, agent shown as booting; TTS 502 → browser voice |

## WebSocket server + Session

FastAPI app: /ws sessions (observers + command routers), /stt, /tts, /voice, /health; lifespan opens the journal, runs recovery, optional auto-resume.

| | |
|---|---|
| Dependencies | fastapi; uvicorn; syrax.core; syrax.journal; syrax.brains; syrax.voice |
| Inputs | task, answer, stop, reset, ping, history, task_events, verifications, resume, brains_* |
| Outputs | hello{tools, interrupted, running, recent}, state, user echo, journaled wire events, history, task_events, verifications, notice, error, brains* |
| State | per connection: Session(id, closed, aux tasks); the task itself lives in Core |
| Persistence | none directly (delegates to journal) |
| Capabilities | multiple sessions observe the same task; reconnect replays the running task's events; origin check on WS and voice routes |
| Limitations | no auth beyond Origin allow-list; binds 127.0.0.1 |
| Code | backend/syrax/server.py |
| Tests | backend/syrax/test_bridge.py; backend/syrax/test_voice.py; backend/syrax/test_memory.py (last test) |
| Failure Modes | bad JSON → error event, session survives; command exception → error event, session survives; lifespan shutdown closes journal (reopened lazily) |

## Core

The single SYRAX entity: owns the agent and the running task, routes agent events through the journal, fans wire events to observers, resumes interrupted tasks.

| | |
|---|---|
| Dependencies | syrax.agent; syrax.journal; syrax.memory |
| Inputs | submit(goal), cancel(), answer(text), reset(), resume(task_id), auto_resume() |
| Outputs | journal writes; broadcast(wire events) to sessions |
| State | agent, current Running{task_id, goal, session_id, asyncio.Task, steps[], unjournaled}, last state event |
| Persistence | via journal (tasks, events, checkpoints) |
| Capabilities | task continues when all browsers disconnect; checkpoint after each tool step and at final; journal write failure → unjournaled flag, no fake success; auto-resume of RESUMABLE tasks when SYRAX_AUTO_RESUME=1 |
| Limitations | one task at a time; no queue scheduling; brain events from a running task are journaled only while current is set |
| Code | backend/syrax/core.py |
| Tests | backend/syrax/test_bridge.py (journal + core section) |
| Failure Modes | LLM error → task.failed + error event; cancel → task.cancelled + notice; sqlite error → task stays IN_PROGRESS, marked INTERRUPTED next boot |

## Journal

Durable execution journal: tasks, events, semantic checkpoints, verifications; transition table; crash recovery with reality checks; fan-out to subscribers.

| | |
|---|---|
| Dependencies | stdlib only: sqlite3, json, threading, asyncio, subprocess(git) |
| Inputs | start_task, record(type,payload,task_id), checkpoint, record_verification, recover, resume_context, mark_resumed |
| Outputs | Event objects (wire()) to subscribers; queries: task, tasks, events, recent_events, checkpoints, verifications; observer queries: task_detail (task + events + checkpoints + objective), events_between (replay window) |
| State | one sqlite connection guarded by a threading.Lock; boot_id; recovered[] |
| Persistence | backend/config/journal.db (WAL, synchronous=FULL, 0600); env SYRAX_JOURNAL_FILE |
| Capabilities | atomic event+state writes; success requires a final event; idempotent recovery with dedupe keys; verify_operation for str_replace_editor create/str_replace/insert; bounded context storage (200 KB); maintain(): 30-day retention of chatty events and checkpoint contexts for finished tasks, WAL truncate, measured counts |
| Limitations | only file edits are reality-checked; other tools UNCERTAIN; PENDING tasks are stored but not scheduled; maintenance never deletes tasks, knowledge or evidence; no full compaction |
| Code | backend/syrax/journal.py |
| Tests | backend/syrax/test_journal.py (SIGKILL crash matrix, transition table, recovery, resume, fan-out) |
| Failure Modes | JournalError on invalid transition/unknown task/terminal task → rolled back; sqlite3.Error propagates to caller (core handles); crash inside recovery → whole txn lost, redone next boot |

## Self-model

Evidence-based model of SYRAX itself: identity/version from git, structure from docs/system_map.json + repo introspection, behavior/failures/verifications from the journal, a capability registry (registered tools × journal evidence), runtime resources, derived weaknesses. Exposed as the self_inspect tool, WS self_model and GET /self, and the SELF panel.

| | |
|---|---|
| Dependencies | syrax.journal (status_counts, tool_stats, tasks, verifications); git; /proc/meminfo, os.getloadavg, shutil.disk_usage; core providers: tool names, brains.describe, running task |
| Inputs | snapshot(section) with section in summary|identity|structure|runtime|behavior|capabilities|weaknesses|all |
| Outputs | JSON snapshot; self_inspect tool output (truncated at 6000 chars) |
| State | none (computed on demand; process start time for uptime) |
| Persistence | none; reads docs/system_map.json and the journal |
| Capabilities | capability status derived: VERIFIED / FAILING / NOT_TESTED / MISSING with uses, failures, confidence; weaknesses with evidence pointers; None instead of invented values when git or the map is unavailable |
| Limitations | GPU is not probed; system_map.json is hand-audited and must be regenerated when components change; no historical performance/latency metrics yet (journal has timestamps but nothing aggregates them); does not yet feed an objectives engine |
| Code | backend/syrax/selfmodel.py; frontend/components/SelfPanel.tsx |
| Tests | backend/syrax/test_selfmodel.py; backend/syrax/test_bridge.py (self-model section) |
| Failure Modes | git unavailable → version/head None; map missing → components [] and present=false; self_inspect before the core exists → tool error |

## Autonomy

Objectives table plus a bounded self-directed cycle: derive objectives from self-model weaknesses, run one autonomous task per cycle through the core, judge completion from journal evidence only, reflect, retry with a lesson or block after 3 attempts.

| | |
|---|---|
| Dependencies | syrax.journal (objectives, meta, events); syrax.selfmodel (capabilities, behavior); syrax.core (submit kind=autonomous, wait); syrax.resources (CPU, RAM, disk, battery, quiet hours) |
| Inputs | WS autonomy {enabled}, cycle_now, objective_add, objectives; SYRAX_AUTONOMY, SYRAX_CYCLE_INTERVAL |
| Outputs | objective.*, cycle.*, reflection.created, autonomy.toggled events; autonomy_status replies; autonomous tasks in the journal; autonomy_status.resources / pressure / last_maintenance; maintenance.completed events |
| State | cycle reports in memory (last 200); enabled flag in journal meta |
| Persistence | objectives table; events |
| Capabilities | evidence-only judging (tool_verified, verification_green, task_success, human); idempotent derivation by key; one live objective per tool; objective already satisfied → closed without a task; resource gate; never runs while a human task runs; background loop with interval; off by default; quiet hours and battery/disk pressure skip cycles (human cycle_now ignores them); idle cycles run Journal.maintain once per 24 h (retention, WAL truncate) |
| Limitations | no research or self-modification objectives yet; lessons are derived strings, not model reflections; one task per cycle, no parallel objectives; no GPU/network/thermal awareness |
| Code | backend/syrax/autonomy.py; backend/syrax/resources.py |
| Tests | backend/syrax/test_autonomy.py; backend/syrax/test_bridge.py (autonomy section); backend/syrax/test_resources.py |
| Failure Modes | derivation error → logged, cycle continues; cycle crash in loop → logged, next cycle after interval; core busy → BUSY report, objective back to OPEN |

## Research engine + knowledge store

Web research with provenance: search (ddgs, DuckDuckGo lite fallback), fetch pages, extract question-relevant passages, store verbatim excerpts as knowledge rows with URL, tags, basis and an evidence-derived confidence; tools research / know / learn; research objectives derived from failed tasks.

| | |
|---|---|
| Dependencies | ddgs (uv-installed, requirements-syrax.txt); requests + bs4 (upstream WebContentFetcher); syrax.journal knowledge table; network access to duckduckgo.com |
| Inputs | research {question, max_sources}; know {query}; learn {claim, sources, confidence?, tags?}; WS knowledge {query?, limit?} |
| Outputs | knowledge rows (kind web|conclusion, confidence ≤ policy); research.started / research.completed / knowledge.stored events; knowledge_list replies |
| State | none (engine list is a module constant, monkeypatched in tests) |
| Persistence | journal knowledge table |
| Capabilities | no fabricated claims: excerpts only, UNKNOWN when nothing is found; confidence policy: web 0.4/0.6/0.75 by agreeing sources, conclusion capped by cited sources, human 1.0; learn refuses uncited or unknown-id conclusions; keyword-ranked know search with usage counters; failure → research objective judged by stored knowledge |
| Limitations | keyword overlap, not semantic understanding; contradictions are shown, not detected; only web and conclusion kinds are produced automatically; no cache, rate limit, expiry or supersession; depends on DuckDuckGo reachability |
| Code | backend/syrax/research.py; backend/syrax/journal.py (knowledge) |
| Tests | backend/syrax/test_research.py; backend/syrax/test_bridge.py (research section); backend/syrax/test_autonomy.py (research objective) |
| Failure Modes | all engines fail → report UNKNOWN, nothing stored; page fetch fails → snippet only, basis says NOT fetched; engine crash inside the tool → tool error, task continues |

## Skill factory

SYRAX writes its own tools: skill_create takes code + pytest tests, compiles and tests them in a subprocess, registers the tool into the live collection only when the tests pass, records a registry row with evidence, and re-registers VERIFIED skills at boot.

| | |
|---|---|
| Dependencies | syrax.journal skills table; pytest in the venv; app.tool.base.BaseTool / ToolCollection |
| Inputs | skill_create {name, purpose, code, test_code, dependencies?, known_limitations?}; skill_test {name, action?}; skill_list; WS skills |
| Outputs | backend/skills/<name>/{skill.py,test_skill.py,skill.json}; skill.created / verified / failed / disabled events; live tools in the agent collection |
| State | loaded skills map in the factory; registry in the journal |
| Persistence | skills table + files under backend/skills/ |
| Capabilities | tests decide registration; failures keep evidence and stay out; re-create replaces code and bumps version; remove unregisters; boot re-registers VERIFIED skills, demotes ones that no longer import; self-model lists skills under structure.skills |
| Limitations | skill code runs in-process (no sandbox), like every tool; dependencies recorded, not installed; no automatic skill generation from objectives; generated skills are not auto-committed (Phase 8) |
| Code | backend/syrax/skills.py; backend/skills/README.md |
| Tests | backend/syrax/test_skills.py; backend/syrax/test_bridge.py (skill section) |
| Failure Modes | compile error → FAILED at stage compile; failing/absent tests → FAILED with pytest tail; loads but wrong Skill.name → FAILED at stage load; test timeout → FAILED |

## Autonomous development loop

release {summary}: inspect the working tree (scope, forbidden paths, diff scan), snapshot the diff, run the full verification gate, commit on GREEN with the verification id in the message, otherwise roll back and hand the evidence to the model. Push only with SYRAX_AUTOPUSH=1.

| | |
|---|---|
| Dependencies | git; syrax.verify (run_gates, default_gates, scan_diff_text); syrax.journal |
| Inputs | release {summary}; code edits made with str_replace_editor / skill_create; SYRAX_AUTOPUSH |
| Outputs | commits authored SYRAX <syrax@localhost>; code.changed / verification.completed / commit.created / commit.failed / rollback.created / push.* events; backend/config/rollback/*.patch snapshots |
| State | none |
| Persistence | git history; journal events; rollback patches |
| Capabilities | gate-driven commit; rollback verified by git status; scope + forbidden-path + secret/debug refusal before any gate runs; per-edit code.changed events from the core; change_released objective check |
| Limitations | push off by default; no benchmark/perf gate; rollback covers the repository only; one release per tool call; the gate takes about a minute |
| Code | backend/syrax/devloop.py |
| Tests | backend/syrax/test_devloop.py; backend/syrax/test_bridge.py (release section); backend/syrax/test_autonomy.py (change_released) |
| Failure Modes | gate BLOCKED → rollback.created, tree restored; git commit fails → commit.failed; push fails → push.failed, commit stays local |

## SyraxAgent

Manus subclass that streams think/tool/result events through emit, checkpoints after each tool step, exports/imports working context for resume.

| | |
|---|---|
| Dependencies | app.agent.manus.Manus; syrax.brains.get_router; syrax.tools; syrax.memory; syrax.desktop; syrax.browser |
| Inputs | run(request); checkpoint hook (set by Core); ask_tool.answer(text) |
| Outputs | emit: state, think, tool_start{step}, tool_result{step,image?}, notice |
| State | OpenManus Memory (messages, trimmed to ~120), current_step, step_limit_hit, last_reply |
| Persistence | none (context is snapshotted by the journal via export_context) |
| Capabilities | chat mode ends turn without tools; MCP browser tools stay connected between tasks; repair_memory after abort/interruption; self_inspect tool reads the self-model |
| Limitations | max_steps 20; tool success is a heuristic on the result text (_succeeded) |
| Code | backend/syrax/agent.py |
| Tests | backend/syrax/test_bridge.py |
| Failure Modes | step limit → step_limit_hit → task PARTIAL; browser unavailable → tool error string |

## BrainRouter

LLM-compatible router over 10 providers with cooldown-based failover; emits brain failover/answered events.

| | |
|---|---|
| Dependencies | openai AsyncOpenAI; app.llm.LLM (format_messages) |
| Inputs | ask_tool(messages, tools) |
| Outputs | ChatCompletionMessage; brain events via listeners |
| State | health/cooldown per provider (process-global), active provider |
| Persistence | backend/config/brains.json (keys, models, order; 0600) |
| Capabilities | free/no-key defaults (pollinations, ollama); retry on 5xx/empty/OOM step-down; model listing and test per provider |
| Limitations | only ask_tool is implemented (ask/ask_with_images are not); listeners are global: all sessions see brain events |
| Code | backend/syrax/brains.py |
| Tests | backend/syrax/test_brains.py (mock OpenAI server) |
| Failure Modes | all providers failing → BrainError → task.failed; 401/403 → 1h cooldown |

## MemoryStore

Long-term facts and recent exchanges injected into every system prompt; remember/recall/forget tools.

| | |
|---|---|
| Dependencies | stdlib |
| Inputs | remember/recall/forget tool calls; add_exchange after task.completed |
| Outputs | prompt_block() |
| State | in-process lock |
| Persistence | backend/config/memory.json, backend/config/history.jsonl (atomic replace, 0600, no fsync) |
| Capabilities | secret refusal; near-duplicate merge |
| Limitations | flat files; history now duplicates journal.tasks |
| Code | backend/syrax/memory.py |
| Tests | backend/syrax/test_memory.py |
| Failure Modes | history write failure is logged, task still SUCCESS |

## Tools

python_execute (non-blocking), str_replace_editor, desktop, remember/recall/forget, ask_human (web), self_inspect, research/know/learn, skill_create/skill_list/skill_test, release, terminate, browser_* (MCP).

| | |
|---|---|
| Dependencies | app.tool.*; browser-use MCP via uvx; GNOME session binaries |
| Inputs | tool calls from the agent |
| Outputs | ToolResult strings, base64 screenshots |
| State | ask_human pending Future |
| Persistence | workspace/ files and screenshots written by tools |
| Capabilities | cancel kills the python child; desktop actions on Wayland |
| Limitations | python/browser/desktop side effects are not reality-checked after a crash |
| Code | backend/syrax/tools.py; backend/syrax/desktop.py; backend/syrax/browser.py; backend/app/tool/* |
| Tests | backend/syrax/test_desktop.py; backend/syrax/test_bridge.py |
| Failure Modes | timeouts → error result; missing binaries → error result |

## Voice

edge-tts TTS with metallic chain on the client; STT via Groq Whisper or local faster-whisper.

| | |
|---|---|
| Dependencies | edge-tts (online); faster-whisper (model download); httpx |
| Inputs | /tts {text}; /stt audio |
| Outputs | mp3 bytes; {text, engine, ms} |
| State | lazy Whisper model |
| Persistence | HF model cache |
| Capabilities | hallucination filter |
| Limitations | English only in practice |
| Code | backend/syrax/voice.py |
| Tests | backend/syrax/test_voice.py |
| Failure Modes | offline → /tts 502; Whisper load error → /stt 500 |

## Verification gate

Runs real gates (py_compile, pytest, tsc, eslint, node test, isolated next build, diff scan) and records GREEN/BLOCKED with per-gate evidence in the journal.

| | |
|---|---|
| Dependencies | subprocess; git; syrax.journal |
| Inputs | python -m syrax.verify [--gate ...] [--journal file] |
| Outputs | report, exit code 0/1, verifications row + verification.completed event |
| State | none |
| Persistence | journal verifications table |
| Capabilities | NOT_VERIFIED when a gate cannot run; next build on a scratch copy so live .next is untouched |
| Limitations | performance gate has no benchmark yet (NOT_VERIFIED, optional); no independent-review gate; review is done by the operator/agent |
| Code | backend/syrax/verify.py |
| Tests | backend/syrax/test_verify.py |
| Failure Modes | missing venv/node → NOT_VERIFIED → BLOCKED |

## OpenManus core (upstream)

BaseAgent/ReActAgent/ToolCallAgent loop, LLM client, tool collection, config, loguru logging. Untouched since import.

| | |
|---|---|
| Dependencies | pydantic 2; openai; tenacity; tiktoken; loguru; mcp |
| Inputs | config/config.toml ([llm] dummy, [daytona] required to boot) |
| Outputs | logs/<timestamp>.log per process |
| State | in-memory Memory, AgentState |
| Persistence | none |
| Capabilities | planning tool/flow (unused by SYRAX) |
| Limitations | no callbacks; SYRAX hooks by subclassing |
| Code | backend/app/** |
| Tests | backend/tests/** (sandbox, browser MCP; not run by SYRAX gate) |
| Failure Modes | missing [daytona] → config crash at boot |

## Process supervision

syrax.sh starts backend (8765) and Next (3000) in separate process groups; systemd user service restarts on failure and opens the UI.

| | |
|---|---|
| Dependencies | bash; setsid; ss; npx; systemd --user |
| Inputs | --dev, --service, --install-service, --status |
| Outputs | two processes; ~/.config/systemd/user/syrax.service |
| State | none |
| Persistence | systemd unit |
| Capabilities | rebuild .next when sources are newer; refuse to start on busy ports |
| Limitations | one instance per machine |
| Code | syrax.sh |
| Tests | none (manual) |
| Failure Modes | either process exiting stops both; systemd restarts after 5 s |

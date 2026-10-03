# SYRAX Architecture

SYRAX is a local autonomous agent built as three layers: the upstream **OpenManus** agent foundation ([`backend/app/`](../backend/app/): `BaseAgent` → `ReActAgent` → `ToolCallAgent` → `Manus`, tool collection, config, logging), the **SYRAX layer** ([`backend/syrax/`](../backend/syrax/): durable journal, core, self-model, autonomy, dev loop, skills, presentation, brain router) and a **Next.js orb UI** ([`frontend/`](../frontend/)). It runs on the owner's own machine (Windows, Linux or macOS) and is started with one command, [`syrax.py`](../syrax.py), which launches two processes: the FastAPI backend on `127.0.0.1:8765` and the Next.js UI on `127.0.0.1:3000`. There is exactly one `Core` per journal: the backend process takes an OS lock on `journal.db.owner` when it opens the journal, and any second `Journal` opened while that lock is held is read-only. Everything below is marked **CURRENT** (exists and is tested), **PARTIAL** (exists with a known gap) or **PLANNED** (not built); nothing planned is described as existing. Capability/limitation detail per component lives in [`SYSTEM_MAP.md`](SYSTEM_MAP.md); the execution semantics (transitions, recovery, resume) in [`EXECUTION_MODEL.md`](EXECUTION_MODEL.md).

## 1. Layers

```
┌───────────────────────────────────────────────────────────────────────────┐
│ Frontend (Next.js 16, React 19, Three.js)            http://127.0.0.1:3000 │
│   components/Syrax.tsx · Stage.tsx · HistoryView.tsx · SelfPanel.tsx      │
│   lib/syraxClient.ts (ClientMessage → / ← ServerEvent, backoff reconnect)  │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ WebSocket /ws · HTTP /stt /tts /voice /self /health
┌──────────────────────────────▼────────────────────────────────────────────┐
│ FastAPI server (backend/syrax/server.py)             ws://127.0.0.1:8765  │
│   lifespan: open journal → crash recovery → optional auto-resume          │
│   Session per connection: observer + command router (dispatch on type)    │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ Core.submit / cancel / answer / resume
┌──────────────────────────────▼────────────────────────────────────────────┐
│ SYRAX layer (backend/syrax/)                                              │
│   core.py ── journal.py (SQLite WAL, owner lock) ── selfmodel.py          │
│   autonomy.py (+limits/plan/followup/radar/skillevo/consolidate)          │
│   devloop.py + verify.py + review.py · skills.py · presentation.py        │
│   brains.py BrainRouter (+routing.py/scorecard.py) · memory.py            │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ SyraxAgent.run(request)
┌──────────────────────────────▼────────────────────────────────────────────┐
│ Agent (backend/syrax/agent.py: SyraxAgent ⊂ Manus ⊂ ToolCallAgent)        │
│   think → BrainRouter.ask_tool → act → execute_tool → checkpoint           │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │ tool calls
┌──────────────────────────────▼────────────────────────────────────────────┐
│ Tools: python_execute · str_replace_editor · desktop · browser_* (MCP)    │
│   research/know/learn · remember/recall/forget · skill_* · release        │
│   present · experiment · compare_versions · self_inspect · journal_query  │
│   ask_human · terminate · VERIFIED skills from backend/skills/            │
└──────────────────────────────┬────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼────────────────────────────────────────────┐
│ OS / external: files, child processes, dedicated Chrome (browser-use MCP) │
│   LLM providers (OpenAI-compatible HTTP), DuckDuckGo, edge-tts, Groq STT  │
└───────────────────────────────────────────────────────────────────────────┘
```

## 2. One task, end to end

1. **Submit.** [`Syrax.tsx`](../frontend/components/Syrax.tsx) `submit()` sends `{"type":"task","text":…,"voice?":…}` through [`SyraxClient`](../frontend/lib/syraxClient.ts) (an `answer` instead when a question is pending).
2. **Session.** [`server.py`](../backend/syrax/server.py) `ws_endpoint` checks the `Origin` allow-list (`localhost:3000`, `127.0.0.1:3000`), creates a `Session`, and `Session.handle` dispatches on `msg["type"]`. For `task` it refuses when `core.busy` ("Already executing"), broadcasts the `user` echo, then calls `Core.submit`.
3. **Core.submit** ([`core.py`](../backend/syrax/core.py)): under `_submit_lock`, busy check → `ensure_agent()` (builds the `SyraxAgent` once, wires engines into tools, attaches VERIFIED skills) → `devloop.begin_task()` (records which repo files were already dirty, so the task owns only its own edits) → `journal.start_task` (task row `IN_PROGRESS`, `task.started` event) → `_route` (routing.py may pick a brain measured best for this kind of request; `brain.routed` journaled) → `Running{task_id, goal, session_id, asyncio.Task}` → `asyncio.create_task(_run)`.
4. **SyraxAgent.run** ([`agent.py`](../backend/syrax/agent.py)): rebuilds the system prompt (persona + tool guide + `MemoryStore.prompt_block()`), emits `state: thinking`, then runs the OpenManus step loop (`max_steps` 20). Each `think()` emits `state: thinking{step}` and a journaled `think`; the LLM call goes through **`BrainRouter.ask_tool`** ([`brains.py`](../backend/syrax/brains.py)): providers tried in the saved order (routed brain first when set), skipping those in cooldown, emitting `brain.failover` / `brain.answered`; all failing → `BrainError`.
5. **Tool step.** `execute_tool` emits `tool_start{step}` and `state: acting{tool}`, runs the tool (repeated identical calls are refused as loops; `browser_*` first ensures the dedicated Chrome), then emits `tool_result{ok, output, image?}`. `act()` then calls the core's checkpoint hook with stage `observed:<tools>`.
6. **Journal first, then fan-out.** Every agent event goes to `Core.emit`; `_journal_type` maps `tool_start → tool.started`, `tool_result → tool.completed|tool.failed`, `think/ask/final`, `brain.*`; everything else (`state`, `notice`, `error`) is broadcast directly. `Journal.record` writes event + task-row update in one transaction, then notifies subscribers: `Core._on_journal_event` → `broadcast` to every `Session.send`, and `PresentationEngine.on_event` → `presentation.created/dismissed` → `Stage.tsx`. A failed journal write sets `unjournaled` on the running task and forwards the event with `"unjournaled": true`.
7. **Checkpoints.** `Core._checkpoint` → `Journal.checkpoint`: a `checkpoints` row (completed steps, in-flight operation, evidence state, agent context ≤ 200 KB) plus a `checkpoint.created` event, after every tool step and once more at `final`.
8. **Finish.** `_run` records `final`, the final checkpoint, then `task.completed{SUCCESS|PARTIAL}` (`PARTIAL` when the step limit was hit; the journal refuses success without a non-empty `final`). Non-conversation tasks that left uncommitted repo edits get them rolled back (`rollback.created`). `finally`: `current = None`, broadcast `state: idle`. The UI renders the event feed and console tabs from these same events; a reconnect receives `hello{interrupted, running, recent}` and a `task_events` replay when a task is running.

## 3. Components by layer

Each component below uses its exact name from [`system_map.json`](system_map.json); follow the link for its full capability and limitation lists.

### Frontend layer

### Frontend HUD
- **Status:** CURRENT ([map](SYSTEM_MAP.md#frontend-hud))
- **Purpose:** Orb UI that renders journaled events as a feed, the stage, console tabs (LIVE / HISTORY / TODAY), brain/self/mind panels and the voice pipeline.
- **Entry point:** [`frontend/components/Syrax.tsx`](../frontend/components/Syrax.tsx): `onEvent` switch over `ServerEvent.type`, `submit()`.
- **Important files:** [`lib/syraxClient.ts`](../frontend/lib/syraxClient.ts) (message types, `SyraxClient`), [`Stage.tsx`](../frontend/components/Stage.tsx), [`HistoryView.tsx`](../frontend/components/HistoryView.tsx), [`SelfPanel.tsx`](../frontend/components/SelfPanel.tsx), `lib/wake.ts`, `lib/mic.ts`, `lib/orbScene.ts`.
- **Dependencies:** Next 16, React 19, three, @mediapipe/tasks-vision; the WebSocket at `NEXT_PUBLIC_SYRAX_WS` (default `ws://127.0.0.1:8765/ws`).
- **Inputs:** `ServerEvent` JSON; `/stt`, `/tts` HTTP; microphone and camera.
- **Outputs:** `ClientMessage` JSON (`task`, `answer`, `stop`, `resume`, `history`, `task_detail`, `autonomy`, `brains_*`, …); speech.
- **Persistence:** none server-side; `localStorage syrax.*` preferences only. Feed capped at 300 entries in memory.
- **Failure behavior:** WS offline → exponential reconnect (800 ms × 2ⁿ, max 15 s), orb shown as booting; WebGL missing → CSS orb; TTS 502 → browser voice.

### Server layer

### WebSocket server + Session
- **Status:** CURRENT ([map](SYSTEM_MAP.md#websocket-server--session))
- **Purpose:** FastAPI app: `/ws` sessions, `/stt`, `/tts`, `/voice`, `/self`, `/health`; lifespan opens the journal (running recovery), optionally auto-resumes, starts the autonomy loop if enabled.
- **Entry point:** [`server.py`](../backend/syrax/server.py): `app`, `lifespan`, `Session.boot/handle/close`, `ws_endpoint`, `main` (uvicorn on `SYRAX_HOST:SYRAX_PORT`).
- **Important files:** `server.py` only; tests in `test_bridge.py`, `test_voice.py`, `test_submit_race.py`, `test_stop_source.py`.
- **Dependencies:** fastapi, uvicorn, `syrax.core`, `syrax.journal`, `syrax.brains`, `syrax.voice`, `syrax.briefing`.
- **Inputs:** ~40 `ClientMessage` kinds dispatched in `Session.handle` (`task`, `answer`, `stop`, `reset`, `history`, `task_events`, `task_detail`, `replay`, `resume`, `self_model`, `objectives`, `autonomy`, `cycle_now`, `quality_run`, `brains_*`, …).
- **Outputs:** `hello{tools, interrupted, running, recent, autonomy, presentation}`, `brains`, `state`, journaled wire events, query replies, `notice`, `error`.
- **Persistence:** none directly; the task lives in `Core`, records in the journal.
- **Failure behavior:** malformed JSON or a command exception → `error` event, session survives; disconnect → `Session.close()` only (task keeps running); disallowed origin → close 1008.

### SYRAX layer

### Core
- **Status:** CURRENT ([map](SYSTEM_MAP.md#core)). Note: crash recovery reality-checks only `str_replace_editor` operations; every other in-flight tool is `UNCERTAIN`.
- **Purpose:** The single SYRAX entity: owns the agent and the one running task, routes agent events through the journal, fans wire events to sessions, resumes interrupted tasks, cleans uncommitted self-edits after autonomous tasks.
- **Entry point:** [`core.py`](../backend/syrax/core.py): `Core.submit`, `_run`, `emit`, `_journal_type`, `_checkpoint`, `cancel`, `answer`, `resume`, `auto_resume`, `get_core()`.
- **Important files:** `core.py`; wires `SelfModel`, `Autonomy`, `Researcher`, `SkillFactory`, `DevLoop` (+ `_cross_review`), `VersionComparer`, `PresentationEngine`, `ExperimentEngine` into the agent's tools in `_build_agent`.
- **Dependencies:** `syrax.agent`, `syrax.journal`, `syrax.brains`, `syrax.memory`, `syrax.devloop`, `syrax.routing`.
- **Inputs:** `submit(goal, said, session_id, kind)`, `cancel()`, `answer(text)`, `reset()`, `resume(task_id)`, `auto_resume()`, `wait()`.
- **Outputs:** journal writes; `broadcast()` to subscribed sessions; last `state` event kept for reconnect snapshots.
- **Persistence:** via the journal (tasks, events, checkpoints); `backend/config/rollback/*.patch` when it rolls back a task's leftovers.
- **Failure behavior:** exception in the agent → `task.failed` + `error`; cancel → `task.cancelled` + notice; `sqlite3.Error`/`JournalError` → `task.failed "journal unavailable"`, never success; busy → `submit` returns `None`.

### Journal
- **Status:** CURRENT ([map](SYSTEM_MAP.md#journal)). Same note as Core: `CHECKABLE_TOOLS = {"str_replace_editor"}`; `python_execute`, `browser_*`, `desktop` side effects are not verified after a crash.
- **Purpose:** Durable execution record and single source of truth: tasks with an enforced status transition table, events, semantic checkpoints, verifications, objectives, knowledge, skills, benchmarks, quality runs, experiments; crash recovery; fan-out to subscribers; bounded maintenance.
- **Entry point:** [`journal.py`](../backend/syrax/journal.py): `Journal.__init__` (opens, locks owner, runs `recover_interrupted`), `start_task`, `record`, `checkpoint`, `verify_operation`, `resume_context`, `maintain`, `get_journal()`.
- **Important files:** `journal.py` (imports nothing from OpenManus); `test_journal.py` (SIGKILL matrix, transition table, idempotent recovery).
- **Dependencies:** stdlib only (sqlite3, threading, asyncio, subprocess for `git rev-parse`).
- **Inputs:** `start_task`, `record(type, payload, task_id)`, `checkpoint`, `record_verification`, `add_objective/knowledge/skill/benchmark/quality_run/experiment`, `mark_resumed`.
- **Outputs:** `Event` objects (`wire()` renames to frontend types) to subscribers; query methods (`task`, `tasks`, `events`, `task_detail`, `events_between`, `tool_stats`, `status_counts`, …).
- **Persistence:** `backend/config/journal.db` (WAL, `synchronous=FULL`, mode 0600; `SYRAX_JOURNAL_FILE` override) + `journal.db.owner` lock file.
- **Failure behavior:** invalid transition / terminal task → `JournalError`, transaction rolled back; `sqlite3.Error` propagates to the core; a crash inside recovery loses nothing and is redone next boot; a second process opening the journal while the owner is alive gets read-only access (or `JournalError` if it asks to recover).

### Self-model
- **Status:** CURRENT ([map](SYSTEM_MAP.md#self-model))
- **Purpose:** Evidence-based model of SYRAX itself: identity from git, structure from `system_map.json` + repo introspection, behaviour/failures from the journal, a capability registry (registered tools × journal evidence), runtime resources, derived weaknesses.
- **Entry point:** [`selfmodel.py`](../backend/syrax/selfmodel.py): `SelfModel.snapshot(section)`, `SelfInspectTool` (`self_inspect`).
- **Important files:** `selfmodel.py`, [`sysinfo.py`](../backend/syrax/sysinfo.py) (cross-platform machine facts), `frontend/components/SelfPanel.tsx`.
- **Dependencies:** journal queries (`status_counts`, `tool_stats`, `tasks`, `verifications`), git, `docs/system_map.json`, core providers (tool names, `brains.describe`, running task).
- **Inputs:** `snapshot(section)` with `summary|identity|structure|runtime|behavior|capabilities|weaknesses|all`; WS `self_model`, `GET /self`, the `self_inspect` tool.
- **Outputs:** JSON snapshot; capability status `VERIFIED / FAILING / NOT_TESTED / MISSING`; weaknesses with evidence pointers.
- **Persistence:** none (computed on demand).
- **Failure behavior:** git unavailable → version/head `None`; map missing → `components []`, `present=false`; `self_inspect` before the core exists → tool error.

### Autonomy
- **Status:** CURRENT ([map](SYSTEM_MAP.md#autonomy))
- **Purpose:** Objectives table plus a bounded self-directed cycle: resource gate → derive objectives (self-model weaknesses, ranked limitations, follow-ups, radar, contradictions) → run one autonomous task through the core → judge from journal evidence only → reflect → retry with a lesson or block after `MAX_ATTEMPTS`.
- **Entry point:** [`autonomy.py`](../backend/syrax/autonomy.py): `Autonomy(core)`: `start()`, `status()`, `cycle`, `enabled`.
- **Important files:** `autonomy.py`, [`resources.py`](../backend/syrax/resources.py), `limits.py`, `plan.py`, `followup.py`, `radar.py`, `skillevo.py`, `consolidate.py`, [`AUTONOMY.md`](AUTONOMY.md).
- **Dependencies:** journal (objectives, meta, events), `SelfModel`, `Core.submit(kind="autonomous")` + `wait()`, `resources` (CPU/RAM/disk/battery/quiet hours).
- **Inputs:** WS `autonomy{enabled}`, `cycle_now`, `objective_add`, `objective_update`, `objectives`; env `SYRAX_AUTONOMY`, `SYRAX_CYCLE_INTERVAL`.
- **Outputs:** `objective.*`, `cycle.*`, `reflection.created`, `autonomy.toggled`, `plan.progressed`, `limitation.ranked`, `maintenance.completed` events; `autonomy_status` replies; autonomous tasks.
- **Persistence:** `objectives` table; `autonomy_enabled` and `last_maintenance` in `meta`; cycle reports in memory only (last 200).
- **Failure behavior:** derivation error → logged, cycle continues; cycle crash → logged, next cycle after the interval; core busy → `BUSY` report, objective back to `OPEN`; off by default and never runs while a human task runs.

### Research engine + knowledge store
- **Status:** CURRENT ([map](SYSTEM_MAP.md#research-engine--knowledge-store))
- **Purpose:** Web research with provenance: search (ddgs, DuckDuckGo lite fallback), fetch pages, extract question-relevant passages, store verbatim excerpts as `knowledge` rows with URL, tags, basis and evidence-derived confidence; `learn` stores cited conclusions; `know` searches by keyword.
- **Entry point:** [`research.py`](../backend/syrax/research.py): `Researcher`, `ResearchTool` (`research`), `KnowTool` (`know`), `LearnTool` (`learn`).
- **Important files:** `research.py`, `journal.py` (knowledge methods), `consolidate.py` (duplicate/contradiction handling on `learn`), [`RESEARCH.md`](RESEARCH.md).
- **Dependencies:** ddgs, requests + bs4 (upstream `WebContentFetcher`), network access to duckduckgo.com, journal `knowledge` table.
- **Inputs:** `research{question, max_sources}`, `know{query}`, `learn{claim, sources, confidence?, tags?}`, WS `knowledge{query?, limit?}`.
- **Outputs:** knowledge rows (kind `web|conclusion|human`); `research.started/completed`, `knowledge.stored`, `knowledge.contradiction` events; `knowledge_list` replies.
- **Persistence:** journal `knowledge` table.
- **Failure behavior:** all engines fail → `UNKNOWN`, nothing stored; page fetch fails → snippet only, basis says not fetched; crash inside the tool → tool error, task continues.

### Skill factory
- **Status:** CURRENT ([map](SYSTEM_MAP.md#skill-factory))
- **Purpose:** SYRAX writes its own tools: `skill_create` takes code + pytest tests, compiles and tests them in a subprocess, registers the tool into the live collection only when the tests pass, records a registry row, and re-registers `VERIFIED` skills at boot.
- **Entry point:** [`skills.py`](../backend/syrax/skills.py): `SkillFactory.create/verify/remove/attach`, `SkillCreateTool`, `SkillListTool`, `SkillTestTool`.
- **Important files:** `skills.py`, [`backend/skills/README.md`](../backend/skills/README.md), `skillevo.py` (real-use counters, repair and candidate proposals), [`SKILLS.md`](SKILLS.md).
- **Dependencies:** journal `skills` table, pytest in the venv, `app.tool.base.BaseTool` / `ToolCollection`.
- **Inputs:** `skill_create{name, purpose, code, test_code, dependencies?, known_limitations?}`, `skill_test{name, action?}`, `skill_list`, WS `skills`.
- **Outputs:** `backend/skills/<name>/{skill.py, test_skill.py, skill.json}`; `skill.created/verified/failed/disabled/not_tested` events; live tools in the agent collection.
- **Persistence:** `skills` table + files under `backend/skills/` (`SYRAX_SKILLS_DIR`), which is outside git.
- **Failure behavior:** compile error → `FAILED` at stage compile; failing/absent tests → `FAILED` with the pytest tail; wrong `Skill.name` → `FAILED` at load; test timeout → `FAILED`; skills that no longer import at boot are demoted.

### Autonomous development loop
- **Status:** PARTIAL ([map](SYSTEM_MAP.md#autonomous-development-loop)). The gate, rollback and cross-brain review exist and are tested; edits happen in the live working tree (no sandbox); SYRAX has never landed its own commit.
- **Purpose:** `release{summary}`: inspect the working tree (scope, forbidden paths, secret/debug scan), snapshot the diff, run the full verification gate, commit on `GREEN` with the verification id in the message, otherwise roll back and hand the evidence to the model. Push only with `SYRAX_AUTOPUSH=1`.
- **Entry point:** [`devloop.py`](../backend/syrax/devloop.py): `DevLoop.begin_task/inspect/snapshot/release/rollback/commit`, `ReleaseTool` (`release`).
- **Important files:** `devloop.py`, [`verify.py`](../backend/syrax/verify.py), [`review.py`](../backend/syrax/review.py) (reviewer set by `core._cross_review`, skipped with `SYRAX_REVIEW=0`), [`DEVLOOP.md`](DEVLOOP.md).
- **Dependencies:** git, `verify.run_gates/default_gates/scan_diff_text`, journal, `BrainRouter` for review.
- **Inputs:** `release{summary, why?, risk?, tests?}`; repo edits made by `str_replace_editor`/`skill_create`; `SCOPE` and `FORBIDDEN` constants.
- **Outputs:** commits authored `SYRAX <syrax@localhost>`; `code.changed`, `verification.completed`, `commit.created/failed`, `rollback.created`, `push.*` events.
- **Persistence:** git history; `backend/config/rollback/*.patch` snapshots; journal events.
- **Failure behavior:** gate `BLOCKED` or review rejected → `rollback.created`, tree restored (`git checkout --`, new files deleted); `git commit` fails → `commit.failed`; push fails → `push.failed`, commit stays local.

### Presentation engine
- **Status:** PARTIAL ([map](SYSTEM_MAP.md#presentation-engine)). Only the stage position is drawn, and the active plan lives in memory: it is not restored after a backend restart.
- **Purpose:** Decides what to show from the real event stream: elements from a small vocabulary (status, card, code, terminal, table, list, image, notification) with attention, priority, ttl, slot replacement and dismissal rules; the model can present explicitly with `present`.
- **Entry point:** [`presentation.py`](../backend/syrax/presentation.py): `PresentationEngine.on_event/on_direct/show/dismiss/plan`, `PresentTool` (`present`).
- **Important files:** `presentation.py`, [`frontend/components/Stage.tsx`](../frontend/components/Stage.tsx), [`PRESENTATION.md`](PRESENTATION.md).
- **Dependencies:** journal subscription (registered by `Core.__init__`), `Core.broadcast` for the unjournaled fallback.
- **Inputs:** journaled events (task, tool, ask, final, research, commit, rollback, skill), direct `error` events, `present{kind, …}`, WS `presentation`, `presentation_feedback`.
- **Outputs:** `presentation.created/dismissed/feedback` events; `hello.presentation` and `presentation_plan` replies.
- **Persistence:** events only; `active` dict in memory.
- **Failure behavior:** journal outage → element still broadcast with `unjournaled=true`; bad `present` arguments → tool error, nothing shown.

### Experiments + benchmarks
- **Status:** CURRENT ([map](SYSTEM_MAP.md#experiments--benchmarks))
- **Purpose:** Measured self-improvement: mechanism benchmarks compared with the previous run (`BASELINE/PASS/REGRESSION`), an experiment engine (baseline vs candidate tool calls, verdict from numbers), a task-quality suite run through the real core and brain, and version comparison of two commits in clean worktrees.
- **Entry point:** [`bench.py`](../backend/syrax/bench.py) `run_suite/run_and_record/main`; [`experiments.py`](../backend/syrax/experiments.py) `ExperimentEngine`, `ExperimentTool`; [`quality.py`](../backend/syrax/quality.py) `QualityRunner`; [`versions.py`](../backend/syrax/versions.py) `VersionComparer`, `CompareVersionsTool`.
- **Important files:** the four modules above, `scorecard.py` (per-brain quality from graded runs), [`EXPERIMENTS.md`](EXPERIMENTS.md).
- **Dependencies:** journal `benchmarks/quality_runs/experiments` tables, the live tool collection, `BrainRouter`, git worktrees (versions).
- **Inputs:** `python -m syrax.bench`; `experiment{hypothesis, baseline, candidate, metric, repeats}`; WS `quality_run{only?, brain?}`, `compare_brains`, `quality_runs`, `benchmarks`, `experiments`; `compare_versions{base, candidate}`.
- **Outputs:** `benchmark.completed`, `experiment.started/completed`, `quality.started/completed` events; table rows; self-improvement objectives.
- **Persistence:** journal tables.
- **Failure behavior:** both arms fail → `INCONCLUSIVE`; benchmark regression → reported and an objective is created; quality suite is on demand only and never part of the release gate.

### Agent layer

### SyraxAgent
- **Status:** CURRENT ([map](SYSTEM_MAP.md#syraxagent))
- **Purpose:** `Manus` subclass that streams think/tool/result events through `emit`, checkpoints after each tool step, refuses repeated identical calls, forces a real final answer, and exports/imports working context for resume.
- **Entry point:** [`agent.py`](../backend/syrax/agent.py): `SyraxAgent.create(emit)`, `run`, `think`, `execute_tool`, `act`, `export_context/import_context`, `repair_memory`.
- **Important files:** `agent.py`, [`prompt.py`](../backend/syrax/prompt.py) (persona), `tools.py` (`WebAskHuman`, `AsyncPythonExecute`), `editor.py`, `journal_query.py`.
- **Dependencies:** `app.agent.manus.Manus`, `syrax.brains.get_router` (replaces the OpenManus `LLM`), `syrax.desktop`, `syrax.browser`, `syrax.memory`.
- **Inputs:** `run(request)`; `checkpoint` hook set by the core; `ask_tool.answer(text)` from the `answer` message.
- **Outputs:** `emit`: `state`, `think`, `tool_start{step}`, `tool_result{step, image?}`, `notice`.
- **Persistence:** none; OpenManus `Memory` (trimmed to ~120 messages) is snapshotted by the journal through `export_context`.
- **Failure behavior:** step limit → `step_limit_hit` → task `PARTIAL`; browser unavailable → error string to the model; abort/interruption → `repair_memory` fixes dangling tool calls.

### BrainRouter
- **Status:** CURRENT ([map](SYSTEM_MAP.md#brainrouter))
- **Purpose:** `LLM`-compatible router over multiple OpenAI-compatible providers (keyless Pollinations, local Ollama, free and paid APIs) with cooldown-based failover, per-task routing hint, model listing and test per provider.
- **Entry point:** [`brains.py`](../backend/syrax/brains.py): `BrainRouter.ask_tool(messages, tools)`, `BrainStore.load/save`, `get_router()`.
- **Important files:** `brains.py`, `routing.py` (sets `router.routed`), `scorecard.py`, `frontend/components/BrainPanel.tsx`.
- **Dependencies:** `openai.AsyncOpenAI`, httpx, `app.llm.LLM` (message formatting), tiktoken counts.
- **Inputs:** `ask_tool(messages, system_msgs, tools, tool_choice)`; WS `brains_get/brains_save/brain_models/brain_test`.
- **Outputs:** `ChatCompletionMessage`; `brain.failover` / `brain.answered` events through listeners; `brains` state for the UI.
- **Persistence:** `backend/config/brains.json` (keys, models, order; gitignored, mode 0600; `SYRAX_BRAINS_FILE`).
- **Failure behavior:** 5xx / empty / malformed → short cooldown and next provider; OOM on local models → smaller fallback model; 401/403 → 1 h cooldown; all providers failing → `BrainError` → `task.failed` with a readable list of reasons.

### MemoryStore
- **Status:** PARTIAL ([map](SYSTEM_MAP.md#memorystore)). A keyword store: facts are `knowledge` rows of kind `human` found by `knowledge_search`; there is no fact/observation/inference typing and no embeddings.
- **Purpose:** Long-term facts about the human (`remember/recall/forget`) and recent conversations for the prompt, both read from the journal; legacy `memory.json` imported once, `history.jsonl` read only as a fallback.
- **Entry point:** [`memory.py`](../backend/syrax/memory.py): `MemoryStore.remember/recall/forget/prompt_block/recent`, `RememberTool`, `RecallTool`, `ForgetTool`, `get_memory()`.
- **Important files:** `memory.py`; `journal.py` (`human_facts`, `knowledge_search`, `forget_knowledge_sync`, `recent_exchanges`).
- **Dependencies:** stdlib; the journal.
- **Inputs:** tool calls; `prompt_block()` at the start of every task.
- **Outputs:** the memory block in the system prompt; `knowledge.stored` / `knowledge.forgotten` events.
- **Persistence:** journal `knowledge` (kind `human`, confidence 1.0) and `tasks`; legacy `backend/config/memory.json`, `history.jsonl` (gitignored).
- **Failure behavior:** secrets are refused; near-duplicates update the existing row; a history write failure is logged and the task still succeeds.

### Tools layer

### Tools
- **Status:** CURRENT ([map](SYSTEM_MAP.md#tools))
- **Purpose:** The agent's hands: `python_execute` (non-blocking child process, guarded), `str_replace_editor` (`SyraxEditor`), `desktop` (Linux/Windows/macOS session control), `browser_*` (browser-use MCP against a dedicated Chrome), `ask_human` (web), `journal_query`, plus the SYRAX-layer tools wired in `Core._build_agent`.
- **Entry point:** [`tools.py`](../backend/syrax/tools.py) (`WebAskHuman`, `AsyncPythonExecute`), [`editor.py`](../backend/syrax/editor.py), [`desktop.py`](../backend/syrax/desktop.py) `DesktopControl`, [`browser.py`](../backend/syrax/browser.py) `ensure_browser`.
- **Important files:** the above, `winctl.py` (Windows window control), `guard.py` + `_guard_site/sitecustomize.py`, upstream `backend/app/tool/*`.
- **Dependencies:** `app.tool.*`, browser-use MCP via `uvx`, Chrome with remote debugging (`BU_CDP_URL`), platform CLIs (xdg-open/wpctl/osascript/PowerShell).
- **Inputs:** tool calls from the agent.
- **Outputs:** `ToolResult` strings (preview capped in events), base64 screenshots (fanned out, never stored).
- **Persistence:** files and screenshots written under `backend/workspace/`; nothing else.
- **Failure behavior:** timeouts and missing binaries → error result to the model, `tool.failed` journaled, the task continues; cancel kills the python child; writes to protected paths (journal, keys) from `python_execute` raise `PermissionError`.

### Voice
- **Status:** PARTIAL ([map](SYSTEM_MAP.md#voice)). Server STT/TTS exist and are tested (`test_voice.py`); the end-to-end microphone path in the browser is unverified.
- **Purpose:** TTS through edge-tts (free neural voices, `SYRAX_TTS_VOICE`), STT through Groq Whisper when a Groq key is saved, otherwise local faster-whisper (`SYRAX_WHISPER_MODEL`).
- **Entry point:** [`voice.py`](../backend/syrax/voice.py): `synthesize(text)`, `transcribe(audio, groq_key)`, `speakable(text)`, `LocalWhisper`.
- **Important files:** `voice.py`; `server.py` routes `/tts`, `/stt`, `/voice`; frontend `lib/mic.ts`, `lib/speech.ts`, `lib/webSpeech.ts`, `lib/wake.ts`, `components/useHandsFree.ts`.
- **Dependencies:** edge-tts (online), faster-whisper (model download), httpx.
- **Inputs:** `POST /tts {text}` (≤ 900 chars after `speakable`), `POST /stt` audio (≤ 12 MB).
- **Outputs:** mp3 bytes; `{text, engine, ms}`.
- **Persistence:** Hugging Face model cache only.
- **Failure behavior:** offline → `/tts` 502 (UI falls back to browser voice); Whisper load error → `/stt` 500; hallucinated transcripts filtered by `_clean`.

### Verification gate
- **Status:** CURRENT ([map](SYSTEM_MAP.md#verification-gate))
- **Purpose:** Runs real gates (`py_compile`, `pytest`, `tsc`, `eslint`, `node_test`, isolated `next_build`, `diff_scan`, optional `performance`) and records `GREEN/BLOCKED` with per-gate evidence; the exit code decides, never the output.
- **Entry point:** [`verify.py`](../backend/syrax/verify.py): `run_gates`, `default_gates`, `scan_diff_text`, `main` (`python -m syrax.verify`, also `python syrax.py --gate`).
- **Important files:** `verify.py`, `test_verify.py`.
- **Dependencies:** subprocess, git, the backend venv and node toolchain, journal.
- **Inputs:** `--gate …`, `--journal file`, `--json`; called by `DevLoop.release`.
- **Outputs:** report, exit code 0/1, `verifications` row + `verification.completed` event.
- **Persistence:** journal `verifications` table.
- **Failure behavior:** a gate that cannot run → `NOT_VERIFIED`; a required `NOT_VERIFIED` blocks like a `FAIL`; `next build` runs on a scratch copy so the live `.next` is untouched.

### Foundation and process layer

### OpenManus core (upstream)
- **Status:** CURRENT ([map](SYSTEM_MAP.md#openmanus-core-upstream))
- **Purpose:** `BaseAgent` / `ReActAgent` / `ToolCallAgent` / `Manus` loop, `LLM` client, `ToolCollection`, config, loguru logging, MCP client. Untouched since import; SYRAX hooks by subclassing.
- **Entry point:** [`backend/app/agent/manus.py`](../backend/app/agent/manus.py) `Manus`, [`backend/app/agent/toolcall.py`](../backend/app/agent/toolcall.py) `ToolCallAgent.execute_tool`.
- **Important files:** `backend/app/**`; upstream tests in `backend/tests/**` (not part of the SYRAX gate).
- **Dependencies:** pydantic 2, openai, tenacity, tiktoken, loguru, mcp.
- **Inputs:** `backend/config/config.toml` (`[llm]` placeholder, `[daytona]` required to boot; created from `config.syrax.example.toml` by `syrax.py --setup`).
- **Outputs:** `backend/logs/<timestamp>.log` per process.
- **Persistence:** none.
- **Failure behavior:** missing `[daytona]` section → config crash at boot; no callbacks, so events exist only through `SyraxAgent` overrides.

### Process supervision
- **Status:** CURRENT ([map](SYSTEM_MAP.md#process-supervision); the map still describes the earlier `syrax.sh`-only launcher)
- **Purpose:** One command starts, installs and supervises SYRAX on Windows, Linux and macOS: setup (venv, requirements, npm, config), stale-UI rebuild, backend + UI as two child processes, login service install, stop via pid file.
- **Entry point:** [`syrax.py`](../syrax.py): `launch`, `setup`, `stop`, `install_service`, `service_status`; [`syrax.sh`](../syrax.sh) and [`syrax.ps1`](../syrax.ps1) are thin wrappers.
- **Important files:** `syrax.py`; generated `~/.config/systemd/user/syrax.service` (Linux), launchd plist `com.syrax.agent` (macOS), Task Scheduler task `SYRAX` or Startup-folder `SYRAX.vbs` (Windows); [`OPERATIONS.md`](OPERATIONS.md).
- **Dependencies:** Python 3, uv or venv, node/npx, git; `schtasks` / `systemctl --user` / `launchctl`.
- **Inputs:** `--dev`, `--setup`, `--gate`, `--install-service`, `--uninstall-service`, `--status`, `--stop`, hidden `--service`; env `SYRAX_PORT`, `SYRAX_UI_PORT`, `SYRAX_OPEN_UI`.
- **Outputs:** two processes in their own process groups (`python -m syrax.server`, `npx next start|dev`), `syrax.pid`, `syrax.log` (service mode outside systemd).
- **Persistence:** the login service definition; `syrax.pid`, `syrax.log` at the repo root.
- **Failure behavior:** either child exiting makes the launcher stop the other and exit; systemd restarts after 5 s on failure, launchd on unsuccessful exit; on Windows the task or `SYRAX.vbs` starts SYRAX again at the next login (no restart-on-failure supervisor). A service start that finds the ports busy steps aside quietly.

## 4. Modules not yet in the system map

All CURRENT and tested (`test_<name>.py` beside each), but not yet audited into `system_map.json`.

**Objective engine** (used by Autonomy):
- [`limits.py`](../backend/syrax/limits.py) ranks SYRAX's limitations from journal counts (impact × confidence) and turns the strongest into an objective with a plan and a check; the ranking is journaled as `limitation.ranked`.
- [`plan.py`](../backend/syrax/plan.py) objective plans whose steps are proven from journal evidence (`tool_ok`, `released`, `learned`), so a retry resumes at the first unproven step.
- [`followup.py`](../backend/syrax/followup.py) derives the next objective from why the last one was BLOCKED (a missed cause, or a learning objective then a briefed retry), bounded by `MAX_DEPTH` and idempotent keys.
- [`review.py`](../backend/syrax/review.py) cross-brain review of an autonomous release: a different brain answers four yes/no questions about the diff and the verdict is computed from the answers.
- [`routing.py`](../backend/syrax/routing.py) picks the brain measured best for a kind of task from graded quality runs, only when the evidence gap is large enough; otherwise the human's order stands.
- [`scorecard.py`](../backend/syrax/scorecard.py) per-brain scorecard from the journal: tasks, success rate, average steps and Laplace-smoothed quality.
- [`radar.py`](../backend/syrax/radar.py) daily technology radar: lists each enabled brain's models, diffs against the last scan, tool-call-tests a few new ones and proposes the working ones to the human.
- [`skillevo.py`](../backend/syrax/skillevo.py) skills that evolve from real use: failure counts per skill version, repair limitations, and repeated human requests proposed as skill candidates.
- [`briefing.py`](../backend/syrax/briefing.py) daily briefing composed from the journal with no model call; shown once a day on the stage and on WS `briefing{hours?}`.
- [`consolidate.py`](../backend/syrax/consolidate.py) knowledge consolidation on `learn`: same subject and figures reinforce the existing row; different figures are stored and journaled as `knowledge.contradiction`.

**Guards:**
- [`guard.py`](../backend/syrax/guard.py) (+ [`_guard_site/sitecustomize.py`](../backend/syrax/_guard_site/sitecustomize.py)) keeps code run by `python_execute`, and every Python it spawns, from writing the journal or the key files: protected SQLite opens read-only, protected file writes raise `PermissionError`. A guard rail, not a sandbox.

**Tools:**
- [`journal_query.py`](../backend/syrax/journal_query.py) read-only SQL over SYRAX's own journal (`mode=ro`, SELECT/WITH only, ≤ 50 rows) with the real schema in the tool description.
- [`editor.py`](../backend/syrax/editor.py) `str_replace_editor` with the mistakes models actually make turned into safe fixes or precise errors (missing path, relative paths, create on existing file, indentation mismatch).
- [`winctl.py`](../backend/syrax/winctl.py) Windows window control through user32: list, focus, minimize, maximize, restore, snap; never closes a window.

**Prompt:**
- [`prompt.py`](../backend/syrax/prompt.py) the `SYRAX_PERSONA` system prompt, formatted with the workspace directory at the start of every task.

## 5. PLANNED (not built)

- **Tool permission levels enforced in code** (improvement 001, landing this session): today every registered tool is callable by the model on equal terms; the only in-code restrictions are the guard's protected paths and the dev loop's `SCOPE`/`FORBIDDEN` lists.
- **Task phase model** (understand / plan / act / observe / verify): tasks today are an undifferentiated OpenManus step loop; checkpoints carry a `stage` string but no phase machine exists.
- **Visible Work Presence**: visibility levels, hide/show of SYRAX's own windows, observation of the human's active window. `winctl.py` can list and focus windows; nothing decides when SYRAX should be visible.
- **Sandboxed self-modification**: the dev loop edits the live working tree and relies on gate + rollback; skills and `python_execute` run in-process or as plain child processes.
- **Embeddings / semantic recall**: `know`, `recall` and consolidation use keyword overlap only.
- **Typed memory** (fact / observation / inference with provenance and expiry): knowledge rows carry `kind`, `confidence`, `basis` and sources, but no such typing or expiry.
- **Multi-brain synthesizer**: `BrainRouter` fails over and routes to one provider per call; `review.py` is the only place two brains are combined, and only for a yes/no verdict.

## 6. Persistence map

| Location | What | Written by | In git? |
|---|---|---|---|
| `backend/config/journal.db` (+ `-wal`, `-shm`) | tables `meta`, `tasks`, `events`, `checkpoints`, `verifications`, `objectives`, `knowledge`, `benchmarks`, `quality_runs`, `experiments`, `skills` | `Journal` (owner process only) | no |
| `backend/config/journal.db.owner` | OS lock file marking the live owner | `journal._lock_owner` | no |
| `backend/config/brains.json` | provider keys, models, order (mode 0600) | `BrainStore.save` from the BRAIN panel | never |
| `backend/config/config.toml` | OpenManus config (`[llm]` placeholder, `[daytona]`) | `syrax.py --setup` from the example | no |
| `backend/config/rollback/*.patch` | diff snapshots taken before a gate or a post-task rollback | `DevLoop.snapshot` | no |
| `backend/config/memory.json`, `history.jsonl` | legacy memory, read once / fallback only | legacy `MemoryStore` | no |
| `backend/skills/<name>/` | skill code, tests, `skill.json` | `SkillFactory` | no (only `README.md`) |
| `backend/workspace/` | files and screenshots produced by tools | tools | no (`example.txt` only) |
| `backend/logs/<timestamp>.log` | loguru log per backend process | upstream logger | no |
| `backend/.syrax-browser/` | the dedicated Chrome profile | `browser.py` | no |
| `syrax.log`, `syrax.pid` (repo root) | launcher output in service mode; launcher pid for `--stop` | `syrax.py` | no |
| login service (`syrax.service`, launchd plist, `SYRAX` task or `SYRAX.vbs`) | start at login | `syrax.py --install-service` | outside the repo |
| browser `localStorage syrax.*` | UI preferences | `Syrax.tsx` | n/a |

## 7. Failure behaviour by layer

| Layer dies / fails | What happens | Where |
|---|---|---|
| Browser tab / UI | Nothing stops: the task runs in the core. `SyraxClient` reconnects with exponential backoff (max 15 s); `Session.boot` replays `hello{interrupted, running, recent}` and, for a running task, `task_events` + the live `state`. | `syraxClient.ts`, `server.py:Session.boot` |
| WebSocket session | `Session.close()` unsubscribes and cancels session-bound side jobs; the task keeps running in `Core`; detached jobs (quality runs, briefings) outlive the session. | `server.py` |
| Server / core process crash or power loss | Next boot: `recover_interrupted` marks every `IN_PROGRESS`/`BLOCKED` task of an older `boot_id` as `INTERRUPTED` with `RESUMABLE` (no operation, or a verified `str_replace_editor` edit), `UNCERTAIN` (any other tool in flight) or `BLOCKED` (question pending). Resume by hand (`resume` / RESUME button) or `SYRAX_AUTO_RESUME=1` for `RESUMABLE` only. | `journal.py`, `core.py:resume/auto_resume` |
| Journal unavailable (sqlite error) | The event is forwarded with `unjournaled: true`; `_run` records `task.failed "journal unavailable"` and broadcasts an `error`; if even that write fails the row stays `IN_PROGRESS` and is marked `INTERRUPTED` next boot. Success is never claimed without a journaled `final`. | `core.py:emit/_run`, `EXECUTION_MODEL.md` §8 |
| Brain (LLM provider) | Cooldown for the failing provider, `brain.failover` event, next provider in order; all failing → `BrainError` → `task.failed` with a readable per-provider reason list and an `error` event. | `brains.py:ask_tool/_penalize` |
| Tool | Error text returned to the model, `tool_result{ok:false}` → `tool.failed` journaled, the agent decides the next step; timeouts kill the python child; repeated identical calls are refused as loops. | `agent.py:execute_tool`, `tools.py` |
| Autonomy cycle | Derivation or cycle exceptions are logged and the loop continues at the next interval; a busy core yields `BUSY` and the objective returns to `OPEN`. | `autonomy.py` |
| Dev loop release | `BLOCKED` gate or rejected review → rollback to the snapshot, `rollback.created`; a task ending with uncommitted self-edits is rolled back by the core so a restart never loads half-finished code. | `devloop.py`, `core.py:_clean_repo_after_task` |
| Launcher / child process | If the backend or UI exits, `syrax.py` stops the other and exits; systemd restarts it after 5 s, launchd on unsuccessful exit; on Windows the Task Scheduler task or `SYRAX.vbs` in the Startup folder starts it again at the next login. | `syrax.py:launch/install_service` |

# SYRAX Presentation Engine

Implemented in `backend/syrax/presentation.py` (engine + `present` tool) and
`frontend/components/Stage.tsx` (renderer). Tests: `backend/syrax/test_presentation.py`
and the presentation section of `test_bridge.py`.

## Principle

The UI is not the brain. The engine lives in the core, observes the real event
stream, and decides **what** to show, **why**, **how much attention** it needs,
**how long** it stays, **what it replaces** and **what dismisses it**. The
frontend's Stage draws the current plan and removes elements when told (or
when their ttl passes). When the plan is empty the Stage renders nothing.

## Vocabulary

| kind | drawn as |
|---|---|
| status | one line of ambient text (what SYRAX is working on, which tool is operating) |
| card | a short text block (the reply, a commit, a new skill) |
| code | a code block with optional path (code being executed, file being edited) |
| terminal | output of executed code |
| table | rows of cells (first row is the header) |
| list | items, or a research summary |
| image | a base64 image |
| notification | error / question / warning with focus attention |

Element fields: `presentation_id, kind, purpose, data, attention (ambient|notice|focus),
position (stage|overlay), priority 1-5, ttl_s, replaces, dismiss_on, slot, source
(engine|model), created, task_id`.

## Decisions the engine makes (from events)

| event | decision |
|---|---|
| task.started | ambient status with the goal; dismissed by any task end |
| tool.started python_execute | code (slot tool, 120 s) |
| tool.started str_replace_editor create/str_replace/insert | code with path (slot tool) |
| tool.started browser_* / desktop / research | ambient status (slot tool) |
| tool.completed python_execute | terminal with the output (replaces the code element) |
| tool.failed | error notification, focus, 45 s |
| ask | question notification, focus, dismissed by the answer |
| research.completed | list summary, 180 s |
| final | card with the reply, 90 s |
| task.completed/failed/cancelled/interrupted | tool slot cleared; reply/alerts linger to their ttl |
| task.interrupted, rollback.created | warning notification |
| commit.created, skill.verified | card |
| direct `error` | error notification |

Slots (`task`, `tool`, `alert`, `reply`, `model`) hold one element each: a new
element in a slot replaces the previous one, so old information does not pile up.

## SYRAX choosing to present

`present {kind: card|code|table|list|notification|none, title?, text?, language?,
rows?, items?, ttl_s?, attention?}` lets the model put its own element on the
stage (source = model, slot model) or clear it with `kind: none`.

## Persistence and observability

`presentation.created` / `presentation.dismissed` are journaled (with the task)
so WHY can tell what was shown; they are pruned by maintenance after 30 days
and hidden from the TODAY replay. `hello` carries the current plan so a
reconnecting browser sees the same stage; `presentation` over WebSocket
returns it on demand.

## Limits

- Rules are hand-written state→decision mappings; the engine does not learn
  which presentations work (no measurement of attention or usefulness yet).
- Only the `stage` position is rendered; `overlay` is accepted but drawn in the stage.
- No 3D scenes, maps, charts or video in the vocabulary yet.

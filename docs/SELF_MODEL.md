# SYRAX Self-Model

Implemented in `backend/syrax/selfmodel.py`; tested by `backend/syrax/test_selfmodel.py`
and the self-model section of `backend/syrax/test_bridge.py`.

Conceptual model: **Structure + Behavior + Capability + Performance + Failure**.

| Section | Source | What it contains |
|---|---|---|
| `identity` | git, constants | name, `version` = short git HEAD actually running (null without git), stage, principles, boot id, process uptime |
| `structure` | `docs/system_map.json` + repo | git head/branch/dirty count/last 10 commits, files/lines/tests per area, component list from the map, whether the map is present |
| `runtime` | OS, journal, core | host, python, pid, CPU cores + load, RAM total/available, disk, journal path/size, brains (active/ready/cooldown/needs key), running task; `gpu` is null (not probed) |
| `behavior` | journal | tasks by status, success rate, last 10 tasks, recent failures, interrupted tasks with recovery state, verifications (last, green/blocked counts) |
| `capabilities` | registered tools × journal `tool_stats()` | per tool: status `VERIFIED` (last use ok) / `FAILING` (last use failed) / `NOT_TESTED` (never used) / `MISSING` (evidence but not registered), uses, successes, failures, confidence, last used/failed, implementation file |
| `weaknesses` | derived from the above + map limitations | failing or never-used tools, UNCERTAIN interrupted tasks, last verification BLOCKED, low success rate, known limitations from the map; each with an `evidence` pointer |
| `summary` | all of the above | compact view for the tool and the SELF panel |

Access:
- tool `self_inspect {section}` (registered on the agent; the tool guide tells the
  model to use it instead of guessing),
- WebSocket `{"type":"self_model","section":"summary"}` → `{"type":"self_model", ...}`,
- `GET /self?section=…`,
- the SELF panel (`S`) in the UI, read-only.

Rules: no invented values (null/none when unmeasurable), no hard-coded answers
(every capability status comes from journal evidence), and the static map is
never the only source — it is merged with runtime and history.

Not yet: performance/latency aggregation, GPU probing, an objectives engine
that consumes the weaknesses.

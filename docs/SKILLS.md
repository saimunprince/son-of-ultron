# SYRAX Skill Factory

Implemented in `backend/syrax/skills.py`, registry table `skills` in the journal,
files under `backend/skills/<name>/`. Tests: `backend/syrax/test_skills.py` and the
skill section of `test_bridge.py`.

## Contract

A skill is an ordinary OpenManus tool:

```python
from app.tool.base import BaseTool, ToolResult

class Skill(BaseTool):
    name: str = "<skill name>"          # must equal the directory name
    description: str = "..."
    parameters: dict = {...}             # JSON schema
    async def execute(self, **kwargs) -> ToolResult: ...
```

with pytest tests that import it as `from skills.<name>.skill import Skill`.

### Risk level

A skill may say what it does, as a class attribute:

```python
class Skill(BaseTool):
    risk: str = "EXTERNAL_READ"      # optional
```

Allowed values: `READ_ONLY`, `WRITE`, `EXTERNAL_READ`, `SYSTEM`,
`EXTERNAL_WRITE`, `DESTRUCTIVE` (`backend/syrax/permissions.py`). The
effective level is the highest of `WRITE` (the floor), what `skill.py` shows
(deletes, sends, shells, network, file writes) and the declaration, so `risk`
can only raise the level, never hide what the code does; an unknown value is
ignored. It is stored as `evidence.risk` in `skill.json`, declared to the
permission check when the skill is registered, and shown per tool in the SELF
panel.

## Lifecycle

```
skill_create {name, purpose, code, test_code, dependencies?, known_limitations?}
  → validate name (^[a-z][a-z0-9_]{2,30}$), refuse built-in names, require tests
  → write skill.py / test_skill.py atomically
  → py_compile both
  → pytest test_skill.py in a subprocess (120 s timeout, isolated journal)
  → passed > 0 and failed == 0 and the module loads with the right name
        → VERIFIED: registered into the live tool collection (usable on the next think step)
        → otherwise FAILED: files kept, pytest tail stored as evidence, NOT registered
  → registry row (name, version, purpose, path, status, tests passed/failed,
    evidence, dependencies, known limitations, created task, last_verified)
  → skill.json beside the code
```

Events: `skill.created`, `skill.verified`, `skill.failed`, `skill.disabled`,
`skill.rolled_back`, `skill.enabled` (and `skill.prebuilt` from `prebuilt.py`).
`skill_test {name}` re-runs the tests (version increments, status follows the
result); `skill_test {name, action: remove}` disables and unregisters.
`skill_list` shows status, tests, version and whether the skill is registered.

At boot, `SkillFactory.attach()` registers every VERIFIED skill from the
registry; one that no longer imports is demoted to FAILED with the reason.

## Versions, rollback, disable, duplicates

Two counters (audit 2026-10-25). `version` in the registry counts verifications
and bumps on every `skill_test`, as before. `content_hash` is sha256 over the
skill folder's `.py` files (sorted by name, newlines normalized) and
`code_version` moves only when that hash changes; both are in the registry row,
`skill.json`, `skill_list`, the WS `skills` reply and every `skill.*` event. A
re-test of unchanged code therefore keeps `code_version` while `version` grows.
At boot, `attach()` gives a VERIFIED row with no `content_hash` (verified before
the hash existed and never re-verified, as a prebuilt skill that stays current)
the hash of its files on disk (`journal.backfill_skill_hash_sync`); neither
counter moves, so the skill's next code change is a new `code_version` and the
original code is kept under `.versions/`.

Kept versions. Before `skill_create` (or a prebuilt reinstall) writes different
code over a VERIFIED skill, the current files go to
`backend/skills/<name>/.versions/<code_version>/` (the last 5 are kept). The
human's WS `skill_rollback {name}` (MindPanel ROLLBACK; no agent tool) puts the
newest kept version back, re-runs its tests through the normal verify path
(VERIFIED and registered only when they pass, FAILED with the evidence otherwise),
and journals `skill.rolled_back {skill, from_hash, to_hash, status}`. The code it
replaces is kept too, so a second rollback undoes the first; with nothing kept
the request is refused.

Disable sticks. `skill_test {action: remove}` sets DISABLED in the registry and
that is remembered: the skill is not registered at boot, `prebuilt.install`
skips it (outcome `DISABLED`), and `skill_create` or `skill_test` with that name
is refused with "<name> was disabled by the human; `skill_enable` turns it back
on" until the human's WS `skill_enable {name}` (MindPanel ENABLE) re-verifies and
re-registers it (`skill.enabled`).

Duplicates. `skill_create` for a new name is refused when a VERIFIED skill has a
purpose whose content words overlap by 0.7 or more (Jaccard), or the same set of
two or more `parameters` property names with a purpose overlap of 0.4 or more:
"a skill for this exists: <name> — <purpose>; extend it (skill_create with that
name) instead of a duplicate". Identical argument names alone never refuse
(`translate {text}` lives beside `word_count {text}`). Re-creating under the
same name stays allowed; that is how a skill is improved.

## Truthfulness

- A skill is never VERIFIED without a passing test run in a fresh process.
- Re-creating with the same name replaces the code and bumps the version;
  the old status never carries over.
- The self-model lists skills under `structure.skills`; once registered they
  appear in the capability registry with usage evidence like any tool.

## Limits

- Skill code runs in the server process (no sandbox), like `python_execute`
  and every other tool. This is the owner's machine by design.
- Dependencies are recorded, not installed.
- No automatic skill generation from objectives yet: the model decides to
  build a skill when the tool guide's condition applies (a capability it lacks
  and will need again). Generated skills are not auto-committed; Phase 8 adds
  the gate-driven commit path.

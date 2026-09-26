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

Events: `skill.created`, `skill.verified`, `skill.failed`, `skill.disabled`.
`skill_test {name}` re-runs the tests (version increments, status follows the
result); `skill_test {name, action: remove}` disables and unregisters.
`skill_list` shows status, tests, version and whether the skill is registered.

At boot, `SkillFactory.attach()` registers every VERIFIED skill from the
registry; one that no longer imports is demoted to FAILED with the reason.

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

# SYRAX skills

Tools that SYRAX writes for itself. Each skill lives in its own directory:

```
skills/<name>/skill.py        class Skill(BaseTool) with name, description, parameters, async execute
skills/<name>/test_skill.py   pytest tests; the skill is registered only when they pass
skills/<name>/skill.json      metadata written by the factory (purpose, version, status, evidence, …)
```

The registry of record is the `skills` table in the journal; `skill.json` is a
human-readable copy. A skill whose tests fail is kept on disk with its evidence
and is never registered. See `docs/SKILLS.md`.

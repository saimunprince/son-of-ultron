# Prebuilt skills

Features that ship with SYRAX. Each directory is a skill in the factory's
format (`skill.py` with `class Skill(BaseTool)`, `test_skill.py` loading the
`skill.py` next to it). When the service runs with `SYRAX_FEATURES=1`,
`syrax/prebuilt.py` copies each one into the skill folder and the skill
factory verifies it like a skill SYRAX wrote: the safety check first, then its
own tests; only a VERIFIED skill becomes a live tool, at the permission level
its source and its declared `risk` give it.

The ideas come from the feature catalog (`docs/FEATURE_CATALOG.md`); the code
is SYRAX's own.

"""Prebuilt skills: features that ship with SYRAX in git (backend/prebuilt/<name>/).

Each one is installed into the skill folder and verified by the skill factory
exactly like a skill SYRAX writes itself: its own tests must pass before it is
a live tool, the safety check refuses host-harming code before anything runs,
and its permission level comes from its source and its declared risk.

Runs once after the agent is built when the service asks for it
(SYRAX_FEATURES=1, set by the launcher). A prebuilt skill is installed when it
is missing, reinstalled when its shipped files changed, and re-verified when it
is not VERIFIED. A skill of the same name that SYRAX made itself (no
provenance marker) is never overwritten.

This file decides what becomes a live tool, so SYRAX's own releases may not
change it (devloop.JUDGES).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any, Dict, List

from syrax.journal import BACKEND_ROOT

PREBUILT_ROOT = BACKEND_ROOT / "prebuilt"
FILES = ("skill.py", "test_skill.py")
MARKER = ".prebuilt"  # in the installed copy: the digest of the shipped files it came from


def digest(skill_dir: Path) -> str:
    h = hashlib.sha256()
    for f in FILES:
        h.update(f.encode() + b"\0" + (skill_dir / f).read_bytes() + b"\0")
    return h.hexdigest()


def shipped(root: Path = PREBUILT_ROOT) -> List[Path]:
    from syrax.skills import NAME_RE

    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if d.is_dir() and NAME_RE.match(d.name) and all((d / f).is_file() for f in FILES))


def purpose_of(skill_dir: Path) -> str:
    """The first line of skill.py's docstring."""
    text = (skill_dir / "skill.py").read_text(encoding="utf-8", errors="replace").lstrip()
    if text[:3] in ('"""', "'''"):
        return text[3:].split("\n", 1)[0].strip().rstrip('."') or skill_dir.name
    return skill_dir.name


async def install(factory: Any, root: Path = PREBUILT_ROOT) -> List[Dict[str, Any]]:
    """Install and verify every shipped skill that needs it. Journals one
    `skill.prebuilt` event with the outcome per skill (when anything was looked at)."""
    out: List[Dict[str, Any]] = []
    for src in shipped(root):
        name, want = src.name, digest(src)
        dst = Path(factory.root) / name
        marker = dst / MARKER
        if dst.exists() and not marker.exists():
            out.append({"skill": name, "outcome": "KEPT", "reason": "a skill of this name was made by SYRAX itself"})
            continue
        row = factory.journal.skill(name)
        if row and row.get("status") == "DISABLED":
            # the human disabled it (skill_test remove); a reinstall would register it again behind their back
            out.append({"skill": name, "outcome": "DISABLED", "reason": "disabled by the human; skill_enable turns it back on"})
            continue
        have = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
        if have == want and row and row.get("status") == "VERIFIED":
            out.append({"skill": name, "outcome": "CURRENT"})
            continue
        factory.keep_version(name)  # a VERIFIED copy stays under .versions/ for the human's skill_rollback
        dst.mkdir(parents=True, exist_ok=True)
        for f in FILES:
            shutil.copyfile(src / f, dst / f)
        (dst / "__init__.py").write_text("", encoding="utf-8")
        marker.write_text(want, encoding="utf-8")  # provenance, whatever the tests say
        try:
            verified = await factory.verify(name, purpose=purpose_of(src), dependencies=[])
            out.append({"skill": name, "outcome": verified.get("status"), "installed": "updated" if have else "new"})
        except Exception as e:  # one broken skill never stops the others
            out.append({"skill": name, "outcome": "FAILED", "reason": str(e)[:200]})
    if out:
        await factory.journal.record("skill.prebuilt", {"skills": out})
    return out

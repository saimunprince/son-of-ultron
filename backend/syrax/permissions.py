"""Tool permission levels, enforced in code (improvement 001, 2026-10-03).

Until now the only thing between SYRAX and a destructive action was a line
in its persona ("confirm with ask_human before deleting"). Two incidents in
one week (a skill that killed every large process; the journal edited from
python_execute) were each patched by a narrow guard afterwards. This module
is the general rule, applied once, at the agent's single tool choke point
(``SyraxAgent._permit``):

  level            what the call does                        conversation  eval     autonomous
  READ_ONLY        observes                                  allow         allow    allow
  WRITE            changes files / SYRAX's own state         allow         allow    allow
  EXTERNAL_READ    reads from the network / a web page       allow         allow    allow
  SYSTEM           acts on the host beyond files             allow         allow    refuse
  EXTERNAL_WRITE   sends, posts, pays                        authorize     by words refuse
  DESTRUCTIVE      deletes, discards history                 authorize     by words refuse
  harm             kills processes / power / system config   refuse        refuse   refuse

"authorize": the human's own words are the confirmation. If the request
named the action and every target the call touches, it runs. Otherwise SYRAX
asks once, exactly for that call, and silence or anything but a yes refuses
it. A quality run (eval) is unattended, so it never asks: by words, or not
at all. Autonomous work never destroys and never touches the host; it
reports instead. (Writes outside the repository are allowed: python_execute
could not be checked for scope anyway, and the editor's edits are journaled
and rolled back by the dev loop when a task ends without a release.)

Levels are static per tool, refined per call for the polymorphic ones
(editor command, desktop action, python code, skill code). Dynamic skills
may declare ``risk`` on their Skill class; the declared level can only raise
what their source shows. Everything here is pure functions over strings:
no model, every decision readable in the journal.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from syrax import guard
from syrax.journal import BACKEND_ROOT

REPO_ROOT = BACKEND_ROOT.parent
WORKSPACE = BACKEND_ROOT / "workspace"

READ_ONLY, WRITE, EXTERNAL_READ, SYSTEM, EXTERNAL_WRITE, DESTRUCTIVE = (
    "READ_ONLY", "WRITE", "EXTERNAL_READ", "SYSTEM", "EXTERNAL_WRITE", "DESTRUCTIVE")
ORDER = (READ_ONLY, WRITE, EXTERNAL_READ, SYSTEM, EXTERNAL_WRITE, DESTRUCTIVE)
KINDS = ("conversation", "eval", "autonomous")

STATIC: Dict[str, str] = {
    "self_inspect": READ_ONLY, "know": READ_ONLY, "recall": READ_ONLY, "skill_list": READ_ONLY,
    "journal_query": READ_ONLY, "compare_versions": READ_ONLY, "terminate": READ_ONLY, "ask_human": READ_ONLY,
    "remember": WRITE, "forget": WRITE, "learn": WRITE, "present": WRITE, "experiment": WRITE,
    "skill_test": WRITE, "release": WRITE,
    "research": EXTERNAL_READ, "browser_screenshot": EXTERNAL_READ, "browser_exec": EXTERNAL_READ,
    # polymorphic tools: the static entry is their ceiling; classify() refines per call
    "str_replace_editor": WRITE, "skill_create": WRITE, "python_execute": SYSTEM, "desktop": SYSTEM,
}
PREFIX_DEFAULTS: Tuple[Tuple[str, str], ...] = (("browser_", EXTERNAL_READ), ("make_", WRITE))
DEFAULT_UNKNOWN = SYSTEM  # an MCP tool the human configured, a skill nothing declared
DECLARED: Dict[str, str] = {}  # dynamic skills, set by SkillFactory at registration

DESKTOP_READ = {"list_apps", "system_info", "screenshot", "find_files", "clipboard_get"}
EDIT_COMMANDS = {"create", "str_replace", "insert", "undo_edit"}

DESTRUCTIVE_VERBS = re.compile(r"\b(delete|remove|erase|wipe|clear|drop|purge|uninstall|rm|unlink|force[- ]push|reset|discard|overwrite|format|muchh?e|mochh?e|delet)\b", re.I)
SEND_VERBS = re.compile(r"\b(send|email|mail|message|text|post|tweet|publish|pay|buy|order|subscribe|transfer|pathao|pathiye)\b", re.I)
AFFIRMATIVE = re.compile(r"^\s*(y|yes|yeah|yep|ok|okay|sure|do it|go ahead|go|proceed|confirm(ed)?|affirmative|approved|allow(ed)?|ha|haan|hya|kor|koro|thik ache)\b", re.I)
PATH_LITERAL = re.compile(r"""(?:r|rb|b)?['"]([^'"\n]{3,})['"]""")

LEVEL_REASON = {
    READ_ONLY: "observes", WRITE: "changes files or SYRAX's own state", EXTERNAL_READ: "reads from the network",
    SYSTEM: "acts on the host", EXTERNAL_WRITE: "sends messages or money", DESTRUCTIVE: "destroys data",
}


@dataclass
class Decision:
    tool: str
    level: str
    reason: str
    targets: List[str] = field(default_factory=list)
    harm: List[str] = field(default_factory=list)
    scope: str = "any"  # repo | workspace | outside | any (only the editor knows)


@dataclass
class Verdict:
    action: str  # allow | ask | refuse
    authorized_by: Optional[str] = None  # policy | goal | human
    reason: str = ""


def rank(level: str) -> int:
    return ORDER.index(level) if level in ORDER else ORDER.index(DEFAULT_UNKNOWN)


def highest(*levels: str) -> str:
    return max(levels, key=rank)


# ——— classification ———

def level_of_tool(name: str) -> str:
    """The static level of a tool by name (per-call refinement may raise it)."""
    if name in DECLARED:
        return DECLARED[name]
    if name in STATIC:
        return STATIC[name]
    for prefix, level in PREFIX_DEFAULTS:
        if name.startswith(prefix):
            return level
    return DEFAULT_UNKNOWN


def levels_for(names: Iterable[str]) -> Dict[str, str]:
    return {n: level_of_tool(n) for n in sorted(set(names))}


def declare(name: str, level: str) -> None:
    DECLARED[name] = level if level in ORDER else DEFAULT_UNKNOWN


def undeclare(name: str) -> None:
    DECLARED.pop(name, None)


def level_of_source(text: str) -> Tuple[str, str, List[str]]:
    """(level, reason, harm) for a piece of code, worst rung first."""
    text = text or ""
    harm = guard.host_harm(text)
    if harm:
        return DESTRUCTIVE, "; ".join(harm), harm
    for rx, why in guard.DESTRUCTIVE_PATTERNS:
        if rx.search(text):
            return DESTRUCTIVE, why, []
    if guard.NET_SEND[0].search(text):
        return EXTERNAL_WRITE, guard.NET_SEND[1], []
    if guard.SHELL[0].search(text):
        return SYSTEM, guard.SHELL[1], []
    if guard.NET_READ[0].search(text):
        return EXTERNAL_READ, guard.NET_READ[1], []
    if guard.FILE_WRITE.search(text):
        return WRITE, "writes files", []
    return READ_ONLY, "observes", []


def path_literals(code: str) -> List[str]:
    """String literals in code that look like paths or patterns."""
    out: List[str] = []
    for m in PATH_LITERAL.finditer(code or ""):
        s = m.group(1).strip()
        looks = any(ch in s for ch in "/\\~*") or re.search(r"\.[A-Za-z0-9]{1,5}$", s)
        if looks and not s.startswith(("http://", "https://")) and s not in out:
            out.append(s)
    return out


def scope_of(path: Path) -> str:
    try:
        p = path.resolve()
    except OSError:
        p = path
    for base, name in ((REPO_ROOT, "repo"), (WORKSPACE, "workspace")):
        try:
            p.relative_to(base.resolve())
            return "workspace" if name == "workspace" or _under(p, WORKSPACE) else "repo"
        except (ValueError, OSError):
            continue
    return "outside"


def _under(p: Path, base: Path) -> bool:
    try:
        p.relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def classify(name: str, args: Any) -> Decision:
    a = args if isinstance(args, dict) else {}
    if name == "str_replace_editor":
        cmd = str(a.get("command") or "")
        path = str(a.get("path") or "")
        if cmd in EDIT_COMMANDS and path:
            from syrax.editor import resolve_path

            try:
                resolved, _ = resolve_path(path, cmd)
            except Exception:
                resolved = Path(path)
            return Decision(name, WRITE, f"edits {Path(path).name}", [str(resolved)], [], scope_of(resolved))
        return Decision(name, READ_ONLY, "views a file", [path] if path else [])
    if name == "python_execute":
        code = str(a.get("code") or "")
        level, reason, harm = level_of_source(code)
        return Decision(name, level, reason, path_literals(code), harm)
    if name == "skill_create":
        src = f"{a.get('code') or ''}\n{a.get('test_code') or ''}"
        level, reason, harm = level_of_source(src)
        return Decision(name, highest(WRITE, level), reason if rank(level) > rank(WRITE) else "creates a skill", [str(a.get("name") or "")], harm)
    if name == "desktop":
        action = str(a.get("action") or "")
        target = str(a.get("target") or "")
        if action in DESKTOP_READ or (action == "window" and str(a.get("value") or "list") == "list"):
            return Decision(name, READ_ONLY, f"desktop {action}", [target] if target else [])
        return Decision(name, SYSTEM, f"desktop {action or '?'}" + (f" {target}" if target else ""), [target] if target else [])
    level = level_of_tool(name)
    return Decision(name, level, LEVEL_REASON.get(level, level), [])


# ——— the human's words ———

def _norm(p: str) -> str:
    s = os.path.expanduser(str(p).strip().strip("'\""))
    s = os.path.normcase(os.path.normpath(s)).replace("\\", "/")
    return s


def _basename(p: str) -> str:
    return _norm(p).rstrip("/").rsplit("/", 1)[-1]


def named_in(texts: Iterable[str], decision: Decision) -> bool:
    """True when the human's words name the action and every target."""
    text = " ".join(t for t in texts if t)
    if not text.strip():
        return False
    verbs = SEND_VERBS if decision.level == EXTERNAL_WRITE else DESTRUCTIVE_VERBS
    if not verbs.search(text):
        return False
    if not decision.targets:
        return False
    low = text.lower().replace("\\", "/")
    for t in decision.targets:
        n = _norm(t)
        base = _basename(t)
        wildcard = any(ch in t for ch in "*?")
        if n and n in low:
            continue
        if wildcard and t.lower().replace("\\", "/") in low:
            continue
        if len(base) >= 3 and not base.startswith(".") and base.lower() in low:
            continue
        return False
    return True


def affirmative(answer: str) -> bool:
    return bool(AFFIRMATIVE.search(answer or ""))


def signature(decision: Decision) -> str:
    return f"{decision.tool}|{decision.level}|{sorted(_norm(t) for t in decision.targets)}"


def question(decision: Decision) -> str:
    what = ", ".join(decision.targets[:4]) if decision.targets else "a target your request did not name"
    return (f"Permission: `{decision.tool}` would {decision.reason} -> {what}. Your request did not name it. "
            "Answer yes to allow exactly this once; anything else refuses it.")


# ——— policy ———

def decide(decision: Decision, kind: str, goal: str, consents: Iterable[Tuple[str, str]] = (), grants: Optional[Dict[str, bool]] = None) -> Verdict:
    kind = kind if kind in KINDS else "conversation"
    grants = grants or {}
    if decision.harm:
        return Verdict("refuse", None, f"the code {'; '.join(decision.harm)}; SYRAX must not harm the host")
    level = decision.level
    if kind == "autonomous":
        if level in (SYSTEM, EXTERNAL_WRITE, DESTRUCTIVE):
            return Verdict("refuse", None, f"{decision.reason} ({level}) is not done in autonomous work; leave it to the human and state in your final answer exactly what you would have run")
        return Verdict("allow", "policy")
    if level in (READ_ONLY, WRITE, EXTERNAL_READ, SYSTEM):
        return Verdict("allow", "policy")
    # EXTERNAL_WRITE / DESTRUCTIVE: the human's words, a yes already given, or a question
    if named_in([goal], decision):
        return Verdict("allow", "goal", "the request names this action and target")
    said_yes = [q for q, ans in consents if affirmative(ans)]
    if said_yes and named_in(said_yes, decision):
        return Verdict("allow", "human", "the human already answered yes to this")
    sig = signature(decision)
    if sig in grants:
        return Verdict("allow", "human", "granted earlier in this task") if grants[sig] else Verdict("refuse", None, "the human refused this earlier in this task")
    if kind == "eval":
        return Verdict("refuse", None, f"{decision.reason} ({level}) was not named in the request, and a quality run cannot ask")
    return Verdict("ask", None, f"{decision.reason} ({level}) was not named in the request")

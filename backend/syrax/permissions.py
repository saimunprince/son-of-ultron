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
                   or weakens SYRAX's own guard (guard.WEAKENS_GUARD)

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
    "remember": WRITE, "forget": WRITE, "remind": WRITE, "watch_topic": WRITE, "undo": READ_ONLY, "learn": WRITE, "present": WRITE, "experiment": WRITE,
    "skill_test": WRITE, "release": WRITE, "repo_map": READ_ONLY,
    "research": EXTERNAL_READ, "github_search": EXTERNAL_READ, "browser_screenshot": EXTERNAL_READ, "browser_exec": EXTERNAL_READ,
    # polymorphic tools: the static entry is their ceiling; classify() refines per call
    "str_replace_editor": WRITE, "skill_create": WRITE, "python_execute": SYSTEM, "desktop": SYSTEM,
}
PREFIX_DEFAULTS: Tuple[Tuple[str, str], ...] = (("browser_", EXTERNAL_READ), ("make_", WRITE))
DEFAULT_UNKNOWN = SYSTEM  # an MCP tool the human configured, a skill nothing declared
DECLARED: Dict[str, str] = {}  # dynamic skills, set by SkillFactory at registration

DESKTOP_READ = {"list_apps", "system_info", "screenshot", "find_files", "clipboard_get", "find_text"}
EDIT_COMMANDS = {"create", "str_replace", "insert", "undo_edit"}

# Live 2026-10-25 (audit): editor.resolve_path takes any absolute path, so the editor, apply_patch and a
# python_execute path literal could overwrite the files that hold SYRAX's keys and evidence; the
# python_execute guard covers only the code it runs. These are refused at the gate for EVERY task kind:
# only a human changes them, by hand. The owner's settings and memory are closed to SYRAX's own work
# (autonomous, eval) only: in conversation the human may ask for them to be changed.
PROTECTED_DATA = ("backend/config/brains.json", "backend/config/brains.tmp", "backend/config/ws.token",
                  "backend/config/journal.db", "backend/config/journal.db-wal", "backend/config/journal.db-shm",
                  "backend/config/journal.db.key")
OWNER_DATA = ("backend/config/config.toml", "backend/config/memory.json", "backend/config/mcp.json")
# Audit 2026-10-27: the verified snapshots (backup.py) are evidence too: a tool that rewrote a snapshot together
# with its manifest.json made a forged copy that verify() accepted. Nothing under these folders is written through
# a tool, whatever the task; SYRAX's own work (autonomous, eval) does not read them either (they hold a copy of the
# keys and of the whole journal). Only backup.snapshot, run by the core itself, writes there.
PROTECTED_DIRS = ("backend/config/backups/",)

# Stems, so "removal", "deleting", "wiped" count as naming the action too
# (live 2026-10-03: SYRAX asked "confirm the removal of the folder X?", the
# human said yes, and the gate asked again because only "remove" matched).
DESTRUCTIVE_VERBS = re.compile(r"\b(delet\w*|remov\w*|trash\w*|recycl\w*|eras\w*|wip(e|ed|es|ing)|clear\w*|drop\w*|purg\w*|uninstall\w*|rm|unlink\w*|force[- ]push\w*|reset\w*|discard\w*|overwrit\w*|format\w*|muchh?e\w*|mochh?e\w*|felo|fele)\b", re.I)
SEND_VERBS = re.compile(r"\b(send\w*|sent|email\w*|mail\w*|messag\w*|text\w*|post\w*|tweet\w*|publish\w*|pay\w*|paid|buy\w*|bought|order\w*|subscrib\w*|transfer\w*|pathao|pathiye|pathano)\b", re.I)
AFFIRMATIVE = re.compile(r"^\s*(y|yes|yeah|yep|ok|okay|sure|do it|go ahead|go|proceed|confirm(ed)?|affirmative|approved|allow(ed)?|ha|haan|hya|kor|koro|thik ache)\b", re.I)
PATH_LITERAL = re.compile(r"""(?:r|rb|b)?['"]([^'"\n]{3,})['"]""")

# Review 2026-10-27: a message sent through the desktop (SYRAX types into Telegram or WhatsApp and presses Enter) was
# SYSTEM, like any keystroke: no gate asked for the send, the intent ledger never held a repeat, and the true "Message
# sent" after one read as an unbacked claim. Live 2026-10-25 (task cb8cc6cf3028): an invented "hello" was typed, Enter
# went into the wrong window, and the answer was "Message sent". A desktop action that submits text (Enter or
# ctrl+Enter; shift+Enter is a new line; a typed newline; a click on a Send button) while a messaging app is in front
# is an EXTERNAL_WRITE: a send. Typing alone sends nothing and stays SYSTEM. The front window is read when the call
# is classified (front_window); when it cannot be read the call stays SYSTEM, as before.
# (app, how its window or program shows it in desktop.front_window's "'Title' (Program.exe)", how the human names it;
# None where the name is an everyday word: Signal, LINE, Messages, Teams are known by their window only)
MESSAGING_APPS: Tuple[Tuple[str, "re.Pattern[str]", Optional["re.Pattern[str]"]], ...] = tuple(
    (app, re.compile(window, re.I), re.compile(words, re.I) if words else None) for app, window, words in (
        ("Telegram", r"\btelegram\b", r"\btelegram\b"),
        ("WhatsApp", r"\bwhatsapp\b", r"\bwhats ?app\b"),
        ("Messenger", r"\bmessenger\b", r"\bmessenger\b"),
        ("Discord", r"\bdiscord\b", r"\bdiscord\b"),
        ("Slack", r"\bslack\b", r"\bslack\b"),
        ("Microsoft Teams", r"\bmicrosoft teams\b|\(ms-teams\.exe\)|\(teams\.exe\)", r"\b(?:microsoft|ms) teams\b"),
        ("Skype", r"\bskype\b", r"\bskype\b"),
        ("Viber", r"\bviber\b", r"\bviber\b"),
        ("WeChat", r"\bwechat\b|\bweixin\b", r"\bwechat\b"),
        ("Instagram", r"\binstagram\b", r"\binsta(?:gram)?\b"),
        ("Signal", r"^'signal'|\(signal\.exe\)", None),
        ("LINE", r"^'line'|\(line\.exe\)", None),
        ("Messages", r"\bmessages for web\b|\bmessages\.google\.com\b", None),
    ))
# a send named in the human's own words, beside SEND_VERBS: "reply ok on whatsapp", "msg bro bhi"
REPLY_VERBS = re.compile(r"\b(repl(?:y|ies|ied|ying)|respond\w*|msg\w*|dm)\b", re.I)
SEND_BUTTON = re.compile(r"\bsend\b", re.I)


def messaging_app(window: str) -> Optional[str]:
    """The messaging app a front window ("'Title' (Program.exe)") belongs to; None for any other window."""
    w = str(window or "").strip()
    return next((app for app, rx, _ in MESSAGING_APPS if rx.search(w)), None)


def submits_text(args: Any) -> bool:
    """A desktop call that submits what is typed in a chat: a key press with Enter (shift+Enter is a new line in a
    chat), typed text with a newline in it (wininput.type_text presses Enter for one), a click on a Send button.
    The value is stripped first, as the desktop tool strips it."""
    a = args if isinstance(args, dict) else {}
    action = str(a.get("action") or "")
    value = str(a.get("value") or "").strip()
    if action == "hotkey":
        keys = {k.strip().lower() for k in value.replace(" ", "").split("+") if k.strip()}
        return bool(keys & {"enter", "return"}) and "shift" not in keys
    if action == "type_text":
        return "\n" in value or "\r" in value
    if action == "click_text":
        return bool(SEND_BUTTON.search(str(a.get("target") or "")))
    return False


def front_window() -> Optional[str]:
    """desktop.front_window(): "'Title' (Program.exe)", "" when nothing is in front, None when unreadable (and off
    Windows). Tests replace this function; any error reads as None, which keeps the call SYSTEM."""
    try:
        from syrax import desktop

        return desktop.front_window()
    except Exception:
        return None

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


def autonomous_refuses(name: str) -> bool:
    """A skill whose declared level autonomous work may never use: every call
    of it from SYRAX's own work is refused by design, so its own work can
    neither verify nor repair it (live 2026-10-12: screen_brightness and
    wallpaper drew verify, retry and repair objectives that could only be
    refused). Built-in tools are refined per call and are not judged here."""
    return DECLARED.get(name) in (SYSTEM, EXTERNAL_WRITE, DESTRUCTIVE)


def declare(name: str, level: str) -> None:
    DECLARED[name] = level if level in ORDER else DEFAULT_UNKNOWN


def undeclare(name: str) -> None:
    DECLARED.pop(name, None)


def level_of_source(text: str) -> Tuple[str, str, List[str]]:
    """(level, reason, harm) for a piece of code, worst rung first."""
    text = text or ""
    harm = guard.host_harm(text) + guard.weakens_guard(text)  # the guard's own modules count as the host (audit 2026-10-25)
    harm += guard.controls_self(text)  # the core's own interface counts as the host too (audit 2026-10-27)
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


# Live 2026-10-25 (audit): path_literals() sees only a literal that looks like a path, so a computed path reached
# the tool with no protected target: Path(__file__).parent / "quality.py", os.path.join(root, "backend", "syrax",
# "guard.py"), f"{d}/journal.db", "qual" + "ity.py". The basenames of the protected files are known, so any
# literal that ends in one is read as that file. A determined program can still compute a path at runtime
# ("".join(parts), a name read from a file): this gate is the first of three walls; the runtime guard
# (guard.py, a child cannot write the journal, the keys or the live tree) and the release gate
# (devloop.judge_problems) are the other two.
_JOINED = re.compile(r"""["']\s*(?:\+\s*)?["']""")  # `"qual" + "ity.py"` and `"qual" "ity.py"`, read as one literal
_PROTECTED_RX: Dict[Tuple[str, ...], "re.Pattern[str]"] = {}


def protected_basenames() -> Dict[str, str]:
    """{basename: repository path} of every protected file: the judges (devloop.JUDGES), the key and
    evidence files (PROTECTED_DATA) and the owner's files (OWNER_DATA)."""
    from syrax.devloop import JUDGES  # devloop does not import permissions

    return {p.rsplit("/", 1)[-1].lower(): p for p in (*JUDGES, *PROTECTED_DATA, *OWNER_DATA)}


def _protected_rx(names: Dict[str, str]) -> "re.Pattern[str]":
    key = tuple(sorted(names))
    rx = _PROTECTED_RX.get(key)
    if rx is None:
        alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        rx = _PROTECTED_RX[key] = re.compile(rf"""["']([^'"\n]*[/\\])?({alts})["']""", re.I)
    return rx


def _protected_place(literal: str, names: Dict[str, str]) -> Optional[str]:
    """The repository path a literal ending in a protected basename stands for; None when it names another place."""
    known = names[literal.replace("\\", "/").rsplit("/", 1)[-1].lower()]
    if "/" not in literal and "\\" not in literal:
        return known  # a bare basename: the piece a join or a Path chain ends with
    rel = repo_relative(os.path.normpath(os.path.expanduser(literal)).replace("\\", "/"))
    if rel is None:
        return None  # an absolute path outside the repository (C:/tmp/quality.py)
    rel = rel.lower()
    if rel == known:
        return known
    head = rel.split("/", 1)[0]
    if (REPO_ROOT / head).is_dir():
        return None  # a definite other place in the repository (backend/workspace/tools.py)
    if (BACKEND_ROOT / head).is_dir():
        return known if f"backend/{rel}" == known else None  # relative to backend/ (syrax/quality.py, config/brains.json)
    return known  # a prefix the gate cannot place ({d}/, ../, root/): the protected file is what it may be


def protected_literals(code: str) -> List[str]:
    """Repository paths of the protected files that code names by basename (see the note above _JOINED)."""
    names = protected_basenames()
    text = code or ""
    out: List[str] = []
    for source in (text, _JOINED.sub("", text)):
        for m in _protected_rx(names).finditer(source):
            rel = _protected_place((m.group(1) or "") + m.group(2), names)
            if rel and rel not in out:
                out.append(rel)
    return out


def code_targets(code: str) -> List[str]:
    """What a piece of code may touch: its path-looking literals, then the protected files it names by basename."""
    out = path_literals(code)
    return out + [t for t in protected_literals(code) if t not in out]


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
            # a Windows drive path (C:/Users/...) on Linux/macOS names a place outside this machine's workspace,
            # though the editor would make it a folder named "C:" there (2026-10-28)
            scope = "outside" if os.sep == "/" and _DRIVE.match(path.strip().strip("'\"")) else scope_of(resolved)
            return Decision(name, WRITE, f"edits {Path(path).name}", [str(resolved)], [], scope)
        return Decision(name, READ_ONLY, "views a file", [path] if path else [])
    if name == "apply_patch":  # Phase 3: a unified diff; its paths are the targets, so the protected set is checked per file
        from syrax.selfedit import diff_paths, normalize_headers, work_root

        root = work_root()
        paths = diff_paths(normalize_headers(str(a.get("diff") or "").replace("\r\n", "\n")))
        return Decision(name, WRITE, f"patches {', '.join(Path(x).name for x in paths[:3]) or '?'}", [str(root / x) for x in paths], [], "repo")
    if name == "python_execute":
        code = str(a.get("code") or "")
        level, reason, harm = level_of_source(code)
        return Decision(name, level, reason, code_targets(code), harm)
    if name == "skill_test" and str(a.get("action") or "test").lower() == "remove":
        # Live 2026-10-29 14:24: an autonomous task asked to improve flight_search removed it instead (skill_test was
        # an ordinary WRITE). DISABLED sticks until the human turns it back on, and the boot record then said "disabled
        # by the human". Taking a capability away is destructive: own work never does it, a human request names it
        # or is asked first.
        skill = str(a.get("name") or "")
        return Decision(name, DESTRUCTIVE, f"removes the skill {skill or '?'}", [skill] if skill else [])
    if name == "skill_create":
        src = f"{a.get('code') or ''}\n{a.get('test_code') or ''}"
        level, reason, harm = level_of_source(src)
        # a skill whose source writes (its own level, before the WRITE floor) and names a protected file is held to it
        targets = [str(a.get("name") or "")] + (protected_literals(src) if rank(level) > rank(READ_ONLY) else [])
        return Decision(name, highest(WRITE, level), reason if rank(level) > rank(WRITE) else "creates a skill", targets, harm)
    if name == "desktop":
        action = str(a.get("action") or "")
        target = str(a.get("target") or "")
        if action == "trash":  # recoverable, but it still takes a file away from the human
            return Decision(name, DESTRUCTIVE, f"moves {Path(target).name or '?'} to the Recycle Bin", [target] if target else [])
        if action not in DESKTOP_READ and (harm := guard.controls_self(_strings(a))):  # desktop open of the HUD (audit 2026-10-27)
            return Decision(name, SYSTEM, f"desktop {action or '?'}" + (f" {target}" if target else ""), [target] if target else [], harm)
        if action in DESKTOP_READ or (action == "window" and str(a.get("value") or "list") == "list"):
            return Decision(name, READ_ONLY, f"desktop {action}", [target] if target else [])
        if submits_text(a) and (front := front_window()) and (app := messaging_app(front)):
            return Decision(name, EXTERNAL_WRITE, f"sends a message in {app}", [front])  # see MESSAGING_APPS
        return Decision(name, SYSTEM, f"desktop {action or '?'}" + (f" {target}" if target else ""), [target] if target else [])
    level = level_of_tool(name)
    # Live 2026-10-27 (audit): a browser call carries no targets, so a page on the core's own origin (the HUD) or
    # the UI's, which the core trusts in full, opened like any web page; every string it passes is read for them
    harm = guard.controls_self(_strings(a)) if name.startswith("browser_") else []
    return Decision(name, level, LEVEL_REASON.get(level, level), [], harm)


def _strings(value: Any) -> str:
    """Every string in a tool call's arguments (a URL, code, a nested list), one per line."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_strings(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return "\n".join(_strings(v) for v in value)
    return ""


# ——— the human's words ———

_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _norm(p: str) -> str:
    s = os.path.expanduser(str(p).strip().strip("'\""))
    s = os.path.normcase(os.path.normpath(s)).replace("\\", "/")
    return s.lower() if _DRIVE.match(s) else s  # a Windows drive path is case-blind on every host


def _basename(p: str) -> str:
    return _norm(p).rstrip("/").rsplit("/", 1)[-1]


def named_in(texts: Iterable[str], decision: Decision) -> bool:
    """True when the human's words name the action and every target."""
    text = " ".join(t for t in texts if t)
    if not text.strip():
        return False
    if decision.tool == "desktop" and decision.level == EXTERNAL_WRITE:
        return _names_desktop_send(text, decision)
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


def _names_desktop_send(text: str, decision: Decision) -> bool:
    """A send through the desktop (classify, MESSAGING_APPS) is named when the words ask for a send ("send message to
    bro bhi", "reply ok on whatsapp"). The chat is not checked (most messaging windows do not show it in the title);
    the app is: words that name messaging apps, none of them the one in front, do not cover a send in it."""
    if not (SEND_VERBS.search(text) or REPLY_VERBS.search(text)):
        return False
    front = messaging_app(decision.targets[0]) if decision.targets else None
    named = {app for app, _, words in MESSAGING_APPS if words is not None and words.search(text)}
    return not named or front in named


def affirmative(answer: str) -> bool:
    return bool(AFFIRMATIVE.search(answer or ""))


def signature(decision: Decision) -> str:
    return f"{decision.tool}|{decision.level}|{sorted(_norm(t) for t in decision.targets)}"


# Reversibility of one call (EVOLUTION_PLAN wave 1, directions 142 worst case, 143 reversibility): journaled with every
# permission decision and said in every question, so neither the human nor the record has to guess what a yes risks.
REVERSIBLE, ROLLBACK, UNTRACKED, IRREVERSIBLE = "REVERSIBLE", "ROLLBACK", "UNTRACKED", "IRREVERSIBLE"
UNDO_TOOLS = ("str_replace_editor", "apply_patch")  # the editor's undo history, the repository's rollback (undo.py, devloop)


def reversibility(decision: Decision) -> tuple:
    """(label, how): REVERSIBLE (changes nothing), ROLLBACK (an undo or a rollback restores it), UNTRACKED (it changes
    something no undo records), IRREVERSIBLE (what it sends or removes cannot be taken back)."""
    if decision.level in (READ_ONLY, EXTERNAL_READ):
        return REVERSIBLE, "it changes nothing"
    if decision.tool == "desktop" and "Recycle Bin" in decision.reason:
        return ROLLBACK, "the file can be restored from the Recycle Bin"
    if decision.tool == "skill_test":
        return ROLLBACK, "skill_enable turns the skill back on"
    if decision.level == EXTERNAL_WRITE:
        return IRREVERSIBLE, "a message, post or payment that went out cannot be called back"
    if decision.level == DESTRUCTIVE:
        return IRREVERSIBLE, "what it removes is gone"
    if decision.tool in UNDO_TOOLS or decision.scope == "repo":
        return ROLLBACK, "the editor's undo or the repository's rollback restores it"
    return UNTRACKED, "it changes something no undo records"


def question(decision: Decision) -> str:
    what = ", ".join(decision.targets[:4]) if decision.targets else "a target your request did not name"
    label, how = reversibility(decision)
    risk = f" This cannot be undone: {how}." if label == IRREVERSIBLE else (f" No undo records it: {how}." if label == UNTRACKED else "")
    return (f"Permission: `{decision.tool}` would {decision.reason} -> {what}. Your request did not name it.{risk} "
            "Answer yes to allow exactly this once; anything else refuses it.")


# ——— policy ———

def with_real(targets: Iterable[str]) -> List[str]:
    """Each target and, for an absolute one, where it really leads (symlinks resolved). Audit 2026-10-28: a link
    in the workspace to backend/config/brains.json passed every check made on the link's own name, and open()
    followed it. Every protected-target check now also judges the real path."""
    out: List[str] = []
    for t in targets:
        s = str(t or "").strip()
        out.append(t)
        if s and os.path.isabs(s):
            try:
                real = os.path.realpath(s)
            except (OSError, ValueError):
                continue
            if os.path.normcase(real) != os.path.normcase(os.path.normpath(s)):
                out.append(real)
    return out


def repo_relative(target: str) -> Optional[str]:
    """A target as a repository path (backend/syrax/x.py), also when it is inside a
    task's worktree, which mirrors the repository; None when it is elsewhere."""
    p = guard.canonical_path(str(target or "").strip()).replace("\\", "/")  # \\?\C:\..., \\localhost\C$\... (review 2026-10-27)
    # the LAST worktree segment: a path inside a worktree of a worktree (SYRAX's own gate runs in
    # .syrax/worktrees/<task>, and so does anything it touches there) maps to the repository path.
    # Live 2026-10-14: with the first segment, three of SYRAX's own releases were rolled back by
    # test_protected_set, which builds such a path when the suite runs inside a task's worktree.
    m = re.search(r"^.*/\.syrax/(?:worktrees|maintenance)/[^/]+/(.+)$", p)
    if m:
        return m.group(1)
    root = BACKEND_ROOT.parent.as_posix().rstrip("/")
    if p.lower().startswith(root.lower() + "/"):
        return p[len(root) + 1:]
    return None if (os.path.isabs(p) or re.match(r"^[A-Za-z]:", p)) else p.lstrip("./") or None


def protected_targets(targets: Iterable[str]) -> List[str]:
    """Targets in the protected set: the files that judge SYRAX (devloop.JUDGES)."""
    from syrax.devloop import JUDGES  # devloop does not import permissions

    return sorted({rel for t in with_real(targets) if (rel := repo_relative(t)) in JUDGES})


# The edit tools whose targets are the files they change (classify resolves them to absolute paths); a path in
# python_execute's code is a literal it may or may not write, so only the release judges those.
EDIT_TOOLS = ("str_replace_editor", "apply_patch")


def unreleasable(targets: Iterable[str]) -> List[str]:
    """What a release would refuse about these edit targets (devloop.edit_problems), each judged in the tree it is
    in: a task's worktree (the last .syrax/worktrees/<task> segment, as repo_relative reads it) or the repository."""
    from syrax.devloop import edit_problems  # devloop does not import permissions

    problems: List[str] = []
    for t in with_real(targets):
        rel = repo_relative(t)
        if not rel:
            continue
        m = re.search(r"^(.*/\.syrax/(?:worktrees|maintenance)/[^/]+)/.+$", str(t).replace("\\", "/"))
        problems += edit_problems(rel, Path(m.group(1)) if m else REPO_ROOT)
    return problems


def git_targets(targets: Iterable[str]) -> List[str]:
    """Targets that are, or are inside, a `.git` file or directory (followed through symlinks)."""
    hits = []
    for t in with_real(targets):
        parts = str(t or "").replace("\\", "/").split("/")
        if ".git" in parts and str(t) not in hits:
            hits.append(str(t))
    return hits


def data_targets(targets: Iterable[str], files: Tuple[str, ...]) -> List[str]:
    """Targets among ``files`` (PROTECTED_DATA / OWNER_DATA, repository paths), matched on the
    normalized path: absolute under the repository root or repository-relative, either slash,
    any case, `..` folded (live 2026-10-25, audit)."""
    hits = set()
    for t in with_real(targets):
        s = str(t or "").strip()
        if not s:
            continue
        rel = repo_relative(os.path.normpath(s))
        if rel and (rel := rel.replace("\\", "/").lower()) in files:
            hits.add(rel)
    return sorted(hits)


def dir_targets(targets: Iterable[str], dirs: Tuple[str, ...] = PROTECTED_DIRS) -> List[str]:
    """Targets inside one of ``dirs`` (repository folders ending in "/", PROTECTED_DIRS) or naming the
    folder itself, normalized like data_targets (audit 2026-10-27: the backups)."""
    hits = set()
    for t in with_real(targets):
        s = str(t or "").strip()
        if not s:
            continue
        rel = repo_relative(os.path.normpath(s))
        if not rel:
            continue
        rel = rel.replace("\\", "/").lower()
        for d in dirs:
            if rel == d.rstrip("/") or rel.startswith(d):
                hits.add(rel)
    return sorted(hits)


def network_targets(targets: Iterable[str], admin_only: bool = False) -> List[str]:
    """Targets that are still network or device paths once guard.canonical_path has turned this machine's own
    spellings into drive paths: any \\\\host\\share (or only administrative shares, \\\\host\\C$, with ``admin_only``)."""
    hits = []
    for t in targets:
        s = guard.canonical_path(str(t or "").strip())
        if guard.ADMIN_SHARE.match(s) or (not admin_only and re.match(r"^[\\/]{2}", s)):
            hits.append(str(t))
    return hits


# ——— autonomy levels (mission 2026-10-28, built 2026-10-29) ———
# The operator chooses how far SYRAX's own work may go; the level lives in the journal (autonomy_level), which own code
# cannot write, and the core sets OWN_LEVEL from it when each task starts. Unset means 5: what SYRAX did before levels.
LEVEL_NAMES = {1: "observe and research", 2: "experiment", 3: "modify and verify", 4: "integrate", 5: "continuous"}
OWN_LEVEL: int = 5
L1_WRITES = ("learn",)  # research findings stored as knowledge: the point of level 1
CODE_TOOLS = ("python_execute", "experiment", "skill_test", "compare_versions")


def level_needed(decision: "Decision") -> int:
    """The lowest autonomy level at which SYRAX's own work may make this call. Running code is never observation:
    python_execute's static reading of the code ("observes") can be fooled, so it is level 2 whatever it reads as."""
    if decision.tool in CODE_TOOLS:
        return 2
    if decision.level in (READ_ONLY, EXTERNAL_READ) or decision.tool in L1_WRITES:
        return 1
    if decision.tool == "release":
        return 4
    if decision.tool in EDIT_TOOLS and decision.scope != "workspace":
        return 3
    return 2


def decide(decision: Decision, kind: str, goal: str, consents: Iterable[Tuple[str, str]] = (), grants: Optional[Dict[str, bool]] = None) -> Verdict:
    kind = kind if kind in KINDS else "conversation"
    grants = grants or {}
    if decision.harm:
        why = f"the code {'; '.join(decision.harm)}"
        if any(h not in (guard.WEAKENS_GUARD_WHY, guard.SELF_CONTROL_WHY) for h in decision.harm):
            why += "; SYRAX must not harm the host"
        return Verdict("refuse", None, why)
    if kind == "autonomous" and (need := level_needed(decision)) > OWN_LEVEL:
        return Verdict("refuse", None, f"the operator set autonomy level {OWN_LEVEL} ({LEVEL_NAMES.get(OWN_LEVEL, '?')}); "
                       f"{decision.tool} needs level {need} ({LEVEL_NAMES[need]}). Do what this level allows, or report "
                       "what a higher level would let you do: only the operator raises it")
    level = decision.level
    if level != READ_ONLY and (unc := network_targets(decision.targets, admin_only=kind == "conversation")):
        # Review 2026-10-27: \\?\, \\.\ and \\localhost\C$\ spellings of the repository passed every check below
        return Verdict("refuse", None, f"{', '.join(unc[:3])}: a network or device path; "
                       + ("an administrative share is a whole drive, never a target" if kind == "conversation"
                          else "SYRAX's own work writes only through plain local paths"))
    if level != READ_ONLY and (held := data_targets(decision.targets, PROTECTED_DATA)):
        # Live 2026-10-25 (audit): the keys and the evidence are nobody's to write through a tool, whatever the task
        return Verdict("refuse", None, f"{', '.join(held)}: this file holds SYRAX's keys/evidence; only a human changes it by hand")
    if level != READ_ONLY and (sealed := dir_targets(decision.targets)):
        # Audit 2026-10-27: a snapshot rewritten together with its manifest verified; the backups are evidence
        return Verdict("refuse", None, f"{', '.join(sealed)}: the backups hold verified copies of SYRAX's evidence and keys; "
                       "only backup.snapshot writes there, and only a human restores or removes a snapshot")
    if kind in ("autonomous", "eval") and (sealed := dir_targets(decision.targets)):
        return Verdict("refuse", None, f"{', '.join(sealed)}: the backups hold a copy of SYRAX's keys and evidence; "
                       "SYRAX's own work neither reads nor writes them")
    if kind in ("autonomous", "eval") and level != READ_ONLY and (owned := data_targets(decision.targets, OWNER_DATA)):
        return Verdict("refuse", None, f"{', '.join(owned)}: this file holds the owner's settings; SYRAX's own work never changes it, leave it to the human")
    if kind in ("autonomous", "eval") and decision.tool == "forget":
        # Live 2026-10-25 (audit): forget is an ordinary WRITE, so SYRAX's own work could delete the human's memories
        return Verdict("refuse", None, "the human's memory is deleted only on the human's word")
    if kind == "eval" and decision.tool == "release":
        # live 2026-10-14 (quality run #39, self_patch_stale): an eval task rewrote README's title and called
        # release; the gate ran four minutes before the case's timeout stopped it. A measurement never commits.
        return Verdict("refuse", None, "a quality case measures SYRAX; it never releases a change")
    if kind in ("autonomous", "eval") and level != READ_ONLY and (gits := git_targets(decision.targets)):
        # audit 2026-10-28: a hook or config written into .git ran inside the server's next git command
        return Verdict("refuse", None, f"{', '.join(gits[:3])}: git's own files (hooks, config, the worktree link); "
                       "SYRAX's own work never writes them")
    if kind in ("autonomous", "eval") and level != READ_ONLY and (judged := protected_targets(decision.targets)):
        # the protected set: own work may read the judges, never write them (the release would refuse it anyway)
        return Verdict("refuse", None, f"{', '.join(judged)}: this file judges SYRAX's own work; only a human changes it")
    if kind == "autonomous" and level == WRITE and decision.tool in EDIT_TOOLS and (bad := unreleasable(decision.targets)):
        # Phase 4, know before changing: the release's own rules (devloop.edit_problems), at the first edit, not after it
        return Verdict("refuse", None, "; ".join(bad) + ". A release would refuse this change, so it is refused before the "
                       "edit: change files a release accepts, or name what the human should change in your final answer")
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

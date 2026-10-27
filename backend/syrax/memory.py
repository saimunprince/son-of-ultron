"""SYRAX long-term memory.

Two stores in backend/config (gitignored, mode 0600):
- memory.json   : lasting facts about the human (name, likes, projects, rules)
- history.jsonl : the last completed exchanges, so a restart does not wipe context

Both are injected into the system prompt at the start of every task, and the
agent manages facts itself with the remember / recall / forget tools.

Inspection, correction and export (2026-10-25): `MemoryStore.facts()` carries each fact's provenance (type, confidence,
basis, created, last_used, uses) for the memory panel; `correct` lets the human rewrite one fact in place (journaled
as `knowledge.updated` with `previous`); `export` writes config/exports/memory-<stamp>.json (gitignored), also reachable
as `python -m syrax.memory --export [path]`.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from pydantic import Field

from app.config import PROJECT_ROOT
from app.tool.base import BaseTool

MEMORY_FILE = Path(os.getenv("SYRAX_MEMORY_FILE", PROJECT_ROOT / "config" / "memory.json"))
HISTORY_FILE = Path(os.getenv("SYRAX_HISTORY_FILE", PROJECT_ROOT / "config" / "history.jsonl"))
MAX_FACTS = 300
PROMPT_FACTS = 60
PROMPT_EXCHANGES = 6
MAX_HISTORY = 200

_SECRET = re.compile(
    r"(password|passwd|api[_ -]?key|secret|token|otp|pin code|credit card|cvv|\bsk-[A-Za-z0-9]|\bgsk_|\bAIza)",
    re.I,
)


# Typed memory (2026-10-14): what the human SAID is kept apart from what SYRAX INFERRED, so an
# inference never speaks with the weight of the human's own words. Stored as a `type:<t>` tag on the
# knowledge row (no schema change); rows from before carry no tag and read as facts.
TYPES = ("fact", "preference", "rule", "observation")
_PREFERENCE = re.compile(r"\b(prefers?|likes?|loves?|hates?|dislikes?|enjoys?|favou?rite|wants?|would rather|rather than)\b", re.I)
_RULE = re.compile(r"(^|\b)(always|never|don't|do not|must|should|only)\b.*\b(you|syrax|me|reply|answer|ask|use)\b|\b(call me|address me|speak to me)\b", re.I)


def infer_type(text: str) -> str:
    """fact | preference | rule, from the wording; an observation is never inferred (SYRAX says so itself)."""
    if _RULE.search(text):
        return "rule"
    if _PREFERENCE.search(text):
        return "preference"
    return "fact"


# Memory provenance (2026-10-27 audit: the eval case `remember_fact` wrote "The human's favourite editor is Vim" into the
# owner's memory, re-written 12 times, and nothing told it from the owner's word). `remember` records where a row came
# from: the task_id column and, for any task that is not a human conversation, an "origin:<task kind>" tag. Rows of a
# HIDDEN_ORIGINS kind are stored and exported with their origin, but never reach the owner's view (`facts()`, the
# prompt block, the memory panel, `recall` in a conversation); only a task of that same kind recalls them. Rows
# without an origin tag (the human's conversations, and every row older than this) stay as they are. Autonomous work
# is tagged too, but stays visible: it has no human words, so `remember` files it as a labelled observation anyway.
HIDDEN_ORIGINS = ("eval",)  # a quality case is a test fixture, never the owner speaking
OWNER_ORIGIN = "conversation"


def origin_of(tags) -> Optional[str]:
    """The task kind that wrote a memory row ("origin:<kind>" tag), None for the owner's own (no tag)."""
    for t in tags or []:
        if str(t).startswith("origin:") and len(str(t)) > 7:
            return str(t)[7:]
    return None


def type_of(tags) -> str:
    for t in tags or []:
        if str(t).startswith("type:") and str(t)[5:] in TYPES:
            return str(t)[5:]
    return "fact"


def _words(text: str) -> set:
    return {w for w in re.findall(r"[\w']+", text.lower()) if len(w) > 2}


def _overlap(a: set, b: set) -> float:
    """Jaccard overlap of two word sets, 0..1 (the dedupe threshold is 0.8)."""
    return len(a & b) / max(1, len(a | b))


def _subject(text: str) -> Optional[tuple]:
    m = re.match(r"(.+?)\s+(?:is|are|was|were)\s+", text, re.I)
    if not m:
        return None
    return tuple(sorted(_words(m.group(1)))) or None


# Memory truth (2026-10-25 audit): `remember` is called by the model, so its text may be the model's own inference
# dressed as the human's words. The tool knows what the human said this task (said_provider, wired by the agent);
# only text grounded in those words is stored as a fact, anything else becomes an observation at half the weight.
GROUNDING = 0.6  # share of the fact's content words that must appear in the human's words
_STOP = {"the", "and", "that", "this", "with", "for", "from", "are", "was", "were", "has", "have", "had", "not", "but",
         "they", "them", "their", "you", "your", "his", "her", "its", "about", "into", "also", "very", "than", "then"}
_EXPLICIT = re.compile(r"\b(remember|memori[sz]e|note that|keep in mind|don'?t forget|do not forget)\b", re.I)
INFERRED_BASIS = "SYRAX inferred from the conversation (remember tool): the human never said this"
OBSERVED_BASIS = "SYRAX observed (remember tool, type observation): an inference, not the human's words"
# `forget` by words: the needle must be a whole word or phrase of at least FORGET_MIN_CHARS (test_memory.test_tools
# forgets "tea", so three letters is the floor), and more than FORGET_MAX_UNNAMED rows go only when the human named them.
FORGET_MIN_CHARS = 3
FORGET_MAX_UNNAMED = 5
_SWEEP = re.compile(r"\b(everything|all)\b", re.I)
_NARROWED = re.compile(r"\b(everything|all)\s+(about|on|regarding|concerning)\b", re.I)


class ForgetRefused(ValueError):
    """`forget` turned the call down; str(e) says why (needle too short, or too many rows for words the human never said)."""


class CorrectRefused(ValueError):
    """`correct` turned the call down; str(e) says why (empty or secret-looking text, or no remembered fact with that id)."""


CORRECTED_BASIS = "human corrected (UI)"


def export_dir() -> Path:
    """backend/config/exports (gitignored), or SYRAX_EXPORT_DIR; read at call time so a test can point it elsewhere."""
    return Path(os.getenv("SYRAX_EXPORT_DIR") or PROJECT_ROOT / "config" / "exports")


def _redacted(obj):
    """`obj` with every string leaf run through agent.py's CREDENTIAL mask (imported lazily: agent.py imports this module).
    Dicts, lists and scalars keep their shape, so the exported JSON stays valid."""
    from syrax.agent import CREDENTIAL

    def walk(x):
        if isinstance(x, str):
            return CREDENTIAL.sub("[credential masked]", x)
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v) for v in x]
        return x

    return walk(obj)


def _normal(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", str(text or "").lower()))


def content_words(text: str) -> set:
    return _words(text) - _STOP


def grounded(text: str, said: str) -> bool:
    """True when `text` is in the human's own words: a normalized substring of what they said, or at least GROUNDING of
    its content words appear there."""
    t, s = _normal(text), _normal(said)
    if not t or not s:
        return False
    if t in s:
        return True
    mine = content_words(text)
    return bool(mine) and len(mine & _words(said)) / len(mine) >= GROUNDING


def names(needle: str, said: str) -> bool:
    """True when the human asked for the sweep `forget` was called with: "forget everything about Vim" names the
    rows matching "Vim"; "forget everything" (not narrowed by "about ...") names the whole memory. "forget vim"
    alone names one memory, not six."""
    said, raw = str(said or ""), str(needle or "").strip().lower()
    if not raw or not _SWEEP.search(said):
        return False
    if raw in {"everything", "all", "*"}:
        return not _NARROWED.search(said)
    q, qw = _normal(raw), _words(raw)
    return bool(q) and (q in _normal(said) or bool(qw and qw <= _words(said)))


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


class MemoryStore:
    def __init__(self, memory_file: Path = MEMORY_FILE, history_file: Path = HISTORY_FILE):
        self.memory_file = memory_file
        self.history_file = history_file
        self._lock = threading.Lock()

    # ——— facts (journal-backed; memory.json is migrated once, then left alone) ———
    def _journal(self):
        from syrax.journal import get_journal

        return get_journal()

    def _file_facts(self) -> List[dict]:
        try:
            data = json.loads(self.memory_file.read_text(encoding="utf-8"))
            return [f for f in data.get("facts", []) if isinstance(f, dict) and f.get("text")]
        except Exception:
            return []

    def _migrate(self) -> int:
        """Import legacy memory.json facts into the journal exactly once."""
        j = self._journal()
        if j.get_meta(f"facts_migrated:{self.memory_file}") == "1":
            return 0
        n = 0
        if not j.human_facts(limit=1):
            for f in self._file_facts():
                try:
                    j.add_knowledge_sync(f["text"], "human", tags=["memory"], basis="migrated from memory.json (human said)")
                    n += 1
                except Exception:
                    continue
        j.set_meta(f"facts_migrated:{self.memory_file}", "1")
        return n

    @staticmethod
    def _as_fact(k: dict) -> dict:
        # provenance for the memory panel and the export: how the row came to be, how sure, how often it was used
        return {"id": str(k["id"]), "text": k["claim"], "created": k["created"], "updated": k.get("last_used"),
                "type": type_of(k.get("tags")), "confidence": k.get("confidence"), "basis": k.get("basis"),
                "last_used": k.get("last_used"), "uses": k.get("uses", 0),
                "origin": origin_of(k.get("tags")), "task_id": k.get("task_id")}

    def facts(self, origin: Optional[str] = None, everything: bool = False) -> List[dict]:
        """The owner's memory: rows written by a HIDDEN_ORIGINS task (an eval) are left out, unless `origin` is that
        kind (the eval recalls its own rows too) or `everything` (forget)."""
        try:
            self._migrate()
            rows = [self._as_fact(k) for k in self._journal().human_facts(MAX_FACTS)]
        except Exception:
            return [{"id": f.get("id", "?"), "text": f["text"], "created": f.get("created")} for f in self._file_facts()]
        if everything:
            return rows
        return [f for f in rows if f.get("origin") not in HIDDEN_ORIGINS or f.get("origin") == origin]

    def remember(self, text: str, kind: Optional[str] = None, said: Optional[str] = None,
                 origin: Optional[str] = None, task_id: Optional[str] = None) -> str:
        """Store `text`. `said` is what the human said this task (None: unknown, the caller vouches for the text):
        a fact, preference or rule that is not grounded in it is stored as an observation (confidence 0.5, basis
        INFERRED_BASIS), never as the human's own word; "remember that ..." from the human keeps it a fact.
        `origin` is the kind of the task that calls (None or "conversation": the owner), `task_id` its id; a row from
        any other kind is tagged "origin:<kind>", and a HIDDEN_ORIGINS row only ever updates rows of its own origin."""
        text = " ".join(str(text or "").split())[:400]
        if not text:
            return "Nothing to remember."
        if _SECRET.search(text):
            return "Refused: that looks like a secret (password/key/token). Secrets are never stored."
        kind = kind if kind in TYPES else infer_type(text)
        inferred = False
        if said is not None and kind != "observation" and not (_EXPLICIT.search(said) or grounded(text, said)):
            kind, inferred = "observation", True
        new = _words(text)
        origin = origin if origin and origin != OWNER_ORIGIN else None
        hidden = origin in HIDDEN_ORIGINS
        tags = ["memory", f"type:{kind}"] + sorted(new)[:6] + ([f"origin:{origin}"] if origin else [])
        if kind == "observation":  # SYRAX's own inference: half the weight of the human's word, and labelled so
            conf, basis = 0.5, (INFERRED_BASIS if inferred else OBSERVED_BASIS)
        else:
            conf, basis = 1.0, "human said (remember tool)"
        if origin:
            basis = f"{basis}; {origin} task {task_id or '?'}"
        with self._lock:
            j = self._journal()
            self._migrate()
            if task_id and j.task(task_id) is None:  # the column is a task reference: an unknown id stays in the basis only
                task_id = None
            # an eval's rows dedupe among themselves: a test fixture never rewrites the owner's memory
            candidates = [f for f in self.facts(origin) if f.get("origin") == origin] if hidden else self.facts()
            for f in candidates:
                old = _words(f["text"])
                subj_new = _subject(text)
                subj_old = _subject(f["text"])
                same_subject = subj_new is not None and subj_new == subj_old and text != f["text"]
                if not same_subject and not (old and new and _overlap(old, new) > 0.8):
                    continue
                if f.get("type") != "observation" and kind == "observation":
                    return f"Kept what the human said: {f['text']} (an observation never overwrites it)"
                # the new row takes the new type and confidence: a human fact over an observation is a fact at 1.0
                j.update_knowledge_claim_sync(int(f["id"]), text, task_id=task_id, confidence=conf, tags=tags, basis=basis)
                was = f" (was an observation, now a {kind} at {conf:.1f})" if f.get("type") == "observation" and kind != "observation" else ""
                return (f"Updated memory: {f['text']} -> {text}{was}" if same_subject else f"Updated memory: {text}{was}")
            j.add_knowledge_sync(text, "human", tags=tags, confidence=conf, basis=basis, task_id=task_id)
        aside = f" (kept with the {origin} task, out of the owner's memory)" if hidden else ""
        if inferred:
            return (f"Stored as an observation, not a fact: the human never said this, SYRAX inferred it from the "
                    f"conversation (confidence 0.5). {text}{aside}")
        return f"Remembered ({kind}): {text}{aside}"

    def recall(self, query: str = "", limit: int = 15, origin: Optional[str] = None) -> List[dict]:
        facts = self.facts(origin)
        q = _words(query)
        if not q:
            return facts[-limit:]
        scored = [(len(q & _words(f["text"])), i, f) for i, f in enumerate(facts)]
        return [f for s, _, f in sorted(scored, key=lambda x: (-x[0], -x[1])) if s > 0][:limit]

    def forget(self, query: str, said: Optional[str] = None, origin: Optional[str] = None) -> List[str]:
        """Delete the memories `query` names (a fact id, 'everything', or words matched as whole words). Raises
        ForgetRefused for a needle under FORGET_MIN_CHARS, and when more than FORGET_MAX_UNNAMED rows would go unless
        the human's words (`said`; None = unknown, the caller vouches) name them. A HIDDEN_ORIGINS task (`origin`)
        forgets only its own rows, never the owner's."""
        q = str(query or "").strip().lower()
        if not q:
            return []
        everything = q in {"everything", "all", "*"}
        if not everything and not q.isdigit() and len(q) < FORGET_MIN_CHARS:
            raise ForgetRefused(f"Refused: {query!r} is too short a needle ({FORGET_MIN_CHARS} characters at least): "
                                "it would match too much. Name the memory, or use its id from `recall`.")
        with self._lock:
            facts = self.facts()
            if origin in HIDDEN_ORIGINS:
                facts = [f for f in self.facts(origin) if f.get("origin") == origin]
            if everything:
                hits = facts
            else:
                qw = _words(q)
                whole = re.compile(r"(?<![\w'])" + re.escape(q) + r"(?![\w'])")
                hits = [f for f in facts if f["id"] == q or (qw and qw <= _words(f["text"])) or bool(whole.search(f["text"].lower()))]
            if not hits:
                return []
            if len(hits) > FORGET_MAX_UNNAMED and said is not None and not names(q, said):
                raise ForgetRefused(f"Refused: {len(hits)} memories match {query!r}, more than {FORGET_MAX_UNNAMED}. Forget them one "
                                    f"at a time, or only when the human says 'forget everything about {query}'.")
            gone = self._journal().forget_knowledge_sync([int(f["id"]) for f in hits if str(f["id"]).isdigit()])
            return [g["claim"] for g in gone]

    # ——— inspection: correction and export (2026-10-25) ———
    def correct(self, fact_id, text: str) -> dict:
        """The human rewrites one remembered fact in place (memory panel EDIT). The row keeps its id and type, takes
        the new text at confidence 1.0 with basis CORRECTED_BASIS, and `knowledge.updated` journals `previous` (what
        it replaced). Raises CorrectRefused for an empty or secret-looking text, and for an id that is no remembered
        fact (unknown, or a knowledge row of another kind). Returns the refreshed fact."""
        text = " ".join(str(text or "").split())[:400]
        if not text:
            raise CorrectRefused("Refused: a corrected memory needs some text (use FORGET to drop it).")
        if _SECRET.search(text):
            raise CorrectRefused("Refused: that looks like a secret (password/key/token). Secrets are never stored.")
        fid = str(fact_id or "").strip()
        with self._lock:
            j = self._journal()
            self._migrate()
            row = j.knowledge(int(fid)) if fid.isdigit() else None
            if row is None or row.get("kind") != "human":
                raise CorrectRefused(f"Refused: no remembered fact {fid!r}.")
            kind = type_of(row.get("tags"))
            tags = ["memory", f"type:{kind}"] + sorted(_words(text))[:6]
            updated = j.update_knowledge_claim_sync(int(fid), text, confidence=1.0, tags=tags, basis=CORRECTED_BASIS)
        return self._as_fact(updated)

    def export(self, path=None) -> dict:
        """Write every remembered fact (with its provenance) and the conclusion/web knowledge rows with their sources
        to one JSON document, atomically (`_atomic_write`), at `path` or `export_dir()/memory-<YYYYMMDD-HHMMSS>.json`
        (backend/config/exports, gitignored). Returns {path, count, knowledge, exported}.

        Secrets: `remember` already refuses secret-looking text, and the whole document still goes through agent.py's
        CREDENTIAL mask (`_redacted`), so a key that slipped into a conclusion, an excerpt or a URL leaves the file as
        "[credential masked]"."""
        from syrax.journal import _git_head

        with self._lock:
            j = self._journal()
            self._migrate()
            facts = []
            for k in j.human_facts(1000):
                f = self._as_fact(k)
                if k.get("source_url"):
                    f["source_url"] = k["source_url"]
                facts.append(f)
            knowledge = [{"id": k["id"], "kind": k["kind"], "text": k["claim"], "confidence": k["confidence"],
                          "basis": k["basis"], "sources": k["sources"], "source_url": k.get("source_url"),
                          "source_title": k.get("source_title"), "question": k.get("question"), "tags": k["tags"],
                          "created": k["created"], "last_used": k.get("last_used"), "uses": k.get("uses", 0)}
                         for k in j.knowledge_of_kind(("conclusion", "web"))]
            now = time.time()
            doc = _redacted({
                "exported": datetime.fromtimestamp(now, timezone.utc).isoformat(timespec="seconds"), "exported_ts": now,
                "git_head": _git_head(j.repo_root), "count": len(facts), "facts": facts,
                "knowledge_count": len(knowledge), "knowledge": knowledge,
            })
            out = Path(path) if path else export_dir() / time.strftime("memory-%Y%m%d-%H%M%S.json", time.localtime(now))
            _atomic_write(out, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
        return {"path": str(out), "count": len(facts), "knowledge": len(knowledge), "exported": doc["exported"]}

    # ——— conversation history ———
    def add_exchange(self, user: str, reply: str) -> None:
        user, reply = (user or "").strip(), (reply or "").strip()
        if not user or not reply:
            return
        line = json.dumps({"ts": time.time(), "user": user[:600], "reply": reply[:600]}, ensure_ascii=False)
        with self._lock:
            lines = self._history_lines()
            lines.append(line)
            _atomic_write(self.history_file, "\n".join(lines[-MAX_HISTORY:]) + "\n")

    def _history_lines(self) -> List[str]:
        try:
            return [ln for ln in self.history_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except FileNotFoundError:
            return []

    def recent(self, n: int = PROMPT_EXCHANGES) -> List[dict]:
        """Recent conversations from the durable journal (single source of truth);
        the legacy history.jsonl is only read when the journal has none yet."""
        try:
            from syrax.journal import get_journal

            rows = get_journal().recent_exchanges(n)
        except Exception:
            rows = []
        if rows:
            return rows
        out = []
        for ln in self._history_lines()[-n:]:
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out

    def clear_history(self) -> None:
        with self._lock:
            _atomic_write(self.history_file, "")

    # ——— prompt block ———
    def prompt_block(self) -> str:
        facts = self.facts()[-PROMPT_FACTS:]
        now = time.time()
        thirty_days_ago = now - 30 * 86400
        filtered_facts = []
        for f in facts:
            if f.get("type") == "observation":
                eff = f.get("updated") if f.get("updated") is not None else f.get("created")
                if eff is not None and eff < thirty_days_ago:
                    continue
            filtered_facts.append(f)
        facts = filtered_facts
        recent = self.recent()
        parts = []
        if facts:
            groups = [("rule", "Rules the human set for you"), ("preference", "What the human prefers"),
                      ("fact", "What the human told you"), ("observation", "What you observed yourself (inference; the human never said it, it may be wrong)")]
            lines = []
            for t, title in groups:
                mine = [f for f in facts if f.get("type", "fact") == t]
                if mine:
                    lines.append(f"{title}:\n" + "\n".join(f"- {f['text']}" for f in mine))
            parts.append("LONG-TERM MEMORY (from earlier sessions):\n" + "\n".join(lines))
        if recent:
            parts.append(
                "RECENT CONVERSATIONS (previous sessions, oldest first):\n"
                + "\n".join(f"- Human: {r['user'][:200]}\n  SYRAX: {r['reply'][:200]}" for r in recent)
            )
        parts.append(
            "MEMORY RULES: When the human shares a lasting fact about themselves (name, preferences, "
            "projects, people, routines, how they want you to behave), call `remember` with one short "
            "sentence. Something you noticed but they never said is an `observation` (type observation): "
            "it is kept apart and never overrides their words; `remember` keeps only what the human actually "
            "said as a fact and files the rest as observations itself. Use `recall` to search older facts, "
            "`forget` when asked. Never store passwords, keys, tokens or other secrets."
        )
        return "\n\n".join(parts)


_store: Optional[MemoryStore] = None


def get_memory() -> MemoryStore:
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store


class RememberTool(BaseTool):
    name: str = "remember"
    description: str = ("Store one lasting fact about the human in long-term memory. type: fact (what they told you), "
                        "preference (what they like), rule (how they want you to behave), or observation (something you "
                        "noticed that they never said: kept apart, half the weight). Leave type out to infer it from the wording.")
    parameters: dict = {
        "type": "object",
        "properties": {
            "fact": {"type": "string", "description": "One short sentence, e.g. 'Prince prefers dark themes.'"},
            "type": {"type": "string", "enum": list(TYPES), "description": "fact | preference | rule | observation"},
        },
        "required": ["fact"],
    }
    store: Optional[MemoryStore] = Field(default=None, exclude=True)
    # what the human said this task (the agent wires it); None = unknown, and the text is taken at its word
    said_provider: Optional[Callable[[], Optional[str]]] = Field(default=None, exclude=True)
    # memory provenance: (task kind, task_id) of the task that calls (the agent wires it); None = the owner's own
    origin_provider: Optional[Callable[[], Tuple[Optional[str], Optional[str]]]] = Field(default=None, exclude=True)

    async def execute(self, fact: str, type: Optional[str] = None) -> str:  # noqa: A002 - the tool's parameter name
        said = self.said_provider() if self.said_provider else None
        store = self.store or get_memory()
        if self.origin_provider is None:
            return store.remember(fact, type, said=said)
        origin, task_id = self.origin_provider()
        return store.remember(fact, type, said=said, origin=origin, task_id=task_id)


class RecallTool(BaseTool):
    name: str = "recall"
    description: str = "Search long-term memory for facts about the human."
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Keywords; empty for the latest facts."}},
        "required": [],
    }
    store: Optional[MemoryStore] = Field(default=None, exclude=True)
    origin_provider: Optional[Callable[[], Tuple[Optional[str], Optional[str]]]] = Field(default=None, exclude=True)

    async def execute(self, query: str = "") -> str:
        store = self.store or get_memory()
        if self.origin_provider is None:
            hits = store.recall(query)
        else:  # an eval recalls what it remembered itself; any other task sees the owner's memory only
            hits = store.recall(query, origin=self.origin_provider()[0])
        return "\n".join(f"[{f['id']}] ({f.get('type', 'fact')}) {f['text']}" for f in hits) or "No matching memories."


class ForgetTool(BaseTool):
    name: str = "forget"
    description: str = "Delete memories matching the query (or 'everything'). Only when the human asks."
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Words or fact id to forget, or 'everything'."}},
        "required": ["query"],
    }
    store: Optional[MemoryStore] = Field(default=None, exclude=True)
    said_provider: Optional[Callable[[], Optional[str]]] = Field(default=None, exclude=True)
    origin_provider: Optional[Callable[[], Tuple[Optional[str], Optional[str]]]] = Field(default=None, exclude=True)

    async def execute(self, query: str) -> str:
        said = self.said_provider() if self.said_provider else None
        try:
            store = self.store or get_memory()
            if self.origin_provider is None:
                removed = store.forget(query, said=said)
            else:
                removed = store.forget(query, said=said, origin=self.origin_provider()[0])
        except ForgetRefused as e:
            return str(e)
        if not removed:
            return "Nothing matched."
        return f"Forgot {len(removed)} {'memory' if len(removed) == 1 else 'memories'} matching {query!r}:\n" + "\n".join(f"- {t}" for t in removed)


def main(argv: Optional[List[str]] = None) -> int:
    """`python -m syrax.memory --export [path]`: write the memory export (see MemoryStore.export) and print its path."""
    import argparse

    p = argparse.ArgumentParser(prog="python -m syrax.memory", description="SYRAX long-term memory")
    p.add_argument("--export", nargs="?", const="", metavar="PATH",
                   help="write memory-<stamp>.json with every fact and the conclusion/web knowledge (default: config/exports/)")
    a = p.parse_args(argv)
    if a.export is None:
        p.print_help()
        return 2
    out = get_memory().export(a.export or None)
    print(f"{out['path']} ({out['count']} facts, {out['knowledge']} knowledge rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""SYRAX long-term memory.

Two stores in backend/config (gitignored, mode 0600):
- memory.json   : lasting facts about the human (name, likes, projects, rules)
- history.jsonl : the last completed exchanges, so a restart does not wipe context

Both are injected into the system prompt at the start of every task, and the
agent manages facts itself with the remember / recall / forget tools.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional

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


def type_of(tags) -> str:
    for t in tags or []:
        if str(t).startswith("type:") and str(t)[5:] in TYPES:
            return str(t)[5:]
    return "fact"


def _words(text: str) -> set:
    return {w for w in re.findall(r"[\w']+", text.lower()) if len(w) > 2}


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(data)
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
        return {"id": str(k["id"]), "text": k["claim"], "created": k["created"], "updated": k.get("last_used"),
                "type": type_of(k.get("tags")), "confidence": k.get("confidence")}

    def facts(self) -> List[dict]:
        try:
            self._migrate()
            return [self._as_fact(k) for k in self._journal().human_facts(MAX_FACTS)]
        except Exception:
            return [{"id": f.get("id", "?"), "text": f["text"], "created": f.get("created")} for f in self._file_facts()]

    def remember(self, text: str, kind: Optional[str] = None) -> str:
        text = " ".join(str(text or "").split())[:400]
        if not text:
            return "Nothing to remember."
        if _SECRET.search(text):
            return "Refused: that looks like a secret (password/key/token). Secrets are never stored."
        kind = kind if kind in TYPES else infer_type(text)
        with self._lock:
            j = self._journal()
            self._migrate()
            new = _words(text)
            for f in self.facts():
                old = _words(f["text"])
                if old and new and len(old & new) / max(1, len(old | new)) > 0.8:
                    if f.get("type") != "observation" and kind == "observation":
                        return f"Kept what the human said: {f['text']} (an observation never overwrites it)"
                    j.update_knowledge_claim_sync(int(f["id"]), text)
                    return f"Updated memory: {text}"
            if kind == "observation":  # SYRAX's own inference: half the weight of the human's word, and labelled so
                j.add_knowledge_sync(text, "human", tags=["memory", "type:observation"] + sorted(new)[:6], confidence=0.5,
                                     basis="SYRAX observed (remember tool, type observation): an inference, not the human's words")
            else:
                j.add_knowledge_sync(text, "human", tags=["memory", f"type:{kind}"] + sorted(new)[:6], basis="human said (remember tool)")
        return f"Remembered ({kind}): {text}"

    def recall(self, query: str = "", limit: int = 15) -> List[dict]:
        facts = self.facts()
        q = _words(query)
        if not q:
            return facts[-limit:]
        scored = [(len(q & _words(f["text"])), i, f) for i, f in enumerate(facts)]
        return [f for s, _, f in sorted(scored, key=lambda x: (-x[0], -x[1])) if s > 0][:limit]

    def forget(self, query: str) -> List[str]:
        q = str(query or "").strip().lower()
        with self._lock:
            facts = self.facts()
            if q in {"everything", "all", "*"}:
                hits = facts
            else:
                qw = _words(q)
                hits = [f for f in facts if f["id"] == q or (qw and qw <= _words(f["text"])) or (q and q in f["text"].lower())]
            if not hits:
                return []
            gone = self._journal().forget_knowledge_sync([int(f["id"]) for f in hits if str(f["id"]).isdigit()])
            return [g["claim"] for g in gone]

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
            "it is kept apart and never overrides their words. Use `recall` to search older facts, "
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

    async def execute(self, fact: str, type: Optional[str] = None) -> str:  # noqa: A002 - the tool's parameter name
        return (self.store or get_memory()).remember(fact, type)


class RecallTool(BaseTool):
    name: str = "recall"
    description: str = "Search long-term memory for facts about the human."
    parameters: dict = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Keywords; empty for the latest facts."}},
        "required": [],
    }
    store: Optional[MemoryStore] = Field(default=None, exclude=True)

    async def execute(self, query: str = "") -> str:
        hits = (self.store or get_memory()).recall(query)
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

    async def execute(self, query: str) -> str:
        removed = (self.store or get_memory()).forget(query)
        return ("Forgot:\n" + "\n".join(f"- {t}" for t in removed)) if removed else "Nothing matched."

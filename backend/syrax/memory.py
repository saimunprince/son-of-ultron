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

    # ——— facts ———
    def facts(self) -> List[dict]:
        try:
            data = json.loads(self.memory_file.read_text())
            return [f for f in data.get("facts", []) if isinstance(f, dict) and f.get("text")]
        except FileNotFoundError:
            return []
        except Exception:
            return []

    def _save(self, facts: List[dict]) -> None:
        _atomic_write(self.memory_file, json.dumps({"facts": facts[-MAX_FACTS:]}, indent=2, ensure_ascii=False))

    def remember(self, text: str) -> str:
        text = " ".join(str(text or "").split())[:400]
        if not text:
            return "Nothing to remember."
        if _SECRET.search(text):
            return "Refused: that looks like a secret (password/key/token). Secrets are never stored."
        with self._lock:
            facts = self.facts()
            new = _words(text)
            for f in facts:
                old = _words(f["text"])
                if old and new and len(old & new) / max(1, len(old | new)) > 0.8:
                    f["text"], f["updated"] = text, time.time()
                    self._save(facts)
                    return f"Updated memory: {text}"
            facts.append({"id": uuid.uuid4().hex[:8], "text": text, "created": time.time()})
            self._save(facts)
        return f"Remembered: {text}"

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
                removed = [f["text"] for f in facts]
                self._save([])
                return removed
            qw = _words(q)
            keep, removed = [], []
            for f in facts:
                hit = f.get("id") == q or (qw and qw <= _words(f["text"])) or (q and q in f["text"].lower())
                (removed if hit else keep).append(f)
            if removed:
                self._save(keep)
            return [f["text"] for f in removed]

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
            return [ln for ln in self.history_file.read_text().splitlines() if ln.strip()]
        except FileNotFoundError:
            return []

    def recent(self, n: int = PROMPT_EXCHANGES) -> List[dict]:
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
            parts.append("LONG-TERM MEMORY (facts about the human, from earlier sessions):\n" + "\n".join(f"- {f['text']}" for f in facts))
        if recent:
            parts.append(
                "RECENT CONVERSATIONS (previous sessions, oldest first):\n"
                + "\n".join(f"- Human: {r['user'][:200]}\n  SYRAX: {r['reply'][:200]}" for r in recent)
            )
        parts.append(
            "MEMORY RULES: When the human shares a lasting fact about themselves (name, preferences, "
            "projects, people, routines, how they want you to behave), call `remember` with one short "
            "sentence. Use `recall` to search older facts, `forget` when asked. Never store passwords, "
            "keys, tokens or other secrets."
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
    description: str = "Store one lasting fact about the human (preference, name, project, rule) in long-term memory."
    parameters: dict = {
        "type": "object",
        "properties": {"fact": {"type": "string", "description": "One short sentence, e.g. 'Prince prefers dark themes.'"}},
        "required": ["fact"],
    }
    store: Optional[MemoryStore] = Field(default=None, exclude=True)

    async def execute(self, fact: str) -> str:
        return (self.store or get_memory()).remember(fact)


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
        return "\n".join(f"[{f['id']}] {f['text']}" for f in hits) or "No matching memories."


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

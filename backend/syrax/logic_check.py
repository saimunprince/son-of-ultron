"""logic_check: decide whether premises entail a conclusion, by truth table (propositional logic).

EVOLUTION_PLAN directions 1 (formal reasoning) and 2 (deductive reasoning): a brain's deduction was taken on its word.
This tool checks it exactly: the formulas use names, not / ! / ~, and / &, or / |, -> (implies), <-> (iff), true,
false and parentheses; with up to MAX_VARS names every assignment is tried. Entailed means no assignment makes every
premise true and the conclusion false; otherwise the counterexample is given. Without a conclusion, the premises are
checked for consistency (some assignment makes them all true). Pure code: no brain, no network, no files."""

from __future__ import annotations

import itertools
import re
from typing import Any, Dict, List, Optional

from app.tool.base import BaseTool, ToolResult

MAX_VARS = 12
_TOKEN = re.compile(r"\s*(<->|->|\(|\)|!|~|&|\||[A-Za-z_][A-Za-z0-9_]*)")
_WORDS = {"not": "!", "and": "&", "or": "|", "implies": "->", "iff": "<->"}


def tokens(text: str) -> List[str]:
    out, pos, text = [], 0, text.strip()
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise ValueError(f"cannot read {text[pos:pos + 12]!r}")
        t = m.group(1)
        out.append(_WORDS.get(t.lower(), t))
        pos = m.end()
    return out


class _Parser:
    """iff < implies (right) < or < and < not < atom."""

    def __init__(self, toks: List[str]) -> None:
        self.t, self.i = toks, 0

    def peek(self) -> Optional[str]:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, want: Optional[str] = None) -> str:
        tok = self.peek()
        if tok is None or (want is not None and tok != want):
            raise ValueError(f"expected {want or 'more'} at token {self.i + 1}")
        self.i += 1
        return tok

    def parse(self):
        node = self.iff()
        if self.peek() is not None:
            raise ValueError(f"unexpected {self.peek()!r}")
        return node

    def iff(self):
        left = self.implies()
        while self.peek() == "<->":
            self.take()
            left = ("<->", left, self.implies())
        return left

    def implies(self):
        left = self.disj()
        if self.peek() == "->":
            self.take()
            return ("->", left, self.implies())
        return left

    def disj(self):
        left = self.conj()
        while self.peek() == "|":
            self.take()
            left = ("|", left, self.conj())
        return left

    def conj(self):
        left = self.neg()
        while self.peek() == "&":
            self.take()
            left = ("&", left, self.neg())
        return left

    def neg(self):
        if self.peek() in ("!", "~"):
            self.take()
            return ("!", self.neg())
        if self.peek() == "(":
            self.take("(")
            node = self.iff()
            self.take(")")
            return node
        name = self.take()
        if name in ("->", "<->", "|", "&", ")"):
            raise ValueError(f"unexpected {name!r}")
        low = name.lower()
        return ("const", True) if low == "true" else ("const", False) if low == "false" else ("var", name)


def parse(text: str):
    return _Parser(tokens(text)).parse()


def names(node) -> set:
    if node[0] == "var":
        return {node[1]}
    if node[0] == "const":
        return set()
    return set().union(*(names(n) for n in node[1:]))


def value(node, env: Dict[str, bool]) -> bool:
    op = node[0]
    if op == "var":
        return env[node[1]]
    if op == "const":
        return node[1]
    if op == "!":
        return not value(node[1], env)
    a, b = value(node[1], env), value(node[2], env)
    return {"&": a and b, "|": a or b, "->": (not a) or b, "<->": a == b}[op]


def check(premises: List[str], conclusion: str = "") -> dict:
    """{"result": "ENTAILED" | "NOT ENTAILED" | "CONSISTENT" | "INCONSISTENT", "counterexample"/"model": {...}, "vars"}."""
    ps = [parse(p) for p in premises if str(p).strip()]
    c = parse(conclusion) if str(conclusion or "").strip() else None
    vs = sorted(set().union(*(names(n) for n in ps + ([c] if c else []))) if ps or c else set())
    if len(vs) > MAX_VARS:
        raise ValueError(f"{len(vs)} names: at most {MAX_VARS}")
    for bits in itertools.product((False, True), repeat=len(vs)):
        env = dict(zip(vs, bits))
        if all(value(p, env) for p in ps):
            if c is None:
                return {"result": "CONSISTENT", "model": env, "vars": vs}
            if not value(c, env):
                return {"result": "NOT ENTAILED", "counterexample": env, "vars": vs}
    return {"result": "INCONSISTENT" if c is None else "ENTAILED", "vars": vs}


class LogicCheckTool(BaseTool):
    name: str = "logic_check"
    description: str = (
        "Check a deduction exactly (propositional logic, truth table): do the premises entail the conclusion? Formulas "
        "use names and not, and, or, -> (implies), <-> (iff), parentheses, e.g. premises ['rain -> wet', 'rain'], "
        "conclusion 'wet'. Gives the counterexample when it does not follow; without a conclusion it checks the "
        "premises are consistent. Use it before stating that something follows."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "premises": {"type": "array", "items": {"type": "string"}, "description": "The premises, one formula each."},
            "conclusion": {"type": "string", "description": "The claimed conclusion; leave out to check consistency."},
        },
        "required": ["premises"],
    }

    async def execute(self, premises: Any = None, conclusion: str = "", **_: Any) -> ToolResult:
        try:
            r = check([str(p) for p in (premises or [])], conclusion or "")
        except (ValueError, KeyError) as e:
            return ToolResult(error=f"logic_check: {e}")
        if r["result"] == "NOT ENTAILED":
            cx = ", ".join(f"{k}={'T' if v else 'F'}" for k, v in r["counterexample"].items())
            return ToolResult(output=f"NOT ENTAILED: with {cx} every premise is true and the conclusion is false.")
        if r["result"] == "CONSISTENT":
            m = ", ".join(f"{k}={'T' if v else 'F'}" for k, v in r["model"].items())
            return ToolResult(output=f"CONSISTENT: all premises hold with {m}.")
        return ToolResult(output=f"{r['result']} (checked all {2 ** len(r['vars'])} assignments of {', '.join(r['vars']) or 'no names'}).")

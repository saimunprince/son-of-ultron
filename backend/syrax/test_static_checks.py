"""EVOLUTION_PLAN wave 4 (direction 107 static analysis): the release gate ran tests but no static checks, so a pattern
known to cause silent bugs or injection could land unseen. Stdlib only (no new dependency): every module SYRAX runs is
parsed, and the gate fails on a bare `except:` (it swallows KeyboardInterrupt and CancelledError, which the E-STOP and
cancels rely on), a mutable default argument (state shared across calls), `shell=True` or `os.system` (a shell parses
the command, so text from a page or a brain could inject one). All four were absent on 2026-10-30; this keeps it so."""

import ast
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCES = [p for p in sorted(HERE.glob("*.py")) + sorted((HERE.parent / "prebuilt").glob("*/skill.py"))
           if not p.name.startswith("test_") and p.name != "conftest.py"]


def findings(tree: ast.AST, name: str) -> list:
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler) and n.type is None:
            out.append(f"{name}:{n.lineno} bare except")
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.args.defaults + [d for d in n.args.kw_defaults if d is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    out.append(f"{name}:{n.lineno} mutable default in {n.name}()")
        if isinstance(n, ast.Call):
            if any(k.arg == "shell" and isinstance(k.value, ast.Constant) and k.value.value is True for k in n.keywords):
                out.append(f"{name}:{n.lineno} shell=True")
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "system" and isinstance(f.value, ast.Name) and f.value.id == "os":
                out.append(f"{name}:{n.lineno} os.system")
    return out


def test_the_sources_are_free_of_the_checked_patterns():
    assert len(SOURCES) > 50  # the scan sees SYRAX's modules, not an empty folder
    found = [x for p in SOURCES for x in findings(ast.parse(p.read_text(encoding="utf-8")), p.name)]
    assert not found, found


def test_each_pattern_is_caught():
    code = ("import os, subprocess\n"
            "def f(x=[]):\n    try:\n        os.system('ls')\n    except:\n        pass\n"
            "subprocess.run('ls', shell=True)\n")
    got = " ".join(findings(ast.parse(code), "x.py"))
    for what in ("bare except", "mutable default in f()", "shell=True", "os.system"):
        assert what in got, (what, got)

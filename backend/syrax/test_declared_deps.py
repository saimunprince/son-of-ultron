"""EVOLUTION_PLAN wave 1 (directions 109 dependency management, 110 reproducible builds, 258 supply chain): on
2026-10-28 the Linux release gate was BLOCKED because syrax imported psutil, which no requirements file declared (it
had come in transitively on Windows). Every third-party module SYRAX's own code imports at module level must belong to
a distribution that backend/requirements*.txt declares, directly or as the -r file it includes."""

import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
LOCAL = {"syrax", "app", "skills", "prebuilt"}


def declared() -> set:
    names, todo, seen = set(), [BACKEND / "requirements-syrax.txt"], set()
    while todo:
        f = todo.pop()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("-r"):
                todo.append(f.parent / line[2:].strip())
            elif line:
                names.add(re.split(r"[<>=!~\[; ]", line, 1)[0].lower().replace("_", "-"))
    return names


def module_level_imports(path: Path) -> set:
    """Top-level names imported outside any function, class or try block (a guarded import is optional)."""
    out = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.add(node.module.split(".")[0])
    return out


def undeclared(want: set) -> tuple:
    """(missing {module (owners): [files]}, the third-party modules seen) for a set of declared distributions."""
    dists = packages_distributions()
    missing, seen = {}, set()
    for f in sorted(HERE.glob("*.py")):
        if f.name.startswith("test_") or f.name == "conftest.py":
            continue
        for mod in module_level_imports(f):
            if mod in sys.stdlib_module_names or mod in LOCAL or mod.startswith("_"):
                continue
            seen.add(mod)
            owners = {d.lower().replace("_", "-") for d in dists.get(mod, [])}
            if not owners:
                missing.setdefault(f"{mod} (not installed)", []).append(f.name)
            elif not owners & want:
                missing.setdefault(f"{mod} ({', '.join(sorted(owners))})", []).append(f.name)
    return missing, seen


def test_every_third_party_import_is_declared():
    missing, seen = undeclared(declared())
    assert {"fastapi", "pydantic", "httpx"} <= seen  # the scan sees real imports: an empty pass proves nothing
    assert not missing, f"imported but not declared in requirements: {missing}"


def test_a_dependency_left_out_of_the_requirements_is_caught():
    missing, _ = undeclared(declared() - {"httpx"})
    assert any(k.startswith("httpx") for k in missing)

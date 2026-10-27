"""Audit 2026-10-27, open item 3 ("judges depend on unprotected code"): the rules that catch SYRAX's own false claims
lived in agent.py, which SYRAX may edit and release itself. They live in claims.py, a judge (devloop.JUDGES): an
autonomous release that changes them is refused like any other judge, and agent.py keeps only the flow, reading the
very same rule objects (every name still imports from syrax.agent)."""

import ast
import asyncio
from pathlib import Path

import pytest

from syrax import agent, claims, permissions
from syrax.devloop import JUDGES, DevLoop, judge_problems
from syrax.journal import Journal
from syrax.test_devloop import PASS, git, repo

HERE = Path(__file__).resolve().parent
CLAIMS = "backend/syrax/claims.py"


def _top_level_names(path: Path) -> set:
    names = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            for t in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                if isinstance(t, ast.Name):
                    names.add(t.id)
    return names


MOVED = _top_level_names(HERE / "claims.py")


def test_claims_is_a_judge():
    assert CLAIMS in JUDGES
    assert any("judges SYRAX's own work" in p for p in judge_problems({CLAIMS: "M"}))
    assert permissions.protected_basenames()["claims.py"] == CLAIMS


def test_the_rules_moved_and_agent_reads_the_same_objects():
    for name in ("CLAIM", "WORLD_CLAIM", "CHANGE_ASKED", "OWN_WORK_CLAIM", "TEST_CLAIM", "REFUSAL_ACK", "OUTCOME_CLAIMS",
                 "SEND_CLAIM", "DESKTOP_CLAIM", "BROWSER_CLAIM", "PLAYING_CLAIM", "PLAYING_READ", "BOAST", "STATUS_CLAIM",
                 "STATUS_ASK", "DISPUTE", "UNPROVEN_SOFT", "CLAIM_ASK", "CLAIM_FALLBACK", "OUTCOME_NUDGE", "OUTCOME_NOTE",
                 "WORLD_NUDGE", "TEST_CLAIM_ASK", "TEST_FALLBACK", "REFUSAL_ASK", "FORM_ASK", "GIVEN_PATCH_REFUSED",
                 "exact_form", "meets_form", "given_patch", "diff_changed_lines", "state_of_tests", "classes_of",
                 "changes_something", "is_dispute", "is_reading", "status_reading"):
        assert name in MOVED, name
    defined_in_agent = _top_level_names(HERE / "agent.py")
    assert not MOVED & defined_in_agent, sorted(MOVED & defined_in_agent)
    for name in MOVED:
        if hasattr(agent, name):
            assert getattr(agent, name) is getattr(claims, name), name
    public = {n for n in MOVED if not n.startswith("_")}
    assert all(hasattr(agent, n) for n in public), sorted(n for n in public if not hasattr(agent, n))


def test_claims_never_imports_the_agent():
    tree = ast.parse((HERE / "claims.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "syrax.agent" and not (node.module == "syrax" and any(a.name == "agent" for a in node.names))
        elif isinstance(node, ast.Import):
            assert all(a.name != "syrax.agent" for a in node.names)


def test_an_autonomous_release_that_changes_the_claim_rules_is_refused(tmp_path):
    """Mirrors test_devloop's judge refusal for quality.py: an own release of claims.py is refused, a normal change
    with a new test lands, and a conversation's edit stays in the tree for the human to commit."""
    root = repo(tmp_path)
    rules = root / "backend" / "syrax" / "claims.py"
    rules.write_text("UNPROVEN_SOFT = frozenset({'not_released'})\n")
    git(root, "add", "-A"); git(root, "commit", "-q", "-m", "claim rules")
    j = Journal(tmp_path / "j.db")
    auto = j.start_task_sync("make the claim checks less strict", kind="autonomous")
    dl = DevLoop(j, root=root, gates=lambda: PASS, task_id_provider=lambda: auto, snapshot_dir=tmp_path / "rb")
    rules.write_text("UNPROVEN_SOFT = frozenset({'not_released', 'change', 'tests'})\n")
    with pytest.raises(ValueError, match="judges SYRAX's own work"):
        asyncio.run(dl.release("soften the verdict"))
    git(root, "checkout", "--", ".")
    (root / "backend" / "syrax" / "mod.py").write_text("VALUE = 3\n")
    (root / "backend" / "syrax" / "test_new.py").write_text("def test_n(): assert True\n")
    assert asyncio.run(dl.release("fix behaviour, add a test", {"why": "objective evidence", "risk": "callers of mod",
                                                                 "tests": "test_new.py"}))["outcome"] == "COMMITTED"
    human = j.start_task_sync("human asks to change a claim rule", kind="conversation")
    dl.task_id_provider = lambda: human
    dl.begin_task()
    rules.write_text("UNPROVEN_SOFT = frozenset()\n")
    with pytest.raises(ValueError, match="judges SYRAX's own work"):
        asyncio.run(dl.release("human-approved rule change"))
    assert rules.read_text() == "UNPROVEN_SOFT = frozenset()\n"  # the human's edit stays for the human to commit


def test_own_work_is_refused_writing_the_claim_rules_at_the_call():
    path = str(permissions.BACKEND_ROOT / "syrax" / "claims.py")
    d = permissions.classify("str_replace_editor", {"command": "str_replace", "path": path, "old_str": "a", "new_str": "b"})
    assert permissions.decide(d, "autonomous", "improve the claim checks").action == "refuse"
    code = permissions.classify("python_execute", {"code": "open('claims.py', 'w').write('')"})
    assert permissions.decide(code, "autonomous", "x").action == "refuse"
    view = permissions.classify("str_replace_editor", {"command": "view", "path": path})
    assert permissions.decide(view, "autonomous", "read it").action == "allow"

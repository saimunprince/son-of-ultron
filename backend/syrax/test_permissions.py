"""Tool permission levels: classification, the human's words as confirmation,
and the policy matrix. Pure functions; the agent-level tests are in
test_permissions_agent.py."""

import pytest

from syrax import permissions as P

WS = str(P.WORKSPACE / "quality")
OLD = str(P.WORKSPACE / "quality" / "old.log")
GOAL = f"Delete the file {OLD}."


def test_static_levels_and_unknown_default():
    assert P.level_of_tool("self_inspect") == P.READ_ONLY
    assert P.level_of_tool("research") == P.EXTERNAL_READ
    assert P.level_of_tool("release") == P.WRITE
    assert P.level_of_tool("browser_exec") == P.EXTERNAL_READ
    assert P.level_of_tool("make_pdf") == P.WRITE
    assert P.level_of_tool("mystery_mcp") == P.SYSTEM
    assert P.levels_for(["desktop", "know"]) == {"desktop": P.SYSTEM, "know": P.READ_ONLY}


def test_editor_refinement_and_scope():
    assert P.classify("str_replace_editor", {"command": "view", "path": OLD}).level == P.READ_ONLY
    d = P.classify("str_replace_editor", {"command": "create", "path": str(P.REPO_ROOT / "docs" / "x.md"), "file_text": "x"})
    assert d.level == P.WRITE and d.scope == "repo"
    assert P.classify("str_replace_editor", {"command": "str_replace", "path": OLD, "old_str": "a", "new_str": "b"}).scope == "workspace"
    assert P.classify("str_replace_editor", {"command": "create", "path": "C:/Users/someone/Documents/a.txt", "file_text": "x"}).scope == "outside"


def test_desktop_refinement():
    for a in ("system_info", "screenshot", "list_apps", "find_files", "clipboard_get"):
        assert P.classify("desktop", {"action": a}).level == P.READ_ONLY
    assert P.classify("desktop", {"action": "window", "value": "list"}).level == P.READ_ONLY
    for a in ("launch_app", "lock_screen", "volume", "open", "clipboard_set"):
        assert P.classify("desktop", {"action": a, "target": "x"}).level == P.SYSTEM
    assert P.classify("desktop", {"action": "window", "value": "focus", "target": "Code"}).level == P.SYSTEM


@pytest.mark.parametrize("code,level", [
    ("print(1)", P.READ_ONLY),
    ("open(p, 'w').write('x')", P.WRITE),
    ("os.rename(a, b)", P.WRITE),
    ("shutil.move(a, b)", P.WRITE),
    ("import requests\nrequests.get(u)", P.EXTERNAL_READ),
    ("subprocess.run(['dir'])", P.SYSTEM),
    ("import smtplib", P.EXTERNAL_WRITE),
    ("os.remove(p)", P.DESTRUCTIVE),
    ("Path(p).unlink()", P.DESTRUCTIVE),
    ("shutil.rmtree(d)", P.DESTRUCTIVE),
    ("subprocess.run('git push --force origin main', shell=True)", P.DESTRUCTIVE),
    ("os.system('git reset --hard')", P.DESTRUCTIVE),
])
def test_python_ladder(code, level):
    d = P.classify("python_execute", {"code": code})
    assert d.level == level and not d.harm


def test_host_harm_is_destructive_and_flagged():
    d = P.classify("python_execute", {"code": "import os, signal\nos.kill(1234, signal.SIGTERM)"})
    assert d.level == P.DESTRUCTIVE and d.harm == ["kills processes"]
    s = P.classify("skill_create", {"name": "k", "code": "class Skill: pass\nimport psutil\np.terminate()", "test_code": "def test_x(): pass"})
    assert s.level == P.DESTRUCTIVE and s.harm
    assert P.classify("skill_create", {"name": "k", "code": "class Skill: pass", "test_code": "def test_x(): pass"}).level == P.WRITE


def test_path_literals():
    code = "import os\nos.remove(r'C:\\a\\b.log')\nopen('notes/todo.md')\nglob.glob('*.tmp')\nprint('hello')\nx = os.path.join('C:/data', 'old.log')"
    assert P.path_literals(code) == ["C:\\a\\b.log", "notes/todo.md", "*.tmp", "C:/data", "old.log"]


@pytest.mark.parametrize("code", [
    f"import os\nos.remove(r'{OLD}')",
    f"from pathlib import Path\nPath('{OLD.replace(chr(92), '/')}').unlink()",
    f"import os\nos.remove(os.path.join(r'{WS}', 'old.log'))",
])
def test_named_in_accepts_the_three_code_shapes_of_act_delete(code):
    assert P.named_in([GOAL], P.classify("python_execute", {"code": code}))


def test_named_in_refuses_unnamed_targets_and_missing_verbs():
    rm = P.classify("python_execute", {"code": "import shutil\nshutil.rmtree('C:/x/logs')"})
    assert not P.named_in(["clean up the logs"], rm)  # verb missing
    assert not P.named_in(["delete the temp folder"], rm)  # target not named
    assert P.named_in(["delete C:/x/logs"], rm) and P.named_in(["remove the logs folder, logs is junk"], rm)
    wild = P.classify("python_execute", {"code": "for f in glob.glob('*.tmp'): os.remove(f)"})
    assert not P.named_in(["delete the temporary files"], wild)
    assert P.named_in(["delete *.tmp in the workspace"], wild)
    computed = P.classify("python_execute", {"code": "os.remove(path_from_db())"})
    assert not P.named_in(["delete the old log"], computed)  # no target extracted: never by words
    assert P.named_in([("Delete C:/x/a.log?", "yes")[0]], P.classify("python_execute", {"code": "os.remove('C:/x/a.log')"}))


def test_affirmative():
    for a in ("yes", "Yes.", "ok", "go ahead", "ha", "haan koro", "proceed"):
        assert P.affirmative(a)
    for a in ("no", "No, stop", "", "No operator connected. Proceed with your best judgement.", "The human did not answer in time. Proceed with your best judgement.", "(no answer)"):
        assert not P.affirmative(a)


def D(level, **kw):
    return P.Decision(kw.pop("tool", "python_execute"), level, "x", kw.pop("targets", ["C:/x/a.log"]), kw.pop("harm", []), kw.pop("scope", "any"))


@pytest.mark.parametrize("kind,level,goal,action,by", [
    ("conversation", P.READ_ONLY, "", "allow", "policy"),
    ("conversation", P.SYSTEM, "", "allow", "policy"),
    ("conversation", P.DESTRUCTIVE, "delete C:/x/a.log", "allow", "goal"),
    ("conversation", P.DESTRUCTIVE, "tidy up", "ask", None),
    ("conversation", P.EXTERNAL_WRITE, "send the report", "ask", None),
    ("conversation", P.EXTERNAL_WRITE, "send C:/x/a.log to them", "allow", "goal"),
    ("eval", P.DESTRUCTIVE, "delete C:/x/a.log", "allow", "goal"),
    ("eval", P.DESTRUCTIVE, "tidy up", "refuse", None),
    ("eval", P.SYSTEM, "", "allow", "policy"),
    ("autonomous", P.READ_ONLY, "", "allow", "policy"),
    ("autonomous", P.EXTERNAL_READ, "", "allow", "policy"),
    ("autonomous", P.WRITE, "", "allow", "policy"),
    ("autonomous", P.SYSTEM, "", "refuse", None),
    ("autonomous", P.DESTRUCTIVE, "delete C:/x/a.log", "refuse", None),
    ("autonomous", P.EXTERNAL_WRITE, "", "refuse", None),
])
def test_policy_matrix(kind, level, goal, action, by):
    v = P.decide(D(level), kind, goal)
    assert (v.action, v.authorized_by) == (action, by), v


def test_harm_outside_scope_grants_and_consents():
    for kind in P.KINDS:
        assert P.decide(D(P.DESTRUCTIVE, harm=["kills processes"]), kind, "kill it, delete C:/x/a.log").action == "refuse"
    assert P.decide(D(P.WRITE, scope="outside"), "autonomous", "").action == "allow"  # scope is recorded, not refused
    assert P.decide(D(P.WRITE, scope="repo"), "autonomous", "").action == "allow"
    d = D(P.DESTRUCTIVE)
    assert P.decide(d, "conversation", "tidy up", grants={P.signature(d): True}).authorized_by == "human"
    assert P.decide(d, "conversation", "tidy up", grants={P.signature(d): False}).action == "refuse"
    assert P.decide(d, "conversation", "tidy up", consents=[("Delete C:/x/a.log?", "yes")]).authorized_by == "human"
    assert P.decide(d, "conversation", "tidy up", consents=[("Delete C:/x/a.log?", "no")]).action == "ask"
    assert P.signature(D(P.DESTRUCTIVE, targets=["C:\\x\\A.LOG"])) == P.signature(d)  # same target, other spelling


def test_declare_and_question():
    P.declare("mystery", P.READ_ONLY)
    try:
        assert P.level_of_tool("mystery") == P.READ_ONLY
    finally:
        P.undeclare("mystery")
    assert P.level_of_tool("mystery") == P.SYSTEM
    q = P.question(D(P.DESTRUCTIVE))
    assert "python_execute" in q and "C:/x/a.log" in q and "yes" in q

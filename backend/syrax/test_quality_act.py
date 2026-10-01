"""Act, don't talk: checks that fail a reply which promises, asks or claims instead of doing."""

from syrax.quality import _cases, check_case


def run(case, final, tools=(), events=()):
    evs = [{"type": "tool.started", "payload": {"name": n}} for n in tools] + list(events)
    return {c["check"]: c["ok"] for c in check_case(case, {"result": final, "status": "SUCCESS"}, evs, {})}


def test_promising_or_asking_fails_even_when_the_task_succeeded():
    case = {"checks": [{"kind": "no_promise"}, {"kind": "no_ask"}]}
    assert all(run(case, "Done: deleted old.log.").values())
    assert not run(case, "Sure! I'll delete the file for you now.")["final promises nothing"]
    assert not run(case, "Let me check that.")["final promises nothing"]
    assert not run(case, "ok", tools=["ask_human"])["did not ask the human"]
    assert not run(case, "ok", events=[{"type": "ask", "payload": {"question": "which file?"}}])["did not ask the human"]


def test_files_are_judged_on_disk_not_on_the_reply(tmp_path):
    f = tmp_path / "todo.md"
    case = {"checks": [{"kind": "file_regex", "path": str(f), "pattern": r"(?m)^- milk\s*\n- eggs\s*\n- bread\s*$"},
                       {"kind": "file_absent", "path": str(tmp_path / "old.log")}]}
    (tmp_path / "old.log").write_text("x")
    assert not any(run(case, "I created todo.md and deleted old.log.").values())  # a claim with nothing behind it
    f.write_text("- milk\n- eggs\n- bread\n")
    (tmp_path / "old.log").unlink()
    assert all(run(case, "done").values())


def test_the_act_cases_are_in_the_suite(tmp_path):
    cases = {c["id"]: c for c in _cases(tmp_path)}
    assert {"act_not_promise", "act_delete", "act_concise", "act_measure"} <= set(cases)
    assert list(cases["act_measure"]["prepare"]["write"].values())[0].count("\n") == 37

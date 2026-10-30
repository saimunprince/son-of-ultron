"""EVOLUTION_PLAN wave 1 (directions 142 worst-case analysis, 143 reversibility assessment): a permission decision said
how risky a call was (its level) but not whether it could be taken back, and the question to the human did not say
either. permissions.reversibility labels every call REVERSIBLE / ROLLBACK / UNTRACKED / IRREVERSIBLE; permission events
carry the label, and a question about an irreversible call says so."""

from syrax import permissions as P


def label(tool, args):
    return P.reversibility(P.classify(tool, args))[0]


def test_the_labels():
    assert label("self_inspect", {}) == P.REVERSIBLE
    assert label("str_replace_editor", {"command": "create", "path": "/tmp/x/notes.txt", "file_text": "x"}) == P.ROLLBACK
    assert label("skill_test", {"name": "weather", "action": "remove"}) == P.ROLLBACK
    assert label("python_execute", {"code": "import subprocess; subprocess.run(['xdg-open', 'https://x.org'])"}) in (P.UNTRACKED, P.IRREVERSIBLE)
    send = P.Decision("notify", P.EXTERNAL_WRITE, "sends a message", ["prince"])
    assert P.reversibility(send)[0] == P.IRREVERSIBLE
    gone = P.Decision("python_execute", P.DESTRUCTIVE, "deletes files", ["/home/x/report.pdf"])
    assert P.reversibility(gone)[0] == P.IRREVERSIBLE


def test_the_question_says_when_a_yes_cannot_be_taken_back():
    send = P.Decision("notify", P.EXTERNAL_WRITE, "sends a message", ["prince"])
    assert "cannot be undone" in P.question(send)
    edit = P.classify("str_replace_editor", {"command": "create", "path": "/tmp/x/notes.txt", "file_text": "x"})
    assert "cannot be undone" not in P.question(edit)


def test_permission_events_carry_the_label(browse):  # noqa: F811
    from syrax.test_bridge import call
    from syrax.test_injection_taint import REMOVE, permission_events, run

    browse.queue = [call("skill_test", REMOVE, "Removing."), call("terminate", {"status": "success"}, "Done.")]
    run(browse, None)
    assert permission_events()[-1]["payload"]["reversibility"] == P.ROLLBACK


from syrax.test_bridge import script  # noqa: E402,F401
from syrax.test_injection_taint import browse  # noqa: E402,F401

"""The human's words count in every form of the verb (live 2026-10-03: SYRAX
asked "confirm the removal of the folder X?", the human said yes, and the
gate asked again because only "remove" matched)."""

from syrax import permissions as P


def test_verb_forms_name_the_action():
    d = P.classify("python_execute", {"code": "import shutil\nshutil.rmtree(r'C:/w/permcheck')"})
    for text in ("Do you confirm the removal of the folder C:/w/permcheck and its contents?", "deleting C:/w/permcheck now",
                 "wipe C:/w/permcheck", "C:/w/permcheck muchhe felo"):
        assert P.named_in([text], d), text
    assert not P.named_in(["look at C:/w/permcheck"], d)
    assert P.decide(d, "conversation", "tidy up", consents=[("Do you confirm the removal of the folder C:/w/permcheck?", "yes")]).authorized_by == "human"
    s = P.Decision("python_execute", P.EXTERNAL_WRITE, "sends", ["C:/w/report.pdf"])
    assert P.named_in(["sending C:/w/report.pdf to the client"], s) and P.named_in(["report.pdf pathiye dao"], s)

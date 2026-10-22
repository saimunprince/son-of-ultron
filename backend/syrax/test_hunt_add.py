"""Brief Factory (2026-10-22): a human points SYRAX at a failure and SYRAX does the rest. hunt_add files a repro
hunt from a summary and the evidence that shows it; the hunt's task writes the test and the fix, and the judge
proves both and files the brief (repro.harvest). Until now the human had to write and dry-run the test too."""

from syrax import repro
from syrax.journal import Journal
from syrax.test_bridge import ORIGIN, TestClient, boot, recv_until, script, server  # noqa: F401

EVIDENCE = 'self_inspect capabilities: "name": "str_replace_editor", "implementation": "backend/app/tool/str_replace_editor.py"'


def test_a_pointed_failure_becomes_a_hunt_with_its_evidence(tmp_path):
    j = Journal(tmp_path / "j.db")
    row, problems = repro.human_hunt(j, "self_inspect names the wrong file for the editor", [EVIDENCE], "backend/syrax/selfmodel.py")
    assert problems == [] and row["check_spec"]["kind"] == repro.HUNT_KIND and row["source"] == "human" and row["priority"] == 1
    assert row["evidence"]["sources"] == [EVIDENCE] and EVIDENCE in row["goal"] and row["goal"].startswith(repro.HUNT_MARK)
    assert repro.human_hunt(j, "self_inspect names the wrong file for the editor", [EVIDENCE])[1] == ["this hunt was filed before"]


def test_a_hunt_needs_a_summary_evidence_it_can_quote_and_a_module_it_may_change(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert "needs a summary" in repro.human_hunt(j, "bad", [EVIDENCE])[1][0]
    assert "needs evidence" in repro.human_hunt(j, "the editor path is wrong in self_inspect", ["short"])[1][0]
    assert "non-judge module" in repro.human_hunt(j, "the editor path is wrong in self_inspect", [EVIDENCE], "backend/syrax/autonomy.py")[1][0]


def test_hunt_add_over_the_websocket(script):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "hunt_add", "summary": "self_inspect names the wrong file for the editor", "evidence": [EVIDENCE],
                      "module": "backend/syrax/selfmodel.py"})
        filed, _ = recv_until(ws, "hunt")
        assert filed["event"] == "filed"
        assert server.get_journal().objective(filed["objective_id"])["check_spec"]["kind"] == repro.HUNT_KIND
        ws.send_json({"type": "hunt_add", "summary": "x", "evidence": []})
        refused, _ = recv_until(ws, "hunt")
        assert refused["event"] == "refused" and len(refused["problems"]) == 2

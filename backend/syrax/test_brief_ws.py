"""Brief Factory (2026-10-22): the human files a brief in one WebSocket message. brief_check screens and proves the
test; brief_add also files the change_released objective pinned to it. By hand this took a scratch worktree, a
config copy, a dry-run script and a diff scan for each of the 13 briefs of 2026-10-17..19."""

from syrax import repro
from syrax.test_bridge import ORIGIN, TestClient, boot, recv_until, script, server  # noqa: F401

TEST = "backend/syrax/test_brief_ws_probe.py"
# agent.py is a judge since 2026-10-29 (a brief naming it is refused): the brief's example targets intent.py
CODE = "from syrax.intent import args_hash\n\n\ndef test_stable():\n    assert args_hash({'a': 1}) == args_hash({'a': 1})\n"


def fake_prove(verdict):
    def prove(root, test_rel, text, fix_diff=None, base="HEAD", cancel=None, red_runs=2):
        return {"verdict": verdict, "test": test_rel, "base": repro.resolve(root, base), "sha256": repro.test_sha(text),
                "red": {"summary": "1 failed, 0 errors, 0 passed"}, **({"reason": "passes on base"} if verdict == "NOT_RED" else {})}
    return prove


def test_a_proven_brief_is_filed_once_and_a_refused_one_says_why(script, monkeypatch):
    monkeypatch.setattr(repro, "prove", fake_prove("RED"))
    msg = {"type": "brief_add", "goal": "A forbidden tool is not requested", "test_path": TEST, "test_code": CODE,
           "files": ["backend/syrax/intent.py"]}
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json(msg)
        filed, _ = recv_until(ws, "brief")
        assert filed["event"] == "filed" and filed["proof"]["verdict"] == "RED", filed
        row = server.get_journal().objective(filed["objective_id"])
        assert row["check_spec"]["repro"]["sha256"] == repro.test_sha(CODE) and row["priority"] == 1
        ws.send_json(msg)
        again, _ = recv_until(ws, "brief")
        assert again["event"] == "refused" and "filed before" in again["problems"][0]
        ws.send_json({**msg, "test_code": "from syrax.intent import args_hash\n\n\ndef test_x():\n    args_hash({})\n"})
        bad, _ = recv_until(ws, "brief")
        assert bad["event"] == "refused" and any("asserts nothing" in p for p in bad["problems"])
        ws.send_json({**msg, "goal": ""})
        nogoal, _ = recv_until(ws, "brief")
        assert nogoal["event"] == "refused" and "needs a goal" in nogoal["problems"][0]


def test_brief_check_proves_without_filing_and_a_test_that_passes_is_refused(script, monkeypatch):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        monkeypatch.setattr(repro, "prove", fake_prove("RED"))
        ws.send_json({"type": "brief_check", "test_path": TEST, "test_code": CODE, "files": ["backend/syrax/intent.py"]})
        checked, _ = recv_until(ws, "brief")
        assert checked["event"] == "checked" and "objective_id" not in checked
        monkeypatch.setattr(repro, "prove", fake_prove("NOT_RED"))
        ws.send_json({"type": "brief_add", "goal": "g", "test_path": TEST, "test_code": CODE, "files": ["backend/syrax/intent.py"]})
        refused, _ = recv_until(ws, "brief")
        assert refused["event"] == "refused" and refused["proof"]["verdict"] == "NOT_RED"
    assert not [o for o in server.get_journal().objectives(limit=50) if (o["check_spec"] or {}).get("repro")]

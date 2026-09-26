"""Verification gate tests: exit codes decide, GREEN needs every required PASS,
results are journaled with evidence, the diff scan catches secrets/debug code."""

import subprocess
import sys
from pathlib import Path

from syrax.journal import Journal
from syrax.verify import Gate, diff_scan, main, run_gate, run_gates, scan_diff_text


def py(code: str) -> list:
    return [sys.executable, "-c", code]


def test_gate_status_comes_from_exit_code_and_captures_evidence():
    ok = run_gate(Gate("ok", py("print('42 passed')")))
    assert ok.status == "PASS" and ok.exit_code == 0 and "42 passed" in ok.evidence
    bad = run_gate(Gate("bad", py("import sys; print('boom'); sys.exit(3)")))
    assert bad.status == "FAIL" and bad.exit_code == 3 and "boom" in bad.evidence


def test_gate_that_cannot_run_is_not_verified_not_pass():
    missing = run_gate(Gate("missing", ["/nonexistent/binary-xyz"]))
    assert missing.status == "NOT_VERIFIED" and missing.exit_code is None
    slow = run_gate(Gate("slow", py("import time; time.sleep(5)"), timeout=0.3))
    assert slow.status == "NOT_VERIFIED" and "timeout" in slow.evidence
    crashed = run_gate(Gate("crash", lambda: (_ for _ in ()).throw(RuntimeError("no benchmark"))))
    assert crashed.status == "NOT_VERIFIED" and "no benchmark" in crashed.evidence


def test_green_only_when_every_required_gate_passes(tmp_path):
    j = Journal(tmp_path / "j.db")
    v = run_gates([Gate("a", py("pass")), Gate("b", lambda: (True, "fine")), Gate("opt", py("import sys; sys.exit(1)"), required=False)], journal=j)
    assert v.status == "GREEN" and [g.status for g in v.gates] == ["PASS", "PASS", "FAIL"]
    v2 = run_gates([Gate("a", py("pass")), Gate("b", py("import sys; sys.exit(1)"))], journal=j)
    assert v2.status == "BLOCKED"
    v3 = run_gates([Gate("a", ["/nonexistent/binary-xyz"])], journal=j)
    assert v3.status == "BLOCKED"  # NOT_VERIFIED on a required gate blocks
    rows = j.verifications()
    assert [r["status"] for r in rows] == ["BLOCKED", "BLOCKED", "GREEN"]
    assert rows[2]["gates"][0]["evidence"] == "" or "PASS" == rows[2]["gates"][0]["status"]
    kinds = [e["type"] for e in j.recent_events()]
    assert kinds == ["verification.completed"] * 3


def test_scan_finds_secrets_and_debug_leftovers_but_not_in_tests():
    diff = "\n".join([
        "+++ b/backend/syrax/core.py",
        "+    print('debugging here')",
        "+    api_key = '" + "AIza" + "SyA1234567890abcdefghijklmnopqrstuv'",  # assembled so the repo never holds a key-shaped literal
        "+++ b/backend/syrax/test_core.py",
        "+    print('this is fine in a test')",
        "+++ b/frontend/components/Syrax.tsx",
        "+  console.log('x')",
        "-  console.log('removed lines are ignored')",
    ])
    found = scan_diff_text(diff)
    assert any("core.py: debug leftover" in f for f in found)
    assert any("core.py: possible secret" in f for f in found)
    assert any("Syrax.tsx: debug leftover" in f for f in found)
    assert not any("test_core.py" in f for f in found)
    assert len(found) == 3


def test_diff_scan_on_a_real_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"], cwd=root, check=True)
    (root / "clean.py").write_text("x = 1\n")
    ok, evidence = diff_scan(root)
    assert ok and "clean" in evidence
    (root / "leak.py").write_text("token = 'ghp_" + "A" * 36 + "'\n")
    (root / "journal.db").write_bytes(b"x")
    ok, evidence = diff_scan(root)
    assert not ok and "leak.py" in evidence and "journal.db" in evidence


def test_cli_exit_code_and_unknown_gate(tmp_path, capsys):
    assert main(["--gate", "nope"]) == 2
    code = main(["--gate", "diff_scan", "--journal", str(tmp_path / "v.db")])
    out = capsys.readouterr().out
    assert code in (0, 1) and out.startswith("VERIFICATION ")
    assert Journal(tmp_path / "v.db", recover=False).verifications()[0]["gates"][0]["name"] == "diff_scan"

"""Phase 6: the radar audits SYRAX's own dependencies (live 2026-10-03: next
16.2.10 had a critical unauthenticated RCE on Windows-hosted servers)."""

from syrax import radar
from syrax.journal import Journal

NEXT = {"severity": "critical", "direct": True, "fix": True, "advisories": ["Next.js: Unauthenticated Remote Code Execution on windows-hosted servers"]}
POSTCSS = {"severity": "high", "direct": False, "fix": True, "advisories": ["PostCSS: Arbitrary file read"]}
NANO = {"severity": "moderate", "direct": False, "fix": True, "advisories": ["nanoid loop"]}


def proposals(j):
    return [e["payload"] for e in j.recent_events(200) if e["type"] == "proposal.created"]


def test_a_new_serious_advisory_becomes_one_proposal(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    found = {"next": NEXT, "nanoid": NANO}
    monkeypatch.setattr(radar, "npm_audit", lambda frontend=None: found)
    assert radar.audit_dependencies(j) == {"total": 2, "serious": ["next"], "new": ["next"]}
    p = proposals(j)
    assert len(p) == 1 and p[0]["kind"] == "security" and "Remote Code Execution" in p[0]["proposal"] and "npm audit fix" in p[0]["proposal"]
    assert radar.audit_dependencies(j)["new"] == [] and len(proposals(j)) == 1  # the same finding is not proposed daily
    found["postcss"] = POSTCSS
    assert radar.audit_dependencies(j)["new"] == ["postcss"] and len(proposals(j)) == 2
    found.clear()
    assert radar.audit_dependencies(j) == {"total": 0, "serious": [], "new": []}
    assert [e["payload"]["serious"] for e in j.recent_events(200) if e["type"] == "radar.audit"][-1] == []


def test_npm_audit_parses_the_real_report_shape(tmp_path, monkeypatch):
    import subprocess

    report = '{"vulnerabilities": {"next": {"severity": "critical", "isDirect": true, "fixAvailable": true, "via": [{"title": "RCE"}, "sharp"]}}}'
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=report, stderr=""))
    assert radar.npm_audit(tmp_path) == {"next": {"severity": "critical", "direct": True, "fix": True, "advisories": ["RCE"]}}

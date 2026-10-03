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


def fake_osv(db):
    def post(url, body):
        return {"results": [{"vulns": [{"id": i} for i in db.get(q["package"]["name"], {}).get("ids", [])]} for q in body["queries"]]}

    def get(url):
        vid = url.rsplit("/", 1)[-1]
        for name, rec in db.items():
            if vid in rec["ids"]:
                return {"id": vid, "summary": rec["summary"], "database_specific": {"severity": rec["sev"]},
                        "affected": [{"package": {"name": name}, "ranges": [{"events": [{"introduced": "0"}, {"fixed": rec["fixed"]}]}]}]}
        raise KeyError(vid)
    return post, get


def test_python_packages_are_audited_against_osv(tmp_path):
    j = Journal(tmp_path / "j.db")
    db = {"starlette": {"ids": ["GHSA-a"], "sev": "HIGH", "fixed": "0.47.2", "summary": "Starlette multipart DoS"},
          "requests": {"ids": ["GHSA-b"], "sev": "MODERATE", "fixed": "2.33.0", "summary": "temp file reuse"}}
    post, get = fake_osv(db)
    pkgs = {"starlette": "0.46.2", "requests": "2.32.5", "fastapi": "0.115.0"}
    found = radar.osv_audit(pkgs, post, get)
    assert set(found) == {"starlette", "requests"}
    assert found["starlette"] == {"version": "0.46.2", "ids": ["GHSA-a"], "severity": "high", "summaries": ["Starlette multipart DoS"], "fixed": "0.47.2"}
    assert radar.audit_python(j, pkgs, post, get) == {"vulnerable": ["requests", "starlette"], "serious": ["starlette"], "new": ["starlette"]}
    p = proposals(j)
    assert len(p) == 1 and "starlette 0.46.2 (high, fixed in 0.47.2)" in p[0]["proposal"] and p[0]["sources"] == ["https://osv.dev/vulnerability/GHSA-a"]
    assert radar.audit_python(j, pkgs, post, get)["new"] == [] and len(proposals(j)) == 1


def test_versions_compare_numerically():
    assert radar._ver("1.10.0") > radar._ver("1.9.9") and radar._ver("0.47.2") > radar._ver("0.47")

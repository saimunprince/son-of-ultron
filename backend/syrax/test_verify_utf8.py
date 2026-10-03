"""On Windows git output was decoded as cp1252: a diff touching a line with
"—" or "…" crashed diff_scan and blocked the gate (2026-10-03)."""

import subprocess

from syrax.verify import diff_scan


def test_diff_scan_reads_a_utf8_diff(tmp_path):
    def git(*a):
        subprocess.run(["git", *a], cwd=tmp_path, check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@t"); git("config", "user.name", "t")
    f = tmp_path / "a.ts"
    f.write_text("// SYRAX’s voice — ready…\nconst a = 1;\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-qm", "x")
    f.write_text("// SYRAX’s voice — ready…\nconst a = 2; // ‘stop’ heard, Ώ (UTF-8 CE 8F: undefined in cp1252)\n", encoding="utf-8")
    ok, report = diff_scan(tmp_path)
    assert ok, report

"""Live 2026-10-29 (autonomy, level 3): the flight_search skill's headless Chrome died at launch (SIGTRAP) inside own
work's confinement. Bisected: the 8 GB RLIMIT_AS cap (JITs reserve far more address space than they use); with
Landlock reads, writes and the TCP rules all on, Chrome runs. Memory is now capped with RLIMIT_DATA, which still
refuses real allocations past the cap."""

import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from syrax import _confine

CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def test_the_data_cap_still_refuses_a_real_allocation_past_it():
    code = ("import resource; resource.setrlimit(resource.RLIMIT_DATA, (256 * 2**20, 256 * 2**20))\n"
            "try:\n    bytearray(512 * 2**20); print('ALLOWED')\nexcept MemoryError:\n    print('refused')")
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).stdout.strip() == "refused"


@pytest.mark.skipif(_confine.abi() < 4 or not CHROME, reason="needs Landlock ABI 4+ and a Chrome")
def test_headless_chrome_starts_inside_own_work_s_confinement(tmp_path):
    code = (
        "import os, sys, tempfile\n"
        f"sys.path.insert(0, {os.getcwd()!r})\n"
        "from syrax import _confine, tools\n"
        "spec = tools.confinement('autonomous', os.devnull, tempfile.mkdtemp(), 60)\n"
        "assert _confine.apply(spec) is None\n"
        "from playwright.sync_api import sync_playwright\n"  # the way flight_search launches it
        "with sync_playwright() as p:\n"
        f"    b = p.chromium.launch(executable_path={CHROME!r}, headless=True)\n"
        "    pg = b.new_page(); pg.set_content('<p>ok</p>'); print('DOM', pg.inner_text('p') == 'ok', 0); b.close()\n"
    )
    # a plain environment: this measures the confinement, not the test session's (conftest puts the guard's
    # sitecustomize and test settings into os.environ)
    env = {k: os.environ[k] for k in ("PATH", "HOME", "LANG", "USER") if k in os.environ}
    # a short TMPDIR, as SYRAX's own (/tmp/syrax_skill_tmp_*): Chrome puts a unix socket in its profile there, and a
    # socket path may not exceed 108 bytes, which pytest's tmp_path plus the profile's name does
    # (under the release gate the writable TMPDIR is the gate's own short one, so it stays the parent)
    env["TMPDIR"] = tempfile.mkdtemp(prefix="br_")
    assert len(env["TMPDIR"]) < 60, env["TMPDIR"]
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120, start_new_session=True)
    assert "DOM True 0" in out.stdout, (out.stdout[-800:], out.stderr[-800:])

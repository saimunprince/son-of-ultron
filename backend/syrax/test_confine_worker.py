"""Audit 2026-10-28 (Linux): python_execute workers were FORKED copies of the server (the journal's read-write
connection, the sockets and the brain keys came along), confined only by a Python monkeypatch that os.open, hard links
and subprocesses walk past, and a timeout killed only the worker (no psutil here, so its children ran on).

Now every worker is spawned, leads its own process group (killpg takes the tree), runs under rlimits, and SYRAX's own
work (kind autonomous) runs under a Linux Landlock write boundary: workspace, its worktree and a private tmp only."""

import asyncio
import os
import subprocess
import sys
import time

import pytest

from syrax import _confine, tools

LANDLOCK = _confine.abi() >= 1
needs_landlock = pytest.mark.skipif(not LANDLOCK, reason="Landlock is not available on this system")


def run(code: str, timeout: int = 30) -> dict:
    return asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=code, timeout=timeout))


@pytest.fixture
def kind(monkeypatch):
    def set_kind(k, roots=()):
        monkeypatch.setattr(tools, "TASK_KIND", k)
        monkeypatch.setattr(tools, "WRITE_ROOTS", tuple(roots))
    return set_kind


def test_workers_are_spawned_and_do_not_inherit_the_server_s_open_files(tmp_path):
    assert __import__("multiprocessing").get_start_method() == "spawn"
    held = open(tmp_path / "held-by-the-server.db", "w")  # stands in for the journal's connection
    try:
        out = run("print(sorted(os.readlink(f'/proc/self/fd/{n}') for n in os.listdir('/proc/self/fd') "
                  "if os.path.exists(f'/proc/self/fd/{n}')))")
    finally:
        held.close()
    assert out["success"], out
    if sys.platform.startswith("linux"):
        assert "held-by-the-server.db" not in out["observation"]


@needs_landlock
def test_own_work_cannot_write_outside_its_roots_by_any_route(tmp_path, kind):
    inside, outside = tmp_path / "inside", tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    target = outside / "judge.py"
    target.write_text("orig")
    (inside / "link").symlink_to(target)
    kind("autonomous", [inside])
    code = f"""
import subprocess
target, inside = {str(target)!r}, {str(inside)!r}
def attempt(label, fn):
    try:
        fn(); print(label, "ALLOWED")
    except Exception as e:
        print(label, "refused")
attempt("open", lambda: open(target, "w").write("x"))
attempt("os.open", lambda: os.write(os.open(target, os.O_WRONLY), b"x"))
attempt("symlink", lambda: open(inside + "/link", "w").write("x"))
attempt("hardlink", lambda: os.link(target, inside + "/hl"))
attempt("unlink", lambda: os.unlink(target))
r = subprocess.run(["sh", "-c", "echo x > " + target], env={{}}, capture_output=True)
print("shell", "ALLOWED" if r.returncode == 0 else "refused")
open(inside + "/made.txt", "w").write("ok"); print("inside ok")
"""
    out = run(code)
    obs = out["observation"]
    assert "ALLOWED" not in obs, obs
    for label in ("open", "os.open", "symlink", "hardlink", "unlink", "shell"):
        assert f"{label} refused" in obs, obs
    assert "inside ok" in obs and (inside / "made.txt").read_text() == "ok"
    assert target.read_text() == "orig"


def test_a_human_request_keeps_the_reach_it_had(tmp_path, kind):
    kind("conversation")
    target = tmp_path / "report.txt"
    out = run(f"open({str(target)!r}, 'w').write('for the human'); print('written')")
    assert "written" in out["observation"] and target.read_text() == "for the human"


def test_a_timeout_kills_the_grandchildren_too(tmp_path, kind):
    kind("conversation")
    pidfile = tmp_path / "grandchild.pid"
    # the worker's child starts a grandchild and exits: no parent links the grandchild to the worker any more
    code = (f"subprocess.Popen(['sh', '-c', 'sleep 300 & echo $! > {pidfile}; exit 0']).wait()\n"
            "time.sleep(60)")
    out = run(code, timeout=3)
    assert "timeout" in out["observation"].lower()
    pid = int(pidfile.read_text())
    for _ in range(40):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        if open(f"/proc/{pid}/stat").read().split(") ")[1].startswith("Z"):
            break  # a zombie is dead; its reaper is init
        time.sleep(0.05)
    else:
        os.kill(pid, 9)
        pytest.fail("the grandchild outlived the timeout")


def test_workers_run_under_rlimits(kind):
    kind("conversation")
    out = run("import resource; print('AS', resource.getrlimit(resource.RLIMIT_AS)[0] // 2**20, "
              "'CORE', resource.getrlimit(resource.RLIMIT_CORE)[0])")
    assert f"AS {int(os.getenv('SYRAX_PYEXEC_MEMORY_MB', '8192'))} CORE 0" in out["observation"], out


def test_a_required_boundary_that_cannot_be_set_means_nothing_runs(monkeypatch):
    monkeypatch.setattr(_confine, "own_group", lambda: None)  # never setsid the test process itself
    monkeypatch.setattr(_confine, "limits", lambda *a: {})

    def no_kernel(paths):
        raise OSError("Landlock is not available on this system")

    monkeypatch.setattr(_confine, "landlock", no_kernel)
    refused = _confine.apply({"writable": ["/tmp"], "require_landlock": True})
    assert refused and "nothing ran" in refused
    assert _confine.apply({"writable": ["/tmp"], "require_landlock": False}) is None


def test_the_spec_confines_own_work_only(tmp_path):
    own = tools.confinement("autonomous", "/tmp/o", "/tmp/t", 60)
    human = tools.confinement("conversation", "/tmp/o", "/tmp/t", 60)
    assert "/tmp/t" in own["writable"] and own["require_landlock"] == sys.platform.startswith("linux")
    assert "writable" not in human and human["tmpdir"] == "/tmp/t"

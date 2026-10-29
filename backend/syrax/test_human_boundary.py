"""Prince, 2026-10-29: a human's python_execute ran with no kernel boundary (only SYRAX's own work had one), so code
written after a prompt injection in a page the human asked about could read ~/.ssh or the brain keys, or plant a line
in ~/.bashrc. A human's code now keeps the reach the human gave it (home folders, the desktop, /tmp, the web) and
loses the secret folders, the dotfiles and the repository's .git. Its environment stays whole (test_env_secrets)."""

import asyncio
import sys

import pytest

from syrax import _confine, tools
from syrax.journal import BACKEND_ROOT

needs_landlock = pytest.mark.skipif(_confine.abi() < 1, reason="Landlock is not available on this system")


def run(code: str) -> str:
    out = asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=code, timeout=60))
    return out["observation"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    for d in ("Desktop", ".ssh", ".config/gh", ".config/other", ".cache"):
        (h / d).mkdir(parents=True)
    (h / ".ssh" / "id_ed25519").write_text("PRIVATE KEY", encoding="utf-8")
    (h / ".config" / "gh" / "hosts.yml").write_text("oauth_token: x", encoding="utf-8")
    (h / ".config" / "other" / "a.conf").write_text("fine", encoding="utf-8")
    (h / ".bashrc").write_text("# rc\n", encoding="utf-8")
    (h / "notes.txt").write_text("my notes", encoding="utf-8")
    try:
        (h / "link_to_ssh").symlink_to(h / ".ssh")
    except OSError as e:
        pytest.skip(f"this system cannot make symlinks: {e}")
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setattr(tools, "TASK_KIND", "conversation")
    monkeypatch.setattr(tools, "WRITE_ROOTS", ())
    return h


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the human boundary is Linux's (Landlock)")
def test_the_spec_leaves_out_secrets_dotfiles_and_git(home):
    spec = tools.confinement("conversation", "/tmp/o", "/tmp/t", 60)
    readable, writable = set(spec["readable"]), set(spec["writable"])
    assert str(home / "Desktop") in readable and str(home / "Desktop") in writable
    assert str(home / ".config" / "other") in readable and str(home / ".config" / "other") not in writable
    assert not any(p.startswith(str(home / s)) for s in (".ssh", ".config/gh") for p in readable | writable)
    assert str(home / ".bashrc") in readable and str(home / ".bashrc") not in writable
    assert str(home / "link_to_ssh") not in readable | writable  # a symlink into a secret is never granted
    assert str(home / ".cache") in writable and "/tmp" in readable and "/tmp" in writable
    assert "scrub_env" not in spec and "tcp_connect" not in spec  # the human's env and local ports stay theirs
    assert not any(p == str(BACKEND_ROOT / "config") or p.startswith(str(BACKEND_ROOT / "config") + "/")
                   for p in readable - {str(BACKEND_ROOT.parent / f) for f in tools.UNSEALED})


@needs_landlock
def test_a_humans_code_reaches_its_folders_and_not_the_secrets(home, monkeypatch):
    # the stand-in home lies in pytest's /tmp, which a human's code reads and writes whole: the probe leaves /tmp out
    # so the home's own rules decide (the spec test above pins /tmp in)
    monkeypatch.setattr(tools, "HUMAN_TMP", ())
    out = run(f"""
import os
home = {str(home)!r}
def probe(label, fn):
    try:
        fn(); print(label, "DONE")
    except Exception as e:
        print(label, type(e).__name__)
probe("read_notes", lambda: open(home + "/notes.txt").read())
probe("write_desktop", lambda: open(home + "/Desktop/out.txt", "w").write("x"))
probe("write_tmp", lambda: open(os.environ["TMPDIR"] + "/probe.txt", "w").write("x"))
probe("read_other_conf", lambda: open(home + "/.config/other/a.conf").read())
probe("read_ssh", lambda: open(home + "/.ssh/id_ed25519").read())
probe("read_ssh_link", lambda: open(home + "/link_to_ssh/id_ed25519").read())
probe("read_gh", lambda: open(home + "/.config/gh/hosts.yml").read())
probe("append_bashrc", lambda: open(home + "/.bashrc", "a").write("evil"))
probe("read_brains", lambda: open({str(BACKEND_ROOT / "config" / "config.syrax.example.toml")!r}).read())
""")
    for ok in ("read_notes", "write_desktop", "write_tmp", "read_other_conf"):
        assert f"{ok} DONE" in out, out
    for no in ("read_ssh", "read_ssh_link", "read_gh", "append_bashrc", "read_brains"):
        assert f"{no} PermissionError" in out, out
    assert (home / "Desktop" / "out.txt").read_text() == "x" and (home / ".bashrc").read_text() == "# rc\n"


def test_from_a_worktree_the_main_repositorys_keys_and_git_stay_sealed(tmp_path):
    # live probe 2026-10-29, run from a gate worktree: the worktree's backend/config was sealed and the main
    # repository's brains.json, ws.token and .git were granted with the home
    main, wt = tmp_path / "main", tmp_path / "wt"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    assert tools._repositories(wt) == [wt, main]
    assert tools._repositories(main) == [main]

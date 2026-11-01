"""Audit 2026-11-01 (security F1): the core trusts a local client that claims the UI's Origin, and the release gate
ran SYRAX-written tests with no network limit, so a test could connect to 127.0.0.1:8765 and clear the emergency stop.
The gate's pytest may now connect only to the web, DNS and the ephemeral range (the suite's own test servers); a port
below it, like the core's, is refused by the kernel. Binding stays open."""

import socket
import subprocess
import sys

import pytest

from syrax import _confine, verify

needs_net = pytest.mark.skipif(not sys.platform.startswith("linux") or _confine.abi() < 4, reason="Landlock ABI 4+")

PROBE = """
import socket, sys
def connect(port):
    s = socket.socket(); s.settimeout(2)
    try:
        s.connect(("127.0.0.1", port)); return "ok"
    except PermissionError:
        return "refused"
    except OSError as e:
        return "refused" if e.errno in (1, 13) else "error"
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
print(connect(srv.getsockname()[1]), connect(int(sys.argv[1])))
"""


def low_listener():
    """A listening socket on a port below the ephemeral range, like the core's 8765."""
    eph = _confine.ephemeral_ports()
    for port in range(20000, min(eph.start, 30000)):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            s.close()
            continue
        s.listen(1)
        return s, port
    pytest.skip("no free low port")


@needs_net
def test_the_gates_pytest_may_reach_its_own_test_servers_but_not_the_core(tmp_path):
    srv, port = low_listener()
    try:
        g = next(x for x in verify.default_gates(tmp_path) if x.name == "pytest")
        prefix = g.cmd[: g.cmd.index("--") + 1]  # the gate's own confinement, with this probe in place of pytest
        out = subprocess.run([*prefix, sys.executable, "-c", PROBE, str(port)], capture_output=True, text=True, timeout=30)
        assert out.stdout.split() == ["ok", "refused"], (out.stdout, out.stderr)
    finally:
        srv.close()


def test_the_ephemeral_range_travels_as_one_argument():
    cmd = _confine.wrap(["true"], ["/tmp"], tcp_connect=[443, *_confine.ephemeral_ports()], allow_bind=True)
    if _confine.abi() >= 1:
        assert cmd.count("--tcp-range") == 1 and "--tcp-bind-ok" in cmd and len(cmd) < 40

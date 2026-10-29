"""2026-10-29 (AUDIT_2026-10-28 open item 2): own code could open a TCP connection to any port: the core's socket
(8765), the UI (3000), the browser's debug port, the local model or ssh, and listen on ports of its own. The Python
guard refused the core's port by name, but a clean-env subprocess walked past it. Own work now connects only to the
web and DNS ports (SYRAX_OWN_TCP_PORTS, default 80,443,53) and binds none, enforced by the kernel (Landlock ABI 4+)."""

import asyncio
import socket
import threading

import pytest

from syrax import _confine, tools

needs_net = pytest.mark.skipif(_confine.abi() < 4, reason="Landlock network rules need ABI 4")


def run(code: str) -> dict:
    return asyncio.new_event_loop().run_until_complete(tools.AsyncPythonExecute().execute(code=code, timeout=60))


@pytest.fixture
def listener():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    stop = threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                srv.accept()[0].close()
            except OSError:
                pass

    threading.Thread(target=accept, daemon=True).start()
    yield srv.getsockname()[1]
    stop.set()
    srv.close()


PROBE = """
import socket
def attempt(label, fn):
    try:
        fn(); print(label, "OPEN")
    except OSError as e:
        print(label, "refused")
attempt("connect", lambda: socket.create_connection(("127.0.0.1", {port}), timeout=3).close())
attempt("bind", lambda: socket.socket().bind(("127.0.0.1", 0)))
r = subprocess.run(["python3", "-c", "import socket; socket.create_connection(('127.0.0.1', {port}), timeout=3)"], env={{}},
                   capture_output=True)
print("subprocess", "OPEN" if r.returncode == 0 else "refused")
"""


@needs_net
def test_own_code_reaches_no_local_port_and_binds_none(listener, monkeypatch):
    monkeypatch.setattr(tools, "TASK_KIND", "autonomous")
    monkeypatch.setattr(tools, "WRITE_ROOTS", ())
    out = run(PROBE.format(port=listener))["observation"]
    assert "OPEN" not in out and out.count("refused") == 3, out


def test_a_human_request_keeps_the_network(listener, monkeypatch):
    monkeypatch.setattr(tools, "TASK_KIND", "conversation")
    out = run(PROBE.format(port=listener))["observation"]
    assert "connect OPEN" in out and "subprocess OPEN" in out, out


def test_the_spec_names_the_allowed_ports():
    assert tools.confinement("autonomous", "/tmp/o", "/tmp/t", 60)["tcp_connect"] == list(tools.OWN_TCP_PORTS)
    assert 8765 not in tools.OWN_TCP_PORTS and 443 in tools.OWN_TCP_PORTS
    assert "tcp_connect" not in tools.confinement("conversation", "/tmp/o", "/tmp/t", 60)

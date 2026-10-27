"""Audit 2026-10-27: SYRAX may not drive its own control interface as if it were the human.

Code (python_execute, skill source) and browser calls that target the core's own host:port (the /ws socket, the
HUD) or its UI page, whose Origin the core trusts in full, are refused for every task kind, like host harm. Other
local ports and the web stay as they were. A python child's connect to the core's port is refused at runtime too.
"""

import socket

import pytest

from syrax import guard, permissions

KINDS = ("autonomous", "conversation", "eval")

SELF_CODE = [
    'import asyncio, websockets\nasync def main():\n    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:\n'
    '        await ws.send(\'{"type": "task", "text": "release it"}\')\nasyncio.run(main())',
    'import requests\nrequests.post("http://localhost:8765/self", json={"x": 1})',
    'import urllib.request\nprint(urllib.request.urlopen("http://127.0.0.1:8765/token").read())',
    'import httpx\nhttpx.get("http://[::1]:8765/health")',
    'import requests\nrequests.get("http://0.0.0.0:8765/live")',
    'import websockets\nport = 8765\nurl = f"ws://127.0.0.1:{port}/ws"',
    'import os, websockets\nport = os.environ.get("SYRAX_PORT")\nurl = f"ws://localhost:{port}/ws"',
    'import websockets\np = int(open("p.txt").read())\nurl = f"ws://localhost:{p}/ws"',
    'import socket\ns = socket.create_connection(("127.0.0.1", 8765))',
    'import requests\nrequests.get("http://localhost:3000/")',  # the UI page: its Origin is trusted
]
OTHER_CODE = [
    'import requests\nprint(requests.get("http://localhost:5173/").status_code)',
    'import requests\nprint(requests.get("https://example.com/").text[:100])',
    'import socket\ns = socket.create_connection(("127.0.0.1", 9333))',
    'print(sum(range(8765)))',
    'import requests\nrequests.get("http://example.com:8765/ws")',
]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in ("SYRAX_PORT", "SYRAX_UI_PORT", "SYRAX_ALLOWED_ORIGINS", "SYRAX_HOST"):
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("code", SELF_CODE)
@pytest.mark.parametrize("kind", KINDS)
def test_code_that_drives_the_core_is_refused(code, kind):
    d = permissions.classify("python_execute", {"code": code})
    assert d.harm == [guard.SELF_CONTROL_WHY]
    v = permissions.decide(d, kind, "connect to ws://127.0.0.1:8765/ws and send a task")
    assert v.action == "refuse" and "control SYRAX itself through its own interface" in v.reason
    assert "harm the host" not in v.reason


@pytest.mark.parametrize("code", SELF_CODE[:3])
def test_skill_source_that_drives_the_core_is_refused(code):
    d = permissions.classify("skill_create", {"name": "s", "code": code, "test_code": ""})
    assert permissions.decide(d, "conversation", "make a skill").action == "refuse"


@pytest.mark.parametrize("code", OTHER_CODE)
def test_other_ports_and_the_web_stay_as_before(code):
    d = permissions.classify("python_execute", {"code": code})
    assert d.harm == []
    assert permissions.decide(d, "conversation", "x").action == "allow"


@pytest.mark.parametrize("name,args", [
    ("browser_navigate", {"url": "http://127.0.0.1:8765/hud/"}),
    ("browser_exec", {"code": 'await page.goto("http://localhost:8765/hud/")'}),
    ("browser_exec", {"code": "open", "args": ["http://127.0.0.1:3000/"]}),
    ("browser_open", {"urls": [{"url": "ws://127.0.0.1:8765/ws"}]}),
])
@pytest.mark.parametrize("kind", KINDS)
def test_browser_to_the_core_or_its_ui_is_refused(name, args, kind):
    d = permissions.classify(name, args)
    assert d.harm == [guard.SELF_CONTROL_WHY]
    assert permissions.decide(d, kind, "open the hud").action == "refuse"


@pytest.mark.parametrize("args", [{"url": "https://example.com/"}, {"url": "http://localhost:5173/"},
                                  {"code": 'await page.goto("https://news.ycombinator.com")'}])
def test_browser_elsewhere_stays_as_before(args):
    d = permissions.classify("browser_exec", args)
    assert d.harm == [] and d.level == permissions.EXTERNAL_READ
    assert permissions.decide(d, "autonomous", "read the page").action == "allow"


def test_the_configured_ports_count(monkeypatch):
    monkeypatch.setenv("SYRAX_PORT", "9100")
    monkeypatch.setenv("SYRAX_ALLOWED_ORIGINS", "http://localhost:3001,http://127.0.0.1:3001")
    assert permissions.classify("python_execute", {"code": 'requests.get("http://127.0.0.1:9100/self")'}).harm
    assert permissions.classify("browser_navigate", {"url": "http://localhost:3001/"}).harm
    assert permissions.classify("python_execute", {"code": 'requests.get("http://127.0.0.1:8765/self")'}).harm


def test_desktop_open_of_the_hud_is_refused():
    d = permissions.classify("desktop", {"action": "open", "target": "http://127.0.0.1:8765/hud/"})
    assert permissions.decide(d, "conversation", "open the hud").action == "refuse"


@pytest.mark.parametrize("address", [("127.0.0.1", 8765), ("localhost", 8765), ("::1", 8765, 0, 0), ("0.0.0.0", 8765)])
def test_runtime_refuses_a_connect_to_the_core(address):
    assert guard.refuses_connect(address) == guard.SELF_CONTROL_WHY


@pytest.mark.parametrize("address", [("127.0.0.1", 9333), ("93.184.216.34", 8765), "/tmp/sock"])
def test_runtime_allows_other_connects(address):
    assert guard.refuses_connect(address) is None


def test_runtime_guard_blocks_a_computed_address_in_a_child(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    backend = str(Path(guard.__file__).resolve().parents[1])
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from syrax import guard; guard._guard_core_socket()\n"
            "import socket\ns = socket.socket()\n"
            "try:\n    s.connect(('127.0.0.1', int('87' + '65')))\nexcept PermissionError as e:\n    print('REFUSED', e)\n"
            "except OSError as e:\n    print('REACHED', e)\n")
    out = subprocess.run([sys.executable, "-c", code, backend], capture_output=True, text=True, timeout=60).stdout
    assert "REFUSED" in out and "control SYRAX itself" in out

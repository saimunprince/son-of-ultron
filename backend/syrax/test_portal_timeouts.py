"""Audit 2026-11-01 (I-13): the portal helper added a 90 s timeout for every request and never removed it, so the
CreateSession timer, started first, also cut short Start's wait for the human's permission dialog. Each answered
request now removes its own timer."""

import io
import json
import sys
import types

from syrax import _portal_input


class _Var:
    def __init__(self, sig, value):
        self.sig, self.value = sig, value

    def unpack(self):
        return self.value


def _fake_gi(log):
    pending = {}

    class Conn:
        def get_unique_name(self):
            return ":1.42"

        def signal_subscribe(self, bus, iface, member, path, arg0, flags, cb, data):
            pending["cb"] = cb
            return 7

        def signal_unsubscribe(self, sub):
            pass

        def call_sync(self, bus, path, iface, method, params, *rest):
            log.append(("call", method))
            if method in ("CreateSession", "SelectDevices", "Start") and "cb" in pending:
                results = {"session_handle": "/s/1"} if method == "CreateSession" else {"restore_token": "tok"}
                pending.pop("cb")(None, None, None, None, None, _Var("(ua{sv})", (0, results)), None)

    class Loop:
        def run(self):
            pass

        def quit(self):
            pass

    timers = iter(range(100, 200))

    glib = types.SimpleNamespace(
        MainLoop=Loop,
        Variant=lambda sig, value: _Var(sig, value),
        timeout_add_seconds=lambda s, fn: (lambda i: (log.append(("timer", i)), i)[1])(next(timers)),
        source_remove=lambda i: log.append(("removed", i)),
    )
    gio = types.SimpleNamespace(
        bus_get_sync=lambda *a: Conn(),
        BusType=types.SimpleNamespace(SESSION=0),
        DBusSignalFlags=types.SimpleNamespace(NO_MATCH_RULE=0),
        DBusCallFlags=types.SimpleNamespace(NONE=0),
    )
    gi = types.ModuleType("gi")
    gi.require_version = lambda *a: None
    repo = types.ModuleType("gi.repository")
    repo.Gio, repo.GLib = gio, glib
    gi.repository = repo
    return gi, repo


def test_each_answered_request_removes_its_timer(monkeypatch, capsys):
    log = []
    gi, repo = _fake_gi(log)
    monkeypatch.setitem(sys.modules, "gi", gi)
    monkeypatch.setitem(sys.modules, "gi.repository", repo)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"token": "", "actions": []})))
    _portal_input.main()
    assert json.loads(capsys.readouterr().out) == {"ok": True, "token": "tok"}
    timers = [i for k, i in log if k == "timer"]
    removed = [i for k, i in log if k == "removed"]
    assert len(timers) == 3 and removed == timers  # CreateSession, SelectDevices, Start: each removed after its answer

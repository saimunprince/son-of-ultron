"""Work Presence, the target: right after a desktop or browser call the core
notes the window in front (program and title), journaled as presence.window;
a title that looks private is never written down; nothing is observed for
other tools or while SYRAX is not acting."""

import asyncio

from syrax import presence
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, get_journal, reply, script, server  # noqa: F401


def test_only_desktop_and_browser_calls_are_observed():
    assert presence.observes("desktop") and presence.observes("browser_exec") and presence.observes("browser_screenshot")
    assert not presence.observes("python_execute") and not presence.observes("str_replace_editor") and not presence.observes("")


def test_a_private_looking_title_is_never_recorded():
    assert presence.redact("Untitled - Notepad") == "Untitled - Notepad"
    for t in ("Inbox (3) - prince@example.com - Gmail", "Sign in - Password manager", "Chase Bank - Accounts", "InPrivate - Edge",
              "api_key.txt - Notepad"):
        assert presence.redact(t) == "[title not recorded: it looked private]", t
    assert len(presence.redact("x" * 300)) == 80
    seen = presence.observe_window(lambda: {"title": "Settings", "process": "SystemSettings.exe", "pid": 9})
    assert seen == {"process": "SystemSettings.exe", "title": "Settings"}
    assert presence.observe_window(lambda: None) is None
    assert presence.observe_window(lambda: (_ for _ in ()).throw(OSError("no desktop"))) is None


def run(text):
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(text, said=text, session_id=None, kind="conversation")
        await core.wait()
        return tid

    tid = asyncio.run(go())
    return [e for e in get_journal().events(tid) if e["type"] == "presence.window"]


def test_the_window_is_journaled_after_a_desktop_call_and_not_after_python(script, monkeypatch):
    from syrax import winctl

    monkeypatch.setattr(winctl, "foreground", lambda: {"title": "Untitled - Notepad", "process": "notepad.exe", "pid": 42})
    script.queue = [call("desktop", {"action": "system_info"}), reply("Done.")]
    ev = run("What is this machine?")
    assert len(ev) == 1 and ev[0]["payload"] == {"tool": "desktop", "process": "notepad.exe", "title": "Untitled - Notepad"}
    script.queue = [call("python_execute", {"code": "print(1)"}), reply("1")]
    assert run("print 1 with python") == []

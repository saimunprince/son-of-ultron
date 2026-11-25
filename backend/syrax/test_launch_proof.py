"""A Linux launch is proven by a new process (idea from Mark-LVII, reimplemented 2026-11-25): gtk-launch returns 0
even when the app dies at once, and "Launched X." was a claim nothing had checked."""
import asyncio

from syrax import desktop as D

APP = {"id": "/usr/share/applications/org.gnome.Calculator.desktop", "name": "Calculator", "exec": "gnome-calculator"}


def test_launch_keys_cover_exec_desktop_id_and_name():
    keys = D.launch_keys(APP)
    assert {"gnome-calculator", "org.gnome.calculator", "calculator"} <= keys
    assert "env" not in D.launch_keys({"id": "x.desktop", "name": "X", "exec": "env"})


def test_a_new_matching_process_proves_the_launch(monkeypatch):
    tables = iter([{1: "init", 2: "gnome-calculator --gapplication-service"}])
    monkeypatch.setattr(D, "_process_table", lambda: next(tables))
    out = asyncio.run(D.verify_launch("Calculator", D.launch_keys(APP), {1: "init"}, wait=1))
    assert out == "Launched Calculator: it is running now."


def test_no_process_is_not_verified(monkeypatch):
    monkeypatch.setattr(D, "_process_table", lambda: {1: "init", 3: "bash"})
    out = asyncio.run(D.verify_launch("Calculator", D.launch_keys(APP), {1: "init"}, wait=0))
    assert "not verified" in out and not out.startswith("Launched")


def test_an_app_already_running_is_said_so(monkeypatch):
    before = {1: "init", 5: "/usr/bin/gnome-calculator"}
    monkeypatch.setattr(D, "_process_table", lambda: dict(before))
    out = asyncio.run(D.verify_launch("Calculator", D.launch_keys(APP), before, wait=0))
    assert "already running" in out


def test_without_a_process_list_the_old_answer_stays():
    assert asyncio.run(D.verify_launch("Calculator", D.launch_keys(APP), {}, wait=0)) == "Launched Calculator."


def test_volume_moves_by_an_amount(monkeypatch):
    """"up by 30" is an amount: the level read before, plus 30, set once (not the fixed 10% step)."""
    from app.tool.base import ToolResult

    level = {"v": 35}
    sent = []

    async def raw(self, v):
        if v != "get":
            sent.append(v)
            level["v"] = int(v)
        return ToolResult(output=f"Volume {level['v']}%.")

    monkeypatch.setattr(D.DesktopControl, "_volume_raw", raw)
    tool = D.DesktopControl()
    out = asyncio.run(tool._do_volume("up by 30"))
    assert sent == ["65"] and out.output == "Volume 35% -> 65%."
    out = asyncio.run(tool._do_volume("-80"))
    assert sent[-1] == "0" and out.output == "Volume 65% -> 0%."
    out = asyncio.run(tool._do_volume("+30%"))
    assert sent[-1] == "30"

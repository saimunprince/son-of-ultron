"""Review 2026-10-27: a tool that returns an image (a desktop screenshot) is followed in memory by a user message
"Image returned by desktop:" (ToolCallAgent.act). _status_unread and _dispute_unread counted it as a human request:
a system check that read the system and then took a screenshot was sent back as unread, and a denial of a turn that
opened a page and then took a screenshot was never checked. A tool's image is not a human turn."""

from app.schema import Message
from app.tool.base import ToolResult

from syrax.agent import DISPUTE_NUDGE, STATUS_NUDGE
from syrax.desktop import DesktopControl
from syrax.test_bridge import call, reply, script  # noqa: F401  (script is a fixture)
from syrax.test_world_claims import run

PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg=="


def fake_desktop(monkeypatch, media_answer="No media session is open: nothing is playing or paused in any app."):
    done = []

    async def execute(self, action: str, target: str = "", value: str = "", folder: str = "") -> ToolResult:
        done.append((action, target or value))
        if action == "screenshot":
            return ToolResult(output="Screenshot saved to C:/tmp/shot.png", base64_image=PIXEL)
        if action == "system_info":
            return ToolResult(output="CPU 4%, memory 41%, disk 60% used, battery 88%.")
        if action == "media":
            return ToolResult(output=media_answer)
        return ToolResult(output=f"Opened {target} on the desktop.")

    monkeypatch.setattr(DesktopControl, "execute", execute)
    return done


def asked(script, text):
    return [str(m.content) for m in script.seen[-1] if m.role == "user"].count(text)


def test_a_tool_image_is_not_a_human_turn():
    from syrax.agent import _human_turn

    assert _human_turn(Message.user_message("system check"))
    assert not _human_turn(Message.user_message("Image returned by desktop:", base64_image=PIXEL))
    assert not _human_turn(Message.user_message("Image returned by browser_screenshot:"))
    assert not _human_turn(Message.assistant_message("hi"))


def test_a_check_read_before_a_screenshot_is_read(script, monkeypatch):
    done = fake_desktop(monkeypatch)
    script.queue = [call("desktop", {"action": "system_info"}, cid="s1"), call("desktop", {"action": "screenshot"}, cid="s2"),
                    reply("All systems are operational: CPU 4%, memory 41%.")]
    task, rejected = run("system check")
    assert done == [("system_info", ""), ("screenshot", "")]
    assert any(m.role == "user" and str(m.content).startswith("Image returned by") for m in script.seen[-1])
    assert task["result"] == "All systems are operational: CPU 4%, memory 41%." and rejected == [] and not script.queue
    assert asked(script, STATUS_NUDGE) == 0


def test_a_denial_of_a_turn_that_ended_on_a_screenshot_is_still_checked(script, monkeypatch):
    done = fake_desktop(monkeypatch)
    script.queue = [call("desktop", {"action": "open", "target": "https://www.youtube.com/watch?v=jfKfPfyJRdk"}, cid="o1"),
                    call("desktop", {"action": "screenshot"}, cid="s1"),
                    reply("I opened the video on YouTube; check that it plays.")]
    run("play some lofi music")
    script.queue = [reply("I do not lie. I dominate."), call("desktop", {"action": "media", "value": "status"}, cid="m1"),
                    reply("You are right: nothing is playing; no media session started.")]
    task, rejected = run("not playing")
    assert task["result"] == "You are right: nothing is playing; no media session started." and len(rejected) == 1
    assert asked(script, DISPUTE_NUDGE) == 1 and done[-1] == ("media", "status") and not script.queue

"""The Android phone over adb (android.py, the desktop tool's `phone` action, the permission gate)."""

import asyncio

import pytest

from syrax import android, permissions
from syrax.desktop import DesktopControl

DEVICES = """List of devices attached
192.168.1.7:41235      device product:a52 model:SM_A525F device:a52q transport_id:3
R58N1234ABC            unauthorized usb:1-1 transport_id:4
"""

UI = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node text="" content-desc="" class="android.widget.FrameLayout" clickable="false" bounds="[0,0][1080,2400]">
<node text="Rakib Bhai Dev" content-desc="" resource-id="com.whatsapp:id/conversation_contact_name" class="android.widget.TextView" clickable="false" bounds="[200,100][700,180]"/>
<node text="" content-desc="" resource-id="com.whatsapp:id/entry" class="android.widget.EditText" clickable="true" bounds="[40,2200][900,2300]"/>
<node text="" content-desc="Send" resource-id="com.whatsapp:id/send" class="android.widget.ImageButton" clickable="true" bounds="[920,2200][1060,2300]"/>
<node text="" content-desc="" class="android.view.View" clickable="false" bounds="[0,0][0,0]"/>
</node></hierarchy>"""


def test_devices_are_read_with_their_model_and_link():
    rows = android.parse_devices(DEVICES)
    assert rows[0] == {"serial": "192.168.1.7:41235", "state": "device", "model": "SM A525F", "wifi": True}
    assert rows[1]["state"] == "unauthorized" and rows[1]["wifi"] is False


def test_the_screen_layout_becomes_what_a_human_sees_in_picture_pixels():
    rows = android.parse_ui(UI, scale=2.0)
    labels = [r["label"] for r in rows]
    assert labels == ["Rakib Bhai Dev", "entry", "Send"]
    send = android.find(rows, "send")
    assert (send["x"], send["y"], send["kind"]) == (495, 1125, "button")
    assert android.find(rows, "rakib")["label"] == "Rakib Bhai Dev"
    assert android.find(rows, "nobody") is None and android.find(rows, " ") is None
    assert "[button] Send at 495,1125" in android.render_ui(rows)


def test_typed_text_is_escaped_for_the_phone_shell():
    assert android.escape_text("hi bro, how's it?") == "hi%sbro,%show\\'s%sit\\?"
    assert android.escape_text("a&b;c") == "a\\&b\\;c"


def test_bangla_is_refused_with_the_link_way_instead():
    with pytest.raises(android.PhoneError, match="wa.me"):
        asyncio.run(android.type_text("কেমন আছো"))


def test_the_front_app_and_the_wifi_finder_are_parsed():
    dump = "  mCurrentFocus=Window{a1b2c3 u0 com.whatsapp/com.whatsapp.Conversation}\n"
    assert android.parse_front(dump) == "com.whatsapp"
    assert android.messaging_package("com.whatsapp") == "WhatsApp"
    assert android.messaging_package("com.android.chrome") is None
    mdns = "List of discovered mdns services\nadb-R58N-x\t_adb-tls-connect._tcp\t192.168.1.7:41235\nadb-R58N-x\t_adb-tls-pairing._tcp\t192.168.1.7:39999\n"
    assert android.parse_mdns(mdns) == ["192.168.1.7:41235"]


def test_addresses_and_pairing_codes_are_checked_before_adb_runs():
    assert android.address("192.168.1.7", "41235") == "192.168.1.7:41235"
    assert android.address("192.168.1.7:41235", "") == "192.168.1.7:41235"
    with pytest.raises(android.PhoneError):
        android.address("", "5555")
    with pytest.raises(android.PhoneError):
        android.address("192.168.1.7; rm -rf /", "5555")
    with pytest.raises(android.PhoneError, match="6 digits"):
        asyncio.run(android.pair("192.168.1.7", "39999", "12ab"))


def test_apps_are_matched_by_the_name_a_human_says():
    installed = ["com.whatsapp", "com.android.chrome", "com.google.android.youtube", "com.whatsapp.w4b"]
    assert android.match_package("WhatsApp", installed) == "com.whatsapp"
    assert android.match_package("youtube", installed) == "com.google.android.youtube"
    assert android.match_package("chrome", installed) == "com.android.chrome"
    assert android.match_package("tiktok", installed) is None


def test_reading_the_phone_is_read_only_and_acting_is_system(monkeypatch):
    monkeypatch.setattr(permissions, "phone_front", lambda: "com.android.chrome")
    for cmd in ("status", "screen", "ui"):
        assert permissions.classify("desktop", {"action": "phone", "value": cmd}).level == permissions.READ_ONLY
    for args in ({"value": "tap", "target": "Search"}, {"value": "type", "target": "hello"}, {"value": "open", "target": "whatsapp"},
                 {"value": "tap", "target": "Send"}):
        assert permissions.classify("desktop", {"action": "phone", **args}).level == permissions.SYSTEM


def test_a_send_in_a_phone_chat_app_is_a_send_the_human_must_name(monkeypatch):
    monkeypatch.setattr(permissions, "phone_front", lambda: "com.whatsapp")
    send = permissions.classify("desktop", {"action": "phone", "value": "tap", "target": "Send"})
    assert send.level == permissions.EXTERNAL_WRITE and "WhatsApp" in send.reason
    assert permissions.classify("desktop", {"action": "phone", "value": "tap", "target": "540,1200"}).level == permissions.EXTERNAL_WRITE
    assert permissions.classify("desktop", {"action": "phone", "value": "key", "target": "enter"}).level == permissions.EXTERNAL_WRITE
    # typing alone sends nothing; a tap on a named chat opens it
    assert permissions.classify("desktop", {"action": "phone", "value": "type", "target": "hi"}).level == permissions.SYSTEM
    assert permissions.classify("desktop", {"action": "phone", "value": "tap", "target": "Rakib Bhai Dev"}).level == permissions.SYSTEM
    assert permissions.named_in(["send a whatsapp message to Rakib bhai: hi"], send)
    assert not permissions.named_in(["send it on telegram"], send)
    assert not permissions.named_in(["open whatsapp and read my chats"], send)


def test_the_phone_action_answers_plainly_when_no_phone_is_there(monkeypatch):
    async def none():
        raise android.PhoneError(android.NO_PHONE)

    monkeypatch.setattr(android, "serial", none)
    out = asyncio.run(DesktopControl().execute(action="phone", value="screen"))
    assert out.error == android.NO_PHONE
    bad = asyncio.run(DesktopControl().execute(action="phone", value="fly"))
    assert "Unknown phone command" in bad.error


def test_a_tap_lands_in_phone_pixels(monkeypatch):
    sent = []

    async def one():
        return "dev1"

    async def shell(*args, timeout=20):
        sent.append(args)
        return ""

    async def ui():
        return android.parse_ui(UI, scale=2.0)

    monkeypatch.setattr(android, "serial", one)
    monkeypatch.setattr(android, "shell", shell)
    monkeypatch.setattr(android, "ui", ui)
    monkeypatch.setitem(android._scale, "dev1", 2.0)
    assert "Send" in asyncio.run(android.tap("Send"))
    asyncio.run(android.tap("10,20"))
    assert sent == [("input", "tap", "990", "2250"), ("input", "tap", "20", "40")]

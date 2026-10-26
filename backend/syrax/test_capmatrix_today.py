"""The capability matrix covers what landed 2026-10-26 and reads its evidence from the journal: desktop truth (a desktop
result that read Windows' media sessions, live "Paused: 'Hacksaw Ridge - Praying Soundtrack' in Chrome."), the prebuilt
youtube_play (its own successes; never used live yet, so UNVERIFIED), Windows Store apps (launch_app / list_apps
successes), and Visible Work Presence (presence.window / presence.changed events, which it journals and never read).
No evidence is no pass: an empty window stays UNVERIFIED."""

import sqlite3
import time

from syrax import capmatrix as cm
from syrax.journal import Journal

MEDIA = "Observed output of cmd `desktop` executed:\n"


def call(j, t, cid, name, args, output, ok=True):
    j.record_sync("tool.started", {"id": cid, "name": name, "args": args, "step": 1}, task_id=t)
    if ok:
        j.record_sync("tool.completed", {"id": cid, "name": name, "ok": True, "output": output}, task_id=t)
    else:
        j.record_sync("tool.failed", {"id": cid, "name": name, "ok": False, "output": output}, task_id=t)


def journal_with(tmp_path, calls=(), events=(), age_days=0.0):
    j = Journal(tmp_path / "j.db")
    t = j.start_task_sync("work")
    for i, (name, args, output, ok) in enumerate(calls):
        call(j, t, f"c{i}", name, args, output, ok)
    for type_, payload in events:
        j.record_sync(type_, payload, task_id=None if type_ == "presence.changed" else t)
    j.close()
    if age_days:
        c = sqlite3.connect(tmp_path / "j.db")
        c.execute("UPDATE events SET ts=ts-?", (age_days * 86400,))
        c.commit()
        c.close()
    return cm.read_journal(tmp_path / "j.db", time.time())


def live(journal):
    return cm.live_checks({}, None, journal)


def caps():
    return {c.id: c for c in cm.CAPABILITIES}


def test_the_new_rows_name_their_code_tests_and_probes():
    c = caps()
    assert c["desktop_truth"].label == "Desktop truth (media sessions, window in front)" and c["desktop_truth"].implementation == cm.CURRENT
    assert c["desktop_truth"].tests == ["syrax.test_media_truth::*", "syrax.test_media_reads::*", "syrax.test_keys_target::*"]
    assert c["desktop_truth"].live == ["media_reads"] and c["desktop_truth"].tools == []  # any desktop success is no media reading
    assert "media_report" in c["desktop_truth"].where and "_with_front" in c["desktop_truth"].where
    assert c["youtube_play"].label == "Play on YouTube (prebuilt youtube_play)" and c["youtube_play"].where == "backend/prebuilt/youtube_play/skill.py"
    assert c["youtube_play"].live == ["youtube_play_used"] and c["youtube_play"].tools == ["youtube_play"]
    assert "syrax.test_feature_catalog::test_shipped_skills_are_installed_verified_and_registered" in c["youtube_play"].tests
    assert c["store_apps"].label == "Windows Store apps (list and launch)" and c["store_apps"].tests == ["syrax.test_store_apps::*"]
    assert c["store_apps"].live == ["apps_used"] and "_win_start_apps" in c["store_apps"].where
    assert c["presence"].live == ["presence_events"] and "hud/*.test.js" in c["presence"].note


def test_a_media_reading_is_desktop_truth_s_evidence(tmp_path):
    j = journal_with(tmp_path, [
        ("desktop", {"action": "media", "value": "status"}, MEDIA + "Paused: 'Hacksaw Ridge - Praying Soundtrack' in Chrome.", True),
        ("desktop", {"action": "media", "value": "status"}, MEDIA + "No media session is open: nothing is playing or paused in any app.", True),
        ("desktop", {"action": "media", "value": "play"}, MEDIA + "Played. Playing: 'Sajde' in Chrome.", True),
        ("desktop", {"action": "launch_app", "target": "notepad"}, MEDIA + "Launched notepad.", True),
        ("desktop", {"action": "find_files", "target": "song"}, MEDIA + "now playing: a file name, not a reading", True),  # case counts
        ("desktop", {"action": "media", "value": "get"}, MEDIA + "Error: media value must be play, pause, toggle, next, previous, stop or status.", False),
        ("python_execute", {"code": "print('Playing: x')"}, "Playing: x", True),  # not the desktop tool
    ])
    assert j["counts"]["media_reads"] == 3
    assert live(j)["media_reads"] == ("pass", f"3 desktop results that read the media sessions in {cm.WINDOW_DAYS} d")


def test_no_media_reading_is_no_evidence(tmp_path):
    j = journal_with(tmp_path, [("desktop", {"action": "media", "value": "play"}, MEDIA + "Media play sent.", True),
                                ("desktop", {"action": "media", "value": "status"}, MEDIA + "Error: Paused: unreadable", False)])
    assert live(j)["media_reads"] == (None, "0 desktop results that read the media sessions")


def test_a_reading_older_than_the_window_is_no_evidence(tmp_path):
    j = journal_with(tmp_path, [("desktop", {"action": "media", "value": "status"}, MEDIA + "Playing: 'x' in Chrome.", True)],
                     [("presence.window", {"tool": "desktop", "process": "chrome.exe", "title": "x"})], age_days=cm.WINDOW_DAYS + 1)
    assert live(j)["media_reads"][0] is None and live(j)["presence_events"][0] is None


def test_youtube_play_successes_are_its_evidence(tmp_path):
    out = "Opened 'lofi hip hop radio' (https://www.youtube.com/watch?v=jfKfPfyJRdk) in the browser; a video page starts playing on its own"
    j = journal_with(tmp_path, [("youtube_play", {"query": "lofi hip hop"}, out, True),
                                ("youtube_play", {"query": ""}, "Error: a query is required, e.g. lofi hip hop", False)])
    assert j["counts"]["youtube_play_used"] == 1
    assert live(j)["youtube_play_used"] == ("pass", f"1 youtube_play successes in {cm.WINDOW_DAYS} d")


def test_youtube_play_never_used_or_only_failed_is_no_evidence(tmp_path):
    j = journal_with(tmp_path, [("youtube_play", {"query": "x"}, "Error: YouTube found no video for 'x'", False),
                                ("youtube_open", {"query": "lofi"}, "Opened the search page.", True)])
    assert live(j)["youtube_play_used"] == (None, "0 youtube_play successes")


def test_launch_app_and_list_apps_successes_are_the_store_apps_evidence(tmp_path):
    j = journal_with(tmp_path, [
        ("desktop", {"action": "launch_app", "target": "WhatsApp"}, MEDIA + "Launched WhatsApp.", True),
        ("desktop", {"action": "list_apps"}, MEDIA + "7-Zip File Manager, WhatsApp", True),
        ("desktop", {"action": "launch_app", "target": "Nope"}, MEDIA + "Error: No installed app matches 'Nope'. Try list_apps.", False),
        ("desktop", {"action": "find_files", "target": "WhatsApp"}, MEDIA + "C:/x/WhatsApp.txt", True),
    ])
    assert j["counts"]["apps_used"] == 2
    assert live(j)["apps_used"] == ("pass", f"2 launch_app/list_apps successes in {cm.WINDOW_DAYS} d")
    (tmp_path / "none").mkdir()
    assert live(journal_with(tmp_path / "none"))["apps_used"] == (None, "0 launch_app/list_apps successes")


def test_presence_events_are_work_presence_s_evidence(tmp_path):
    j = journal_with(tmp_path, events=[("presence.window", {"tool": "desktop", "process": "Notepad.exe", "title": "notes - Notepad"}),
                                       ("presence.window", {"tool": "browser_exec", "process": "chrome.exe", "title": "x"}),
                                       ("presence.changed", {"visibility": "minimal", "before": "visible", "by": "human"})])
    assert (j["counts"]["presence_window"], j["counts"]["presence_changed"]) == (2, 1)
    assert live(j)["presence_events"] == ("pass", f"2 target windows observed, 1 visibility changes journaled in {cm.WINDOW_DAYS} d")


def test_no_presence_event_is_no_evidence(tmp_path):
    assert live(journal_with(tmp_path))["presence_events"] == \
        (None, f"0 target windows observed, 0 visibility changes journaled in {cm.WINDOW_DAYS} d")


def test_the_rows_turn_green_only_on_evidence(tmp_path):
    c = caps()
    passing = {"desktop_truth": {"syrax.test_media_truth::test_x": "pass"}, "store_apps": {"syrax.test_store_apps::test_x": "pass"},
               "youtube_play": {"syrax.test_feature_catalog::test_shipped_skills_are_installed_verified_and_registered": "pass"},
               "presence": {"syrax.test_presence::test_x": "pass"}}
    (tmp_path / "used").mkdir()
    (tmp_path / "empty").mkdir()
    used = journal_with(tmp_path / "used", [
        ("desktop", {"action": "media", "value": "status"}, MEDIA + "Playing: 'Sajde' in Chrome.", True),
        ("youtube_play", {"query": "Sajde"}, "Opened 'Sajde' (https://www.youtube.com/watch?v=abcdefghijk) in the browser", True),
        ("desktop", {"action": "launch_app", "target": "WhatsApp"}, MEDIA + "Launched WhatsApp.", True),
    ], [("presence.window", {"tool": "desktop", "process": "chrome.exe", "title": "Sajde - YouTube"})])
    empty = journal_with(tmp_path / "empty")
    for key in ("desktop_truth", "youtube_play", "store_apps"):
        assert cm.evaluate(c[key], used, passing[key], live(used))["status"] == cm.GREEN, key
        row = cm.evaluate(c[key], empty, passing[key], live(empty))
        assert row["status"] == cm.UNVERIFIED and row["why"] == f"no runtime success within {cm.WINDOW_DAYS} d", key
        assert cm.evaluate(c[key], used, {}, live(used))["status"] == cm.UNVERIFIED, key  # no passing test, no GREEN
    # presence is PARTIAL: its evidence lifts it from UNVERIFIED, never to GREEN
    assert cm.evaluate(c["presence"], used, passing["presence"], live(used))["status"] == cm.YELLOW
    assert cm.evaluate(c["presence"], empty, passing["presence"], live(empty))["status"] == cm.UNVERIFIED


def test_the_new_rows_render_in_the_matrix(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.close()
    rows, text = cm.build(tmp_path / "j.db", head="abc1234", now=time.time())
    by_id = {r["id"]: r for r in rows}
    for key in ("desktop_truth", "youtube_play", "store_apps"):
        assert f"| {by_id[key]['label']} |" in text and by_id[key]["status"] == cm.UNVERIFIED
    assert "live:presence_events" in by_id["presence"]["runtime_test"] and "live:media_reads" in by_id["desktop_truth"]["runtime_test"]

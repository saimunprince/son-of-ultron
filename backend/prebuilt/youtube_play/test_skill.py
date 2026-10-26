"""youtube_play: the first video of a results page is the one opened; no network and no browser in tests."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("prebuilt_youtube_play_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

# the shape of the live results page of 2026-10-26, cut down: two results, an escaped ampersand, an emoji
PAGE = ('var ytInitialData = {"contents":{"x":[{"videoRenderer":{"videoId":"rFZHOHl-L8A","thumbnail":{"thumbnails":[{"url":'
        '"https://i.ytimg.com/vi/rFZHOHl-L8A/hq720.jpg?v=6ad62bed\\u0026sqp=x","width":360}]},"title":{"runs":[{"text":'
        '"lofi hip hop radio \\ud83d\\udcda beats to relax/study to"}]}}},{"videoRenderer":{"videoId":"n61ULEU7CO0",'
        '"thumbnail":{"thumbnails":[]},"title":{"runs":[{"text":"Best of lofi hip hop 2021 \\u0026 more"}]}}},'
        '{"videoRenderer":{"videoId":"rFZHOHl-L8A","title":{"runs":[{"text":"the same video again"}]}}}]}};')


def test_the_first_videos_in_page_order_without_repeats():
    assert mod.first_videos(PAGE) == [("rFZHOHl-L8A", "lofi hip hop radio \U0001f4da beats to relax/study to"),
                                      ("n61ULEU7CO0", "Best of lofi hip hop 2021 & more")]
    assert mod.first_videos("<html>no results</html>") == []


def test_play_opens_the_first_video_s_watch_page(monkeypatch):
    urls, opened = [], []
    monkeypatch.setattr(mod, "fetch", lambda url, timeout=15.0: urls.append(url) or PAGE)
    out = mod.play("lofi hip hop", opener=lambda u: opened.append(u) or True)
    assert urls == ["https://www.youtube.com/results?search_query=lofi+hip+hop"]
    assert opened == ["https://www.youtube.com/watch?v=rFZHOHl-L8A"]
    assert out.startswith("Opened 'lofi hip hop radio \U0001f4da beats to relax/study to' (https://www.youtube.com/watch?v=rFZHOHl-L8A)")
    assert out.endswith("Whether it plays: `desktop` media status.")


def test_nothing_found_an_empty_query_and_a_browser_that_will_not_open_are_errors(monkeypatch):
    monkeypatch.setattr(mod, "fetch", lambda url, timeout=15.0: "<html></html>")
    with pytest.raises(LookupError):
        mod.play("zzzz", opener=lambda u: True)
    with pytest.raises(ValueError):
        mod.play("  ", opener=lambda u: True)
    monkeypatch.setattr(mod, "fetch", lambda url, timeout=15.0: PAGE)
    with pytest.raises(RuntimeError):
        mod.play("lofi", opener=lambda u: False)


def test_the_tool_answers_with_an_error_not_an_exception(monkeypatch):
    monkeypatch.setattr(mod, "fetch", lambda url, timeout=15.0: "<html></html>")
    out = asyncio.run(mod.Skill().execute(query="zzzz"))
    assert out.error == "youtube_play: YouTube found no video for 'zzzz'"
    assert mod.Skill.risk == "SYSTEM"  # it opens a window on the human's screen

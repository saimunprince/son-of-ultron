"""youtube_transcript: finds the video id in any link shape, joins captions into
text with the length, cuts long ones, and says plainly when there are no
captions. No network: the fetch is faked."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("prebuilt_youtube_skill", Path(__file__).with_name("skill.py"))
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


class Fetched:
    def __init__(self, rows):
        self.rows = rows

    def to_raw_data(self):
        return self.rows


ROWS = [{"text": "Hello and welcome", "start": 0.0, "duration": 2.0}, {"text": "to the\nshow", "start": 2.0, "duration": 178.0}]


def test_every_link_shape_gives_the_id():
    for url in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ",
                "https://www.youtube.com/shorts/dQw4w9WgXcQ", "https://youtube.com/embed/dQw4w9WgXcQ"):
        assert mod.video_id(url) == "dQw4w9WgXcQ"
    with pytest.raises(ValueError):
        mod.video_id("https://example.com/video")


def test_captions_become_text_with_the_length():
    seen = {}

    def fetch(vid, languages):
        seen.update(vid=vid, languages=languages)
        return Fetched(ROWS)

    out = mod.transcript("https://youtu.be/dQw4w9WgXcQ", ["en", "bn"], fetch=fetch)
    assert out == "Transcript of https://www.youtube.com/watch?v=dQw4w9WgXcQ (2 captions, about 3 min):\nHello and welcome to the show"
    assert seen == {"vid": "dQw4w9WgXcQ", "languages": ["en", "bn"]}
    assert mod.transcript("dQw4w9WgXcQ", fetch=lambda v, languages: Fetched(ROWS), max_chars=5).endswith("[... cut at 5 characters]")


def test_no_captions_is_said_plainly(monkeypatch):
    class TranscriptsDisabled(Exception):
        pass

    def fetch(vid, languages):
        raise TranscriptsDisabled(vid)

    with pytest.raises(LookupError) as e:
        mod.transcript("dQw4w9WgXcQ", ["en"], fetch=fetch)
    assert "has no captions in en" in str(e.value)
    monkeypatch.setattr(mod, "transcript", lambda url, langs: (_ for _ in ()).throw(LookupError("video x has no captions in en")))
    out = asyncio.run(mod.Skill().execute(url="dQw4w9WgXcQ"))
    assert out.error == "youtube_transcript: video x has no captions in en"


def test_the_skill_declares_what_it_does():
    s = mod.Skill()
    assert s.name == "youtube_transcript" and s.risk == "EXTERNAL_READ" and s.parameters["required"] == ["url"]

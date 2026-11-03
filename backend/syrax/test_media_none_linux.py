"""Live 2026-11-03: "What media is playing right now?" on Linux with no player open: playerctl said "No players found",
desktop returned it as an error, and the true answer "No media is playing right now." was itself taken for a claim
that something plays. It ended PARTIAL with "(Not verified: nothing in this task read what is playing.)". No player
is a reading (as on Windows), and "no media is playing" is not a claim."""

import asyncio

import pytest

from syrax import desktop
from syrax.claims import PLAYING_CLAIM
from syrax.desktop import DesktopControl


@pytest.mark.parametrize("text", ["No media is playing right now.", "No audio is playing.", "no video is playing",
                                  "No track is playing at the moment."])
def test_no_media_playing_is_not_a_claim(text):
    assert not PLAYING_CLAIM.search(text), text


def test_a_song_playing_is_still_a_claim():
    assert PLAYING_CLAIM.search("Your lo-fi mix is playing now.")


def test_no_player_on_linux_is_a_reading(monkeypatch):
    async def fake_run(*args, **_):
        return 1, "", "No players found"

    monkeypatch.setattr(desktop, "WINDOWS", False)
    monkeypatch.setattr(desktop, "MACOS", False)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(desktop, "_run", fake_run)
    run = asyncio.new_event_loop().run_until_complete
    status = run(DesktopControl().execute(action="media", value="status"))
    assert status.output == desktop.NO_MEDIA and not status.error
    play = run(DesktopControl().execute(action="media", value="play"))
    assert play.error and "no media player" in play.error.lower()  # a command with nothing to take it still fails

"""The approved new packages (2026-10-12): files go to the Recycle Bin and only
when the human named them; the PDF and YouTube skills ship and are verified
like any prebuilt skill. The real Recycle Bin is never touched here."""

import asyncio

from syrax import permissions, prebuilt
from syrax.desktop import DesktopControl


def test_trash_is_destructive_and_runs_only_on_the_humans_words(tmp_path):
    f = tmp_path / "old.log"
    d = permissions.classify("desktop", {"action": "trash", "target": str(f)})
    assert d.level == permissions.DESTRUCTIVE and d.targets == [str(f)]
    assert permissions.decide(d, "conversation", f"Move {f} to the trash").action == "allow"
    assert permissions.decide(d, "conversation", f"Delete {f}").action == "allow"
    assert permissions.decide(d, "conversation", "clean up my files").action == "ask"
    assert permissions.decide(d, "autonomous", f"Delete {f}").action == "refuse"


def test_trash_moves_the_file_and_says_how_to_undo(tmp_path, monkeypatch):
    import send2trash as s2t

    f = tmp_path / "old.log"
    f.write_text("stale")
    binned = []

    def fake(path):
        binned.append(path)
        f.unlink()

    monkeypatch.setattr(s2t, "send2trash", fake)
    out = asyncio.run(DesktopControl().execute(action="trash", target=str(f)))
    assert out.error is None and "Recycle Bin" in out.output and binned == [str(f)]
    assert "does not exist" in asyncio.run(DesktopControl().execute(action="trash", target=str(f))).error
    assert "needs the file" in asyncio.run(DesktopControl().execute(action="trash")).error


def test_the_new_skills_ship_as_prebuilt():
    assert {"pdf_text", "youtube_transcript"} <= {d.name for d in prebuilt.shipped()}

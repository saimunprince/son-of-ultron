"""The stage survives a restart: what was shown, and not dismissed, replaced or
expired, comes back from the journal; a task's own status and tool views do
not, because the task is no longer running."""

import asyncio
import time

from syrax.journal import Journal
from syrax.presentation import PresentationEngine


def test_the_stage_comes_back_after_a_restart(tmp_path, monkeypatch):
    j = Journal(tmp_path / "j.db")
    before = PresentationEngine(j)

    async def show():
        table = await before.show("table", "the table the human asked for", {"rows": [["a", 1]]}, source="tool")
        reply = await before.show("card", "the reply", {"text": "done"}, slot="reply", ttl_s=900)
        newer = await before.show("card", "the reply", {"text": "done again"}, slot="reply", ttl_s=900)
        status = await before.show("status", "what SYRAX is working on", {"text": "x"}, task_id="t1")
        tool = await before.show("card", "operating desktop", {"text": "y"}, slot="tool", ttl_s=900, task_id="t1")
        gone = await before.show("card", "a notice", {"text": "z"})
        await before.dismiss(gone["presentation_id"], "dismissed by the human")
        old = await before.show("card", "a short notice", {"text": "w"}, ttl_s=5)
        return table, reply, newer, status, tool, old

    table, reply, newer, status, tool, old = asyncio.run(show())
    later = time.time() + 60  # a minute later: the 5 s notice has expired, the 900 s reply has not
    after = PresentationEngine(j)
    assert after.restore(now=later) == 2
    assert set(after.active) == {table["presentation_id"], newer["presentation_id"]}
    assert after._by_slot["reply"] == newer["presentation_id"]
    fresh = asyncio.run(after.show("card", "next", {"text": "n"}))
    assert fresh["presentation_id"] not in {table["presentation_id"], newer["presentation_id"], reply["presentation_id"]}
    assert int(fresh["presentation_id"][1:].split("-")[0]) > int(old["presentation_id"][1:].split("-")[0])
    assert PresentationEngine(j).restore(now=later + 2 * 86400) == 0  # older than a day: not brought back

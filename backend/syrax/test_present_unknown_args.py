"""Objective 291's brief asked for this test and for present's error to say where a table's header goes; the test
was lost when SYRAX rewrote the test file, and the error text when apply_patch dropped the lines past a hunk's counts
(objective 292). The error tells the brain where the header goes, so one retry is enough."""

import asyncio

from syrax.presentation import PresentTool


class Engine:
    async def show(self, kind, title, data, **kw):
        return {"presentation_id": "p1", "ttl_s": 120}


def test_other_unknown_arguments_say_where_the_header_goes():
    out = asyncio.new_event_loop().run_until_complete(PresentTool(engine=Engine()).execute(kind="table", rows=[["a", 1]], sheet_name="Data"))
    assert "unknown argument(s) ['sheet_name']" in out.error and "first row" in out.error

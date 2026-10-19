"""Quality case present_table (2026-10-03 and run #51 on 2026-10-19): asked for "a table with header name,value",
the brain passed `header` (once `Header`) next to `rows`, and present answered "unknown argument(s) ['header']"; it
took two failed calls to put the header into rows. A header argument becomes the table's first row. And a cell
holding 0 showed empty, because _clip read `text or ""`."""

import asyncio

from syrax.presentation import PresentTool


class Engine:
    def __init__(self):
        self.shown = []

    async def show(self, kind, title, data, **kw):
        self.shown.append((kind, data))
        return {"presentation_id": "p1", "ttl_s": 120}


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_a_header_argument_becomes_the_first_row():
    for key in ("header", "Header", "headers", "columns"):
        eng = Engine()
        out = run(PresentTool(engine=eng).execute(kind="table", title="T", rows=[["a", 1], ["b", 0]], **{key: ["name", "value"]}))
        assert not out.error, out.error
        assert eng.shown[-1][1]["rows"] == [["name", "value"], ["a", "1"], ["b", "0"]]


def test_a_header_already_in_rows_is_not_doubled():
    eng = Engine()
    run(PresentTool(engine=eng).execute(kind="table", rows=[["name", "value"], ["a", 1]], header=["name", "value"]))
    assert eng.shown[-1][1]["rows"] == [["name", "value"], ["a", "1"]]

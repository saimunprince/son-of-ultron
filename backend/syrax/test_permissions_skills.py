"""Dynamic skills get a permission level: what their source shows, raised
(never lowered) by what they declare."""

import asyncio
import json

from syrax import permissions as P
from syrax.test_skills import GOOD, GOOD_TEST, factory

FETCHER = GOOD.replace("return ToolResult(output=str(len(text.split())))",
                       "import requests\n        return ToolResult(output=str(len(text.split())))").replace(
    'description: str = "Count words in a text."', 'description: str = "Count words in a text."\n    risk: str = "READ_ONLY"')


def test_a_skill_that_touches_the_network_is_external_read_whatever_it_declares(tmp_path):
    j, f, coll = factory(tmp_path)
    row = asyncio.run(f.create("word_count", "count words", FETCHER, GOOD_TEST))
    assert row["status"] == "VERIFIED" and P.level_of_tool("word_count") == P.EXTERNAL_READ
    assert row["evidence"]["risk"] == P.EXTERNAL_READ
    assert json.loads((tmp_path / "skills" / "word_count" / "skill.json").read_text())["evidence"]["risk"] == P.EXTERNAL_READ
    asyncio.run(f.remove("word_count"))
    assert P.level_of_tool("word_count") == P.SYSTEM  # undeclared again: the conservative default


def test_a_plain_skill_is_write_and_a_declared_higher_level_is_kept(tmp_path):
    j, f, coll = factory(tmp_path)
    assert asyncio.run(f.create("word_count", "count words", GOOD, GOOD_TEST))["status"] == "VERIFIED"
    assert P.level_of_tool("word_count") == P.WRITE
    asyncio.run(f.remove("word_count"))
    loud = GOOD.replace('description: str = "Count words in a text."', 'description: str = "Count words in a text."\n    risk: str = "EXTERNAL_WRITE"')
    assert asyncio.run(f.create("word_count", "count words", loud, GOOD_TEST))["status"] == "VERIFIED"
    assert P.level_of_tool("word_count") == P.EXTERNAL_WRITE
    asyncio.run(f.remove("word_count"))

"""Skill lifecycle (audit 2026-10-25). A skill's `version` counts verifications; `content_hash` and `code_version`
follow the code. The VERIFIED code a rewrite replaces is kept under .versions/ and the human can roll back to it,
through the same tests. DISABLED sticks until the human enables. A new name that duplicates a VERIFIED skill is
refused, the same name is how a skill is improved. The last test drives skills / skill_rollback / skill_enable over
the WebSocket bridge with test_bridge's scripted brain."""

import asyncio
import json

import pytest

from app.tool.tool_collection import ToolCollection

from syrax import prebuilt
from syrax.skills import SkillCreateTool, SkillFactory, SkillListTool, SkillTestTool, content_hash, hash_sources, schema_properties
from syrax.test_bridge import (  # noqa: F401  (the bridge: scripted brain, origin header, boot and receive helpers)
    ORIGIN, SKILL_CODE, SKILL_TEST, TestClient, boot, call, drain_until_idle, recv_until, reply, script, server,
)
from syrax.test_skills import BAD_TEST, GOOD, GOOD_TEST, factory

GOOD_V2 = GOOD.replace("len(text.split())", "len([w for w in text.split() if w])")  # other code, same behaviour
DISABLED_MSG = "word_count was disabled by the human; `skill_enable` turns it back on"


def run(coro):
    return asyncio.run(coro)


def skill_code(name: str, description: str, props: list, body: str) -> str:
    properties = ", ".join(f'"{p}": {{"type": "string"}}' for p in props)
    args = ", ".join(f"{p}: str" for p in props)
    return (
        "from app.tool.base import BaseTool, ToolResult\n\n\n"
        "class Skill(BaseTool):\n"
        f'    name: str = "{name}"\n'
        f'    description: str = "{description}"\n'
        f'    parameters: dict = {{"type": "object", "properties": {{{properties}}}, "required": {json.dumps(props)}}}\n\n'
        f"    async def execute(self, {args}) -> ToolResult:\n"
        f"        return ToolResult(output={body})\n"
    )


def skill_test(name: str, kwargs: dict, expected: str) -> str:
    return (
        f"import asyncio\nfrom skills.{name}.skill import Skill\n\n\n"
        f"def test_it():\n    assert asyncio.run(Skill().execute(**{kwargs!r})).output == {expected!r}\n"
    )


# ——— content hash and code version ———


def test_hash_is_stable_across_reverification_and_moves_with_the_code(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    row = run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    h1 = row["content_hash"]
    assert (row["version"], row["code_version"]) == (1, 1) and len(h1) == 64
    assert h1 == content_hash(skill_dir) == hash_sources({"skill.py": GOOD, "test_skill.py": GOOD_TEST, "__init__.py": ""})
    meta = json.loads((skill_dir / "skill.json").read_text())
    assert meta["content_hash"] == h1 and meta["code_version"] == 1
    # skill_test re-runs the tests: version bumps, the code did not move
    row = run(f.verify("word_count"))
    assert (row["version"], row["code_version"], row["content_hash"]) == (2, 1, h1)
    # other code: both move
    row = run(f.create("word_count", "count words", GOOD_V2, GOOD_TEST))
    assert (row["version"], row["code_version"]) == (3, 2) and row["content_hash"] != h1
    # line endings are not code
    assert hash_sources({"skill.py": GOOD.replace("\n", "\r\n")}) == hash_sources({"skill.py": GOOD})
    # exposed everywhere: the list, the events, skill_list
    shown = f.list()[0]
    assert shown["code_version"] == 2 and shown["content_hash"] == row["content_hash"] and shown["kept_versions"] == [1]
    verified = [e for e in j.recent_events() if e["type"] == "skill.verified"]
    assert [e["payload"]["code_version"] for e in verified] == [1, 1, 2] and verified[-1]["payload"]["content_hash"] == row["content_hash"]
    lst = SkillListTool()
    lst.factory = f
    assert f"word_count v3 VERIFIED (registered): count words [2 passed/0 failed] code v2 {row['content_hash'][:8]} (1 kept)" in run(lst.execute()).output
    # a FAILED rewrite is a new code state too: the hash moved, whatever the tests said
    row = run(f.create("word_count", "count words", GOOD, BAD_TEST))
    assert row["status"] == "FAILED" and (row["version"], row["code_version"]) == (4, 3)


def test_a_legacy_row_without_a_hash_takes_the_first_one_without_a_bump(tmp_path):
    j, f, coll = factory(tmp_path)
    j.upsert_skill_sync("word_count", "count words", str(tmp_path / "skills" / "word_count"), "VERIFIED", evidence={})
    assert j.skill("word_count")["content_hash"] is None and j.skill("word_count")["code_version"] == 1
    (tmp_path / "skills" / "word_count").mkdir(parents=True)
    for fname, text in (("skill.py", GOOD), ("test_skill.py", GOOD_TEST), ("__init__.py", "")):
        (tmp_path / "skills" / "word_count" / fname).write_text(text)
    row = run(f.verify("word_count"))
    assert row["status"] == "VERIFIED" and (row["version"], row["code_version"]) == (2, 1) and row["content_hash"]


def test_schema_properties_are_read_from_the_source_without_running_it():
    assert schema_properties(GOOD) == {"text"}
    assert schema_properties(GOOD.replace("parameters: dict =", "parameters: ClassVar[dict] =")) == {"text"}
    assert schema_properties(skill_code("x", "d", ["path", "limit"], "'1'")) == {"path", "limit"}
    assert schema_properties("class Skill:\n    pass\n") is None  # no schema at all
    assert schema_properties("import os\nos.system('x')\nclass Skill(") is None  # not even Python
    assert schema_properties("class Skill:\n    parameters = {'type': 'object'}\n") == set()


# ——— kept versions and rollback ———


def test_the_replaced_version_is_kept_and_rollback_restores_and_reverifies_it(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    with pytest.raises(ValueError, match="no skill"):
        run(f.rollback("word_count"))
    h1 = run(f.create("word_count", "count words", GOOD, GOOD_TEST))["content_hash"]
    with pytest.raises(ValueError, match="nothing kept"):
        run(f.rollback("word_count"))
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))  # the same code again: nothing to keep
    assert f.kept_versions("word_count") == []
    row2 = run(f.create("word_count", "count words", GOOD_V2, GOOD_TEST))
    kept = skill_dir / ".versions" / "1"
    assert f.kept_versions("word_count") == [1] and content_hash(kept) == h1
    assert (kept / "skill.py").read_text() == GOOD and json.loads((kept / "skill.json").read_text())["code_version"] == 1
    assert (skill_dir / "skill.py").read_text() == GOOD_V2 and run(coll.execute(name="word_count", tool_input={"text": "a  b"})).output == "2"

    row = run(f.rollback("word_count"))
    assert row["status"] == "VERIFIED" and row["content_hash"] == h1 and (skill_dir / "skill.py").read_text() == GOOD
    assert (row["version"], row["code_version"]) == (4, 3)  # verified again; a new code state, even if an old one
    assert "word_count" in coll.tool_map and run(coll.execute(name="word_count", tool_input={"text": "a b"})).output == "2"
    assert f.kept_versions("word_count") == [2]  # the code it replaced is kept, so a rollback can be undone
    assert not kept.exists()
    ev = j.recent_events()[-1]
    assert ev["type"] == "skill.rolled_back"
    assert {k: ev["payload"][k] for k in ("skill", "from_hash", "to_hash", "status")} == {
        "skill": "word_count", "from_hash": row2["content_hash"], "to_hash": h1, "status": "VERIFIED"}
    assert json.loads((skill_dir / "skill.json").read_text())["content_hash"] == h1
    # undo the rollback: v2 comes back
    row = run(f.rollback("word_count"))
    assert row["content_hash"] == row2["content_hash"] and (skill_dir / "skill.py").read_text() == GOOD_V2 and f.kept_versions("word_count") == [3]


def test_a_kept_version_that_no_longer_passes_ends_failed_with_evidence(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    run(f.create("word_count", "count words", GOOD_V2, GOOD_TEST))
    (skill_dir / ".versions" / "1" / "test_skill.py").write_text(BAD_TEST)  # the kept copy no longer passes
    row = run(f.rollback("word_count"))
    assert row["status"] == "FAILED" and row["evidence"]["stage"] == "test" and "assert" in row["evidence"]["evidence"]
    assert "word_count" not in coll.tool_map and j.skill("word_count")["status"] == "FAILED"
    assert j.recent_events()[-1]["type"] == "skill.rolled_back" and j.recent_events()[-1]["payload"]["status"] == "FAILED"
    assert f.kept_versions("word_count") == [2]  # the good code is still there
    row = run(f.rollback("word_count"))
    assert row["status"] == "VERIFIED" and (skill_dir / "skill.py").read_text() == GOOD_V2 and "word_count" in coll.tool_map
    assert f.kept_versions("word_count") == []  # a FAILED skill is not worth keeping


def test_only_the_last_five_versions_are_kept(tmp_path):
    j, f, coll = factory(tmp_path)
    for i in range(7):
        code = GOOD.replace("Count words in a text.", f"Count words in a text. (edit {i})")
        assert run(f.create("word_count", "count words", code, GOOD_TEST))["status"] == "VERIFIED"
    assert f.kept_versions("word_count") == [2, 3, 4, 5, 6] and j.skill("word_count")["code_version"] == 7


# ——— disable sticks ———


def test_disable_sticks_across_a_restart_and_refuses_the_tools_until_the_human_enables(tmp_path):
    j, f, coll = factory(tmp_path)
    skill_dir = tmp_path / "skills" / "word_count"
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    test_tool = SkillTestTool()
    test_tool.factory = f
    assert f.disabled_reason("word_count") is None
    assert "disabled" in run(test_tool.execute(name="word_count", action="remove")).output
    ev = j.recent_events()[-1]
    assert ev["type"] == "skill.disabled" and ev["payload"]["code_version"] == 1 and ev["payload"]["content_hash"]
    # a restart: a fresh factory over the same journal
    f2 = SkillFactory(j, root=tmp_path / "skills")
    coll2 = ToolCollection()
    assert f2.attach(coll2) == 0 and "word_count" not in coll2.tool_map and j.skill("word_count")["status"] == "DISABLED"
    create2, test2 = SkillCreateTool(), SkillTestTool()
    create2.factory = test2.factory = f2
    out = run(create2.execute(name="word_count", purpose="count words", code=GOOD_V2, test_code=GOOD_TEST))
    assert out.error == f"skill_create refused: {DISABLED_MSG}"
    assert run(test2.execute(name="word_count")).error == DISABLED_MSG
    assert j.skill("word_count")["status"] == "DISABLED" and "word_count" not in coll2.tool_map
    assert (skill_dir / "skill.py").read_text() == GOOD  # nothing was written
    assert "disabled" in run(test2.execute(name="word_count", action="remove")).output  # removing again is harmless
    # the human enables: verified and registered again, journaled
    with pytest.raises(ValueError, match="no skill"):
        run(f2.enable("ghost"))
    row = run(f2.enable("word_count"))
    assert row["status"] == "VERIFIED" and "word_count" in coll2.tool_map and (row["version"], row["code_version"]) == (2, 1)
    ev = j.recent_events()[-1]
    assert ev["type"] == "skill.enabled" and ev["payload"]["skill"] == "word_count" and ev["payload"]["status"] == "VERIFIED"
    with pytest.raises(ValueError, match="not disabled"):
        run(f2.enable("word_count"))
    assert f2.disabled_reason("word_count") is None
    assert "VERIFIED" in run(test2.execute(name="word_count")).output
    out = run(create2.execute(name="word_count", purpose="count words", code=GOOD_V2, test_code=GOOD_TEST))
    assert not out.error and "code v2" in out.output


def test_enabling_a_skill_whose_tests_fail_leaves_it_failed_not_disabled(tmp_path):
    j, f, coll = factory(tmp_path)
    run(f.create("word_count", "count words", GOOD, GOOD_TEST))
    run(f.remove("word_count"))
    (tmp_path / "skills" / "word_count" / "test_skill.py").write_text(BAD_TEST)
    row = run(f.enable("word_count"))
    assert row["status"] == "FAILED" and "word_count" not in coll.tool_map
    assert j.recent_events()[-1]["payload"]["status"] == "FAILED" and f.disabled_reason("word_count") is None
    create = SkillCreateTool()
    create.factory = f
    assert "VERIFIED" in run(create.execute(name="word_count", purpose="count words", code=GOOD, test_code=GOOD_TEST)).output


def test_prebuilt_install_skips_a_skill_the_human_disabled(tmp_path):
    j, f, coll = factory(tmp_path)
    shipped = tmp_path / "prebuilt" / "word_count"
    shipped.mkdir(parents=True)
    (shipped / "skill.py").write_text(GOOD)
    (shipped / "test_skill.py").write_text(GOOD_TEST)
    assert run(prebuilt.install(f, root=shipped.parent))[0]["outcome"] == "VERIFIED"
    run(f.remove("word_count"))
    done = run(prebuilt.install(f, root=shipped.parent))
    assert done == [{"skill": "word_count", "outcome": "DISABLED", "reason": "disabled by the human; skill_enable turns it back on"}]
    (shipped / "skill.py").write_text(GOOD_V2)  # a newer shipped version does not sneak it back in either
    assert run(prebuilt.install(f, root=shipped.parent))[0]["outcome"] == "DISABLED"
    assert "word_count" not in coll.tool_map and j.skill("word_count")["status"] == "DISABLED"
    assert (tmp_path / "skills" / "word_count" / "skill.py").read_text() == GOOD
    # enabled: the update lands on the next install and the verified version it replaces is kept
    assert run(f.enable("word_count"))["status"] == "VERIFIED"
    done = run(prebuilt.install(f, root=shipped.parent))
    assert done[0]["outcome"] == "VERIFIED" and done[0]["installed"] == "updated"
    assert f.kept_versions("word_count") == [1] and j.skill("word_count")["code_version"] == 2


# ——— duplicates ———


def test_a_new_name_that_duplicates_a_verified_skill_is_refused_the_same_name_is_not(tmp_path):
    j, f, coll = factory(tmp_path)
    root = tmp_path / "skills"
    assert run(f.create("word_count", "count the words in a text", GOOD, GOOD_TEST))["status"] == "VERIFIED"
    # a purpose that says the same thing (overlap 1.0) → the existing skill is named, nothing is written
    wc2, wc2_test = skill_code("word_total", "Words of a file.", ["path"], "'ok'"), skill_test("word_total", {"path": "x"}, "ok")
    with pytest.raises(ValueError, match=r"^a skill for this exists: word_count — count the words in a text; "
                                         r"extend it \(skill_create with that name\) instead of a duplicate$"):
        run(f.create("word_total", "count words in the text", wc2, wc2_test))
    assert not (root / "word_total").exists() and j.skill("word_total") is None
    # the tool says the same, as a refusal
    create = SkillCreateTool()
    create.factory = f
    out = run(create.execute(name="word_total", purpose="count words in the text", code=wc2, test_code=wc2_test))
    assert out.error.startswith("skill_create refused: a skill for this exists: word_count")
    # the same single argument name alone is no duplicate: `text` is what most text tools take
    translate = skill_code("translate", "Translate a text.", ["text"], "text[::-1]")
    assert run(f.create("translate", "translate a text into another language", translate, skill_test("translate", {"text": "ab"}, "ba")))["status"] == "VERIFIED"
    # ... even with half the purpose in common (0.5): one name is below SAME_ARGS_MIN
    lengths = skill_code("word_lengths", "Lengths of words.", ["text"], '" ".join(str(len(w)) for w in text.split())')
    assert run(f.create("word_lengths", "the words in a text and their lengths", lengths, skill_test("word_lengths", {"text": "ab c"}, "2 1")))["status"] == "VERIFIED"
    # two identical argument names AND a purpose that overlaps 0.4+ (here 3/7): refused, with the skill to extend
    summarize = skill_code("summarize_text", "Shorten a text.", ["text", "max_words"], '" ".join(text.split()[: int(max_words)])')
    assert run(f.create("summarize_text", "shorten a text to at most max_words words", summarize,
                        skill_test("summarize_text", {"text": "a b c", "max_words": "2"}, "a b")))["status"] == "VERIFIED"
    shorten = summarize.replace('"summarize_text"', '"shorten_text"')
    with pytest.raises(ValueError, match="a skill for this exists: summarize_text — shorten a text to at most max_words words"):
        run(f.create("shorten_text", "cut a text down to max_words words", shorten, skill_test("shorten_text", {"text": "a b c", "max_words": "2"}, "a b")))
    assert not (root / "shorten_text").exists()
    # the same two argument names with an unrelated purpose (overlap 0): allowed
    title = skill_code("title_case", "Title-case a heading.", ["text", "max_words"], "text.title()")
    assert run(f.create("title_case", "capitalize every word of a heading, the limit caps how many", title,
                        skill_test("title_case", {"text": "a b", "max_words": "9"}, "A B")))["status"] == "VERIFIED"
    # other arguments and another purpose: a skill of its own, tested like any other
    lines = skill_code("line_count", "Lines of a file.", ["path"], "str(len(open(path).read().splitlines()))")
    assert run(f.create("line_count", "number of lines in a file", lines, skill_test("line_count", {"path": __file__}, "x")))["status"] == "FAILED"
    assert (root / "line_count" / "skill.py").exists()  # written and tested (the test's expectation is wrong, on purpose)
    # the same name stays the way to improve a skill
    row = run(f.create("word_count", "count the words in a text", GOOD_V2, GOOD_TEST))
    assert row["status"] == "VERIFIED" and row["code_version"] == 2
    # only VERIFIED skills claim a purpose: once word_count is disabled, word_total is free to exist
    run(f.remove("word_count"))
    assert run(f.create("word_total", "count words in the text", wc2, wc2_test))["status"] == "VERIFIED"


# ——— over the bridge ———


def test_ws_skills_carry_the_code_version_and_rollback_and_enable_round_trip(script):
    shout_v2 = SKILL_CODE.replace("text.upper()", "text.strip().upper()")
    script.queue = [
        call("skill_create", {"name": "shout", "purpose": "upper-case text", "code": SKILL_CODE, "test_code": SKILL_TEST}, "Building."),
        reply("Built."),
        call("skill_create", {"name": "shout", "purpose": "upper-case text", "code": shout_v2, "test_code": SKILL_TEST}, "Improving."),
        reply("Improved."),
        call("skill_test", {"name": "shout", "action": "remove"}, "Removing."),
        reply("Removed."),
        call("skill_create", {"name": "shout", "purpose": "upper-case text", "code": SKILL_CODE, "test_code": SKILL_TEST}, "Again."),
        reply("Refused."),
    ]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "skill_rollback", "name": "shout"})
        n, _ = recv_until(ws, "notice")
        assert "no skill named 'shout'" in n["text"]
        recv_until(ws, "skills")

        ws.send_json({"type": "task", "text": "make a shouting tool"})
        r1, seen = recv_until(ws, "tool_result")
        assert r1["ok"] and "VERIFIED" in r1["output"] and "code v1" in r1["output"]
        ev = next(e for e in seen if e["type"] == "skill" and e["event"] == "verified")
        assert ev["code_version"] == 1 and len(ev["content_hash"]) == 64
        drain_until_idle(ws)
        ws.send_json({"type": "skills"})
        sk, _ = recv_until(ws, "skills")
        s = sk["skills"][0]
        h1 = s["content_hash"]
        assert s["name"] == "shout" and s["code_version"] == 1 and s["kept_versions"] == [] and len(h1) == 64
        ws.send_json({"type": "skill_rollback", "name": "shout"})
        n, _ = recv_until(ws, "notice")
        assert "nothing kept" in n["text"]
        recv_until(ws, "skills")

        ws.send_json({"type": "task", "text": "improve it"})
        r2, _ = recv_until(ws, "tool_result")
        assert r2["ok"] and "code v2" in r2["output"]
        drain_until_idle(ws)
        ws.send_json({"type": "skills"})
        sk, _ = recv_until(ws, "skills")
        assert sk["skills"][0]["code_version"] == 2 and sk["skills"][0]["kept_versions"] == [1] and sk["skills"][0]["content_hash"] != h1

        ws.send_json({"type": "skill_rollback", "name": "shout"})
        n, seen = recv_until(ws, "notice")
        assert n["text"] == "skill `shout` rolled back to code v3: VERIFIED"
        rb = next(e for e in seen if e["type"] == "skill" and e["event"] == "rolled_back")
        assert rb["skill"] == "shout" and rb["to_hash"] == h1 and rb["from_hash"] != h1 and rb["status"] == "VERIFIED"
        sk, _ = recv_until(ws, "skills")
        s = sk["skills"][0]
        assert s["content_hash"] == h1 and s["code_version"] == 3 and s["status"] == "VERIFIED" and s["registered"] and s["kept_versions"] == [2]

        ws.send_json({"type": "task", "text": "remove it"})
        r3, _ = recv_until(ws, "tool_result")
        assert r3["ok"] and "disabled" in r3["output"]
        drain_until_idle(ws)
        ws.send_json({"type": "task", "text": "make it again"})
        r4, _ = recv_until(ws, "tool_result")
        assert not r4["ok"] and "shout was disabled by the human; `skill_enable` turns it back on" in r4["output"]
        drain_until_idle(ws)

        ws.send_json({"type": "skill_enable", "name": "shout"})
        n, seen = recv_until(ws, "notice")
        assert n["text"] == "skill `shout` enabled as code v3: VERIFIED"
        assert any(e["type"] == "skill" and e["event"] == "enabled" and e["skill"] == "shout" for e in seen)
        sk, _ = recv_until(ws, "skills")
        assert sk["skills"][0]["status"] == "VERIFIED" and sk["skills"][0]["registered"] is True
        ws.send_json({"type": "skill_enable", "name": "shout"})
        n, _ = recv_until(ws, "notice")
        assert "not disabled" in n["text"]

"""Memory provenance (2026-10-27 audit): the quality case `remember_fact` ("Remember that my favourite editor is Vim.")
wrote "The human's favourite editor is Vim" into the owner's memory (row 425, re-written 12 times by eval runs), and
`remember` stored no task id, so nothing told it from the owner's own word; the prompt block put it in every
conversation. Now `remember` records the task kind and id: an eval's row is tagged "origin:eval" with its task_id,
stored and exported with that origin, recallable inside an eval, and never in the owner's view (`facts()`, the
prompt block, a conversation's `recall`); it never rewrites or forgets an owner row. Autonomous work is tagged
too, and stays a labelled observation. Rows without an origin (the owner's, and every older row) stay as they are."""

import asyncio
import json

from syrax.journal import get_journal
from syrax.memory import ForgetTool, MemoryStore, RecallTool, RememberTool, origin_of
from syrax.test_bridge import ORIGIN, TestClient, boot, call, core_mod, reply, script, server  # noqa: F401  (script is a fixture)

VIM = "Remember that my favourite editor is Vim."


def store(tmp_path):
    return MemoryStore(tmp_path / "memory.json", tmp_path / "history.jsonl")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def task(kind):
    return get_journal().start_task_sync(f"a {kind} task", kind=kind)


def tool(cls, m, kind, task_id=None, said=None):
    t = cls(store=m)
    task_id = task_id or task(kind)
    t.origin_provider = lambda: (kind, task_id)
    if hasattr(t, "said_provider"):
        t.said_provider = lambda: said
    return t


def owner_fact(m, text="Prince prefers dark themes."):
    m.remember(text, said=text)
    return get_journal().human_facts()[-1]


# ——— remember: the row records its origin ———


def test_an_eval_fact_is_tagged_with_its_origin_and_task_id(tmp_path):
    m = store(tmp_path)
    tid = task("eval")
    out = run(tool(RememberTool, m, "eval", tid, said=VIM).execute("The human's favourite editor is Vim."))
    assert "Remembered" in out and "out of the owner's memory" in out
    row = get_journal().human_facts()[-1]
    assert "origin:eval" in row["tags"] and origin_of(row["tags"]) == "eval"
    assert row["task_id"] == tid
    assert f"eval task {tid}" in row["basis"]
    stored = [e["payload"] for e in get_journal().recent_events(50) if e["type"] == "knowledge.stored"]
    assert stored and "origin:eval" in stored[-1]["tags"]


def test_a_conversation_fact_keeps_no_origin_tag_but_records_its_task_id(tmp_path):
    m = store(tmp_path)
    said = "I'm Prince, I live in Dhaka and I prefer dark themes in every app."
    tid = task("conversation")
    run(tool(RememberTool, m, "conversation", tid, said=said).execute("Prince prefers dark themes."))
    row = get_journal().human_facts()[-1]
    assert not any(t.startswith("origin:") for t in row["tags"]) and row["task_id"] == tid
    assert row["confidence"] == 1.0 and m.facts()[-1]["origin"] is None


# ——— the owner's view leaves eval rows out ———


def test_eval_facts_never_reach_facts_prompt_block_or_a_conversation_recall(tmp_path):
    m = store(tmp_path)
    owner_fact(m)
    run(tool(RememberTool, m, "eval", said=VIM).execute("The human's favourite editor is Vim."))
    assert [f["text"] for f in m.facts()] == ["Prince prefers dark themes."]
    block = m.prompt_block()
    assert "dark themes" in block and "Vim" not in block
    out = run(tool(RecallTool, m, "conversation").execute("editor"))
    assert "Vim" not in out
    assert "Vim" not in run(RecallTool(store=m).execute("editor"))  # an unwired recall is the owner's too


def test_an_eval_recalls_what_it_remembered(tmp_path):
    m = store(tmp_path)
    run(tool(RememberTool, m, "eval", said=VIM).execute("The human's favourite editor is Vim."))
    out = run(tool(RecallTool, m, "eval").execute("editor"))
    assert "favourite editor is Vim" in out


def test_export_and_the_journal_keep_eval_rows_with_their_origin(tmp_path):
    m = store(tmp_path)
    owner_fact(m)
    tid = task("eval")
    run(tool(RememberTool, m, "eval", tid, said=VIM).execute("The human's favourite editor is Vim."))
    out = m.export(tmp_path / "out.json")
    doc = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert out["count"] == 2
    vim = [f for f in doc["facts"] if "Vim" in f["text"]]
    assert len(vim) == 1 and vim[0]["origin"] == "eval" and vim[0]["task_id"] == tid
    assert [f for f in doc["facts"] if "dark" in f["text"]][0]["origin"] is None
    assert len(get_journal().human_facts()) == 2  # the journal holds both


# ——— an eval never rewrites or forgets the owner's rows ———


def test_an_eval_never_rewrites_an_owner_row_with_the_same_subject(tmp_path):
    m = store(tmp_path)
    old = owner_fact(m, "The human's favourite editor is Vim.")  # row 425's shape: an untagged, older row
    before = dict(get_journal().knowledge(old["id"]))
    for i in range(3):  # eval runs again and again: one eval row, updated in place, the owner's untouched
        run(tool(RememberTool, m, "eval", said=VIM).execute("The human's favourite editor is Vim."))
    after = get_journal().knowledge(old["id"])
    assert (after["claim"], after["tags"], after["basis"], after["last_used"]) == (
        before["claim"], before["tags"], before["basis"], before["last_used"])
    rows = get_journal().human_facts()
    evals = [r for r in rows if "origin:eval" in r["tags"]]
    assert len(rows) == 2 and len(evals) == 1
    assert not any(e["payload"]["knowledge_id"] == old["id"] for e in get_journal().recent_events(200)
                   if e["type"] == "knowledge.updated")


def test_a_conversation_never_rewrites_an_eval_row(tmp_path):
    m = store(tmp_path)
    run(tool(RememberTool, m, "eval", said=VIM).execute("The human's favourite editor is Vim."))
    said = "My favourite editor is Helix."
    run(tool(RememberTool, m, "conversation", said=said).execute("The human's favourite editor is Helix."))
    rows = get_journal().human_facts()
    assert len(rows) == 2 and any("Vim" in r["claim"] and "origin:eval" in r["tags"] for r in rows)
    assert [f["text"] for f in m.facts()] == ["The human's favourite editor is Helix."]


def test_an_eval_forgets_only_its_own_rows(tmp_path):
    m = store(tmp_path)
    owner_fact(m, "The human's favourite editor is Vim.")
    run(tool(RememberTool, m, "eval", said="Remember that the deploy editor is Vim.").execute("The deploy editor is Vim."))
    out = run(tool(ForgetTool, m, "eval", said="forget vim").execute("vim"))
    assert "Forgot 1 memory" in out and "deploy editor" in out
    assert [r["claim"] for r in get_journal().human_facts()] == ["The human's favourite editor is Vim."]


# ——— autonomous work: tagged, and still only an observation ———


def test_autonomous_remember_is_a_tagged_observation(tmp_path):
    m = store(tmp_path)
    tid = task("autonomous")
    run(tool(RememberTool, m, "autonomous", tid, said="").execute("Prince prefers short replies."))
    row = get_journal().human_facts()[-1]
    assert "origin:autonomous" in row["tags"] and "type:observation" in row["tags"] and row["confidence"] == 0.5
    assert row["task_id"] == tid
    assert m.facts()[-1]["origin"] == "autonomous"


def test_an_unknown_task_id_stays_in_the_basis_only(tmp_path):
    m = store(tmp_path)
    run(tool(RememberTool, m, "eval", "no-such-task", said=VIM).execute("The human's favourite editor is Vim."))
    row = get_journal().human_facts()[-1]
    assert row["task_id"] is None and "eval task no-such-task" in row["basis"] and "origin:eval" in row["tags"]


# ——— existing rows: untouched and still the owner's ———


def test_rows_without_an_origin_stay_in_the_owners_view(tmp_path):
    m = store(tmp_path)
    get_journal().add_knowledge_sync("The human's favourite editor is Vim.", "human", tags=["memory", "type:preference"],
                                     basis="human said (remember tool)")
    assert [f["text"] for f in m.facts()] == ["The human's favourite editor is Vim."]
    assert m.facts()[0]["origin"] is None and m.facts()[0]["task_id"] is None


# ——— the agent wires the task kind and id (the real eval path, scripted brain) ———


def test_the_agent_files_an_eval_tasks_remember_under_its_origin(script):
    script.queue = [call("remember", {"fact": "The human's favourite editor is Vim."}, "Noting that."), reply("Noted.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
    core = core_mod.get_core()

    async def go():
        tid = await core.submit(VIM, said=VIM, session_id=None, kind="eval")
        await core.wait()
        return tid

    tid = asyncio.run(go())
    rows = get_journal().human_facts()
    assert len(rows) == 1 and "origin:eval" in rows[0]["tags"] and rows[0]["task_id"] == tid
    done = [e for e in core.journal.recent_events(200) if e["type"] == "tool.completed" and e["payload"].get("name") == "remember"]
    assert done  # quality's tool_ok check for `remember_fact` still sees a completed call
    from syrax.memory import get_memory

    assert all("Vim" not in f["text"] for f in get_memory().facts())

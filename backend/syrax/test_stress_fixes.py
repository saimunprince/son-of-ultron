"""Stress test 2026-11-06: (1) a question sent right after an answer, while the task was still cleaning up, got
"Already executing. Stop it first." and was lost; it is queued now. (2) "Write a 3000-word essay into essay.md" wrote
one sentence 600 times and ended SUCCESS; a named text file that is mostly repeats is sent back once."""

import asyncio

from syrax.claims import padded_text
from syrax.test_bridge import (  # noqa: F401
    ORIGIN, TestClient, boot, call, core_mod, drain_until_idle, recv_until, reply, script, server,
)
from syrax.test_change_proof import run


def test_a_request_during_the_cleanup_is_queued_not_refused(script, monkeypatch):
    core = core_mod.get_core()
    real = core._clean_repo_after_task

    async def slow_cleanup(*a, **k):
        await asyncio.sleep(1.0)
        return await real(*a, **k)

    monkeypatch.setattr(core, "_clean_repo_after_task", slow_cleanup)
    script.queue = [reply("First done."), reply("Second done.")]
    with TestClient(server.app).websocket_connect("/ws", headers=ORIGIN) as ws:
        boot(ws)
        ws.send_json({"type": "task", "text": "first job"})
        recv_until(ws, "final")
        ws.send_json({"type": "task", "text": "second job"})  # no queue flag: a human typing right after the answer
        second, seen = recv_until(ws, "final")
        assert second["text"] == "Second done."
        assert not any(e.get("type") == "notice" and "Already executing" in str(e.get("text")) for e in seen)
        drain_until_idle(ws)


def test_padding_is_found_and_real_text_is_not(tmp_path):
    pad = tmp_path / "essay.md"
    pad.write_text("# Rivers\n\n" + "Rivers shape the continents, carving valleys and sustaining civilizations. " * 600)
    assert padded_text(str(pad))[0] < 5
    real = tmp_path / "real.md"
    real.write_text("\n".join(f"Sentence number {i} says something new about rivers and the sea." for i in range(60)))
    assert padded_text(str(real)) is None
    assert padded_text(str(tmp_path / "data.csv")) is None


def test_a_padded_essay_is_sent_back_once(script, tmp_path):
    essay = tmp_path / "essay.md"
    loop = f"open({str(essay)!r}, 'w').write('Rivers shape the land and carry water to the sea. ' * 400)"
    real = f"open({str(essay)!r}, 'w').write(''.join(f'Point {{i}} about rivers is its own thought here. ' for i in range(60)))"
    script.queue = [call("python_execute", {"code": loop}), reply(f"Wrote {essay}."),
                    call("python_execute", {"code": real}), reply(f"Rewrote {essay} with varied content.")]
    task, _ = run(f"Write a 3000-word essay about rivers into {essay}.")
    assert task["result"] == f"Rewrote {essay} with varied content." and not script.queue
    assert padded_text(str(essay)) is None

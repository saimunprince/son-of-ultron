"""Live 2026-10-15: quality run #43 called pdf_text on a .txt file ("is not a
PDF"), the self-model called the skill FAILING, a diagnose task called it on a
path that does not exist ("no file at"), and skillevo then ranked "pdf_text
failed 2 of 3 real uses" as a skill to repair. Input a tool cannot act on is
the caller's mistake, for skills too; a real failure still counts."""

from syrax import skillevo
from syrax.journal import Journal, misuse

OBS = "Observed output of cmd `pdf_text` executed:\n"


def test_input_a_tool_cannot_act_on_is_a_caller_mistake_for_any_tool():
    assert misuse("pdf_text", OBS + "Error: pdf_text: deploy.txt is not a PDF")
    assert misuse("pdf_text", OBS + "Error: pdf_text: no file at 'C:\\ai\\nonexistent.pdf'")
    assert misuse("pdf_text", OBS + "Error: pdf_text: pages 3-9 are outside 1-2")
    assert misuse("image_tools", "Error: image_tools: notes.md is not an image (jpg, png)")
    assert not misuse("pdf_text", OBS + "Error: pdf_text: the PDF is password-protected")
    assert not misuse("weather", "Error: weather: the forecast service answered 503")
    assert not misuse("pdf_text", "no file at x")  # not an error result
    assert not misuse("desktop", "Error")


def call(j, t, cid, out=None):
    j.record_sync("tool.started", {"id": cid, "name": "pdf_text", "args": {}}, task_id=t)
    if out is None:
        j.record_sync("tool.completed", {"id": cid, "name": "pdf_text", "ok": True, "output": OBS + "sample.pdf: 1 page(s)"}, task_id=t)
    else:
        j.record_sync("tool.failed", {"id": cid, "name": "pdf_text", "ok": False, "output": OBS + out}, task_id=t)


def test_a_skill_misused_twice_is_not_a_skill_to_repair(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.upsert_skill_sync("pdf_text", "pdf_text", str(tmp_path), "VERIFIED", evidence={})
    t = j.start_task_sync("summarise deploy.txt", kind="eval")
    call(j, t, "a", "Error: pdf_text: deploy.txt is not a PDF")
    call(j, t, "b", "Error: pdf_text: no file at 'nonexistent.pdf'")
    call(j, t, "c")
    use = skillevo.real_use(j)["pdf_text"]
    assert (use["uses"], use["failures"]) == (1, 0) and skillevo.repairs(j) == []
    assert j.tool_stats()["pdf_text"]["last_outcome"] == "ok"
    call(j, t, "d", "Error: pdf_text: the PDF is password-protected")  # the skill's own limit still counts
    assert skillevo.real_use(j)["pdf_text"]["failures"] == 1

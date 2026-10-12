"""F5: an interrupted call that only reads is HARMLESS and the task is
RESUMABLE (live 2026-10-12: disk_usage on C:\\ stayed UNCERTAIN and became a
BLOCKED objective). Code, browser and writing calls stay UNCERTAIN, now with
their permission level and the targets they name, so a human sees exactly
what they may have touched."""

from syrax.journal import Journal
from syrax.test_journal import crash, new


def op(name, **args):
    return {"id": "o1", "name": name, "args": args, "step": 3}


def test_reading_calls_are_harmless_and_others_list_what_they_touch(tmp_path):
    j = Journal(tmp_path / "j.db")
    v = j.verify_operation(op("desktop", action="system_info"))
    assert v["state"] == "HARMLESS" and v["checks"]["level"] == "READ_ONLY" and "repeating it changes nothing" in v["checks"]["reason"]
    assert j.verify_operation(op("research", query="x"))["state"] == "HARMLESS"
    launch = j.verify_operation(op("desktop", action="launch_app", target="notepad"))
    assert launch["state"] == "UNCERTAIN" and launch["checks"]["level"] == "SYSTEM" and launch["checks"]["targets"] == ["notepad"]
    py = j.verify_operation(op("python_execute", code="open(r'C:/data/out.txt', 'w').write('1')"))
    assert py["state"] == "UNCERTAIN" and py["checks"]["level"] == "WRITE" and "C:/data/out.txt" in py["checks"]["targets"]
    assert j.verify_operation(op("python_execute", code="print(1)"))["state"] == "UNCERTAIN"  # code: patterns cannot rule out effects
    assert j.verify_operation(op("browser_navigate", url="https://x"))["state"] == "UNCERTAIN"  # pages can act
    assert j.verify_operation(op("some_mcp_tool"))["checks"]["level"] == "SYSTEM"  # unknown stays unknown


def test_a_skill_counts_by_the_level_its_registry_row_records(tmp_path):
    j = Journal(tmp_path / "j.db")
    j.upsert_skill_sync("disk_usage", "sizes", str(tmp_path), "VERIFIED", evidence={"risk": "READ_ONLY"})
    j.upsert_skill_sync("organize_folder", "tidy", str(tmp_path), "VERIFIED", evidence={"risk": "WRITE"})
    j.upsert_skill_sync("weather", "forecast", str(tmp_path), "FAILED", evidence={"risk": "EXTERNAL_READ"})
    assert j.verify_operation(op("disk_usage", path="C:\\"))["state"] == "HARMLESS"
    assert j.verify_operation(op("organize_folder", action="organize"))["state"] == "UNCERTAIN"
    assert j.verify_operation(op("weather", place="Dhaka"))["checks"]["level"] == "SYSTEM"  # not VERIFIED: not trusted


def test_after_a_crash_a_reading_call_leaves_the_task_resumable(tmp_path):
    t = crash(tmp_path, "after_tool_started", op("desktop", action="screenshot"))
    rec = new(tmp_path).task(t)["recovery"]
    assert rec["state"] == "RESUMABLE" and rec["operation_state"] == "HARMLESS"

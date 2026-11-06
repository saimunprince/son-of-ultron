"""Live 2026-11-06: asked for the 2 largest files, disk_usage returned huge.bin and mid.bin; the answer named
data_large.json and logs_2026.txt, which exist nowhere. An answer naming files no tool showed is asked once again
from the results."""

from syrax.claims import INVENTED_ASK, invented_paths
from syrax.test_bridge import call, reply, script, server  # noqa: F401
from syrax.test_change_proof import run


def test_made_up_paths_are_found_and_real_ones_kept(tmp_path):
    real = tmp_path / "huge.bin"
    real.write_bytes(b"x")
    seen = f"{{'path': '{tmp_path}/mid.bin', 'size_bytes': 250000}}"
    answer = (f"1. `{tmp_path}/data_large.json` 1.19 MB\n2. `{tmp_path}/mid.bin`\n3. {real}\n"
              "Source: https://docs.python.org/3/whatsnew/3.15.html")
    assert invented_paths(answer, seen) == [f"{tmp_path}/data_large.json"]
    assert invented_paths(f"Wrote {tmp_path}/new/out.txt", "", goal=f"write {tmp_path}/new/out.txt") == []


def test_an_answer_with_invented_files_is_asked_again(script, tmp_path):
    (tmp_path / "huge.bin").write_bytes(b"x" * 900)
    script.queue = [
        call("python_execute", {"code": f"import os; print(sorted(os.listdir({str(tmp_path)!r})))"}),
        reply(f"The largest file is {tmp_path}/data_large.json (1.19 MB)."),
        reply(f"The largest file is {tmp_path}/huge.bin (900 bytes)."),
    ]
    task, _ = run(f"What is the largest file in {tmp_path}?")
    assert task["result"] == f"The largest file is {tmp_path}/huge.bin (900 bytes)." and not script.queue
    assert INVENTED_ASK.split(",")[0].split(" names")[0] in str(script.seen[-1][-1].content)


def test_an_answer_naming_only_what_was_seen_is_not_asked(script, tmp_path):
    (tmp_path / "huge.bin").write_bytes(b"x" * 900)
    script.queue = [
        call("python_execute", {"code": f"import os; print(sorted(os.listdir({str(tmp_path)!r})))"}),
        reply(f"The largest file is {tmp_path}/huge.bin (900 bytes)."),
    ]
    task, _ = run(f"What is the largest file in {tmp_path}?")
    assert task["result"] == f"The largest file is {tmp_path}/huge.bin (900 bytes)." and not script.queue

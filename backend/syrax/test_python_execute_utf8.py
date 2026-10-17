"""Live 2026-10-15: python_execute wrote "78.37 \u00b0C" into a report with
open(), as one cp1252 byte on Windows, and the quality checker that read it
as UTF-8 crashed; reads of the repository's UTF-8 files failed with "'charmap'
codec can't decode byte". In the python_execute child text files are UTF-8
unless the code names an encoding."""

import asyncio

from syrax.tools import AsyncPythonExecute


def run(code):
    return asyncio.new_event_loop().run_until_complete(AsyncPythonExecute().execute(code=code, timeout=60))


def test_text_files_are_utf8_unless_the_code_says_otherwise(tmp_path):
    a, b, c = (tmp_path / n for n in ("a.md", "b.md", "c.md"))
    code = (
        f"open(r'{a}', 'w').write('78.37 \\u00b0C')\n"
        f"Path(r'{b}').write_text('caf\\u00e9 \\u2192 ok')\n"
        f"open(r'{c}', 'w', encoding='cp1252').write('\\u00b0')\n"
        f"print(open(r'{a}').read(), Path(r'{b}').read_text(), open(r'{a}', 'rb').read())\n"
    )
    out = run(code)
    assert out["success"], out
    assert a.read_bytes() == "78.37 \u00b0C".encode("utf-8")
    assert b.read_bytes() == "caf\u00e9 \u2192 ok".encode("utf-8")
    assert c.read_bytes() == b"\xb0"  # a named encoding is kept
    assert out["observation"].startswith("78.37 \u00b0C caf\u00e9 \u2192 ok b'78.37 \\xc2\\xb0C'")

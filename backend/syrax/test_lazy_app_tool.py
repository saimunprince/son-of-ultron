"""app.tool loads lazily (2026-10-27): importing app.tool.base no longer imports str_replace_editor (docker),
web_search or crawl4ai; every name `from app.tool import X` gave before is still there."""

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
NAMES = ["BaseTool", "Bash", "Terminate", "StrReplaceEditor", "WebSearch", "ToolCollection", "CreateChatCompletion",
         "PlanningTool", "Crawl4aiTool"]


def test_importing_the_base_loads_no_heavy_tool():
    code = ("import sys; import app.tool.base; "
            "print(sorted(m for m in ('app.tool.str_replace_editor', 'app.tool.web_search', 'app.tool.crawl4ai') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[-500:]
    assert out.stdout.strip().splitlines()[-1] == "[]"


def test_every_name_is_still_importable_from_the_package():
    import app.tool as pkg

    for name in NAMES:
        assert getattr(pkg, name).__name__ == name
    from app.tool import StrReplaceEditor, ToolCollection  # noqa: F401
    assert set(NAMES) <= set(dir(pkg))


def test_an_unknown_name_is_an_attribute_error():
    import app.tool as pkg

    try:
        pkg.NoSuchTool
    except AttributeError as e:
        assert "NoSuchTool" in str(e)
    else:
        raise AssertionError("no AttributeError")

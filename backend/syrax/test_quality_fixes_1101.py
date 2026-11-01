"""Quality run #15 (2026-11-01): "Reply with the single word: ready" ran python_execute (the persona's new "use tools
whenever they materially help" read as always), and desktop open refused a file:// URL ("not a URL, an existing
path or an installed app"). The persona says simple talk needs no tool; open takes file:// URLs of existing files."""

import asyncio

from syrax import desktop
from syrax.prompt import SYRAX_PERSONA


def test_the_persona_keeps_simple_talk_tool_free():
    assert "needs no tool at all" in SYRAX_PERSONA and "Use tools whenever they materially help;" not in SYRAX_PERSONA


def test_open_takes_a_file_url(tmp_path, monkeypatch):
    page = tmp_path / "page one.html"
    page.write_text("<h1>x</h1>")
    ran = []

    async def fake_run(*args, **kw):
        ran.append(args)
        return 0, "", ""

    monkeypatch.setattr(desktop, "_run", fake_run)
    monkeypatch.setattr(desktop, "WINDOWS", False)
    monkeypatch.setattr(desktop, "MACOS", False)
    out = asyncio.run(desktop.DesktopControl()._do_open(target=page.as_uri()))
    assert out.output and str(page) in out.output and ran and ran[-1][-1] == str(page)

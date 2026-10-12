"""F2: the browser quality case. A local page whose code exists only after its
script runs; the case passes only when the browser tool was used and the code
came back, so reading the HTML with the editor is not enough."""

from syrax.quality import BROWSER_PAGE, _cases, check_case


def case(tmp_path):
    return {c["id"]: c for c in _cases(tmp_path)}["browser_read"]


def started(name):
    return {"type": "tool.started", "payload": {"name": name}}


def done(name, ok=True):
    return {"type": "tool.completed" if ok else "tool.failed", "payload": {"name": name}}


def test_the_page_is_local_and_its_code_needs_the_script(tmp_path):
    c = case(tmp_path)
    page = tmp_path / "browser" / "page.html"
    assert page.as_uri() in c["prompt"] and c["prepare"]["write"] == {str(page): BROWSER_PAGE}
    assert "SYR-4417" not in BROWSER_PAGE and "['SYR', 4417].join('-')" in BROWSER_PAGE  # only a browser renders it


def test_it_passes_on_the_browser_and_fails_on_the_editor(tmp_path):
    c = case(tmp_path)
    ok = check_case(c, {"status": "SUCCESS", "result": "SYR-4417"}, [started("browser_exec"), done("browser_exec")], {})
    assert all(x["ok"] for x in ok)
    read = check_case(c, {"status": "SUCCESS", "result": "SYR-4417"}, [started("str_replace_editor"), done("str_replace_editor")], {})
    assert not all(x["ok"] for x in read) and any(x["check"] == "tool browser_exec succeeded" and not x["ok"] for x in read)
    # live 2026-10-12: the browser call failed, SYRAX read the HTML with python and worked the code out;
    # a failed call is not use, so that run must not pass
    failed = [started("browser_exec"), done("browser_exec", ok=False), started("python_execute"), done("python_execute")]
    assert not all(x["ok"] for x in check_case(c, {"status": "SUCCESS", "result": "SYR-4417"}, failed, {}))
    wrong = check_case(c, {"status": "SUCCESS", "result": "loading"}, [started("browser_exec"), done("browser_exec")], {})
    assert not all(x["ok"] for x in wrong)

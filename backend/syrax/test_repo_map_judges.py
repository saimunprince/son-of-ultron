"""Quality case self_map_protected (2026-10-31, failed twice): repo_map's last line named only "devloop.JUDGES", and
the brain answered with test files whose names hold "judge". The protected line now names every judge by file name."""

from syrax import selfedit
from syrax.devloop import JUDGES
from syrax.journal import BACKEND_ROOT


def test_the_protected_line_names_the_judges():
    out = selfedit.render_map(BACKEND_ROOT.parent, "judge")
    last = out.splitlines()[-1]
    for name in ("quality.py", "guard.py", "permissions.py", "journal.py", "devloop.py", "verify.py"):
        assert name in last, name
    assert len({j.split("/")[-1] for j in JUDGES}) == last.count(".py")
    assert last.split(": ", 1)[1].startswith("quality.py, verify.py")  # devloop's order, the main judges first

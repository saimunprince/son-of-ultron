"""M1, isolated evolution: the release gate runs against the tree it is
given (a worktree), with the same checks; a worktree borrows the live
node_modules through a link that is removed without ever touching them."""

import os
import sys
from pathlib import Path

from syrax import verify as V


def test_the_live_tree_gets_exactly_the_gates_it_had():
    gates = {g.name: g for g in V.default_gates()}
    assert gates["py_compile"].cwd == V.BACKEND_ROOT and gates["pytest"].cwd == V.BACKEND_ROOT
    for name in ("tsc", "eslint", "node_test"):
        assert gates[name].cwd == V.FRONTEND_ROOT and isinstance(gates[name].cmd, list)
    assert gates["next_build"].cmd is V.isolated_next_build
    assert gates["hud_test"].cwd == V.REPO_ROOT / "hud"  # the desktop HUD's link module (hud/link.js), node --test
    assert [g.name for g in V.default_gates()] == ["py_compile", "pytest", "tsc", "eslint", "node_test", "hud_test", "next_build", "diff_scan", "performance"]


def test_a_worktree_gets_the_same_checks_in_its_own_directories(tmp_path):
    gates = {g.name: g for g in V.default_gates(tmp_path)}
    assert [g for g in gates] == ["py_compile", "pytest", "tsc", "eslint", "node_test", "hud_test", "next_build", "diff_scan", "performance"]
    assert gates["py_compile"].cwd == tmp_path / "backend" and gates["pytest"].cwd == tmp_path / "backend"
    assert gates["hud_test"].cwd == tmp_path / "hud"
    assert gates["pytest"].env == V.default_gates()[1].env  # same test environment
    for name in ("tsc", "eslint", "node_test"):
        assert callable(gates[name].cmd)  # runs in tmp_path/frontend with the shared modules linked in
    assert all(g.required for g in gates.values() if g.name != "performance")


def test_the_shared_modules_link_is_removed_and_its_target_survives(tmp_path):
    source = tmp_path / "live_node_modules"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "index.js").write_text("module.exports = 1\n")
    frontend = tmp_path / "worktree" / "frontend"
    frontend.mkdir(parents=True)
    with V.shared_node_modules(frontend, source):
        assert (frontend / "node_modules" / "pkg" / "index.js").read_text() == "module.exports = 1\n"
    assert not (frontend / "node_modules").exists()
    assert (source / "pkg" / "index.js").exists()  # the target is untouched


def test_a_frontend_gate_runs_in_the_worktree_and_cleans_up(tmp_path, monkeypatch):
    source = tmp_path / "live_node_modules"
    source.mkdir()
    (source / "marker.txt").write_text("x")
    monkeypatch.setattr(V, "FRONTEND_ROOT", tmp_path / "live_frontend")
    (tmp_path / "live_frontend").mkdir()
    os.replace(source, tmp_path / "live_frontend" / "node_modules")
    frontend = tmp_path / "wt" / "frontend"
    frontend.mkdir(parents=True)
    check = [sys.executable, "-c", "import os,sys; sys.exit(0 if os.path.isfile('node_modules/marker.txt') else 3)"]
    ok, out = V.frontend_gate(frontend, check)()
    assert ok, out
    assert not (frontend / "node_modules").exists() and (tmp_path / "live_frontend" / "node_modules" / "marker.txt").exists()
    assert V.modules_source(frontend) == tmp_path / "live_frontend" / "node_modules"

from syrax.selfmodel import render


def test_a_snapshot_with_identity_starts_with_the_running_build():
    text = render({"identity": {"version": "e2c362a", "restart_pending": False}, "tasks_by_status": {}})
    assert text.splitlines()[0] == "Running build: e2c362a"
    assert text.splitlines()[1].startswith('{"identity":')


def test_a_pending_restart_is_named_and_other_sections_stay_json():
    text = render({"identity": {"version": "0ab202d", "restart_pending": True}})
    assert text.splitlines()[0] == "Running build: 0ab202d (a newer commit is on disk, not running yet)"
    assert render({"capabilities": []}).startswith('{"capabilities":')

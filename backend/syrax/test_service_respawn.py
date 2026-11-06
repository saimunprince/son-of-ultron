"""Live 2026-11-06: SYRAX saw new code on disk and restarted itself from inside the login service; the detached
restarter died with the service's cgroup and SYRAX stayed down. Inside its own systemd unit, systemd restarts it;
anywhere else (an editor or terminal with an INVOCATION_ID of its own) nothing is asked of systemd."""

import sys

import pytest

from syrax.test_service_path import launcher

linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="systemd is Linux")


class Ran:
    def __init__(self, unit_id="abc", code=0):
        self.calls, self.unit_id, self.code = [], unit_id, code

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        out = self.unit_id if "show" in argv else ""
        return type("R", (), {"returncode": self.code, "stdout": out})()


@linux
def test_inside_its_own_unit_systemd_restarts_it():
    ran = Ran()
    assert launcher().systemd_service_restart({"INVOCATION_ID": "abc"}, runner=ran) is True
    assert ran.calls[-1] == ["systemctl", "--user", "restart", "--no-block", "syrax.service"]


@linux
def test_another_units_id_never_restarts_the_service():
    ran = Ran(unit_id="the-service")
    assert launcher().systemd_service_restart({"INVOCATION_ID": "vscode"}, runner=ran) is False
    assert not any("restart" in c for c in ran.calls)


def test_outside_systemd_nothing_is_asked():
    ran = Ran()
    assert launcher().systemd_service_restart({}, runner=ran) is False and ran.calls == []


@linux
def test_a_refused_systemctl_falls_back_to_the_detached_restart():
    assert launcher().systemd_service_restart({"INVOCATION_ID": "abc"}, runner=Ran(code=1)) is False

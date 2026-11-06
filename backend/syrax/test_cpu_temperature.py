"""Live 2026-11-06: asked for the CPU temperature, the brain read acpitz (a fixed 16.8 C board value) while the CPU's
own sensor (k10temp) read 44 C. system_info now names the CPU sensor."""

from syrax import sysinfo

READ = [{"sensor": "acpitz", "c": 16.8, "crit": None}, {"sensor": "nvme", "c": 31.9, "crit": 79.8},
        {"sensor": "k10temp", "c": 43.1, "crit": None}]


def test_the_cpu_sensor_is_picked_not_the_board():
    assert sysinfo.cpu_temperature(READ)["sensor"] == "k10temp"
    line = sysinfo.temperatures_line(READ)
    assert line.startswith("Temperatures: CPU 43.1 C (k10temp)") and "acpitz 16.8 C (board, not the CPU)" in line


def test_no_cpu_sensor_is_said_plainly():
    assert sysinfo.cpu_temperature([READ[0]]) is None
    assert sysinfo.temperatures_line([]) == "Temperatures: CPU: no CPU sensor readable here"


def test_intel_counts_too():
    assert sysinfo.cpu_temperature([{"sensor": "coretemp", "c": 55.0, "crit": 100.0}])["c"] == 55.0

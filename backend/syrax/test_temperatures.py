"""EVOLUTION_PLAN direction 218 (hardware fault detection): SYRAX warned about memory, disk, battery and load, but not
heat. Linux exposes every temperature sensor in /sys/class/hwmon without root; the snapshot carries them, and a sensor
near its own critical temperature, or a processor at 90 °C, raises an alert after three readings in a row."""

from syrax import alerts, sysinfo


def hwmon(tmp_path, name, milli, crit=None):
    d = tmp_path / f"hwmon{len(list(tmp_path.iterdir()))}"
    d.mkdir()
    (d / "name").write_text(name + "\n")
    (d / "temp1_input").write_text(f"{milli}\n")
    if crit is not None:
        (d / "temp1_crit").write_text(f"{crit}\n")


def test_sensors_are_read_in_celsius(tmp_path):
    hwmon(tmp_path, "k10temp", 42500)
    hwmon(tmp_path, "nvme", 29850, 79850)
    assert sysinfo.temperatures(str(tmp_path)) == [{"sensor": "k10temp", "c": 42.5, "crit": None},
                                                   {"sensor": "nvme", "c": 29.9, "crit": 79.8}]


def test_heat_is_raised_after_three_hot_readings_only():
    cool = {"temperatures": [{"sensor": "k10temp", "c": 55.0, "crit": None}, {"sensor": "nvme", "c": 40.0, "crit": 80.0}]}
    hot = {"temperatures": [{"sensor": "k10temp", "c": 93.0, "crit": None}]}
    near = {"temperatures": [{"sensor": "nvme", "c": 76.0, "crit": 80.0}]}
    assert alerts.hot(cool) is None and "93" in alerts.hot(hot) and "close to its critical 80" in alerts.hot(near)
    w = alerts.Watch()
    raised = [w.check(hot, 1000.0 + i) for i in range(3)]
    assert raised[0] == raised[1] == [] and raised[2][0]["kind"] == "heat"


def test_the_live_sensors_on_this_machine_read_without_root():
    for t in sysinfo.temperatures():  # whatever this machine has; none on a machine without hwmon
        assert isinstance(t["c"], float) and t["sensor"]

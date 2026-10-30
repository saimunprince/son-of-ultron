"""EVOLUTION_PLAN direction 279 (capacity planning): the disk alert fired only at under 2 GB free. The free space of
each day is now kept, and a least-squares trend that reaches zero within 14 days raises a disk_trend alert, once a day."""

from syrax import capacity
from syrax.journal import Journal

DAY = 86400.0
T0 = 1_800_000_000.0


def test_the_trend_gives_days_until_full():
    shrinking = [(T0 + i * DAY, 50.0 - 5 * i) for i in range(4)]  # 50, 45, 40, 35 GB: 5 GB a day
    assert capacity.days_until_full(shrinking) == 7.0
    assert capacity.days_until_full([(T0 + i * DAY, 40.0 + i) for i in range(4)]) is None  # growing free space
    assert capacity.days_until_full(shrinking[:2]) is None  # too few days to tell


def test_one_reading_a_day_is_kept_and_the_alert_comes_once_a_day(tmp_path):
    j = Journal(tmp_path / "j.db")
    assert capacity.check(j, 50.0, T0) is None
    assert capacity.check(j, 49.0, T0 + 3600) is None and len(capacity.history(j)) == 1  # same day: not kept again
    assert capacity.check(j, 45.0, T0 + DAY) is None  # two days: no trend yet
    alert = capacity.check(j, 40.0, T0 + 2 * DAY)
    assert alert["kind"] == "disk_trend" and "about 8 days" in alert["detail"]
    assert capacity.check(j, 39.0, T0 + 2 * DAY + 60) is None  # once a day

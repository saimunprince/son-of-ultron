import asyncio
import time

from syrax import stallwatch
from syrax.journal import Journal


def test_a_machine_sleep_is_not_a_stall(tmp_path):
    j = Journal(tmp_path / "j.db")

    async def main():
        w = stallwatch.Watchdog(asyncio.get_running_loop(), j, check_s=0.05, stall_s=0.5, log_dir=tmp_path / "logs")
        w.sleep_gap_s = 0.3
        real_wait, calls = w._stop.wait, []

        def wait(timeout):
            calls.append(timeout)
            if len(calls) == 4:
                time.sleep(1.0)  # the watchdog thread is frozen like the rest of the machine
            return real_wait(timeout)

        w._stop.wait = wait
        w.start()
        await asyncio.sleep(0.12)
        time.sleep(1.3)  # the event loop is frozen too, and wakes a little after the watchdog
        await asyncio.sleep(0.6)
        w.stop()

    asyncio.run(main())
    assert not (tmp_path / "logs").exists() and j.events_of_type("stall.recovered") == []

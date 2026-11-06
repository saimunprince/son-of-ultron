# Test plan for a second computer

For a coding agent (Claude Code or another) on a computer other than the main Linux PC, mostly the owner's
Windows 11 PC. When the owner says "test SYRAX", "test koro" or similar, follow these steps. The owner does not
need to say more.

## Steps

1. **Update.** Stop SYRAX if it runs (`python syrax.py --stop`), then `git pull --ff-only`. If the pull fails
   because of local changes, report it and stop: never reset or discard the owner's changes.
2. **Run.** `python syrax.py --testhere` (`py` instead of `python` if needed). It installs what is missing, runs
   the host check (safe desktop actions) and the full release gate, and writes one report to
   `docs/hostchecks/<os>-<desktop>-<display>-<date>.md`. It takes 10 to 20 minutes.
   - Keep the screen unlocked: a locked screen gives a black screenshot.
   - Add `hands` (`python syrax.py --testhere hands`) only when the owner is at the computer: it presses Shift once.
3. **Explain.** For every failing test and every MISMATCH row, find the cause in the code and add it to the report
   under `## Causes`, one item each: the test, what happens, and the fix you suggest (file and change). Do not
   edit SYRAX's code here: the fixes are made on the main PC, so the two computers never fight over the same files.
4. **The round's own checks.** Do what "This round" below asks and add the results under `## This round`.
5. **Send it back.** Commit only `docs/hostchecks/`, with a message like `hostcheck: <system> on <commit>`, then
   `git push`. If the push is refused, `git pull --rebase` once and push again.
6. **Tell the owner** in two or three lines: GREEN or BLOCKED, how many failures, and that the report is pushed.

## Rules

- Never commit secrets: `backend/config/` stays out of git, and so does any key or token you see.
- Never run the quality suite or anything that sends many brain requests: the free brain quota is shared with the
  main PC.
- Never start SYRAX as a service or change the owner's environment variables; only report what is set.

## This round

Updated on the main PC with every push that needs a check here. Last update: 2026-11-06 (52ca844 and later).

- The gate on 1a9cfff had 3 failures (`test_open_takes_a_file_url`, `test_a_correction_that_changed_a_named_file_stands`,
  `test_tests_never_reach_the_real_portal`); ce7bf97 fixed them. Confirm the gate is now GREEN on Windows.
- New since then, check they pass here: `test_hostcheck.py`, `test_sign_off.py`, `test_banglish.py`,
  `test_cpu_temperature.py`, `test_invented_paths.py`.
- `system_info` now has a `Temperatures:` line. On Windows there are no hwmon sensors, so it should read
  "CPU: no CPU sensor readable here". Run `python -c "from syrax import sysinfo; print(sysinfo.temperatures_line())"`
  from `backend` with the venv python and report the line.

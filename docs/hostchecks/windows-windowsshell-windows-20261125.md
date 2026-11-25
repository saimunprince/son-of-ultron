# Host check: Windows 11 (build 10.0.26300)

- When: 2026-11-25 17:20
- System: Windows 11 (build 10.0.26300), kernel 11, AMD64
- Desktop: Windows shell on windows
- Helper programs found: python3
- Python: 3.12.10
- Result: ALL AS PREDICTED

| Action | Predicted | Result | Detail |
|---|---|---|---|
| system_info | yes | OK |  |
| list_apps | yes | OK |  |
| volume | yes | OK |  |
| media | yes | OK |  |
| notify | yes | OK |  |
| dark_mode | yes | OK |  |
| window | yes | OK |  |
| find_text | yes | OK |  |
| phone | no: adb is not installed | NO (as predicted) | adb is not installed on this computer (Ubuntu: sudo apt install adb). |
| screenshot | yes | OK |  |
| clipboard | yes | OK |  |
| open | yes | NOT TRIED | not tried: opens a window |
| launch_app | yes | NOT TRIED | not tried: starts an app |
| type_text | yes | NOT TRIED | not tried: types into the window in front |
| click | yes | NOT TRIED | not tried: clicks the mouse |
| click_text | yes | NOT TRIED | not tried: clicks the mouse |
| lock_screen | yes | NOT TRIED | not tried: locks the screen |
| display_off | yes | NOT TRIED | not tried: turns the display off |
| trash | yes | NOT TRIED | not tried: moves a file to the trash |
| view_video | no: ffmpeg is not installed | NOT TRIED | not tried: needs a video file |
| hotkey | yes | NOT TRIED | not tried (add: --hostcheck hands) |
| camera | yes | NOT TRIED | not tried (add: --hostcheck camera) |

A MISMATCH means hostprofile.py predicted one thing and the action did the other.

## Release gate

- Result: BLOCKED on bc86d98

| Gate | Result | Seconds |
|---|---|---|
| py_compile | PASS | 6 |
| pytest | FAIL | 1195 |
| tsc | PASS | 31 |
| eslint | PASS | 29 |
| node_test | PASS | 2 |
| hud_test | PASS | 1 |
| next_build | PASS | 41 |
| diff_scan | PASS | 0 |
| performance (optional) | PASS | 14 |

Failing tests:

- `FAILED syrax/test_pasted_text.py::test_the_brain_is_told_where_the_long_message_is`

## Causes

- `test_pasted_text.py::test_the_brain_is_told_where_the_long_message_is`: the code works on Windows. `save_pasted` builds the path with `os.path.join`, so the note reads `...\pasted\t1.txt`, and the system message does carry "THE HUMAN'S MESSAGE is long". The test asserts `"/pasted/" in systems[0]`, which only matches POSIX separators. Suggested fix (test only): assert `os.sep + "pasted" + os.sep in systems[0]`, or normalise with `.replace("\\", "/")` before the check.

## This round

- Gate on bc86d98: BLOCKED by the one test above. Every other pytest test passed, and so did all the other gates. The 3 failures from 1a9cfff (`test_open_takes_a_file_url`, `test_a_correction_that_changed_a_named_file_stands`, `test_tests_never_reach_the_real_portal`) pass now.
- `test_hostcheck.py`, `test_sign_off.py`, `test_banglish.py`, `test_cpu_temperature.py` and `test_invented_paths.py` were run in the full gate and pass.
- `sysinfo.temperatures_line()` prints `Temperatures: CPU: no CPU sensor readable here`, as expected.
- Host check: ALL AS PREDICTED (clipboard OK).
- Environment, reported only and not changed: `SYRAX_ALLOWED_ORIGINS`, `SYRAX_UI_PORT=3001` and `SYRAX_OLLAMA_URL` are set for the user.

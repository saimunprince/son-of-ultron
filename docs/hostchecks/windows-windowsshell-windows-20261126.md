# Host check: Windows 11 (build 10.0.26300)

- When: 2026-11-26 12:09
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

- Result: GREEN on 0824def

| Gate | Result | Seconds |
|---|---|---|
| py_compile | PASS | 1 |
| pytest | PASS | 1146 |
| tsc | PASS | 17 |
| eslint | PASS | 26 |
| node_test | PASS | 1 |
| hud_test | PASS | 1 |
| next_build | PASS | 30 |
| diff_scan | PASS | 0 |
| performance (optional) | PASS | 5 |

## This round

- Gate on 0824def: GREEN. `test_pasted_text.py` passes now.
- `test_paths_note.py`, `test_gpu_fallback.py`, `test_review_whole.py`, `test_phone_playing.py` and `test_brains.py::test_fit_request_clips_the_task_request_last` were run in the full gate and pass.
- `sysinfo.gpu()` returns `{'name': 'AMD Radeon(TM) Graphics', 'memory_total_mb': 512, 'memory_used_mb': None, 'utilization_pct': None}`, so the GPU is named through PowerShell.
- Host check: ALL AS PREDICTED.

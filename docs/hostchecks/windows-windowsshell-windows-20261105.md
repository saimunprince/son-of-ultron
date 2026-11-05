# Host check: Windows 11 (build 10.0.26300)

- When: 2026-11-05 16:10
- System: Windows 11 (build 10.0.26300), kernel 11, AMD64
- Desktop: Windows shell on windows
- Helper programs found: python3
- Python: 3.12.10
- Result: 1 MISMATCH

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
| clipboard | yes | MISMATCH | Set-Clipboard : Requested Clipboard operation did not succeed. At line:1 char:107 + ... = [System.Text.Encoding]::UTF8; Set-Clipboard -Value $env:SYRAX_CLIP + ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ + Ca |
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

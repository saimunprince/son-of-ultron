# Host check: Ubuntu 26.04.1 LTS

- When: 2026-11-05 15:54
- System: Ubuntu 26.04.1 LTS, kernel 7.0.0-42-generic, x86_64
- Desktop: GNOME on wayland
- Helper programs found: adb, amixer, ffmpeg, ffprobe, gdbus, gsettings, gtk-launch, loginctl, notify-send, playerctl, python3, tesseract, wl-copy, wl-paste, wpctl, xdg-open, xsel
- Python: 3.12.16
- Result: ALL AS PREDICTED

| Action | Predicted | Result | Detail |
|---|---|---|---|
| system_info | yes | OK |  |
| list_apps | yes | OK |  |
| volume | yes | OK |  |
| media | yes | OK |  |
| notify | yes | OK |  |
| dark_mode | yes | OK |  |
| window | no: Wayland lets no program list or move other windows | NO (as predicted) | Window control is not possible on this Linux desktop (Wayland lets no program list, focus or move other windows); do not try it again. Use launch_app or open to bring an app up, and screenshot to see  |
| find_text | no: reading controls on the screen is built for Windows only | NO (as predicted) | find_text: keyboard, mouse, theme and display control are Windows-only for now |
| phone | yes | OK | adb works; no phone is connected |
| screenshot | yes | OK |  |
| clipboard | yes | OK |  |
| open | yes | NOT TRIED | not tried: opens a window |
| launch_app | yes | NOT TRIED | not tried: starts an app |
| type_text | yes | NOT TRIED | not tried: types into the window in front |
| click | yes | NOT TRIED | not tried: clicks the mouse |
| click_text | no: reading controls on the screen is built for Windows only | NOT TRIED | not tried: clicks the mouse |
| lock_screen | yes | NOT TRIED | not tried: locks the screen |
| display_off | no: built for Windows only | NOT TRIED | not tried: turns the display off |
| trash | yes | NOT TRIED | not tried: moves a file to the trash |
| view_video | yes | NOT TRIED | not tried: needs a video file |
| hotkey | yes | NOT TRIED | not tried (add: --hostcheck hands) |
| camera | yes | NOT TRIED | not tried (add: --hostcheck camera) |

A MISMATCH means hostprofile.py predicted one thing and the action did the other.

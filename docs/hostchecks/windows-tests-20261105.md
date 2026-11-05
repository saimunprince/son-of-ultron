# Windows test run: Windows 11 desktop, 2026-11-05

- Code: main d91aeb0, run in a clean worktree
- Python 3.12.10, backend venv
- Gate (`full_gate.py`): BLOCKED. pytest stopped at collection on `test_soak.py`. tsc, eslint, node_test, hud_test, next_build and diff_scan passed.
- pytest without `test_soak.py`, every `SYRAX_*` variable removed (as the gate does): 13 failed, all other tests passed.
- Every failing test is new since e584485 (2026-10-27). Every older test passes on Windows.

## Linux-only tests that need a skip on Windows

| Test | Why it fails on Windows |
|---|---|
| test_soak.py (collection) | `import resource`: the module does not exist on Windows |
| test_linux_input.py, 2 tests | the Linux portal is missing (WinError 2); the token file mode is 0o666, the test expects 0o600 |
| test_net_boundary.py::test_a_human_request_keeps_the_network | the subprocess probe is refused; the test expects the network to stay open |
| test_browser_confined.py::test_the_data_cap_still_refuses_a_real_allocation_past_it | there is no RLIMIT_DATA, so the allocation is not refused |
| test_service_path.py::test_the_service_path_keeps_the_shell_path_and_the_system_folders | PATH is split on `:`, so `C:\...` becomes `C` |

## Windows bugs

| Test | What happens |
|---|---|
| test_quality_fixes_1101.py::test_open_takes_a_file_url | desktop `open` refuses `file:///C:/.../page%20one.html` as "not a URL, an existing path or an installed app" |
| test_change_proof.py::test_paths_named_in_a_request_are_watched | a Windows path named in the request is not watched (returns `[]`) |
| test_change_proof.py::test_a_correction_that_changed_a_named_file_stands | follows from the bug above: the real change is not seen, so the claim is rewritten as "Nothing was changed" |
| test_undo_volume_theme.py::test_a_trashed_file_names_untrash_and_untrash_puts_it_back | untrash returns None on Windows (TypeError: 'NoneType' object is not subscriptable) |
| test_quality_run_fixes.py, 2 tests | the edited file keeps CRLF line endings; the tests look for `\n` |

## Test problems

| Test | What happens |
|---|---|
| test_hostprofile.py::test_this_computer_is_read_and_self_inspect_shows_it | the temp `j.db` is still open when the test cleans up (WinError 32) |
| test_read_boundary.py::test_the_sealed_folder_is_left_out_of_what_own_code_may_read | expects the worktree's `backend/syrax` in the list, but the list holds the live repository's paths |

## Running the tests on Windows

A user-level `SYRAX_ALLOWED_ORIGINS` (set when the UI moved to :3001) makes about 290 websocket tests fail with "origin http://localhost:3000 not allowed". Run pytest with every `SYRAX_*` variable removed, as the gate does.

## Host check notes

- Clipboard: Set-Clipboard fails some of the time ("Requested Clipboard operation did not succeed"). 2 of 3 direct calls failed while another program was syncing the clipboard, and a second host check passed. A short retry on Windows clipboard writes would cover it.
- Camera: this computer has no webcam (DSHOW and MSMF both fail to open device 0). The host check's camera row was a MISMATCH for another reason: the journal is owned by the running SYRAX, so a second process cannot journal the photo. The check should either skip journaling or say why it failed.
- Shift press (`--hostcheck hands`): OK.

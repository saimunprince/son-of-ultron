# Host checks

One report per kind of computer: which of SYRAX's desktop actions really work there, against what
`backend/syrax/hostprofile.py` predicts. A MISMATCH row is a bug to fix in `hostprofile.py` or `desktop.py`.
Reports keep no private data (no clipboard text, window titles, app names or pictures; the home folder is `~`).

## Run it on a new computer

Windows (PowerShell), Linux or macOS (terminal):

    git clone https://github.com/saimunprince/son-of-ultron.git     # or: git pull, in an existing copy
    cd son-of-ultron
    python syrax.py --setup              # first time only: venv, Python deps, npm, config
    python syrax.py --hostcheck          # safe: reads, one notification, one screenshot, clipboard put back
    python syrax.py --hostcheck hands camera   # also presses Shift once and takes one webcam photo

On Windows use `py` if `python` is not found. Stay logged in with the screen unlocked while it runs: a locked
screen gives a black screenshot. Then send the report back:

    git add docs/hostchecks
    git commit -m "hostcheck: <this computer>"
    git push

For the whole picture, `python syrax.py --testhere` runs the host check and the release gate together, in one
report. A coding agent on that computer follows [TEST_PLAN.md](TEST_PLAN.md).

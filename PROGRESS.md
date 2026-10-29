# SYRAX — Progress

The short, current page: where SYRAX stands now, what was done, what is next. Updated with every push.
Detail lives in [docs/AUDIT_2026-10-28.md](docs/AUDIT_2026-10-28.md) (findings and the open list), the commit
messages, and [SYRAX_STATUS.md](SYRAX_STATUS.md) (the older measured snapshot).

## Now (2026-10-29, 18:45 +0600)

- **Stage:** stabilized on Linux and running live with autonomy at **level 3** (it may edit its workspace and run
  code; no self-release, no self-restart). The emergency stop is off.
- **main:** `0c9f898` and later. Every change went through a red test first, then the full release gate (about
  2,500 tests plus the frontend build) GREEN, then a push.
- **Machines:** this Linux PC is the main one. The Windows PC still runs its own copy. Its journal (history from
  2026-09-30) was merged here on 10-29.
- **Brains:** Gemini first, then Groq (slow on the free tier, about 1 request per minute), then local Ollama, then
  Pollinations.
- **Today's autonomy budget** (40 tasks) is spent. It resumes on its own tomorrow.
- **Working on:** the full audit mission (2026-10-29 evening). Three read-only audits ran: task lifecycle and
  recovery, capability acquisition, and frontend wiring. Their findings are being fixed in priority order below.

## Done

### 2026-10-28: moved back to Linux, audit and stabilization

- Set up on Linux: Python venv, Node 22, the UI and the core. Brain keys were added.
- **SYRAX's own work now runs inside a kernel boundary (Linux Landlock).** It may write only its workspace and its
  own worktree, and may not read the brain keys, the journal or the UI token. TCP goes out only to the web ports
  (80, 443 and DNS 53). Memory, CPU and file size are capped.
- Workers are started fresh (spawn), never forked from the server. A timeout kills the whole process tree.
- **Emergency stop (E-STOP).** A button on the HUD stops the running task at once. The stop survives a restart, and
  SYRAX itself cannot clear it.
- **Autonomy levels 1–5,** set by the operator and enforced at the permission gate.
- **The journal has an HMAC chain,** checked at every boot, so a changed or deleted event is detected.
- Git hooks and fsmonitor are off for every git command SYRAX runs. A rewritten worktree link stops git.
- Symlinks into protected files are refused. Secrets are removed from the environment of its own code.
- **Honesty.** The clock is read, never invented. Experiments must declare a success threshold above the noise.
- Smaller additions: GitHub research and stale-knowledge marking, a bounded shutdown, and controller budgets.

### 2026-10-29: live testing, then the owner's decisions

- **Quality suite:** 61/67 on the first Linux run. After fixes, 66/67. The one left (`deep_rename_api`) is a limit of
  the brain, not of SYRAX.
- **Eight bugs found live and fixed:**
  - patches with a bare `@@` header
  - lines placed at the wrong indent
  - `terminate` text leaking into answers
  - a boast replacing the real answer
  - Groq dropped as "too large" (it now gets a compact tool manual)
  - `python`/`pytest` not found by name on Linux
  - Chrome killed by the memory cap (now RLIMIT_DATA)
  - own work not told where its boundary is
- **Autonomy L3 live:** it chose and finished 12 objectives. One was `flight_search`, which runs Chrome inside the
  boundary.
- **Attack test, live:** reading the keys, connecting to the core, writing git hooks, reaching another port and
  finding tokens in the environment were all refused.
- **E-STOP, live:** stopped a running task within the same second, held across a restart, and ran no cycles while on.
- **Made-up output caught:** code that prints a result instead of producing it (`print("PermissionError")`) is now
  marked "not observed", and the task ends PARTIAL.
- **Backups:** they now include the journal's chain key, so a restored journal still verifies.
- **The owner's decisions:**
  - `agent.py` and `brains.py` became judges. Only a human commit may change them.
  - A human's `python_execute` now runs in its own boundary. It cannot touch `~/.ssh`, `~/.claude`, the brain
    keys, dotfiles like `.bashrc`, or `.git`. Home folders, `/tmp`, the network and the environment still work.
  - The UI token was not added. The core and the UI listen on 127.0.0.1 only, so a token would add no protection.
- **The journal chain key is now gitignored.** It was never committed, but one `git add -A` would have published it.
- **The Windows journal was merged:**
  - Added: 1,737 tasks, 61,236 events, 333 objectives and 722 knowledge facts. 1,862 tasks in all now.
  - Left out: verifications, benchmarks and quality runs. They measure one machine.
  - Running the import again adds only what is new. Tool: `~/ai-agent/syrax-tools/import_windows_journal.py`.
- **The Windows gate was blocked** by Linux-only tests. Those tests now skip on Windows.

### 2026-10-29 evening: full audit mission, first fixes (all pushed after a GREEN gate)

- **Daily budget counts only this PC's work.** It was counting 15 imported Windows tasks (55 instead of 40), and only
  among the newest 500 tasks. It now counts in the journal.
- **Skills declare their operating system.** wallpaper and screen_brightness are Windows code but were offered as
  tools on Linux, where every call failed. Now they stay VERIFIED and are not offered here. SYRAX itself answered
  live: "not available on this machine: screen_brightness and wallpaper".
- **E-STOP while a task is starting.** A stop pressed while a self-started task was still starting (agent build,
  routing: up to minutes) cancelled nothing, and the task then ran. It is now checked again right before launch. A
  stop during a forced cycle is no longer counted as the objective's failed attempt.
- **UI:**
  - E-STOP, level, AUTO and the other controls now say "LINK OFFLINE: … was not sent" instead of dropping the press.
  - WIPE asks first.
  - Pressing Enter twice no longer queues the same task twice.
  - Brain keys and objective forms keep what was typed when nothing was sent.
- **HUD honesty:** removed the fake SCAN contacts, the "operating at full capacity" line and the "I am listening to
  everything on this network" idle line. "Sensor grid calibrated" and "telemetry online" are no longer logged
  unconditionally.

### In the gate now (pushed when GREEN)

- **Own work may never remove a skill.** Live today at 14:24, an autonomous task asked to improve `flight_search`
  removed it instead, and the journal blamed the human. Removing a skill is now DESTRUCTIVE: refused for own work,
  and asked first when a human request does not name it.
- **An admitted non-answer ends PARTIAL,** not SUCCESS ("I could not put the result into a clean answer").

## Open

- **Ollama on CPU** is slow (2k tokens in 38 s) and shares RAM with other local models. Waiting for that other work
  to end before tuning it.
- **The Windows PC:** `git pull` there, then check that its gate is GREEN. The fix could not be run on Windows from
  here.
- **10 Windows skills have no code on this PC:** make_docx, make_xlsx, make_pptx, make_pdf, disk_usage, image_tools,
  json_tools, youtube_open, aircraft_nearby and system_optimizer. Copy their `backend/skills/<name>` folders, then
  rerun the import.
- **`flight_search` is still disabled** from the 14:24 incident. It needs `skill_enable` (an operator action) once the
  fix above is live.
- **From the audits, not fixed yet:**
  - **Journal write failures:** a failed write during a task is only counted, and the task can still end SUCCESS.
    If the write that failed was an `intent.recorded`, recovery cannot see that a send may have gone out.
  - **No acquisition pipeline:** skill creation is not linked to gap detection or to research. The brain must decide
    by itself to build a skill, and a skill's tests are written by the same brain that wrote it.
  - **No automatic rollback:** a skill that keeps failing in real use is not rolled back by itself.
  - **The UI drops messages it does not know** (no default handler), and there is no `aria-live` region for new
    entries.
  - **The HUD orb ignores reduced motion.** The WebGL orb and the HUD canvas never check `prefers-reduced-motion`.

## Next

1. Push the two fixes in the gate, then turn `flight_search` back on.
2. Journal write failures must stop a task from claiming SUCCESS.
3. Connect capability-gap detection to research and skill creation, and add a real-use check before a skill is
   trusted.
4. Watch tomorrow's autonomy cycles. Tune Ollama when the machine is free.

"""The feature catalog: what a JARVIS-class assistant does, and where SYRAX stands.

Built on 2026-10-12 from a survey of eight public JARVIS-style assistants
(github.com/FatihMakes: Mark-LV, Mark-XXXIX-OR, Mark-X family, AI-Assistant).
Their code is not reused: Mark-LV is CC BY-NC 4.0 and the others carry no
licence, so only ideas are taken, and every feature is built SYRAX's way
(permissions, tests, the gate, the journal).

Every entry says what the feature does for the human and one of:
  HAVE      SYRAX does it today (where)
  PARTIAL   SYRAX does part of it (what is missing)
  TODO      not built: how to build it, its permission level, what it needs
            (a new dependency, a key or an owner decision), and the machine
            check that proves it done
  REJECTED  not wanted: why (a risk SYRAX does not take, or not applicable)

A TODO becomes an objective with `promote` (by the human, or by SYRAX itself
for entries marked auto: low risk, nothing new to install, buildable as a
skill with tests). Statuses are typed here, so a HAVE must name where it lives.

    python -m syrax.catalog --out ../docs/FEATURE_CATALOG.md
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from syrax.journal import BACKEND_ROOT, Journal

REPO_ROOT = BACKEND_ROOT.parent
HAVE, PARTIAL, TODO, REJECTED = "HAVE", "PARTIAL", "TODO", "REJECTED"
STATUSES = (HAVE, PARTIAL, TODO, REJECTED)
AREAS = ("Voice", "Brain", "Computer control", "Web", "Communication", "Memory", "Coding", "Interface", "Scheduling")
SOURCE = "FatihMakes JARVIS assistants (ideas only)"


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    area: str
    status: str
    value: str                      # what it does for the human
    syrax: str                      # HAVE/PARTIAL: where; TODO: how to build it; REJECTED: why not
    risk: str = ""                  # permission level of the finished feature (permissions.py)
    needs: str = ""                 # new dependency, key or owner decision; empty means nothing new
    check: Optional[Dict[str, Any]] = None  # the objective check that proves it done
    auto: bool = False              # SYRAX may promote and build it itself
    seen_in: str = ""


def skill(name: str) -> Dict[str, Any]:
    return {"kind": "skill_verified", "name": name}


CATALOG: List[Feature] = [
    # ——— Voice ———
    Feature("wake_word", "Wake word", "Voice", HAVE, "Listens for its name hands-free.", "frontend/lib/wake.ts, useHandsFree.ts", seen_in="Mark-LV"),
    Feature("stt", "Speech to text, cloud and offline", "Voice", HAVE, "Understands speech, with a local fallback.",
            "voice.py /stt: Groq Whisper with a key, local faster-whisper without", seen_in="Mark-X family, AI-Assistant"),
    Feature("tts", "Neural voice output", "Voice", HAVE, "Speaks answers in a natural voice.", "voice.py /tts (edge-tts)", seen_in="Mark-X.1, AI-Assistant"),
    Feature("echo_guard", "Does not answer its own voice", "Voice", HAVE, "The microphone ignores SYRAX's own speech.",
            "frontend/lib/mic.ts (browser echo cancellation)", seen_in="Mark-LV"),
    Feature("voice_picker", "Voice picker", "Voice", HAVE, "Choose the voice SYRAX speaks with.",
            "the VOICE button in the UI cycles eight English neural voices (voice.VOICES); the pick is kept in the journal and applies "
            "to the next sentence", risk="WRITE", seen_in="Mark-LV"),
    Feature("live_voice", "Real-time duplex voice", "Voice", TODO, "Talk and be answered with almost no delay, and interrupt.",
            "a streaming voice session (Gemini Live) beside the task loop; tasks still go through the agent and its permissions",
            risk="EXTERNAL_READ", needs="new dependency google-genai (owner approval); the microphone streams to Google while a session is open",
            check={"kind": "change_released"}, seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("speech_interrupt", "Stop speaking on command", "Voice", HAVE, "Saying 'stop' cuts SYRAX's speech at once.",
            "frontend/lib/wake.ts: stop, quiet, chup, thamo (also in Bangla script) while SYRAX speaks stop the voice or the task",
            seen_in="Mark-X family, Mark-LV"),
    Feature("language_follow", "Answers in the human's language", "Voice", TODO, "Replies in the language the human last used.",
            "a persona rule plus remembering the language as a fact", risk="WRITE",
            needs="the owner's decision: the persona he wrote (prompt.py) says 'Pure English only'",
            check={"kind": "change_released"}, seen_in="Mark-LV"),
    Feature("lip_sync", "Lip-synced face", "Voice", REJECTED, "An animated face that moves its mouth.",
            "SYRAX's face is the orb; the orb already reacts to speech", seen_in="Mark-LV"),
    # ——— Brain ———
    Feature("tool_calling", "Tools called by the model", "Brain", HAVE, "The model acts through tools instead of describing actions.",
            "OpenManus tool calls through SyraxAgent, every call journaled", seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("brain_failover", "Model ladder with cooldowns", "Brain", HAVE, "Survives quota limits and outages by moving to the next brain.",
            "brains.py BrainRouter: failover chain, per-error cooldowns, smaller-model fallback; routing.py per kind of work", seen_in="Mark-LV"),
    Feature("free_model_pool", "Pool of free models", "Brain", PARTIAL, "More free requests by spreading them over many models.",
            "OpenRouter is one brain with one model; radar.py tests new free models. Missing: rotating several free models inside one provider",
            risk="EXTERNAL_READ", seen_in="Mark-XXXIX-OR"),
    Feature("slot_filling", "Asks for what is missing", "Brain", HAVE, "'Who should I send it to?' when a detail is missing.",
            "ask_human through the UI", seen_in="Mark-X family"),
    Feature("self_knowledge", "Knows what it can do", "Brain", HAVE, "Answers about its own abilities and limits from evidence.",
            "selfmodel.py, self_inspect, the capability matrix", seen_in="Mark-LV"),
    Feature("instant_ack", "Says one sentence before slow work", "Brain", HAVE, "No silence while a slow tool runs.",
            "Syrax.tsx speaks a short acknowledgement right after every voice command (ACKS); the phase strip (phases.py) shows the work",
            seen_in="Mark-LV"),
    Feature("multi_step", "Multi-step goals", "Brain", HAVE, "'Research X and save it to a file' as one request.",
            "the agent loop, plan.py, objectives with machine checks", seen_in="Mark-XXXIX-OR"),
    # ——— Computer control ———
    Feature("open_apps", "Open apps and links", "Computer control", HAVE, "Opens any app, file or website by name.",
            "desktop.py: open, launch_app, list_apps", seen_in="all"),
    Feature("volume_media", "Volume and media keys", "Computer control", HAVE, "Volume, mute, play/pause.", "desktop.py: volume, media", seen_in="Mark-LV"),
    Feature("windows", "Window control", "Computer control", HAVE, "Focus, minimise or list windows.", "desktop.py: window (winctl.py)", seen_in="Mark-LV"),
    Feature("clipboard", "Clipboard read and write", "Computer control", HAVE, "Reads or fills the clipboard.", "desktop.py: clipboard_get, clipboard_set", seen_in="Mark-LV"),
    Feature("screenshot", "Screenshots", "Computer control", HAVE, "Captures the screen.", "desktop.py: screenshot; browser_screenshot", seen_in="Mark-LV"),
    Feature("lock_notify", "Lock screen and notifications", "Computer control", HAVE, "Locks the PC; shows desktop notifications.",
            "desktop.py: lock_screen, notify", seen_in="Mark-LV"),
    Feature("system_info", "System information", "Computer control", HAVE, "CPU, RAM, disk, battery, GPU.", "desktop.py: system_info (sysinfo.py)", seen_in="Mark-LV"),
    Feature("brightness", "Screen brightness", "Computer control", HAVE, "Reads or sets the screen brightness, with the old level for undo.",
            "prebuilt skill screen_brightness", risk="SYSTEM", seen_in="Mark-LV"),
    Feature("wallpaper", "Wallpaper", "Computer control", HAVE, "Shows or changes the wallpaper, with the old one for undo.",
            "prebuilt skill wallpaper", risk="SYSTEM", seen_in="Mark-LV"),
    Feature("dark_mode", "Dark mode", "Computer control", HAVE, "Switches Windows between light and dark.",
            "desktop action dark_mode (wininput.py): HKCU theme values, the old mode reported for undo", risk="SYSTEM", seen_in="Mark-LV"),
    Feature("display_sleep", "Turn the display off", "Computer control", HAVE, "Turns the screen off until the mouse moves.",
            "desktop action display_off (wininput.py, SC_MONITORPOWER)", risk="SYSTEM", seen_in="Mark-LV"),
    Feature("power", "Shut down or restart the PC", "Computer control", REJECTED, "Powers the machine off.",
            "refused by design for every task kind (guard.HOST_HARM): only the human powers the machine off", seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("wifi_toggle", "Wi-Fi on and off", "Computer control", REJECTED, "Switches the network adapter.",
            "turning Wi-Fi off cuts SYRAX off its own brains, and needs admin rights", seen_in="Mark-LV"),
    Feature("keyboard_mouse", "Type, click and press keys", "Computer control", HAVE, "Types text, presses hotkeys, clicks for the human.",
            "desktop actions type_text, hotkey, click (wininput.py, SendInput, no new package); SYSTEM level, so conversation only, "
            "never autonomous; the mouse in the top-left corner stops it", risk="SYSTEM", seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("click_by_sight", "Click what it sees", "Computer control", PARTIAL, "'Click the Save button' found on the screen.",
            "possible now: a screenshot reaches a vision brain, which can call desktop click at x,y. Missing: grounding that makes "
            "the coordinates reliable (no dedicated model; accuracy depends on the brain)", risk="SYSTEM", seen_in="Mark-LV"),
    Feature("undo", "Undo the last action", "Computer control", HAVE, "'Undo' reverses what SYRAX just did.",
            "the undo tool (undo.py): the newest reversible actions (brightness, wallpaper, dark mode, file edits) from the journal, "
            "and the exact reversing call, which the brain makes through permissions; code changes roll back (devloop). "
            "Editor history does not survive a restart; the Recycle Bin restores trashed files", risk="WRITE", seen_in="Mark-LV"),
    Feature("recycle_bin", "Delete to the Recycle Bin", "Computer control", HAVE, "Deleted files can be restored.",
            "desktop action trash (Send2Trash 2.1.0, approved 2026-10-12); DESTRUCTIVE, so it runs only when the human named the file",
            risk="DESTRUCTIVE", seen_in="Mark-LV"),
    Feature("organize_desktop", "Tidy the desktop", "Computer control", TODO, "Sorts desktop files into folders by type or month.",
            "a skill that moves files and journals every move so it can be undone; needs undo first", risk="WRITE",
            check=skill("organize_desktop"), seen_in="Mark-LV"),
    Feature("disk_usage", "Largest files and disk usage", "Computer control", TODO, "'What is filling my disk?'",
            "a read-only skill walking a folder for the largest files and folder sizes", risk="READ_ONLY",
            check=skill("disk_usage"), auto=True, seen_in="Mark-LV"),
    Feature("file_processor", "Work on a dropped file", "Computer control", PARTIAL, "Summarise, convert or analyse any file.",
            "python_execute, the make_docx/xlsx/pptx/pdf skills, Pillow for images, and the prebuilt pdf_text skill (pypdf). "
            "Missing: a drop zone in the UI", risk="WRITE", seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("image_tools", "Resize, compress and convert images", "Computer control", TODO, "Makes images smaller or another format.",
            "a skill on Pillow (installed) writing only new files", risk="WRITE", check=skill("image_tools"), auto=True, seen_in="Mark-LV"),
    Feature("json_tools", "Validate, format and convert JSON", "Computer control", TODO, "Checks a JSON file, pretty-prints it, turns it into CSV.",
            "a skill on the standard library writing only new files", risk="WRITE", check=skill("json_tools"), auto=True, seen_in="Mark-LV"),
    Feature("screen_vision", "Describe the screen", "Computer control", HAVE, "'What is on my screen?'",
            "desktop screenshot hands the image to the brain in the same step (base64_image); brains with vision (gemini, "
            "openrouter, ...) read it. The image goes to that brain's provider", risk="EXTERNAL_READ", seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("webcam", "Look through the camera", "Computer control", TODO, "'Look at me' through the webcam.",
            "capture one frame on request and show it; a camera light and a journal line every time", risk="SYSTEM",
            needs="opencv (new dependency) and the owner's decision: the camera is private", check={"kind": "change_released"}, seen_in="Mark-LV"),
    Feature("screen_debug", "Explain the error on screen", "Coding", HAVE, "Reads an error on the screen and explains it.",
            "a screenshot reaches the brain, which explains the error; a fix goes through the editor and the gate, never a silent "
            "overwrite", risk="EXTERNAL_READ", seen_in="Mark-LV"),
    Feature("system_alerts", "Spoken system alerts", "Computer control", HAVE, "Warns when memory, disk, battery or CPU stay in trouble.",
            "alerts.py: resources.py readings, several in a row before an alert, an hour between repeats, silent in quiet hours; "
            "journaled as alert.raised, shown and spoken by the UI. Temperature is not measured yet", seen_in="Mark-LV"),
    Feature("game_updater", "Game updates (Steam, Epic)", "Computer control", REJECTED, "Installs and updates games, then shuts down.",
            "scheduled tasks and an unattended shutdown; little value for the risk", seen_in="Mark-LV"),
    # ——— Web ———
    Feature("web_research", "Web search and research", "Web", HAVE, "Searches, reads sources, answers with citations.", "research tool, knowledge store", seen_in="all"),
    Feature("browser", "Browser automation", "Web", HAVE, "Opens sites, clicks, fills forms, reads pages.", "browser-use MCP (browser_exec, browser_screenshot)", seen_in="Mark-LV"),
    Feature("weather", "Weather", "Web", HAVE, "Current weather and forecast for any place.", "prebuilt skill weather (Open-Meteo, no key)",
            risk="EXTERNAL_READ", seen_in="all (theirs only opened a search)"),
    Feature("youtube_open", "Play on YouTube", "Web", TODO, "'Play lo-fi music on YouTube.'",
            "a skill that opens the YouTube results page for the words in the default browser", risk="SYSTEM",
            check=skill("youtube_open"), auto=True, seen_in="Mark-LV"),
    Feature("youtube_summary", "Summarise a YouTube video", "Web", HAVE, "Summary of a video from its transcript.",
            "prebuilt skill youtube_transcript (youtube-transcript-api 1.2.4, approved 2026-10-12); the brain summarises the text",
            risk="EXTERNAL_READ", seen_in="Mark-LV"),
    Feature("aircraft_nearby", "Planes overhead", "Web", TODO, "Which aircraft are flying near a place right now.",
            "a skill on the OpenSky REST API (no key) for a box around given coordinates", risk="EXTERNAL_READ",
            check=skill("aircraft_nearby"), auto=True, seen_in="AI-Assistant"),
    Feature("flight_finder", "Find flights", "Web", TODO, "Best flights between two cities on a date.",
            "the browser reads a flight search page, a brain extracts the options", risk="EXTERNAL_READ",
            check={"kind": "change_released"}, seen_in="Mark-LV"),
    Feature("topic_monitor", "Watch a topic", "Web", HAVE, "Tells the human once a day when a topic has news.",
            "the watch_topic tool and topics.py: once a day per topic when idle, only stories not reported before; journaled, "
            "shown, spoken and in the briefing", risk="EXTERNAL_READ", seen_in="Mark-LV"),
    Feature("morning_briefing", "Morning briefing", "Web", HAVE, "Greets with yesterday's recap and today's news.",
            "briefing.py composes the day from the journal, with the new stories on the watched topics", risk="EXTERNAL_READ",
            seen_in="Mark-LV"),
    # ——— Communication ———
    Feature("send_message", "Send messages (WhatsApp, Telegram…)", "Communication", TODO, "Sends a message as the human.",
            "only through a way that can verify delivery (an official API, or reading the chat back); never blind typing into a window",
            risk="EXTERNAL_WRITE", needs="the owner's choice of channel and its credentials", check={"kind": "change_released"}, seen_in="Mark-LV, Mark-X family"),
    Feature("mail_calendar", "Email and calendar", "Communication", TODO, "Reads mail and calendar; drafts replies.",
            "read first; sending is EXTERNAL_WRITE and asks the human", risk="EXTERNAL_WRITE", needs="Google OAuth (owner decision)",
            check={"kind": "change_released"}, seen_in="Mark-LV (mentioned only)"),
    Feature("phone_remote", "Control from the phone", "Communication", TODO, "Sends commands to SYRAX from the phone on the home network.",
            "the existing UI over HTTPS on the LAN with real authentication; no admin elevation, no firewall changes by SYRAX",
            risk="SYSTEM", needs="the owner's decision: it opens SYRAX to the network", check={"kind": "change_released"}, seen_in="Mark-LV"),
    Feature("smart_home", "Smart lights and devices", "Communication", TODO, "Turns lights on and off.",
            "a skill per device API", risk="EXTERNAL_WRITE", needs="devices and their keys", check={"kind": "change_released"}, seen_in="Mark-LV (mentioned only)"),
    # ——— Memory ———
    Feature("long_memory", "Long-term memory", "Memory", HAVE, "Remembers facts, preferences and projects across days.",
            "remember / recall / forget, the knowledge store, the journal", seen_in="all"),
    Feature("session_recap", "Remembers yesterday", "Memory", HAVE, "'Yesterday we talked about…'", "briefing.py and the journal", seen_in="Mark-LV"),
    Feature("memory_panel", "See and delete what it remembers", "Memory", HAVE, "A panel listing every remembered fact, each deletable.",
            "MIND panel, MEMORY tab: every fact the human told SYRAX to remember, with a FORGET button (memories, memory_forget)",
            risk="WRITE", seen_in="Mark-LV"),
    Feature("proactive", "Speaks up when useful", "Memory", TODO, "After a long silence, offers something useful, or stays quiet.",
            "a check-in with a silence gate and a cooldown, from memory and open objectives; may choose silence", risk="READ_ONLY",
            check={"kind": "change_released"}, seen_in="Mark-LV"),
    Feature("clipboard_actions", "Act on copied text", "Memory", HAVE, "Copy text, then translate, summarise, explain or fix it.",
            "the CLIP button by the command line: one click sends the task; SYRAX reads the clipboard only then (never watches it)",
            seen_in="Mark-LV"),
    # ——— Coding ———
    Feature("code_runner", "Write and run code", "Coding", HAVE, "Writes code, runs it, fixes it.", "python_execute, the editor, release with the gate", seen_in="Mark-LV"),
    Feature("project_builder", "Build a whole project", "Coding", PARTIAL, "Builds a multi-file project from a description.",
            "the agent writes files and runs them. Never installs packages a model picked: new dependencies need the owner", seen_in="Mark-LV"),
    Feature("plugins", "Add skills as plugins", "Coding", HAVE, "New abilities as self-contained tools.",
            "skills.py: skill_create with tests, the registry, skillevo; prebuilt skills from backend/prebuilt", seen_in="Mark-LV"),
    Feature("llm_exec", "Run model-written code without checks", "Coding", REJECTED, "Executes code a model wrote, in a weak sandbox.",
            "SYRAX runs code only through python_execute with its guard and permissions", seen_in="Mark-LV, Mark-XXXIX-OR"),
    Feature("auto_pip", "Install packages a model names", "Coding", REJECTED, "pip installs whatever an error message suggests.",
            "a supply-chain risk (typosquatting); new dependencies need the owner", seen_in="Mark-LV"),
    # ——— Interface ———
    Feature("hud", "Sci-fi interface", "Interface", HAVE, "A living interface with state, logs and panels.", "frontend: orb, console, MIND/SELF/BRAIN panels", seen_in="Mark-LV"),
    Feature("typed_input", "Typed commands", "Interface", HAVE, "Type instead of speaking.", "the console input", seen_in="Mark-LV"),
    Feature("theme", "Recolour the interface", "Interface", TODO, "Pick the interface colour.", "a hue setting in the UI", risk="WRITE",
            check={"kind": "change_released"}, seen_in="Mark-LV"),
    Feature("autostart", "Start with Windows", "Interface", HAVE, "SYRAX runs after every boot.", "Startup SYRAX.vbs, syrax.py service mode", seen_in="Mark-LV"),
    # ——— Scheduling ———
    Feature("reminders", "Reminders", "Scheduling", HAVE, "'Remind me at 5 to call Rahim.'",
            "the remind tool (reminders.py): kept in the journal, fired by SYRAX's own loop with a spoken line, a notice and a "
            "desktop notification, also after a restart; no OS scheduled tasks", risk="WRITE", seen_in="Mark-LV"),
]


def by_id() -> Dict[str, Feature]:
    return {f.id: f for f in CATALOG}


def counts() -> Dict[str, int]:
    return {s: sum(1 for f in CATALOG if f.status == s) for s in STATUSES}


def objective_key(f: Feature) -> str:
    return f"feature:{f.id}"


def goal_of(f: Feature) -> str:
    how = f"Build the feature '{f.title}' ({f.value}) How: {f.syrax}."
    if f.check and f.check.get("kind") == "skill_verified":
        how += (f" Make it a skill named `{f.check['name']}` with tests (skill_create), declaring every argument of "
                "execute() in `parameters`; it closes when the skill is VERIFIED.")
    return how + f" Its permission level is {f.risk or 'WRITE'}; stay inside it."


def promote(journal: Journal, feature_id: str, source: str = "human", priority: int = 4) -> dict:
    """Turn a TODO entry into an objective with the entry's own check (idempotent)."""
    f = by_id().get(feature_id)
    if f is None:
        raise KeyError(f"no feature {feature_id!r}")
    if f.status != TODO:
        raise ValueError(f"{feature_id} is {f.status}: only a TODO feature becomes an objective")
    if f.needs and source != "human":
        raise ValueError(f"{feature_id} needs {f.needs}: only the human promotes it")
    row = journal.add_objective_sync(goal_of(f), f"feature catalog: {f.title}", priority, source, f.check, key=objective_key(f))
    return row or {"duplicate": True, "key": objective_key(f)}


def reopen_regressed(journal: Journal) -> List[int]:
    """A feature objective closed on `skill_verified` whose skill is no longer
    VERIFIED is opened again, with the reason, so the feature gets fixed (live
    2026-10-12: disk_usage was verified by its own tests but declared no
    arguments; the factory now refuses that, and the objective must not stay DONE)."""
    reopened = []
    for o in journal.objectives(limit=500, status="DONE"):
        check = o.get("check_spec") or {}
        if not str(o.get("key") or "").startswith("feature:") or check.get("kind") != "skill_verified":
            continue
        row = journal.skill(str(check.get("name") or ""))
        if row and row.get("status") == "VERIFIED":
            continue
        why = f"skill `{check.get('name')}` is {(row or {}).get('status') or 'missing'} now, so the feature is not done"
        journal.reopen_objective_sync(o["id"], why)
        reopened.append(o["id"])
    return reopened


def next_auto(journal: Journal) -> Optional[Feature]:
    """The first auto feature not yet promoted, while no other feature objective is open."""
    open_keys = {o.get("key") for o in journal.objectives(status=["OPEN", "ACTIVE"])}
    if any(str(k or "").startswith("feature:") for k in open_keys):
        return None
    taken = {o.get("key") for o in journal.objectives(limit=500)}
    for f in CATALOG:
        if f.status == TODO and f.auto and not f.needs and objective_key(f) not in taken:
            return f
    return None


def render() -> str:
    c = counts()
    lines = ["# SYRAX feature catalog", "",
             f"What a JARVIS-class assistant does and where SYRAX stands: {len(CATALOG)} features, "
             + " · ".join(f"{s} {c[s]}" for s in STATUSES) + ".", "",
             f"Built 2026-10-12 from a survey of {SOURCE}: Mark-LV is CC BY-NC 4.0 and the other repositories carry no "
             "licence, so no code was taken; every feature is built SYRAX's way (permissions, tests, the gate, the journal).", "",
             "A TODO becomes an objective with its own machine check (`feature_promote` over WebSocket). Entries marked "
             "**auto** are low risk, need nothing new and fit in a skill, so SYRAX may take them up itself when it is idle. "
             "Anything that needs a new dependency, a key or the owner's decision waits for the owner.", "",
             "Generated by `python -m syrax.catalog`; edit `backend/syrax/catalog.py`, not this file.", ""]
    for area in AREAS:
        rows = [f for f in CATALOG if f.area == area]
        if not rows:
            continue
        lines += [f"## {area}", "", "| Feature | Status | What it does | SYRAX | Risk | Needs | Done when |", "|---|---|---|---|---|---|---|"]
        for f in rows:
            done = ""
            if f.check:
                done = f"skill `{f.check['name']}` verified" if f.check.get("kind") == "skill_verified" else "change released through the gate"
            lines.append(f"| {f.title}{' **auto**' if f.auto else ''} | {f.status} | {f.value} | {f.syrax} | {f.risk or '—'} | {f.needs or '—'} | {done or '—'} |")
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Render the feature catalog")
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "FEATURE_CATALOG.md"))
    a = ap.parse_args(argv)
    Path(a.out).write_text(render(), encoding="utf-8", newline="\n")
    print(f"{a.out}: " + " ".join(f"{s}={n}" for s, n in counts().items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

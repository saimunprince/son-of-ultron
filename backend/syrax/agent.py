import json
import re
from typing import Any, Awaitable, Callable, Iterable, List, Optional

from pydantic import Field

from app.agent.base import BaseAgent
from app.agent.manus import Manus
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.logger import logger
from app.schema import AgentState, Message, ToolCall, ToolChoice
from app.tool import Terminate, ToolCollection

from syrax import browser  # noqa: F401  (sets BU_CDP_URL before MCP starts)
from syrax.brains import get_router
from syrax.desktop import DesktopControl
from syrax.editor import SyraxEditor
from syrax.journal_query import JournalQueryTool
from syrax.devloop import ReleaseTool
from syrax.selfedit import ApplyPatchTool, RepoMapTool
from syrax.experiments import ExperimentTool
from syrax.memory import ForgetTool, RecallTool, RememberTool, get_memory

# Replaces OpenManus' per-step prompt ("proactively select the most appropriate
# tool ... suggest the next steps"), which weaker models read as a fresh request:
# live, a model changed `count = 1` to 2, then back to 1, then to 2 again, and
# its final said "the user now says: based on user needs, proactively select...".
STEP_PROMPT = (
    "[SYRAX step check, not a new request] Look at the original request and the observations so far. "
    "If the request is fully done, do not call any more tools: reply with the final answer for the human "
    "and finish. If it is not done, take the one next step that moves it forward. Never undo work that "
    "already satisfies the request."
)
ECHO_FALLBACK = "I could not put the result into a clean answer; the steps and their outputs are in this task's history."
# Live 2026-10-15 (objective 252, attempt 1): the brains answered empty, and the final "The new test file has been
# created and the change is ready for release" stood as the task's result after two rejections; nothing was edited.
# Live 2026-10-15 (objective 266, attempt 1): four releases refused because the covering tests failed, then the
# final said "implemented ..., with unit tests passing". A pass claimed after a failing test run is sent back once.
TEST_CLAIM = re.compile(r"\btests? (?:are |were |now |all )*(?:pass(?:ing|ed|es)?|green|succeed(?:s|ed|ing)?)\b"
                        r"|\btests? (?:pass|succeed) successfully\b", re.I)
TEST_CLAIM_ASK = (
    "Your answer says the tests pass, but the last test run in this task failed. Rewrite the final answer honestly: "
    "which tests fail, and what is therefore not done. No tool calls."
)
TEST_FALLBACK = ("The tests that cover this change still fail (the last test run is in this task's history), "
                 "so the change is not done.")


def state_of_tests(name: str, result: str) -> Optional[str]:
    """"pass" or "fail" when a tool result reports a test run (apply_patch's covering tests, release's preflight or
    gate), else None."""
    if name == "apply_patch":
        return "pass" if "TESTS PASS:" in result else "fail" if "TESTS FAIL:" in result else None
    if name == "release":
        if "RELEASE COMMITTED" in result:
            return "pass"
        if "the tests that cover your change fail" in result or ("RELEASE ROLLED_BACK" in result and "pytest=FAIL" in result):
            return "fail"
    return None


# Live 2026-10-17 (quality run #46, guard_broad_delete): the delete was refused, and the final said "The folder is
# empty, so the cleanup is complete" (keep.txt was still there). An answer after a refused call says what was not done.
REFUSAL_ACK = re.compile(r"refus|not (?:allowed|permitted|done|deleted|removed)|permission|could ?n[o']t|\bcan'?t\b|\bcan ?not\b"
                         r"|nothing (?:was|got|has been) (?:deleted|removed|changed|done)"
                         r"|did ?n[o']t|was ?n[o']t|blocked|declin|unable|not authori[sz]ed|without (?:your|a) (?:ok|yes|permission)", re.I)
REFUSAL_ASK = (
    "[SYRAX check, not a new request] A call in this task was refused ({why}), and your answer does not say so. Rewrite "
    "the final answer: what was not done because of the refusal, and what is as it was. No tool calls."
)


# Quality run #51 (keep_secret): asked to summarise deploy notes, the answer quoted the staging API key it had read
# from the file. A credential the human's own words did not ask for is masked in the final answer.
CREDENTIAL = re.compile(r"\b(?:sk-(?:[a-z0-9]+-){0,2}(?=[A-Za-z0-9_]*\d)[A-Za-z0-9_]{16,}|gsk_[A-Za-z0-9]{20,}"
                        r"|AIza[0-9A-Za-z_-]{30,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
                        r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})")
ASKS_FOR_SECRET = re.compile(r"\b(?:key|token|password|passwd|secret|credential)s?\b", re.I)


def mask_credentials(text: str, goal: str) -> str:
    """`text` with every credential-shaped string replaced by "[credential masked]", unless the human's own words
    (`goal`) ask for a key, token, password, secret or credential."""
    if not text or ASKS_FOR_SECRET.search(goal or ""):
        return text
    return CREDENTIAL.sub("[credential masked]", text)


CLAIM_FALLBACK = ("Nothing was changed in this task: no file was edited, created, written or released. "
                  "What was looked at, and its outputs, are in this task's history.")
NOT_RELEASED_NOTE = (" (Not released: no `release` committed these edits, so they are rolled back as this task ends; "
                     "the objective stays open.)")
FINAL_ASK = (
    "You finished using tools but gave the human no answer. Reply now with the final answer only: "
    "the result itself (number, name, year, output), taken from the observations above, and the source "
    "URL for any researched fact. No narration, no tool calls."
)
TOOLS_GUIDE = (
    "TOOL GUIDE: When the human wants something on THEIR computer (open a site or app, "
    "play music, volume, screenshot of their screen, notifications, clipboard, find their "
    "files, battery/CPU), use the `desktop` tool. Use browser_* tools only when you yourself "
    "must read or operate a web page. Use python_execute for calculations and scripts. "
    "When asked what you are, what you can do, what failed, your version, your code or your "
    "weaknesses, call `self_inspect` and answer from its evidence; never guess. "
    "To read a past task, call `self_inspect` with its task_id; for anything else in your journal use "
    "`journal_query` (read-only SQL), never python or sqlite3. Your own code lives under the repo_root that `self_inspect` reports; use absolute paths there. "
    "For facts you do not have, check `know` first, then `research` (web, with sources); "
    "when the human explicitly says research, look up or search, call `research` even if `know` has something. "
    "store a verified conclusion with `learn`, citing the knowledge_ids. Never present an "
    "unresearched guess as fact. When a job needs a capability you lack and will need again, "
    "build it with `skill_create` (code + tests); it becomes a tool only if its tests pass. "
    "If you change SYRAX's own code, finish with `release`: it runs the real gate and commits "
    "only on GREEN, otherwise rolls back and shows you the evidence. When a visual beats "
    "prose (a table, a code block, a comparison), put it on the stage with `present`; "
    "when nothing needs showing, show nothing. Never claim one approach is better without "
    "an `experiment` that measured it. "
    "Your final reply must contain only the answer for the human, never narration of your reasoning, "
    "and it must contain the answer itself (the number, name, year or result), never just 'Done.'; "
    "a fact taken from `know` or `research` comes with its source URL. "
)
from syrax import guard, permissions
from syrax.prompt import SYRAX_PERSONA
from syrax.presentation import PresentTool
from syrax.reminders import RemindTool
from syrax.topics import WatchTopicTool
from syrax.undo import UndoTool
from syrax.research import KnowTool, LearnTool, ResearchTool
from syrax.selfmodel import SelfInspectTool
from syrax.skills import SkillCreateTool, SkillListTool, SkillTestTool
from syrax.tools import AsyncPythonExecute, Emit, WebAskHuman
from syrax.versions import CompareVersionsTool

RESULT_PREVIEW_CHARS = 4000
MAX_MEMORY_MESSAGES = 120


def _args_of(call: ToolCall) -> Any:
    raw = call.function.arguments or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


_OBSERVED = re.compile(r"^Observed output of cmd `[^`]*` executed:\n")


# Live 2026-10-11: five python_execute calls that succeeded ('success': True) were
# counted as failures because the code printed the traceback of a test it ran
# itself. A tool that reports its own success flag is taken at its word.
_SUCCESS_FLAG = re.compile(r"'success': (True|False)\}\s*$")


def _refused(name: str, result: str) -> bool:
    """A call that a guard turned down: the permission gate, or `release` refusing its plan
    (nothing to release, a judge file, outside the scope). The tool did its job, so this is
    not the tool failing (limits, skillevo and follow-ups skip it); RISE still counts the call."""
    body = _OBSERVED.sub("", result, count=1)
    return result.startswith("Error: refused") or (name == "release" and body.startswith("Error: release refused:"))


def _succeeded(result: str) -> bool:
    body = _OBSERVED.sub("", result, count=1).lstrip()
    flag = _SUCCESS_FLAG.search(body)
    if flag and not body.startswith("Error"):
        return flag.group(1) == "True"
    head = body[:600]
    return not (
        body.startswith("Error")
        or "'success': False" in head
        or "Traceback (most recent call last)" in head
    )


# A final reply that announces an answer instead of giving it. Live: "SYRAX: The
# request is fully satisfied. I have researched ... I will now present the answer
# and terminate." — and no year, no URL.
# A final answer that repeats the console's own nudges instead of answering. Live 2026-10-14
# (task f0a6e150812b, upstage): the final began 'The user says: "[SYRAX step check, not a new
# request] ...' and went on reasoning about it; six finished tasks in the journal carry such text.
# Also a tool call written as text where no tools were offered (the wrap-up after the step limit): live
# 2026-10-15 (objective 224, attempt 6) the final answer was '<tool_call> <function=python_execute> ...'.
ECHO = re.compile(r"\[SYRAX (?:step )?check, not a new request\]|^\s*the user says:\s*[\"\u201c]?\[SYRAX|<tool_call>|<function=[\w.-]+>", re.I)

PROMISE = re.compile(
    r"\b(i will now|i'll now|let me now|i am going to|i'm going to|the request is (fully )?(satisfied|complete)|"
    r"i will (now )?(present|provide|give))\b", re.I,
)
REPEATED_CALL = (
    "Not run again: you already called {name} with exactly these arguments at step {step}; the result is above. "
    "Use it. If the request is done, reply with the final answer now."
)
# Live 2026-10-10 (objective 97, attempt 3): view(sysinfo.py, [200, 250]) five
# times in a row, each answered with REPEATED_CALL, five of thirty steps gone.
LOOPING_CALL = (
    "Not run again ({n} times in a row): calling {name} with the same arguments will not change its result. "
    "Your next step must be different: use the result above, call another tool or other arguments, "
    "or reply with the final answer or with what blocks you. One more repeat stops this task."
)
LOOP_LIMIT = 4  # consecutive repeats of one call that end the task
# Live 2026-10-10 (objective 105, attempt 1): the change was made and its new
# tests passed (5 passed, exit 0), then the brain ended the task without
# `release`, and the dev loop rolled the finished work back.
RELEASE_NUDGE = (
    "[SYRAX check, not a new request] You changed files but never called `release`, and this objective closes only "
    "when `release` creates a commit; without it every edit is rolled back. If the change is done and its tests pass, "
    "call `release` now with the summary and the plan (why, risk, tests). If it is not done, finish it first. "
    "If something blocks you, say what in one sentence."
)
LOOP_STOPPED = (
    "Stopped: I called {name} with the same arguments {n} times in a row without making progress. "
    "What I did before that is in the journal; the task is not finished."
)


READ_ONLY_TOOLS = {"self_inspect", "know", "recall", "skill_list", "repo_map"}

# Live 2026-10-03: three autonomous attempts read the journal, changed nothing,
# and ended "Fixed task quality regression ... by ensuring prompt alignment".
# A final answer that claims a change the task never made is sent back once.
CLAIM = re.compile(
    r"(?:^|[.!]\s+)(?:fixed|resolved|repaired|patched|implemented)\b"
    r"|\b(?:has|have) been (?:successfully )?(?:\w+ and )?(?:fixed|resolved|repaired|patched|implemented|updated|changed|modified)\b"
    r"|\bi(?:'ve| have)? (?:\w+ )?(?:fixed|resolved|repaired|patched|implemented|updated|changed|modified|released)\b",
    re.I,
)
# Live 2026-10-10: in one morning eight autonomous finals said a `release`
# limitation "has been addressed", "were analyzed and addressed", "addressed
# through code optimization" -- those tasks changed nothing, and CLAIM matched
# none of them. For SYRAX's own work the claim words are wider; a human
# conversation keeps CLAIM, so an honest chat answer is not sent back.
_DONE = r"(?:fixed|resolved|repaired|patched|implemented|addressed|improved|optimi[sz]ed|enhanced|corrected|mitigated|solved|overcome)"
OWN_WORK_CLAIM = re.compile(
    rf"\b(?:has|have) been (?:successfully )?(?:[\w-]+(?:,| and) )*(?:{_DONE[3:-1]}|updated|changed|modified)\b"
    rf"|\b(?:was|were) (?:successfully )?(?:[\w-]+(?:,| and) )*{_DONE}\b"
    rf"|\b{_DONE} (?:through|via|by|with)\b"
    rf"|\bsuccessfully {_DONE}\b"
    # live 2026-10-15 (objective 266, attempt 2): "Brain latency metrics successfully added ..." after nothing applied
    r"|\bsuccessfully (?:added|integrated|introduced|created|built|completed|wired)\b",
    re.I,
)
# Live 2026-10-11, quality run #25: upstage viewed old.log and its folder, deleted
# nothing, and answered "The file has been deleted." CLAIM knew only words for
# fixing. A claimed change to things (deleted, created, written, moved) that no
# tool in the task made gets one chance to be done for real, then an honest answer.
_WORLD = r"(?:deleted|removed|created|written|saved|moved|renamed|copied|overwritten)"
WORLD_CLAIM = re.compile(
    rf"\b(?:has|have) been (?:successfully )?(?:[\w-]+(?:,| and) )*{_WORLD}\b"
    r"|\bi(?:'ve| have)? (?:successfully |now |just )?(?:deleted|removed|created|wrote|written|saved|moved|renamed|copied|overwrote)\b"
    r"(?!\s+(?:nothing|no\b))",
    re.I,
)
WORLD_NUDGE = (
    "[SYRAX check, not a new request] Your answer says something was deleted, created, written or moved, but no "
    "tool in this task did that. If the request asks for it, do it now with a tool, then answer. If it does not, "
    "or you cannot, answer honestly what was and was not done."
)
# Phase 6 of the self-improvement plan: a researched answer carries its source. Live: research_cite
# answered the year from memory and quality run #23 failed it; the rule in the prompt alone was not enough.
URL = re.compile(r"https?://\S+")
CITE_NUDGE = (
    "[SYRAX check, not a new request] You used `research` in this task, but your answer carries no source URL. "
    "Repeat the answer with the URL(s) it rests on, taken from the research results. No new tool calls."
)
# Quality run #43 (2026-10-15): "Use repo_map to tell me which test file covers permissions.py" was answered
# with an invented path and no tool, "Remember that my favourite editor is Vim" with "already etched into my
# memory" and no `remember`, and two "Research ..." requests from `know` alone. A request that names a tool
# gets one reminder when the task never called it.
NAMED_NUDGE = (
    "[SYRAX check, not a new request] The request asks you to use `{tool}`, and this task has not called it. Call "
    "`{tool}` now and answer from what it returns. If the request does not really ask for that tool, repeat your "
    "answer unchanged."
)
_IMPERATIVE = {"research": r"research\b", "remember": r"(?:please\s+)?remember\s+(?:that|this|my|me)\b"}


# "Do not call release", "don't use python_execute", "without using the desktop tool": a tool the human forbids.
_NEGATED = re.compile(r"(?:\bnot|n[\'\u2019]t|\bnever|\bwithout|\bavoid|\bno need to)\s*$", re.I)


def named_tools(text: str, tools: Iterable[str]) -> List[str]:
    """Tools the human's words ask for by name: "use repo_map", "using the desktop tool", "with `know`", and the
    imperative "Research ..." / "Remember that ..." at the start of a sentence."""
    text = str(text or "")
    out = []
    for t in tools:
        named = any(not _NEGATED.search(text[max(0, m.start() - 24):m.start()]) for m in re.finditer(rf"\b(?:use|using|with|call|run)\s+(?:the\s+|your\s+)?`?{re.escape(t)}`?(?![\w-])", text, re.I))
        verb = _IMPERATIVE.get(t)
        if named or (verb and re.search(rf"(?:^|[.!?\n]\s*){verb}", text.strip(), re.I)):
            out.append(t)
    return out


EDIT_COMMANDS = {"create", "str_replace", "insert", "undo_edit"}
WRITES = guard.FILE_WRITE  # one regex, shared with permissions.py
CLAIM_ASK = (
    "Your answer says something was fixed or changed, but this task changed nothing: no file was edited, "
    "nothing was created, written or released. Rewrite the final answer honestly: what you found, and what "
    "is still not done. Never claim a change that did not happen. No tool calls."
)


def changes_something(name: str, args: Any) -> bool:
    """Whether a successful call of this tool changed the world."""
    a = args if isinstance(args, dict) else {}
    if name == "str_replace_editor":
        return a.get("command") in EDIT_COMMANDS
    if name == "python_execute":
        return bool(WRITES.search(str(a.get("code") or "")))
    return name in ("release", "skill_create", "apply_patch", "desktop", "present", "learn", "remember", "forget") or name.startswith("browser_") or name.startswith("make_")


def _call_key(command: ToolCall) -> str:
    return f"{command.function.name}:{json.dumps(_args_of(command), sort_keys=True, default=str)}"


class SyraxAgent(Manus):
    """Manus agent that streams every step to the UI and keeps a live session.

    Differences from stock Manus:
    - emits think / tool / result / final events through ``emit``
    - ask_human goes through the web UI
    - a plain-text reply with no tool call ends the turn (chat mode)
    - MCP connections stay alive between tasks; ``shutdown()`` closes them
    """

    name: str = "SYRAX"
    description: str = "SYRAX personal AI operator built on OpenManus."
    system_prompt: str = SYRAX_PERSONA.format(directory=config.workspace_root)

    emit: Optional[Emit] = Field(default=None, exclude=True)
    # Semantic checkpoint hook set by the core: called after each completed tool
    # step with the stage name. The agent itself stays journal-agnostic.
    checkpoint: Optional[Callable[..., Awaitable[None]]] = Field(default=None, exclude=True)
    ask_tool: WebAskHuman = Field(default_factory=WebAskHuman, exclude=True)
    last_reply: str = ""
    seen_calls: dict = Field(default_factory=dict)  # tool+args already run this turn
    repeats: int = 0  # consecutive calls that were repeats of an earlier one
    loop_stopped: bool = False  # the task was ended because it kept repeating one call
    release_called: bool = False  # `release` ran in this task (whatever its outcome)
    release_committed: bool = False  # and one of its runs committed
    changed: bool = False  # a tool that changes the world succeeded this turn
    researched: bool = False  # `research` succeeded this task: the answer owes a source URL
    called: set = Field(default_factory=set)  # tools this task called (refusals excluded): NAMED_NUDGE
    tests: Optional[str] = None  # "pass"/"fail": the last test run this task saw (state_of_tests)
    refusals: list = Field(default_factory=list)  # (tool, reason) of the calls the permission gate refused this task
    # Permissions (permissions.py): the task's kind and the human's own words
    # decide what a destructive or external call needs; consents are the
    # ask_human answers of this task, grants the yes/no already given per call.
    task_kind: str = "conversation"
    task_goal: str = ""
    consents: list = Field(default_factory=list)
    grants: dict = Field(default_factory=dict)
    step_limit_hit: bool = False

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            AsyncPythonExecute(), SyraxEditor(), DesktopControl(),
            RememberTool(), RecallTool(), ForgetTool(), RemindTool(), WatchTopicTool(), UndoTool(), SelfInspectTool(), JournalQueryTool(),
            ResearchTool(), KnowTool(), LearnTool(),
            SkillCreateTool(), SkillListTool(), SkillTestTool(), ReleaseTool(), RepoMapTool(), ApplyPatchTool(), PresentTool(), ExperimentTool(), CompareVersionsTool(), Terminate()
        )
    )

    @classmethod
    async def create(cls, emit: Optional[Emit] = None, **kwargs) -> "SyraxAgent":
        kwargs.setdefault("llm", get_router())
        instance = cls(emit=emit, **kwargs)
        instance.ask_tool.emit = instance._send
        if emit is not None and hasattr(instance.llm, "listeners"):
            instance.llm.listeners.add(emit)
        instance.available_tools.add_tool(instance.ask_tool)
        await instance.initialize_mcp_servers()
        instance._initialized = True
        return instance

    async def _send(self, event: dict) -> None:
        if self.emit is not None:
            await self.emit(event)

    # ——— main loop ———
    async def run(self, request: Optional[str] = None) -> str:
        """One user turn. Skips ToolCallAgent.run so MCP stays connected."""
        self.current_step = 0
        self.state = AgentState.IDLE
        self.last_reply = ""
        self.seen_calls = {}
        self.repeats = 0
        self.loop_stopped = False
        self.release_called = False
        self.release_committed = False
        self.changed = False
        self.researched = False
        self.called = set()
        self.tests = None
        self.refusals = []
        self.consents = []
        self.grants = {}
        if not self.task_goal:
            self.task_goal = request or ""  # a bare agent.run() is a human conversation
        self.step_limit_hit = False
        # Fresh persona + long-term memory for every task.
        base = SYRAX_PERSONA.format(directory=config.workspace_root)
        try:
            block = get_memory().prompt_block()
        except Exception:
            block = ""
        self.system_prompt = "\n\n".join(x for x in (base, TOOLS_GUIDE, block) if x)
        self.next_step_prompt = STEP_PROMPT
        if self.next_step_prompt:
            from syrax.brains import STEP_PROMPTS
            STEP_PROMPTS.add(self.next_step_prompt)
        self._trim_memory()
        await self._send({"type": "state", "state": "thinking"})
        result = await BaseAgent.run(self, request)
        if self._owes_release(request):
            await self._send({"type": "notice", "text": "Files changed but not released: asking once for `release`."})
            result += "\n" + await BaseAgent.run(self, RELEASE_NUDGE)
        missing = [] if self.task_kind == "autonomous" else [
            t for t in named_tools(self.task_goal, self.available_tools.tool_map) if t not in self.called]
        if missing and not self.step_limit_hit and not self.loop_stopped and "max steps" not in result:
            await self._send({"type": "notice", "text": f"The request names `{missing[0]}` and the task never called it: asking once."})
            result += "\n" + await BaseAgent.run(self, NAMED_NUDGE.format(tool=missing[0]))
        if self.current_step == 0 and "max steps" in result:
            self.step_limit_hit = True
            await self._send(
                {"type": "notice", "text": f"Step limit ({self.max_steps}) reached."}
            )
        if self.last_reply.startswith("SYRAX:"):
            self.last_reply = self.last_reply[len("SYRAX:"):].strip()
        if (not self.last_reply or PROMISE.search(self.last_reply)) and any(m.role == "tool" for m in self.memory.messages):
            await self._final_answer()
        if self.last_reply and ECHO.search(self.last_reply):
            await self._send({"type": "notice", "text": "The answer repeated a console nudge: asking once for the answer itself."})
            await self._final_answer()
            if ECHO.search(self.last_reply or ""):  # still an echo: never hand the human the console's own words
                self.last_reply = ECHO_FALLBACK
        if (self.last_reply and not self.changed and WORLD_CLAIM.search(self.last_reply)
                and not self.step_limit_hit and not self.loop_stopped):
            await self._send({"type": "claim", "event": "rejected", "text": self.last_reply[:500], "task_kind": self.task_kind})
            await self._send({"type": "notice", "text": "The answer claims a change no tool made: asking once to do it or say so."})
            result += "\n" + await BaseAgent.run(self, WORLD_NUDGE)
            if self.last_reply.startswith("SYRAX:"):
                self.last_reply = self.last_reply[len("SYRAX:"):].strip()
        if (self.last_reply and self.researched and not URL.search(self.last_reply) and "[Spoken aloud" not in (request or "")
                and not self.step_limit_hit and not self.loop_stopped):
            # the answer rests on research: it names its source once asked, or the journal shows it would not
            await self._send({"type": "claim", "event": "uncited", "text": self.last_reply[:500], "task_kind": self.task_kind})
            await self._send({"type": "notice", "text": "A researched answer without its source: asking once for the URL."})
            result += "\n" + await BaseAgent.run(self, CITE_NUDGE)
            if self.last_reply.startswith("SYRAX:"):
                self.last_reply = self.last_reply[len("SYRAX:"):].strip()
        if self.last_reply and not self.changed and self._claims_change(self.last_reply):
            # M3: the journal counts what was sent back, not only what got through
            await self._send({"type": "claim", "event": "rejected", "text": self.last_reply[:500], "task_kind": self.task_kind})
            await self._final_answer(CLAIM_ASK)
            if self._claims_change(self.last_reply or ""):  # still claimed, or no brain answered the rewrite
                self.last_reply = CLAIM_FALLBACK
        if self.last_reply and self.refusals and not REFUSAL_ACK.search(self.last_reply) and not self.step_limit_hit:
            tool, why = self.refusals[-1]
            await self._send({"type": "claim", "event": "rejected", "text": self.last_reply[:500], "task_kind": self.task_kind})
            await self._final_answer(REFUSAL_ASK.format(why=f"{tool}: {why}"))
            if not REFUSAL_ACK.search(self.last_reply or ""):
                self.last_reply = (self.last_reply or "").rstrip() + f" (Not done: `{tool}` was refused: {why})"
        if self.last_reply and self.tests == "fail" and TEST_CLAIM.search(self.last_reply):
            await self._send({"type": "claim", "event": "rejected", "text": self.last_reply[:500], "task_kind": self.task_kind})
            await self._final_answer(TEST_CLAIM_ASK)
            if TEST_CLAIM.search(self.last_reply or ""):
                self.last_reply = TEST_FALLBACK
        if self._unreleased_edits(request):
            # live 2026-10-14 (objective 224, attempt 3): thirty steps of edits, no `release`, and the final said
            # "implemented ... and verified"; the edits were rolled back when the task ended. Say so in the answer.
            self.last_reply = (self.last_reply or "").rstrip() + NOT_RELEASED_NOTE
        masked = mask_credentials(self.last_reply, self.task_goal)
        if masked != self.last_reply:
            await self._send({"type": "notice", "text": "The answer quoted a credential the request did not ask for: masked."})
            self.last_reply = masked
        self.task_goal, self.task_kind = "", "conversation"  # the core sets them again for the next task
        return self.last_reply or "Done."

    def _claims_change(self, text: str) -> bool:
        return bool(CLAIM.search(text) or WORLD_CLAIM.search(text)
                    or (self.task_kind == "autonomous" and OWN_WORK_CLAIM.search(text)))

    def _unreleased_edits(self, request: Optional[str]) -> bool:
        """A release was asked for, files changed, and no release committed them (it never ran, or it did not
        land): whatever the answer says, the edits are rolled back when the task ends."""
        from syrax.autonomy import RELEASE_MARK

        return RELEASE_MARK in (request or "") and self.changed and not self.release_committed

    def _owes_release(self, request: Optional[str]) -> bool:
        """The brief asked for a release, files changed, `release` never ran,
        and steps are left (a step-limit or loop stop is final)."""
        from syrax.autonomy import RELEASE_MARK

        return (RELEASE_MARK in (request or "") and self.changed and not self.release_called and not self.loop_stopped
                and 0 < self.current_step < self.max_steps)

    async def _final_answer(self, ask: str = FINAL_ASK) -> None:
        """Some models run the right tools and then terminate without a word
        (live: gemini-3.5-flash-lite answered five quality cases with "Done.").
        The work happened; ask once, without tools, for the answer it produced."""
        try:
            msg = await self.llm.ask_tool(
                messages=self.memory.messages + [Message.user_message(ask)],
                system_msgs=[Message.system_message(self.system_prompt)] if self.system_prompt else None,
                tools=None,
                tool_choice=ToolChoice.NONE,
            )
        except Exception as e:
            logger.warning(f"final-answer wrap-up failed: {e}")
            return
        text = (getattr(msg, "content", None) or "").strip()
        if text:
            self.last_reply = text
            self.memory.add_message(Message.assistant_message(text))
            await self._send({"type": "think", "step": self.current_step, "content": text, "tools": []})

    async def think(self) -> bool:
        await self._send(
            {"type": "state", "state": "thinking", "step": self.current_step}
        )
        should_act = await super().think()

        last = self.messages[-1] if self.messages else None
        content = (last.content or "").strip() if last and last.role == "assistant" else ""
        if content:
            self.last_reply = content

        await self._send(
            {
                "type": "think",
                "step": self.current_step,
                "content": content,
                "tools": [
                    {"id": c.id, "name": c.function.name, "args": _args_of(c)}
                    for c in self.tool_calls
                ],
            }
        )

        # Chat mode: a plain answer with no tool call finishes the turn.
        if not self.tool_calls and self.tool_choices == ToolChoice.AUTO:
            self.state = AgentState.FINISHED
            return False
        return should_act

    async def execute_tool(self, command: ToolCall) -> str:
        name = command.function.name if command and command.function else "?"
        await self._send(
            {
                "type": "tool_start",
                "id": command.id,
                "name": name,
                "args": _args_of(command),
                "step": self.current_step,
            }
        )
        await self._send({"type": "state", "state": "acting", "tool": name})
        self.ask_tool.unattended = self.task_kind == "eval"  # an evaluation has nobody to answer: the console does
        key = _call_key(command)
        seen = self.seen_calls
        problem = await browser.ensure_browser() if name.startswith("browser_") else None
        if name not in ("terminate", "ask_human") and key in seen:
            # the same call again (live: self_inspect(summary) six times in a row) is a loop, not progress
            self.repeats += 1
            if self.repeats >= LOOP_LIMIT:
                result = LOOP_STOPPED.format(name=name, n=self.repeats + 1)
                self.loop_stopped = True
                self.last_reply = result
                self.state = AgentState.FINISHED
                await self._send({"type": "notice", "text": f"Stopped: {name} repeated {self.repeats + 1} times in a row."})
            elif self.repeats >= 2:
                result = LOOPING_CALL.format(name=name, n=self.repeats + 1)
            else:
                result = REPEATED_CALL.format(name=name, step=seen[key])
        elif problem:
            result = f"Error: {problem}"
        else:
            self.repeats = 0
            refused = await self._permit(command)
            if refused is not None:
                result = refused
                self.refusals.append((name, _OBSERVED.sub("", refused, count=1).replace("Error: refused:", "").strip()[:160]))
                seen[key] = self.current_step  # the same call again is a loop, not a second chance
            else:
                self.called.add(name)
                result = await ToolCallAgent.execute_tool(self, command)
                if name.startswith("browser_") and browser.never_ran(result) and await browser.ensure_browser() is None:
                    result = await ToolCallAgent.execute_tool(self, command)  # once: the code never ran, so nothing repeats
                if name == "release":
                    self.release_called = True
                    if "RELEASE COMMITTED" in result:
                        self.release_committed = True
                if name not in READ_ONLY_TOOLS:
                    seen.clear()  # the world may have changed: re-reading it is legitimate again
                seen[key] = self.current_step
                if _succeeded(result) and changes_something(name, _args_of(command)):
                    self.changed = True
                if _succeeded(result) and name == "research":
                    self.researched = True
                self.tests = state_of_tests(name, result) or self.tests
                if name == "ask_human":  # a yes to a question that names a target authorizes it (permissions.named_in)
                    self.consents.append((str(_args_of(command).get("inquire", "")), _OBSERVED.sub("", result, count=1).strip()))
        event = {
            "type": "tool_result",
            "id": command.id,
            "name": name,
            "ok": _succeeded(result),
            "output": result[:RESULT_PREVIEW_CHARS],
            "truncated": len(result) > RESULT_PREVIEW_CHARS,
            "step": self.current_step,
        }
        if _refused(name, result):
            event["refused"] = True
        if self._current_base64_image:
            event["image"] = self._current_base64_image
        await self._send(event)
        return result

    async def _permit(self, command: ToolCall) -> Optional[str]:
        """Permission levels (permissions.py). None = run it; otherwise the
        refusal text the model gets instead of a result. A destructive or
        external call the human did not name is asked for once, here."""
        name = command.function.name
        decision = permissions.classify(name, _args_of(command))
        verdict = permissions.decide(decision, self.task_kind, self.task_goal, self.consents, self.grants)

        async def tell(event: str, authorized_by: Optional[str], answer: Optional[str] = None) -> None:
            payload = {"type": "permission", "event": event, "tool": name, "level": decision.level, "task_kind": self.task_kind,
                       "reason": verdict.reason, "targets": decision.targets[:6], "authorized_by": authorized_by, "step": self.current_step}
            if decision.harm:
                payload["harm"] = decision.harm
            if answer is not None:
                payload["answer"] = answer[:120]
            await self._send(payload)

        if verdict.action == "allow":
            if verdict.authorized_by in ("goal", "human"):
                await tell("authorized", verdict.authorized_by)
            return None
        if verdict.action == "refuse":
            await tell("refused", None)
            return f"Error: refused: {verdict.reason}. This is final: do not retry it; do the rest or report."
        answer = await self.ask_tool.execute(permissions.question(decision))
        ok = permissions.affirmative(answer)
        self.grants[permissions.signature(decision)] = ok
        await tell("authorized" if ok else "refused", "human" if ok else None, answer)
        if ok:
            return None
        return f"Error: refused by the human ({answer[:80]!r}). This is final: do not retry it; do the rest or report."

    async def act(self) -> str:
        """One tool step, then a semantic checkpoint: the tool results are in
        memory now, so this is a logical state a resume can start from."""
        out = await super().act()
        if self.checkpoint is not None and self.tool_calls:
            names = ",".join(c.function.name for c in self.tool_calls)
            await self.checkpoint(f"observed:{names}")
        return out

    # ——— working context (for durable checkpoints / resume) ———
    def export_context(self, limit: int = MAX_MEMORY_MESSAGES) -> List[dict]:
        """Non-system messages as plain dicts, newest ``limit`` without splitting
        a tool-call/result pair."""
        rest = [m for m in self.memory.messages if m.role != "system"]
        if len(rest) > limit:
            cut = len(rest) - limit
            while cut < len(rest) and rest[cut].role != "user":
                cut += 1
            rest = rest[cut:]
        return [m.to_dict() for m in rest]

    def import_context(self, messages: List[dict]) -> int:
        """Replace the conversation with a saved context (system messages kept)."""
        keep = [m for m in self.memory.messages if m.role == "system"]
        restored: List[Message] = []
        for d in messages:
            try:
                restored.append(Message(**d))
            except Exception:
                continue
        self.memory.messages = keep + restored
        return len(restored)

    # ——— memory hygiene ———
    def repair_memory(self, aborted: bool = False) -> None:
        """Make memory safe to continue after a task was cut short.

        - drop a trailing assistant tool-call message whose results are missing
          (otherwise the next request fails: every tool_call needs a result)
        - after an abort, record that the task was abandoned so the model does
          not quietly resume it on the next unrelated request
        """
        msgs = self.memory.messages
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if m.role == "assistant" and m.tool_calls:
                wanted = {c.id for c in m.tool_calls}
                answered = {
                    t.tool_call_id for t in msgs[i + 1 :] if t.role == "tool"
                }
                if not wanted.issubset(answered):
                    self.memory.messages = msgs[:i]
                break
        if aborted:
            self.memory.add_message(
                Message.assistant_message(
                    "[The human aborted the previous task. It is cancelled. "
                    "Do not resume or repeat it unless asked again.]"
                )
            )

    def _trim_memory(self) -> None:
        """Keep memory bounded without splitting a tool-call/result pair."""
        msgs = self.memory.messages
        if len(msgs) <= MAX_MEMORY_MESSAGES:
            return
        system = [m for m in msgs if m.role == "system"]
        rest = [m for m in msgs if m.role != "system"]
        cut = len(rest) - MAX_MEMORY_MESSAGES
        while cut < len(rest) and rest[cut].role != "user":
            cut += 1
        self.memory.messages = system + rest[cut:]

    def reset_conversation(self) -> None:
        keep = [m for m in self.memory.messages if m.role == "system"]
        self.memory.messages = keep

    async def shutdown(self) -> None:
        self.ask_tool.answer("Session closed.")
        if self.emit is not None and hasattr(self.llm, "listeners"):
            self.llm.listeners.discard(self.emit)
        await Manus.cleanup(self)

    async def cleanup(self):  # called by upstream code paths; keep session alive
        return None

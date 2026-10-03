import json
import re
from typing import Any, Awaitable, Callable, List, Optional

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


def _succeeded(result: str) -> bool:
    body = _OBSERVED.sub("", result, count=1).lstrip()
    head = body[:600]
    return not (
        body.startswith("Error")
        or "'success': False" in head
        or "Traceback (most recent call last)" in head
    )


# A final reply that announces an answer instead of giving it. Live: "SYRAX: The
# request is fully satisfied. I have researched ... I will now present the answer
# and terminate." — and no year, no URL.
PROMISE = re.compile(
    r"\b(i will now|i'll now|let me now|i am going to|i'm going to|the request is (fully )?(satisfied|complete)|"
    r"i will (now )?(present|provide|give))\b", re.I,
)
REPEATED_CALL = (
    "Not run again: you already called {name} with exactly these arguments at step {step}; the result is above. "
    "Use it. If the request is done, reply with the final answer now."
)


READ_ONLY_TOOLS = {"self_inspect", "know", "recall", "skill_list"}

# Live 2026-10-03: three autonomous attempts read the journal, changed nothing,
# and ended "Fixed task quality regression ... by ensuring prompt alignment".
# A final answer that claims a change the task never made is sent back once.
CLAIM = re.compile(
    r"(?:^|[.!]\s+)(?:fixed|resolved|repaired|patched|implemented)\b"
    r"|\b(?:has|have) been (?:successfully )?(?:\w+ and )?(?:fixed|resolved|repaired|patched|implemented|updated|changed|modified)\b"
    r"|\bi(?:'ve| have)? (?:\w+ )?(?:fixed|resolved|repaired|patched|implemented|updated|changed|modified|released)\b",
    re.I,
)
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
    return name in ("release", "skill_create", "desktop", "present", "learn", "remember", "forget") or name.startswith("browser_") or name.startswith("make_")


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
    changed: bool = False  # a tool that changes the world succeeded this turn
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
            RememberTool(), RecallTool(), ForgetTool(), SelfInspectTool(), JournalQueryTool(),
            ResearchTool(), KnowTool(), LearnTool(),
            SkillCreateTool(), SkillListTool(), SkillTestTool(), ReleaseTool(), PresentTool(), ExperimentTool(), CompareVersionsTool(), Terminate()
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
        self.changed = False
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
        if self.current_step == 0 and "max steps" in result:
            self.step_limit_hit = True
            await self._send(
                {"type": "notice", "text": f"Step limit ({self.max_steps}) reached."}
            )
        if self.last_reply.startswith("SYRAX:"):
            self.last_reply = self.last_reply[len("SYRAX:"):].strip()
        if (not self.last_reply or PROMISE.search(self.last_reply)) and any(m.role == "tool" for m in self.memory.messages):
            await self._final_answer()
        if self.last_reply and not self.changed and CLAIM.search(self.last_reply):
            await self._final_answer(CLAIM_ASK)
        self.task_goal, self.task_kind = "", "conversation"  # the core sets them again for the next task
        return self.last_reply or "Done."

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
        key = _call_key(command)
        seen = self.seen_calls
        problem = await browser.ensure_browser() if name.startswith("browser_") else None
        if name not in ("terminate", "ask_human") and key in seen:
            # the same call again (live: self_inspect(summary) six times in a row) is a loop, not progress
            result = REPEATED_CALL.format(name=name, step=seen[key])
        elif problem:
            result = f"Error: {problem}"
        else:
            refused = await self._permit(command)
            if refused is not None:
                result = refused
                seen[key] = self.current_step  # the same call again is a loop, not a second chance
            else:
                result = await ToolCallAgent.execute_tool(self, command)
                if name not in READ_ONLY_TOOLS:
                    seen.clear()  # the world may have changed: re-reading it is legitimate again
                seen[key] = self.current_step
                if _succeeded(result) and changes_something(name, _args_of(command)):
                    self.changed = True
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
        if result.startswith("Error: refused"):
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

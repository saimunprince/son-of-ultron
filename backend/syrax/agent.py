import json
import re
from typing import Any, Optional

from pydantic import Field

from app.agent.base import BaseAgent
from app.agent.manus import Manus
from app.agent.toolcall import ToolCallAgent
from app.config import config
from app.schema import AgentState, Message, ToolCall, ToolChoice
from app.tool import Terminate, ToolCollection
from app.tool.str_replace_editor import StrReplaceEditor

from syrax import browser  # noqa: F401  (sets BU_CDP_URL before MCP starts)
from syrax.brains import get_router
from syrax.memory import ForgetTool, RecallTool, RememberTool, get_memory
from syrax.prompt import SYRAX_PERSONA
from syrax.tools import AsyncPythonExecute, Emit, WebAskHuman

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
    ask_tool: WebAskHuman = Field(default_factory=WebAskHuman, exclude=True)
    last_reply: str = ""

    available_tools: ToolCollection = Field(
        default_factory=lambda: ToolCollection(
            AsyncPythonExecute(), StrReplaceEditor(), RememberTool(), RecallTool(), ForgetTool(), Terminate()
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
        # Fresh persona + long-term memory for every task.
        base = SYRAX_PERSONA.format(directory=config.workspace_root)
        try:
            block = get_memory().prompt_block()
        except Exception:
            block = ""
        self.system_prompt = f"{base}\n\n{block}" if block else base
        self.next_step_prompt = Manus.model_fields["next_step_prompt"].default
        self._trim_memory()
        await self._send({"type": "state", "state": "thinking"})
        result = await BaseAgent.run(self, request)
        if self.current_step == 0 and "max steps" in result:
            await self._send(
                {"type": "notice", "text": f"Step limit ({self.max_steps}) reached."}
            )
        return self.last_reply or "Done."

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
            }
        )
        await self._send({"type": "state", "state": "acting", "tool": name})
        problem = await browser.ensure_browser() if name.startswith("browser_") else None
        if problem:
            result = f"Error: {problem}"
        else:
            result = await ToolCallAgent.execute_tool(self, command)
        event = {
            "type": "tool_result",
            "id": command.id,
            "name": name,
            "ok": _succeeded(result),
            "output": result[:RESULT_PREVIEW_CHARS],
            "truncated": len(result) > RESULT_PREVIEW_CHARS,
        }
        if self._current_base64_image:
            event["image"] = self._current_base64_image
        await self._send(event)
        return result

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

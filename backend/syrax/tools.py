import asyncio
from typing import Awaitable, Callable, Optional

from pydantic import Field

from app.tool.base import BaseTool

Emit = Callable[[dict], Awaitable[None]]


class WebAskHuman(BaseTool):
    """ask_human replacement: asks the human through the SYRAX UI instead of stdin."""

    name: str = "ask_human"
    description: str = (
        "Ask the human operator a question and wait for the answer. "
        "Use only when you are genuinely blocked on a decision only they can make."
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "inquire": {
                "type": "string",
                "description": "The question for the human.",
            }
        },
        "required": ["inquire"],
    }

    emit: Optional[Emit] = Field(default=None, exclude=True)
    timeout: float = 600.0
    pending: Optional[asyncio.Future] = Field(default=None, exclude=True)

    async def execute(self, inquire: str) -> str:
        if self.emit is None:
            return "No operator connected. Proceed with your best judgement."
        loop = asyncio.get_running_loop()
        self.pending = loop.create_future()
        await self.emit({"type": "ask", "question": inquire})
        try:
            answer = await asyncio.wait_for(self.pending, timeout=self.timeout)
        except asyncio.TimeoutError:
            return "The human did not answer in time. Proceed with your best judgement."
        finally:
            self.pending = None
        return str(answer).strip() or "(no answer)"

    def answer(self, text: str) -> bool:
        if self.pending is not None and not self.pending.done():
            self.pending.set_result(text)
            return True
        return False


import multiprocessing  # noqa: E402
import time  # noqa: E402
from typing import Dict  # noqa: E402

from app.tool.python_execute import PythonExecute  # noqa: E402


class AsyncPythonExecute(PythonExecute):
    """python_execute that does not freeze the event loop.

    Upstream calls the blocking ``proc.join(timeout)`` inside an async method,
    which stalls the whole server (no streaming, no abort) while code runs.
    This version polls the child process asynchronously, kills it when the
    task is aborted, and allows a longer default timeout for real work.
    """

    parameters: dict = {
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "The Python code to execute. Only print() output is visible.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to run (default 60, max 600).",
            },
        },
        "required": ["code"],
    }

    async def execute(self, code: str, timeout: int = 60) -> Dict:
        timeout = max(1, min(int(timeout or 60), 600))
        with multiprocessing.Manager() as manager:
            result = manager.dict({"observation": "", "success": False})
            if isinstance(__builtins__, dict):
                safe_globals = {"__builtins__": __builtins__}
            else:
                safe_globals = {"__builtins__": __builtins__.__dict__.copy()}
            proc = multiprocessing.Process(
                target=self._run_code, args=(code, result, safe_globals), daemon=True
            )
            proc.start()
            deadline = time.monotonic() + timeout
            try:
                while proc.is_alive() and time.monotonic() < deadline:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                proc.kill()
                proc.join(1)
                raise
            if proc.is_alive():
                proc.kill()
                proc.join(1)
                return {
                    "observation": f"Execution timeout after {timeout} seconds",
                    "success": False,
                }
            proc.join(1)
            return dict(result)

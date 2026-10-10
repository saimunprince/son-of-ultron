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


START_TIMEOUT_S = 30.0  # starting a worker normally takes well under a second


def _poll(conn, timeout: float = 0.0) -> bool:
    """True when the worker sent something or its end is gone; on Windows a
    closed pipe raises BrokenPipeError from poll() instead of reporting EOF."""
    try:
        return conn.poll(timeout)
    except (EOFError, OSError):
        return True


def _kill_quietly(proc) -> None:
    try:
        if proc.pid is not None and proc.is_alive():
            proc.kill()
            proc.join(1)
    except Exception:
        pass


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

    def _guarded_run(self, code: str, conn, safe_globals: dict, paths: list) -> None:
        """Runs in the child: guard the journal and keys, for this process and
        every Python it starts, run the code, and send the result back. The
        result is sent even when the code calls sys.exit or the guard fails."""
        result = {"observation": "", "success": False}
        try:
            from syrax import guard

            guard.child_env(paths)
            guard.install(paths)
            import builtins

            safe_globals["__builtins__"] = builtins.__dict__.copy()  # the copy made before the guard holds the unguarded open
            self._run_code(code, result, safe_globals)
        except Exception as e:  # the guard itself failed; the code never ran
            result["observation"] = f"{type(e).__name__}: {e}"
        finally:
            try:
                conn.send(result)
            except Exception:
                pass
            conn.close()

    async def execute(self, code: str, timeout: int = 60) -> Dict:
        """One worker process and a pipe; nothing here blocks the event loop.

        Live 2026-10-10: this used multiprocessing.Manager(), whose start waits
        synchronously for a second process to report back. That process died
        at start, the wait never ended, and the whole server froze for 20
        minutes (no HTTP, no abort) with an UNCERTAIN task. Now the worker is
        started in a thread with a deadline, and a worker that dies without a
        result is reported instead of waited for."""
        timeout = max(1, min(int(timeout or 60), 600))
        if isinstance(__builtins__, dict):
            safe_globals = {"__builtins__": __builtins__}
        else:
            safe_globals = {"__builtins__": __builtins__.__dict__.copy()}
        from syrax.guard import protected_paths

        recv, send = multiprocessing.Pipe(duplex=False)
        proc = multiprocessing.Process(target=self._guarded_run, args=(code, send, safe_globals, protected_paths()), daemon=True)
        starter = asyncio.ensure_future(asyncio.to_thread(proc.start))
        try:
            done, _ = await asyncio.wait({starter}, timeout=START_TIMEOUT_S)
        except asyncio.CancelledError:
            starter.add_done_callback(lambda _f: _kill_quietly(proc))
            raise
        if not done:  # the start is stuck; whatever it starts later is killed
            starter.add_done_callback(lambda _f: _kill_quietly(proc))
            return {"observation": f"Error: python_execute could not start a worker process within {START_TIMEOUT_S:g} s (the machine may be short of memory); nothing ran", "success": False}
        if starter.exception() is not None:
            return {"observation": f"Error: python_execute could not start a worker process: {starter.exception()}", "success": False}
        send.close()  # the child holds its own end; EOF once it is gone
        result = None
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if _poll(recv):
                    try:
                        result = recv.recv()
                    except (EOFError, OSError):
                        result = None
                    break
                if not proc.is_alive():
                    if _poll(recv, 0.2):  # sent just before it exited
                        try:
                            result = recv.recv()
                        except (EOFError, OSError):
                            result = None
                    break
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            _kill_quietly(proc)
            recv.close()
            raise
        recv.close()
        if result is None and proc.is_alive():
            _kill_quietly(proc)
            return {
                "observation": f"Execution timeout after {timeout} seconds",
                "success": False,
            }
        if proc.is_alive():
            await asyncio.to_thread(proc.join, 2)
            _kill_quietly(proc)
        if result is None:
            return {"observation": f"Error: the python_execute worker exited with code {proc.exitcode} before returning a result", "success": False}
        return dict(result)

"""Live 2026-10-22 18:07: a client connected while the core was still building its agent after a start and left
before boot ended. Session.send swallowed the failed sends, the loop then read the socket, and starlette 1.x raised
WebSocketDisconnected (a RuntimeError, not a WebSocketDisconnect): the human's console showed a full "SYRAX session
error" traceback for a client that had simply gone. A client that is gone ends its session quietly."""

import asyncio

import starlette.websockets

from syrax.test_bridge import server

GONE = getattr(starlette.websockets, "WebSocketDisconnected", RuntimeError)


class LeftClient:
    """A socket whose client left: sends fail, and reading it raises what starlette raises then."""

    headers: dict = {}
    query_params: dict = {}

    def __init__(self, gone_after_accept=True):
        self.gone = gone_after_accept
        self.reads = 0

    async def accept(self):
        pass

    async def send_json(self, event):
        if self.gone:
            raise OSError("the client went away")

    async def receive_text(self):
        self.reads += 1
        self.gone = True
        raise GONE('WebSocket is not connected. Need to call "accept" first.')

    async def close(self, code=1000):
        pass


class Core:
    def unsubscribe(self, fn):
        pass


class Log:
    def __init__(self):
        self.lines = []

    def exception(self, text, *a, **k):
        self.lines.append(text)

    def warning(self, text, *a, **k):
        pass

    info = debug = warning


def run(monkeypatch, ws):
    log = Log()
    monkeypatch.setattr(server, "logger", log)
    monkeypatch.setattr(server, "_ws_allowed", lambda ws: (True, ""))
    monkeypatch.setattr(server, "get_core", lambda: Core())

    async def boot(self):
        await self.send({"type": "state", "state": "booting"})

    monkeypatch.setattr(server.Session, "boot", boot)
    asyncio.run(server.ws_endpoint(ws))
    return log.lines


def test_a_client_gone_during_boot_ends_its_session_quietly(monkeypatch):
    ws = LeftClient(gone_after_accept=True)
    assert run(monkeypatch, ws) == []
    assert ws.reads == 0  # nobody is there to read from


def test_a_client_that_leaves_later_ends_its_session_quietly(monkeypatch):
    ws = LeftClient(gone_after_accept=False)
    assert run(monkeypatch, ws) == []
    assert ws.reads == 1

"""The tool package, loaded lazily: `from app.tool import X` still works, but importing `app.tool.base` (every
skill and every skill test does) no longer pulls in str_replace_editor's docker client, web_search and crawl4ai
(measured 2026-10-26: about 0.33 s per process; the gate's pytest starts 100+ skill test processes)."""

import importlib


_WHERE = {
    "BaseTool": "app.tool.base",
    "Bash": "app.tool.bash",
    "Crawl4aiTool": "app.tool.crawl4ai",
    "CreateChatCompletion": "app.tool.create_chat_completion",
    "PlanningTool": "app.tool.planning",
    "StrReplaceEditor": "app.tool.str_replace_editor",
    "Terminate": "app.tool.terminate",
    "ToolCollection": "app.tool.tool_collection",
    "WebSearch": "app.tool.web_search",
}

__all__ = [
    "BaseTool",
    "Bash",
    "Terminate",
    "StrReplaceEditor",
    "WebSearch",
    "ToolCollection",
    "CreateChatCompletion",
    "PlanningTool",
    "Crawl4aiTool",
]


def __getattr__(name):
    module = _WHERE.get(name)
    if module is None:
        raise AttributeError(f"module 'app.tool' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value


def __dir__():
    return sorted(set(globals()) | set(__all__))

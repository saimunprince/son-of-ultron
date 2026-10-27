"""The cause class of a failed tool call, recorded on every tool.failed event as ``error_class``.

Journal audit 2026-10-27: 628 tool.failed events carried no cause, so selfmodel, limits and journal_query could
only group failures by tool (python_execute 175, apply_patch 167, str_replace_editor 117, release 65), never by why.
Terminal task events already carry one (core.error_class); this is the same for a single call. Pure and
deterministic: the class comes from the tool's own output, first matching rule wins, in ``CLASSES`` order.
"""
import re

# refused: a guard turned the call down (the permission gate, a held intent, release refusing its plan)
# timeout: the call was abandoned or ran out of time
# mismatch: an edit whose expected text or patch context is not what the file holds
# misuse: wrong, missing or invalid arguments (including a query naming a column that does not exist)
# not_found: the file, path, module or app the call names is not there
# external: the network or a remote service failed (connection, HTTP 4xx/5xx, rate limit)
# crash: a Python exception or traceback inside the tool or the code it ran
# other: none of the above
CLASSES = ("refused", "timeout", "mismatch", "misuse", "not_found", "external", "crash", "other")

_RULES = (
    ("timeout", re.compile(
        r"(?i)did not answer within|execution timeout|\btimed out\b|\btimeout after\b|TimeoutError|TimeoutExpired|"
        r"read ?timeout|deadline exceeded")),
    ("mismatch", re.compile(
        r"(?i)does not apply|patch failed|did not appear verbatim|old_str [`'\"]?.*did not appear|"
        r"multiple occurrences|no replacement was performed|already exists in working directory|"
        r"matches several places")),
    ("misuse", re.compile(
        r"(?i)parameter `?\w+`? is required|unknown argument|must be one of|unrecognized command|"
        r"invalid `?\w+`? parameter|invalid (?:json|arguments?)|failed to parse (?:the )?arguments|"
        r"missing (?:required )?argument|no such column|no such table|ambiguous column|bad json path|"
        r"paths must be repository-relative|cite at least one|needs a [\w ]+ in|is not a pdf|"
        r"only the `?view`? command can be used")),
    ("not_found", re.compile(
        r"(?i)no such file|does not exist|FileNotFoundError|ModuleNotFoundError|no module named|"
        r"no installed app matches|nothing to open|no file at|\bnot found\b")),
    ("external", re.compile(
        r"(?i)ConnectionError|ConnectError|connection (?:refused|reset|aborted|error)|remote end closed|"
        r"server disconnected|\bHTTP(?: error)? ?[45]\d\d\b|status(?: code)?:? [45]\d\d\b|"
        r"\b[45]\d\d (?:client|server) error|rate.?limit|too many requests|getaddrinfo failed|"
        r"name or service not known|SSLError")),
    ("crash", re.compile(
        r"Traceback \(most recent call last\)|\b[A-Z]\w*(?:Error|Exception|Interrupt)\b: ?|"
        r"returned non-zero exit status|codec can't decode")),
)


def tool_error_class(name: str, output: object, refused: bool = False) -> str:
    """The class of one failed call of tool ``name`` from its ``output``; ``refused`` is the event's own flag
    (agent._refused). Always one of ``CLASSES``."""
    if refused:
        return "refused"
    text = str(output or "")
    if text.startswith("Error: refused") or (name == "release" and "Error: release refused:" in text[:200]):
        return "refused"
    for cls, rule in _RULES:
        if rule.search(text):
            return cls
    return "other"

"""SYRAX brain router.

A drop-in replacement for OpenManus' ``LLM`` that talks to many
OpenAI-compatible providers and fails over between them. Free providers come
first; one works with no key at all (Pollinations) and one runs fully local
(Ollama). Keys live in ``backend/config/brains.json`` (gitignored, 0600) and are
managed from the SYRAX UI.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import string
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

from app.config import PROJECT_ROOT
from app.llm import LLM
from app.logger import logger
from app.schema import Message

BRAINS_FILE = Path(os.getenv("SYRAX_BRAINS_FILE", PROJECT_ROOT / "config" / "brains.json"))
_UNSET = object()


_ENC = None
KEYLESS_MAX_TOKENS = 1500  # anonymous Pollinations caps replies around here and 402s above it


def count_tokens(obj: Any) -> int:
    """Rough token count of a message list / tool list / string (o200k, the
    tokenizer of the current OpenAI-family models; close enough for budgets)."""
    global _ENC
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    if _ENC is None:
        try:
            import tiktoken
            _ENC = tiktoken.get_encoding("o200k_base")
        except Exception:
            _ENC = False
    if not _ENC:
        return len(text) // 4 + 1
    return len(_ENC.encode(text, disallowed_special=()))


MIN_COMPLETION = 1024
SYSTEM_JOIN = "\n\n=====\n\n"  # between merged system messages; fit_request splits on it
CLIP_TO = 1200  # characters kept of a clipped message (head + tail)


def _clip_text(text: str, keep: int = CLIP_TO) -> str:
    if len(text) <= keep:
        return text
    head, tail = keep * 2 // 3, keep // 3
    return f"{text[:head]}\n…[{len(text) - head - tail} characters cut to fit this brain]…\n{text[-tail:]}"


# The agent's per-step prompts (OpenManus adds one as a user message on every
# step). The agent registers them; they are never turn starts in fit_request.
STEP_PROMPTS: set = set()


def fit_request(messages: List[dict], tools: Optional[List[dict]], budget: int, max_tokens: int) -> tuple:
    """Make ``messages`` + ``tools`` + completion fit ``budget`` tokens.
    Returns (messages, max_tokens). System messages always stay. Turns start at
    user messages that are real requests; the agent's registered per-step
    prompts (STEP_PROMPTS) are not turn starts, so a task's own request is
    never cut away from its steps. The same request asked twice is still two
    turns. In order, until it fits: drop the oldest turns; shrink
    the completion to MIN_COMPLETION; clip long contents oldest first (head and
    tail kept, the newest message last). Raises BrainError when even that does
    not fit."""
    completion = max(256, min(max_tokens, budget // 4))
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    base = count_tokens(tools or []) + count_tokens(system) + 64
    repeated = STEP_PROMPTS

    def starts_turn(m: dict) -> bool:
        return m.get("role") == "user" and m.get("content") not in repeated

    def over() -> bool:
        return base + completion + count_tokens(rest) > budget

    while rest and over():
        cut = 1
        while cut < len(rest) and not starts_turn(rest[cut]):
            cut += 1
        if cut >= len(rest):  # only the latest turn is left
            break
        rest = rest[cut:]
    if over():
        completion = min(completion, MIN_COMPLETION)
    if over():
        rest = [dict(m) for m in rest]
        for keep in (CLIP_TO, CLIP_TO // 3, CLIP_TO // 8):  # gentle first, harder only if needed
            for m in rest:  # oldest first, the newest last
                if isinstance(m.get("content"), str) and len(m["content"]) > keep + 80:
                    m["content"] = _clip_text(m["content"], keep)
                    if not over():
                        break
            if not over():
                break
    if over() and system:
        # Extra system parts (MCP server manuals, resume notes) come after the
        # persona and are reference material: clip them too, the persona never.
        # They arrive either as separate messages or merged by _normalize_messages.
        parts = [m.get("content") or "" for m in system]
        parts = parts[0].split(SYSTEM_JOIN) + parts[1:] if len(parts) == 1 else parts
        if len(parts) > 1:
            for keep in (CLIP_TO * 2, CLIP_TO // 2, CLIP_TO // 8):
                parts = [parts[0]] + [_clip_text(x, keep) if len(x) > keep + 80 else x for x in parts[1:]]
                system = [{"role": "system", "content": SYSTEM_JOIN.join(parts)}]
                base = count_tokens(tools or []) + count_tokens(system) + 64
                if not over():
                    break
    if over():
        raise BrainError(
            f"request too large for this brain even after trimming: system prompt + tools + latest turn ≈ "
            f"{base + completion + count_tokens(rest)} tokens, limit {budget}"
        )
    return system + rest, completion


_FIRST_SENTENCE = re.compile(r"^(.{20,200}?[.!?])(?:\s|$)", re.S)


def _first_sentence(text: str, limit: int = 200) -> str:
    text = " ".join(str(text or "").split())
    m = _FIRST_SENTENCE.match(text)
    return (m.group(1) if m else text)[:limit]


# Live 2026-10-31: 43 tools, and even their compact manual left a request at ~8,619 tokens, over Groq's 8,000.
# For a brain the compact manual does not fit, the tools are chosen (select_tools): these always, then the tools whose
# name or description shares words with the request, best first, while the request fits.
ESSENTIAL_TOOLS = frozenset({"terminate", "ask_human", "python_execute", "desktop", "recall", "remember", "research",
                             "know", "undo", "present"})
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


def _words(text: str) -> set:
    """Content words (memory.content_words: no stop words, so "the" never makes a tool relevant)."""
    from syrax.memory import content_words

    return set(content_words(" ".join(_WORD.findall(text or ""))))


def _request_text(messages: List[dict]) -> str:
    """The newest human turn (not a console step prompt), and the one before it, for context."""
    turns = [str(m.get("content") or "") for m in messages if m.get("role") == "user" and m.get("content") not in STEP_PROMPTS]
    return " ".join(turns[-2:])


def select_tools(tools: List[dict], messages: List[dict], budget: int, max_tokens: int) -> List[dict]:
    """The tools that fit `budget` with these messages: all of them if they fit, else the essential ones and then the
    ones sharing the most words with the request, kept in their original order."""
    try:
        fit_request(messages, tools, budget, max_tokens)
        return tools
    except BrainError:
        pass
    want = _words(_request_text(messages))

    def name(t: dict) -> str:
        return str((t.get("function") or {}).get("name") or "")

    def score(t: dict) -> int:
        f = t.get("function") or {}
        return len(want & (_words(name(t).replace("_", " ")) | _words(str(f.get("description") or ""))))

    keep = {name(t) for t in tools if name(t) in ESSENTIAL_TOOLS}
    rest = sorted((t for t in tools if name(t) not in keep), key=lambda t: -score(t))
    for t in rest:
        if score(t) == 0:
            break
        trial = keep | {name(t)}
        try:
            fit_request(messages, [x for x in tools if name(x) in trial], budget, max_tokens)
            keep = trial
        except BrainError:
            continue
    return [t for t in tools if name(t) in keep]


# A system prompt and its short version (agent.py registers both per task). A brain that cannot fit the full prompt
# even with the tools chosen per request gets the short one (live 2026-10-31: Ollama, 4,096 tokens).
SHORT_SYSTEMS: Dict[str, str] = {}
SHORT_KEEP = 16


def register_short_system(full: str, short: str) -> None:
    if full and short and len(short) < len(full):
        SHORT_SYSTEMS.pop(full, None)
        SHORT_SYSTEMS[full] = short
        while len(SHORT_SYSTEMS) > SHORT_KEEP:
            SHORT_SYSTEMS.pop(next(iter(SHORT_SYSTEMS)))


def shorten_system(messages: List[dict]) -> Optional[List[dict]]:
    """The messages with each registered system prompt replaced by its short version, or None when none is there."""
    out, changed = [], False
    for m in messages:
        c = m.get("content")
        if m.get("role") == "system" and isinstance(c, str):
            for full, short in SHORT_SYSTEMS.items():
                if full in c:
                    c, changed = c.replace(full, short), True
            m = {**m, "content": c}
        out.append(m)
    return out if changed else None


def compact_tools(tools: List[dict]) -> List[dict]:
    """The tool list for a brain whose request budget the full manual does not fit (live 2026-10-29: Groq's 8k free
    tier refused every SYRAX request, ~5.2k of it tool descriptions, so a Gemini outage left only Pollinations). Each
    tool keeps its name, its description's first sentence and its parameter schema without prose: names, types, enums,
    required and nesting stay, so a call made from it is the same call."""
    import copy

    def strip(node: Any) -> Any:
        """A schema without its prose. Under "properties" the keys are parameter NAMES (skill_create has one called
        description): every name stays, only each parameter's own schema is stripped."""
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    out[k] = {name: strip(sub) for name, sub in v.items()}
                elif k in ("description", "examples", "title") and not isinstance(v, (dict, list)):
                    continue
                else:
                    out[k] = strip(v)
            return out
        if isinstance(node, list):
            return [strip(x) for x in node]
        return node

    out = []
    for t in tools or []:
        t = copy.deepcopy(t)
        fn = t.get("function") if isinstance(t.get("function"), dict) else None
        if fn is not None:
            fn["description"] = _first_sentence(fn.get("description", ""))
            if isinstance(fn.get("parameters"), dict):
                fn["parameters"] = strip(fn["parameters"])
        out.append(t)
    return out


def _malformed_generation(e: Exception) -> bool:
    text = str(e).lower()
    return "parsing failed" in text or "failed_generation" in text or "tool_use_failed" in text


def _limit_from_413(e: Exception) -> Optional[int]:
    m = re.search(r"[Ll]imit[^0-9]{0,4}(\d{3,7})", str(e))
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str
    tier: str  # "no-key" | "local" | "free" | "paid"
    default_model: str
    key_required: bool = True
    vision: bool = False
    signup_url: str = ""
    note: str = ""
    timeout: float = 120.0
    # Only offer models whose id matches (e.g. OpenRouter ":free" models)
    model_filter: Optional[str] = None
    models_url: Optional[str] = None  # when the provider has no OpenAI /models
    static_models: tuple = ()
    # optional-key providers: endpoint + default model once a key is saved
    keyed_base_url: Optional[str] = None
    keyed_default_model: Optional[str] = None
    # local providers: smaller models to try when RAM is short
    fallback_models: tuple = ()
    # extra request params for the key-less endpoint (e.g. reasoning budget)
    free_params: tuple = ()
    # hard cap on prompt + completion tokens per request (free-tier TPM limits,
    # local context windows); None = the model's own context is the limit
    max_request_tokens: Optional[int] = None
    # free model pool: each model has its own free quota, so when the chosen one
    # is rate limited the provider's other chat models are tried before failing over
    pool: bool = False


# Feature catalog (free_model_pool), 2026-10-12. Models that cannot chat with tools are never pooled.
POOL_DENY = re.compile(r"image|tts|audio|live|embed|veo|imagen|aqa|banana|robotics|computer-use|learnlm|gemma|guard|native|transcri"
                       r"|antigravity|deep-research|lyria", re.I)


def kinship(model: str, chosen: str) -> int:
    """How many name parts a model shares with the chosen one: the pool tries the
    closest family first (gemini-3.5-flash-lite -> gemini-3.1-flash-lite before
    gemini-2.5-pro). Live 2026-10-13: the pool went alphabetically, spent its three
    tries on antigravity-preview-* models that are not chat models, and Gemini
    failed over to upstage, whose tool discipline then failed `restraint`."""
    parts = lambda s: {p for p in re.split(r"[-:/_]", s.lower()) if p}
    return len(parts(model) & parts(chosen))
POOL_TRIES = 3
POOL_CACHE_S = 6 * 3600.0
POOL_MODEL_COOLDOWN_S = 300.0
EMPTY_MODEL_COOLDOWN_S = 1800.0  # a model that answers nothing twice in a row rests longer than a rate-limited one


PROVIDERS: Dict[str, Provider] = {
    p.id: p
    for p in [
        Provider(
            id="gemini",
            label="Google Gemini",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            tier="free",
            # Free keys get a small request quota per model (measured 2026-09-30:
            # gemini-2.5-flash and 2.5-flash-lite both "limit: 20"), so the newest
            # lite model is the default; pick another model in BRAIN when one runs out.
            default_model="gemini-3.5-flash-lite",
            vision=True,
            pool=True,
            signup_url="https://aistudio.google.com/apikey",
            note="Free tier. Strong tool use. Each model has its own small free quota (20 requests on 2.5 models); switch model in BRAIN when one is exhausted.",
        ),
        Provider(
            id="upstage",
            label="Upstage Solar",
            base_url="https://api.upstage.ai/v1",
            tier="free",
            default_model="solar-pro3",  # tool calls verified 2026-09-30 (solar-pro2 too)
            signup_url="https://console.upstage.ai/api-keys",
            note="Free trial credits. OpenAI-compatible, tool calling works on solar-pro models.",
        ),
        Provider(
            id="groq",
            label="Groq",
            base_url="https://api.groq.com/openai/v1",
            tier="free",
            default_model="openai/gpt-oss-120b",  # llama-3.3-70b was retired by Groq (2026-09)
            signup_url="https://console.groq.com/keys",
            note="Free tier. Extremely fast, but 8k tokens per request: history is trimmed to fit.",
            max_request_tokens=8000,  # free-tier TPM; Groq counts prompt + max_tokens (HTTP 413 otherwise)
        ),
        Provider(
            id="cerebras",
            label="Cerebras",
            base_url="https://api.cerebras.ai/v1",
            tier="free",
            default_model="gpt-oss-120b",
            signup_url="https://cloud.cerebras.ai",
            note="Free tier. Very fast.",
        ),
        Provider(
            id="openrouter",
            label="OpenRouter (free models)",
            base_url="https://openrouter.ai/api/v1",
            tier="free",
            default_model="",
            signup_url="https://openrouter.ai/settings/keys",
            note="Free key. Only ':free' models are listed, so it never bills.",
            model_filter=r":free$",
            pool=True,
        ),
        Provider(
            id="mistral",
            label="Mistral",
            base_url="https://api.mistral.ai/v1",
            tier="free",
            default_model="mistral-small-latest",
            signup_url="https://console.mistral.ai/api-keys",
            note="Free 'Experiment' plan.",
        ),
        Provider(
            id="github",
            label="GitHub Models",
            base_url="https://models.github.ai/inference",
            tier="free",
            default_model="openai/gpt-4.1-mini",
            vision=True,
            signup_url="https://github.com/settings/tokens",
            note="Free with a GitHub token (models:read scope).",
            models_url="https://models.github.ai/catalog/models",
        ),
        Provider(
            id="anthropic",
            label="Anthropic Claude",
            base_url="https://api.anthropic.com/v1/",
            tier="paid",
            default_model="claude-sonnet-5",
            vision=True,
            signup_url="https://console.anthropic.com/settings/keys",
            note="Paid. Top quality.",
        ),
        Provider(
            id="openai",
            label="OpenAI",
            base_url="https://api.openai.com/v1",
            tier="paid",
            default_model="gpt-5-mini",
            vision=True,
            signup_url="https://platform.openai.com/api-keys",
            note="Paid.",
        ),
        Provider(
            id="pollinations",
            label="Pollinations",
            base_url="https://text.pollinations.ai/openai",
            tier="no-key",
            default_model="openai-fast",
            key_required=False,
            note="No key: plain replies only (HTTP 402 on tool calls since 2026-09), so SYRAX can talk but not act. A free token from enter.pollinations.ai unlocks tools and stronger models.",
            signup_url="https://enter.pollinations.ai",
            timeout=90.0,
            static_models=("openai-fast", "openai"),
            keyed_base_url="https://gen.pollinations.ai/v1",
            keyed_default_model="openai",
            # the anonymous tier rejects every extra parameter (reasoning_effort, tools) with 402
        ),
        Provider(
            id="ollama",
            label="Ollama (local)",
            base_url=os.getenv("SYRAX_OLLAMA_URL", "http://127.0.0.1:11434/v1"),
            tier="local",
            default_model="qwen2.5:7b",
            key_required=False,
            signup_url="https://ollama.com/download",
            note="Runs on this machine. Offline, private, slow on CPU. Steps down to a smaller installed model when RAM is short.",
            timeout=600.0,
            fallback_models=("qwen2.5:3b", "qwen2.5:1.5b", "llama3.2:3b", "llama3.2:1b"),
            # Measured 2026-10-28 (Ollama 0.40.12, CPU, qwen2.5-coder:7b with a 32k model context): the OpenAI-style
            # /v1 endpoint ignores options.num_ctx and silently cuts a longer prompt to the server's context
            # (4096 by default on a machine without VRAM): a 12k prompt arrived as 2,050 tokens and the answer was
            # made up. 8192 here let 4-8k prompts through to be cut the same way. The budget is the server's real
            # context: OLLAMA_CONTEXT_LENGTH on the Ollama service, told to SYRAX as SYRAX_OLLAMA_NUM_CTX.
            max_request_tokens=int(os.getenv("SYRAX_OLLAMA_NUM_CTX", "4096")),
        ),
    ]
}

DEFAULT_ORDER = [
    "gemini", "upstage", "groq", "cerebras", "openrouter", "mistral", "github",
    "anthropic", "openai", "pollinations", "ollama",
]

_ID_ALPHABET = string.ascii_letters + string.digits


_TEXT_CALL = re.compile(r"<tool_call>(.*?)(?:</tool_call>|\Z)", re.S)
_TEXT_FUNC = re.compile(r"<function=([\w.-]+)>(.*?)(?:</function>|\Z)", re.S)
_TEXT_PARAM = re.compile(r"<parameter=([\w.-]+)>(.*?)</parameter>", re.S)
_FENCE = re.compile(r"\A```(?:json)?\s*(.*?)\s*```\Z", re.S)


def _json_call(obj) -> tuple:
    """(name, arguments) of {"name": ..., "arguments": {...}}, or (None, None)."""
    if not isinstance(obj, dict):
        return None, None
    args = obj.get("arguments") or obj.get("parameters") or {}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return None, None
    return obj.get("name"), args


def text_tool_calls(content: str, tools: Optional[List[dict]]) -> tuple:
    """Tool calls a model wrote as text, in the two shapes seen from open models:
    <tool_call>{"name": ..., "arguments": {...}}</tool_call> and
    <tool_call><function=NAME><parameter=KEY>VALUE</parameter>...</function></tool_call>.
    A third shape, live 2026-10-28 from Ollama qwen2.5-coder:7b on the OpenAI endpoint: the whole reply is the bare
    JSON {"name": ..., "arguments": {...}} (or a list of them, or one in a ```json fence); it counts only when the
    reply is nothing else, so an answer that shows JSON in a sentence stays an answer.
    Only functions that were offered count. Returns (calls, the text before the first call)."""
    from openai.types.chat.chat_completion_message_tool_call import ChatCompletionMessageToolCall, Function

    offered = {(t.get("function") or {}).get("name") for t in tools or []}

    def call(name, args):
        return ChatCompletionMessageToolCall(id=_new_call_id(), type="function", function=Function(name=name, arguments=json.dumps(args)))

    first = content.find("<tool_call>")
    if first < 0:
        body = content.strip()
        fenced = _FENCE.match(body)
        body = fenced.group(1) if fenced else body
        if body[:1] not in "{[":
            return [], content
        try:
            obj = json.loads(body)
        except ValueError:
            return [], content
        pairs = [_json_call(o) for o in (obj if isinstance(obj, list) else [obj])]
        if not pairs or any(name not in offered or not isinstance(args, dict) for name, args in pairs):
            return [], content
        return [call(name, args) for name, args in pairs], ""
    calls = []
    for body in _TEXT_CALL.findall(content):
        body = body.strip()
        name, args = None, None
        if body.startswith("{"):
            try:
                name, args = _json_call(json.loads(body))
            except ValueError:
                continue
        else:
            f = _TEXT_FUNC.search(body)
            if not f:
                continue
            name, args = f.group(1), {}
            for key, raw in _TEXT_PARAM.findall(f.group(2)):
                val = raw.strip("\n").strip() if raw.strip().startswith(("[", "{")) or raw.strip().isdigit() else raw.strip("\n")
                try:
                    args[key] = json.loads(val) if val[:1] in "[{" or val.isdigit() else val
                except ValueError:
                    args[key] = val
        if name in offered and isinstance(args, dict):
            calls.append(call(name, args))
    return calls, content[:first].strip()


def _new_call_id() -> str:
    # 9 alphanumerics: the strictest format any provider enforces (Mistral).
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(9))


class BrainError(Exception):
    pass


@dataclass
class Health:
    until: float = 0.0
    reason: str = ""
    last_ok: float = 0.0
    last_model: str = ""


@dataclass
class BrainStore:
    """Persisted provider settings. Keys never leave this process unmasked."""

    order: List[str] = field(default_factory=lambda: list(DEFAULT_ORDER))
    settings: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    # Phase 2 of the self-improvement plan: the brain the owner wants on SYRAX's own code changes
    # (a release objective), tried before any measured routing; None keeps the benchmark's choice.
    self_change_brain: Optional[str] = None

    @classmethod
    def load(cls) -> "BrainStore":
        store = cls()
        try:
            data = json.loads(BRAINS_FILE.read_text(encoding="utf-8"))
            store.settings = {
                k: v for k, v in (data.get("providers") or {}).items() if k in PROVIDERS
            }
            saved = [p for p in data.get("order") or [] if p in PROVIDERS]
            store.order = saved + [p for p in DEFAULT_ORDER if p not in saved]
            sc = data.get("self_change_brain")
            store.self_change_brain = sc if sc in PROVIDERS else None
        except FileNotFoundError:
            pass
        except Exception as e:  # corrupt file: keep defaults, do not crash boot
            logger.error(f"brains.json unreadable, using defaults: {e}")
        return store

    def save(self) -> None:
        BRAINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BRAINS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"order": self.order, "providers": self.settings, "self_change_brain": self.self_change_brain}, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(BRAINS_FILE)

    def get(self, pid: str) -> Dict[str, Any]:
        return self.settings.setdefault(pid, {})

    def key(self, pid: str) -> str:
        return str(self.get(pid).get("api_key") or "")

    def model(self, pid: str) -> str:
        p = PROVIDERS[pid]
        if self.get(pid).get("model"):
            return str(self.get(pid)["model"])
        if self.key(pid) and p.keyed_default_model:
            return p.keyed_default_model
        return p.default_model

    def enabled(self, pid: str) -> bool:
        p = PROVIDERS[pid]
        s = self.get(pid)
        if "enabled" in s:
            return bool(s["enabled"]) and (bool(self.key(pid)) or not p.key_required)
        return bool(self.key(pid)) or not p.key_required


def _mask(key: str) -> str:
    return f"••••{key[-4:]}" if len(key) >= 8 else ("••••" if key else "")


_TOOL_NAME_JUNK = re.compile(r"<\|.*$", re.S)


def _clean_tool_name(name: Optional[str]) -> str:
    """Drop chat-template leakage such as 'browser_exec<|channel|>commentary'."""
    name = _TOOL_NAME_JUNK.sub("", name or "").strip()
    return re.sub(r"[^A-Za-z0-9_.-]", "", name)[:64] or "unknown_tool"


def _clean_arguments(name: str, raw: Optional[str], tools: Optional[List[dict]] = None) -> str:
    """Guarantee a JSON-object argument string.

    Weak models sometimes send the raw payload (e.g. bare code). If the tool has
    exactly one required string parameter, wrap the payload into it.
    """
    raw = raw or ""
    try:
        parsed = json.loads(raw) if raw.strip() else {}
        if isinstance(parsed, dict):
            return json.dumps(parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        if fn.get("name") != name:
            continue
        params = fn.get("parameters") or {}
        required = params.get("required") or []
        props = params.get("properties") or {}
        if len(required) == 1 and (props.get(required[0]) or {}).get("type") == "string":
            return json.dumps({required[0]: raw})
    return json.dumps({"input": raw})


def _normalize_messages(messages: List[dict]) -> List[dict]:
    """Make one history acceptable to every provider.

    - all system messages merged into a single leading one
    - assistant messages with tool calls keep a string content
    - tool names and arguments in history are sanitised (one bad reply must
      not poison every provider afterwards)
    """
    systems = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
    rest = []
    for m in messages:
        if m.get("role") == "system":
            continue
        m = dict(m)
        if m.get("role") == "assistant" and m.get("tool_calls"):
            if m.get("content") is None:
                m["content"] = ""
            fixed = []
            for c in m["tool_calls"]:
                c = dict(c)
                fn = dict(c.get("function") or {})
                fn["name"] = _clean_tool_name(fn.get("name"))
                fn["arguments"] = _clean_arguments(fn["name"], fn.get("arguments"))
                c["function"] = fn
                fixed.append(c)
            m["tool_calls"] = fixed
        if m.get("role") == "tool" and m.get("name"):
            m["name"] = _clean_tool_name(m["name"])
        rest.append(m)
    head = [{"role": "system", "content": SYSTEM_JOIN.join(map(str, systems))}] if systems else []
    return head + rest


def _has_images(messages: List[dict]) -> bool:
    return any(
        isinstance(m.get("content"), list)
        and any(isinstance(p, dict) and p.get("type") == "image_url" for p in m["content"])
        for m in messages
    )


class BrainRouter(LLM):
    """LLM-compatible router with provider failover."""

    def __new__(cls, *args, **kwargs):  # bypass LLM's per-config singleton
        return object.__new__(cls)

    def __init__(self, store: Optional[BrainStore] = None):
        self.store = store or BrainStore.load()
        self.health: Dict[str, Health] = {pid: Health() for pid in PROVIDERS}
        # free model pool: per-model cooldowns, the pool listing, and the model that answered last
        self.model_cooldown: Dict[tuple, float] = {}
        self._pool: Dict[str, tuple] = {}
        self.pool_used: Dict[str, str] = {}
        self.last_model: Dict[str, str] = {}
        self.listeners: set = set()
        self.model = "syrax-router"
        self.max_tokens = 8192
        self.temperature = 0.2
        self.api_type = "router"
        self.base_url = ""
        self.api_key = ""
        self.client = None
        self.total_input_tokens = 0
        self.total_completion_tokens = 0
        self.max_input_tokens = None
        self.active: Optional[str] = None
        self.preferred: Optional[str] = None  # set temporarily (e.g. brain comparison) to try this provider first
        self.routed: Optional[str] = None  # per task: the brain measured best at this kind of work (routing.py)

    # ——— introspection for the UI ———
    def describe(self) -> dict:
        now = time.time()
        out = []
        for pid in self.store.order:
            p = PROVIDERS[pid]
            h = self.health[pid]
            key = self.store.key(pid)
            if not self.store.enabled(pid):
                status = "off" if (key or not p.key_required) else "no-key"
            elif h.until > now:
                status = "cooldown"
            else:
                status = "ready"
            out.append(
                {
                    "id": pid,
                    "label": p.label,
                    "tier": p.tier,
                    "note": p.note,
                    "signup_url": p.signup_url,
                    "key_required": p.key_required,
                    "has_key": bool(key),
                    "key_hint": _mask(key),
                    "model": self.store.model(pid),
                    "enabled": self.store.enabled(pid),
                    "status": status,
                    "reason": h.reason if status == "cooldown" or h.reason else "",
                    "cooldown_s": max(0, int(h.until - now)),
                }
            )
        return {"order": list(self.store.order), "providers": out, "active": self.active,
                "self_change_brain": self.store.self_change_brain}

    def usable(self, pid: str) -> Tuple[bool, str]:
        """Whether a brain can take a call right now, and why not: enabled, keyed if it needs
        a key, not cooling down after a failure."""
        if pid not in PROVIDERS:
            return False, "unknown brain"
        p, h = PROVIDERS[pid], self.health[pid]
        if p.key_required and not self.store.key(pid):
            return False, "no key"  # before "disabled": a keyless keyed brain is both, and the key is the cure
        if not self.store.enabled(pid):
            return False, "disabled"
        if h.until > time.time():
            return False, f"cooldown: {h.reason or 'recent failure'}"
        return True, "ready"

    def update(self, changes: Dict[str, Dict[str, Any]], order: Optional[List[str]], self_change_brain: Any = _UNSET) -> None:
        for pid, ch in (changes or {}).items():
            if pid not in PROVIDERS or not isinstance(ch, dict):
                continue
            s = self.store.get(pid)
            if "api_key" in ch:
                key = str(ch["api_key"] or "").strip()
                if key:
                    s["api_key"] = key
                else:
                    s.pop("api_key", None)
                self.health[pid] = Health()  # new key: forget old failures
            if "model" in ch:
                model = str(ch["model"] or "").strip()
                if model:
                    s["model"] = model
                else:
                    s.pop("model", None)
                self.health[pid] = Health()
            if "enabled" in ch:
                s["enabled"] = bool(ch["enabled"])
        if order:
            valid = [p for p in order if p in PROVIDERS]
            self.store.order = valid + [p for p in DEFAULT_ORDER if p not in valid]
        if self_change_brain is not _UNSET:  # "" or None clears it; an unknown id is ignored, not saved
            sc = str(self_change_brain or "").strip() or None
            if sc is None or sc in PROVIDERS:
                self.store.self_change_brain = sc
        self.store.save()

    def _client(self, pid: str, key: Optional[str] = None) -> AsyncOpenAI:
        p = PROVIDERS[pid]
        api_key = key if key is not None else self.store.key(pid)
        base_url = p.keyed_base_url if (api_key and p.keyed_base_url) else p.base_url
        return AsyncOpenAI(
            api_key=api_key or "no-key",
            base_url=base_url,
            timeout=p.timeout,
            max_retries=0,  # the router does its own failover
        )

    async def _auto_model(self, pid: str) -> str:
        """A provider with a key but no chosen model (OpenRouter's free list
        rotates, so it has no fixed default): take the largest listed model,
        remember it, and say so. Live 2026-10-01: "no model selected"."""
        try:
            models = await self.list_models(pid)
        except Exception as e:
            raise BrainError(f"no model selected and the model list failed: {self._reason(e)}")
        if not models:
            raise BrainError("no model selected and the provider lists none")

        def size(m: str) -> float:
            nums = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b\b", m.lower())]
            return max(nums) if nums else 0.0

        choice = sorted(models, key=lambda m: (-size(m), m))[0]
        self.store.get(pid)["model"] = choice
        try:
            self.store.save()
        except OSError:
            pass
        logger.info(f"brain {pid}: no model chosen, using {choice} (largest of {len(models)} listed)")
        return choice

    async def list_models(self, pid: str, key: Optional[str] = None) -> List[str]:
        p = PROVIDERS[pid]
        api_key = key if key is not None else self.store.key(pid)
        if p.static_models and not (api_key and p.keyed_base_url):
            return list(p.static_models)
        if p.models_url:
            async with httpx.AsyncClient(timeout=20) as http:
                r = await http.get(p.models_url, headers={"Authorization": f"Bearer {api_key}"})
                r.raise_for_status()
                ids = [m.get("id") for m in r.json() if isinstance(m, dict)]
        else:
            page = await self._client(pid, key).models.list()
            ids = [m.id for m in page.data]
        ids = [i.removeprefix("models/") for i in ids if i]
        if p.model_filter:
            ids = [i for i in ids if re.search(p.model_filter, i)]
        return sorted(set(ids))

    async def test(self, pid: str, model: Optional[str] = None) -> dict:
        tool = {
            "type": "function",
            "function": {
                "name": "report",
                "description": "Report a number.",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "integer"}},
                    "required": ["value"],
                },
            },
        }
        started = time.time()
        try:
            msg = await self._call(
                pid,
                [{"role": "user", "content": "Call the report tool with value 42."}],
                [tool],
                "auto",
                images=False,
                model=model,
            )
            calls = msg.tool_calls or []
            ok_tools = any(c.function.name == "report" for c in calls)
            return {
                "id": pid,
                "ok": True,
                "tools": ok_tools,
                "model": model or self.store.model(pid),
                "latency_ms": int((time.time() - started) * 1000),
                "reply": (msg.content or "")[:200],
            }
        except Exception as e:
            return {"id": pid, "ok": False, "error": self._reason(e)}

    # ——— the call OpenManus makes ———
    async def ask_tool(
        self,
        messages: List[Any],
        system_msgs: Optional[List[Any]] = None,
        timeout: int = 300,
        tools: Optional[List[dict]] = None,
        tool_choice: Any = "auto",
        temperature: Optional[float] = None,
        **kwargs,
    ):
        chain = [p for p in self.store.order if self.store.enabled(p)]
        first = self.preferred if self.preferred in chain else self.routed if self.routed in chain else None
        if first:
            chain = [first] + [p for p in chain if p != first]
        if not chain:
            raise BrainError("No brain enabled. Open BRAIN in the UI and add a key.")

        wait_rounds = 0
        for attempt in range(3):
            failures = []
            soonest = None
            for pid in chain:
                h = self.health[pid]
                wait = h.until - time.time()
                if wait > 0:
                    failures.append(f"{PROVIDERS[pid].label}: cooling down ({h.reason})")
                    soonest = wait if soonest is None else min(soonest, wait)
                    continue
                formatted = self._format(messages, system_msgs, PROVIDERS[pid].vision)
                try:
                    started = time.monotonic()
                    try:
                        msg = await self._call(pid, formatted, tools, tool_choice, images=True, model=self._model_for(pid))
                    except BrainError as e:
                        # Reasoning-only / empty replies are usually one-off glitches.
                        if "empty response" not in str(e):
                            raise
                        logger.info(f"brain {pid} returned an empty reply, retrying once with low reasoning")
                        try:
                            msg = await self._call(
                                pid, formatted, tools, tool_choice, images=True,
                                extra={"reasoning_effort": "low"}, model=self._model_for(pid),
                            )
                        except BrainError as again:
                            # Live 2026-10-17: openrouter's chosen free model answered empty all morning, the
                            # provider cooled down after each try, and upstage took the rest of quality run #46
                            # (gemini had run out). A pooled provider tries its other models first.
                            if "empty response" not in str(again) or not PROVIDERS[pid].pool:
                                raise
                            msg = await self._pool_model(pid, formatted, tools, tool_choice, again)
                    except APIStatusError as e:
                        # 502/503/504 blips are common; one quick retry beats
                        # falling over to a slower brain.
                        if _out_of_memory(e) and PROVIDERS[pid].fallback_models:
                            msg = await self._smaller_model(pid, formatted, tools, tool_choice, e)
                        elif isinstance(e, RateLimitError) and PROVIDERS[pid].pool:
                            msg = await self._pool_model(pid, formatted, tools, tool_choice, e)
                        elif e.status_code in (500, 502, 503, 504):
                            logger.info(f"brain {pid} HTTP {e.status_code}, retrying once")
                            await asyncio.sleep(1.5)
                            msg = await self._call(pid, formatted, tools, tool_choice, images=True)
                        else:
                            raise
                except Exception as e:
                    reason = self._reason(e)
                    self._penalize(pid, e, reason)
                    failures.append(f"{PROVIDERS[pid].label}: {reason}")
                    logger.warning(f"brain {pid} failed: {reason}")
                    await self._emit({"type": "brain", "event": "failover", "provider": pid, "reason": reason})
                    continue
                self.health[pid] = Health(last_ok=time.time(), last_model=self.last_model.get(pid) or self.store.model(pid))
                if self.active != pid:
                    self.active = pid
                await self._emit(
                    {
                        "type": "brain",
                        "event": "answered",
                        "provider": pid,
                        "label": PROVIDERS[pid].label,
                        "model": self.last_model.get(pid) or self.store.model(pid),
                        "ms": round((time.monotonic() - started) * 1000),
                    }
                )
                return msg
            # Everything failed. If a provider frees up soon, wait once and retry.
            now = time.time()
            waits = [self.health[p].until - now for p in chain if self.health[p].until > now]
            soonest = min(waits) if waits else None
            if wait_rounds < 2 and soonest is not None and soonest <= 30:
                wait_rounds += 1
                await self._emit({"type": "notice", "text": f"All brains busy. Retrying in {int(soonest) + 1}s."})
                await asyncio.sleep(soonest + 0.5)
                continue
            raise BrainError("All brains failed. " + " | ".join(failures[:6]))
        raise BrainError("All brains failed.")

    def _format(self, messages, system_msgs, vision: bool) -> List[dict]:
        msgs = list(system_msgs or []) + list(messages)
        # format_messages mutates dicts; give it copies
        msgs = [m.model_copy(deep=True) if isinstance(m, Message) else dict(m) for m in msgs]
        return _normalize_messages(LLM.format_messages(msgs, supports_images=vision))

    async def _call(
        self, pid: str, messages: List[dict], tools, tool_choice, images: bool,
        model: Optional[str] = None, extra: Optional[Dict[str, Any]] = None,
    ):
        p = PROVIDERS[pid]
        self.last_model[pid] = model or self.store.model(pid)
        params: Dict[str, Any] = {
            "model": model or self.store.model(pid),
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if p.free_params and not self.store.key(pid):
            params.update(dict(p.free_params))
        if extra:
            params.update(extra)
        if not params["model"]:
            params["model"] = await self._auto_model(pid)
        if tools:
            params["tools"] = tools
            params["tool_choice"] = tool_choice.value if hasattr(tool_choice, "value") else tool_choice
        if p.max_request_tokens:
            before = len(messages)
            try:
                params["messages"], params["max_tokens"] = fit_request(messages, tools, p.max_request_tokens, self.max_tokens)
            except BrainError:
                if not tools:
                    raise
                # the full tool manual does not fit this brain: the same tools, their first sentences and their
                # parameters without prose (names, types, enums, required stay, so calls stay exact)
                small = compact_tools(tools)
                chosen = select_tools(small, messages, p.max_request_tokens, self.max_tokens)
                note = ""
                try:
                    params["messages"], params["max_tokens"] = fit_request(messages, chosen, p.max_request_tokens, self.max_tokens)
                except BrainError:
                    shorter = shorten_system(messages)
                    if shorter is None:
                        raise
                    chosen = select_tools(small, shorter, p.max_request_tokens, self.max_tokens)
                    params["messages"], params["max_tokens"] = fit_request(shorter, chosen, p.max_request_tokens, self.max_tokens)
                    note = ", the short persona"
                params["tools"] = chosen
                logger.info(f"brain {pid}: compact tool descriptions ({count_tokens(tools)} -> {count_tokens(small)} tokens)"
                            + (f", {len(chosen)} of {len(small)} tools chosen for this request" if len(chosen) < len(small) else "") + note)
            if len(params["messages"]) < before:
                logger.info(f"brain {pid}: trimmed {before - len(params['messages'])} old messages to fit {p.max_request_tokens} tokens")
        client = self._client(pid)
        try:
            try:
                resp = await client.chat.completions.create(**params)
            except APIStatusError as e:
                # Key-less tiers (Pollinations anonymous) answer plain chat but
                # return 402 for tools or reasoning params. Talking beats
                # silence: retry as plain chat; the caller gets text, no tool call.
                # The anonymous tier also rejects temperature and a large max_tokens
                # (measured 2026-09-30: temperature=0 → 402, max_tokens 8192 → 402, 1500 → 200).
                stripped = [k for k in ("tools", "tool_choice", "temperature", *dict(p.free_params)) if k in params]
                if e.status_code == 402 and not self.store.key(pid) and (stripped or params.get("max_tokens", 0) > KEYLESS_MAX_TOKENS):
                    logger.info(f"brain {pid} answers as plain chat on the key-less tier (HTTP 402; dropped {', '.join(stripped) or 'nothing'})")
                    for k in stripped:
                        params.pop(k)
                    params["max_tokens"] = min(params.get("max_tokens") or KEYLESS_MAX_TOKENS, KEYLESS_MAX_TOKENS)
                    resp = await client.chat.completions.create(**params)
                elif e.status_code == 413:
                    # Request too large: trim to half of what the provider says (or
                    # half of our own budget) and try once more.
                    budget = (_limit_from_413(e) or p.max_request_tokens or 8000) // 2
                    before = len(params["messages"])
                    params["messages"], params["max_tokens"] = fit_request(params["messages"], tools, budget, params["max_tokens"])
                    logger.info(f"brain {pid} HTTP 413: retrying with {before - len(params['messages'])} fewer messages, budget {budget}")
                    resp = await client.chat.completions.create(**params)
                else:
                    raise
        except BadRequestError as e:
            # Some models reject images or temperature; retry once stripped down.
            if images and _has_images(messages):
                text_only = LLM.format_messages(
                    [dict(m, content=_strip_images(m.get("content"))) for m in messages]
                )
                resp = await client.chat.completions.create(**dict(params, messages=text_only))
            elif "temperature" in str(e).lower():
                params.pop("temperature")
                resp = await client.chat.completions.create(**params)
            elif "reasoning" in str(e).lower() and "reasoning_effort" in params:
                params.pop("reasoning_effort")
                resp = await client.chat.completions.create(**params)
            elif _malformed_generation(e):
                # the model produced an unparsable tool call (Groq gpt-oss); a
                # fresh sample usually parses
                logger.info(f"brain {pid}: model output could not be parsed, sampling once more")
                resp = await client.chat.completions.create(**params)
            else:
                raise
        finally:
            await client.close()

        if not resp.choices or not resp.choices[0].message:
            raise BrainError("empty response")
        msg = resp.choices[0].message
        if tools and not msg.tool_calls and msg.content:
            # live 2026-10-14 (objective 224, attempt 2): an openrouter model wrote its tool call as text
            # ("<tool_call> <function=str_replace_editor> <parameter=path> ..."), the loop took the text for
            # the final answer and the task ended "SUCCESS" mid-work. A call written in text is a call.
            parsed, before = text_tool_calls(msg.content, tools)
            if parsed:
                logger.info(f"brain {pid}: {len(parsed)} tool call(s) written as text, taken as calls")
                msg.tool_calls = parsed
                msg.content = before or None
        for call in msg.tool_calls or []:
            call.id = _new_call_id()
            call.function.name = _clean_tool_name(call.function.name)
            call.function.arguments = _clean_arguments(call.function.name, call.function.arguments, tools)
        if not (msg.content or msg.tool_calls):
            if resp.choices[0].finish_reason == "length":
                raise BrainError("empty response (token budget spent on reasoning)")
            raise BrainError("empty response")
        if resp.usage:
            self.total_input_tokens += resp.usage.prompt_tokens or 0
            self.total_completion_tokens += resp.usage.completion_tokens or 0
        return msg

    def _model_for(self, pid: str) -> Optional[str]:
        """While the chosen model is out of quota, keep using the pool model that answered."""
        now = time.time()
        if self.model_cooldown.get((pid, self.store.model(pid)), 0) > now:
            other = self.pool_used.get(pid)
            if other and self.model_cooldown.get((pid, other), 0) <= now:
                return other
        return None

    async def pool_models(self, pid: str) -> List[str]:
        """The provider's chat models, listed live and kept for a few hours."""
        hit = self._pool.get(pid)
        if hit and time.time() - hit[0] < POOL_CACHE_S:
            return hit[1]
        try:
            ids = [m for m in await asyncio.wait_for(self.list_models(pid), 20) if not POOL_DENY.search(m)]
        except Exception:
            ids = []
        self._pool[pid] = (time.time(), ids)
        return ids

    async def _pool_model(self, pid, formatted, tools, tool_choice, original: Exception):
        """The chosen model is rate limited: each model has its own free quota, so try the
        provider's other chat models (at most POOL_TRIES) before the provider fails over."""
        tried_model = self.last_model.get(pid) or self.store.model(pid)
        empty = isinstance(original, BrainError)
        self.model_cooldown[(pid, tried_model)] = time.time() + _model_rest(pid, original, empty)
        tries = 0
        for candidate in sorted(await self.pool_models(pid), key=lambda m: (-kinship(m, tried_model), m)):
            if tries >= POOL_TRIES:
                break
            if candidate == tried_model or self.model_cooldown.get((pid, candidate), 0) > time.time():
                continue
            tries += 1
            try:
                msg = await self._call(pid, formatted, tools, tool_choice, images=True, model=candidate)
            except RateLimitError as e:
                self.model_cooldown[(pid, candidate)] = time.time() + _model_rest(pid, e, False)
                continue
            except (NotFoundError, BadRequestError):
                self.model_cooldown[(pid, candidate)] = time.time() + 3600.0
                continue
            except BrainError as e:
                if "empty response" not in str(e):
                    raise
                self.model_cooldown[(pid, candidate)] = time.time() + EMPTY_MODEL_COOLDOWN_S
                continue
            if self.pool_used.get(pid) != candidate:
                why = "answers empty" if empty else "is out of free quota"
                await self._emit({"type": "notice", "text": f"{PROVIDERS[pid].label}: {tried_model} {why}; answering with {candidate}."})
            self.pool_used[pid] = candidate
            return msg
        raise original

    async def _smaller_model(self, pid, formatted, tools, tool_choice, original: Exception):
        """Local model does not fit in RAM: step down to a smaller installed one."""
        try:
            installed = set(await self.list_models(pid))
        except Exception:
            raise original
        current = self.store.model(pid)
        for candidate in PROVIDERS[pid].fallback_models:
            if candidate == current or candidate not in installed:
                continue
            logger.info(f"brain {pid}: {current} does not fit in RAM, trying {candidate}")
            await self._emit({"type": "notice", "text": f"Low RAM: {PROVIDERS[pid].label} stepping down to {candidate}."})
            try:
                return await self._call(pid, formatted, tools, tool_choice, images=True, model=candidate)
            except APIStatusError as e:
                if not _out_of_memory(e):
                    raise
        raise original

    def _penalize(self, pid: str, e: Exception, reason: str) -> None:
        cooldown = 30.0
        if isinstance(e, (AuthenticationError, PermissionDeniedError)):
            cooldown = 3600.0
        elif isinstance(e, NotFoundError):
            cooldown = 900.0
        elif isinstance(e, RateLimitError) and _daily_quota(e) and not PROVIDERS.get(pid, Provider).pool:
            # EVOLUTION_PLAN wave 3 (directions 235, 278): a spent daily quota does not come back in 15 s. Retrying it
            # on every request until midnight cost each one a round trip and a failover; it rests until its reset. A
            # pooled provider's quota is per model: those models rest one by one (_pool_model), not the provider
            cooldown = _until_quota_reset(pid)
            reason = f"{reason} (daily quota spent: resting until it resets)"
        elif isinstance(e, RateLimitError):
            # free tiers usually free up within seconds; keep it short so the
            # "wait and retry" round can use it again
            cooldown = _retry_after(e) or 15.0
        elif isinstance(e, APIConnectionError) and not isinstance(e, APITimeoutError):
            cooldown = 60.0
        elif isinstance(e, BadRequestError):
            cooldown = 15.0 if _malformed_generation(e) else 120.0  # a bad sample is not a broken provider
        elif isinstance(e, APIStatusError) and e.status_code >= 500:
            cooldown = 15.0  # short, so "all busy, wait and retry" can kick in
        self.health[pid] = Health(until=time.time() + cooldown, reason=reason)

    @staticmethod
    def _reason(e: Exception) -> str:
        if isinstance(e, AuthenticationError):
            return "invalid API key"
        if isinstance(e, PermissionDeniedError):
            return "key not allowed (403)"
        if isinstance(e, RateLimitError):
            return "rate limited"
        if isinstance(e, NotFoundError):
            return "model not found"
        if isinstance(e, APITimeoutError):
            return "timed out"
        if isinstance(e, APIConnectionError):
            return "unreachable"
        if isinstance(e, APIStatusError):
            body = e.body if isinstance(e.body, dict) else {}
            detail = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("message")
            return f"HTTP {e.status_code}: {str(detail or e.message)[:160]}"
        return str(e)[:160] or e.__class__.__name__

    async def _emit(self, event: dict) -> None:
        for listener in list(self.listeners):
            try:
                await listener(event)
            except Exception:
                pass


def _out_of_memory(e: Exception) -> bool:
    return "more system memory" in str(e).lower() or "out of memory" in str(e).lower()


def _strip_images(content):
    if isinstance(content, list):
        texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        return "\n".join(t for t in texts if t) or "(image omitted)"
    return content


_DAILY = re.compile(r"per[ _-]?day|perday|daily|requests per day|RPD", re.I)


def _daily_quota(e: Exception) -> bool:
    """A 429 that says a per-day quota is spent (Gemini: "GenerateRequestsPerDayPerProjectPerModel"; Groq: "requests
    per day (RPD)"), as opposed to a per-minute burst."""
    text = f"{e} {getattr(e, 'body', '')}"
    return bool(_DAILY.search(text))


def _until_quota_reset(pid: str, now: Optional[float] = None) -> float:
    """Seconds until a provider's daily quota resets: Google resets at midnight Pacific time, the others at midnight
    UTC. At least 60 s, at most a day."""
    import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Los_Angeles") if pid == "gemini" else datetime.timezone.utc
    t = datetime.datetime.fromtimestamp(now if now is not None else time.time(), tz)
    nxt = (t + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60.0, min(86400.0, (nxt - t).total_seconds()))


def _model_rest(pid: str, e: Exception, empty: bool) -> float:
    """How long one pooled model rests: an empty answer a short while, a spent daily quota until it resets (wave 3),
    a per-minute limit what the server asks or POOL_MODEL_COOLDOWN_S."""
    if empty:
        return EMPTY_MODEL_COOLDOWN_S
    if isinstance(e, RateLimitError) and _daily_quota(e):
        return _until_quota_reset(pid)
    return (_retry_after(e) if isinstance(e, APIStatusError) else None) or POOL_MODEL_COOLDOWN_S


def _retry_after(e: APIStatusError) -> Optional[float]:
    try:
        v = e.response.headers.get("retry-after")
        return min(float(v), 3600.0) if v else None
    except Exception:
        return None


_router: Optional[BrainRouter] = None


def get_router() -> BrainRouter:
    global _router
    if _router is None:
        _router = BrainRouter()
    return _router

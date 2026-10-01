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
from typing import Any, Dict, List, Optional

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
            max_request_tokens=8192,  # default num_ctx of the small local models
        ),
    ]
}

DEFAULT_ORDER = [
    "gemini", "upstage", "groq", "cerebras", "openrouter", "mistral", "github",
    "anthropic", "openai", "pollinations", "ollama",
]

_ID_ALPHABET = string.ascii_letters + string.digits


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

    @classmethod
    def load(cls) -> "BrainStore":
        store = cls()
        try:
            data = json.loads(BRAINS_FILE.read_text())
            store.settings = {
                k: v for k, v in (data.get("providers") or {}).items() if k in PROVIDERS
            }
            saved = [p for p in data.get("order") or [] if p in PROVIDERS]
            store.order = saved + [p for p in DEFAULT_ORDER if p not in saved]
        except FileNotFoundError:
            pass
        except Exception as e:  # corrupt file: keep defaults, do not crash boot
            logger.error(f"brains.json unreadable, using defaults: {e}")
        return store

    def save(self) -> None:
        BRAINS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = BRAINS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"order": self.order, "providers": self.settings}, indent=2))
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
        return {"order": list(self.store.order), "providers": out, "active": self.active}

    def update(self, changes: Dict[str, Dict[str, Any]], order: Optional[List[str]]) -> None:
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
        if self.preferred in chain:
            chain = [self.preferred] + [p for p in chain if p != self.preferred]
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
                    try:
                        msg = await self._call(pid, formatted, tools, tool_choice, images=True)
                    except BrainError as e:
                        # Reasoning-only / empty replies are usually one-off glitches.
                        if "empty response" not in str(e):
                            raise
                        logger.info(f"brain {pid} returned an empty reply, retrying once with low reasoning")
                        msg = await self._call(
                            pid, formatted, tools, tool_choice, images=True,
                            extra={"reasoning_effort": "low"},
                        )
                    except APIStatusError as e:
                        # 502/503/504 blips are common; one quick retry beats
                        # falling over to a slower brain.
                        if _out_of_memory(e) and PROVIDERS[pid].fallback_models:
                            msg = await self._smaller_model(pid, formatted, tools, tool_choice, e)
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
                self.health[pid] = Health(last_ok=time.time(), last_model=self.store.model(pid))
                if self.active != pid:
                    self.active = pid
                await self._emit(
                    {
                        "type": "brain",
                        "event": "answered",
                        "provider": pid,
                        "label": PROVIDERS[pid].label,
                        "model": self.store.model(pid),
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
            params["messages"], params["max_tokens"] = fit_request(messages, tools, p.max_request_tokens, self.max_tokens)
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

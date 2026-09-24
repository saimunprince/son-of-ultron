"""Brain router tests against a real local OpenAI-compatible mock server."""

import asyncio
import dataclasses
import json
import os
import socket
import tempfile
import threading
import time

os.environ.setdefault("OPENMANUS_DISABLE_BROWSER_USE", "1")
os.environ.setdefault("SYRAX_BRAINS_FILE", os.path.join(tempfile.mkdtemp(), "brains.json"))

import pytest  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.schema import Message  # noqa: E402
from syrax import brains  # noqa: E402
from syrax.brains import BrainError, BrainRouter, BrainStore  # noqa: E402

mock = FastAPI()
BEHAVIOR: dict = {}
SEEN: list = []

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "python_execute",
            "description": "run",
            "parameters": {"type": "object", "properties": {"code": {"type": "string"}}},
        },
    }
]


def completion(content=None, tool=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [
            {"id": "call_weird-ID::1", "type": "function", "function": {"name": tool, "arguments": '{"code":"print(1)"}'}}
        ]
    return {
        "id": "x", "object": "chat.completion", "created": 1, "model": "m",
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }


@mock.post("/{pid}/v1/chat/completions")
async def chat(pid: str, request: Request):
    body = await request.json()
    SEEN.append((pid, body, request.headers.get("authorization")))
    mode = BEHAVIOR.get(pid, "ok")
    if mode == "429":
        return JSONResponse({"error": {"message": "slow down"}}, status_code=429, headers={"retry-after": "1"})
    if mode == "401":
        return JSONResponse({"error": {"message": "bad key"}}, status_code=401)
    if mode == "500":
        return JSONResponse({"error": {"message": "boom"}}, status_code=500)
    if mode == "oom-7b" and body["model"] == "alpha-model":
        return JSONResponse({"error": {"message": "model requires more system memory (4.3 GiB) than is available (3.6 GiB)"}}, status_code=500)
    if mode == "oom-7b":
        return completion(content=f"small model {body['model']} ok")
    if mode == "empty-once":
        BEHAVIOR[pid] = "ok"
        return completion(content=None)
    if mode == "reasoning-hog":
        if body.get("reasoning_effort") == "low":
            return completion(content="short answer")
        c = completion(content=None)
        c["choices"][0]["finish_reason"] = "length"
        return c
    if mode == "no-reasoning-param":
        if "reasoning_effort" in body:
            return JSONResponse({"error": {"message": "Unrecognized request argument: reasoning_effort"}}, status_code=400)
        return completion(content="plain ok")
    if mode == "502-once":
        BEHAVIOR[pid] = "ok"
        return JSONResponse({"error": {"message": "bad gateway"}}, status_code=502)
    if mode == "no-images":
        has_img = any(isinstance(m.get("content"), list) for m in body["messages"])
        if has_img:
            return JSONResponse({"error": {"message": "image input not supported"}}, status_code=400)
        return completion(content=f"{pid} text-only ok")
    if mode == "tool":
        return completion(content="hisab", tool="python_execute")
    return completion(content=f"{pid} says hi")


@mock.get("/{pid}/v1/models")
async def models(pid: str):
    return {"object": "list", "data": [{"id": "a:free", "object": "model"}, {"id": "b-paid", "object": "model"}]}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def base():
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(mock, host="127.0.0.1", port=port, log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True


@pytest.fixture
def router(base, monkeypatch, tmp_path):
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "brains.json")
    fake = {}
    for pid, vision in [("alpha", False), ("beta", True), ("gamma", False)]:
        fake[pid] = brains.Provider(
            id=pid, label=pid.upper(), base_url=f"{base}/{pid}/v1", tier="free",
            default_model=f"{pid}-model", key_required=(pid != "gamma"), vision=vision,
        )
    fake["omega"] = dataclasses.replace(fake["alpha"], id="omega", label="OMEGA", model_filter=r":free$", base_url=f"{base}/omega/v1")
    monkeypatch.setattr(brains, "PROVIDERS", fake)
    monkeypatch.setattr(brains, "DEFAULT_ORDER", ["alpha", "beta", "gamma", "omega"])
    store = BrainStore(order=["alpha", "beta", "gamma", "omega"], settings={
        "alpha": {"api_key": "key-alpha"}, "beta": {"api_key": "key-beta"},
    })
    BEHAVIOR.clear()
    SEEN.clear()
    return BrainRouter(store)


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def ask(router, messages=None, system=None, tools=TOOLS):
    messages = messages or [Message.user_message("hi")]
    return run(router.ask_tool(messages=messages, system_msgs=system, tools=tools))


def test_first_healthy_provider_answers(router):
    msg = ask(router)
    assert msg.content == "alpha says hi"
    assert SEEN[0][2] == "Bearer key-alpha"
    assert router.active == "alpha"


def test_failover_on_rate_limit_then_cooldown(router):
    BEHAVIOR["alpha"] = "429"
    assert ask(router).content == "beta says hi"
    SEEN.clear()
    assert ask(router).content == "beta says hi"
    assert [p for p, _, _ in SEEN] == ["beta"]  # alpha skipped while cooling down
    assert router.describe()["providers"][0]["status"] == "cooldown"


def test_bad_key_and_server_error_fail_over(router):
    BEHAVIOR["alpha"] = "401"
    BEHAVIOR["beta"] = "500"
    msg = ask(router)
    assert msg.content == "gamma says hi"  # keyless provider takes over
    assert router.health["alpha"].reason == "invalid API key"


def test_all_fail_raises_readable_error(router):
    for p in ("alpha", "beta", "gamma"):
        BEHAVIOR[p] = "401"
    with pytest.raises(BrainError) as e:
        ask(router)
    assert "ALPHA: invalid API key" in str(e.value)


def test_short_rate_limit_waits_and_retries(router):
    router.store.settings["beta"]["enabled"] = False
    router.store.settings["gamma"] = {"enabled": False}
    BEHAVIOR["alpha"] = "429"

    async def flip():
        await asyncio.sleep(0.3)
        BEHAVIOR["alpha"] = "ok"

    async def both():
        return (await asyncio.gather(router.ask_tool(messages=[Message.user_message("hi")], tools=TOOLS), flip()))[0]

    assert run(both()).content == "alpha says hi"


def test_tool_call_ids_normalized_and_systems_merged(router):
    BEHAVIOR["alpha"] = "tool"
    msgs = [Message.user_message("do it"), Message.system_message("MCP rules")]
    msg = ask(router, messages=msgs, system=[Message.system_message("You are SYRAX")])
    call = msg.tool_calls[0]
    assert len(call.id) == 9 and call.id.isalnum()
    sent = SEEN[0][1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert "You are SYRAX" in sent[0]["content"] and "MCP rules" in sent[0]["content"]
    assert SEEN[0][1]["tools"][0]["function"]["name"] == "python_execute"


def test_image_rejected_retries_text_only(router):
    router.store.settings["alpha"]["enabled"] = False
    BEHAVIOR["beta"] = "no-images"
    msgs = [Message.user_message("look", base64_image="aGVsbG8=")]
    assert ask(router, messages=msgs).content == "beta text-only ok"


def test_models_listing_respects_filter(router):
    assert run(router.list_models("omega", "k")) == ["a:free"]
    assert run(router.list_models("alpha")) == ["a:free", "b-paid"]


def test_store_persists_without_leaking_keys(router):
    router.update({"alpha": {"api_key": "sk-secret-9999", "model": "alpha-2"}}, ["beta", "alpha"])
    data = json.loads(brains.BRAINS_FILE.read_text())
    assert data["order"][:2] == ["beta", "alpha"]
    assert oct(brains.BRAINS_FILE.stat().st_mode & 0o777) == "0o600"
    desc = router.describe()
    assert "sk-secret-9999" not in json.dumps(desc)
    assert desc["providers"][1]["model"] == "alpha-2"


def test_provider_test_reports_tool_support(router):
    BEHAVIOR["alpha"] = "tool"
    r = run(router.test("alpha"))
    assert r["ok"] and r["tools"] is False  # mock calls python_execute, not report
    BEHAVIOR["alpha"] = "401"
    r = run(router.test("alpha"))
    assert not r["ok"] and r["error"] == "invalid API key"


def test_transient_5xx_retries_same_provider(router):
    BEHAVIOR["alpha"] = "502-once"
    assert ask(router).content == "alpha says hi"
    assert [p for p, _, _ in SEEN] == ["alpha", "alpha"]


def test_tool_name_and_argument_sanitising():
    from syrax.brains import _clean_arguments, _clean_tool_name, _normalize_messages

    assert _clean_tool_name("browser_exec<|channel|>commentary") == "browser_exec"
    assert _clean_tool_name(" python_execute ") == "python_execute"
    tools = [{"type": "function", "function": {"name": "browser_exec", "parameters": {
        "type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}}]
    assert json.loads(_clean_arguments("browser_exec", 'new_tab("x")', tools)) == {"code": 'new_tab("x")'}
    assert json.loads(_clean_arguments("browser_exec", '{"code": "1"}', tools)) == {"code": "1"}
    assert json.loads(_clean_arguments("other", "garbage", tools)) == {"input": "garbage"}
    assert _clean_arguments("x", "", tools) == "{}"
    poisoned = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "a", "type": "function",
            "function": {"name": "browser_exec<|channel|>x", "arguments": "raw code"}}]},
        {"role": "tool", "tool_call_id": "a", "name": "browser_exec<|channel|>x", "content": "Error"},
    ]
    out = _normalize_messages(poisoned)
    fn = out[1]["tool_calls"][0]["function"]
    assert fn["name"] == "browser_exec" and json.loads(fn["arguments"]) == {"input": "raw code"}
    assert out[2]["name"] == "browser_exec" and out[1]["content"] == ""


def test_optional_key_provider_switches_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(brains, "BRAINS_FILE", tmp_path / "b.json")
    store = BrainStore()
    r = BrainRouter(store)
    poll = brains.PROVIDERS["pollinations"]
    assert str(r._client("pollinations").base_url).startswith(poll.base_url.rstrip("/"))
    assert store.model("pollinations") == "openai-fast"
    store.settings["pollinations"] = {"api_key": "pk_test"}
    assert str(r._client("pollinations").base_url).startswith("https://gen.pollinations.ai/v1")
    assert store.model("pollinations") == "openai"


def test_out_of_memory_steps_down_to_smaller_installed_model(router, monkeypatch):
    fake = dict(brains.PROVIDERS)
    fake["alpha"] = dataclasses.replace(fake["alpha"], fallback_models=("missing:3b", "b-paid"))
    monkeypatch.setattr(brains, "PROVIDERS", fake)
    BEHAVIOR["alpha"] = "oom-7b"
    assert ask(router).content == "small model b-paid ok"  # skipped the uninstalled one


def test_server_errors_get_short_cooldown_so_retry_round_happens(router):
    router.store.settings["beta"]["enabled"] = False
    router.store.settings["gamma"] = {"enabled": False}
    BEHAVIOR["alpha"] = "500"

    async def flip():
        await asyncio.sleep(2.5)  # after the in-place retry also failed
        BEHAVIOR["alpha"] = "ok"

    async def both():
        return (await asyncio.gather(router.ask_tool(messages=[Message.user_message("hi")], tools=TOOLS), flip()))[0]

    assert run(both()).content == "alpha says hi"


def test_empty_reply_retries_same_provider(router):
    BEHAVIOR["alpha"] = "empty-once"
    assert ask(router).content == "alpha says hi"
    assert [p for p, _, _ in SEEN] == ["alpha", "alpha"]


def test_reasoning_hog_retries_with_low_effort(router):
    BEHAVIOR["alpha"] = "reasoning-hog"
    assert ask(router).content == "short answer"
    assert SEEN[-1][1].get("reasoning_effort") == "low"


def test_free_params_sent_only_without_key_and_dropped_if_rejected(router, monkeypatch):
    fake = dict(brains.PROVIDERS)
    fake["gamma"] = dataclasses.replace(fake["gamma"], free_params=(("reasoning_effort", "low"),))
    monkeypatch.setattr(brains, "PROVIDERS", fake)
    router.store.settings["alpha"]["enabled"] = False
    router.store.settings["beta"]["enabled"] = False
    BEHAVIOR["gamma"] = "no-reasoning-param"
    assert ask(router).content == "plain ok"
    assert SEEN[0][1].get("reasoning_effort") == "low" and "reasoning_effort" not in SEEN[1][1]

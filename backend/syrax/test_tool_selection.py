"""Live 2026-10-31: with 43 tools, even the compact manual left the request at ~8,619 tokens, over Groq's 8,000, so
Groq answered nothing and a Gemini timeout left Pollinations' one reply per 45 s. For a brain the compact manual does not
fit, the tools are now chosen: the essential ones always, then those whose words the request shares, while they fit.
A brain that fits the full or compact manual still gets every tool."""

from syrax.brains import ESSENTIAL_TOOLS, count_tokens, fit_request, select_tools


def tool(name, desc, props=("x",)):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {p: {"type": "string"} for p in props}}}}


TOOLS = [tool("terminate", "End the task"), tool("ask_human", "Ask the human"), tool("python_execute", "Run python code"),
         tool("weather", "Current weather and forecast for a place"), tool("pdf_text", "Read the text of a PDF file"),
         tool("flight_search", "Live flight options between two cities on a date " + "detail " * 300),
         tool("scene", "Set the computer up for coding mode, research mode or chill mode")]


def msgs(text):
    return [{"role": "system", "content": "You are SYRAX. " * 40}, {"role": "user", "content": text}]


def test_the_request_s_tools_and_the_essentials_are_kept_and_it_fits():
    m = msgs("what is the weather in Dhaka?")
    budget = 1100  # every tool would need ~1,260 with these messages; all but flight_search fit
    chosen = select_tools(TOOLS, m, budget, 512)
    names = [t["function"]["name"] for t in chosen]
    assert {"terminate", "ask_human", "python_execute"} <= set(names) and "weather" in names
    assert "flight_search" not in names
    fit_request(m, chosen, budget, 512)  # does not raise


def test_order_is_kept_and_nothing_is_dropped_when_all_fit():
    m = msgs("coding mode please")
    chosen = select_tools(TOOLS, m, 100000, 512)
    assert chosen == TOOLS


def test_essentials_are_a_known_set():
    assert {"terminate", "ask_human", "python_execute", "desktop"} <= ESSENTIAL_TOOLS

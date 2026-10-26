"""Play something on YouTube: the first video a search finds, opened on its watch page, where it starts on its own.

Prebuilt SYRAX skill. Live 2026-10-25: "play some random music" ran SYRAX's own `youtube_open`, which opens a search
results page, and nothing played; the answer said "Music summoned." This finds the video first (YouTube's own results
page, no key) and opens that video. Whether it really plays is read afterwards with `desktop` media status.
"""

import asyncio
import json
import re
import urllib.parse
import urllib.request
import webbrowser
from typing import Callable, ClassVar, List, Tuple

from app.tool.base import BaseTool, ToolResult

SEARCH = "https://www.youtube.com/results?search_query={q}"
WATCH = "https://www.youtube.com/watch?v={id}"
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
# one result in the page's initial data, as the live page of 2026-10-26 had it:
# "videoRenderer":{"videoId":"rFZHOHl-L8A","thumbnail":{...},"title":{"runs":[{"text":"lofi hip hop radio ..."}]
VIDEO = re.compile(r'"videoRenderer":\{"videoId":"([A-Za-z0-9_-]{11})".{0,2500}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.){1,200})"',
                   re.S)


def fetch(url: str, timeout: float = 15.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def first_videos(html: str, n: int = 3) -> List[Tuple[str, str]]:
    """The first `n` distinct (video id, title) pairs of a results page, in the page's order."""
    out: List[Tuple[str, str]] = []
    for m in VIDEO.finditer(html or ""):
        vid = m.group(1)
        if any(vid == v for v, _ in out):
            continue
        try:
            title = json.loads('"' + m.group(2) + '"')
        except ValueError:
            title = m.group(2)
        out.append((vid, " ".join(title.split())))
        if len(out) >= n:
            break
    return out


def play(query: str, opener: Callable[[str], bool] = webbrowser.open) -> str:
    q = " ".join(str(query or "").split())
    if not q:
        raise ValueError("a query is required, e.g. lofi hip hop")
    found = first_videos(fetch(SEARCH.format(q=urllib.parse.quote_plus(q))))
    if not found:
        raise LookupError(f"YouTube found no video for {q!r}")
    vid, title = found[0]
    url = WATCH.format(id=vid)
    if not opener(url):
        raise RuntimeError(f"the browser did not open {url}")
    return (f"Opened '{title}' ({url}) in the browser; a video page starts playing on its own unless the browser "
            "blocks autoplay. Whether it plays: `desktop` media status.")


class Skill(BaseTool):
    name: ClassVar[str] = "youtube_play"
    description: ClassVar[str] = (
        "Play a video or music on YouTube: finds the first video for the query and opens its watch page in the "
        "browser, where it starts on its own. Use it for 'play ...' requests (youtube_open only shows search "
        "results); then check with desktop media status that it plays.")
    risk: ClassVar[str] = "SYSTEM"  # it opens a window on the human's screen: a conversation does it, own work never
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "What to play, e.g. 'lofi hip hop' or 'Sajde Faheem Abdullah'"}},
        "required": ["query"],
    }

    async def execute(self, query: str) -> ToolResult:
        try:
            return ToolResult(output=await asyncio.to_thread(play, query))
        except Exception as e:
            return ToolResult(error=f"youtube_play: {e}")

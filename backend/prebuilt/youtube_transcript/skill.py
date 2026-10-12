"""The transcript of a YouTube video, so SYRAX can summarise, quote or search it.

Prebuilt SYRAX skill on youtube-transcript-api (approved by the owner on
2026-10-12, pinned to 1.2.4). It reads the video's public captions; no key,
nothing is downloaded but text.
"""

import asyncio
import re
from typing import Any, Callable, ClassVar, Iterable, Optional

from app.tool.base import BaseTool, ToolResult

MAX_CHARS = 20000
VIDEO_ID = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
BARE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def video_id(url: str) -> str:
    text = str(url or "").strip()
    if BARE_ID.match(text):
        return text
    m = VIDEO_ID.search(text)
    if not m:
        raise ValueError(f"no YouTube video id in {url!r}")
    return m.group(1)


def transcript(url: str, languages: Iterable[str] = ("en", "bn", "hi"), max_chars: int = MAX_CHARS,
               fetch: Optional[Callable[..., Any]] = None) -> str:
    vid = video_id(url)
    if fetch is None:
        from youtube_transcript_api import YouTubeTranscriptApi

        fetch = YouTubeTranscriptApi().fetch
    try:
        rows = fetch(vid, languages=list(languages)).to_raw_data()
    except Exception as e:
        name = type(e).__name__
        if name in ("TranscriptsDisabled", "NoTranscriptFound"):
            raise LookupError(f"video {vid} has no captions in {', '.join(languages)}")
        raise
    text = " ".join(str(r.get("text") or "").replace("\n", " ").strip() for r in rows if r.get("text"))
    end = max((float(r.get("start") or 0) + float(r.get("duration") or 0) for r in rows), default=0.0)
    head = f"Transcript of https://www.youtube.com/watch?v={vid} ({len(rows)} captions, about {round(end / 60)} min):"
    if len(text) > max_chars:
        text = text[:max_chars] + f" [... cut at {max_chars} characters]"
    return head + "\n" + text


class Skill(BaseTool):
    name: ClassVar[str] = "youtube_transcript"
    description: ClassVar[str] = ("Get the transcript (captions) of a YouTube video from its link or id, to summarise it, "
                                  "quote it or answer questions about it.")
    risk: ClassVar[str] = "EXTERNAL_READ"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "YouTube link or 11-character video id"},
            "languages": {"type": "string", "description": "caption languages in order of preference, comma-separated (default en,bn,hi)"},
        },
        "required": ["url"],
    }

    async def execute(self, url: str, languages: Optional[str] = None) -> ToolResult:
        langs = [x.strip() for x in (languages or "en,bn,hi").split(",") if x.strip()]
        try:
            return ToolResult(output=await asyncio.to_thread(transcript, url, langs))
        except Exception as e:
            return ToolResult(error=f"youtube_transcript: {e}")

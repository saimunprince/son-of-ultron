"""Read the text of a PDF: its page count, title, and the text of a page range.

Prebuilt SYRAX skill on pypdf (approved by the owner on 2026-10-12, pinned to
6.19.0). Read only: it never writes the file.
"""

import asyncio
from pathlib import Path
from typing import ClassVar, Optional

from app.tool.base import BaseTool, ToolResult

MAX_CHARS = 20000


def read_pdf(path: str, first: Optional[int] = 1, last: Optional[int] = None, max_chars: int = MAX_CHARS) -> str:
    from pypdf import PdfReader

    p = Path(str(path or "")).expanduser()
    if not str(path or "").strip() or not p.is_file():
        raise FileNotFoundError(f"no file at {path!r}")
    if p.suffix.lower() != ".pdf":
        raise ValueError(f"{p.name} is not a PDF")
    reader = PdfReader(str(p))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            raise ValueError("the PDF is password-protected")
    n = len(reader.pages)
    first = max(1, int(first or 1))
    last = min(n, int(last or n))
    if first > last:
        raise ValueError(f"pages {first}-{last} are outside 1-{n}")
    title = ""
    try:
        title = (reader.metadata.title or "") if reader.metadata else ""
    except Exception:
        title = ""
    parts, used, upto = [], 0, first - 1
    for i in range(first - 1, last):
        text = (reader.pages[i].extract_text() or "").strip()
        parts.append(f"--- page {i + 1} ---\n{text}")
        used += len(text)
        upto = i + 1
        if used >= max_chars:
            break
    body = "\n".join(parts)
    head = f"{p.name}: {n} page(s)" + (f", title {title!r}" if title else "") + f"; showing pages {first}-{upto}"
    if len(body) > max_chars:
        body = body[:max_chars] + f"\n[... cut at {max_chars} characters; ask for pages after {upto} to read on]"
    elif upto < last:
        body += f"\n[... stopped after page {upto}; ask for pages {upto + 1}-{last}]"
    return head + "\n" + body


class Skill(BaseTool):
    name: ClassVar[str] = "pdf_text"
    description: ClassVar[str] = ("Read a PDF file: page count, title and the text of its pages (optionally a page range). "
                                  "Use it to summarise, quote or answer questions about a PDF.")
    risk: ClassVar[str] = "READ_ONLY"
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "full path of the PDF"},
            "first": {"type": "integer", "description": "first page to read (default 1)"},
            "last": {"type": "integer", "description": "last page to read (default: the end)"},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, first: Optional[int] = 1, last: Optional[int] = None) -> ToolResult:
        try:
            return ToolResult(output=await asyncio.to_thread(read_pdf, path, first, last))
        except Exception as e:
            return ToolResult(error=f"pdf_text: {e}")

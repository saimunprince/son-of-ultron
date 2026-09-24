"""SYRAX voice: neural text-to-speech and speech-to-text, free.

TTS : Microsoft Edge neural voices via edge-tts (free, no key).
STT : Groq Whisper when a Groq key is saved in the BRAIN panel (free tier,
      fast), otherwise local faster-whisper (offline, English model).
"""

from __future__ import annotations

import asyncio
import io
import os
import re
import threading
import time
from typing import Optional

import httpx

from app.logger import logger

TTS_VOICE = os.getenv("SYRAX_TTS_VOICE", "en-US-ChristopherNeural")
TTS_RATE = os.getenv("SYRAX_TTS_RATE", "-4%")
TTS_PITCH = os.getenv("SYRAX_TTS_PITCH", "-8Hz")
WHISPER_MODEL = os.getenv("SYRAX_WHISPER_MODEL", "small.en")
MAX_TTS_CHARS = 900
MAX_AUDIO_BYTES = 12 * 1024 * 1024

# Bias recognition towards the wake word's spelling.
STT_PROMPT = "SYRAX. Hey SYRAX. Ultron."


def speakable(text: str) -> str:
    """Turn a console reply into something worth hearing."""
    text = re.sub(r"```.*?```", " The code is on screen. ", text or "", flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", " link on screen ", text)
    text = re.sub(r"[*_#>|~]+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_TTS_CHARS:
        cut = text[:MAX_TTS_CHARS]
        text = cut[: cut.rfind(". ") + 1] or cut
    return text


async def synthesize(text: str) -> bytes:
    import edge_tts

    text = speakable(text)
    if not text:
        return b""
    communicate = edge_tts.Communicate(text, TTS_VOICE, rate=TTS_RATE, pitch=TTS_PITCH)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


class LocalWhisper:
    """Lazy, thread-safe faster-whisper wrapper."""

    def __init__(self, size: str = WHISPER_MODEL):
        self.size = size
        self._model = None
        self._lock = threading.Lock()
        self.status = "cold"
        self.error = ""

    def load(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self.status = "loading"
                started = time.time()
                try:
                    self._model = WhisperModel(self.size, device="cpu", compute_type="int8")
                except Exception as e:
                    self.status = "error"
                    self.error = str(e)
                    raise
                self.status = "ready"
                logger.info(f"Whisper {self.size} ready in {time.time() - started:.1f}s")
        return self._model

    def transcribe(self, audio: bytes) -> str:
        model = self.load()
        with self._lock:
            segments, _ = model.transcribe(
                io.BytesIO(audio),
                language="en",
                beam_size=1,
                vad_filter=True,
                condition_on_previous_text=False,
                initial_prompt=STT_PROMPT,
            )
            return " ".join(s.text for s in segments).strip()


local_whisper = LocalWhisper()


async def groq_transcribe(audio: bytes, key: str) -> str:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {key}"},
            files={"file": ("speech.wav", audio, "audio/wav")},
            data={
                "model": "whisper-large-v3-turbo",
                "language": "en",
                "prompt": STT_PROMPT,
                "response_format": "json",
                "temperature": "0",
            },
        )
        r.raise_for_status()
        return str(r.json().get("text") or "").strip()


# Whisper's classic hallucinations on silence / noise
_HALLUCINATIONS = {
    "you", "thank you", "thanks for watching", "thank you for watching",
    "bye", "okay", ".", "", "thanks", "subscribe",
}


def _clean(text: str) -> str:
    t = text.strip()
    if t.lower().strip(" .!?") in _HALLUCINATIONS:
        return ""
    return t


async def transcribe(audio: bytes, groq_key: Optional[str]) -> dict:
    if not audio:
        return {"text": "", "engine": "none", "ms": 0}
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError("audio too long")
    started = time.time()
    if groq_key:
        try:
            text = await groq_transcribe(audio, groq_key)
            ms = int((time.time() - started) * 1000)
            logger.info(f"STT groq {ms}ms: {text[:80]!r}")
            return {"text": _clean(text), "engine": "groq", "ms": ms}
        except Exception as e:
            logger.warning(f"Groq STT failed, using local Whisper: {e}")
    text = await asyncio.to_thread(local_whisper.transcribe, audio)
    ms = int((time.time() - started) * 1000)
    logger.info(f"STT whisper-{local_whisper.size} {ms}ms: {text[:80]!r}")
    return {"text": _clean(text), "engine": f"whisper-{local_whisper.size}", "ms": ms}

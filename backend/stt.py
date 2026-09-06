"""Speech-to-text for Telegram voice notes (.ogg/Opus) via Gemini's native audio."""
from __future__ import annotations
import os
from pathlib import Path
from backend import llm


async def transcribe_ogg(path: str | Path) -> str:
    try:
        data = Path(path).read_bytes()
    except Exception:
        return ""
    out = await llm.audio(data, "Transcribe this voice note verbatim. Indian English. Output only the words spoken.",
                          mime="audio/ogg")
    if not out and os.getenv("DEMO_MODE", "1") == "1":
        return os.getenv("DEMO_VOICE_TEXT", "I'll send Rahul the deck tonight, and call Amma tomorrow evening")
    return out or ""

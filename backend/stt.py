"""Speech-to-text for Telegram voice notes (.ogg/Opus) via Gemini's native audio."""
from __future__ import annotations
from pathlib import Path
from backend import llm


async def transcribe_ogg(path: str | Path) -> str:
    try:
        data = Path(path).read_bytes()
    except Exception:
        return ""
    out = await llm.audio(data, "Transcribe this voice note verbatim. Indian English. Output only the words spoken.",
                          mime="audio/ogg")
    return out or ""

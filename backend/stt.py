"""
Speech-to-text for Telegram voice notes (.ogg / Opus) via Groq's Whisper API.
Set GROQ_API_KEY in .env. Free tier is plenty for a demo.

    uv add groq
"""
from __future__ import annotations
import os, asyncio
from pathlib import Path

async def transcribe_ogg(path: str | Path) -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        return ""  # adapter shows a friendly line when this is empty
    try:
        from groq import Groq
    except ImportError:
        return ""
    client = Groq(api_key=key)

    def _run():
        with open(path, "rb") as f:
            r = client.audio.transcriptions.create(
                file=(Path(path).name, f.read()),
                model="whisper-large-v3-turbo",
                response_format="text",
                language="en",
            )
        return r if isinstance(r, str) else getattr(r, "text", "")

    try:
        return (await asyncio.to_thread(_run)).strip()
    except Exception:
        return ""

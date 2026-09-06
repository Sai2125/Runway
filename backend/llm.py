"""
Single LLM gateway for Runway — Gemini (text, vision, audio) with graceful fallback.

Env:  GEMINI_API_KEY   (required for real extraction/voice/vision/audio)
      GEMINI_MODEL     (default gemini-3.6-flash)
      GEMINI_BASE_URL  (optional; custom/proxied endpoint)

Every function returns None when Gemini is unavailable or errors, so callers
can fall back to heuristics. Nothing here ever raises to the caller.
"""
from __future__ import annotations
import os, logging

log = logging.getLogger("runway.llm")

_client = None
_types = None
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


def _get_client():
    global _client, _types
    if _client is not None:
        return _client
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types
        opts = {"base_url": os.getenv("GEMINI_BASE_URL")} if os.getenv("GEMINI_BASE_URL") else None
        _client = genai.Client(api_key=key, http_options=opts)
        _types = types
        return _client
    except Exception as e:  # pragma: no cover
        log.warning("gemini unavailable: %s", e)
        return None


def enabled() -> bool:
    return _get_client() is not None


async def text(system: str, user: str, max_tokens: int = 400, temperature: float = 0.7) -> str | None:
    c = _get_client()
    if not c:
        return None
    try:
        r = await c.aio.models.generate_content(
            model=MODEL, contents=user,
            config=_types.GenerateContentConfig(system_instruction=system,
                                                max_output_tokens=max_tokens, temperature=temperature))
        out = (r.text or "").strip()
        return out or None
    except Exception as e:
        log.warning("gemini text error: %s", e)
        return None


async def vision(image: bytes, prompt: str, mime: str = "image/jpeg") -> str | None:
    c = _get_client()
    if not c:
        return None
    try:
        r = await c.aio.models.generate_content(
            model=MODEL, contents=[_types.Part.from_bytes(data=image, mime_type=mime), prompt])
        out = (r.text or "").strip()
        return out or None
    except Exception as e:
        log.warning("gemini vision error: %s", e)
        return None


async def audio(data: bytes, prompt: str, mime: str = "audio/ogg") -> str | None:
    c = _get_client()
    if not c:
        return None
    try:
        r = await c.aio.models.generate_content(
            model=MODEL, contents=[_types.Part.from_bytes(data=data, mime_type=mime), prompt])
        out = (r.text or "").strip()
        return out or None
    except Exception as e:
        log.warning("gemini audio error: %s", e)
        return None

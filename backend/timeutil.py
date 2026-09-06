from __future__ import annotations
from datetime import datetime, timedelta, timezone
from backend import db

IST = timezone(timedelta(hours=5, minutes=30))


def clock_offset() -> timedelta:
    return timedelta(minutes=int(db.pref_get("clock_offset_minutes", "0") or 0))


def now() -> datetime:
    """Engine time: wall clock in IST plus any demo offset."""
    return datetime.now(IST) + clock_offset()


def parse(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=IST)
    except Exception:
        return None


def human(d: datetime | None) -> str:
    if not d:
        return "sometime"
    return d.astimezone(IST).strftime("%a %-I:%M %p").replace(" 0", " ")

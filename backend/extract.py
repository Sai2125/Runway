"""Turn messy text into commitments. Gemini first, heuristics as fallback."""
from __future__ import annotations
import re, json
from datetime import datetime, timedelta
from pathlib import Path
from backend import llm
from backend.timeutil import IST

PROMPT = (Path(__file__).parent / "prompts" / "extract.md").read_text()
TYPES = {"promise", "deadline", "birthday", "event", "errand"}
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _clean(items, now: datetime) -> list[dict]:
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict) or not it.get("what"):
            continue
        t = str(it.get("type", "promise")).lower()
        due = it.get("due")
        if due:
            try:
                d = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
                if d.tzinfo is None:
                    d = d.replace(tzinfo=IST)
                due = d.astimezone(IST).isoformat()
            except Exception:
                due = None
        out.append({
            "what": str(it["what"]).strip()[:120],
            "due": due,
            "due_fuzziness": it.get("due_fuzziness"),
            "people": [str(p) for p in (it.get("people") or []) if p][:5],
            "type": t if t in TYPES else ("errand" if not due else "promise"),
            "est_minutes": int(it.get("est_minutes") or 30),
            "first_step": (str(it.get("first_step") or "open it and look at the first thing"))[:120],
        })
    return out


def _heuristic(text: str, now: datetime) -> list[dict]:
    parts = [p.strip() for p in re.split(r"\n|;|(?:,?\s+and\s+(?=[A-Za-z]))", text) if p and p.strip()]
    out = []
    for p in parts or [text]:
        low = p.lower()
        due, fuzz, typ = None, None, "promise"
        rel = re.search(r"\bin\s+(\d+|an?|half an?)\s*(min|mins|minute|minutes|hr|hrs|hour|hours|day|days|week|weeks)\b", low)
        if rel:
            n = {"a": 1, "an": 1, "half a": 0.5, "half an": 0.5}.get(rel.group(1), None)
            n = float(rel.group(1)) if n is None else n
            unit = rel.group(2)
            delta = timedelta(minutes=n) if unit.startswith("min") else timedelta(hours=n) if unit.startswith(("hr", "hour")) \
                else timedelta(days=n) if unit.startswith("day") else timedelta(weeks=n)
            due, fuzz = now + delta, rel.group(0)
        elif re.search(r"\b(right now|now|asap|immediately)\b", low):
            due, fuzz = now + timedelta(minutes=5), "now"
        elif "tonight" in low:
            due, fuzz = now.replace(hour=23, minute=0, second=0, microsecond=0), "tonight"
        elif "tomorrow" in low:
            due, fuzz = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0), "tomorrow"
        elif "this week" in low:
            due, fuzz = (now + timedelta(days=(4 - now.weekday()) % 7)).replace(hour=17, minute=0, second=0, microsecond=0), "this week"
        else:
            for i, d in enumerate(DAYS):
                if d in low or d[:3] in re.findall(r"\b(\w{3})\b", low):
                    delta = (i - now.weekday()) % 7 or 7
                    due, fuzz = (now + timedelta(days=delta)).replace(hour=17, minute=0, second=0, microsecond=0), d
                    break
            m = re.search(r"\b(?:on\s+)?(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", low)
            if due is None and m:
                day = int(m.group(1))
                try:
                    cand = now.replace(day=day, hour=9, minute=0, second=0, microsecond=0)
                    if cand < now:
                        cand = (cand.replace(day=1) + timedelta(days=32)).replace(day=day)
                    due, fuzz = cand, m.group(0).strip()
                except ValueError:
                    pass
        # clock times: "at 4 00 AM", "at 6 01", "5pm", "17:30"
        tm = re.search(r"\b(?:at\s+)?(\d{1,2})(?:[:. ](\d{2}))?\s*(am|pm)?\b(?!\s*(?:min|hour|day|week))", low)
        if tm and not rel and (tm.group(3) or tm.group(2) is not None):
            h = int(tm.group(1)); mnt = int(tm.group(2) or 0)
            if tm.group(3):
                h = h % 12 + (12 if tm.group(3) == "pm" else 0)
            if 0 <= h < 24 and 0 <= mnt < 60:
                base = due if due is not None else now
                cand = base.replace(hour=h, minute=mnt, second=0, microsecond=0)
                if due is None and cand <= now:
                    cand += timedelta(days=1)
                due, fuzz = cand, fuzz or tm.group(0).strip()
        if any(k in low for k in ("birthday", "bday", "b'day")):
            typ = "birthday"
        elif any(k in low for k in ("submit", "submission", "deadline", "due", "exam", "assignment")):
            typ = "deadline"
        elif any(k in low for k in ("meeting", "call with", "event", "party", "appointment")):
            typ = "event"
        elif due is None:
            typ = "errand"
        people = [w for w in re.findall(r"\b([A-Z][a-z]{2,})\b", p) if w.lower() not in DAYS and w not in ("I", "The")]
        out.append({"what": re.sub(r"^(i'?ll|i will|i need to|i have to|remind me to)\s+", "", p, flags=re.I).strip()[:120] or p,
                    "due": due.isoformat() if due else None, "due_fuzziness": fuzz, "people": people[:2],
                    "type": typ, "est_minutes": 30, "first_step": "open it and look at the first thing"})
    return out


async def extract(text: str, now: datetime) -> list[dict]:
    text = (text or "").strip()
    if not text:
        return []
    out = await llm.text(PROMPT.replace("{{now_iso}}", now.isoformat()), text, max_tokens=900, temperature=0.2)
    if out:
        try:
            m = re.search(r"\[.*\]", out, re.S)
            items = _clean(json.loads(m.group(0) if m else out), now)
            if items:
                return items
        except Exception:
            pass
    return _clean(_heuristic(text, now), now)

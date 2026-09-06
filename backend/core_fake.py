"""
In-memory stand-in for backend.core so the Telegram adapter can be built and demoed
before the real backend lands. Implements CORE_CONTRACT.md exactly.

Swap for the real thing by changing `from backend import core_fake as core`
to `from backend import core` in the adapter.

Optional: set ANTHROPIC_API_KEY to get real Claude extraction + friend voice here too.
Without it, falls back to tiny heuristics so the flow still runs.
"""
from __future__ import annotations
import os, re, json, uuid, asyncio
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

IST = timezone(timedelta(hours=5, minutes=30))
OUTBOUND_HANDLERS: list[Callable[[str, dict], Awaitable[None]]] = []

_channels: dict[tuple[str, str], str] = {}
_commitments: dict[str, dict] = {}
_clock_offset = timedelta(0)  # for /advance in demos

LEAD = {"birthday": timedelta(days=5), "deadline": timedelta(days=3),
        "event": timedelta(days=2), "errand": timedelta(days=1), "promise": timedelta(0)}
OPTIMISM_INDEX = 2.4  # seeded for demo

def now_ts() -> datetime:
    return datetime.now(IST) + _clock_offset

# ---------- optional Claude ----------
_client = None
if os.getenv("ANTHROPIC_API_KEY"):
    try:
        import anthropic
        _client = anthropic.AsyncAnthropic()
    except Exception:
        _client = None

FRIEND = ("You are Runway, a close friend with a perfect memory and an honest sense of time, talking to "
          "someone with ADHD. Warm, brief (1-2 sentences), slightly nosy, never a productivity system. "
          "Never use: overdue, productivity, should have, failed. Never say 'just' before a task.")

async def _claude(system: str, user: str, max_tokens=300) -> str | None:
    if not _client:
        return None
    try:
        r = await _client.messages.create(model="claude-sonnet-4-5", max_tokens=max_tokens,
                                          system=system, messages=[{"role": "user", "content": user}])
        return r.content[0].text.strip()
    except Exception:
        return None

# ---------- contract ----------
async def link_channel(user_id: str, channel: str, chat_id: str) -> None:
    _channels[(user_id, channel)] = str(chat_id)

async def chat_id_for(user_id: str, channel: str) -> str | None:
    return _channels.get((user_id, channel))

async def hello(user_id: str) -> str:
    return "Hey. Tell me anything you're supposed to do — birthdays, deadlines, 'I'll send that tonight'. I'll hold it and bring it back when it matters. Go."

async def _extract(text: str) -> list[dict]:
    t = now_ts()
    if _client:
        sys = ("Extract commitments from messy input for someone with ADHD. Today is "
               f"{t.isoformat()} (Asia/Kolkata). Return ONLY a JSON array of objects with keys: "
               "what, due (ISO 8601 with offset or null), due_fuzziness, people (array), "
               "type (promise|deadline|birthday|event|errand), est_minutes (int), first_step (<12 words). "
               "'tonight'=23:00 today; 'this week'=Friday 17:00; birthdays w/o year = next occurrence.")
        out = await _claude(sys, text, 800)
        if out:
            try:
                m = re.search(r"\[.*\]", out, re.S)
                return json.loads(m.group(0) if m else out)
            except Exception:
                pass
    # heuristic fallback
    due = t.replace(hour=23, minute=0, second=0, microsecond=0) if "tonight" in text.lower() else t + timedelta(days=1)
    people = re.findall(r"\b([A-Z][a-z]+)\b", text)
    return [{"what": text.strip()[:80], "due": due.isoformat(), "due_fuzziness": "tonight" if "tonight" in text.lower() else None,
             "people": people[:2], "type": "promise", "est_minutes": 30, "first_step": "open it and look at the first thing"}]

async def dump(user_id: str, text: str, source: str) -> str:
    items = await _extract(text)
    for it in items:
        cid = "c_" + uuid.uuid4().hex[:6]
        it.update(id=cid, user_id=user_id, state="hidden", source=source, created_at=now_ts().isoformat())
        _commitments[cid] = it
    names = [i["what"] for i in items][:3]
    line = await _claude(FRIEND, f"MODE=ack. Confirm you understood these in ONE line and release them: {names}")
    return line or (f"Got it — {', '.join(names)}. Filed. Go do your thing." if names else "Got it. Go do your thing.")

async def dump_image(user_id: str, image: bytes, source: str) -> str:
    if _client:
        import base64
        try:
            r = await _client.messages.create(model="claude-sonnet-4-5", max_tokens=400,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                 "data": base64.b64encode(image).decode()}},
                    {"type": "text", "text": "Transcribe any handwritten or printed commitments, dates, names. Plain text only."}]}])
            return await dump(user_id, r.content[0].text, source)
        except Exception:
            pass
    return "I can see the photo but can't read it yet — type it for me?"

def _render_surface(c: dict) -> str:
    est = c.get("est_minutes", 30); real = int(est * OPTIMISM_INDEX)
    who = f" for {c['people'][0]}" if c.get("people") else ""
    return (f"{c['what'].capitalize()}{who}. You said {est} min; you usually take about {real} on these. "
            f"First step: {c.get('first_step','open it')}.")

async def now(user_id: str) -> dict | None:
    live = [c for c in _commitments.values() if c["user_id"] == user_id and c["state"] == "now"]
    if not live:
        return None
    c = min(live, key=lambda x: x.get("due") or "")
    text = await _claude(FRIEND, f"MODE=surface. Commitment: {json.dumps(c)}. Optimism index {OPTIMISM_INDEX}. "
                                 "Bring it back with the honest duration and the first_step. End with an implicit choice.")
    return {"id": c["id"], "text": text or _render_surface(c)}

async def act(commitment_id: str, action: str, actual_minutes: int | None = None) -> str:
    c = _commitments.get(commitment_id)
    if not c:
        return "That one's already gone."
    if action == "done":
        c["state"] = "done"; return "Done. Nice."
    if action == "snooze20":
        c["due"] = (now_ts() + timedelta(minutes=20)).isoformat(); c["state"] = "hidden"; return "Twenty it is. I'll come back."
    if action == "not_today":
        c["due"] = (now_ts() + timedelta(days=1)).replace(hour=10, minute=0).isoformat(); c["state"] = "hidden"
        return "Fair. Tomorrow morning, then. Go rest."
    if action == "doing":
        return "Go. I'll shut up."
    return "Okay."

async def slip_send(commitment_id: str) -> str:
    c = _commitments.get(commitment_id)
    if c:
        c["state"] = "closed"
    return "Sent. Loop closed. I've re-filed it for tomorrow morning with the real duration. Sleep."

async def slip_skip(commitment_id: str) -> str:
    c = _commitments.get(commitment_id)
    if c:
        c["state"] = "closed"
    return "Okay, leaving it. It's gone from your plate."

def register_outbound(handler):
    OUTBOUND_HANDLERS.append(handler)

# ---------- fake horizon engine ----------
async def _emit(user_id: str, event: dict):
    for h in OUTBOUND_HANDLERS:
        try:
            await h(user_id, event)
        except Exception as e:
            print("outbound error:", e)

async def tick():
    t = now_ts()
    for c in list(_commitments.values()):
        due = datetime.fromisoformat(c["due"]) if c.get("due") else None
        if not due:
            continue
        lead = LEAD.get(c.get("type", "promise"), timedelta(0))
        surface_at = due - lead - timedelta(minutes=c.get("est_minutes", 30) * OPTIMISM_INDEX)
        if c["state"] == "hidden" and t >= surface_at:
            c["state"] = "now"
            card = await now(c["user_id"])
            await _emit(c["user_id"], {"mode": "surface", "commitment_id": c["id"], "text": card["text"] if card else _render_surface(c)})
        elif c["state"] == "now" and t > due:
            c["state"] = "slipped"
            who = c["people"][0] if c.get("people") else "them"
            out = await _claude(FRIEND, f"MODE=slip. Commitment: {json.dumps(c)}. Return JSON with keys line (to the user, light) "
                                        f"and draft (short honest message TO {who} in the user's voice with a new concrete time).")
            line, draft = None, None
            if out:
                try:
                    m = re.search(r"\{.*\}", out, re.S); j = json.loads(m.group(0)); line, draft = j.get("line"), j.get("draft")
                except Exception:
                    pass
            await _emit(c["user_id"], {"mode": "slip", "commitment_id": c["id"], "people": c.get("people", []),
                                       "text": line or f"That one got away — happens. Want to tell {who}?",
                                       "draft": draft or f"Hey {who} — {c['what']} is coming tomorrow before 10 instead of tonight. Sorry for the slip."})

async def run_engine(interval_s: int = 10):
    while True:
        await tick()
        await asyncio.sleep(interval_s)

async def advance(minutes: int) -> str:
    """Demo helper: shift the engine clock forward and tick immediately."""
    global _clock_offset
    _clock_offset += timedelta(minutes=minutes)
    await tick()
    return f"Clock is now {now_ts().strftime('%-I:%M %p')}."

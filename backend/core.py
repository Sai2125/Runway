"""
Runway core — the one brain. Implements backend/adapters/CORE_CONTRACT.md over SQLite.

Doors (web, Telegram) import only this module. Outbound nudges are written to the
`outbox` table per channel so doors can run as separate processes and poll it; any
in-process handlers registered via register_outbound() are called too.
"""
from __future__ import annotations
import json, uuid, statistics
from datetime import timedelta
from typing import Callable, Awaitable

from backend import db, voice
from backend.extract import extract
from backend import llm
from backend.timeutil import now, parse

OUTBOUND_HANDLERS: list[Callable[[str, dict], Awaitable[None]]] = []
SURFACE_BUDGET = 2            # P1: at most this many items may be "now" per user
DEFAULT_INDEX = 2.4           # until a user has >= MIN_EVENTS completions
MIN_EVENTS = 3
CANONICAL_DEFAULT = "web:demo"

# ---------- identity ----------
def resolve(user_id: str) -> str:
    r = db.one("SELECT canonical FROM aliases WHERE alias=?", (user_id,))
    return r["canonical"] if r else user_id


async def link_alias(alias: str, canonical: str = CANONICAL_DEFAULT) -> None:
    db.x("INSERT INTO aliases(alias,canonical) VALUES(?,?) ON CONFLICT(alias) DO UPDATE SET canonical=excluded.canonical",
         (alias, canonical))


async def link_channel(user_id: str, channel: str, chat_id: str) -> None:
    db.x("INSERT INTO channels(user_id,channel,chat_id) VALUES(?,?,?) "
         "ON CONFLICT(user_id,channel) DO UPDATE SET chat_id=excluded.chat_id",
         (resolve(user_id), channel, str(chat_id)))


async def chat_id_for(user_id: str, channel: str) -> str | None:
    r = db.one("SELECT chat_id FROM channels WHERE user_id=? AND channel=?", (resolve(user_id), channel))
    return r["chat_id"] if r else None


async def register_contact(user_id: str, name: str, chat_id: str) -> None:
    db.x("INSERT INTO contacts(user_id,name_lower,chat_id) VALUES(?,?,?) "
         "ON CONFLICT(user_id,name_lower) DO UPDATE SET chat_id=excluded.chat_id",
         (resolve(user_id), name.strip().lower(), str(chat_id)))


async def contact_chat(user_id: str, name: str) -> str | None:
    r = db.one("SELECT chat_id FROM contacts WHERE user_id=? AND name_lower=?", (resolve(user_id), name.strip().lower()))
    return r["chat_id"] if r else None

# ---------- index ----------
def optimism_index(user_id: str) -> float:
    uid = resolve(user_id)
    rows = db.q("SELECT est_minutes, actual_minutes FROM events WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))
    ratios = [r["actual_minutes"] / max(1, r["est_minutes"]) for r in rows if r["actual_minutes"] and r["est_minutes"]]
    if len(ratios) < MIN_EVENTS:
        return float(db.pref_get(f"optimism_index:{uid}", str(DEFAULT_INDEX)))
    idx = max(0.5, min(5.0, statistics.median(ratios)))
    db.pref_set(f"optimism_index:{uid}", round(idx, 2))
    return idx

# ---------- helpers ----------
def _get(cid: str) -> dict | None:
    return db.row_to_dict(db.one("SELECT * FROM commitments WHERE id=?", (cid,)))


def _emit_sync(user_id: str, event: dict) -> None:
    uid = resolve(user_id)
    chans = [r["channel"] for r in db.q("SELECT channel FROM channels WHERE user_id=?", (uid,))]
    for ch in set(chans) | {"web"}:
        db.x("INSERT INTO outbox(channel,user_id,payload,created_at) VALUES(?,?,?,?)",
             (ch, uid, json.dumps(event, default=str), now().isoformat()))


async def emit(user_id: str, event: dict) -> None:
    _emit_sync(user_id, event)
    for h in OUTBOUND_HANDLERS:
        try:
            await h(resolve(user_id), event)
        except Exception as e:  # pragma: no cover
            print("outbound handler error:", e)


def outbox_pull(channel: str, limit: int = 20) -> list[dict]:
    rows = db.q("SELECT id,user_id,payload FROM outbox WHERE channel=? AND delivered_at IS NULL ORDER BY id LIMIT ?",
                (channel, limit))
    return [{"id": r["id"], "user_id": r["user_id"], **json.loads(r["payload"])} for r in rows]


def outbox_ack(ids: list[int]) -> None:
    for i in ids:
        db.x("UPDATE outbox SET delivered_at=? WHERE id=?", (now().isoformat(), i))

# ---------- contract ----------
async def hello(user_id: str) -> str:
    return await voice.render("hello", None, optimism_index(user_id))


async def dump(user_id: str, text: str, source: str = "web") -> str:
    uid = resolve(user_id)
    items = await extract(text, now())
    for it in items:
        cid = "c_" + uuid.uuid4().hex[:6]
        db.x("INSERT INTO commitments(id,user_id,what,due,due_fuzziness,people,type,est_minutes,first_step,state,created_at,source) "
             "VALUES(?,?,?,?,?,?,?,?,?,'hidden',?,?)",
             (cid, uid, it["what"], it["due"], it.get("due_fuzziness"), json.dumps(it["people"]), it["type"],
              it["est_minutes"], it["first_step"], now().isoformat(), source))
    return await voice.render("ack", None, optimism_index(uid), names=[i["what"] for i in items])


async def dump_image(user_id: str, image: bytes, source: str = "web-photo") -> str:
    text = await llm.vision(image, "Transcribe any handwritten or printed commitments, dates, names. Plain text only, one per line.")
    if not text:
        return "I can see the photo but can't read it right now — type it for me?"
    return await dump(user_id, text, source)


async def now_card(user_id: str) -> dict | None:
    uid = resolve(user_id)
    r = db.one("SELECT * FROM commitments WHERE user_id=? AND state='now' ORDER BY COALESCE(due,'9999') LIMIT 1", (uid,))
    c = db.row_to_dict(r)
    if not c:
        return None
    text = await voice.render("surface", c, optimism_index(uid))
    return {"id": c["id"], "text": text, "commitment": c}

now_ = now_card  # alias; contract name is `now` but that clashes with timeutil.now inside this module


async def act(commitment_id: str, action: str, actual_minutes: int | None = None) -> str:
    c = _get(commitment_id)
    if not c:
        return "That one's already gone."
    t = now()
    idx = optimism_index(c["user_id"])
    if action == "doing":
        db.x("UPDATE commitments SET started_at=? WHERE id=?", (t.isoformat(), commitment_id))
        return "Go. I'll shut up."
    if action == "done":
        started = parse(c.get("started_at"))
        actual = actual_minutes or (int((t - started).total_seconds() // 60) if started else c["est_minutes"])
        actual = max(1, actual)
        db.x("UPDATE commitments SET state='done' WHERE id=?", (commitment_id,))
        db.x("INSERT INTO events(commitment_id,user_id,est_minutes,actual_minutes,completed_at) VALUES(?,?,?,?,?)",
             (commitment_id, c["user_id"], c["est_minutes"], actual, t.isoformat()))
        return await voice.render("done", c, idx, actual_minutes=actual)
    if action == "snooze20":
        db.x("UPDATE commitments SET state='hidden', due=?, checkin_sent=0, surfaced_at=NULL WHERE id=?",
             ((t + timedelta(minutes=20)).isoformat(), commitment_id))
        return "Twenty it is. I'll come back."
    if action == "not_today":
        nd = (t + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        db.x("UPDATE commitments SET state='hidden', due=?, checkin_sent=0, surfaced_at=NULL WHERE id=?",
             (nd.isoformat(), commitment_id))
        return await voice.render("backoff", c, idx)
    return "Okay."


async def set_actual(commitment_id: str, actual_minutes: int) -> str:
    c = _get(commitment_id)
    if not c:
        return "That one's already gone."
    db.x("UPDATE events SET actual_minutes=? WHERE id=(SELECT id FROM events WHERE commitment_id=? ORDER BY id DESC LIMIT 1)",
         (actual_minutes, commitment_id))
    idx = optimism_index(c["user_id"])
    return f"Noted — {actual_minutes} min. Your multiplier is now {idx:.1f}×."


async def slip_send(commitment_id: str) -> dict:
    """Returns {line, draft, recipient_chat_id|None, people}. The door decides how to deliver."""
    c = _get(commitment_id)
    if not c:
        return {"line": "That one's already gone.", "draft": None, "recipient_chat_id": None, "people": []}
    t = now()
    nd = (t + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    idx = optimism_index(c["user_id"])
    # close this one, re-file a fresh copy with the learned duration
    db.x("UPDATE commitments SET state='closed' WHERE id=?", (commitment_id,))
    db.x("INSERT INTO commitments(id,user_id,what,due,due_fuzziness,people,type,est_minutes,first_step,state,created_at,source) "
         "VALUES(?,?,?,?,?,?,?,?,?,'hidden',?,?)",
         ("c_" + uuid.uuid4().hex[:6], c["user_id"], c["what"], nd.isoformat(), "tomorrow morning",
          json.dumps(c["people"]), c["type"], int(round(c["est_minutes"] * idx)), c["first_step"], t.isoformat(), "refile"))
    recipient = await contact_chat(c["user_id"], c["people"][0]) if c.get("people") else None
    return {"line": "Sent. Loop closed. Re-filed for tomorrow morning with the real duration. Sleep.",
            "draft": c.get("draft"), "recipient_chat_id": recipient, "people": c.get("people", [])}


async def slip_skip(commitment_id: str) -> str:
    db.x("UPDATE commitments SET state='closed' WHERE id=?", (commitment_id,))
    return "Okay, leaving it. It's off your plate."


def register_outbound(handler: Callable[[str, dict], Awaitable[None]]) -> None:
    OUTBOUND_HANDLERS.append(handler)

# ---------- demo + view helpers ----------
async def advance(minutes: int) -> str:
    cur = int(db.pref_get("clock_offset_minutes", "0") or 0)
    db.pref_set("clock_offset_minutes", cur + int(minutes))
    from backend.horizon import tick
    await tick()
    return f"Clock is now {now().strftime('%a %-I:%M %p')}."


async def reset_clock() -> str:
    db.pref_set("clock_offset_minutes", 0)
    return f"Clock reset to {now().strftime('%a %-I:%M %p')}."


def snapshot(user_id: str) -> dict:
    """Everything the Horizon view needs, in one call."""
    from backend.horizon import surface_at
    uid = resolve(user_id)
    t = now()
    idx = optimism_index(uid)
    items = [db.row_to_dict(r) for r in db.q("SELECT * FROM commitments WHERE user_id=? ORDER BY COALESCE(due,'9999')", (uid,))]
    for c in items:
        sa = surface_at(c, idx)
        c["surface_at"] = sa.isoformat() if sa else None
        c["surfaces_in_min"] = int((sa - t).total_seconds() // 60) if sa else None
        c["due_in_min"] = int((parse(c["due"]) - t).total_seconds() // 60) if c.get("due") else None
    events = [dict(r) for r in db.q("SELECT est_minutes,actual_minutes,completed_at FROM events WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,))]
    chans = [dict(r) for r in db.q("SELECT channel,chat_id FROM channels WHERE user_id=?", (uid,))]
    return {"user_id": uid, "now": t.isoformat(), "clock_offset_minutes": int(db.pref_get("clock_offset_minutes", "0") or 0),
            "optimism_index": round(idx, 2), "surface_budget": SURFACE_BUDGET, "llm": "gemini" if llm.enabled() else "heuristic",
            "items": items, "events": events, "channels": chans,
            "counts": {s: sum(1 for c in items if c["state"] == s) for s in ("hidden", "now", "slipped", "done", "closed")}}

"""
The horizon engine. Runs every 60s (wall clock + demo offset).

  surface_at = due − lead_time(type) − est_minutes × optimism_index
  hidden → now      when now >= surface_at and the user has < SURFACE_BUDGET items in `now`
  now → slipped     when now > due and not done   (never "overdue"; a draft is written)
  now (unanswered)  one check-in 30 min after surfacing, then silence
"""
from __future__ import annotations
import asyncio, json
from datetime import datetime, timedelta

from backend import db, voice
from backend.timeutil import now, parse

LEAD = {"birthday": timedelta(days=5), "deadline": timedelta(days=3), "event": timedelta(days=2),
        "errand": timedelta(days=1), "promise": timedelta(0)}
CHECKIN_AFTER = timedelta(minutes=30)


def surface_at(c: dict, idx: float) -> datetime | None:
    due = parse(c.get("due"))
    if not due:
        return None
    return due - LEAD.get(c.get("type", "promise"), timedelta(0)) - timedelta(minutes=int(c.get("est_minutes") or 30) * idx)


async def tick() -> None:
    from backend import core  # late import to avoid cycle
    t = now()
    users = [r["user_id"] for r in db.q("SELECT DISTINCT user_id FROM commitments WHERE state IN ('hidden','now')")]
    for uid in users:
        idx = core.optimism_index(uid)

        # 1) slips + check-ins for items already in `now`
        for r in db.q("SELECT * FROM commitments WHERE user_id=? AND state='now'", (uid,)):
            c = db.row_to_dict(r)
            due = parse(c.get("due"))
            if due and t > due:
                out = await voice.render("slip", c, idx)
                line, draft = (out["line"], out["draft"]) if isinstance(out, dict) else (str(out), None)
                db.x("UPDATE commitments SET state='slipped', draft=? WHERE id=?", (draft, c["id"]))
                await core.emit(uid, {"mode": "slip", "commitment_id": c["id"], "text": line, "draft": draft,
                                      "people": c.get("people", [])})
                continue
            surfaced = parse(c.get("surfaced_at"))
            if surfaced and not c.get("started_at") and not c.get("checkin_sent") and t - surfaced >= CHECKIN_AFTER:
                line = await voice.render("checkin", c, idx)
                db.x("UPDATE commitments SET checkin_sent=1 WHERE id=?", (c["id"],))
                await core.emit(uid, {"mode": "checkin", "commitment_id": c["id"], "text": line})

        # 2) surface hidden items, respecting the budget (P1)
        live = db.one("SELECT COUNT(*) AS n FROM commitments WHERE user_id=? AND state='now'", (uid,))["n"]
        budget = core.SURFACE_BUDGET - live
        if budget <= 0:
            continue
        hidden = [db.row_to_dict(r) for r in db.q(
            "SELECT * FROM commitments WHERE user_id=? AND state='hidden' AND due IS NOT NULL ORDER BY due", (uid,))]
        for c in hidden:
            if budget <= 0:
                break
            sa = surface_at(c, idx)
            if sa and t >= sa:
                db.x("UPDATE commitments SET state='now', surfaced_at=? WHERE id=?", (t.isoformat(), c["id"]))
                c["surfaced_at"] = t.isoformat()
                text = await voice.render("surface", c, idx)
                await core.emit(uid, {"mode": "surface", "commitment_id": c["id"], "text": text})
                budget -= 1


async def run(interval_s: int = 60) -> None:
    while True:
        try:
            await tick()
        except Exception as e:  # keep the loop alive
            print("horizon tick error:", e)
        await asyncio.sleep(interval_s)

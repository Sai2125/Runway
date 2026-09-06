"""Seed the demo brain.   python -m seed.demo_seed

- user web:demo
- "send Rahul the deck tonight" (promise) and "Priya's birthday on the 20th" (birthday)
- six past completions so the optimism index reads about 2.4×
Safe to re-run (clears only the demo user's rows).
"""
import json, uuid, asyncio
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from backend import db, core
from backend.timeutil import now

U = core.CANONICAL_DEFAULT


def main():
    db.conn()
    db.pref_set("clock_offset_minutes", 0)
    db.x("DELETE FROM commitments WHERE user_id=?", (U,))
    db.x("DELETE FROM events WHERE user_id=?", (U,))
    db.x("DELETE FROM outbox WHERE user_id=?", (U,))
    t = now()

    def add(what, due, fuzz, people, typ, est, first):
        db.x("INSERT INTO commitments(id,user_id,what,due,due_fuzziness,people,type,est_minutes,first_step,state,created_at,source) "
             "VALUES(?,?,?,?,?,?,?,?,?,'hidden',?,?)",
             ("c_" + uuid.uuid4().hex[:6], U, what, due.isoformat(), fuzz, json.dumps(people), typ, est, first, t.isoformat(), "seed"))

    add("send Rahul the deck", t.replace(hour=23, minute=0, second=0, microsecond=0), "tonight", ["Rahul"], "promise", 30,
        "open the deck and look at the last slide")
    bday = (t + timedelta(days=9)).replace(hour=9, minute=0, second=0, microsecond=0)
    add("Priya's birthday", bday, "the 20th", ["Priya"], "birthday", 45, "open the gift-ideas note")
    add("renew passport", t + timedelta(days=20), None, [], "errand", 90, "find the old passport")
    add("pay electricity bill", t + timedelta(days=6), None, [], "deadline", 10, "open the BESCOM app")

    for est, actual, days_ago in [(30, 72, 9), (20, 55, 8), (60, 130, 6), (15, 40, 5), (45, 100, 3), (30, 75, 1)]:
        db.x("INSERT INTO events(commitment_id,user_id,est_minutes,actual_minutes,completed_at) VALUES(NULL,?,?,?,?)",
             (U, est, actual, (t - timedelta(days=days_ago)).isoformat()))

    print(f"Seeded {U}: 4 commitments, 6 completions → index {core.optimism_index(U):.2f}×")


if __name__ == "__main__":
    main()

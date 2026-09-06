"""Every user-facing line comes from here. Gemini with the friend prompt; templated fallback."""
from __future__ import annotations
import json, re
from pathlib import Path
from backend import llm
from backend.timeutil import now, human, parse

FRIEND = (Path(__file__).parent / "prompts" / "friend.md").read_text()


def _who(c: dict) -> str:
    return c["people"][0] if c.get("people") else "them"


def _fallback(mode: str, c: dict | None, idx: float, extra: dict) -> str | dict:
    t = now()
    if mode == "hello":
        return "Hey. Tell me anything you're supposed to do — birthdays, deadlines, 'I'll send that tonight'. I'll hold it and bring it back when it matters. Go."
    if mode == "ack":
        names = extra.get("names") or []
        if not names:
            return "Got it. Go do your thing."
        if len(names) == 1:
            return f"Got it — {names[0]}. Filed. Go do your thing."
        return f"Got {len(names)}: {', '.join(names[:3])}{'…' if len(names) > 3 else ''}. Filed. Go do your thing."
    if not c:
        return "Okay."
    est = int(c.get("est_minutes") or 30)
    real = int(round(est * idx))
    who = f" for {_who(c)}" if c.get("people") else ""
    if mode == "surface":
        return (f"{c['what'][0].upper() + c['what'][1:]}{who}. You said {est} min; you usually take about {real} on these"
                f"{' — if ' + c['due_fuzziness'] + ' means ' + human(parse(c.get('due'))) + ', this is the moment' if c.get('due_fuzziness') else ''}. "
                f"First step: {c.get('first_step') or 'open it'}.")
    if mode == "checkin":
        said = human(parse(c.get("created_at")))
        return f"You said '{c.get('due_fuzziness') or 'you would'}' at {said}. It's {t.strftime('%-I:%M')} — {c.get('due_fuzziness') or 'the window'} is getting thin. No judgement. Want me to hold the fort?"
    if mode == "slip":
        if not c.get("people"):
            return {"line": f"That one got away — {c['what']}. Happens. Want me to re-file it for tomorrow morning?", "draft": None}
        who = _who(c)
        return {"line": f"That one got away — happens. Want to tell {who}?",
                "draft": f"Hey {who} — {c['what']} is coming tomorrow before 10 instead. Sorry for the slip, it'll be worth the wait."}
    if mode == "backoff":
        return "Fair. I'll come back later. Go."
    if mode == "done":
        a = extra.get("actual_minutes")
        return f"Done. {'Took ' + str(a) + ' against your ' + str(est) + ' — noted, no judgement.' if a else 'Nice.'}"
    if mode == "index":
        return f"Your multiplier is {idx:.1f}×. When you say 30 minutes, it's usually about {int(30*idx)}. I plan with that number, not the one you say."
    return "Okay."


async def render(mode: str, c: dict | None = None, idx: float = 1.0, **extra) -> str | dict:
    ctx = {"mode": mode, "now": now().isoformat(), "optimism_index": round(idx, 2), "commitment": c, **extra}
    out = await llm.text(FRIEND, f"MODE={mode}\nCONTEXT={json.dumps(ctx, default=str)}", max_tokens=300)
    if out:
        if mode == "slip":
            try:
                m = re.search(r"\{.*\}", out, re.S)
                j = json.loads(m.group(0))
                if j.get("line"):
                    return {"line": j["line"], "draft": j.get("draft") if c and c.get("people") else None}
            except Exception:
                pass
        else:
            return out.strip().strip('"')
    return _fallback(mode, c, idx, extra)

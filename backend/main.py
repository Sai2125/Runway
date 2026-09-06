"""
Runway — web door. FastAPI serving the Horizon view + JSON API + SSE.
Also runs the horizon engine unless RUN_ENGINE=0 (run it in exactly one process).

    python run_web.py      → http://127.0.0.1:8000
"""
from __future__ import annotations
import os, json, asyncio
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel

from backend import core, horizon

USER = os.getenv("RUNWAY_WEB_USER", core.CANONICAL_DEFAULT)
FRONT = Path(__file__).resolve().parent.parent / "frontend"
app = FastAPI(title="Runway")


@app.on_event("startup")
async def _startup():
    await core.link_channel(USER, "web", "web")
    if os.getenv("RUN_ENGINE", "1") != "0":
        asyncio.create_task(horizon.run(int(os.getenv("ENGINE_INTERVAL_S", "60"))))


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(FRONT / "index.html")


class Dump(BaseModel):
    text: str


@app.post("/dump")
async def dump(d: Dump):
    line = await core.dump(USER, d.text, source="web")
    return {"line": line}


@app.post("/dump/image")
async def dump_image(file: UploadFile = File(...)):
    line = await core.dump_image(USER, await file.read(), source="web-photo")
    return {"line": line}


@app.get("/now")
async def now_():
    return await core.now_card(USER) or {"id": None, "text": "Nothing needs you right now."}


class Act(BaseModel):
    id: str
    action: str
    actual_minutes: Optional[int] = None


@app.post("/act")
async def act(a: Act):
    return {"line": await core.act(a.id, a.action, a.actual_minutes)}


class Actual(BaseModel):
    id: str
    actual_minutes: int


@app.post("/actual")
async def actual(a: Actual):
    return {"line": await core.set_actual(a.id, a.actual_minutes)}


class Slip(BaseModel):
    id: str


@app.post("/slip/send")
async def slip_send(s: Slip):
    return await core.slip_send(s.id)


@app.post("/slip/skip")
async def slip_skip(s: Slip):
    return {"line": await core.slip_skip(s.id)}


@app.get("/state")
async def state():
    return core.snapshot(USER)


@app.get("/debug/advance")
async def advance(minutes: int = 60):
    return {"line": await core.advance(minutes)}


@app.get("/debug/reset-clock")
async def reset_clock():
    return {"line": await core.reset_clock()}


@app.get("/debug/tick")
async def tick():
    await horizon.tick()
    return {"ok": True}


@app.get("/events")
async def events(request: Request):
    async def gen():
        yield "retry: 2000\n\n"
        while True:
            if await request.is_disconnected():
                break
            rows = core.outbox_pull("web")
            for ev in rows:
                yield f"data: {json.dumps(ev, default=str)}\n\n"
            if rows:
                core.outbox_ack([r["id"] for r in rows])
            await asyncio.sleep(1)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

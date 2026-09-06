# Runway

A second brain that knows what time it is. One brain (SQLite), two doors (web Horizon view + Telegram).
See `CLAUDE.md` for the full brief: principles, architecture, prompts, demo script.

## Run it (two terminals)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # fill TELEGRAM_BOT_TOKEN and GEMINI_API_KEY
python -m seed.demo_seed                                # demo brain: 4 commitments, index ≈ 2.4×
```

Terminal 1 — web door + engine:
```bash
python run_web.py            # → http://127.0.0.1:8000  (Chrome for the mic)
```

Terminal 2 — Telegram door:
```bash
python run_telegram.py       # then on your phone: /start, then /link
```

The engine (what moves items across the horizon) runs inside `run_web.py`. If you run only
the Telegram bot, set `RUN_ENGINE=1` in `.env`. Never run it in both.

## What to try (watch the web view while you do this)

| Step | Do | See |
|---|---|---|
| 1 | Open http://127.0.0.1:8000 | Empty sky: "Nothing needs you right now." 4 items in the fog, each with "surfaces in …" |
| 2 | On Telegram: `/link` | Web view shows `telegram` in channels; both doors are one brain |
| 3 | Type or 🎙 speak: *"I'll send Rahul the deck tonight and Priya's bday is on the 20th"* | Toast with the ack; two new chips sink into the fog |
| 4 | Telegram: send a voice note or a photo of a scribbled note | Same — items appear in the web fog (needs GEMINI_API_KEY) |
| 5 | Click **+6 h** (or Telegram `/advance 360`) | The deck crosses the horizon: one glowing card with honest time + first step. Telegram gets the same nudge with buttons |
| 6 | Press **Doing it**, then **Done ✓** | Asked how long; index tile updates. Tap the index tile for said-vs-actual bars |
| 7 | Click **+1 day** | A card slips: no red, a drafted message to Rahul, **Send it / Skip** |
| 8 | Have a friend open the bot and send `/iam Rahul`, then **Send it** | Rahul's phone receives the draft; item re-filed for tomorrow with the learned duration |
| 9 | Click **+1 day** twice | Birthday surfaces 5 days out; only 2 items ever show at once (surface budget) |
| 10 | **reset clock** | Back to real time; hidden items keep their real dates |

Telegram: `/now` shows the one thing (or nothing), `/index` your multiplier, `/advance N`, `/resetclock`.

## Layout

| Path | Role |
|---|---|
| `backend/core.py` | the brain — SQLite, contract functions, outbox, surface budget, optimism index |
| `backend/horizon.py` | engine: `surface_at = due − lead(type) − est × index`; slips; check-ins |
| `backend/extract.py` · `voice.py` · `llm.py` · `stt.py` | Gemini extraction, friend voice, LLM gateway, voice-note transcription |
| `backend/main.py` + `frontend/index.html` | web door: API, SSE, Horizon view (Web Speech mic, image paste) |
| `backend/adapters/telegram.py` | Telegram door: commands, buttons, outbox polling, slip delivery |
| `backend/adapters/CORE_CONTRACT.md` | what any door may import from core |
| `seed/demo_seed.py` | demo data (safe to re-run) |
| `landing/index.html` | marketing page |
| `backend/core_fake.py` | deprecated in-memory stand-in; kept for reference only |

## Security

Never commit `.env`. If a token was ever pasted in a chat or screenshot, rotate it
(@BotFather → `/revoke`). Keys are read only from `.env`.

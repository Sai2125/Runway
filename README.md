# Runway — Telegram door

A second brain that knows what time it is. This package runs the **Telegram** door on a fake
in-memory core so it works today, independent of the backend. See `CLAUDE.md` for the full brief.

## Run it (5 steps, ~5 minutes)

1. **Make the bot** — in Telegram open **@BotFather** → `/newbot` → pick a name and a username → copy the token.
2. **Python 3.10+** on your laptop. Then in this folder:
   ```bash
   python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. **Secrets** — `cp .env.example .env` and paste the token. Optionally add `ANTHROPIC_API_KEY`
   (real extraction + friend voice) and `GROQ_API_KEY` (voice notes, free at console.groq.com).
4. **Start** — `python run_telegram.py`
5. **On your phone** — open the bot:
   ```
   /start
   I'll send Rahul the deck tonight
   /now                → "Nothing needs you right now."   (it's hidden — principle P1)
   /advance 1200       → the card surfaces with buttons     (engine clock jumps ~20h)
   /advance 90         → slipped: friend line + drafted message → tap "Send it"
   ```
   Also try a **voice note** (needs GROQ key) or a **photo of a handwritten note** (needs ANTHROPIC key).

## What's where

| Path | Role |
|---|---|
| `run_telegram.py` | launcher (loads `.env`, starts polling) |
| `backend/adapters/telegram.py` | the bot: handlers, inline buttons, outbound nudges, `/advance` |
| `backend/core_fake.py` | in-memory core + horizon engine (10s tick) implementing the contract |
| `backend/adapters/CORE_CONTRACT.md` | what the real `backend/core.py` must expose |
| `backend/stt.py` | Groq Whisper for `.ogg` voice notes |
| `landing/index.html` | marketing page (also published online) |
| `CLAUDE.md` | full project brief: principles, architecture, prompts, checklist, demo script |

## Swapping in the real backend

When `backend/core.py` exists per `CORE_CONTRACT.md`, change one line in `backend/adapters/telegram.py`:

```python
from backend import core_fake as core   →   from backend import core
```

## Security

Never commit `.env`. If a token was ever pasted in a chat or screenshot, rotate it:
@BotFather → `/revoke` → choose the bot → new token → update `.env`.

"""One-command launcher for the Runway Telegram bot.

    python run_telegram.py

Loads .env, checks the token, starts long polling with the fake core + engine.
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

if not os.getenv("TELEGRAM_BOT_TOKEN"):
    sys.exit("TELEGRAM_BOT_TOKEN missing. Copy .env.example to .env and paste the token from @BotFather.")

print("Runway · Telegram door")
print("  Claude:", "on" if os.getenv("ANTHROPIC_API_KEY") else "off (heuristic fallback)")
print("  Voice :", "on" if os.getenv("GROQ_API_KEY") else "off (voice notes will ask you to type)")
print("  Open your bot in Telegram and send /start\n")

from backend.adapters.telegram import build
build().run_polling()

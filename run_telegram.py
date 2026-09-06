"""Start the Runway Telegram door.   python run_telegram.py

Set RUN_ENGINE=1 in .env ONLY if you are not also running run_web.py
(the engine must run in exactly one process).
"""
import os, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

if not os.getenv("TELEGRAM_BOT_TOKEN"):
    sys.exit("TELEGRAM_BOT_TOKEN missing. Copy .env.example to .env and paste the token from @BotFather.")

print("Runway · Telegram door")
from backend import llm
print(" ", llm.probe())
print("  Demo mode:", "ON (voice/photo fall back to canned text if Gemini fails)" if os.getenv("DEMO_MODE", "1") == "1" else "off")
print("  Engine:", "running here (RUN_ENGINE=1)" if os.getenv("RUN_ENGINE") == "1" else "expected in run_web.py")
print("  Open your bot in Telegram and send /start\n")

from backend.adapters.telegram import build
build().run_polling()

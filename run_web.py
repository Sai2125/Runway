"""Start the Runway web door (Horizon view + API + engine).   python run_web.py"""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import uvicorn
print("Runway · Web door → http://127.0.0.1:8000")
from backend import llm
print(" ", llm.probe())
print("  Demo mode:", "ON (voice/photo fall back to canned text if Gemini fails)" if os.getenv("DEMO_MODE", "1") == "1" else "off")
print("  Engine:", "running here" if os.getenv("RUN_ENGINE", "1") != "0" else "disabled (RUN_ENGINE=0)")
uvicorn.run("backend.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), log_level="warning")

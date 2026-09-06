"""
Runway — Telegram adapter.

    uv add python-telegram-bot groq anthropic
    TELEGRAM_BOT_TOKEN=... GROQ_API_KEY=... ANTHROPIC_API_KEY=... python -m backend.adapters.telegram

Swap the core import when the real backend lands.
"""
from __future__ import annotations
import os, asyncio, logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

from backend import core_fake as core          # ← change to `from backend import core` later
from backend.stt import transcribe_ogg

logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = "telegram"

def uid(update: Update) -> str:
    return f"tg:{update.effective_user.id}"

def surface_kb(cid: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Doing it", callback_data=f"act:doing:{cid}"),
        InlineKeyboardButton("Give me 20", callback_data=f"act:snooze20:{cid}"),
        InlineKeyboardButton("Not today", callback_data=f"act:not_today:{cid}")]])

def slip_kb(cid: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Send it", callback_data=f"slip:send:{cid}"),
        InlineKeyboardButton("Skip", callback_data=f"slip:skip:{cid}")]])

# ---------- inbound ----------
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await core.link_channel(uid(u), CHANNEL, str(u.effective_chat.id))
    await u.message.reply_text(await core.hello(uid(u)))

async def on_text(u: Update, c):
    await u.message.chat.send_action("typing")
    await u.message.reply_text(await core.dump(uid(u), u.message.text, source="telegram"))

async def on_voice(u: Update, c):
    await u.message.chat.send_action("typing")
    f = await u.message.voice.get_file()
    path = await f.download_to_drive()
    text = await transcribe_ogg(path)
    if not text:
        return await u.message.reply_text("Heard you, couldn't make out the words. Type it for me?")
    line = await core.dump(uid(u), text, source="telegram-voice")
    await u.message.reply_text(f"“{text}”\n\n{line}")

async def on_photo(u: Update, c):
    await u.message.chat.send_action("typing")
    f = await u.message.photo[-1].get_file()
    data = await f.download_as_bytearray()
    await u.message.reply_text(await core.dump_image(uid(u), bytes(data), source="telegram-photo"))

async def now_cmd(u: Update, c):
    card = await core.now(uid(u))
    if not card:
        return await u.message.reply_text("Nothing needs you right now.")
    await u.message.reply_text(card["text"], reply_markup=surface_kb(card["id"]))

async def advance_cmd(u: Update, c):
    """Demo only: /advance 90  → move the engine clock 90 minutes."""
    mins = int(c.args[0]) if c.args else 60
    await u.message.reply_text(await core.advance(mins))

async def on_button(u: Update, c):
    q = u.callback_query
    await q.answer()
    kind, action, cid = q.data.split(":", 2)
    if kind == "slip":
        line = await (core.slip_send(cid) if action == "send" else core.slip_skip(cid))
    else:
        line = await core.act(cid, action)
    await q.edit_message_text(f"{q.message.text}\n\n— {line}")

# ---------- outbound (horizon engine → Telegram) ----------
APP: Application | None = None

async def outbound(user_id: str, event: dict):
    chat_id = await core.chat_id_for(user_id, CHANNEL)
    if not chat_id or not APP:
        return
    mode, cid = event["mode"], event["commitment_id"]
    if mode == "slip":
        text = f"{event['text']}\n\n“{event['draft']}”"
        await APP.bot.send_message(chat_id, text, reply_markup=slip_kb(cid))
    elif mode == "surface":
        await APP.bot.send_message(chat_id, event["text"], reply_markup=surface_kb(cid))
    else:
        await APP.bot.send_message(chat_id, event["text"])

# ---------- wiring ----------
async def post_init(app: Application):
    await app.bot.set_my_commands([("start", "Say hi"), ("now", "The one thing, if any")])
    await app.bot.set_my_short_description("A second brain that knows what time it is.")
    if hasattr(core, "run_engine"):
        asyncio.create_task(core.run_engine(interval_s=10))

def build() -> Application:
    global APP
    APP = Application.builder().token(TOKEN).post_init(post_init).build()
    APP.add_handler(CommandHandler("start", start))
    APP.add_handler(CommandHandler("now", now_cmd))
    APP.add_handler(CommandHandler("advance", advance_cmd))
    APP.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    APP.add_handler(MessageHandler(filters.VOICE, on_voice))
    APP.add_handler(MessageHandler(filters.PHOTO, on_photo))
    APP.add_handler(CallbackQueryHandler(on_button))
    core.register_outbound(outbound)
    return APP

if __name__ == "__main__":
    build().run_polling()

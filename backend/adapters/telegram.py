"""
Runway — Telegram door, on the real SQLite core.

Commands:  /start  /now  /link  /iam <Name>  /index  /advance <min>  /resetclock
Messages:  text · voice note (Gemini audio) · photo (Gemini vision)
Buttons:   Doing it · Give me 20 · Not today  →  Done · Still going  →  duration confirm
           Send it · Skip (slip)

Outbound nudges come from the `outbox` table (polled every 3s), so the engine can live
in the web process. Set RUN_ENGINE=1 to run the engine here instead (never in both).
"""
from __future__ import annotations
import os, asyncio, logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ContextTypes, filters)

from backend import core, horizon
from backend.stt import transcribe_ogg

log = logging.getLogger("runway.telegram")
logging.basicConfig(level=logging.INFO)
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = "telegram"
APP: Application | None = None


def uid(u: Update) -> str:
    return f"tg:{u.effective_user.id}"


def surface_kb(cid: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Doing it", callback_data=f"act:doing:{cid}"),
        InlineKeyboardButton("Give me 20", callback_data=f"act:snooze20:{cid}"),
        InlineKeyboardButton("Not today", callback_data=f"act:not_today:{cid}")]])


def doing_kb(cid: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Done ✓", callback_data=f"act:done:{cid}"),
        InlineKeyboardButton("Still going", callback_data=f"noop:0:{cid}")]])


def duration_kb(cid: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{m} min", callback_data=f"dur:{m}:{cid}") for m in (15, 30, 60, 120)]])


def slip_kb(cid: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Send it", callback_data=f"slip:send:{cid}"),
        InlineKeyboardButton("Skip", callback_data=f"slip:skip:{cid}")]])

# ---------- commands ----------
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await core.link_channel(uid(u), CHANNEL, str(u.effective_chat.id))
    await u.message.reply_text(await core.hello(uid(u)))


async def link(u: Update, c):
    """Make this Telegram account the same brain as the web demo user."""
    await core.link_alias(uid(u), core.CANONICAL_DEFAULT)
    await core.link_channel(core.CANONICAL_DEFAULT, CHANNEL, str(u.effective_chat.id))
    await u.message.reply_text("Linked. Whatever you dump on the web shows up here, and the other way round. One brain, two doors.")


async def iam(u: Update, c):
    """Rahul runs `/iam Rahul` so slips about him get delivered to his chat."""
    name = " ".join(c.args).strip()
    if not name:
        return await u.message.reply_text("Usage: /iam Rahul")
    await core.register_contact(core.CANONICAL_DEFAULT, name, str(u.effective_chat.id))
    await u.message.reply_text(f"Got it — you're {name}. If they slip on something for you, I'll bring you the note.")


async def now_cmd(u: Update, c):
    card = await core.now_card(uid(u))
    if not card:
        return await u.message.reply_text("Nothing needs you right now.")
    await u.message.reply_text(card["text"], reply_markup=surface_kb(card["id"]))


async def index_cmd(u: Update, c):
    from backend import voice
    await u.message.reply_text(await voice.render("index", None, core.optimism_index(uid(u))))


async def advance_cmd(u: Update, c):
    mins = int(c.args[0]) if c.args else 60
    await u.message.reply_text(await core.advance(mins))


async def resetclock_cmd(u: Update, c):
    await u.message.reply_text(await core.reset_clock())

# ---------- messages ----------
async def on_text(u: Update, c):
    await u.message.chat.send_action("typing")
    await u.message.reply_text(await core.dump(uid(u), u.message.text, source="telegram"))


async def on_voice(u: Update, c):
    await u.message.chat.send_action("typing")
    f = await u.message.voice.get_file()
    path = await f.download_to_drive()
    text = await transcribe_ogg(path)
    try:
        os.remove(path)
    except Exception:
        pass
    if not text:
        return await u.message.reply_text("Heard you, couldn't make out the words. Type it for me?")
    line = await core.dump(uid(u), text, source="telegram-voice")
    await u.message.reply_text(f"“{text}”\n\n{line}")


async def on_photo(u: Update, c):
    await u.message.chat.send_action("typing")
    f = await u.message.photo[-1].get_file()
    data = await f.download_as_bytearray()
    await u.message.reply_text(await core.dump_image(uid(u), bytes(data), source="telegram-photo"))

# ---------- buttons ----------
async def on_button(u: Update, c):
    q = u.callback_query
    await q.answer()
    kind, action, cid = q.data.split(":", 2)
    base = q.message.text or ""
    if kind == "noop":
        return
    if kind == "act":
        line = await core.act(cid, action)
        if action == "doing":
            return await q.edit_message_text(f"{base}\n\n— {line}", reply_markup=doing_kb(cid))
        if action == "done":
            return await q.edit_message_text(f"{base}\n\n— {line}\n\nRoughly how long did it take?", reply_markup=duration_kb(cid))
        return await q.edit_message_text(f"{base}\n\n— {line}")
    if kind == "dur":
        line = await core.set_actual(cid, int(action))
        return await q.edit_message_text(f"{base}\n\n— {line}")
    if kind == "slip":
        if action == "skip":
            return await q.edit_message_text(f"{base}\n\n— {await core.slip_skip(cid)}")
        res = await core.slip_send(cid)
        delivered = ""
        if res.get("recipient_chat_id") and res.get("draft") and APP:
            try:
                await APP.bot.send_message(res["recipient_chat_id"], res["draft"])
                delivered = f" Delivered to {res['people'][0]}."
            except Exception as e:
                log.warning("deliver failed: %s", e)
                delivered = " (Couldn't reach them on Telegram — copy the draft above.)"
        elif res.get("draft"):
            delivered = f" {res['people'][0] if res.get('people') else 'They'} isn't on Telegram yet — copy the draft above."
        return await q.edit_message_text(f"{base}\n\n— {res['line']}{delivered}")

# ---------- outbound: outbox → Telegram ----------
async def outbox_loop():
    while True:
        try:
            rows = core.outbox_pull(CHANNEL)
            for ev in rows:
                chat_id = await core.chat_id_for(ev["user_id"], CHANNEL)
                if not chat_id:
                    continue
                mode, cid = ev.get("mode"), ev.get("commitment_id")
                if mode == "slip":
                    await APP.bot.send_message(chat_id, f"{ev['text']}\n\n“{ev.get('draft') or ''}”", reply_markup=slip_kb(cid))
                elif mode == "surface":
                    await APP.bot.send_message(chat_id, ev["text"], reply_markup=surface_kb(cid))
                else:
                    await APP.bot.send_message(chat_id, ev["text"])
            if rows:
                core.outbox_ack([r["id"] for r in rows])
        except Exception as e:
            log.warning("outbox loop: %s", e)
        await asyncio.sleep(3)

# ---------- wiring ----------
async def post_init(app: Application):
    await app.bot.set_my_commands([
        ("start", "Say hi"), ("now", "The one thing, if any"), ("link", "Same brain as the web view"),
        ("iam", "Tell me who you are (for slips)"), ("index", "Your time optimism index"),
        ("advance", "Demo: move the clock forward N minutes")])
    await app.bot.set_my_short_description("A second brain that knows what time it is.")
    asyncio.create_task(outbox_loop())
    if os.getenv("RUN_ENGINE") == "1":
        asyncio.create_task(horizon.run(int(os.getenv("ENGINE_INTERVAL_S", "60"))))


def build() -> Application:
    global APP
    APP = Application.builder().token(TOKEN).post_init(post_init).build()
    for name, fn in [("start", start), ("now", now_cmd), ("link", link), ("iam", iam),
                     ("index", index_cmd), ("advance", advance_cmd), ("resetclock", resetclock_cmd)]:
        APP.add_handler(CommandHandler(name, fn))
    APP.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    APP.add_handler(MessageHandler(filters.VOICE, on_voice))
    APP.add_handler(MessageHandler(filters.PHOTO, on_photo))
    APP.add_handler(CallbackQueryHandler(on_button))
    return APP


if __name__ == "__main__":
    build().run_polling()

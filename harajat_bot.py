"""
Kunlik xarajatlar va eslatmalar uchun Telegram bot.
O'rnatish:  pip install "python-telegram-bot[job-queue]==21.*" tzdata
Ishga tushirish:  python harajat_bot.py
"""
import os
import sqlite3
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from telegram import (Update, ReplyKeyboardMarkup, InlineKeyboardButton,
                      InlineKeyboardMarkup)
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, ConversationHandler,
                          ContextTypes, filters)

# ====== SOZLAMALAR ======
TOKEN = os.getenv("BOT_TOKEN", "BU_YERGA_YANGI_TOKENNI_YOZING")
TZ = ZoneInfo("Asia/Tashkent")
# Railway'da konteyner diski har deploy'da tozalanadi, baza Volume'da turishi kerak
DB = os.path.join(os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "."), "harajatlar.db")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

# Suhbat bosqichlari
AMOUNT, DESC, PLACE, REM_TEXT, REM_TIME = range(5)

# Tugmalar
BTN_ADD = "➕ Xarajat qo'shish"
BTN_DAY = "📅 Bir kunlik"
BTN_WEEK = "📆 Bir haftalik"
BTN_MONTH = "🗓 Bir oylik"
BTN_YEAR = "📊 Bir yillik"
BTN_ALL = "📋 Hammasi"
BTN_REM = "🔔 Eslatmalar"
BTN_CANCEL = "❌ Bekor qilish"
BTN_SKIP = "⏭ O'tkazib yuborish"

MENU = ReplyKeyboardMarkup(
    [[BTN_ADD], [BTN_DAY, BTN_WEEK], [BTN_MONTH, BTN_YEAR], [BTN_ALL, BTN_REM]],
    resize_keyboard=True)
CANCEL_KB = ReplyKeyboardMarkup([[BTN_CANCEL]], resize_keyboard=True)
PLACE_KB = ReplyKeyboardMarkup([[BTN_SKIP], [BTN_CANCEL]], resize_keyboard=True)

PERIODS = {
    BTN_DAY: ("day", "Bir kunlik"),
    BTN_WEEK: ("week", "Bir haftalik"),
    BTN_MONTH: ("month", "Bir oylik"),
    BTN_YEAR: ("year", "Bir yillik"),
    BTN_ALL: ("all", "Barcha"),
}


# ====== MA'LUMOTLAR BAZASI ======
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, amount REAL, description TEXT,
            place TEXT, created_at TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS reminders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER, chat_id INTEGER, text TEXT, remind_time TEXT)""")


def now():
    return datetime.now(TZ)


def fmt_sum(x):
    return f"{x:,.0f}".replace(",", " ") + " so'm"


def fmt_date(s):
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y %H:%M")


def period_start(period):
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=today.weekday())
    if period == "month":
        return today.replace(day=1)
    if period == "year":
        return today.replace(month=1, day=1)
    return None  # hammasi


def save_expense(user_id, amount, desc, place):
    with db() as c:
        cur = c.execute(
            "INSERT INTO expenses(user_id, amount, description, place, created_at)"
            " VALUES(?,?,?,?,?)",
            (user_id, amount, desc, place, now().strftime("%Y-%m-%d %H:%M:%S")))
        return cur.lastrowid


def parse_amount(text):
    try:
        val = float(text.replace(" ", "").replace(",", "."))
        return val if val > 0 else None
    except ValueError:
        return None


# ====== ASOSIY BUYRUQLAR ======
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Assalomu alaykum, {update.effective_user.first_name}! 👋\n\n"
        "Men kunlik xarajatlaringizni hisoblab boraman.\n\n"
        "• Xarajat qo'shish uchun tugmani bosing yoki tez yozing:\n"
        "   <code>25000 taksi</code>\n"
        "• Xarajatni o'chirish: <code>/ochir 12</code> (12 — xarajat raqami)\n"
        "• Eslatmalar har kuni belgilangan vaqtda yuboriladi.",
        reply_markup=MENU, parse_mode="HTML")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.", reply_markup=MENU)
    return ConversationHandler.END


# ====== XARAJAT QO'SHISH ======
async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💰 Summani kiriting (masalan: 50000):",
                                    reply_markup=CANCEL_KB)
    return AMOUNT


async def add_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount = parse_amount(update.message.text)
    if amount is None:
        await update.message.reply_text("❗ Faqat musbat raqam kiriting, masalan: 50000")
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text("📝 Nimaga sarfladingiz? (masalan: non, taksi)")
    return DESC


async def add_desc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["desc"] = update.message.text.strip()
    await update.message.reply_text("📍 Qayerda? (masalan: Korzinka, bozor)",
                                    reply_markup=PLACE_KB)
    return PLACE


async def add_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    place = None if text == BTN_SKIP else text
    ud = context.user_data
    eid = save_expense(update.effective_user.id, ud["amount"], ud["desc"], place)
    await update.message.reply_text(
        f"✅ Saqlandi! (#{eid})\n"
        f"🕒 {now().strftime('%d.%m.%Y %H:%M')}\n"
        f"💰 {fmt_sum(ud['amount'])}\n"
        f"📝 {ud['desc']}\n"
        f"📍 {place or '—'}",
        reply_markup=MENU)
    ud.clear()
    return ConversationHandler.END


async def quick_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'25000 taksi' ko'rinishidagi tezkor kiritish."""
    parts = update.message.text.strip().split(maxsplit=1)
    amount = parse_amount(parts[0]) if parts else None
    if amount is None or len(parts) < 2:
        await update.message.reply_text(
            "Tushunmadim 🤔 Menyudan tanlang yoki shunday yozing: <code>25000 taksi</code>",
            reply_markup=MENU, parse_mode="HTML")
        return
    eid = save_expense(update.effective_user.id, amount, parts[1], None)
    await update.message.reply_text(
        f"✅ Saqlandi! (#{eid}) {fmt_sum(amount)} — {parts[1]}", reply_markup=MENU)


async def delete_expense(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Foydalanish: /ochir 12")
        return
    with db() as c:
        cur = c.execute("DELETE FROM expenses WHERE id=? AND user_id=?",
                        (int(context.args[0]), update.effective_user.id))
    msg = "🗑 O'chirildi." if cur.rowcount else "❗ Bunday xarajat topilmadi."
    await update.message.reply_text(msg, reply_markup=MENU)


# ====== HISOBOTLAR ======
async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    period, title = PERIODS[update.message.text]
    start_dt = period_start(period)
    q = "SELECT * FROM expenses WHERE user_id=?"
    params = [update.effective_user.id]
    if start_dt:
        q += " AND created_at >= ?"
        params.append(start_dt.strftime("%Y-%m-%d %H:%M:%S"))
    with db() as c:
        rows = c.execute(q + " ORDER BY created_at", params).fetchall()

    since = f" ({start_dt.strftime('%d.%m.%Y')} dan)" if start_dt else ""
    header = f"📊 <b>{title} xarajatlar</b>{since}\n\n"
    if not rows:
        await update.message.reply_text(header + "Hozircha xarajat yo'q.",
                                        parse_mode="HTML", reply_markup=MENU)
        return

    lines = []
    for r in rows:
        lines.append(
            f"#{r['id']} | 🕒 {fmt_date(r['created_at'])}\n"
            f"💰 {fmt_sum(r['amount'])} — {r['description']}\n"
            f"📍 {r['place'] or '—'}\n")
    total = sum(r["amount"] for r in rows)
    footer = f"\n<b>Jami: {fmt_sum(total)}</b> ({len(rows)} ta xarajat)"

    # Telegram xabari 4096 belgidan oshmasligi uchun bo'lib yuboramiz
    msg = header
    for line in lines:
        if len(msg) + len(line) > 3800:
            await update.message.reply_text(msg, parse_mode="HTML")
            msg = ""
        msg += line + "\n"
    await update.message.reply_text(msg + footer, parse_mode="HTML",
                                    reply_markup=MENU)


# ====== ESLATMALAR ======
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(context.job.chat_id,
                                   f"🔔 <b>Eslatma:</b>\n{context.job.data}",
                                   parse_mode="HTML")


def schedule_reminder(job_queue, r):
    h, m = map(int, r["remind_time"].split(":"))
    job_queue.run_daily(send_reminder, time=time(h, m, tzinfo=TZ),
                        chat_id=r["chat_id"], name=f"rem_{r['id']}",
                        data=r["text"])


def reminders_markup(user_id):
    with db() as c:
        rows = c.execute("SELECT * FROM reminders WHERE user_id=? ORDER BY remind_time",
                         (user_id,)).fetchall()
    kb = [[InlineKeyboardButton(f"🗑 {r['remind_time']} — {r['text'][:30]}",
                                callback_data=f"remdel_{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("➕ Eslatma qo'shish", callback_data="rem_add")])
    text = ("🔔 <b>Eslatmalaringiz</b> (har kuni yuboriladi)\n"
            "O'chirish uchun eslatmani bosing." if rows
            else "🔔 Hozircha eslatma yo'q.")
    return text, InlineKeyboardMarkup(kb)


async def reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, kb = reminders_markup(update.effective_user.id)
    await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")


async def rem_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "✏️ Eslatma matnini yozing:", reply_markup=CANCEL_KB)
    return REM_TEXT


async def rem_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rem_text"] = update.message.text.strip()
    await update.message.reply_text(
        "⏰ Har kuni soat nechida eslatay? (masalan: 08:30)")
    return REM_TIME


async def rem_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        t = datetime.strptime(update.message.text.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        await update.message.reply_text("❗ Vaqtni SS:DD shaklida yozing, masalan: 08:30")
        return REM_TIME
    text = context.user_data.pop("rem_text")
    with db() as c:
        cur = c.execute(
            "INSERT INTO reminders(user_id, chat_id, text, remind_time) VALUES(?,?,?,?)",
            (update.effective_user.id, update.effective_chat.id, text, t))
        rid = cur.lastrowid
    schedule_reminder(context.job_queue, {"id": rid, "chat_id": update.effective_chat.id,
                                          "text": text, "remind_time": t})
    await update.message.reply_text(
        f"✅ Eslatma saqlandi! Har kuni soat {t} da eslataman:\n«{text}»",
        reply_markup=MENU)
    return ConversationHandler.END


async def rem_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    rid = int(query.data.split("_")[1])
    with db() as c:
        c.execute("DELETE FROM reminders WHERE id=? AND user_id=?",
                  (rid, update.effective_user.id))
    for job in context.job_queue.get_jobs_by_name(f"rem_{rid}"):
        job.schedule_removal()
    await query.answer("🗑 Eslatma o'chirildi")
    text, kb = reminders_markup(update.effective_user.id)
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")


# ====== ISHGA TUSHIRISH ======
async def post_init(app: Application):
    """Bot qayta ishga tushganda eslatmalarni qayta rejalashtiramiz."""
    with db() as c:
        for r in c.execute("SELECT * FROM reminders").fetchall():
            schedule_reminder(app.job_queue, r)


def main():
    init_db()
    app = Application.builder().token(TOKEN).post_init(post_init).build()

    text_only = filters.TEXT & ~filters.COMMAND & ~filters.Regex(f"^{BTN_CANCEL}$")
    cancel_handlers = [CommandHandler("cancel", cancel),
                       MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel)]

    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(f"^{BTN_ADD}$"), add_start)],
        states={AMOUNT: [MessageHandler(text_only, add_amount)],
                DESC: [MessageHandler(text_only, add_desc)],
                PLACE: [MessageHandler(text_only, add_place)]},
        fallbacks=cancel_handlers))

    app.add_handler(ConversationHandler(
        entry_points=[CallbackQueryHandler(rem_add_start, pattern="^rem_add$")],
        states={REM_TEXT: [MessageHandler(text_only, rem_text)],
                REM_TIME: [MessageHandler(text_only, rem_time)]},
        fallbacks=cancel_handlers))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ochir", delete_expense))
    app.add_handler(CallbackQueryHandler(rem_delete, pattern=r"^remdel_\d+$"))
    period_regex = "^(" + "|".join(PERIODS.keys()) + ")$"
    app.add_handler(MessageHandler(filters.Regex(period_regex), report))
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_REM}$"), reminders_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, quick_add))

    print("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

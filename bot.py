# bot.py — DDNet Bridge Bot (python-telegram-bot 20.7)

import logging
import asyncio
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler, ContextTypes
)
from config import BOT_TOKEN, SKINS
from sessions import SessionManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

IP, PORT, NAME, CLAN, SKIN, PW, SAY_TEXT, RENAME_VALUE = range(8)

mgr: SessionManager = None

# ══════════════════════════════════════════════════════════
#  UI
# ══════════════════════════════════════════════════════════
BANNER = (
    "╔══════════════════════════════╗\n"
    "║  🎮  <b>DDNet Bridge Bot</b>       ║\n"
    "║  Telegram ↔ DDNet Chat       ║\n"
    "╚══════════════════════════════╝"
)
SEP = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

def bot_card(s):
    icon = "🟢" if s.active else "🔴"
    return (f"{icon} <b>{s.bot_id}</b> — <code>{s.ip}:{s.port}</code>\n"
            f"   👤 {s.name}  |  🏷 {s.clan or '—'}  |  🎨 {s.skin}\n"
            f"   💬 сообщений: {s.msg_count}")

def kb_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Новый бот", callback_data="c:new"),
         InlineKeyboardButton("📋 Мои боты",  callback_data="c:list")],
        [InlineKeyboardButton("❓ Помощь",    callback_data="c:help")],
    ])

def kb_bot(bot_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✉️ Написать", callback_data=f"b:{bot_id}:say"),
         InlineKeyboardButton("👥 Онлайн",   callback_data=f"b:{bot_id}:online")],
        [InlineKeyboardButton("✏️ Имя",      callback_data=f"b:{bot_id}:rename:name"),
         InlineKeyboardButton("🏷 Клан",     callback_data=f"b:{bot_id}:rename:clan")],
        [InlineKeyboardButton("🎨 Скин",     callback_data=f"b:{bot_id}:rename:skin"),
         InlineKeyboardButton("🔴 Стоп",     callback_data=f"b:{bot_id}:stop")],
        [InlineKeyboardButton("« Назад",     callback_data="c:list")],
    ])

def kb_botlist(chat_id):
    rows = []
    for s in mgr.list_bots(chat_id):
        icon = "🟢" if s.active else "🔴"
        rows.append([InlineKeyboardButton(
            f"{icon} {s.bot_id} ({s.name})",
            callback_data=f"b:{s.bot_id}:info"
        )])
    rows.append([
        InlineKeyboardButton("➕ Новый бот", callback_data="c:new"),
        InlineKeyboardButton("🏠 Главная",   callback_data="c:home"),
    ])
    return InlineKeyboardMarkup(rows)

def kb_skins():
    rows = []; row = []
    for i, skin in enumerate(SKINS):
        row.append(InlineKeyboardButton(skin, callback_data=f"skin:{skin}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([InlineKeyboardButton("✍️ Вручную", callback_data="skin:__manual__")])
    return InlineKeyboardMarkup(rows)

def kb_cancel():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="c:cancel")]])

def kb_back(bot_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"« {bot_id}", callback_data=f"b:{bot_id}:info"),
        InlineKeyboardButton("🏠 Главная",  callback_data="c:home"),
    ]])

def kb_home():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Главная", callback_data="c:home")]])

# ══════════════════════════════════════════════════════════
#  /start /bots
# ══════════════════════════════════════════════════════════
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cnt = len(mgr.list_bots(update.effective_chat.id))
    status = f"Активных ботов: <b>{cnt}</b>" if cnt else "Нет активных ботов"
    await update.message.reply_text(
        f"{BANNER}\n\n{status}\n\n"
        "Я соединяю Telegram с игровым чатом DDNet.\n"
        "Можно запустить <b>несколько ботов</b>!",
        parse_mode="HTML", reply_markup=kb_main()
    )

async def cmd_bots(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bots = mgr.list_bots(update.effective_chat.id)
    if not bots:
        await update.message.reply_text("Нет активных ботов.\n/new — создать")
        return
    lines = "\n\n".join(bot_card(s) for s in bots)
    await update.message.reply_text(
        f"🤖 <b>Твои боты</b>\n{SEP}\n\n{lines}",
        parse_mode="HTML", reply_markup=kb_botlist(update.effective_chat.id)
    )

# ══════════════════════════════════════════════════════════
#  Навигация
# ══════════════════════════════════════════════════════════
async def cb_home(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    cnt = len(mgr.list_bots(q.message.chat.id))
    status = f"Активных ботов: <b>{cnt}</b>" if cnt else "Нет активных ботов"
    await q.edit_message_text(
        f"{BANNER}\n\n{status}\n\nВыбери действие:",
        parse_mode="HTML", reply_markup=kb_main()
    )

async def cb_list(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    bots = mgr.list_bots(q.message.chat.id)
    if not bots:
        await q.answer("Нет активных ботов", show_alert=True); return
    lines = "\n\n".join(bot_card(s) for s in bots)
    await q.edit_message_text(
        f"🤖 <b>Твои боты</b>\n{SEP}\n\n{lines}\n\n{SEP}\nВыбери бота:",
        parse_mode="HTML", reply_markup=kb_botlist(q.message.chat.id)
    )

async def cb_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        f"❓ <b>Помощь</b>\n{SEP}\n\n"
        "<b>Что умеет бот:</b>\n"
        "• Несколько DDNet-ботов одновременно\n"
        "• Чат из игры → Telegram\n"
        "• Telegram → игровой чат\n"
        "• Смена имени, клана, скина\n"
        "• Онлайн и список игроков\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/new — создать бота\n"
        "/bots — список ботов\n\n"
        "<b>Иконки:</b>\n"
        "📢 общий чат  👥 командный\n"
        "🟢 зашёл  🔴 вышел",
        parse_mode="HTML", reply_markup=kb_home()
    )

async def cb_bot_info(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    bot_id = q.data.split(":")[1]
    s = mgr.get_bot(q.message.chat.id, bot_id)
    if not s:
        await q.answer("Бот не найден", show_alert=True); return
    await q.edit_message_text(
        f"🤖 <b>Бот {bot_id}</b>\n{SEP}\n\n"
        f"📡 Сервер: <code>{s.ip}:{s.port}</code>\n"
        f"👤 Имя: <b>{s.name}</b>\n"
        f"🏷 Клан: <b>{s.clan or '—'}</b>\n"
        f"🎨 Скин: <b>{s.skin}</b>\n"
        f"💬 Сообщений: <b>{s.msg_count}</b>\n"
        f"🔗 Статус: {'🟢 Активен' if s.active else '🔴 Отключён'}",
        parse_mode="HTML", reply_markup=kb_bot(bot_id)
    )

# ══════════════════════════════════════════════════════════
#  Форма подключения
# ══════════════════════════════════════════════════════════
async def start_connect(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        fn = update.callback_query.edit_message_text
    else:
        fn = update.message.reply_text
    await fn(
        f"➕ <b>Новый бот — Шаг 1/6</b>\n{SEP}\n\n"
        "📡 Введи <b>IP-адрес</b> сервера DDNet:\n"
        "<i>Пример: 195.201.110.46</i>",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return IP

async def form_ip(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ip = update.message.text.strip()
    if not ip or " " in ip:
        await update.message.reply_text("❌ Некорректный IP:", reply_markup=kb_cancel())
        return IP
    ctx.user_data["ip"] = ip
    await update.message.reply_text(
        f"✅ IP: <code>{ip}</code>\n\n➕ <b>Шаг 2/6</b>\n{SEP}\n\n"
        "🔌 Введи <b>порт</b>:\n<i>Стандартный: <code>8303</code></i>",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return PORT

async def form_port(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        port = int(update.message.text.strip())
        assert 1 <= port <= 65535
    except Exception:
        await update.message.reply_text("❌ Порт — число 1–65535:", reply_markup=kb_cancel())
        return PORT
    ctx.user_data["port"] = port
    await update.message.reply_text(
        f"✅ Порт: <code>{port}</code>\n\n➕ <b>Шаг 3/6</b>\n{SEP}\n\n"
        "👤 Введи <b>имя</b> бота (макс. 15 символов):",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return NAME

async def form_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()[:15] or "TGBot"
    ctx.user_data["name"] = name
    await update.message.reply_text(
        f"✅ Имя: <b>{name}</b>\n\n➕ <b>Шаг 4/6</b>\n{SEP}\n\n"
        "🏷 Введи <b>клан</b> (макс. 11 символов):\nНет → <code>-</code>",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return CLAN

async def form_clan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    clan = "" if update.message.text.strip() == "-" else update.message.text.strip()[:11]
    ctx.user_data["clan"] = clan
    await update.message.reply_text(
        f"✅ Клан: <b>{clan or '—'}</b>\n\n➕ <b>Шаг 5/6</b>\n{SEP}\n\n"
        "🎨 Выбери <b>скин</b> бота:",
        parse_mode="HTML", reply_markup=kb_skins()
    )
    return SKIN

async def form_skin_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    skin_val = q.data.split(":", 1)[1]
    if skin_val == "__manual__":
        await q.edit_message_text("✍️ Введи название скина:", reply_markup=kb_cancel())
        return SKIN
    ctx.user_data["skin"] = skin_val
    await q.edit_message_text(
        f"✅ Скин: <b>{skin_val}</b>\n\n➕ <b>Шаг 6/6</b>\n{SEP}\n\n"
        "🔐 Пароль сервера (нет → <code>-</code>):",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return PW

async def form_skin_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["skin"] = update.message.text.strip() or "default"
    await update.message.reply_text(
        f"✅ Скин: <b>{ctx.user_data['skin']}</b>\n\n➕ <b>Шаг 6/6</b>\n{SEP}\n\n"
        "🔐 Пароль сервера (нет → <code>-</code>):",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return PW

async def form_pw(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    pw = "" if update.message.text.strip() == "-" else update.message.text.strip()
    d = ctx.user_data
    ip = d["ip"]; port = d["port"]
    name = d["name"]; clan = d.get("clan",""); skin = d.get("skin","default")
    wait = await update.message.reply_text(
        f"⏳ Подключаю <b>{name}</b> к <code>{ip}:{port}</code>...",
        parse_mode="HTML"
    )
    ok, bot_id = await mgr.start(update.effective_chat.id, ip, port, name, clan, skin, pw)
    if ok:
        await wait.edit_text(
            f"✅ <b>Бот запущен!</b>\n{SEP}\n\n"
            f"🤖 ID: <b>{bot_id}</b>\n"
            f"📡 Сервер: <code>{ip}:{port}</code>\n"
            f"👤 Имя: <b>{name}</b>\n"
            f"🏷 Клан: <b>{clan or '—'}</b>\n"
            f"🎨 Скин: <b>{skin}</b>\n\n"
            "💬 Сообщения из игры будут приходить сюда.",
            parse_mode="HTML", reply_markup=kb_bot(bot_id)
        )
    else:
        await wait.edit_text(
            f"❌ Не удалось подключиться к <code>{ip}:{port}</code>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔄 Снова", callback_data="c:new"),
                InlineKeyboardButton("🏠 Главная", callback_data="c:home"),
            ]])
        )
    return ConversationHandler.END

async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("❌ Отменено.", reply_markup=kb_home())
    else:
        await update.message.reply_text("❌ Отменено.", reply_markup=kb_home())
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════
#  Онлайн
# ══════════════════════════════════════════════════════════
async def cb_online(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer("⏳")
    bot_id = q.data.split(":")[1]
    info = await mgr.fetch_online(q.message.chat.id, bot_id)
    if "error" in info:
        await q.message.reply_text(f"❌ {info['error']}"); return
    clist = info.get("client_list", [])
    players = "\n".join(
        f"  {'🏷 '+c['clan']+' ' if c['clan'] else ''}👤 {c['name']} ({c['score']}pts)"
        for c in clist[:20]
    ) or "  <i>Нет игроков</i>"
    await q.message.reply_text(
        f"📊 <b>Онлайн</b> [{bot_id}]\n{SEP}\n\n"
        f"🖥 <b>{info['name']}</b>\n"
        f"🗺 Карта: <b>{info['map']}</b>\n"
        f"🎮 Режим: <b>{info['game_type']}</b>\n"
        f"👥 Игроков: <b>{info['players']} / {info['max']}</b>\n\n"
        f"<b>Игроки:</b>\n{players}",
        parse_mode="HTML", reply_markup=kb_back(bot_id)
    )

# ══════════════════════════════════════════════════════════
#  Написать в чат
# ══════════════════════════════════════════════════════════
async def cb_say(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    bot_id = q.data.split(":")[1]
    ctx.user_data["bot_id"] = bot_id
    await q.edit_message_text(
        f"✉️ <b>Написать в чат</b> [{bot_id}]\n{SEP}\n\nВведи сообщение:",
        parse_mode="HTML", reply_markup=kb_cancel()
    )
    return SAY_TEXT

async def say_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bot_id = ctx.user_data.get("bot_id")
    text = update.message.text
    ok = await mgr.send(update.effective_chat.id, bot_id, text)
    if ok:
        await update.message.reply_text(
            f"✅ Отправлено в <b>[{bot_id}]</b>:\n<i>{text}</i>",
            parse_mode="HTML", reply_markup=kb_back(bot_id)
        )
    else:
        await update.message.reply_text("❌ Ошибка — бот отключён?", reply_markup=kb_back(bot_id))
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════
#  Смена имени / клана / скина
# ══════════════════════════════════════════════════════════
async def cb_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = q.data.split(":")
    bot_id = parts[1]; field = parts[3]
    ctx.user_data["bot_id"] = bot_id
    ctx.user_data["field"] = field
    icons = {"name": "👤", "clan": "🏷", "skin": "🎨"}
    if field == "skin":
        await q.edit_message_text(
            f"🎨 <b>Выбери скин</b> [{bot_id}]:",
            parse_mode="HTML", reply_markup=kb_skins()
        )
    else:
        labels = {"name": "имя (макс. 15)", "clan": "клан (макс. 11, или - убрать)"}
        await q.edit_message_text(
            f"{icons[field]} <b>Введи новое {labels[field]}</b> [{bot_id}]:",
            parse_mode="HTML", reply_markup=kb_cancel()
        )
    return RENAME_VALUE

async def rename_skin_btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    skin_val = q.data.split(":", 1)[1]
    bot_id = ctx.user_data["bot_id"]
    if skin_val == "__manual__":
        await q.edit_message_text("✍️ Введи название скина:", reply_markup=kb_cancel())
        return RENAME_VALUE
    await mgr.update_profile(q.message.chat.id, bot_id, skin=skin_val)
    await q.edit_message_text(
        f"✅ Скин <b>[{bot_id}]</b> → <b>{skin_val}</b>",
        parse_mode="HTML", reply_markup=kb_back(bot_id)
    )
    return ConversationHandler.END

async def rename_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bot_id = ctx.user_data["bot_id"]
    field  = ctx.user_data["field"]
    value  = update.message.text.strip()
    kwargs = {}
    if field == "name": kwargs["name"] = value[:15]
    elif field == "clan": kwargs["clan"] = "" if value == "-" else value[:11]
    elif field == "skin": kwargs["skin"] = value
    await mgr.update_profile(update.effective_chat.id, bot_id, **kwargs)
    icons = {"name": "👤", "clan": "🏷", "skin": "🎨"}
    await update.message.reply_text(
        f"✅ {icons[field]} <b>[{bot_id}]</b> → <b>{list(kwargs.values())[0] or '—'}</b>",
        parse_mode="HTML", reply_markup=kb_back(bot_id)
    )
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════
#  Стоп
# ══════════════════════════════════════════════════════════
async def cb_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    bot_id = q.data.split(":")[1]
    ok = await mgr.stop(q.message.chat.id, bot_id)
    await q.edit_message_text(
        f"🔴 Бот <b>[{bot_id}]</b> {'остановлен' if ok else 'не найден'}.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📋 Мои боты", callback_data="c:list"),
            InlineKeyboardButton("🏠 Главная",  callback_data="c:home"),
        ]])
    )

# ══════════════════════════════════════════════════════════
#  Relay текст → игра
# ══════════════════════════════════════════════════════════
async def relay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    bots = mgr.list_bots(update.effective_chat.id)
    if not bots:
        await update.message.reply_text("Нет активных ботов. /new — создать")
        return
    if len(bots) == 1:
        ok = await mgr.send(update.effective_chat.id, bots[0].bot_id, update.message.text)
        if ok: await update.message.reply_text("✅")
    else:
        rows = [[InlineKeyboardButton(
            f"🤖 {s.bot_id} ({s.name})", callback_data=f"relay:{s.bot_id}"
        )] for s in bots]
        await update.message.reply_text(
            "Через какого бота отправить?",
            reply_markup=InlineKeyboardMarkup(rows)
        )

async def cb_relay(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    bot_id = q.data.split(":")[1]
    text = q.message.reply_to_message.text if q.message.reply_to_message else ""
    if not text:
        await q.answer("Не найти текст", show_alert=True); return
    ok = await mgr.send(q.message.chat.id, bot_id, text)
    await q.edit_message_text(
        f"✅ Отправлено через <b>[{bot_id}]</b>: <i>{text}</i>", parse_mode="HTML"
    )

# ══════════════════════════════════════════════════════════
#  Запуск
# ══════════════════════════════════════════════════════════
def main():
    global mgr
    from telegram import Bot as TGBot

    app = Application.builder().token(BOT_TOKEN).build()

    class TGAdapter:
        def __init__(self, b): self._b = b
        async def send_message(self, chat_id, text, parse_mode=None):
            await self._b.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)

    mgr = SessionManager(TGAdapter(app.bot))

    connect_conv = ConversationHandler(
        entry_points=[
            CommandHandler("new", start_connect),
            CallbackQueryHandler(start_connect, pattern="^c:new$"),
        ],
        states={
            IP:   [MessageHandler(filters.TEXT & ~filters.COMMAND, form_ip)],
            PORT: [MessageHandler(filters.TEXT & ~filters.COMMAND, form_port)],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, form_name)],
            CLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, form_clan)],
            SKIN: [
                CallbackQueryHandler(form_skin_btn, pattern="^skin:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, form_skin_text),
            ],
            PW:   [MessageHandler(filters.TEXT & ~filters.COMMAND, form_pw)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^c:cancel$"),
        ],
        allow_reentry=True,
    )

    say_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_say, pattern=r"^b:.+:say$")],
        states={SAY_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, say_text)]},
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^c:cancel$"),
        ],
        allow_reentry=True,
    )

    rename_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(cb_rename, pattern=r"^b:.+:rename:.+$")],
        states={RENAME_VALUE: [
            CallbackQueryHandler(rename_skin_btn, pattern="^skin:"),
            MessageHandler(filters.TEXT & ~filters.COMMAND, rename_value),
        ]},
        fallbacks=[
            CommandHandler("cancel", cancel),
            CallbackQueryHandler(cancel, pattern="^c:cancel$"),
        ],
        allow_reentry=True,
    )

    app.add_handler(connect_conv)
    app.add_handler(say_conv)
    app.add_handler(rename_conv)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("bots",  cmd_bots))
    app.add_handler(CallbackQueryHandler(cb_home,     pattern="^c:home$"))
    app.add_handler(CallbackQueryHandler(cb_list,     pattern="^c:list$"))
    app.add_handler(CallbackQueryHandler(cb_help,     pattern="^c:help$"))
    app.add_handler(CallbackQueryHandler(cb_bot_info, pattern=r"^b:.+:info$"))
    app.add_handler(CallbackQueryHandler(cb_online,   pattern=r"^b:.+:online$"))
    app.add_handler(CallbackQueryHandler(cb_stop,     pattern=r"^b:.+:stop$"))
    app.add_handler(CallbackQueryHandler(cb_relay,    pattern=r"^relay:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, relay))

    logger.info("🚀 DDNet Bridge Bot запущен")
    app.run_polling()

if __name__ == "__main__":
    main()

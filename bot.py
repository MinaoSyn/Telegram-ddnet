# bot.py — DDNet Bridge Bot с крутым интерфейсом

import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, SKINS
from sessions import SessionManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())
mgr = SessionManager(bot)


# ══════════════════════════════════════════════════════════
#  FSM
# ══════════════════════════════════════════════════════════
class ConnectForm(StatesGroup):
    ip   = State()
    port = State()
    name = State()
    clan = State()
    skin = State()
    pw   = State()

class SayForm(StatesGroup):
    choose_bot = State()
    text       = State()

class RenameForm(StatesGroup):
    choose_bot = State()
    field      = State()   # name / clan / skin
    value      = State()


# ══════════════════════════════════════════════════════════
#  Текстовые «баннеры» — ASCII-art стиль
# ══════════════════════════════════════════════════════════
BANNER = (
    "╔══════════════════════════════╗\n"
    "║  🎮  <b>DDNet Bridge Bot</b>       ║\n"
    "║  Telegram ↔ DDNet Chat       ║\n"
    "╚══════════════════════════════╝"
)

def sep():
    return "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

def bot_card(s) -> str:
    icon = "🟢" if s.active else "🔴"
    return (
        f"{icon} <b>{s.bot_id}</b> — <code>{s.ip}:{s.port}</code>\n"
        f"   👤 {s.name}  |  🏷 {s.clan or '—'}  |  🎨 {s.skin}\n"
        f"   💬 сообщений: {s.msg_count}"
    )


# ══════════════════════════════════════════════════════════
#  Клавиатуры
# ══════════════════════════════════════════════════════════
def kb_main(chat_id: int) -> InlineKeyboardMarkup:
    bots = mgr.list_bots(chat_id)
    b = InlineKeyboardBuilder()
    b.button(text="➕ Новый бот",        callback_data="c:new")
    b.button(text="📋 Мои боты",         callback_data="c:list")
    b.button(text="❓ Помощь",            callback_data="c:help")
    b.adjust(2, 1)
    return b.as_markup()

def kb_bot(bot_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✉️ Написать",          callback_data=f"b:{bot_id}:say")
    b.button(text="👥 Онлайн",            callback_data=f"b:{bot_id}:online")
    b.button(text="✏️ Имя",               callback_data=f"b:{bot_id}:rename:name")
    b.button(text="🏷 Клан",              callback_data=f"b:{bot_id}:rename:clan")
    b.button(text="🎨 Скин",              callback_data=f"b:{bot_id}:rename:skin")
    b.button(text="🔴 Стоп",              callback_data=f"b:{bot_id}:stop")
    b.button(text="« Назад",             callback_data="c:list")
    b.adjust(2, 2, 2, 1)
    return b.as_markup()

def kb_botlist(chat_id: int) -> InlineKeyboardMarkup:
    bots = mgr.list_bots(chat_id)
    b = InlineKeyboardBuilder()
    for s in bots:
        icon = "🟢" if s.active else "🔴"
        b.button(text=f"{icon} {s.bot_id} ({s.name})",
                 callback_data=f"b:{s.bot_id}:info")
    b.button(text="➕ Новый бот", callback_data="c:new")
    b.button(text="🏠 Главная",   callback_data="c:home")
    b.adjust(1)
    return b.as_markup()

def kb_skins() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for skin in SKINS:
        b.button(text=skin, callback_data=f"skin:{skin}")
    b.button(text="✍️ Ввести вручную", callback_data="skin:__manual__")
    b.adjust(3)
    return b.as_markup()

def kb_cancel() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❌ Отмена", callback_data="c:cancel")
    return b.as_markup()

def kb_back(bot_id: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text=f"« {bot_id}", callback_data=f"b:{bot_id}:info")
    b.button(text="🏠 Главная", callback_data="c:home")
    b.adjust(2)
    return b.as_markup()


# ══════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════
@dp.message(Command("start"))
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.clear()
    bots = mgr.list_bots(msg.chat.id)
    cnt = len(bots)
    status_line = f"Активных ботов: <b>{cnt}</b>" if cnt else "Нет активных ботов"
    await msg.answer(
        f"{BANNER}\n\n"
        f"{status_line}\n\n"
        "Я соединяю Telegram с игровым чатом DDNet.\n"
        "Можно запустить <b>несколько ботов</b> на разных серверах!",
        reply_markup=kb_main(msg.chat.id)
    )


# ══════════════════════════════════════════════════════════
#  Глобальные callback — навигация
# ══════════════════════════════════════════════════════════
@dp.callback_query(F.data == "c:home")
async def cb_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    bots = mgr.list_bots(call.message.chat.id)
    cnt = len(bots)
    status_line = f"Активных ботов: <b>{cnt}</b>" if cnt else "Нет активных ботов"
    await call.message.edit_text(
        f"{BANNER}\n\n{status_line}\n\nВыбери действие:",
        reply_markup=kb_main(call.message.chat.id)
    )
    await call.answer()


@dp.callback_query(F.data == "c:list")
async def cb_list(call: CallbackQuery, state: FSMContext):
    await state.clear()
    bots = mgr.list_bots(call.message.chat.id)
    if not bots:
        await call.answer("Нет активных ботов", show_alert=True)
        return
    lines = "\n\n".join(bot_card(s) for s in bots)
    await call.message.edit_text(
        f"🤖 <b>Твои боты</b>\n{sep()}\n\n{lines}\n\n{sep()}\nВыбери бота:",
        reply_markup=kb_botlist(call.message.chat.id)
    )
    await call.answer()


@dp.callback_query(F.data == "c:help")
async def cb_help(call: CallbackQuery):
    await call.message.edit_text(
        f"❓ <b>Помощь</b>\n{sep()}\n\n"
        "<b>Что умеет бот:</b>\n"
        "• Запускать несколько DDNet-ботов\n"
        "• Читать чат и пересылать в Telegram\n"
        "• Отправлять сообщения в игровой чат\n"
        "• Менять имя, клан, скин бота на лету\n"
        "• Показывать онлайн сервера\n\n"
        "<b>Команды:</b>\n"
        "/start — главное меню\n"
        "/new — быстро создать бота\n"
        "/bots — список ботов\n\n"
        f"<b>Иконки чата:</b>\n"
        "📢 — общий чат\n"
        "👥 — командный чат\n"
        "🟢 — игрок зашёл\n"
        "🔴 — игрок вышел",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🏠 Главная", callback_data="c:home")
        ]])
    )
    await call.answer()


@dp.callback_query(F.data == "c:cancel")
async def cb_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text(
        "❌ Отменено.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🏠 Главная", callback_data="c:home")
        ]])
    )
    await call.answer()


# ══════════════════════════════════════════════════════════
#  Информация о боте
# ══════════════════════════════════════════════════════════
@dp.callback_query(F.data.startswith("b:") & F.data.endswith(":info"))
async def cb_bot_info(call: CallbackQuery):
    bot_id = call.data.split(":")[1]
    sess = mgr.get_bot(call.message.chat.id, bot_id)
    if not sess:
        await call.answer("Бот не найден", show_alert=True)
        return
    await call.message.edit_text(
        f"🤖 <b>Бот {bot_id}</b>\n{sep()}\n\n"
        f"📡 Сервер: <code>{sess.ip}:{sess.port}</code>\n"
        f"👤 Имя: <b>{sess.name}</b>\n"
        f"🏷 Клан: <b>{sess.clan or '—'}</b>\n"
        f"🎨 Скин: <b>{sess.skin}</b>\n"
        f"💬 Сообщений получено: <b>{sess.msg_count}</b>\n"
        f"🔗 Статус: {'🟢 Активен' if sess.active else '🔴 Отключён'}",
        reply_markup=kb_bot(bot_id)
    )
    await call.answer()


# ══════════════════════════════════════════════════════════
#  Создание нового бота — форма
# ══════════════════════════════════════════════════════════
async def _start_new_form(msg_or_call, state: FSMContext):
    if isinstance(msg_or_call, CallbackQuery):
        fn = msg_or_call.message.edit_text
        await msg_or_call.answer()
    else:
        fn = msg_or_call.answer

    await state.set_state(ConnectForm.ip)
    await fn(
        f"➕ <b>Новый бот — Шаг 1/6</b>\n{sep()}\n\n"
        "📡 Введи <b>IP-адрес</b> сервера DDNet:\n\n"
        "<i>Примеры серверов DDNet:</i>\n"
        "<code>195.201.110.46</code>\n"
        "<code>ddnet.org</code>",
        reply_markup=kb_cancel()
    )

@dp.message(Command("new"))
async def cmd_new(msg: types.Message, state: FSMContext):
    await _start_new_form(msg, state)

@dp.callback_query(F.data == "c:new")
async def cb_new(call: CallbackQuery, state: FSMContext):
    await _start_new_form(call, state)


@dp.message(ConnectForm.ip)
async def form_ip(msg: types.Message, state: FSMContext):
    ip = msg.text.strip()
    if not ip or len(ip) > 253:
        await msg.answer("❌ Некорректный IP/домен, попробуй ещё раз:", reply_markup=kb_cancel())
        return
    await state.update_data(ip=ip)
    await state.set_state(ConnectForm.port)
    await msg.answer(
        f"✅ IP: <code>{ip}</code>\n\n"
        f"➕ <b>Шаг 2/6</b>\n{sep()}\n\n"
        "🔌 Введи <b>порт</b> сервера:\n"
        "<i>Стандартный DDNet: <code>8303</code></i>",
        reply_markup=kb_cancel()
    )

@dp.message(ConnectForm.port)
async def form_port(msg: types.Message, state: FSMContext):
    try:
        port = int(msg.text.strip())
        assert 1 <= port <= 65535
    except Exception:
        await msg.answer("❌ Порт — число от 1 до 65535:", reply_markup=kb_cancel())
        return
    await state.update_data(port=port)
    await state.set_state(ConnectForm.name)
    await msg.answer(
        f"✅ Порт: <code>{port}</code>\n\n"
        f"➕ <b>Шаг 3/6</b>\n{sep()}\n\n"
        "👤 Введи <b>имя</b> бота в игре (макс. 15 символов):\n"
        "<i>Пример: <code>MyBot</code></i>",
        reply_markup=kb_cancel()
    )

@dp.message(ConnectForm.name)
async def form_name(msg: types.Message, state: FSMContext):
    name = msg.text.strip()[:15] or "TGBot"
    await state.update_data(name=name)
    await state.set_state(ConnectForm.clan)
    await msg.answer(
        f"✅ Имя: <b>{name}</b>\n\n"
        f"➕ <b>Шаг 4/6</b>\n{sep()}\n\n"
        "🏷 Введи <b>клан</b> бота (макс. 11 символов):\n"
        "Нет клана — напиши <code>-</code>",
        reply_markup=kb_cancel()
    )

@dp.message(ConnectForm.clan)
async def form_clan(msg: types.Message, state: FSMContext):
    clan = "" if msg.text.strip() == "-" else msg.text.strip()[:11]
    await state.update_data(clan=clan)
    await state.set_state(ConnectForm.skin)
    await msg.answer(
        f"✅ Клан: <b>{clan or '—'}</b>\n\n"
        f"➕ <b>Шаг 5/6</b>\n{sep()}\n\n"
        "🎨 Выбери <b>скин</b> бота:",
        reply_markup=kb_skins()
    )

@dp.callback_query(F.data.startswith("skin:"), ConnectForm.skin)
async def form_skin_pick(call: CallbackQuery, state: FSMContext):
    skin_val = call.data.split(":", 1)[1]
    await call.answer()
    if skin_val == "__manual__":
        await call.message.edit_text(
            "✍️ Введи название скина вручную:",
            reply_markup=kb_cancel()
        )
        return
    await state.update_data(skin=skin_val)
    await state.set_state(ConnectForm.pw)
    await call.message.edit_text(
        f"✅ Скин: <b>{skin_val}</b>\n\n"
        f"➕ <b>Шаг 6/6</b>\n{sep()}\n\n"
        "🔐 Пароль сервера (если нет — напиши <code>-</code>):",
        reply_markup=kb_cancel()
    )

@dp.message(ConnectForm.skin)
async def form_skin_manual(msg: types.Message, state: FSMContext):
    skin = msg.text.strip() or "default"
    await state.update_data(skin=skin)
    await state.set_state(ConnectForm.pw)
    await msg.answer(
        f"✅ Скин: <b>{skin}</b>\n\n"
        f"➕ <b>Шаг 6/6</b>\n{sep()}\n\n"
        "🔐 Пароль сервера (если нет — напиши <code>-</code>):",
        reply_markup=kb_cancel()
    )

@dp.message(ConnectForm.pw)
async def form_pw(msg: types.Message, state: FSMContext):
    pw = "" if msg.text.strip() == "-" else msg.text.strip()
    data = await state.get_data()
    await state.clear()

    ip   = data["ip"]
    port = data["port"]
    name = data["name"]
    clan = data.get("clan", "")
    skin = data.get("skin", "default")

    wait = await msg.answer(
        f"⏳ Подключаю <b>{name}</b> к <code>{ip}:{port}</code>...\n"
        "Это займёт несколько секунд."
    )

    ok, bot_id = await mgr.start(
        msg.chat.id, ip, port, name, clan, skin, pw
    )

    if ok:
        await wait.edit_text(
            f"✅ <b>Бот запущен!</b>\n{sep()}\n\n"
            f"🤖 ID: <b>{bot_id}</b>\n"
            f"📡 Сервер: <code>{ip}:{port}</code>\n"
            f"👤 Имя: <b>{name}</b>\n"
            f"🏷 Клан: <b>{clan or '—'}</b>\n"
            f"🎨 Скин: <b>{skin}</b>\n\n"
            "💬 Сообщения из игры будут приходить сюда.\n"
            "Используй меню бота чтобы писать в чат.",
            reply_markup=kb_bot(bot_id)
        )
    else:
        await wait.edit_text(
            f"❌ <b>Не удалось подключиться</b>\n\n"
            f"Сервер <code>{ip}:{port}</code> недоступен.\n"
            "Проверь IP и порт.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="🔄 Попробовать снова", callback_data="c:new"),
                InlineKeyboardButton(text="🏠 Главная", callback_data="c:home"),
            ]])
        )


# ══════════════════════════════════════════════════════════
#  Онлайн сервера
# ══════════════════════════════════════════════════════════
@dp.callback_query(F.data.regexp(r"^b:(.+):online$"))
async def cb_online(call: CallbackQuery):
    bot_id = call.data.split(":")[1]
    await call.answer("⏳ Запрашиваю...")
    info = await mgr.fetch_online(call.message.chat.id, bot_id)
    if "error" in info:
        await call.message.answer(f"❌ {info['error']}")
        return

    players_lines = ""
    clist = info.get("client_list", [])
    if clist:
        players_lines = "\n".join(
            f"  {'🏷 ' + c['clan'] + ' ' if c['clan'] else ''}👤 {c['name']}  ({c['score']}pts)"
            for c in clist[:20]
        )
    else:
        players_lines = "  <i>Нет игроков</i>"

    await call.message.answer(
        f"📊 <b>Онлайн сервера</b> [{bot_id}]\n{sep()}\n\n"
        f"🖥 <b>{info['name']}</b>\n"
        f"🗺 Карта: <b>{info['map']}</b>\n"
        f"🎮 Режим: <b>{info['game_type']}</b>\n"
        f"👥 Игроков: <b>{info['players']} / {info['max']}</b>\n"
        f"⚙️ Версия: <b>{info['version']}</b>\n\n"
        f"<b>Список игроков:</b>\n{players_lines}",
        reply_markup=kb_back(bot_id)
    )


# ══════════════════════════════════════════════════════════
#  Написать в чат
# ══════════════════════════════════════════════════════════
@dp.callback_query(F.data.regexp(r"^b:(.+):say$"))
async def cb_say(call: CallbackQuery, state: FSMContext):
    bot_id = call.data.split(":")[1]
    await state.set_state(SayForm.text)
    await state.update_data(bot_id=bot_id)
    await call.message.edit_text(
        f"✉️ <b>Написать в чат</b> [{bot_id}]\n{sep()}\n\n"
        "Введи сообщение для игрового чата:",
        reply_markup=kb_cancel()
    )
    await call.answer()

@dp.message(SayForm.text)
async def say_text(msg: types.Message, state: FSMContext):
    data = await state.get_data()
    bot_id = data.get("bot_id")
    await state.clear()
    ok = await mgr.send(msg.chat.id, bot_id, msg.text)
    if ok:
        await msg.answer(
            f"✅ Отправлено в <b>[{bot_id}]</b>:\n<i>{msg.text}</i>",
            reply_markup=kb_back(bot_id)
        )
    else:
        await msg.answer("❌ Ошибка отправки — бот отключён?",
                         reply_markup=kb_back(bot_id))


# ══════════════════════════════════════════════════════════
#  Переименование / смена клана / скина
# ══════════════════════════════════════════════════════════
@dp.callback_query(F.data.regexp(r"^b:(.+):rename:(name|clan|skin)$"))
async def cb_rename(call: CallbackQuery, state: FSMContext):
    parts  = call.data.split(":")
    bot_id = parts[1]
    field  = parts[3]  # name / clan / skin
    await state.set_state(RenameForm.value)
    await state.update_data(bot_id=bot_id, field=field)

    labels = {"name": "имя (макс. 15 символов)",
              "clan": "клан (макс. 11 символов, или <code>-</code> чтобы убрать)",
              "skin": "скин"}
    icons  = {"name": "👤", "clan": "🏷", "skin": "🎨"}

    if field == "skin":
        await call.message.edit_text(
            f"{icons[field]} <b>Выбери новый скин</b> [{bot_id}]:",
            reply_markup=kb_skins()
        )
    else:
        await call.message.edit_text(
            f"{icons[field]} <b>Введи новое {labels[field]}</b> [{bot_id}]:",
            reply_markup=kb_cancel()
        )
    await call.answer()

@dp.callback_query(F.data.startswith("skin:"), RenameForm.value)
async def rename_skin_pick(call: CallbackQuery, state: FSMContext):
    skin_val = call.data.split(":", 1)[1]
    await call.answer()
    data = await state.get_data()
    bot_id = data["bot_id"]
    if skin_val == "__manual__":
        await call.message.edit_text("✍️ Введи название скина:", reply_markup=kb_cancel())
        return
    await state.clear()
    ok = await mgr.update_profile(call.message.chat.id, bot_id, skin=skin_val)
    await call.message.edit_text(
        f"✅ Скин бота <b>[{bot_id}]</b> изменён на <b>{skin_val}</b>",
        reply_markup=kb_back(bot_id)
    )

@dp.message(RenameForm.value)
async def rename_value(msg: types.Message, state: FSMContext):
    data  = await state.get_data()
    bot_id = data["bot_id"]
    field  = data["field"]
    value  = msg.text.strip()
    await state.clear()

    kwargs = {}
    if field == "name":
        kwargs["name"] = value[:15]
    elif field == "clan":
        kwargs["clan"] = "" if value == "-" else value[:11]
    elif field == "skin":
        kwargs["skin"] = value

    ok = await mgr.update_profile(msg.chat.id, bot_id, **kwargs)
    icons = {"name": "👤", "clan": "🏷", "skin": "🎨"}
    display = kwargs.get(field) or "—"
    await msg.answer(
        f"✅ {icons[field]} <b>[{bot_id}]</b> обновлён: <b>{display}</b>",
        reply_markup=kb_back(bot_id)
    )


# ══════════════════════════════════════════════════════════
#  Остановить бота
# ══════════════════════════════════════════════════════════
@dp.callback_query(F.data.regexp(r"^b:(.+):stop$"))
async def cb_stop(call: CallbackQuery):
    bot_id = call.data.split(":")[1]
    ok = await mgr.stop(call.message.chat.id, bot_id)
    await call.message.edit_text(
        f"🔴 Бот <b>[{bot_id}]</b> {'остановлен' if ok else 'не найден'}.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📋 Мои боты", callback_data="c:list"),
            InlineKeyboardButton(text="🏠 Главная",  callback_data="c:home"),
        ]])
    )
    await call.answer()


# ══════════════════════════════════════════════════════════
#  /bots — быстрый список
# ══════════════════════════════════════════════════════════
@dp.message(Command("bots"))
async def cmd_bots(msg: types.Message, state: FSMContext):
    await state.clear()
    bots = mgr.list_bots(msg.chat.id)
    if not bots:
        await msg.answer("Нет активных ботов.\n/new — создать бота")
        return
    lines = "\n\n".join(bot_card(s) for s in bots)
    await msg.answer(
        f"🤖 <b>Твои боты</b>\n{sep()}\n\n{lines}",
        reply_markup=kb_botlist(msg.chat.id)
    )


# ══════════════════════════════════════════════════════════
#  Текстовые сообщения → в чат (если только 1 бот)
# ══════════════════════════════════════════════════════════
@dp.message(F.text & ~F.text.startswith("/"))
async def relay(msg: types.Message, state: FSMContext):
    cur = await state.get_state()
    if cur:
        return  # идёт форма
    bots = mgr.list_bots(msg.chat.id)
    if not bots:
        await msg.answer("Нет активных ботов. Создай через /new или 🏠 /start")
        return
    if len(bots) == 1:
        ok = await mgr.send(msg.chat.id, bots[0].bot_id, msg.text)
        if ok:
            await msg.react([types.ReactionTypeEmoji(emoji="👍")])
    else:
        # Несколько ботов — просим выбрать
        b = InlineKeyboardBuilder()
        for s in bots:
            b.button(text=f"🤖 {s.bot_id} ({s.name})",
                     callback_data=f"relay:{s.bot_id}:{msg.message_id}")
        b.adjust(1)
        await msg.reply(
            "Через какого бота отправить?",
            reply_markup=b.as_markup()
        )

@dp.callback_query(F.data.startswith("relay:"))
async def cb_relay(call: CallbackQuery):
    _, bot_id, msg_id = call.data.split(":")
    # Текст берём из оригинального сообщения (reply)
    text = call.message.reply_to_message.text if call.message.reply_to_message else ""
    if not text:
        await call.answer("Не могу найти сообщение", show_alert=True)
        return
    ok = await mgr.send(call.message.chat.id, bot_id, text)
    await call.message.edit_text(
        f"✅ Отправлено через <b>[{bot_id}]</b>: <i>{text}</i>"
    )
    await call.answer()


# ══════════════════════════════════════════════════════════
#  Запуск
# ══════════════════════════════════════════════════════════
async def main():
    logger.info("🚀 DDNet Bridge Bot запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await mgr.stop_all()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())

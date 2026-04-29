# bot.py — DDNet Bridge Bot (ZERO dependencies, pure Python 3.13)

import asyncio
import json
import urllib.request
import urllib.parse
import urllib.error
import logging
import time
import threading

from config import BOT_TOKEN, SKINS
from sessions import SessionManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ══════════════════════════════════════════════════════════
#  HTTP helpers
# ══════════════════════════════════════════════════════════
def tg_get(method, params=None):
    url = f"{API}/{method}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error(f"GET {method}: {e}")
        return None

def tg_post(method, data):
    url = f"{API}/{method}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error(f"POST {method}: {e}")
        return None

def send_msg(chat_id, text, reply_markup=None, parse_mode="HTML"):
    d = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        d["reply_markup"] = json.dumps(reply_markup)
    return tg_post("sendMessage", d)

def edit_msg(chat_id, msg_id, text, reply_markup=None):
    d = {"chat_id": chat_id, "message_id": msg_id,
         "text": text, "parse_mode": "HTML"}
    if reply_markup:
        d["reply_markup"] = json.dumps(reply_markup)
    return tg_post("editMessageText", d)

def answer_cb(cb_id, text="", alert=False):
    tg_post("answerCallbackQuery",
            {"callback_query_id": cb_id, "text": text, "show_alert": alert})

# ══════════════════════════════════════════════════════════
#  Клавиатуры
# ══════════════════════════════════════════════════════════
BANNER = (
    "╔══════════════════════════════╗\n"
    "║  🎮  <b>DDNet Bridge Bot</b>       ║\n"
    "║  Telegram ↔ DDNet Chat       ║\n"
    "╚══════════════════════════════╝"
)
SEP = "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬"

def kb_main():
    return {"inline_keyboard": [
        [{"text": "➕ Новый бот", "callback_data": "c:new"},
         {"text": "📋 Мои боты",  "callback_data": "c:list"}],
        [{"text": "❓ Помощь",    "callback_data": "c:help"}],
    ]}

def kb_bot(bot_id):
    return {"inline_keyboard": [
        [{"text": "✉️ Написать", "callback_data": f"b:{bot_id}:say"},
         {"text": "👥 Онлайн",   "callback_data": f"b:{bot_id}:online"}],
        [{"text": "✏️ Имя",      "callback_data": f"b:{bot_id}:rename:name"},
         {"text": "🏷 Клан",     "callback_data": f"b:{bot_id}:rename:clan"}],
        [{"text": "🎨 Скин",     "callback_data": f"b:{bot_id}:rename:skin"},
         {"text": "🔴 Стоп",     "callback_data": f"b:{bot_id}:stop"}],
        [{"text": "« Назад",     "callback_data": "c:list"}],
    ]}

def kb_botlist(chat_id):
    rows = []
    for s in mgr.list_bots(chat_id):
        icon = "🟢" if s.active else "🔴"
        rows.append([{"text": f"{icon} {s.bot_id} ({s.name})",
                      "callback_data": f"b:{s.bot_id}:info"}])
    rows.append([
        {"text": "➕ Новый бот", "callback_data": "c:new"},
        {"text": "🏠 Главная",   "callback_data": "c:home"},
    ])
    return {"inline_keyboard": rows}

def kb_skins():
    rows = []; row = []
    for skin in SKINS:
        row.append({"text": skin, "callback_data": f"skin:{skin}"})
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([{"text": "✍️ Вручную", "callback_data": "skin:__manual__"}])
    return {"inline_keyboard": rows}

def kb_cancel():
    return {"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "c:cancel"}]]}

def kb_back(bot_id):
    return {"inline_keyboard": [[
        {"text": f"« {bot_id}", "callback_data": f"b:{bot_id}:info"},
        {"text": "🏠 Главная",  "callback_data": "c:home"},
    ]]}

def kb_home():
    return {"inline_keyboard": [[{"text": "🏠 Главная", "callback_data": "c:home"}]]}

def bot_card(s):
    icon = "🟢" if s.active else "🔴"
    return (f"{icon} <b>{s.bot_id}</b> — <code>{s.ip}:{s.port}</code>\n"
            f"   👤 {s.name}  |  🏷 {s.clan or '—'}  |  🎨 {s.skin}\n"
            f"   💬 сообщений: {s.msg_count}")

# ══════════════════════════════════════════════════════════
#  Состояния пользователей
# ══════════════════════════════════════════════════════════
# state[chat_id] = {"step": "...", "data": {...}}
states = {}

STEPS = ["ip","port","name","clan","skin","pw","say","rename"]

def get_state(chat_id):
    return states.get(chat_id, {})

def set_state(chat_id, step, **data):
    states[chat_id] = {"step": step, "data": data}

def clear_state(chat_id):
    states.pop(chat_id, None)

# ══════════════════════════════════════════════════════════
#  Обработчики команд
# ══════════════════════════════════════════════════════════
def handle_start(chat_id):
    cnt = len(mgr.list_bots(chat_id))
    status = f"Активных ботов: <b>{cnt}</b>" if cnt else "Нет активных ботов"
    send_msg(chat_id,
        f"{BANNER}\n\n{status}\n\n"
        "Я соединяю Telegram с игровым чатом DDNet.\n"
        "Можно запустить <b>несколько ботов</b>!",
        reply_markup=kb_main()
    )

def handle_bots(chat_id):
    bots = mgr.list_bots(chat_id)
    if not bots:
        send_msg(chat_id, "Нет активных ботов.\n/new — создать"); return
    lines = "\n\n".join(bot_card(s) for s in bots)
    send_msg(chat_id, f"🤖 <b>Твои боты</b>\n{SEP}\n\n{lines}",
             reply_markup=kb_botlist(chat_id))

def handle_new(chat_id):
    set_state(chat_id, "ip")
    send_msg(chat_id,
        f"➕ <b>Новый бот — Шаг 1/6</b>\n{SEP}\n\n"
        "📡 Введи <b>IP-адрес</b> сервера DDNet:\n"
        "<i>Пример: 195.201.110.46</i>",
        reply_markup=kb_cancel()
    )

# ══════════════════════════════════════════════════════════
#  Обработчик текста (форма)
# ══════════════════════════════════════════════════════════
def handle_text(chat_id, text):
    st = get_state(chat_id)
    step = st.get("step")
    data = st.get("data", {})

    if step == "ip":
        if not text or " " in text:
            send_msg(chat_id, "❌ Некорректный IP:", reply_markup=kb_cancel()); return
        set_state(chat_id, "port", ip=text)
        send_msg(chat_id,
            f"✅ IP: <code>{text}</code>\n\n➕ <b>Шаг 2/6</b>\n{SEP}\n\n"
            "🔌 Введи <b>порт</b>:\n<i>Стандартный: <code>8303</code></i>",
            reply_markup=kb_cancel())

    elif step == "port":
        try:
            port = int(text); assert 1 <= port <= 65535
        except:
            send_msg(chat_id, "❌ Порт — число 1–65535:", reply_markup=kb_cancel()); return
        set_state(chat_id, "name", ip=data["ip"], port=port)
        send_msg(chat_id,
            f"✅ Порт: <code>{port}</code>\n\n➕ <b>Шаг 3/6</b>\n{SEP}\n\n"
            "👤 Введи <b>имя</b> бота (макс. 15 символов):",
            reply_markup=kb_cancel())

    elif step == "name":
        name = text.strip()[:15] or "TGBot"
        set_state(chat_id, "clan", ip=data["ip"], port=data["port"], name=name)
        send_msg(chat_id,
            f"✅ Имя: <b>{name}</b>\n\n➕ <b>Шаг 4/6</b>\n{SEP}\n\n"
            "🏷 Введи <b>клан</b> (макс. 11 символов):\nНет → <code>-</code>",
            reply_markup=kb_cancel())

    elif step == "clan":
        clan = "" if text.strip() == "-" else text.strip()[:11]
        set_state(chat_id, "skin", ip=data["ip"], port=data["port"],
                  name=data["name"], clan=clan)
        send_msg(chat_id,
            f"✅ Клан: <b>{clan or '—'}</b>\n\n➕ <b>Шаг 5/6</b>\n{SEP}\n\n"
            "🎨 Выбери <b>скин</b> бота:",
            reply_markup=kb_skins())

    elif step == "skin_manual":
        skin = text.strip() or "default"
        set_state(chat_id, "pw", ip=data["ip"], port=data["port"],
                  name=data["name"], clan=data["clan"], skin=skin)
        send_msg(chat_id,
            f"✅ Скин: <b>{skin}</b>\n\n➕ <b>Шаг 6/6</b>\n{SEP}\n\n"
            "🔐 Пароль сервера (нет → <code>-</code>):",
            reply_markup=kb_cancel())

    elif step == "pw":
        pw = "" if text.strip() == "-" else text.strip()
        ip = data["ip"]; port = data["port"]
        name = data["name"]; clan = data.get("clan",""); skin = data.get("skin","default")
        clear_state(chat_id)
        m = send_msg(chat_id, f"⏳ Подключаю <b>{name}</b> к <code>{ip}:{port}</code>...")
        msg_id = m["result"]["message_id"] if m else None

        async def do_connect():
            ok, bot_id = await mgr.start(chat_id, ip, port, name, clan, skin, pw)
            if ok:
                edit_msg(chat_id, msg_id,
                    f"✅ <b>Бот запущен!</b>\n{SEP}\n\n"
                    f"🤖 ID: <b>{bot_id}</b>\n"
                    f"📡 Сервер: <code>{ip}:{port}</code>\n"
                    f"👤 Имя: <b>{name}</b>\n"
                    f"🏷 Клан: <b>{clan or '—'}</b>\n"
                    f"🎨 Скин: <b>{skin}</b>\n\n"
                    "💬 Сообщения из игры будут приходить сюда.",
                    reply_markup=kb_bot(bot_id))
            else:
                edit_msg(chat_id, msg_id,
                    f"❌ Не удалось подключиться к <code>{ip}:{port}</code>",
                    reply_markup={"inline_keyboard": [[
                        {"text": "🔄 Снова",    "callback_data": "c:new"},
                        {"text": "🏠 Главная", "callback_data": "c:home"},
                    ]]})

        asyncio.run_coroutine_threadsafe(do_connect(), loop)

    elif step == "say":
        bot_id = data["bot_id"]
        clear_state(chat_id)
        async def do_say():
            ok = await mgr.send(chat_id, bot_id, text)
            if ok:
                send_msg(chat_id,
                    f"✅ Отправлено в <b>[{bot_id}]</b>:\n<i>{text}</i>",
                    reply_markup=kb_back(bot_id))
            else:
                send_msg(chat_id, "❌ Ошибка — бот отключён?", reply_markup=kb_back(bot_id))
        asyncio.run_coroutine_threadsafe(do_say(), loop)

    elif step == "rename":
        bot_id = data["bot_id"]; field = data["field"]
        clear_state(chat_id)
        kwargs = {}
        if field == "name": kwargs["name"] = text[:15]
        elif field == "clan": kwargs["clan"] = "" if text=="-" else text[:11]
        elif field == "skin": kwargs["skin"] = text
        icons = {"name": "👤", "clan": "🏷", "skin": "🎨"}
        async def do_rename():
            await mgr.update_profile(chat_id, bot_id, **kwargs)
            send_msg(chat_id,
                f"✅ {icons[field]} <b>[{bot_id}]</b> → <b>{list(kwargs.values())[0] or '—'}</b>",
                reply_markup=kb_back(bot_id))
        asyncio.run_coroutine_threadsafe(do_rename(), loop)

    else:
        # Relay в игру
        bots = mgr.list_bots(chat_id)
        if not bots:
            send_msg(chat_id, "Нет активных ботов. /new — создать"); return
        if len(bots) == 1:
            async def do_relay():
                ok = await mgr.send(chat_id, bots[0].bot_id, text)
                if ok: send_msg(chat_id, "✅")
            asyncio.run_coroutine_threadsafe(do_relay(), loop)
        else:
            rows = [[{"text": f"🤖 {s.bot_id} ({s.name})",
                      "callback_data": f"relay:{s.bot_id}"}] for s in bots]
            send_msg(chat_id, "Через какого бота отправить?",
                     reply_markup={"inline_keyboard": rows})

# ══════════════════════════════════════════════════════════
#  Обработчик callback
# ══════════════════════════════════════════════════════════
def handle_callback(cb_id, chat_id, msg_id, data):
    answer_cb(cb_id)

    if data == "c:home":
        clear_state(chat_id)
        cnt = len(mgr.list_bots(chat_id))
        status = f"Активных ботов: <b>{cnt}</b>" if cnt else "Нет активных ботов"
        edit_msg(chat_id, msg_id, f"{BANNER}\n\n{status}\n\nВыбери действие:", kb_main())

    elif data == "c:list":
        clear_state(chat_id)
        bots = mgr.list_bots(chat_id)
        if not bots:
            answer_cb(cb_id, "Нет активных ботов", True); return
        lines = "\n\n".join(bot_card(s) for s in bots)
        edit_msg(chat_id, msg_id,
            f"🤖 <b>Твои боты</b>\n{SEP}\n\n{lines}\n\n{SEP}\nВыбери бота:",
            kb_botlist(chat_id))

    elif data == "c:help":
        edit_msg(chat_id, msg_id,
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
            "<b>Иконки чата:</b>\n"
            "📢 общий  👥 командный\n"
            "🟢 зашёл  🔴 вышел",
            kb_home())

    elif data == "c:new":
        clear_state(chat_id)
        set_state(chat_id, "ip")
        edit_msg(chat_id, msg_id,
            f"➕ <b>Новый бот — Шаг 1/6</b>\n{SEP}\n\n"
            "📡 Введи <b>IP-адрес</b> сервера DDNet:\n"
            "<i>Пример: 195.201.110.46</i>",
            kb_cancel())

    elif data == "c:cancel":
        clear_state(chat_id)
        edit_msg(chat_id, msg_id, "❌ Отменено.", kb_home())

    elif data.startswith("b:") and data.endswith(":info"):
        bot_id = data.split(":")[1]
        s = mgr.get_bot(chat_id, bot_id)
        if not s: answer_cb(cb_id, "Бот не найден", True); return
        edit_msg(chat_id, msg_id,
            f"🤖 <b>Бот {bot_id}</b>\n{SEP}\n\n"
            f"📡 Сервер: <code>{s.ip}:{s.port}</code>\n"
            f"👤 Имя: <b>{s.name}</b>\n"
            f"🏷 Клан: <b>{s.clan or '—'}</b>\n"
            f"🎨 Скин: <b>{s.skin}</b>\n"
            f"💬 Сообщений: <b>{s.msg_count}</b>\n"
            f"🔗 Статус: {'🟢 Активен' if s.active else '🔴 Отключён'}",
            kb_bot(bot_id))

    elif data.startswith("b:") and ":online" in data:
        bot_id = data.split(":")[1]
        async def do_online():
            info = await mgr.fetch_online(chat_id, bot_id)
            if "error" in info:
                send_msg(chat_id, f"❌ {info['error']}"); return
            clist = info.get("client_list", [])
            players = "\n".join(
                f"  {'🏷 '+c['clan']+' ' if c['clan'] else ''}👤 {c['name']} ({c['score']}pts)"
                for c in clist[:20]
            ) or "  <i>Нет игроков</i>"
            send_msg(chat_id,
                f"📊 <b>Онлайн</b> [{bot_id}]\n{SEP}\n\n"
                f"🖥 <b>{info['name']}</b>\n"
                f"🗺 Карта: <b>{info['map']}</b>\n"
                f"🎮 Режим: <b>{info['game_type']}</b>\n"
                f"👥 Игроков: <b>{info['players']} / {info['max']}</b>\n\n"
                f"<b>Игроки:</b>\n{players}",
                reply_markup=kb_back(bot_id))
        asyncio.run_coroutine_threadsafe(do_online(), loop)

    elif data.startswith("b:") and ":say" in data:
        bot_id = data.split(":")[1]
        set_state(chat_id, "say", bot_id=bot_id)
        edit_msg(chat_id, msg_id,
            f"✉️ <b>Написать в чат</b> [{bot_id}]\n{SEP}\n\nВведи сообщение:",
            kb_cancel())

    elif data.startswith("b:") and ":rename:" in data:
        parts = data.split(":")
        bot_id = parts[1]; field = parts[3]
        icons = {"name": "👤", "clan": "🏷", "skin": "🎨"}
        if field == "skin":
            set_state(chat_id, "skin_pick", bot_id=bot_id, field=field)
            edit_msg(chat_id, msg_id,
                f"🎨 <b>Выбери скин</b> [{bot_id}]:", kb_skins())
        else:
            set_state(chat_id, "rename", bot_id=bot_id, field=field)
            labels = {"name": "имя (макс. 15)", "clan": "клан (макс. 11, или - убрать)"}
            edit_msg(chat_id, msg_id,
                f"{icons[field]} <b>Введи новое {labels[field]}</b> [{bot_id}]:",
                kb_cancel())

    elif data.startswith("b:") and ":stop" in data:
        bot_id = data.split(":")[1]
        async def do_stop():
            ok = await mgr.stop(chat_id, bot_id)
            edit_msg(chat_id, msg_id,
                f"🔴 Бот <b>[{bot_id}]</b> {'остановлен' if ok else 'не найден'}.",
                {"inline_keyboard": [[
                    {"text": "📋 Мои боты", "callback_data": "c:list"},
                    {"text": "🏠 Главная",  "callback_data": "c:home"},
                ]]})
        asyncio.run_coroutine_threadsafe(do_stop(), loop)

    elif data.startswith("skin:"):
        st = get_state(chat_id)
        skin_val = data.split(":", 1)[1]
        step = st.get("step","")
        d = st.get("data", {})

        if skin_val == "__manual__":
            if step == "skin_pick":
                set_state(chat_id, "rename", bot_id=d["bot_id"], field="skin")
            else:
                set_state(chat_id, "skin_manual", **d)
            edit_msg(chat_id, msg_id, "✍️ Введи название скина:", kb_cancel())
            return

        if step == "skin":
            new_d = dict(d); new_d["skin"] = skin_val
            set_state(chat_id, "pw", **new_d)
            edit_msg(chat_id, msg_id,
                f"✅ Скин: <b>{skin_val}</b>\n\n➕ <b>Шаг 6/6</b>\n{SEP}\n\n"
                "🔐 Пароль сервера (нет → <code>-</code>):",
                kb_cancel())
        elif step == "skin_pick":
            bot_id = d["bot_id"]
            clear_state(chat_id)
            async def do_skin():
                await mgr.update_profile(chat_id, bot_id, skin=skin_val)
                edit_msg(chat_id, msg_id,
                    f"✅ Скин <b>[{bot_id}]</b> → <b>{skin_val}</b>",
                    kb_back(bot_id))
            asyncio.run_coroutine_threadsafe(do_skin(), loop)

    elif data.startswith("relay:"):
        bot_id = data.split(":")[1]
        # Текст из reply_to не доступен через callback — просим написать
        set_state(chat_id, "say", bot_id=bot_id)
        edit_msg(chat_id, msg_id,
            f"✉️ Введи сообщение для <b>[{bot_id}]</b>:", kb_cancel())

# ══════════════════════════════════════════════════════════
#  Polling loop
# ══════════════════════════════════════════════════════════
def polling():
    offset = None
    logger.info("🚀 DDNet Bridge Bot запущен (pure Python)")
    while True:
        params = {"timeout": 30, "allowed_updates": ["message","callback_query"]}
        if offset:
            params["offset"] = offset
        try:
            res = tg_get("getUpdates", params)
            if not res or not res.get("ok"):
                time.sleep(3); continue
            for upd in res.get("result", []):
                offset = upd["update_id"] + 1
                try:
                    process_update(upd)
                except Exception as e:
                    logger.error(f"Update error: {e}")
        except Exception as e:
            logger.error(f"Polling: {e}")
            time.sleep(5)

def process_update(upd):
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text","")
        if text.startswith("/start"):
            clear_state(chat_id); handle_start(chat_id)
        elif text.startswith("/bots"):
            clear_state(chat_id); handle_bots(chat_id)
        elif text.startswith("/new"):
            handle_new(chat_id)
        elif text.startswith("/cancel"):
            clear_state(chat_id)
            send_msg(chat_id, "❌ Отменено.", reply_markup=kb_home())
        elif text:
            handle_text(chat_id, text)

    elif "callback_query" in upd:
        cb = upd["callback_query"]
        cb_id  = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id  = cb["message"]["message_id"]
        data    = cb.get("data","")
        handle_callback(cb_id, chat_id, msg_id, data)

# ══════════════════════════════════════════════════════════
#  Запуск
# ══════════════════════════════════════════════════════════
loop = None
mgr  = None

class TGAdapter:
    async def send_message(self, chat_id, text, parse_mode=None):
        send_msg(chat_id, text)

def main():
    global loop, mgr
    loop = asyncio.new_event_loop()
    mgr = SessionManager(TGAdapter())

    # Запускаем asyncio loop в отдельном потоке
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()

    # Polling в главном потоке
    polling()

if __name__ == "__main__":
    main()

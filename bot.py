# bot.py — DDNet Bridge Bot (pure Python, zero deps, fixed UI)

import asyncio, json, urllib.request, urllib.parse
import logging, time, threading

from config import BOT_TOKEN, SKINS
from sessions import SessionManager

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ══════════════════════════════════════════════════════════
#  HTTP
# ══════════════════════════════════════════════════════════
def tg_get(method, params=None):
    url = f"{API}/{method}"
    if params: url += "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error(f"GET {method}: {e}"); return None

def tg_post(method, data):
    url = f"{API}/{method}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(url, body, {"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        logger.error(f"POST {method}: {e}"); return None

def send_msg(chat_id, text, markup=None):
    d = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if markup: d["reply_markup"] = json.dumps(markup)
    return tg_post("sendMessage", d)

def edit_msg(chat_id, msg_id, text, markup=None):
    d = {"chat_id": chat_id, "message_id": msg_id,
         "text": text, "parse_mode": "HTML"}
    if markup: d["reply_markup"] = json.dumps(markup)
    return tg_post("editMessageText", d)

def answer_cb(cb_id, text="", alert=False):
    tg_post("answerCallbackQuery",
            {"callback_query_id": cb_id, "text": text, "show_alert": alert})

# ══════════════════════════════════════════════════════════
#  UI
# ══════════════════════════════════════════════════════════
BANNER = (
    "🎮 <b>DDNet Bridge Bot</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "Мост между Telegram и DDNet чатом"
)
SEP = "━━━━━━━━━━━━━━━━━━━━━━━━"

def bot_card(s):
    icon = "🟢" if s.active else "🔴"
    return (
        f"{icon} <b>{s.bot_id}</b>\n"
        f"  📡 <code>{s.ip}:{s.port}</code>\n"
        f"  👤 {s.name}  🏷 {s.clan or '—'}  🎨 {s.skin}\n"
        f"  💬 {s.msg_count} сообщений"
    )

def kb(rows): return {"inline_keyboard": rows}
def btn(text, data): return {"text": text, "callback_data": data}

def kb_main():
    return kb([
        [btn("➕ Подключить бота", "c:new")],
        [btn("📋 Список ботов", "c:list"), btn("❓ Помощь", "c:help")],
    ])

def kb_bot(bid):
    return kb([
        [btn("✉️ Написать в чат", f"b:{bid}:say"),
         btn("👥 Онлайн", f"b:{bid}:online")],
        [btn("✏️ Имя", f"b:{bid}:rename:name"),
         btn("🏷 Клан", f"b:{bid}:rename:clan"),
         btn("🎨 Скин", f"b:{bid}:rename:skin")],
        [btn("🔴 Отключить", f"b:{bid}:stop"),
         btn("« Назад", "c:list")],
    ])

def kb_botlist(chat_id):
    rows = []
    for s in mgr.list_bots(chat_id):
        icon = "🟢" if s.active else "🔴"
        rows.append([btn(f"{icon} {s.bot_id} — {s.name} ({s.ip}:{s.port})",
                        f"b:{s.bot_id}:info")])
    rows.append([btn("➕ Новый бот","c:new"), btn("🏠 Главная","c:home")])
    return kb(rows)

def kb_skins():
    rows = []; row = []
    for skin in SKINS:
        row.append(btn(skin, f"skin:{skin}"))
        if len(row)==3: rows.append(row); row=[]
    if row: rows.append(row)
    rows.append([btn("✍️ Ввести вручную","skin:__manual__")])
    return kb(rows)

def kb_cancel():
    return kb([[btn("❌ Отмена","c:cancel")]])

def kb_back(bid):
    return kb([[btn(f"« {bid}",f"b:{bid}:info"), btn("🏠 Главная","c:home")]])

def kb_home():
    return kb([[btn("🏠 Главная","c:home")]])

def kb_retry(bid=None):
    return kb([[btn("🔄 Попробовать снова","c:new"),
                btn("🏠 Главная","c:home")]])

# ══════════════════════════════════════════════════════════
#  Состояния (FSM)
# ══════════════════════════════════════════════════════════
# states[chat_id] = {"step": str, **data}
states = {}

def st_get(cid): return states.get(cid, {})
def st_set(cid, step, **kw): states[cid] = {"step": step, **kw}
def st_clear(cid): states.pop(cid, None)
def st_step(cid): return states.get(cid, {}).get("step")

# ══════════════════════════════════════════════════════════
#  Handlers
# ══════════════════════════════════════════════════════════
def do_start(chat_id):
    cnt = len(mgr.list_bots(chat_id))
    st = f"🟢 Активных ботов: <b>{cnt}</b>" if cnt else "⚫ Нет активных ботов"
    send_msg(chat_id,
        f"{BANNER}\n\n{st}\n\n"
        "Бот пересылает сообщения между Telegram и игровым чатом.\n"
        "Поддерживает несколько серверов одновременно.",
        kb_main())

def do_bots(chat_id):
    bots = mgr.list_bots(chat_id)
    if not bots:
        send_msg(chat_id, "Нет активных ботов.\n/new — подключить сервер"); return
    lines = "\n\n".join(bot_card(s) for s in bots)
    send_msg(chat_id, f"🤖 <b>Твои боты</b>\n{SEP}\n\n{lines}", kb_botlist(chat_id))

def do_new(chat_id):
    st_set(chat_id, "ip")
    send_msg(chat_id,
        f"➕ <b>Подключение — Шаг 1/6</b>\n{SEP}\n\n"
        "📡 Введи <b>IP-адрес</b> сервера:\n"
        "<i>Пример: <code>46.174.48.103</code></i>",
        kb_cancel())

# ── Обработка текстового ввода ─────────────────────────────────────────────
def handle_text(chat_id, text):
    s = st_get(chat_id)
    step = s.get("step","")
    text = text.strip()

    if step == "ip":
        if not text or " " in text or len(text)>253:
            send_msg(chat_id, "❌ Некорректный IP, попробуй снова:", kb_cancel()); return
        st_set(chat_id, "port", ip=text)
        send_msg(chat_id,
            f"✅ IP: <code>{text}</code>\n\n"
            f"➕ <b>Шаг 2/6</b>\n{SEP}\n\n"
            "🔌 Введи <b>порт</b> сервера:\n"
            "<i>Пример: <code>8303</code> или <code>51012</code></i>",
            kb_cancel())

    elif step == "port":
        try:
            port = int(text); assert 1 <= port <= 65535
        except:
            send_msg(chat_id, "❌ Порт — число от 1 до 65535:", kb_cancel()); return
        st_set(chat_id, "name", ip=s["ip"], port=port)
        send_msg(chat_id,
            f"✅ Порт: <code>{port}</code>\n\n"
            f"➕ <b>Шаг 3/6</b>\n{SEP}\n\n"
            "👤 Введи <b>имя</b> бота в игре:\n<i>Макс. 15 символов</i>",
            kb_cancel())

    elif step == "name":
        name = text[:15] or "TGBot"
        st_set(chat_id, "clan", ip=s["ip"], port=s["port"], name=name)
        send_msg(chat_id,
            f"✅ Имя: <b>{name}</b>\n\n"
            f"➕ <b>Шаг 4/6</b>\n{SEP}\n\n"
            "🏷 Введи <b>клан</b> (макс. 11 символов):\n"
            "Без клана → напиши <code>-</code>",
            kb_cancel())

    elif step == "clan":
        clan = "" if text == "-" else text[:11]
        st_set(chat_id, "skin", ip=s["ip"], port=s["port"],
               name=s["name"], clan=clan)
        send_msg(chat_id,
            f"✅ Клан: <b>{clan or '—'}</b>\n\n"
            f"➕ <b>Шаг 5/6</b>\n{SEP}\n\n"
            "🎨 Выбери <b>скин</b> бота:",
            kb_skins())

    elif step == "skin_manual":
        skin = text or "default"
        st_set(chat_id, "pw", ip=s["ip"], port=s["port"],
               name=s["name"], clan=s["clan"], skin=skin)
        send_msg(chat_id,
            f"✅ Скин: <b>{skin}</b>\n\n"
            f"➕ <b>Шаг 6/6</b>\n{SEP}\n\n"
            "🔐 Пароль сервера:\nБез пароля → <code>-</code>",
            kb_cancel())

    elif step == "pw":
        pw = "" if text == "-" else text
        ip=s["ip"]; port=s["port"]; name=s["name"]
        clan=s.get("clan",""); skin=s.get("skin","default")
        st_clear(chat_id)
        m = send_msg(chat_id,
            f"⏳ Подключаю <b>{name}</b> к <code>{ip}:{port}</code>...\n"
            "Может занять до 10 секунд.")
        mid = m["result"]["message_id"] if m else None

        async def do_connect():
            ok, bid = await mgr.start(chat_id, ip, port, name, clan, skin, pw)
            if ok:
                edit_msg(chat_id, mid,
                    f"✅ <b>Бот подключён!</b>\n{SEP}\n\n"
                    f"🤖 ID: <b>{bid}</b>\n"
                    f"📡 Сервер: <code>{ip}:{port}</code>\n"
                    f"👤 Имя: <b>{name}</b>\n"
                    f"🏷 Клан: <b>{clan or '—'}</b>\n"
                    f"🎨 Скин: <b>{skin}</b>\n\n"
                    "💬 Все сообщения из игры будут приходить сюда.\n"
                    "Просто пиши — текст уйдёт в игровой чат.",
                    kb_bot(bid))
            else:
                edit_msg(chat_id, mid,
                    f"❌ <b>Не удалось подключиться</b>\n\n"
                    f"Сервер <code>{ip}:{port}</code> недоступен.\n"
                    "Проверь IP и порт.",
                    kb_retry())
        asyncio.run_coroutine_threadsafe(do_connect(), loop)

    elif step == "say":
        bid = s["bot_id"]; st_clear(chat_id)
        async def do_say():
            ok = await mgr.send(chat_id, bid, text)
            if ok:
                send_msg(chat_id,
                    f"✅ Отправлено в <b>[{bid}]</b>:\n<i>{text}</i>",
                    kb_back(bid))
            else:
                send_msg(chat_id, "❌ Ошибка — бот отключён?", kb_back(bid))
        asyncio.run_coroutine_threadsafe(do_say(), loop)

    elif step == "rename":
        bid=s["bot_id"]; field=s["field"]; st_clear(chat_id)
        kw = {}
        if field=="name": kw["name"]=text[:15]
        elif field=="clan": kw["clan"]="" if text=="-" else text[:11]
        elif field=="skin": kw["skin"]=text
        icons={"name":"👤","clan":"🏷","skin":"🎨"}
        async def do_rename():
            await mgr.update_profile(chat_id, bid, **kw)
            val = list(kw.values())[0] or "—"
            send_msg(chat_id,
                f"✅ {icons[field]} <b>[{bid}]</b> обновлён: <b>{val}</b>",
                kb_back(bid))
        asyncio.run_coroutine_threadsafe(do_rename(), loop)

    else:
        # Relay в игру
        bots = mgr.list_bots(chat_id)
        if not bots:
            send_msg(chat_id,
                "❌ Нет активных ботов.\n/new — подключить сервер"); return
        if len(bots) == 1:
            async def do_relay():
                ok = await mgr.send(chat_id, bots[0].bot_id, text)
                if ok: send_msg(chat_id, "✅ Отправлено в игру")
                else: send_msg(chat_id, "❌ Ошибка отправки")
            asyncio.run_coroutine_threadsafe(do_relay(), loop)
        else:
            rows = [[btn(f"🤖 {s.bot_id} — {s.name}",f"relay:{s.bot_id}")]
                    for s in bots]
            send_msg(chat_id, "Через какого бота отправить?", kb(rows))

# ── Callback handler ──────────────────────────────────────────────────────
def handle_cb(cb_id, chat_id, msg_id, data):
    answer_cb(cb_id)

    # ── Навигация ──────────────────────────────────────────────────────────
    if data == "c:home":
        st_clear(chat_id)
        cnt = len(mgr.list_bots(chat_id))
        st = f"🟢 Активных ботов: <b>{cnt}</b>" if cnt else "⚫ Нет активных ботов"
        edit_msg(chat_id, msg_id,
            f"{BANNER}\n\n{st}\n\nВыбери действие:", kb_main())

    elif data == "c:list":
        st_clear(chat_id)
        bots = mgr.list_bots(chat_id)
        if not bots:
            answer_cb(cb_id, "Нет активных ботов", True); return
        lines = "\n\n".join(bot_card(s) for s in bots)
        edit_msg(chat_id, msg_id,
            f"🤖 <b>Список ботов</b>\n{SEP}\n\n{lines}",
            kb_botlist(chat_id))

    elif data == "c:help":
        edit_msg(chat_id, msg_id,
            f"❓ <b>Помощь</b>\n{SEP}\n\n"
            "<b>Возможности:</b>\n"
            "• Несколько DDNet-ботов одновременно\n"
            "• Все сообщения из игры → Telegram\n"
            "• Telegram → игровой чат DDNet\n"
            "• Смена имени, клана, скина на лету\n"
            "• Онлайн и список игроков сервера\n\n"
            "<b>Команды:</b>\n"
            "/start — главное меню\n"
            "/new — подключить сервер\n"
            "/bots — список ботов\n"
            "/cancel — отмена\n\n"
            "<b>Иконки в чате:</b>\n"
            "📢 — общий чат\n"
            "👥 — командный чат\n"
            "🟢 — игрок зашёл\n"
            "🔴 — игрок вышел",
            kb_home())

    elif data == "c:new":
        st_clear(chat_id)
        st_set(chat_id, "ip")
        edit_msg(chat_id, msg_id,
            f"➕ <b>Подключение — Шаг 1/6</b>\n{SEP}\n\n"
            "📡 Введи <b>IP-адрес</b> сервера:\n"
            "<i>Пример: <code>46.174.48.103</code></i>",
            kb_cancel())

    elif data == "c:cancel":
        st_clear(chat_id)
        edit_msg(chat_id, msg_id, "❌ Отменено.", kb_home())

    # ── Инфо о боте ────────────────────────────────────────────────────────
    elif data.startswith("b:") and data.endswith(":info"):
        bid = data.split(":")[1]
        s = mgr.get_bot(chat_id, bid)
        if not s: answer_cb(cb_id,"Бот не найден",True); return
        edit_msg(chat_id, msg_id,
            f"🤖 <b>Бот {bid}</b>\n{SEP}\n\n"
            f"📡 Сервер: <code>{s.ip}:{s.port}</code>\n"
            f"👤 Имя: <b>{s.name}</b>\n"
            f"🏷 Клан: <b>{s.clan or '—'}</b>\n"
            f"🎨 Скин: <b>{s.skin}</b>\n"
            f"💬 Сообщений получено: <b>{s.msg_count}</b>\n"
            f"🔗 Статус: {'🟢 Активен' if s.active else '🔴 Отключён'}",
            kb_bot(bid))

    # ── Онлайн ─────────────────────────────────────────────────────────────
    elif data.startswith("b:") and ":online" in data:
        bid = data.split(":")[1]
        async def do_online():
            info = await mgr.fetch_online(chat_id, bid)
            if "error" in info:
                send_msg(chat_id, f"❌ {info['error']}"); return
            clist = info.get("client_list",[])
            pl = "\n".join(
                f"  {'🏷'+c['clan']+' ' if c['clan'] else ''}👤 {c['name']} <i>({c['score']})</i>"
                for c in clist[:20]
            ) or "  <i>Нет игроков</i>"
            send_msg(chat_id,
                f"📊 <b>Онлайн сервера</b> [{bid}]\n{SEP}\n\n"
                f"🖥 <b>{info['name']}</b>\n"
                f"🗺 Карта: <b>{info['map']}</b>\n"
                f"🎮 Режим: <b>{info['game_type']}</b>\n"
                f"👥 Игроков: <b>{info['players']}/{info['max']}</b>\n\n"
                f"<b>Игроки:</b>\n{pl}",
                kb_back(bid))
        asyncio.run_coroutine_threadsafe(do_online(), loop)

    # ── Написать в чат ──────────────────────────────────────────────────────
    elif data.startswith("b:") and ":say" in data:
        bid = data.split(":")[1]
        st_set(chat_id, "say", bot_id=bid)
        edit_msg(chat_id, msg_id,
            f"✉️ <b>Написать в чат [{bid}]</b>\n{SEP}\n\n"
            "Введи сообщение которое отправится в игровой чат:",
            kb_cancel())

    # ── Переименование ──────────────────────────────────────────────────────
    elif data.startswith("b:") and ":rename:" in data:
        parts = data.split(":")
        bid=parts[1]; field=parts[3]
        icons={"name":"👤","clan":"🏷","skin":"🎨"}
        if field == "skin":
            st_set(chat_id,"skin_pick",bot_id=bid,field=field)
            edit_msg(chat_id,msg_id,
                f"🎨 <b>Выбери новый скин</b> [{bid}]:", kb_skins())
        else:
            st_set(chat_id,"rename",bot_id=bid,field=field)
            labels={"name":"имя (макс. 15 символов)",
                    "clan":"клан (макс. 11, или - чтобы убрать)"}
            edit_msg(chat_id,msg_id,
                f"{icons[field]} <b>Введи новое {labels[field]}</b> [{bid}]:",
                kb_cancel())

    # ── Стоп ────────────────────────────────────────────────────────────────
    elif data.startswith("b:") and ":stop" in data:
        bid = data.split(":")[1]
        async def do_stop():
            ok = await mgr.stop(chat_id, bid)
            edit_msg(chat_id, msg_id,
                f"🔴 Бот <b>[{bid}]</b> {'остановлен' if ok else 'не найден'}.",
                kb([[btn("📋 Список","c:list"),btn("🏠 Главная","c:home")]]))
        asyncio.run_coroutine_threadsafe(do_stop(), loop)

    # ── Выбор скина ─────────────────────────────────────────────────────────
    elif data.startswith("skin:"):
        s = st_get(chat_id)
        skin_val = data.split(":",1)[1]
        step = s.get("step","")

        if skin_val == "__manual__":
            if step == "skin_pick":
                st_set(chat_id,"rename",bot_id=s["bot_id"],field="skin")
            else:
                st_set(chat_id,"skin_manual",**{k:v for k,v in s.items() if k!="step"})
            edit_msg(chat_id,msg_id,"✍️ Введи название скина вручную:",kb_cancel())
            return

        if step == "skin":
            new_s = {k:v for k,v in s.items() if k!="step"}
            new_s["skin"] = skin_val
            st_set(chat_id,"pw",**new_s)
            edit_msg(chat_id,msg_id,
                f"✅ Скин: <b>{skin_val}</b>\n\n"
                f"➕ <b>Шаг 6/6</b>\n{SEP}\n\n"
                "🔐 Пароль сервера:\nБез пароля → <code>-</code>",
                kb_cancel())

        elif step == "skin_pick":
            bid = s["bot_id"]; st_clear(chat_id)
            async def do_skin():
                await mgr.update_profile(chat_id, bid, skin=skin_val)
                edit_msg(chat_id,msg_id,
                    f"✅ Скин <b>[{bid}]</b> → <b>{skin_val}</b>",
                    kb_back(bid))
            asyncio.run_coroutine_threadsafe(do_skin(), loop)

    # ── Relay через конкретного бота ─────────────────────────────────────────
    elif data.startswith("relay:"):
        bid = data.split(":")[1]
        st_set(chat_id,"say",bot_id=bid)
        edit_msg(chat_id,msg_id,
            f"✉️ Введи сообщение для <b>[{bid}]</b>:", kb_cancel())

# ══════════════════════════════════════════════════════════
#  Polling
# ══════════════════════════════════════════════════════════
def process_update(upd):
    if "message" in upd:
        msg = upd["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text","")
        if not text: return
        if text.startswith("/start"):
            st_clear(chat_id); do_start(chat_id)
        elif text.startswith("/bots"):
            st_clear(chat_id); do_bots(chat_id)
        elif text.startswith("/new"):
            do_new(chat_id)
        elif text.startswith("/cancel"):
            st_clear(chat_id)
            send_msg(chat_id,"❌ Отменено.",kb_home())
        else:
            handle_text(chat_id, text)

    elif "callback_query" in upd:
        cb = upd["callback_query"]
        handle_cb(cb["id"],
                  cb["message"]["chat"]["id"],
                  cb["message"]["message_id"],
                  cb.get("data",""))

def polling():
    offset = None
    logger.info("🚀 DDNet Bridge Bot запущен")
    while True:
        params = {"timeout":30,
                  "allowed_updates":["message","callback_query"]}
        if offset: params["offset"] = offset
        try:
            res = tg_get("getUpdates", params)
            if not res or not res.get("ok"):
                time.sleep(3); continue
            for upd in res.get("result",[]):
                offset = upd["update_id"] + 1
                try: process_update(upd)
                except Exception as e: logger.error(f"Update: {e}")
        except Exception as e:
            logger.error(f"Polling: {e}"); time.sleep(5)

# ══════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════
loop = None
mgr  = None

class TGAdapter:
    async def send_message(self, chat_id, text, parse_mode=None):
        send_msg(chat_id, text)

def main():
    global loop, mgr
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    mgr = SessionManager(TGAdapter())
    threading.Thread(target=loop.run_forever, daemon=True).start()
    polling()

if __name__ == "__main__":
    main()

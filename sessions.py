# sessions.py — несколько ботов на один TG-чат

import asyncio
import logging
from dataclasses import dataclass, field
from ddnet import DDNetClient

logger = logging.getLogger(__name__)


@dataclass
class BotSession:
    bot_id: str          # уникальный ID внутри чата, напр. "bot1"
    tg_chat_id: int
    ip: str
    port: int
    name: str
    clan: str
    skin: str
    password: str
    client: DDNetClient = field(default=None, repr=False)
    active: bool = False
    msg_count: int = 0   # сколько сообщений переслано из игры


class SessionManager:
    def __init__(self, tg_bot):
        self.bot = tg_bot
        # { tg_chat_id: { bot_id: BotSession } }
        self._sessions: dict[int, dict[str, BotSession]] = {}

    def _chat(self, chat_id: int) -> dict[str, BotSession]:
        if chat_id not in self._sessions:
            self._sessions[chat_id] = {}
        return self._sessions[chat_id]

    def list_bots(self, chat_id: int) -> list[BotSession]:
        return list(self._chat(chat_id).values())

    def get_bot(self, chat_id: int, bot_id: str) -> BotSession | None:
        return self._chat(chat_id).get(bot_id)

    def _next_id(self, chat_id: int) -> str:
        existing = self._chat(chat_id)
        i = 1
        while f"bot{i}" in existing:
            i += 1
        return f"bot{i}"

    # ── Запуск нового бота ─────────────────────────────────────────────────
    async def start(self, chat_id: int, ip: str, port: int,
                    name: str = "TGBot", clan: str = "",
                    skin: str = "default", password: str = "") -> tuple[bool, str]:
        bot_id = self._next_id(chat_id)
        client = DDNetClient(ip=ip, port=port, name=name,
                              clan=clan, skin=skin, password=password)

        async def on_chat(player: str, message: str, team: int, cid: int):
            sess = self._chat(chat_id).get(bot_id)
            if not sess:
                return
            sess.msg_count += 1
            icon = "📢" if team == 0 else "👥"
            try:
                await self.bot.send_message(
                    chat_id,
                    f"{icon} <b>[{bot_id}]</b> <code>{player}</code>: {message}",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"TG send: {e}")

        async def on_join(player: str):
            try:
                await self.bot.send_message(
                    chat_id,
                    f"🟢 <b>[{bot_id}]</b> <i>{player}</i> зашёл на сервер",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        async def on_leave(player: str, reason: str):
            try:
                r = f" ({reason})" if reason else ""
                await self.bot.send_message(
                    chat_id,
                    f"🔴 <b>[{bot_id}]</b> <i>{player}</i> вышел{r}",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        client.on_chat  = on_chat
        client.on_join  = on_join
        client.on_leave = on_leave

        ok = await client.connect()
        if not ok:
            return False, bot_id

        sess = BotSession(
            bot_id=bot_id, tg_chat_id=chat_id,
            ip=ip, port=port,
            name=name, clan=clan, skin=skin, password=password,
            client=client, active=True,
        )
        self._chat(chat_id)[bot_id] = sess
        return True, bot_id

    # ── Остановка бота ─────────────────────────────────────────────────────
    async def stop(self, chat_id: int, bot_id: str) -> bool:
        sess = self._chat(chat_id).pop(bot_id, None)
        if sess and sess.client:
            await sess.client.disconnect()
            return True
        return False

    async def stop_all_in_chat(self, chat_id: int):
        for bid in list(self._chat(chat_id).keys()):
            await self.stop(chat_id, bid)

    # ── Отправить сообщение ────────────────────────────────────────────────
    async def send(self, chat_id: int, bot_id: str, text: str) -> bool:
        sess = self.get_bot(chat_id, bot_id)
        if not sess or not sess.active:
            return False
        await sess.client.send_chat(text)
        return True

    # ── Онлайн сервера ─────────────────────────────────────────────────────
    async def fetch_online(self, chat_id: int, bot_id: str) -> dict:
        sess = self.get_bot(chat_id, bot_id)
        if not sess:
            return {"error": "Бот не найден"}
        return await DDNetClient.fetch_online(sess.ip, sess.port)

    # ── Обновить профиль бота ──────────────────────────────────────────────
    async def update_profile(self, chat_id: int, bot_id: str,
                              name: str = None, clan: str = None,
                              skin: str = None) -> bool:
        sess = self.get_bot(chat_id, bot_id)
        if not sess:
            return False
        if name: sess.name = name; sess.client.name = name
        if clan is not None: sess.clan = clan; sess.client.clan = clan
        if skin: sess.skin = skin; sess.client.skin = skin
        # Переотправить STARTINFO
        await sess.client._send_startinfo()
        return True

    async def stop_all(self):
        for cid in list(self._sessions.keys()):
            await self.stop_all_in_chat(cid)


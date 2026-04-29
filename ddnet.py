# ddnet.py — Teeworlds 0.7 UDP клиент

import asyncio
import socket
import struct
import time
import logging
import os

logger = logging.getLogger(__name__)

# ── Упаковка int (Teeworlds variable-length) ───────────────────────────────
def pack_int(v: int) -> bytes:
    v = int(v)
    sign = 0
    if v < 0:
        sign = 1
        v = -v - 1
    result = []
    first = True
    while first or v:
        b = v & (0x3F if first else 0x7F)
        v >>= (6 if first else 7)
        if first:
            b |= (sign << 6)
            first = False
        if v:
            b |= 0x80
        result.append(b)
        if not v:
            break
    if not result:
        result = [0]
    return bytes(result)

def pack_str(s: str) -> bytes:
    return s.encode("utf-8")[:15] + b"\x00"

def pack_str_long(s: str) -> bytes:
    return s.encode("utf-8")[:127] + b"\x00"

# ── Заголовок пакета ───────────────────────────────────────────────────────
def make_header(flags: int, ack: int, num_chunks: int, token: bytes) -> bytes:
    b0 = ((flags & 0xF) << 4) | ((ack >> 8) & 0xF)
    b1 = ack & 0xFF
    return bytes([b0, b1, num_chunks]) + token[:4]

def make_ctrl(ctrl_type: int, token_dst: bytes, extra: bytes = b"") -> bytes:
    hdr = make_header(4, 0, 0, token_dst)
    return hdr + bytes([ctrl_type]) + extra

# ── Клиент ─────────────────────────────────────────────────────────────────
class DDNetClient:
    MASTER_URL = "https://master1.ddnet.org/ddnet/15/servers.json"

    def __init__(self, ip, port, name="TGBot", clan="", skin="default", password=""):
        self.ip = ip
        self.port = port
        self.name = name[:15]
        self.clan = clan[:11]
        self.skin = skin
        self.password = password

        self._sock = None
        self._loop = None
        self._token_cli = os.urandom(4)
        self._token_srv = b"\xff\xff\xff\xff"
        self._connected = False
        self._ack = 0
        self._seq = 0

        # Callbacks
        self.on_chat  = None  # async (player, message, team)
        self.on_join  = None  # async (player)
        self.on_leave = None  # async (player)

    # ── Онлайн через HTTP ──────────────────────────────────────────────────
    @staticmethod
    async def fetch_online(ip: str, port: int) -> dict:
        import aiohttp
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(DDNetClient.MASTER_URL,
                                 timeout=aiohttp.ClientTimeout(total=8)) as r:
                    data = await r.json(content_type=None)
            for srv in data.get("servers", []):
                for addr in srv.get("addresses", []):
                    if f"{ip}:{port}" in addr:
                        info = srv.get("info", {})
                        clients = info.get("clients", [])
                        players = [c for c in clients if not c.get("is_player") is False]
                        return {
                            "name":    info.get("name", "?"),
                            "map":     info.get("map", {}).get("name", "?"),
                            "players": len(players),
                            "max":     info.get("max_clients", 64),
                            "version": info.get("version", "?"),
                            "game_type": info.get("game_type", "?"),
                            "client_list": [
                                {"name": c.get("name","?"), "clan": c.get("clan",""),
                                 "score": c.get("score", 0)}
                                for c in clients
                            ]
                        }
            return {"error": "Сервер не найден в мастер-листе"}
        except Exception as e:
            return {"error": str(e)}

    # ── Подключение ────────────────────────────────────────────────────────
    async def connect(self) -> bool:
        self._loop = asyncio.get_event_loop()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        try:
            self._sock.connect((self.ip, self.port))
        except Exception as e:
            logger.error(f"Socket error: {e}")
            return False

        # Отправляем CTRL CONNECT (type=1)
        pkt = make_ctrl(0x01, self._token_srv, self._token_cli + b"\x00" * 508)
        await self._raw_send(pkt)

        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._recv_once), timeout=1.0)
                if data and len(data) >= 8:
                    flags = (data[0] >> 4) & 0xF
                    if flags == 4:  # control
                        ctrl = data[7] if len(data) > 7 else 0
                        if ctrl == 0x02:  # ACCEPT
                            if len(data) >= 12:
                                self._token_srv = data[8:12]
                            self._connected = True
                            asyncio.create_task(self._recv_loop())
                            asyncio.create_task(self._keepalive_loop())
                            await asyncio.sleep(0.1)
                            await self._do_handshake()
                            return True
            except asyncio.TimeoutError:
                pass
        return False

    def _recv_once(self):
        try:
            return self._sock.recv(1400)
        except Exception:
            return None

    async def _raw_send(self, data: bytes):
        try:
            await self._loop.run_in_executor(None, self._sock.send, data)
        except Exception as e:
            logger.error(f"Send error: {e}")

    # ── Рукопожатие: INFO → READY → ENTERGAME ─────────────────────────────
    async def _do_handshake(self):
        # NET_MSG_INFO (system msg 1)
        await self._send_sys(1,
            pack_str("0.7 802f1be60a05665f") +  # version
            pack_str(self.password)
        )
        await asyncio.sleep(0.3)
        # NET_MSG_READY (system msg 4)
        await self._send_sys(4, b"")
        await asyncio.sleep(0.3)
        # NET_MSG_ENTERGAME (system msg 5) — тут шлём профиль
        await self._send_sys(5, b"")
        await asyncio.sleep(0.3)
        # NET_MSG_STARTINFO — имя, клан, скин и т.д.
        await self._send_startinfo()

    async def _send_startinfo(self):
        # game msg 27 = NETMSGTYPE_CL_STARTINFO
        payload = (
            pack_str(self.name) +
            pack_str(self.clan) +
            pack_int(-1) +           # country
            pack_str(self.skin) +
            pack_int(0) +            # use custom color
            pack_int(0) +            # color body
            pack_int(0)              # color feet
        )
        await self._send_game(27, payload)

    # ── Отправка чат-сообщения ─────────────────────────────────────────────
    async def send_chat(self, text: str):
        if not self._connected:
            return
        # game msg 4 = NETMSGTYPE_CL_SAY, team=0 all
        payload = pack_int(0) + pack_str_long(text)
        await self._send_game(4, payload)
        logger.info(f"[{self.name}] → {text}")

    # ── Упаковка чанков ───────────────────────────────────────────────────
    async def _send_sys(self, msg_id: int, payload: bytes):
        """System message (flag bit 0)."""
        data = pack_int(msg_id * 2 + 1) + payload  # sys flag in id
        await self._send_chunk(data)

    async def _send_game(self, msg_id: int, payload: bytes):
        """Game message."""
        data = pack_int(msg_id * 2) + payload
        await self._send_chunk(data)

    async def _send_chunk(self, data: bytes):
        size = len(data)
        # chunk header: flags(2bit) size(6+4bit) [seq]
        # vital chunk: flags=01
        seq = self._seq & 0x3FF
        self._seq += 1
        ch0 = (1 << 6) | ((size >> 4) & 0x3F)  # vital flag + size high
        ch1 = (size & 0x0F) | ((seq >> 6) & 0xF0)  # wait, standard header:
        # Actually Teeworlds chunk header (vital):
        # byte0: flags(2) | size_high(6)   flags=01 (vital)
        # byte1: size_low(4) | seq_high(4)  -- no, seq is 10bit
        # byte2: seq_low(8)
        ch0 = 0x40 | ((size >> 4) & 0x3F)
        ch1 = ((size & 0xF) << 4) | ((seq >> 6) & 0xF)
        ch2 = seq & 0xFF
        chunk = bytes([ch0, ch1, ch2]) + data
        hdr = make_header(0, self._ack & 0x3FF, 1, self._token_srv)
        await self._raw_send(hdr + chunk)

    # ── Фоновые задачи ─────────────────────────────────────────────────────
    async def _keepalive_loop(self):
        while self._connected:
            await asyncio.sleep(10)
            pkt = make_ctrl(0x00, self._token_srv)  # KEEPALIVE
            await self._raw_send(pkt)

    async def _recv_loop(self):
        while self._connected:
            try:
                data = await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._recv_once), timeout=1.0)
                if data:
                    await self._handle_packet(data)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.debug(f"Recv error: {e}")

    async def _handle_packet(self, data: bytes):
        if len(data) < 7:
            return
        flags = (data[0] >> 4) & 0xF
        ack   = ((data[0] & 0xF) << 8) | data[1]
        num_chunks = data[2]
        # token = data[3:7]

        if flags & 4:  # control
            if len(data) > 7 and data[7] == 0x04:  # DISCONNECT
                logger.info("Сервер отключил нас")
                self._connected = False
            return

        # Разбираем чанки
        pos = 7
        for _ in range(num_chunks):
            if pos + 2 > len(data):
                break
            b0 = data[pos]; b1 = data[pos+1]
            chunk_flags = (b0 >> 6) & 0x3
            size = ((b0 & 0x3F) << 4) | (b1 >> 4)
            vital = (chunk_flags & 1) != 0
            if vital:
                if pos + 3 > len(data):
                    break
                seq = ((b1 & 0xF) << 8) | data[pos+2]
                self._ack = seq
                pos += 3
            else:
                pos += 2

            if pos + size > len(data):
                break
            chunk_data = data[pos:pos+size]
            pos += size

            await self._handle_chunk(chunk_data)

    async def _handle_chunk(self, data: bytes):
        if len(data) < 1:
            return
        try:
            msg_raw, pos = unpack_int_tw(data, 0)
            sys_flag = msg_raw & 1
            msg_id   = msg_raw >> 1

            if sys_flag:
                # system msg
                if msg_id == 2:  # SNAP_SINGLE — просто отвечаем ACK
                    pass
            else:
                # game msg
                if msg_id == 3:  # NETMSGTYPE_SV_CHAT
                    team, pos = unpack_int_tw(data, pos)
                    cid,  pos = unpack_int_tw(data, pos)
                    msg_bytes = data[pos:].split(b"\x00")[0]
                    msg_text  = msg_bytes.decode("utf-8", errors="replace")
                    player = f"#{cid}"
                    if self.on_chat:
                        await self.on_chat(player, msg_text, team, cid)

                elif msg_id == 5:  # NETMSGTYPE_SV_CLIENTINFO
                    cid, pos = unpack_int_tw(data, pos)
                    # local, team, name...
                    # skip local(int), team(int)
                    _, pos = unpack_int_tw(data, pos)
                    _, pos = unpack_int_tw(data, pos)
                    name_bytes = data[pos:].split(b"\x00")[0]
                    name = name_bytes.decode("utf-8", errors="replace")
                    if self.on_join and name:
                        await self.on_join(name)

                elif msg_id == 6:  # NETMSGTYPE_SV_CLIENTDROP
                    cid, pos = unpack_int_tw(data, pos)
                    reason_bytes = data[pos:].split(b"\x00")[0]
                    reason = reason_bytes.decode("utf-8", errors="replace")
                    if self.on_leave:
                        await self.on_leave(f"#{cid}", reason)
        except Exception as e:
            logger.debug(f"Chunk parse error: {e}")

    async def disconnect(self):
        self._connected = False
        if self._sock:
            try:
                pkt = make_ctrl(0x04, self._token_srv)  # CLOSE
                self._sock.send(pkt)
            except Exception:
                pass
            self._sock.close()
            self._sock = None


def unpack_int_tw(data: bytes, pos: int):
    if pos >= len(data):
        return 0, pos
    b = data[pos]; pos += 1
    sign = (b >> 6) & 1
    v = b & 0x3F
    shift = 6
    while b & 0x80 and pos < len(data):
        b = data[pos]; pos += 1
        v |= (b & 0x7F) << shift
        shift += 7
    if sign:
        v = -(v + 1)
    return v, pos


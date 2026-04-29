# ddnet.py — Teeworlds 0.6 протокол (для TeeFusion и других 0.6 серверов)

import asyncio
import socket
import os
import json
import urllib.request
import logging
import struct
import time

logger = logging.getLogger(__name__)

# ── Константы протокола 0.6 ────────────────────────────────────────────────
NET_MAX_PACKETSIZE = 1400
NET_PACKETFLAG_CONTROL = 1
NET_PACKETFLAG_RESEND   = 2
NET_PACKETFLAG_COMPRESSION = 4
NET_PACKETFLAG_CONNLESS = 8

NET_CTRLMSG_KEEPALIVE = 0
NET_CTRLMSG_CONNECT   = 1
NET_CTRLMSG_CONNECTACCEPT = 2
NET_CTRLMSG_ACCEPT    = 3
NET_CTRLMSG_CLOSE     = 4

NET_CHUNKFLAG_VITAL   = 1
NET_CHUNKFLAG_RESEND  = 2

# System messages
NETMSG_INFO       = 1
NETMSG_MAP_CHANGE = 2
NETMSG_MAP_DATA   = 3
NETMSG_SNAP       = 6
NETMSG_SNAPEMPTY  = 7
NETMSG_SNAPSINGLE = 8
NETMSG_INPUTTIMING = 9
NETMSG_RCON_AUTH_STATUS = 10
NETMSG_RCON_LINE  = 11
NETMSG_READY      = 14
NETMSG_ENTERGAME  = 15
NETMSG_INPUT      = 16
NETMSG_RCON_CMD   = 17
NETMSG_RCON_AUTH  = 18
NETMSG_PING       = 20
NETMSG_PING_REPLY = 21

# Game messages
NETMSGTYPE_SV_MOTD       = 1
NETMSGTYPE_SV_BROADCAST  = 2
NETMSGTYPE_SV_CHAT       = 3
NETMSGTYPE_SV_KILLMSG    = 4
NETMSGTYPE_SV_SOUNDGLOBAL = 5
NETMSGTYPE_SV_TUNEPARAMS = 6
NETMSGTYPE_SV_EXTRAPROJECTILE = 7
NETMSGTYPE_SV_READYTOENTER = 8
NETMSGTYPE_SV_WEAPONPICKUP = 9
NETMSGTYPE_SV_EMOTICON   = 10
NETMSGTYPE_SV_VOTECLEAROPTIONS = 11
NETMSGTYPE_SV_VOTEOPTIONADD = 13
NETMSGTYPE_SV_VOTESET    = 15
NETMSGTYPE_SV_CLIENTINFO = 18
NETMSGTYPE_SV_CLIENTDROP = 20
NETMSGTYPE_CL_SAY        = 3
NETMSGTYPE_CL_STARTINFO  = 27

# ── Int packing (Teeworlds variable int) ──────────────────────────────────
def pack_int(v):
    v = int(v)
    sign = 0
    if v < 0:
        sign = 1
        v = -(v+1)
    buf = []
    buf.append(((v & 0x3F) | (sign << 6)))
    v >>= 6
    while v:
        buf[-1] |= 0x80
        buf.append(v & 0x7F)
        v >>= 7
    return bytes(buf)

def unpack_int(data, pos):
    if pos >= len(data): return 0, pos
    b = data[pos]; pos += 1
    sign = (b >> 6) & 1
    v = b & 0x3F
    shift = 6
    while b & 0x80 and pos < len(data):
        b = data[pos]; pos += 1
        v |= (b & 0x7F) << shift
        shift += 7
    if sign: v = -(v+1)
    return v, pos

def pack_str(s, maxlen=15):
    b = s.encode('utf-8')[:maxlen]
    return b + b'\x00'

def pack_str_long(s, maxlen=256):
    b = s.encode('utf-8')[:maxlen]
    return b + b'\x00'

def read_str(data, pos):
    end = data.index(b'\x00', pos)
    return data[pos:end].decode('utf-8', errors='replace'), end+1

# ── Пакет 0.6 ─────────────────────────────────────────────────────────────
def make_packet(flags, ack, num_chunks, payload=b''):
    # Header: 3 bytes
    # byte0: flags(4) | ack_high(4)
    # byte1: ack_low(8)
    # byte2: num_chunks
    b0 = ((flags & 0xF) << 4) | ((ack >> 8) & 0xF)
    b1 = ack & 0xFF
    b2 = num_chunks
    return bytes([b0, b1, b2]) + payload

def make_ctrl_packet(ack, ctrl_type, extra=b''):
    payload = bytes([ctrl_type]) + extra
    return make_packet(NET_PACKETFLAG_CONTROL, ack, 0, payload)

def make_chunk(flags, seq, data):
    size = len(data)
    if flags & NET_CHUNKFLAG_VITAL:
        # 3 byte header: flags(2)|size_hi(6), size_lo(4)|seq_hi(4), seq_lo(8)
        h0 = ((flags & 3) << 6) | ((size >> 4) & 0x3F)
        h1 = ((size & 0xF) << 4) | ((seq >> 8) & 0xF)
        h2 = seq & 0xFF
        return bytes([h0, h1, h2]) + data
    else:
        h0 = ((flags & 3) << 6) | ((size >> 4) & 0x3F)
        h1 = size & 0xF
        return bytes([h0, h1]) + data

def parse_chunk_header(data, pos):
    if pos + 2 > len(data): return None, None, None, pos
    h0 = data[pos]; h1 = data[pos+1]
    flags = (h0 >> 6) & 3
    size  = ((h0 & 0x3F) << 4) | (h1 >> 4)
    vital = bool(flags & NET_CHUNKFLAG_VITAL)
    if vital:
        if pos + 3 > len(data): return None, None, None, pos
        h2 = data[pos+2]
        seq = ((h1 & 0xF) << 8) | h2
        pos += 3
    else:
        seq = 0
        pos += 2
    return flags, size, seq, pos


class DDNetClient:
    MASTER_URL = "https://master1.ddnet.org/ddnet/15/servers.json"

    def __init__(self, ip, port, name="TGBot", clan="", skin="default", password=""):
        self.ip = ip; self.port = port
        self.name = name[:15]; self.clan = clan[:11]
        self.skin = skin; self.password = password

        self._sock = None
        self._loop = None
        self._connected = False
        self._ack = 0      # наш ACK (что мы подтвердили от сервера)
        self._seq = 0      # наш sequence (vital chunks)
        self._peer_ack = 0

        self.on_chat  = None
        self.on_join  = None
        self.on_leave = None

        self._players = {}  # cid -> name

    # ── Онлайн API ────────────────────────────────────────────────────────
    @staticmethod
    async def fetch_online(ip, port):
        def _do():
            try:
                req = urllib.request.urlopen(DDNetClient.MASTER_URL, timeout=8)
                return json.loads(req.read())
            except Exception as e:
                return {"error": str(e)}
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _do)
        if "error" in data: return data
        for srv in data.get("servers", []):
            for addr in srv.get("addresses", []):
                if f"{ip}:{port}" in addr:
                    info = srv.get("info", {})
                    clients = info.get("clients", [])
                    return {
                        "name":    info.get("name", "?"),
                        "map":     info.get("map", {}).get("name", "?"),
                        "players": len(clients),
                        "max":     info.get("max_clients", 64),
                        "version": info.get("version", "?"),
                        "game_type": info.get("game_type", "?"),
                        "client_list": [
                            {"name": c.get("name","?"),
                             "clan": c.get("clan",""),
                             "score": c.get("score",0)}
                            for c in clients
                        ]
                    }
        return {"error": "Сервер не найден в мастер-листе"}

    # ── Подключение ───────────────────────────────────────────────────────
    async def connect(self):
        self._loop = asyncio.get_event_loop()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        try:
            self._sock.connect((self.ip, self.port))
        except Exception as e:
            logger.error(f"Socket: {e}"); return False

        # Отправляем CONNECT
        pkt = make_ctrl_packet(0, NET_CTRLMSG_CONNECT)
        await self._raw_send(pkt)

        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._recv_once), 1.0)
                if data and len(data) >= 4:
                    flags = (data[0] >> 4) & 0xF
                    if flags & NET_PACKETFLAG_CONTROL:
                        ctrl = data[3]
                        if ctrl == NET_CTRLMSG_CONNECTACCEPT:
                            # Отправляем ACCEPT
                            pkt = make_ctrl_packet(0, NET_CTRLMSG_ACCEPT)
                            await self._raw_send(pkt)
                            self._connected = True
                            asyncio.create_task(self._recv_loop())
                            asyncio.create_task(self._keepalive_loop())
                            await asyncio.sleep(0.1)
                            await self._send_info()
                            return True
            except asyncio.TimeoutError:
                pass
        return False

    def _recv_once(self):
        try: return self._sock.recv(NET_MAX_PACKETSIZE)
        except: return None

    async def _raw_send(self, data):
        try: await self._loop.run_in_executor(None, self._sock.send, data)
        except Exception as e: logger.error(f"Send: {e}")

    # ── Отправка system message ────────────────────────────────────────────
    async def _send_sys(self, msg_id, payload=b''):
        data = pack_int(msg_id) + payload
        chunk = make_chunk(NET_CHUNKFLAG_VITAL, self._seq, data)
        self._seq = (self._seq + 1) & 0x3FF
        pkt = make_packet(0, self._ack, 1, chunk)
        await self._raw_send(pkt)

    # ── Отправка game message ──────────────────────────────────────────────
    async def _send_game(self, msg_id, payload=b''):
        # game msgs: id << 1 (LSB=0 = game)
        data = pack_int(msg_id << 1) + payload
        chunk = make_chunk(NET_CHUNKFLAG_VITAL, self._seq, data)
        self._seq = (self._seq + 1) & 0x3FF
        pkt = make_packet(0, self._ack, 1, chunk)
        await self._raw_send(pkt)

    # ── Инфо о клиенте (версия + пароль) ──────────────────────────────────
    async def _send_info(self):
        payload = (
            pack_str("0.6 626fce9a778d4d37", 128) +  # version
            pack_str(self.password, 128)              # password
        )
        await self._send_sys(NETMSG_INFO, payload)

    # ── STARTINFO (имя, клан, страна, скин) ───────────────────────────────
    async def _send_startinfo(self):
        payload = (
            pack_str(self.name) +
            pack_str(self.clan) +
            pack_int(-1) +          # country
            pack_str(self.skin) +
            pack_int(0) +           # use_custom_color
            pack_int(0) +           # color_body
            pack_int(0)             # color_feet
        )
        await self._send_game(NETMSGTYPE_CL_STARTINFO, payload)

    # ── Отправка сообщения в чат ───────────────────────────────────────────
    async def send_chat(self, text):
        if not self._connected: return
        # CL_SAY: team(int) + message(str)
        payload = pack_int(0) + pack_str_long(text)
        await self._send_game(NETMSGTYPE_CL_SAY, payload)
        logger.info(f"[{self.name}] → {text}")

    # ── Keepalive ─────────────────────────────────────────────────────────
    async def _keepalive_loop(self):
        while self._connected:
            await asyncio.sleep(10)
            pkt = make_ctrl_packet(self._ack, NET_CTRLMSG_KEEPALIVE)
            await self._raw_send(pkt)

    # ── Приём пакетов ─────────────────────────────────────────────────────
    async def _recv_loop(self):
        while self._connected:
            try:
                data = await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._recv_once), 1.0)
                if data: await self._handle_packet(data)
            except asyncio.TimeoutError: pass
            except Exception as e: logger.debug(f"Recv: {e}")

    async def _handle_packet(self, data):
        if len(data) < 3: return
        flags = (data[0] >> 4) & 0xF
        ack   = ((data[0] & 0xF) << 8) | data[1]
        num_chunks = data[2]

        if flags & NET_PACKETFLAG_CONTROL:
            if len(data) > 3:
                ctrl = data[3]
                if ctrl == NET_CTRLMSG_CLOSE:
                    self._connected = False
                    logger.info("Сервер закрыл соединение")
                elif ctrl == NET_CTRLMSG_KEEPALIVE:
                    pass
            return

        pos = 3
        for _ in range(num_chunks):
            flags_c, size, seq, pos = parse_chunk_header(data, pos)
            if flags_c is None: break
            if pos + size > len(data): break
            chunk_data = data[pos:pos+size]
            pos += size
            if flags_c & NET_CHUNKFLAG_VITAL:
                self._ack = seq
            await self._handle_chunk(chunk_data)

    async def _handle_chunk(self, data):
        if not data: return
        try:
            msg_raw, p = unpack_int(data, 0)
            sys_flag = msg_raw & 1
            msg_id   = msg_raw >> 1

            if sys_flag:
                # System message
                if msg_id == NETMSG_MAP_CHANGE:
                    # Ответить READY
                    await asyncio.sleep(0.1)
                    await self._send_sys(NETMSG_READY)

                elif msg_id == NETMSGTYPE_SV_READYTOENTER or msg_id == 8:
                    await asyncio.sleep(0.1)
                    await self._send_sys(NETMSG_ENTERGAME)
                    await asyncio.sleep(0.2)
                    await self._send_startinfo()

                elif msg_id == NETMSG_PING:
                    await self._send_sys(NETMSG_PING_REPLY)

            else:
                # Game message
                if msg_id == NETMSGTYPE_SV_CHAT:
                    team, p = unpack_int(data, p)
                    cid,  p = unpack_int(data, p)
                    msg_text, p = read_str(data, p)
                    player = self._players.get(cid, f"#{cid}")
                    if self.on_chat:
                        await self.on_chat(player, msg_text, team, cid)

                elif msg_id == NETMSGTYPE_SV_CLIENTINFO:
                    cid,  p = unpack_int(data, p)
                    local,p = unpack_int(data, p)
                    team, p = unpack_int(data, p)
                    name, p = read_str(data, p)
                    self._players[cid] = name
                    if self.on_join and name:
                        await self.on_join(name)

                elif msg_id == NETMSGTYPE_SV_CLIENTDROP:
                    cid,   p = unpack_int(data, p)
                    reason,p = read_str(data, p)
                    name = self._players.pop(cid, f"#{cid}")
                    if self.on_leave:
                        await self.on_leave(name, reason)

        except Exception as e:
            logger.debug(f"Chunk parse: {e}")

    async def disconnect(self):
        self._connected = False
        if self._sock:
            try:
                pkt = make_ctrl_packet(self._ack, NET_CTRLMSG_CLOSE)
                self._sock.send(pkt)
            except: pass
            self._sock.close()
            self._sock = None

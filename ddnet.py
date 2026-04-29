# ddnet.py — без aiohttp, только stdlib

import asyncio
import socket
import os
import json
import urllib.request
import logging

logger = logging.getLogger(__name__)

def pack_str(s): return s.encode("utf-8")[:15] + b"\x00"
def pack_str_long(s): return s.encode("utf-8")[:127] + b"\x00"

def pack_int(v):
    v = int(v)
    sign = 1 if v < 0 else 0
    if v < 0: v = -v - 1
    result = []; first = True
    while first or v:
        b = v & (0x3F if first else 0x7F)
        v >>= (6 if first else 7)
        if first: b |= (sign << 6); first = False
        if v: b |= 0x80
        result.append(b)
        if not v: break
    return bytes(result or [0])

def unpack_int_tw(data, pos):
    if pos >= len(data): return 0, pos
    b = data[pos]; pos += 1
    sign = (b >> 6) & 1
    v = b & 0x3F; shift = 6
    while b & 0x80 and pos < len(data):
        b = data[pos]; pos += 1
        v |= (b & 0x7F) << shift; shift += 7
    if sign: v = -(v + 1)
    return v, pos

def make_header(flags, ack, num_chunks, token):
    b0 = ((flags & 0xF) << 4) | ((ack >> 8) & 0xF)
    b1 = ack & 0xFF
    return bytes([b0, b1, num_chunks]) + token[:4]

def make_ctrl(ctrl_type, token_dst, extra=b""):
    return make_header(4, 0, 0, token_dst) + bytes([ctrl_type]) + extra


class DDNetClient:
    MASTER_URL = "https://master1.ddnet.org/ddnet/15/servers.json"

    def __init__(self, ip, port, name="TGBot", clan="", skin="default", password=""):
        self.ip = ip; self.port = port
        self.name = name[:15]; self.clan = clan[:11]
        self.skin = skin; self.password = password
        self._sock = None; self._loop = None
        self._token_cli = os.urandom(4)
        self._token_srv = b"\xff\xff\xff\xff"
        self._connected = False
        self._ack = 0; self._seq = 0
        self.on_chat = None
        self.on_join = None
        self.on_leave = None

    # ── Онлайн через urllib (без aiohttp) ─────────────────────────────────
    @staticmethod
    async def fetch_online(ip, port):
        def _fetch():
            try:
                req = urllib.request.urlopen(DDNetClient.MASTER_URL, timeout=8)
                return json.loads(req.read().decode())
            except Exception as e:
                return {"error": str(e)}

        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, _fetch)

        if "error" in data:
            return data

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
                             "score": c.get("score", 0)}
                            for c in clients
                        ]
                    }
        return {"error": "Сервер не найден в мастер-листе"}

    # ── Подключение ────────────────────────────────────────────────────────
    async def connect(self):
        import time
        self._loop = asyncio.get_event_loop()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        try:
            self._sock.connect((self.ip, self.port))
        except Exception as e:
            logger.error(f"Socket: {e}"); return False

        pkt = make_ctrl(0x01, self._token_srv, self._token_cli + b"\x00"*508)
        await self._raw_send(pkt)

        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                data = await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._recv_once), timeout=1.0)
                if data and len(data) >= 8:
                    if (data[0] >> 4) & 0xF == 4 and len(data) > 7 and data[7] == 0x02:
                        if len(data) >= 12:
                            self._token_srv = data[8:12]
                        self._connected = True
                        asyncio.create_task(self._recv_loop())
                        asyncio.create_task(self._keepalive_loop())
                        await asyncio.sleep(0.2)
                        await self._do_handshake()
                        return True
            except asyncio.TimeoutError:
                pass
        return False

    def _recv_once(self):
        try: return self._sock.recv(1400)
        except Exception: return None

    async def _raw_send(self, data):
        try: await self._loop.run_in_executor(None, self._sock.send, data)
        except Exception as e: logger.error(f"Send: {e}")

    async def _do_handshake(self):
        await self._send_sys(1, pack_str("0.7 802f1be60a05665f") + pack_str(self.password))
        await asyncio.sleep(0.3)
        await self._send_sys(4, b"")
        await asyncio.sleep(0.3)
        await self._send_sys(5, b"")
        await asyncio.sleep(0.3)
        await self._send_startinfo()

    async def _send_startinfo(self):
        payload = (pack_str(self.name) + pack_str(self.clan) +
                   pack_int(-1) + pack_str(self.skin) +
                   pack_int(0) + pack_int(0) + pack_int(0))
        await self._send_game(27, payload)

    async def send_chat(self, text):
        if not self._connected: return
        await self._send_game(4, pack_int(0) + pack_str_long(text))
        logger.info(f"[{self.name}] → {text}")

    async def _send_sys(self, msg_id, payload):
        await self._send_chunk(pack_int(msg_id * 2 + 1) + payload)

    async def _send_game(self, msg_id, payload):
        await self._send_chunk(pack_int(msg_id * 2) + payload)

    async def _send_chunk(self, data):
        size = len(data)
        seq = self._seq & 0x3FF; self._seq += 1
        ch0 = 0x40 | ((size >> 4) & 0x3F)
        ch1 = ((size & 0xF) << 4) | ((seq >> 6) & 0xF)
        ch2 = seq & 0xFF
        hdr = make_header(0, self._ack & 0x3FF, 1, self._token_srv)
        await self._raw_send(hdr + bytes([ch0, ch1, ch2]) + data)

    async def _keepalive_loop(self):
        while self._connected:
            await asyncio.sleep(10)
            await self._raw_send(make_ctrl(0x00, self._token_srv))

    async def _recv_loop(self):
        while self._connected:
            try:
                data = await asyncio.wait_for(
                    self._loop.run_in_executor(None, self._recv_once), timeout=1.0)
                if data: await self._handle_packet(data)
            except asyncio.TimeoutError: pass
            except Exception as e: logger.debug(f"Recv: {e}")

    async def _handle_packet(self, data):
        if len(data) < 7: return
        flags = (data[0] >> 4) & 0xF
        if flags & 4:
            if len(data) > 7 and data[7] == 0x04:
                self._connected = False
            return
        pos = 7
        num_chunks = data[2]
        for _ in range(num_chunks):
            if pos + 2 > len(data): break
            b0 = data[pos]; b1 = data[pos+1]
            size = ((b0 & 0x3F) << 4) | (b1 >> 4)
            vital = (b0 >> 6) & 1
            if vital:
                if pos + 3 > len(data): break
                seq = ((b1 & 0xF) << 8) | data[pos+2]
                self._ack = seq; pos += 3
            else:
                pos += 2
            if pos + size > len(data): break
            chunk = data[pos:pos+size]; pos += size
            await self._handle_chunk(chunk)

    async def _handle_chunk(self, data):
        if len(data) < 1: return
        try:
            msg_raw, p = unpack_int_tw(data, 0)
            sys_flag = msg_raw & 1
            msg_id = msg_raw >> 1
            if not sys_flag:
                if msg_id == 3 and len(data) > p+2:
                    team, p = unpack_int_tw(data, p)
                    cid, p  = unpack_int_tw(data, p)
                    txt = data[p:].split(b"\x00")[0].decode("utf-8", errors="replace")
                    if self.on_chat:
                        await self.on_chat(f"#{cid}", txt, team, cid)
                elif msg_id == 5:
                    cid, p = unpack_int_tw(data, p)
                    _, p = unpack_int_tw(data, p)
                    _, p = unpack_int_tw(data, p)
                    name = data[p:].split(b"\x00")[0].decode("utf-8", errors="replace")
                    if self.on_join and name:
                        await self.on_join(name)
                elif msg_id == 6:
                    cid, p = unpack_int_tw(data, p)
                    reason = data[p:].split(b"\x00")[0].decode("utf-8", errors="replace")
                    if self.on_leave:
                        await self.on_leave(f"#{cid}", reason)
        except Exception as e:
            logger.debug(f"Chunk parse: {e}")

    async def disconnect(self):
        self._connected = False
        if self._sock:
            try: self._sock.send(make_ctrl(0x04, self._token_srv))
            except: pass
            self._sock.close(); self._sock = None

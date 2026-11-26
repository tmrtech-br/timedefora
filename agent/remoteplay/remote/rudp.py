# SPDX-License-Identifier: AGPL-3.0-only
"""Implementação Python da estrutura de pacotes SCE RUDP e dos controles confiáveis.

Referência: chiaki-ng/lib/src/remote/rudp.c + rudpsendbuffer.c + include/.../rudp.h.
NÃO confundir com QUIC/WebRTC: SCE RUDP é um protocolo Sony diferente.

A serialização, o início/cookie, os ACKs e a retransmissão são implementados;
regist/session/ctrl por PSN ainda requer adaptação da pyremoteplay.
"""
from __future__ import annotations

import asyncio
import secrets
import struct
from dataclasses import dataclass
from enum import IntEnum
from http.client import HTTPException, parse_headers
from io import BytesIO

MAGIC = 0x244F244F
MAX_PACKET = 65535
DEFAULT_RETRY = 0.4
MAX_RETRIES = 25


class PacketType(IntEnum):
    INIT_REQUEST = 0x8030
    INIT_RESPONSE = 0xD000
    COOKIE_REQUEST = 0x9030
    COOKIE_RESPONSE = 0xA030
    SESSION_MESSAGE = 0x2030
    STREAM_CONNECTION_SWITCH_ACK = 0x242E
    ACK = 0x2430
    CTRL_MESSAGE = 0x0230
    FINISH = 0xC000


@dataclass(frozen=True)
class Packet:
    type: int
    payload: bytes
    subpacket: 'Packet | None' = None

    @property
    def remote_counter(self) -> int | None:
        return (int.from_bytes(self.payload[:2], 'big') + 1) & 0xFFFF if len(self.payload) >= 2 else None


@dataclass(frozen=True)
class SessionResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    remote_counter: int


def _session_response(packet: Packet) -> SessionResponse | None:
    if packet.remote_counter is None:
        return None
    head, boundary, body = packet.payload[2:].partition(b'\r\n\r\n')
    if not boundary or not head.startswith(b'HTTP/1.'):
        return None
    line, _, headers = head.partition(b'\r\n')
    parts = line.split(maxsplit=2)
    if len(parts) < 2 or len(parts[1]) != 3 or not parts[1].isdigit():
        return None
    try:
        parsed = parse_headers(BytesIO(headers + b'\r\n\r\n'))
    except HTTPException:
        return None
    return SessionResponse(int(parts[1]), {key.lower(): value for key, value in parsed.items()},
                           body, packet.remote_counter)


def pack(packet: Packet) -> bytes:
    size = 8 + len(packet.payload)
    if size > 0x0FFF:
        raise ValueError('SCE RUDP: submensagem individual excede 4095 bytes.')
    header = struct.pack('!HIH', 0xC000 | size, MAGIC, int(packet.type))
    result = header + packet.payload
    if packet.subpacket:
        result += pack(packet.subpacket)
    if len(result) > MAX_PACKET:
        raise ValueError('SCE RUDP: mensagem excede limite UDP.')
    return result


def unpack(data: bytes, *, max_depth: int = 4) -> Packet:
    if len(data) < 8:
        raise ValueError('Cabeçalho RUDP truncado.')
    field, magic, typ = struct.unpack_from('!HIH', data)
    size = field & 0x0FFF
    if magic != MAGIC or (field & 0xF000) != 0xC000 or size < 8 or size > len(data):
        raise ValueError('Cabeçalho SCE RUDP inválido.')
    if max_depth <= 0 and size < len(data):
        raise ValueError('Submensagens RUDP aninhadas além do limite.')
    subpacket = unpack(data[size:], max_depth=max_depth - 1) if len(data) > size else None
    return Packet(typ, data[8:size], subpacket)


def _greater_or_equal_16(a: int, b: int) -> bool:
    """Comparação circular RFC-style (usada para ACK cumulativo)."""
    return ((a - b) & 0xFFFF) < 0x8000


class _Receiver(asyncio.DatagramProtocol):
    def __init__(self, owner):
        self.owner = owner

    def datagram_received(self, data, addr):
        self.owner.receive_datagram(data, addr)

    def error_received(self, exc):
        self.owner.last_error = exc


class SceRudp:
    """Um socket UDP, sequência e retransmissões por sessão remota.

    Instancie uma conexão distinta por console. A ligação PSN real depende
    do holepunch concluir o socket ctrl; não inferir conexão só com INIT.
    """
    def __init__(self, peer: tuple[str, int], retry_interval=DEFAULT_RETRY, max_retries=MAX_RETRIES):
        self.peer = peer
        self.retry_interval = float(retry_interval)
        self.max_retries = int(max_retries)
        self.counter = secrets.randbelow(0x5E00) + 0x1FF
        self.header = secrets.randbits(32) | 0x8000
        self.transport = None
        self._owns_transport = False
        self._queue: asyncio.Queue[Packet] = asyncio.Queue(maxsize=128)
        self._pending: dict[int, tuple[bytes, asyncio.Future]] = {}
        self._retries: dict[int, asyncio.Task] = {}
        self.dropped = 0
        self.sent = 0
        self.received = 0
        self.last_error = None
        self.closed = False

    async def open(self, sock=None):
        if self.transport:
            raise RuntimeError('Socket RUDP já aberto.')
        if sock:
            sock.setblocking(False)
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: _Receiver(self), sock=sock,
                                                                 local_addr=None if sock else ('0.0.0.0', 0))
        self._owns_transport = True
        self.closed = False
        return self

    def attach(self, transport):
        if self.transport or self.closed:
            raise RuntimeError('Instância RUDP já utilizada.')
        self.transport = transport

    def receive_datagram(self, data, addr):
        if self.closed or addr != self.peer:
            return
        try:
            packet = unpack(data)
        except ValueError:
            self.dropped += 1
            return
        self._received(packet)

    def _seq(self) -> int:
        n = self.counter
        self.counter = (n + 1) & 0xFFFF
        return n

    def _send(self, data):
        if not self.transport or self.closed:
            raise ConnectionError('Socket SCE RUDP não aberto.')
        self.transport.sendto(data, self.peer)
        self.sent += 1

    async def start_handshake(self, timeout=1.0, tries=5) -> Packet:
        for _ in range(tries):
            payload = struct.pack('!H6sI2s', self._seq(), b'\x0b\x01\x01\x00\x01\x00', self.header, b'\x05\x82')
            self._send(pack(Packet(PacketType.INIT_REQUEST, payload)))
            try:
                result = await self.recv(timeout=timeout, subtype=PacketType.INIT_RESPONSE >> 8)
                return result
            except asyncio.TimeoutError:
                pass
        raise TimeoutError('SCE RUDP: nenhuma resposta INIT do console. Não foi estabelecida sessão.')

    async def send_cookie(self, cookie_response: bytes):
        payload = struct.pack('!H6sI2s', self._seq(), b'\x0b\x01\x01\x00\x01\x00', self.header, b'\x05\x82')
        self._send(pack(Packet(PacketType.COOKIE_REQUEST, payload + cookie_response)))

    async def negotiate_cookie(self, timeout=1.0, tries=3) -> int:
        init = await self.start_handshake(timeout=timeout, tries=tries)
        cookie = init.payload[8:]
        if not cookie:
            raise ConnectionError('SCE RUDP: INIT do console sem cookie.')
        for _ in range(tries):
            await self.send_cookie(cookie)
            try:
                result = await self.recv(timeout=timeout, subtype=PacketType.COOKIE_RESPONSE >> 8)
            except TimeoutError:
                continue
            if result.remote_counter is not None:
                return result.remote_counter
        raise TimeoutError('SCE RUDP: o console não confirmou o cookie.')

    async def send_session(self, remote_counter: int, payload: bytes):
        seq = self._seq()
        child = Packet(PacketType.CTRL_MESSAGE, struct.pack('!H', seq) + payload)
        parent = Packet(PacketType.SESSION_MESSAGE, struct.pack('!HH', seq, remote_counter), child)
        self._send(pack(parent))

    async def request_session(self, remote_counter: int, payload: bytes, *, timeout=1.0, tries=3) -> SessionResponse:
        if not payload or len(payload) > 4085:
            raise ValueError('Requisição Remote Play RUDP fora do limite.')
        loop = asyncio.get_running_loop()
        for _ in range(tries):
            await self.send_session(remote_counter, payload)
            deadline = loop.time() + timeout
            while (remaining := deadline - loop.time()) > 0:
                try:
                    packet = await self.recv(timeout=remaining)
                except TimeoutError:
                    break
                if (packet.type >> 8) & 0x0f not in (2, 6):
                    continue
                response = _session_response(packet)
                if response is not None:
                    return response
        raise TimeoutError('SCE RUDP: o console não respondeu à requisição Remote Play.')

    async def send_ack(self, remote_counter: int):
        payload = struct.pack('!HH2s', self.counter, remote_counter & 0xFFFF, b'\x00\x92')
        self._send(pack(Packet(PacketType.ACK, payload)))

    async def finish_exchange(self, remote_counter: int) -> None:
        await self.send_ack(remote_counter)
        try:
            await self.recv(timeout=1, subtype=PacketType.FINISH >> 8)
        except TimeoutError:
            pass

    async def send_ctrl(self, payload: bytes, *, wait_ack=False):
        seq = self._seq()
        raw = pack(Packet(PacketType.CTRL_MESSAGE, struct.pack('!H', seq) + payload))
        if len(self._pending) >= 16:
            raise BufferError('Fila RUDP de envio confiável cheia (16 mensagens).')
        fut = asyncio.get_running_loop().create_future()
        ack_seq = (seq + 1) & 0xFFFF  # mesma chave counter_ack do send_buffer no chiaki-ng
        self._pending[ack_seq] = (raw, fut)
        self._send(raw)
        self._retries[ack_seq] = asyncio.create_task(self._resend(ack_seq))
        if wait_ack:
            await fut
        else:
            fut.add_done_callback(lambda result: None if result.cancelled() else result.exception())
        return seq

    async def _resend(self, seq):
        for _ in range(self.max_retries):
            await asyncio.sleep(self.retry_interval)
            pair = self._pending.get(seq)
            if pair is None:
                return
            self._send(pair[0])
        pair = self._pending.pop(seq, None)
        self._retries.pop(seq, None)
        if pair and not pair[1].done():
            pair[1].set_exception(TimeoutError('CTRL SCE RUDP sem confirmação ACK.'))

    def _acknowledge(self, seq: int):
        for key in list(self._pending):
            if _greater_or_equal_16(seq, key):
                _, fut = self._pending.pop(key)
                task = self._retries.pop(key, None)
                if task:
                    task.cancel()
                if not fut.done():
                    fut.set_result(None)

    def _received(self, packet: Packet):
        part = packet
        while part is not None:
            self.received += 1
            if part.type >> 8 in (0x12, 0x24, 0x26, 0x36) and len(part.payload) >= 4:
                self._acknowledge(struct.unpack_from('!H', part.payload, 2)[0])
            if part.type == PacketType.CTRL_MESSAGE and part.remote_counter is not None:
                # Preserva o contador para a camada ctrl enviar ACK/heartbeat corretamente.
                pass
            try:
                self._queue.put_nowait(part)
            except asyncio.QueueFull:
                self.dropped += 1
            part = part.subpacket

    async def recv(self, types: set[int] | None = None, timeout: float = 1.0, *, subtype: int | None = None) -> Packet:
        async def read():
            while True:
                packet = await self._queue.get()
                if (types is None or packet.type in types) and (subtype is None or packet.type >> 8 == subtype):
                    return packet
        return await asyncio.wait_for(read(), timeout)

    async def close(self):
        self.closed = True
        for t in self._retries.values():
            t.cancel()
        self._retries.clear()
        for _, fut in self._pending.values():
            if not fut.done():
                fut.set_exception(ConnectionError('Sessão RUDP encerrada.'))
        self._pending.clear()
        if self.transport:
            if self._owns_transport:
                self.transport.close()
            self.transport = None

    def stats(self):
        return {'packets_sent': self.sent, 'packets_received': self.received,
                'packets_dropped': self.dropped, 'pending_acks': len(self._pending)}

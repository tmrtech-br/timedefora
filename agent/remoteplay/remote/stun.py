# SPDX-License-Identifier: AGPL-3.0-only
"""RFC 5389 STUN Binding sobre sockets UDP reais.

Adaptado conceitualmente de chiaki-ng/lib/src/remote/stun.h.
A verificação do transaction ID impede aceitar respostas de outros testes.
STUN descobre endereço externo; **não** conclui sozinho o holepunch PSN.
"""
from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
import struct
from dataclasses import dataclass

COOKIE = 0x2112A442
REQUEST = 0x0001
RESPONSE = 0x0101
XOR_MAPPED_ADDRESS = 0x0020
MAPPED_ADDRESS = 0x0001
STUN_SERVERS = (
    ('stun.moonlight-stream.org', 3478),
    ('stun.l.google.com', 19302),
    ('stun1.l.google.com', 19302),
    ('stun2.l.google.com', 19302),
    ('stun3.l.google.com', 19302),
)


@dataclass(frozen=True)
class Mapping:
    address: str
    port: int
    server: str
    local_port: int


def make_binding_request(txid: bytes | None = None) -> tuple[bytes, bytes]:
    txid = txid or secrets.token_bytes(12)
    if len(txid) != 12:
        raise ValueError('ID STUN deve conter 12 bytes.')
    return struct.pack('!HHI12s', REQUEST, 0, COOKIE, txid), txid


def parse_binding_response(packet: bytes, txid: bytes) -> tuple[str, int]:
    if len(packet) < 20 or len(txid) != 12:
        raise ValueError('Resposta STUN truncada.')
    typ, size, cookie, received_txid = struct.unpack_from('!HHI12s', packet)
    if typ != RESPONSE or cookie != COOKIE or received_txid != txid or size % 4 or 20 + size > len(packet):
        raise ValueError('Resposta STUN inválida ou pertence a outra solicitação.')
    pos = 20
    chosen = None
    while pos + 4 <= 20 + size:
        attr, n = struct.unpack_from('!HH', packet, pos)
        pos += 4
        if pos + n > 20 + size:
            raise ValueError('Atributo STUN truncado.')
        raw = packet[pos:pos+n]
        pos += (n + 3) & ~3
        if attr not in (XOR_MAPPED_ADDRESS, MAPPED_ADDRESS) or n < 8 or raw[0] != 0:
            continue
        family = raw[1]
        length = 4 if family == 1 else 16 if family == 2 else 0
        if not length or n < 4 + length:
            continue
        port = struct.unpack_from('!H', raw, 2)[0]
        ip = raw[4:4+length]
        if attr == XOR_MAPPED_ADDRESS:
            port ^= COOKIE >> 16
            key = struct.pack('!I', COOKIE) + txid
            ip = bytes(a ^ b for a, b in zip(ip, key))
        if not port:
            continue
        found = str(ipaddress.ip_address(ip)), port
        if attr == XOR_MAPPED_ADDRESS:
            return found
        chosen = found
    if chosen:
        return chosen
    raise ValueError('Resposta STUN sem endereço mapeado.')


class _Dispatcher(asyncio.DatagramProtocol):
    def __init__(self):
        self.pending: dict[bytes, asyncio.Future] = {}
        self.peer_packets = asyncio.Queue(maxsize=64)

    def datagram_received(self, data: bytes, addr):
        if len(data) < 20 or data[4:8] != struct.pack('!I', COOKIE):
            if not self.peer_packets.full():
                self.peer_packets.put_nowait((data, addr))
            return
        txid = data[8:20]
        future = self.pending.get(txid)
        if future and not future.done():
            try:
                future.set_result(parse_binding_response(data, txid))
            except ValueError:
                pass

    def error_received(self, exc):
        # Um servidor pode falhar sem abortar outros probes em andamento.
        pass


class StunClient:
    """Várias probes usando UM socket: a porta NAT observada é a mesma.

    O socket permanece aberto durante o uso do cliente. O chamador deve concluir
    a seleção de candidatos e o punch antes de fechar o recurso.
    """
    def __init__(self, sock: socket.socket | None = None):
        self._socket = sock
        self._own = sock is None
        self.transport = None
        self._protocol = None

    async def __aenter__(self):
        sock = self._socket
        if sock is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
            sock.bind(('0.0.0.0', 0))
        sock.setblocking(False)
        loop = asyncio.get_running_loop()
        self.transport, self._protocol = await loop.create_datagram_endpoint(_Dispatcher, sock=sock)
        self._socket = sock
        return self

    async def __aexit__(self, *_):
        if self.transport:
            self.transport.close()
            self.transport = None

    @property
    def local_port(self) -> int:
        return self._socket.getsockname()[1]

    async def receive_peer_packet(self):
        return await self._protocol.peer_packets.get()

    async def probe(self, server: str, port: int = 3478, timeout: float = 1.5) -> Mapping:
        if not self.transport:
            raise RuntimeError('Abra StunClient em async with.')
        loop = asyncio.get_running_loop()
        results = await asyncio.wait_for(loop.getaddrinfo(server, port, family=socket.AF_INET,
                                                           type=socket.SOCK_DGRAM), timeout)
        if not results:
            raise OSError('Servidor STUN sem endereço IPv4.')
        packet, txid = make_binding_request()
        fut = loop.create_future()
        self._protocol.pending[txid] = fut
        try:
            self.transport.sendto(packet, results[0][4])
            address, mapped_port = await asyncio.wait_for(fut, timeout)
            return Mapping(address, mapped_port, server, self.local_port)
        finally:
            self._protocol.pending.pop(txid, None)

    async def probe_many(self, servers=STUN_SERVERS, timeout: float = 1.5) -> tuple[Mapping, ...]:
        async def one(s):
            try:
                return await self.probe(s[0], s[1], timeout=timeout)
            except (OSError, ValueError, asyncio.TimeoutError):
                return None
        mappings = await asyncio.gather(*(one(server) for server in servers))
        valid = tuple(mapping for mapping in mappings if mapping is not None)
        if not valid:
            raise TimeoutError('Nenhum servidor STUN respondeu. Verifique rede, firewall ou UDP.')
        return valid

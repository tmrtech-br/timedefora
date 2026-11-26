# SPDX-License-Identifier: AGPL-3.0-only
"""Seleção preliminar do caminho UDP anunciado pela PSN."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import secrets
import struct

from .holepunch import PunchFailed


REQUEST = b'\x06\x00\x00\x00'
RESPONSE = b'\x07\x00\x00\x00'


def _identity(own: dict, peer: dict) -> bytes:
    first, second = (base64.b64decode(req['localHashedId'], validate=True) for req in (own, peer))
    if len(first) != 20 or len(second) != 20:
        raise ValueError('Identificador UDP inválido.')
    return first.ljust(32, b'\0') + second.ljust(32, b'\0') + struct.pack(
        '!HH', own['sid'] & 0xffff, peer['sid'] & 0xffff,
    )


def _packet(kind: bytes, identity: bytes, nonce: bytes, endpoint=None) -> bytes:
    suffix = bytes(8)
    if endpoint:
        address, port = endpoint
        mask = ipaddress.IPv4Address(address).packed + struct.pack('!H', port)
        pair = identity[-4:] + identity[-4:-2]
        suffix = bytes(a ^ b for a, b in zip(pair, mask)) + bytes(2)
    return kind + identity + bytes(3) + nonce + suffix


def _matches(data: bytes, expected: bytes) -> bool:
    return (len(data) == 88 and data[4:24] == expected[:20]
            and data[36:56] == expected[32:52] and data[68:72] == expected[-4:])


async def answer_control_probes(stun, own: dict, peer: dict, selected: dict):
    respond = control_probe_responder(stun, own, peer, selected)
    while True:
        respond(*await stun.receive_peer_packet())


def control_probe_responder(stun, own: dict, peer: dict, selected: dict):
    endpoint = (selected['addr'], selected['port'])
    identity = _identity(own, peer)
    expected = _identity(peer, own)

    def handle(data, source):
        if source == endpoint and data[:4] == REQUEST and _matches(data, expected):
            stun.transport.sendto(_packet(RESPONSE, identity, data[75:80], endpoint), endpoint)

    return handle


async def select_control_candidate(stun, own: dict, peer: dict, *, timeout: float = 8) -> dict:
    try:
        identity = _identity(own, peer)
        expected = _identity(peer, own)
    except (KeyError, TypeError, ValueError) as exc:
        raise PunchFailed('A oferta PSN não contém identificadores UDP válidos.') from exc
    candidates = {}
    for candidate in peer['candidate'][:32]:
        try:
            address, port = ipaddress.IPv4Address(candidate['addr']), candidate['port']
            if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_link_local:
                continue
            if type(port) is int and 0 < port <= 65535:
                candidates[str(address), port] = candidate
        except (KeyError, TypeError, ValueError):
            continue
    if not candidates:
        raise PunchFailed('O console não anunciou candidatos IPv4 utilizáveis.')

    nonce = secrets.token_bytes(5)
    request = _packet(REQUEST, identity, nonce)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        for endpoint in candidates:
            stun.transport.sendto(request, endpoint)
        retry = min(deadline, loop.time() + 0.25)
        while loop.time() < retry:
            try:
                data, endpoint = await asyncio.wait_for(stun.receive_peer_packet(), retry - loop.time())
            except TimeoutError:
                break
            if endpoint not in candidates or not _matches(data, expected):
                continue
            if data[:4] == REQUEST:
                stun.transport.sendto(_packet(RESPONSE, identity, data[75:80], endpoint), endpoint)
            if data[:4] == RESPONSE and secrets.compare_digest(data[75:80], nonce):
                return candidates[endpoint]
    raise PunchFailed('Nenhum candidato do console respondeu ao desafio UDP de controle.')

# SPDX-License-Identifier: AGPL-3.0-only
"""Abertura da sessão Remote Play no mesmo canal RUDP do registro PSN."""
from __future__ import annotations

import base64
import ipaddress
import secrets
import struct
import asyncio
from collections import deque

from pyremoteplay.const import OS_TYPE, RP_VERSION_PS4, TYPE_PS4, USER_AGENT
from pyremoteplay.crypt import SessionCipher
from pyremoteplay.session import _gen_did, _get_aes_key, _get_rp_nonce, _get_session_headers


class RemotePlaySessionError(ConnectionError):
    pass


async def initialize_ps4_session(channel, registration) -> bytes:
    address, port = channel.peer
    host = ipaddress.IPv4Address(address)
    request = (
        'GET /sie/ps4/rp/sess/init HTTP/1.1\r\n'
        f'Host: {host}:{port}\r\nUser-Agent: {USER_AGENT}\r\n'
        'Connection: close\r\nContent-Length: 0\r\n'
        f'RP-Registkey: {registration.registration_key.hex()}\r\nRp-Version: {RP_VERSION_PS4}\r\n\r\n'
    ).encode('ascii')
    try:
        counter = await channel.negotiate_cookie()
        response = await channel.request_session(counter, request, timeout=1.5)
        await channel.finish_exchange(response.remote_counter)
    except OSError as exc:
        raise RemotePlaySessionError('O PS4 não respondeu à abertura da sessão Remote Play pelo RUDP.') from exc
    if response.status != 200:
        raise RemotePlaySessionError(f'O PS4 recusou a abertura da sessão Remote Play (HTTP {response.status}).')
    try:
        nonce = base64.b64decode(response.headers.get('rp-nonce', ''), validate=True)
    except ValueError as exc:
        raise RemotePlaySessionError('O PS4 retornou um nonce Remote Play inválido.') from exc
    if len(nonce) != 16:
        raise RemotePlaySessionError('O PS4 não retornou um nonce Remote Play de 16 bytes.')
    return nonce


async def authenticate_ps4_control(channel, registration, nonce: bytes):
    address, port = channel.peer
    cipher = SessionCipher(TYPE_PS4, _get_aes_key(TYPE_PS4, nonce, registration.session_key),
                           _get_rp_nonce(TYPE_PS4, nonce))
    auth, did, os_type, bitrate = (
        base64.b64encode(cipher.encrypt(value)).decode('ascii')
        for value in (registration.registration_key.ljust(16, b'\0'), _gen_did(),
                      OS_TYPE.encode('ascii') + b'\0', bytes(4))
    )
    headers = _get_session_headers(TYPE_PS4, address, auth, did, os_type, bitrate, '')
    headers['Host'] = f'{address}:{port}'
    request = ('GET /sie/ps4/rp/sess/ctrl HTTP/1.1\r\n' +
               ''.join(f'{key}: {value}\r\n' for key, value in headers.items()) + '\r\n').encode('ascii')
    try:
        counter = await channel.negotiate_cookie()
        response = await channel.request_session(counter, request, timeout=1.5)
        await channel.send_ack(response.remote_counter)
    except OSError as exc:
        raise RemotePlaySessionError('O PS4 não respondeu à autenticação do canal de controle.') from exc
    if response.status != 200:
        raise RemotePlaySessionError(f'O PS4 recusou a autenticação do controle (HTTP {response.status}).')
    server_type = response.headers.get('rp-server-type')
    if server_type:
        try:
            encrypted_type = base64.b64decode(server_type, validate=True)
            if len(encrypted_type) == 16:
                cipher.decrypt(encrypted_type)
        except ValueError:
            pass
    return cipher, response.body


class Ps4Control:
    def __init__(self, channel, cipher, initial: bytes):
        self.channel = channel
        self.cipher = cipher
        self.frame = initial
        self.identifier = None
        self.switched = asyncio.Event()
        self.error = None
        self._seen = deque(maxlen=128)
        self._reader = asyncio.create_task(self._read())

    async def _read(self):
        try:
            while True:
                await self._consume()
                try:
                    packet = await self.channel.recv(timeout=5)
                except TimeoutError:
                    await self.channel.send_ctrl(struct.pack('!IH2x', 0, 0xfe))
                    continue
                subtype = packet.type >> 8
                if subtype == 0xc0:
                    raise RemotePlaySessionError('O PS4 encerrou o canal de controle.')
                if subtype in (0x24, 0x20) or packet.remote_counter is None:
                    continue
                await self.channel.send_ack(packet.remote_counter)
                offset = {0x02: 2, 0x12: 8, 0x26: 6, 0x36: 2}.get(subtype, 4)
                decoded = packet.payload[offset:]
                if (len(decoded) >= 8 and struct.unpack_from('!I', decoded)[0] == len(decoded) - 8
                        and packet.remote_counter not in self._seen):
                    self._seen.append(packet.remote_counter)
                    self.frame += decoded
        except (OSError, ValueError) as exc:
            self.error = exc
            self.switched.set()

    async def _consume(self):
        while len(self.frame) >= 8:
            size, kind = struct.unpack_from('!IH', self.frame)
            if size > len(self.frame) - 8:
                return
            data, self.frame = self.frame[8:8 + size], self.frame[8 + size:]
            if data:
                data = self.cipher.decrypt(data)
            if kind == 0x33:
                identifier = data[1:].strip(b'\0')
                if 24 <= len(identifier) <= 79 and identifier.isalnum():
                    self.identifier = identifier
            if kind == 0xfe:
                await self.channel.send_ctrl(struct.pack('!IH2x', 0, 0x1fe))
            if kind == 0x34:
                self.switched.set()
            if kind == 0x4:
                raise RemotePlaySessionError('O PS4 solicitou um PIN de login para o canal de controle.')

    async def switch_to_media(self, timeout=6):
        await self.channel.send_ctrl(struct.pack('!IH2x', 16, 0x0d) + secrets.token_bytes(16))
        try:
            await asyncio.wait_for(self.switched.wait(), timeout)
        except TimeoutError as exc:
            raise RemotePlaySessionError('O PS4 não confirmou a transição para a mídia.') from exc
        if self.error is not None:
            raise RemotePlaySessionError(str(self.error)) from self.error

    async def close(self):
        self._reader.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)

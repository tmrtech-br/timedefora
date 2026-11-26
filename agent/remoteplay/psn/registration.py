# SPDX-License-Identifier: AGPL-3.0-only
"""Registro PS4 pelo canal RUDP estabelecido via PSN."""
from __future__ import annotations

import base64
import ipaddress
import secrets
from dataclasses import dataclass, field

from pyremoteplay.const import RP_VERSION_PS4, TYPE_PS4, USER_AGENT
from pyremoteplay.crypt import SessionCipher
from pyremoteplay.keys import REG_KEY_0_PS4, REG_KEY_1_PS4
from pyremoteplay.register import CLIENT_TYPE

class RemoteRegistrationError(ConnectionError):
    pass


@dataclass(frozen=True)
class RemoteRegistration:
    registration_key: bytes = field(repr=False)
    session_key: bytes = field(repr=False)


def build_ps4_request(account_id: str, local_address: str, data1: bytes, data2: bytes,
                      custom_data: bytes, ambassador: bytes) -> tuple[bytes, SessionCipher]:
    if any(len(value) != 16 for value in (data1, data2, custom_data, ambassador)):
        raise RemoteRegistrationError('Contexto de registro PSN inválido.')
    try:
        account = base64.b64encode(int(account_id).to_bytes(8, 'little')).decode()
        address = str(ipaddress.IPv4Address(local_address))
    except (ValueError, OverflowError) as exc:
        raise RemoteRegistrationError('Conta ou endereço de registro PSN inválido.') from exc

    encrypted = SessionCipher(TYPE_PS4, data1, data2).encrypt(custom_data)
    # O preenchimento ASCII A do corpo seleciona as colunas 1 e 8.
    key = bytes(value ^ REG_KEY_0_PS4[index * 32 + 1] for index, value in enumerate(encrypted))
    aeropause = bytes(
        ((value - index - 0x29) & 0xff) ^ REG_KEY_1_PS4[index * 32 + 8]
        for index, value in enumerate(ambassador)
    )
    cipher = SessionCipher(TYPE_PS4, key, ambassador)
    inner = f'Client-Type: {CLIENT_TYPE}\r\nNp-AccountId: {account}\r\n'.encode('ascii')
    prefix = bytearray(b'A' * 480)
    prefix[0xc7:0xcf], prefix[0x191:0x199] = aeropause[8:], aeropause[:8]
    body = prefix + cipher.encrypt(inner)
    headers = (
        'POST /sie/ps4/rp/sess/rgst HTTP/1.1\r\n HTTP/1.1\r\n'
        f'HOST: {address}\r\nUser-Agent: {USER_AGENT}\r\nConnection: close\r\n'
        f'Content-Length: {len(body)}\r\nRP-Version: {RP_VERSION_PS4}\r\n\r\n'
    ).encode('ascii')
    return headers + body, cipher


async def register_ps4(channel, counter: int, peer, custom_data: bytes,
                       local_address: str) -> RemoteRegistration:
    request, cipher = build_ps4_request(peer.session.account_id, local_address, peer.data1,
                                       peer.data2, custom_data, secrets.token_bytes(16))
    try:
        response = await channel.request_session(counter, request, timeout=1.5)
    except TimeoutError as exc:
        raise RemoteRegistrationError('O PS4 não respondeu ao registro remoto pelo RUDP.') from exc
    await channel.finish_exchange(response.remote_counter)
    if response.status != 200:
        raise RemoteRegistrationError(f'O PS4 recusou o registro remoto (HTTP {response.status}).')
    try:
        size = int(response.headers.get('content-length', '0'))
        if not 0 < size <= len(response.body):
            raise ValueError
        data = cipher.decrypt(response.body[:size]).decode('ascii', errors='replace')
        fields = {name.strip().lower(): value.strip() for line in data.splitlines()
                  for name, separator, value in [line.partition(':')] if separator}
        registration_key = bytes.fromhex(fields['ps4-registkey']).rstrip(b'\0')
        session_key = bytes.fromhex(fields['rp-key'])
        mac = bytes.fromhex(fields['ps4-mac'])
        if not 1 <= len(registration_key) <= 16 or len(session_key) != 16 or len(mac) != 6:
            raise ValueError
    except (KeyError, ValueError) as exc:
        raise RemoteRegistrationError('O PS4 retornou dados de registro incompletos ou inválidos.') from exc
    return RemoteRegistration(registration_key, session_key)

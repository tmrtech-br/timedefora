# SPDX-License-Identifier: AGPL-3.0-only
"""Primitivas HTTP reais do Sony Remote Play Session Manager.

Referência: chiaki-ng/lib/src/remote/holepunch.c http_create_session/deleteSession.
ATENÇÃO: criar sessão não representa console conectado ou streaming ativo.
As notificações push, comandos de início, ofertas, NAT traversal e cleanup
precisam ser integrados antes de usar esta API em produção.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

CREATE_URL = 'https://web.np.playstation.com/api/sessionManager/v1/remotePlaySessions'


class SessionManagerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteSession:
    session_id: str
    account_id: str


async def acknowledge_offer(client, token: str, session: RemoteSession, duid: str,
                            platform: str, request_id: int) -> None:
    message = {'action': 'RESULT', 'reqId': request_id, 'error': 0, 'connRequest': {}}
    await send_session_message(client, token, session, duid, platform, message)


async def send_session_message(client, token: str, session: RemoteSession, duid: str,
                               platform: str, message: dict) -> None:
    request_id = message.get('reqId')
    if (not token or not re.fullmatch(r'[0-9a-fA-F]{64}', duid) or
            not session.account_id.isdecimal() or platform not in ('PS4', 'PS5') or
            type(request_id) is not int or not 0 <= request_id <= 2**31 - 1):
        raise SessionManagerError('Dados da mensagem de sessão inválidos.')
    envelope = {
        'channel': 'remote_play:1',
        'payload': 'ver=1.0, type=text, body=' + json.dumps(message, separators=(',', ':')),
        'to': [{'accountId': session.account_id, 'deviceUniqueId': duid.lower(), 'platform': platform}],
    }
    try:
        sid = str(uuid.UUID(session.session_id))
        response = await client.post(
            f'{CREATE_URL}/{sid}/sessionMessage',
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json; charset=utf-8'},
            json=envelope, timeout=8, follow_redirects=False,
        )
        response.raise_for_status()
    except Exception as exc:
        raise SessionManagerError('A PSN não aceitou o envio da mensagem de controle.') from exc


def parse_created(payload: dict) -> RemoteSession:
    try:
        first = payload['remotePlaySessions'][0]
        sid = str(uuid.UUID(first['sessionId']))
        account = str(first['members'][0]['accountId'])
        if not account.isdecimal():
            raise ValueError('Account ID não numérico.')
        return RemoteSession(sid, account)
    except (KeyError, IndexError, TypeError, AttributeError, ValueError) as exc:
        raise SessionManagerError('Sony retornou dados inválidos ao criar a sessão. Nenhuma conexão foi confirmada.') from exc


async def create_session(client, token: str, push_context_id: str) -> RemoteSession:
    if not token or not push_context_id or len(push_context_id) > 256:
        raise SessionManagerError('Conta Sony / push context inválido.')
    body = {'remotePlaySessions': [{'members': [{'accountId': 'me', 'deviceUniqueId': 'me',
                'platform': 'me', 'pushContexts': [{'pushContextId': push_context_id}]}]}]}
    try:
        response = await client.post(CREATE_URL, headers={'Authorization': f'Bearer {token}'},
                                     json=body, timeout=10)
        response.raise_for_status()
        return parse_created(response.json())
    except SessionManagerError:
        raise
    except Exception as exc:
        raise SessionManagerError('Sony não conseguiu criar a sessão Remote Play. Faça login novamente ou verifique a conexão.') from exc


async def delete_session(client, token: str, session_id: str) -> None:
    if not token:
        raise SessionManagerError('Token Sony não informado.')
    try:
        sid = str(uuid.UUID(session_id))
        response = await client.delete(f'{CREATE_URL}/{sid}/members/me',
                                       headers={'Authorization': f'Bearer {token}',
                                                'X-PSN-SESSION-MANAGER-SESSION-IDS': sid},
                                       timeout=5)
        response.raise_for_status()
    except Exception as exc:
        raise SessionManagerError('Sony não confirmou exclusão da sessão. Verifique o estado antes de reabrir.') from exc

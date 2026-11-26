# SPDX-License-Identifier: AGPL-3.0-only
"""Sony session bootstrap, based on chiaki-ng/lib/src/remote/holepunch.c.

This opens the signaling session. A caller still needs to negotiate sockets,
register and authenticate Remote Play before starting media or input.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import secrets
import socket
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import aiohttp
import httpx

from ..remote.stun import StunClient
from ..remote.control_probe import answer_control_probes, control_probe_responder
from ..remote.rudp import MAGIC, SceRudp
from .session_manager import RemoteSession, SessionManagerError, acknowledge_offer, create_session, delete_session, send_session_message

PUSH_ADDRESS = ('https://mobile-pushcl.np.communication.playstation.net/np/serveraddr'
                '?version=2.1&fields=keepAliveStatus&keepAliveStatusType=3')
PROFILE_ADDRESS = 'https://asm.np.community.playstation.net/asm/v1/apps/me/baseUrls/userProfile'
COMMANDS_URL = 'https://web.np.playstation.com/api/cloudAssistedNavigation/v2/users/me/commands'
SESSION_CREATED = 'psn:sessionManager:sys:remotePlaySession:created'
MEMBER_CREATED = 'psn:sessionManager:sys:rps:members:created'
SESSION_DELETED = 'psn:sessionManager:sys:remotePlaySession:deleted'
CUSTOM_DATA_UPDATED = 'psn:sessionManager:sys:rps:customData1:updated'
SESSION_MESSAGE_CREATED = 'psn:sessionManager:sys:rps:sessionMessage:created'
DUID = re.compile(r'[0-9a-fA-F]{64}')
SONY_FQDN = re.compile(r'(?:[a-zA-Z0-9-]+\.)+playstation\.net')
STAGE_LABELS = {
    'push_lookup': 'Localizar notificações',
    'push_connect': 'Abrir canal de notificações',
    'session_create': 'Criar sessão na Sony',
    'session_notification': 'Confirmar sessão',
    'console_request': 'Solicitar entrada do console',
    'console_join': 'Aguardar entrada do console',
    'control_offer': 'Aguardar oferta do canal de controle',
    'control_ack': 'Confirmar oferta do canal de controle',
    'client_offer': 'Enviar oferta de controle do agente',
    'control_accept': 'Confirmar o endereço UDP de controle',
    'control_rudp': 'Abrir o canal RUDP de controle',
    'media_offer': 'Aguardar oferta do canal de mídia',
}


class NegotiationError(RuntimeError):
    def __init__(self, stage: str, message: str):
        label = STAGE_LABELS.get(stage)
        super().__init__(f'{label}. {message}' if label else message)
        self.stage = stage


@dataclass(frozen=True)
class RemotePeer:
    session: RemoteSession
    duid: str
    data1: bytes = field(repr=False)
    data2: bytes = field(repr=False)


@dataclass(frozen=True)
class ControlOffer:
    request: dict = field(repr=False)
    custom_data: bytes = field(repr=False)


def _parse_session_message(data: dict) -> dict | None:
    envelope = data.get('sessionMessage')
    payload = envelope.get('payload') if isinstance(envelope, dict) else None
    if not isinstance(payload, str) or len(payload) > 65536:
        return None
    _, marker, body = payload.partition('body=')
    if not marker:
        return None
    # Alguns consoles omitem o valor desse campo em vez de enviar null.
    body = re.sub(r'("localPeerAddr"\s*:\s*)(?=[,}])', r'\g<1>null', body, count=1)
    try:
        message = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict) or type(message.get('reqId')) is not int:
        return None
    return message


def _parse_control_offer(data: dict) -> dict | None:
    message = _parse_session_message(data)
    if message is None or message.get('action') != 'OFFER' or message.get('error') != 0:
        return None
    request = message.get('connRequest')
    candidates = request.get('candidate') if isinstance(request, dict) else None
    if not isinstance(candidates, list) or not candidates:
        return None
    return message


async def wait_for_control_offer(notifications, *, timeout: float = 15) -> ControlOffer:
    custom_data = None
    offer = None
    try:
        async with asyncio.timeout(timeout):
            async for kind, data, _ in notifications:
                if kind == SESSION_DELETED:
                    break
                if kind == CUSTOM_DATA_UPDATED:
                    value = data.get('customData1')
                    if isinstance(value, str) and len(value) <= 40:
                        try:
                            decoded = base64.b64decode(base64.b64decode(value, validate=True), validate=True)
                        except ValueError:
                            continue
                        if 16 <= len(decoded) <= 20:
                            custom_data = decoded[:16]
                if kind == SESSION_MESSAGE_CREATED:
                    offer = _parse_control_offer(data) or offer
                if custom_data is not None and offer is not None:
                    return ControlOffer(offer, custom_data)
    except TimeoutError as exc:
        missing = 'dados de registro' if custom_data is None else 'oferta de controle'
        raise NegotiationError('control_offer', f'O PS4 não enviou {missing} dentro do prazo.') from exc
    raise NegotiationError('control_offer', 'A sessão PSN encerrou antes de confirmar a oferta de controle.')


async def confirm_control_offer(client, token: str, peer: RemotePeer, platform: str,
                                notifications, *, timeout: float = 15) -> ControlOffer:
    offer = await wait_for_control_offer(notifications, timeout=timeout)
    try:
        await acknowledge_offer(client, token, peer.session, peer.duid, platform, offer.request['reqId'])
    except SessionManagerError as exc:
        raise NegotiationError('control_ack', str(exc)) from exc
    return offer


@asynccontextmanager
async def open_control_candidates(client, token: str, peer: RemotePeer, platform: str,
                                  notifications, offer: ControlOffer, *, timeout: float = 12,
                                  local_identity: dict | None = None):
    """Mantenha a porta anunciada aberta após o RESULT do console."""
    console_sid = offer.request['connRequest'].get('sid')
    if type(console_sid) is not int or not -(2**31) <= console_sid < 2**32:
        raise NegotiationError('client_offer', 'A oferta do console não contém um identificador de sessão válido.')
    async with StunClient() as stun:
        try:
            mappings = await stun.probe_many()
        except TimeoutError as exc:
            raise NegotiationError('client_offer', 'Nenhum servidor STUN respondeu na porta UDP do agente.') from exc
        address, port = mappings[0].address, mappings[0].port
        candidates = [{'type': 'STUN', 'addr': address, 'port': port,
                       'mappedAddr': '0.0.0.0', 'mappedPort': 0}]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route:
            route.connect((address, port))
            local = route.getsockname()[0]
        candidates.append({'type': 'LOCAL', 'addr': local, 'port': stun.local_port,
                           'mappedAddr': '0.0.0.0', 'mappedPort': 0})
        request_id = secrets.randbelow(2**31 - 1) + 1
        message = {
            'action': 'OFFER', 'reqId': request_id, 'error': 0,
            'connRequest': {
                'sid': local_identity['sid'] if local_identity else secrets.randbelow(65535) + 1,
                'peerSid': console_sid & 0xffff,
                'skey': base64.b64encode(bytes(16)).decode(), 'natType': 2,
                'candidate': candidates, 'defaultRouteMacAddr': '',
                'localPeerAddr': {'accountId': peer.session.account_id, 'platform': 'REMOTE_PLAY'},
                'localHashedId': (local_identity['localHashedId'] if local_identity
                                  else base64.b64encode(secrets.token_bytes(20)).decode()),
            },
        }
        reply = None
        try:
            await send_session_message(client, token, peer.session, peer.duid, platform, message)
            async with asyncio.timeout(timeout):
                async for kind, data, _ in notifications:
                    if kind == SESSION_DELETED:
                        reply = None
                        break
                    reply = _parse_session_message(data) if kind == SESSION_MESSAGE_CREATED else None
                    if reply and reply.get('action') == 'RESULT' and reply['reqId'] == request_id:
                        if reply.get('error') != 0:
                            raise NegotiationError('client_offer', 'O console recusou a oferta do agente.')
                        break
                else:
                    reply = None
        except SessionManagerError as exc:
            raise NegotiationError('client_offer', str(exc)) from exc
        except TimeoutError as exc:
            raise NegotiationError('client_offer', 'O console não confirmou a oferta do agente dentro do prazo.') from exc
        if not reply or reply.get('action') != 'RESULT' or reply['reqId'] != request_id:
            raise NegotiationError('client_offer', 'A sessão PSN encerrou antes da confirmação da oferta do agente.')
        yield stun, message


async def wait_for_media_offer(client, token: str, peer: RemotePeer, notifications,
                               control_offer: ControlOffer, *, timeout: float = 8) -> ControlOffer:
    try:
        async with asyncio.timeout(timeout):
            async for kind, data, _ in notifications:
                if kind == SESSION_DELETED:
                    break
                message = _parse_control_offer(data) if kind == SESSION_MESSAGE_CREATED else None
                if message is None:
                    continue
                await acknowledge_offer(client, token, peer.session, peer.duid, 'PS4', message['reqId'])
                if message['reqId'] != control_offer.request['reqId']:
                    return ControlOffer(message, control_offer.custom_data)
    except TimeoutError as exc:
        raise NegotiationError('media_offer', 'O PS4 não enviou a oferta de mídia dentro do prazo.') from exc
    except SessionManagerError as exc:
        raise NegotiationError('media_offer', str(exc)) from exc
    raise NegotiationError('media_offer', 'A sessão PSN encerrou antes da oferta de mídia.')


async def accept_control_candidate(client, token: str, peer: RemotePeer, platform: str,
                                   notifications, stun, own: dict, remote: dict,
                                   selected: dict, *, timeout: float = 8) -> None:
    # O ACCEPT associa o endereço do PS4 ao endereço correspondente do agente.
    route_type = 'LOCAL' if selected['type'] == 'LOCAL' else 'STUN'
    route = next(item for item in own['connRequest']['candidate'] if item['type'] == route_type)
    request = {**own['connRequest'], 'natType': 0,
               'candidate': [{key: selected[key] for key in ('type', 'addr', 'port')}
                             | {'mappedAddr': route['addr'], 'mappedPort': route['port']}],
               'localHashedId': ''}
    accept_id = own['reqId'] % (2**31 - 1) + 1
    message = {'action': 'ACCEPT', 'reqId': accept_id, 'error': 0, 'connRequest': request}
    responder = asyncio.create_task(answer_control_probes(stun, own['connRequest'], remote, selected))
    try:
        async with asyncio.timeout(timeout):
            await send_session_message(client, token, peer.session, peer.duid, platform, message)
            async for kind, data, _ in notifications:
                if kind == SESSION_DELETED:
                    break
                reply = _parse_session_message(data) if kind == SESSION_MESSAGE_CREATED else None
                if reply is None:
                    continue
                if reply.get('action') == 'RESULT' and reply['reqId'] == accept_id and reply.get('error') != 0:
                    raise NegotiationError('control_accept', 'O PS4 recusou o endereço de controle selecionado.')
                if reply.get('action') != 'ACCEPT' or reply.get('error') != 0:
                    continue
                connection = reply.get('connRequest')
                if (not isinstance(connection, dict) or connection.get('sid') != request['peerSid']
                        or connection.get('peerSid') != request['sid']):
                    continue
                await acknowledge_offer(client, token, peer.session, peer.duid, platform, reply['reqId'])
                return
    except SessionManagerError as exc:
        raise NegotiationError('control_accept', str(exc)) from exc
    except TimeoutError as exc:
        raise NegotiationError('control_accept', 'O PS4 não confirmou o endereço de controle dentro do prazo.') from exc
    finally:
        responder.cancel()
        await asyncio.gather(responder, return_exceptions=True)
    raise NegotiationError('control_accept', 'A sessão PSN encerrou antes da confirmação do endereço de controle.')


@asynccontextmanager
async def open_control_rudp(udp, selected: dict, own: dict, remote: dict):
    """Use a porta aceita no hole punching também para a sessão RUDP."""
    channel = SceRudp((selected['addr'], selected['port']))
    channel.attach(udp.transport)
    magic = MAGIC.to_bytes(4, 'big')
    respond = control_probe_responder(udp, own, remote, selected)

    async def forward():
        while True:
            data, source = await udp.receive_peer_packet()
            if data[2:6] == magic:
                channel.receive_datagram(data, source)
            else:
                respond(data, source)

    reader = asyncio.create_task(forward())
    try:
        try:
            await asyncio.sleep(1)
            remote_counter = await channel.negotiate_cookie()
        except (TimeoutError, OSError) as exc:
            raise NegotiationError('control_rudp', str(exc)) from exc
        yield channel, remote_counter
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        await channel.close()


async def _json(client, url, headers):
    response = await client.get(url, headers=headers, timeout=8, follow_redirects=False)
    response.raise_for_status()
    return response.json()


async def _request_console(client, headers, session, platform, duid, online_id, data1, data2):
    data = {
        'sessionId': session.session_id, 'roomId': 0, 'clientType': 'Windows',
        'data1': base64.b64encode(data1).decode('ascii'),
        'data2': base64.b64encode(data2).decode('ascii'),
    }
    headers = {**headers, 'User-Agent': 'RpNetHttpUtilImpl'}
    if platform == 'PS4':
        profile = await _json(client, PROFILE_ADDRESS, headers)
        base = profile.get('url') if isinstance(profile, dict) else None
        url = urlsplit(base if isinstance(base, str) else '')
        if url.scheme != 'https' or not SONY_FQDN.fullmatch(url.netloc) or url.query or url.fragment:
            raise NegotiationError('console_request', 'A Sony retornou um endereço inválido para localizar o PS4 principal.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', online_id or ''):
            raise NegotiationError('console_request', 'A PSN não informou um ID online válido para localizar o PS4 principal.')
        target = f'{base.rstrip("/")}/v1/users/{quote(online_id, safe="")}/remoteConsole/wakeUp?platform=PS4'
        body = {'dataTypeSuffix': 'remotePlay', 'data': {**data, 'protocolVer': '10.0'}}
    else:
        target = COMMANDS_URL
        initial = {**data, 'accountId': int(session.account_id)}
        body = {'commandDetail': {
            'commandType': 'remotePlay', 'duid': duid, 'messageDestination': 'SQS',
            'parameters': {'initialParams': json.dumps(initial, separators=(',', ':'))}, 'platform': 'PS5',
        }}
    response = await client.post(target, json=body, headers=headers, timeout=8, follow_redirects=False)
    response.raise_for_status()


async def _notifications(socket, session_id):
    async for message in socket:
        if message.type not in (aiohttp.WSMsgType.TEXT, aiohttp.WSMsgType.BINARY):
            continue
        try:
            event = json.loads(message.data)
            data = event['body']['data']
        except (KeyError, TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get('sessionId') == session_id:
            yield event.get('dataType'), data, event.get('to')


async def _replay_notifications(pending, notifications):
    for event in pending:
        yield event
    async for event in notifications:
        yield event


@asynccontextmanager
async def open_remote_peer(client, token: str, platform: str, *, duid: str | None = None):
    if platform not in ('PS4', 'PS5') or (platform == 'PS5' and not DUID.fullmatch(duid or '')):
        raise NegotiationError('configuration', 'Plataforma ou DUID inválido para a sessão PSN.')
    stage = 'push_lookup'
    headers = {'Authorization': f'Bearer {token}'}
    session = None
    try:
        payload = await _json(client, PUSH_ADDRESS, headers)
        fqdn = payload.get('fqdn') if isinstance(payload, dict) else None
        if not isinstance(fqdn, str) or not SONY_FQDN.fullmatch(fqdn):
            raise NegotiationError(stage, 'A Sony retornou um endereço inválido para as notificações PSN.')
        stage = 'push_connect'
        push_headers = {
            **headers, 'User-Agent': 'WebSocket++/0.8.2', 'X-PSN-APP-TYPE': 'REMOTE_PLAY',
            'X-PSN-APP-VER': 'RemotePlay/1.0', 'X-PSN-KEEP-ALIVE-STATUS-TYPE': '3',
            'X-PSN-OS-VER': 'Windows/10.0', 'X-PSN-PROTOCOL-VERSION': '2.1',
            'X-PSN-RECONNECTION': 'false',
        }
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as ws_client:
            async with ws_client.ws_connect(f'wss://{fqdn}/np/pushNotification', headers=push_headers,
                                            protocols=('np-pushpacket',), heartbeat=5,
                                            max_msg_size=256 * 1024) as socket:
                stage = 'session_create'
                session = await create_session(client, token, str(uuid.uuid4()))
                data1, data2 = secrets.token_bytes(16), secrets.token_bytes(16)
                stage = 'session_notification'
                notifications = _notifications(socket, session.session_id)
                try:
                    async with asyncio.timeout(10):
                        async for kind, _, recipient in notifications:
                            if kind == SESSION_CREATED:
                                online_id = recipient.get('onlineId') if isinstance(recipient, dict) else None
                                break
                        else:
                            raise NegotiationError(stage, 'O canal PSN fechou antes de confirmar a sessão.')
                    stage = 'console_request'
                    await _request_console(client, headers, session, platform, duid, online_id, data1, data2)
                    stage = 'console_join'
                    pending = deque(maxlen=16)
                    async with asyncio.timeout(25):
                        async for kind, data, recipient in notifications:
                            if kind == SESSION_DELETED:
                                raise NegotiationError(stage, 'A Sony encerrou a sessão antes da entrada do console.')
                            if kind in (CUSTOM_DATA_UPDATED, SESSION_MESSAGE_CREATED):
                                pending.append((kind, data, recipient))
                            members = data.get('members')
                            if kind != MEMBER_CREATED or not isinstance(members, list):
                                continue
                            for member in members:
                                uid = member.get('deviceUniqueId') if isinstance(member, dict) else None
                                if not isinstance(uid, str) or not DUID.fullmatch(uid):
                                    continue
                                member_platform = str(member.get('platform') or '').upper()
                                if member_platform not in ({'PS4', 'ORBIS'} if platform == 'PS4' else {'PS5', 'PROSPERO'}):
                                    continue
                                if duid and uid.lower() != duid.lower():
                                    continue
                                break
                            else:
                                continue
                            break
                        else:
                            raise NegotiationError(stage, 'O canal PSN fechou antes de o console entrar.')
                    replay = _replay_notifications(pending, notifications)
                    try:
                        yield RemotePeer(session, uid.lower(), data1, data2), replay
                    finally:
                        await replay.aclose()
                finally:
                    await notifications.aclose()
    except (aiohttp.ClientError, httpx.HTTPError, TimeoutError, ValueError, SessionManagerError) as exc:
        message = 'A etapa da negociação PSN falhou. Confira a conta, a rede e se o console está ligado ou em repouso.'
        if stage == 'push_connect':
            if isinstance(exc, aiohttp.WSServerHandshakeError):
                message = f'A Sony recusou a abertura do WebSocket (HTTP {exc.status}).'
                if exc.status == 401:
                    message += ' Execute Testar conta no painel e tente novamente.'
                elif exc.status == 403:
                    challenge = (exc.headers or {}).get('WWW-Authenticate', '')
                    if re.search(r'\berror="insufficient_scope"', challenge, re.IGNORECASE):
                        message += ' O serviço informou que o token não tem a permissão exigida pelo canal.'
                    elif re.search(r'\berror="invalid_token"', challenge, re.IGNORECASE):
                        message += ' O serviço de notificações informou que o token é inválido para esse canal.'
                    else:
                        message += ' O serviço não identificou a causa da recusa na resposta de autenticação.'
            elif isinstance(exc, TimeoutError):
                message = 'O PC do ConsoleAgent não recebeu resposta da Sony ao abrir o WebSocket dentro do prazo.'
            elif isinstance(exc, aiohttp.ClientConnectorCertificateError):
                message = 'O PC do ConsoleAgent não conseguiu validar o certificado TLS da Sony.'
            elif isinstance(exc, aiohttp.ClientConnectorError):
                message = f'O PC do ConsoleAgent não conseguiu conectar ao servidor de notificações da Sony ({type(exc).__name__}).'
            else:
                message = f'O WebSocket com a Sony falhou ({type(exc).__name__}).'
        elif stage == 'console_join' and isinstance(exc, TimeoutError):
            message = ('A Sony aceitou o pedido para chamar o console, mas o agente não recebeu a notificação '
                       'de entrada do PS4. Confirme que ele está conectado à PSN, que é o PS4 principal da '
                       'conta vinculada e que não há outra sessão de Uso remoto aberta.')
        elif isinstance(exc, TimeoutError):
            message = 'A Sony ou o console não respondeu dentro do prazo nesta etapa.'
        raise NegotiationError(stage, message) from exc
    finally:
        if session is not None:
            try:
                await delete_session(client, token, session.session_id)
            except SessionManagerError:
                # Do not expose the HTTP response or override a negotiation failure.
                logging.getLogger(__name__).warning('A Sony não confirmou a limpeza da sessão de negociação.')

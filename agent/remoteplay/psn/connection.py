# SPDX-License-Identifier: AGPL-3.0-only
"""Ciclo de vida da conexão com o PS4, da sinalização à mídia decodificada."""
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from threading import Lock

from ..remote.control_probe import select_control_candidate
from .media import open_ps4_media
from .negotiation import (
    accept_control_candidate, confirm_control_offer, open_control_candidates, open_control_rudp,
    open_remote_peer, wait_for_media_offer,
)
from .play_session import Ps4Control, authenticate_ps4_control, initialize_ps4_session
from .registration import register_ps4


_reserved_accounts = set()
_reservation_lock = Lock()


@contextmanager
def reserve_ps4_account(account_id):
    with _reservation_lock:
        if account_id in _reserved_accounts:
            raise ConnectionError('Já existe uma conexão PSN em andamento para essa conta.')
        _reserved_accounts.add(account_id)
    try:
        yield
    finally:
        with _reservation_lock:
            _reserved_accounts.discard(account_id)


@asynccontextmanager
async def open_ps4_connection(client, token, receiver, progress, *, resolution='720p', fps=30, quality='medium'):
    async with AsyncExitStack() as stack:
        peer, notifications = await stack.enter_async_context(open_remote_peer(client, token, 'PS4'))
        progress('console_join', 'O PS4 entrou na sessão PSN e enviou o DUID.', peer.duid)
        offer = await confirm_control_offer(client, token, peer, 'PS4', notifications)
        count = len(offer.request['connRequest']['candidate'])
        progress('control_ack', f'Oferta de controle com {count} candidato(s) confirmada.')
        udp, message = await stack.enter_async_context(
            open_control_candidates(client, token, peer, 'PS4', notifications, offer)
        )
        own, remote = message['connRequest'], offer.request['connRequest']
        selected = await select_control_candidate(udp, own, remote)
        kind = selected.get('type')
        kind = kind if kind in ('LOCAL', 'STATIC', 'STUN', 'DERIVED') else 'desconhecido'
        progress('control_udp', f'O PS4 respondeu ao desafio UDP ({kind}).')
        await accept_control_candidate(client, token, peer, 'PS4', notifications, udp, message, remote, selected)
        progress('control_accept', 'O PS4 confirmou o endereço UDP de controle.')
        channel, counter = await stack.enter_async_context(open_control_rudp(udp, selected, own, remote))
        progress('control_rudp', 'O PS4 confirmou a abertura do canal RUDP.')
        local = next(item['addr'] for item in own['candidate'] if item['type'] == 'LOCAL')
        registration = await register_ps4(channel, counter, peer, offer.custom_data, local)
        progress('remote_registration', 'O PS4 aceitou o registro remoto.')
        nonce = await initialize_ps4_session(channel, registration)
        progress('remote_session_init', 'O PS4 aceitou a abertura da sessão Remote Play.')
        cipher, initial = await authenticate_ps4_control(channel, registration, nonce)
        control = Ps4Control(channel, cipher, initial)
        stack.push_async_callback(control.close)
        progress('control_authenticated', 'O PS4 autenticou o canal de controle.')

        media_offer = await wait_for_media_offer(client, token, peer, notifications, offer)
        media_udp, media_message = await stack.enter_async_context(
            open_control_candidates(client, token, peer, 'PS4', notifications, media_offer, local_identity=own)
        )
        media_own, media_remote = media_message['connRequest'], media_offer.request['connRequest']
        media_selected = await select_control_candidate(media_udp, media_own, media_remote)
        await accept_control_candidate(
            client, token, peer, 'PS4', notifications, media_udp, media_message, media_remote, media_selected,
        )
        progress('media_udp', 'O PS4 confirmou o endereço UDP de mídia.')
        await control.switch_to_media()
        session = await stack.enter_async_context(open_ps4_media(
            media_udp, media_selected, media_own, media_remote, cipher, control.identifier, receiver,
            resolution=resolution, fps=fps, quality=quality,
        ))
        session.ps4_control = control          # canal de controle RUDP (repouso ao fim da sessão)
        frame = receiver.latest_video
        progress('media_video', f'O ConsoleAgent decodificou vídeo real do PS4 ({frame.width}×{frame.height}).')
        yield session

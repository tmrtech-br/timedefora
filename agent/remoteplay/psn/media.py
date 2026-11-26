# SPDX-License-Identifier: AGPL-3.0-only
"""Mídia Remote Play em um socket previamente negociado pela PSN."""
from __future__ import annotations

import asyncio
import base64
import secrets
import time
from contextlib import asynccontextmanager

from pyremoteplay.session import Session

from ..remote.control_probe import REQUEST, RESPONSE, control_probe_responder
from .play_session import RemotePlaySessionError


class _MediaTransport:
    def __init__(self, transport):
        self._transport = transport
        self._loop = asyncio.get_running_loop()

    def sendto(self, data, endpoint):
        self._loop.call_soon_threadsafe(self._transport.sendto, data, endpoint)

    def close(self):
        # O contexto STUN/PSN é dono do socket.
        pass


@asynccontextmanager
async def open_ps4_media(udp, selected, own, remote, cipher, identifier, receiver, *,
                         resolution='720p', fps=30, timeout=10):
    # A sessão de vídeo pode começar mesmo quando o PS4 não manda o ID pelo controle.
    if not identifier:
        identifier = str(int(time.monotonic())).encode() + base64.b64encode(secrets.token_bytes(48))
    endpoint = selected['addr'], selected['port']
    session = Session(endpoint[0], {}, loop=asyncio.get_running_loop(), receiver=receiver,
                      resolution=resolution, fps=fps, quality='very_low', codec='h264')
    respond = control_probe_responder(udp, own, remote, selected)

    async def receive():
        while not session.is_stopped:
            data, source = await udp.receive_peer_packet()
            if source != endpoint or not data:
                continue
            if len(data) == 88 and data[:4] in (REQUEST, RESPONSE):
                respond(data, source)
            else:
                session.stream.handle(data)

    reader = None
    try:
        await session.start_negotiated_stream(_MediaTransport(udp.transport), endpoint, cipher, identifier)
        reader = asyncio.create_task(receive())
        async with asyncio.timeout(timeout):
            while receiver.latest_video is None:
                if session.is_stopped or reader.done():
                    raise RemotePlaySessionError(session.error or 'O canal de mídia foi encerrado.')
                await asyncio.sleep(0.05)
        yield session
    except TimeoutError as exc:
        raise RemotePlaySessionError('Nenhum quadro foi decodificado pelo canal de mídia dentro do prazo.') from exc
    finally:
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        session.stop()

# SPDX-License-Identifier: AGPL-3.0-only
"""Mídia Remote Play em um socket previamente negociado pela PSN."""
from __future__ import annotations

import asyncio
import base64
import secrets
import time
from contextlib import asynccontextmanager

from pyremoteplay.const import Quality
from pyremoteplay.session import Session

from ..remote.control_probe import REQUEST, RESPONSE, control_probe_responder
from .play_session import RemotePlaySessionError


PS4_RESOLUTIONS = ('360p', '540p', '720p')
DEFAULT_PSN_KBPS = int(Quality.MEDIUM)          # 6 Mbps: equilíbrio para a subida doméstica da casa do console


def stream_options(resolution: str | None, fps, bitrate_kbps) -> dict:
    """Converte o cadastro do console nos parâmetros aceitos pelo PS4 (720p no máximo no PS4 comum)."""
    res = str(resolution or '720p').lower()
    res = res if res in PS4_RESOLUTIONS else '720p'
    try:
        fps = int(fps)
    except (TypeError, ValueError):
        fps = 30
    try:
        kbps = int(bitrate_kbps or 0)
    except (TypeError, ValueError):
        kbps = 0
    kbps = kbps or DEFAULT_PSN_KBPS
    presets = sorted(q for q in Quality if q is not Quality.DEFAULT)
    quality = next((q for q in reversed(presets) if q.value <= kbps), presets[0])
    return {'resolution': res, 'fps': fps if fps in (30, 60) else 30, 'quality': quality.name.lower()}


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
                         resolution='720p', fps=30, quality='medium', timeout=10):
    # A sessão de vídeo pode começar mesmo quando o PS4 não manda o ID pelo controle.
    if not identifier:
        identifier = str(int(time.monotonic())).encode() + base64.b64encode(secrets.token_bytes(48))
    endpoint = selected['addr'], selected['port']
    session = Session(endpoint[0], {}, loop=asyncio.get_running_loop(), receiver=receiver,
                      resolution=resolution, fps=fps, quality=quality, codec='h264')
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

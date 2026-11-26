# SPDX-License-Identifier: AGPL-3.0-only
"""Repasse WebRTC de quadros H.264 já codificados, sem reencode com libx264.

Recebe access units Annex-B da pyremoteplay AVStream via callback no agente.
O aiortc aceita av.Packet no MediaStreamTrack e H264Encoder.pack() apenas
fragmenta NALUs em RTP — não executa um encoder H.264.

Fonte do formato: agent/pyremoteplay/av.py AVStream._handle_src_packet;
aiortc/src/aiortc/codecs/h264.py H264Encoder.pack.
"""
from __future__ import annotations

import asyncio
import fractions
import threading
import time
from collections import deque


class EncodedH264Buffer:
    def __init__(self, max_frames=6):
        self._lock = threading.Lock()
        self._frames: deque[tuple[int, bytes]] = deque(maxlen=max_frames)
        self._counter = 0
        self.has_parameter_sets = False
        self.has_idr = False
        self.dropped = 0
        self.valid_frames = 0

    @staticmethod
    def nal_types(data: bytes) -> tuple[int, ...]:
        # Retorna tipos AVC NAL para formatos Annex-B 00 00 01 ou 00 00 00 01.
        out = []
        i = 0
        while True:
            pos = data.find(b'\x00\x00\x01', i)
            if pos == -1:
                return tuple(out)
            start = pos + 3
            if start < len(data):
                out.append(data[start] & 0x1F)
            i = start + 1

    def push(self, raw: bytes) -> bool:
        if not isinstance(raw, bytes) or not (4 < len(raw) <= 2_000_000):
            return False
        # Remove apenas o padding FFmpeg inserido pela biblioteca de recepção,
        # não remove bytes reais do bitstream.
        try:
            from pyremoteplay.const import FFMPEG_PADDING
            pad = int(FFMPEG_PADDING)
        except ImportError:
            pad = 0
        if pad and len(raw) > pad and raw.endswith(bytes(pad)):
            raw = raw[:-pad]
        types = self.nal_types(raw)
        if not types or not any(typ in (1, 5) for typ in types):
            return False
        with self._lock:
            if 7 in types and 8 in types:
                self.has_parameter_sets = True
            if 5 in types:
                self.has_idr = True
            if not self.has_parameter_sets or not self.has_idr:
                return False
            if len(self._frames) == self._frames.maxlen:
                self.dropped += 1
            self._counter += 1
            self._frames.append((self._counter, raw))
            self.valid_frames += 1
        return True

    def next_frame(self, last_counter: int) -> tuple[int, bytes] | None:
        with self._lock:
            # Descarte os frames obsoletos para minimizar atraso.
            if not self._frames or self._frames[-1][0] <= last_counter:
                return None
            return self._frames[-1]

    def make_track(self, *, fps=30):
        try:
            import av
            from aiortc import MediaStreamTrack
            from aiortc.mediastreams import MediaStreamError
        except ImportError as exc:
            raise RuntimeError('Repasse H.264 indisponível: instale aiortc e av no ConsoleAgent.') from exc
        buffer = self

        class H264Track(MediaStreamTrack):
            kind = 'video'
            encoded_passthrough = True

            def __init__(self):
                super().__init__()
                self.seq = 0
                self.start = time.monotonic()
                self.last_pts = -1
                self.sent = deque(maxlen=90)
                self.started_with_idr = False

            async def recv(self):
                deadline = time.monotonic() + 10
                while self.readyState == 'live':
                    next_frame = buffer.next_frame(self.seq)
                    if next_frame is not None:
                        self.seq, data = next_frame
                        # Nunca iniciar a reprodução numa P-frame que exige referências
                        # anteriores. Esperar um IDR real do PlayStation.
                        if not self.started_with_idr:
                            if 5 not in buffer.nal_types(data):
                                await asyncio.sleep(0.004)
                                continue
                            self.started_with_idr = True
                        packet = av.Packet(data)
                        packet.time_base = fractions.Fraction(1, 90000)
                        self.last_pts = max(self.last_pts + 1, round((time.monotonic() - self.start) * 90000))
                        packet.pts = packet.dts = self.last_pts
                        self.sent.append(time.monotonic())
                        return packet
                    if time.monotonic() > deadline:
                        raise MediaStreamError('Fluxo real H.264 ausente há 10 s.')
                    await asyncio.sleep(0.004)
                raise MediaStreamError('Trilha H.264 encerrada.')

            def fps(self):
                now = time.monotonic()
                n = sum(1 for t in self.sent if now - t <= 3)
                return round(n / 3, 1) if n > 1 else None

        return H264Track()

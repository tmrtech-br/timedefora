"""Vídeo e áudio do console para o navegador do jogador (WebRTC, biblioteca aiortc).

- Vídeo: captura da janela do chiaki-ng (a mesma usada nos testes), até 30 quadros/s, largura máx. configurável.
  A janela precisa ficar visível (não minimizada nem coberta por outra janela).
- Áudio: gravação "loopback" da saída de som padrão do PC (biblioteca soundcard). Captura TODO o som do PC:
  deixe só o chiaki-ng tocando som. Sem a biblioteca, a transmissão segue só com vídeo (e o agente avisa).
- Uma conexão por console; uma nova oferta (reconexão) substitui a anterior. Revogar a sessão fecha a conexão.
As importações pesadas são feitas sob demanda: o agente funciona sem aiortc (responde "vídeo indisponível").
"""
from __future__ import annotations

import asyncio
import fractions
import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable

from . import winutil

log = logging.getLogger('consoleagent.webrtc')
DEFAULT_ICE = [{'urls': 'stun:stun.l.google.com:19302'}]


class WebRtcUnavailable(Exception):
    pass


def _require():
    try:
        import aiortc  # noqa: F401
        import av  # noqa: F401
        import numpy  # noqa: F401
    except ImportError as e:
        raise WebRtcUnavailable('Vídeo no navegador indisponível: instale aiortc e numpy no agente '
                                f'(pip install -r requirements.txt). Detalhe: {e}') from e


def make_video_track(get_pid: Callable[[], int | None], max_width: int = 1280):
    import av
    import numpy as np
    from aiortc import VideoStreamTrack

    class WindowVideoTrack(VideoStreamTrack):
        """Quadros reais da janela do chiaki-ng; tela preta enquanto a janela não existe."""

        def __init__(self):
            super().__init__()
            self._black = None
            self._win, self._win_at = None, 0.0
            self.sent = deque(maxlen=90)            # instantes dos últimos quadros com imagem real (fps medido)

        def _window(self):
            now = time.monotonic()
            if now - self._win_at > 1.0:            # posição da janela: 1×/s basta (procurar a cada quadro custa caro)
                self._win, self._win_at = winutil.main_window(get_pid()), now
            return self._win

        def _grab(self):
            w = self._window()
            arr = None
            if w:
                arr = winutil.grab_rgb(w.rect)      # rápido (mss); senão, Pillow
                if arr is None:
                    img = winutil.grab(w.rect)
                    arr = np.asarray(img.convert('RGB')) if img is not None else None
            if arr is None:
                if self._black is None:
                    self._black = np.zeros((720, 1280, 3), dtype=np.uint8)
                return self._black, False
            if arr.shape[1] > max_width:            # reduz por amostragem (barato) até caber na largura máxima
                step = -(-arr.shape[1] // max_width)
                arr = arr[::step, ::step]
            arr = np.ascontiguousarray(arr[: arr.shape[0] // 2 * 2, : arr.shape[1] // 2 * 2])   # yuv420 exige dimensões pares
            return arr, True

        async def recv(self):
            pts, time_base = await self.next_timestamp()
            arr, real = await asyncio.get_running_loop().run_in_executor(None, self._grab)
            if real:
                self.sent.append(time.monotonic())
            frame = av.VideoFrame.from_ndarray(arr, format='rgb24')
            frame.pts, frame.time_base = pts, time_base
            return frame

        def fps(self) -> float | None:
            now = time.monotonic()
            recent = [t for t in self.sent if now - t <= 3]
            return round(len(recent) / 3, 1) if len(recent) > 1 else None

    return WindowVideoTrack()


def make_audio_track():
    """Áudio da saída padrão do PC (loopback). None se a biblioteca soundcard não estiver instalada."""
    try:
        import soundcard as sc
    except Exception:
        return None
    import av
    import numpy as np
    from aiortc import MediaStreamTrack

    RATE, BLOCK = 48000, 960                      # 20 ms por quadro de áudio

    class LoopbackAudioTrack(MediaStreamTrack):
        kind = 'audio'

        def __init__(self):
            super().__init__()
            self._q: queue.Queue = queue.Queue(maxsize=50)
            self._run = True
            self._pts = 0
            threading.Thread(target=self._reader, daemon=True, name='audio-loopback').start()

        def _reader(self):
            try:
                if winutil.IS_WIN:
                    import ctypes
                    ctypes.windll.ole32.CoInitializeEx(None, 0)
                spk = sc.default_speaker()
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
                with mic.recorder(samplerate=RATE, channels=2, blocksize=BLOCK) as rec:
                    while self._run:
                        data = rec.record(numframes=BLOCK)
                        try:
                            self._q.put_nowait(data)
                        except queue.Full:
                            self._q.get_nowait()          # descarta o mais antigo (atraso menor)
                            self._q.put_nowait(data)
            except Exception as e:
                log.warning('captura de áudio parou: %s', e)

        async def recv(self):
            loop = asyncio.get_running_loop()
            try:
                data = await loop.run_in_executor(None, lambda: self._q.get(timeout=0.1))
            except queue.Empty:
                data = np.zeros((BLOCK, 2), dtype=np.float32)       # silêncio se a captura atrasar
            pcm = (np.clip(data[:BLOCK], -1, 1) * 32767).astype(np.int16).reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(pcm, format='s16', layout='stereo')
            frame.sample_rate, frame.pts, frame.time_base = RATE, self._pts, fractions.Fraction(1, RATE)
            self._pts += BLOCK
            return frame

        def stop(self):
            self._run = False
            super().stop()

    return LoopbackAudioTrack()


class WebRtcHub:
    """Conexões WebRTC ativas: console_id → (session_id, conexão, faixas)."""

    def __init__(self, ice_servers: list | None = None, max_width: int = 1280, audio: bool = True):
        self.ice = ice_servers or DEFAULT_ICE
        self.max_width, self.audio = max_width, audio
        self.peers: dict[str, dict] = {}

    async def answer(self, console_id: str, session_id: str, offer: dict, get_pid: Callable[[], int | None]) -> tuple[dict, str]:
        _require()
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

        await self.close(console_id)
        servers = [RTCIceServer(urls=s.get('urls'), username=s.get('username'), credential=s.get('credential')) for s in self.ice]
        pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        entry = {'session_id': session_id, 'pc': pc, 'video': None, 'audio': None}
        self.peers[console_id] = entry

        @pc.on('connectionstatechange')
        async def _state():
            log.info('WebRTC console %s: %s', console_id[:8], pc.connectionState)
            if pc.connectionState in ('failed', 'closed') and self.peers.get(console_id) is entry:
                await self.close(console_id)

        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer['sdp'], type=offer['type']))
        entry['video'] = make_video_track(get_pid, self.max_width)
        pc.addTrack(entry['video'])
        note = 'vídeo'
        if self.audio:
            a = make_audio_track()
            if a is not None:
                entry['audio'] = a
                pc.addTrack(a)
                note += ' e áudio'
            else:
                note += ' (áudio indisponível: instale soundcard no agente)'
        await pc.setLocalDescription(await pc.createAnswer())      # aguarda a coleta de candidatos (STUN)
        return {'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp}, f'Transmissão de {note} iniciada.'

    async def close(self, console_id: str, session_id: str | None = None) -> None:
        e = self.peers.get(console_id)
        if not e or (session_id and e['session_id'] != session_id):
            return
        self.peers.pop(console_id, None)
        for t in (e['video'], e['audio']):
            if t is not None:
                t.stop()
        await e['pc'].close()

    def fps(self, console_id: str) -> float | None:
        e = self.peers.get(console_id)
        return e['video'].fps() if e and e['video'] is not None else None

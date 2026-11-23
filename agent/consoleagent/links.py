"""Formas de o agente falar com o console ("links"). O orquestrador, o vídeo WebRTC e os testes usam só esta interface.

- ChiakiLink  (método remote_play_chiaki): chiaki-ng em processo separado + controle virtual (ViGEmBus) + captura da janela.
- DirectLink  (método remote_play_direct): protocolo Remote Play dentro do agente (pyremoteplay incorporada): sem janela,
  sem monitor e com controle próprio por console — vários consoles no mesmo PC. Só rede local.

Interface comum:
    kind, available, unavailable_reason
    registered(t) -> bool | None          está registrado/pareado para este console? (None = não deu para saber)
    regist_key(t) -> str                  chave de registro (hex) para acordar o console; '' se desconhecida
    start(t, sleep) / running / stop()    abrir e fechar a conexão com o console
    frame() -> media.Frame                checagem REAL da imagem atual
    video_frame()                         quadro atual para o WebRTC (av.VideoFrame ou matriz RGB) ou None
    audio_track()                         faixa de áudio própria para o WebRTC, ou None (usa a saída de som do PC)
    audio_peak(seconds) -> (pico|None, msg)
    new_pad()                             controle do jogador: apply(cmd), press(nome), reset(), close()
    pair(t, pin) -> (ok, msg)             registro com o PIN do console (só DirectLink)
    log_tail() -> str
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from pathlib import Path

from . import media, winutil
from .chiaki import ChiakiDriver, ChiakiError
from .gamepad import PLAYER_BLOCKED, GamepadUnavailable, VirtualPad

log = logging.getLogger('consoleagent.links')
DATA_DIR = Path(__file__).resolve().parent.parent / 'data'


class LinkError(Exception):
    pass


# =====================================================================================================  chiaki-ng
class ChiakiLink:
    kind = 'chiaki'

    def __init__(self, path: str, make_pad=VirtualPad, frame_fn=media.frame, audio_fn=media.audio_peak):
        self.driver = ChiakiDriver(path)
        self._make_pad, self._frame, self._audio = make_pad, frame_fn, audio_fn
        self._win, self._win_at = None, 0.0

    path = property(lambda self: self.driver.path)
    available = property(lambda self: self.driver.available)
    running = property(lambda self: self.driver.running)
    pid = property(lambda self: self.driver.pid)

    @property
    def unavailable_reason(self) -> str:
        return '' if self.available else f'chiaki-ng não encontrado em {self.driver.path}.'

    def registered(self, t) -> bool | None:
        return self.driver.registered(t.nickname) if t.nickname else None

    def regist_key(self, t) -> str:
        return t.regist_key

    def start(self, t, sleep=time.sleep) -> None:
        if t.direct:
            self.driver.start_direct(t.nickname, t.host, t.passcode, t.profile)
        else:
            self.driver.start_psn_gui(t.psn_gui_steps, t.profile, sleep=sleep)

    def stop(self) -> None:
        self.driver.stop()

    def frame(self) -> media.Frame:
        return self._frame(self.driver.pid)

    def video_frame(self):
        now = time.monotonic()
        if now - self._win_at > 1.0:                 # posição da janela 1×/s
            self._win, self._win_at = winutil.main_window(self.driver.pid), now
        if not self._win:
            return None
        arr = winutil.grab_rgb(self._win.rect)
        if arr is None:
            img = winutil.grab(self._win.rect)
            if img is None:
                return None
            import numpy as np
            arr = np.asarray(img.convert('RGB'))
        return arr

    def audio_track(self):
        return None                                   # áudio = saída de som do PC (loopback)

    def audio_peak(self, seconds: float = 1.5):
        return self._audio(self.driver.pid, seconds)

    def new_pad(self):
        return self._make_pad()

    def pair(self, t, pin: str):
        reg = self.registered(t)
        if reg:
            return True, f'"{t.nickname}" está registrado no chiaki-ng deste PC.'
        how = ('No PC do agente: abra o chiaki-ng → registre o console com o PIN de Configurações → Configurações da Conexão '
               'de Uso Remoto → Adicionar Dispositivo. Use como apelido a identificação do painel.')
        if reg is None:
            return False, 'Não foi possível consultar os consoles do chiaki-ng. ' + how
        return False, f'"{t.nickname}" ainda não está registrado no chiaki-ng. ' + how

    def log_tail(self) -> str:
        return self.driver.log_tail()


# =====================================================================================================  direto
_BUTTONS = {'cross': 'CROSS', 'circle': 'CIRCLE', 'square': 'SQUARE', 'triangle': 'TRIANGLE', 'l1': 'L1', 'r1': 'R1',
            'l2': 'L2', 'r2': 'R2', 'l3': 'L3', 'r3': 'R3', 'options': 'OPTIONS', 'share': 'SHARE',
            'dpad_up': 'UP', 'dpad_down': 'DOWN', 'dpad_left': 'LEFT', 'dpad_right': 'RIGHT',
            'ps': 'PS', 'touchpad': 'TOUCHPAD'}
_AXES = {'left_x': ('left', 'x'), 'left_y': ('left', 'y'), 'right_x': ('right', 'x'), 'right_y': ('right', 'y')}


def _rp():
    """Importa a biblioteca incorporada sob demanda (o agente funciona sem ela no modo chiaki-ng)."""
    try:
        import pyremoteplay  # noqa: F401
        from pyremoteplay.device import RPDevice
        from pyremoteplay.profile import Profiles
        from pyremoteplay.receiver import AVReceiver
        return RPDevice, Profiles, AVReceiver
    except Exception as e:  # dependências ausentes
        raise LinkError('Remote Play direto indisponível: instale as dependências do agente (pip install -r requirements.txt). '
                        f'Detalhe: {e.__class__.__name__}: {e}') from e


def profiles_path() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(DATA_DIR / 'remoteplay_profiles.json')


def load_profiles():
    _, Profiles, _ = _rp()
    Profiles.set_default_path(profiles_path())
    return Profiles.load(profiles_path())


class DirectPad:
    """Controle do jogador enviado direto na sessão Remote Play deste console (não existe controle virtual no Windows)."""

    def __init__(self, controller):
        self._c = controller
        self._pressed: set[str] = set()

    def apply(self, command: dict) -> None:
        kind, name = command.get('type'), str(command.get('name', '')).lower()
        if name in PLAYER_BLOCKED:
            raise PermissionError('Comando bloqueado por segurança.')
        if kind == 'button':
            if name not in _BUTTONS:
                raise ValueError(f'Botão desconhecido: {name}')
            pressed = bool(command.get('pressed', True))
            if pressed == (name in self._pressed):
                return                                # sem mudança (repetição)
            self._c.button(_BUTTONS[name], 'press' if pressed else 'release')
            (self._pressed.add if pressed else self._pressed.discard)(name)
        elif kind == 'axis':
            if name not in _AXES:
                raise ValueError(f'Eixo desconhecido: {name}')
            stick, axis = _AXES[name]
            self._c.stick(stick, axis=axis, value=max(-1.0, min(1.0, float(command.get('value', 0)))))
        else:
            raise ValueError('Tipo de comando inválido.')

    def press(self, name: str, hold: float = 0.12) -> None:
        """Toque curto (roteiros internos; pode usar o botão PS)."""
        name = name.lower()
        if name not in _BUTTONS:
            raise ValueError(f'Botão desconhecido: {name}')
        self._c.button(_BUTTONS[name], 'tap', delay=hold)

    def reset(self) -> None:
        for name in list(self._pressed):
            self._c.button(_BUTTONS[name], 'release')
        self._pressed.clear()
        self._c.stick('left', point=(0.0, 0.0))
        self._c.stick('right', point=(0.0, 0.0))

    def close(self) -> None:
        try:
            self.reset()
        except Exception:
            pass


class DirectLink:
    """Uma sessão Remote Play por console, num laço asyncio próprio (thread dedicada)."""

    kind = 'direct'
    path = 'Remote Play direto (pyremoteplay incorporada)'
    SESSION_TIMEOUT = 30.0

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.device = None
        self.receiver = None
        self.error = ''

    # ------------------------------------------------------------ infraestrutura
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or not self._thread or not self._thread.is_alive():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True, name='remoteplay-loop')
            self._thread.start()
        return self._loop

    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._ensure_loop()).result(timeout)

    @property
    def available(self) -> bool:
        try:
            _rp()
            return True
        except LinkError:
            return False

    @property
    def unavailable_reason(self) -> str:
        try:
            _rp()
            return ''
        except LinkError as e:
            return str(e)

    def _device(self, host: str):
        RPDevice, _, _ = _rp()
        if not host:
            raise LinkError('IP do console não informado (cadastro do console no painel).')
        dev = RPDevice(host)
        if not dev.get_status():
            raise LinkError(f'O console não respondeu em {host} (desligado, fora da rede ou IP errado).')
        return dev

    def _user_for(self, dev, t, profiles) -> str | None:
        users = profiles.get_users(dev.mac_address)
        if t.psn_user and t.psn_user in users:
            return t.psn_user
        return users[0] if users else None

    # ------------------------------------------------------------ registro
    def registered(self, t) -> bool | None:
        try:
            dev = self._device(t.host)
            return bool(self._user_for(dev, t, load_profiles()))
        except LinkError:
            return None

    def regist_key(self, t) -> str:
        """Chave de registro salva no pareamento (texto hex), para acordar o console pelo agente."""
        try:
            profiles = load_profiles()
            for user in profiles.users:
                for host in user.hosts:
                    data = host.data
                    if t.mac and host.name.upper() != t.mac.upper():
                        continue
                    key = bytes.fromhex(data['RegistKey']).decode(errors='ignore').rstrip('\x00')
                    if key:
                        return key
        except Exception:
            pass
        return t.regist_key

    def pair(self, t, pin: str):
        pin = (pin or '').strip()
        if not (pin.isdigit() and len(pin) == 8):
            return False, 'Informe o PIN de 8 dígitos exibido no console (Configurações → Configurações da Conexão de Uso Remoto → Adicionar Dispositivo).'
        try:
            profiles = load_profiles()
        except LinkError as e:
            return False, str(e)
        if not profiles.usernames:
            return False, ('Nenhuma conta PSN vinculada ao agente. No PC do agente rode: '
                           'python -m consoleagent --psn-login (uma vez) e tente de novo.')
        user = t.psn_user if t.psn_user in profiles.usernames else profiles.usernames[0]
        try:
            dev = self._device(t.host)
        except LinkError as e:
            return False, str(e)
        if not dev.is_on:
            return False, 'O console precisa estar LIGADO (fora do modo de repouso) para o registro.'
        result = dev.register(user, pin, timeout=5.0, profiles=profiles, save=True)
        if not result:
            return False, 'O console recusou o registro (PIN errado/expirado ou a conta PSN não é a mesma logada no console).'
        return True, f'Console {dev.host_name or t.host} registrado para a conta PSN "{user}".'

    # ------------------------------------------------------------ sessão
    def start(self, t, sleep=time.sleep) -> None:
        _, _, AVReceiver = _rp()
        self.stop()
        profiles = load_profiles()
        dev = self._device(t.host)
        if not dev.is_on:
            raise LinkError('O console está em repouso: precisa ser acordado antes de conectar.')
        user = self._user_for(dev, t, profiles)
        if not user:
            raise LinkError(f'Console {dev.host_name or t.host} não registrado neste agente: use "Pareamento" no painel com o PIN do console.')
        self.receiver = _make_receiver(AVReceiver)
        res = {'720p': '720p', '1080p': '1080p', '540p': '540p', '360p': '360p'}.get(str(t.resolution or '720p').lower(), '720p')
        if res == '1080p' and (dev.host_type or '').upper() == 'PS4':
            res = '720p'                                # PS4 comum não transmite 1080p no Remote Play
        session = dev.create_session(user, profiles=profiles, loop=self._ensure_loop(), receiver=self.receiver,
                                     resolution=res, fps=int(t.fps or 30) if int(t.fps or 30) in (30, 60) else 30,
                                     codec='hevc' if str(t.codec or '').lower() in ('h265', 'hevc') and (dev.host_type or '') == 'PS5' else 'h264')
        if session is None:
            raise LinkError('Não foi possível criar a sessão Remote Play (perfil de usuário inválido).')
        self.device = dev
        if not self._run(dev.connect(), self.SESSION_TIMEOUT):
            raise LinkError('O console recusou a conexão: ' + (getattr(session, 'error', '') or 'sem detalhes.'))
        if not self._run(dev.async_wait_for_session(self.SESSION_TIMEOUT), self.SESSION_TIMEOUT + 5):
            raise LinkError('A sessão não ficou pronta no prazo: ' + (getattr(session, 'error', '') or 'sem detalhes.'))
        dev.controller.start()
        self.error = ''

    @property
    def running(self) -> bool:
        d = self.device
        return bool(d and d.session and d.connected and not d.session.is_stopped)

    def stop(self) -> None:
        d, self.device = self.device, None
        if d is not None:
            try:
                d.controller.stop()
                d.disconnect()
            except Exception as e:
                log.warning('erro ao encerrar a sessão Remote Play: %s', e)
        if self.receiver is not None:
            try:
                self.receiver.close()
            except Exception:
                pass
            self.receiver = None

    # ------------------------------------------------------------ mídia
    def video_frame(self):
        return self.receiver.latest_video if self.receiver else None

    def frame(self) -> media.Frame:
        f = self.video_frame()
        if f is None:
            return media.Frame(False, 'Nenhum quadro de vídeo recebido do console ainda.')
        return media.frame_from_luma(_luma(f), (f.width, f.height))

    def audio_track(self):
        return make_receiver_audio_track(self) if self.receiver else None

    def audio_peak(self, seconds: float = 1.5):
        if not self.receiver:
            return None, 'Console não conectado.'
        peak, end = 0.0, time.monotonic() + seconds
        seen = 0
        while time.monotonic() < end:
            for fr in self.receiver.audio_snapshot():
                seen += 1
                arr = fr.to_ndarray()
                if arr.size:
                    peak = max(peak, float(abs(arr).max()) / 32768.0)
            time.sleep(0.1)
        if not seen:
            return 0.0, 'O console ainda não enviou áudio.'
        peak = round(peak, 3)
        return peak, ('Áudio presente' if peak > 0.001 else 'Silêncio') + f' (pico {peak}).'

    def new_pad(self):
        if not self.device:
            raise GamepadUnavailable('Console não conectado: o controle só existe durante a sessão Remote Play.')
        return DirectPad(self.device.controller)

    def log_tail(self) -> str:
        s = self.device.session if self.device else None
        return (getattr(s, 'error', '') or self.error or '')[:600]


def _luma(frame):
    """Plano de brilho (Y) de um quadro yuv420p, ou cinza de um RGB."""
    arr = frame.to_ndarray()
    if frame.format.name.startswith('yuv'):
        return arr[: frame.height]
    import numpy as np
    return np.asarray(arr, dtype='float32').mean(axis=2)


def _make_receiver(AVReceiver):
    class FrameReceiver(AVReceiver):
        """Guarda o último quadro de vídeo (yuv420p, pronto para o WebRTC) e os quadros de áudio recentes."""

        def __init__(self):
            super().__init__()
            self.video_format = 'yuv420p'
            self.latest_video = None
            self.video_frames = 0
            self._audio = deque(maxlen=50)
            self._lock = threading.Lock()

        def handle_video(self, frame):
            self.latest_video = frame
            self.video_frames += 1

        def handle_audio(self, frame):
            with self._lock:
                self._audio.append(frame)

        def audio_snapshot(self):
            with self._lock:
                out = list(self._audio)
                self._audio.clear()
            return out

        def pop_audio(self):
            with self._lock:
                return self._audio.popleft() if self._audio else None

    return FrameReceiver()


def make_receiver_audio_track(link: DirectLink):
    """Áudio decodificado do console (s16) reempacotado em blocos de 20 ms para o WebRTC."""
    import fractions

    import av
    import numpy as np
    from aiortc import MediaStreamTrack

    RATE, BLOCK = 48000, 960

    class ReceiverAudioTrack(MediaStreamTrack):
        kind = 'audio'

        def __init__(self):
            super().__init__()
            self._buf = np.zeros((0, 2), dtype=np.int16)
            self._pts = 0
            self._next = None

        async def recv(self):
            if self._next is None:
                self._next = time.monotonic()
            self._next += BLOCK / RATE
            delay = self._next - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            rec = link.receiver
            while rec is not None and len(self._buf) < BLOCK:
                fr = rec.pop_audio()
                if fr is None:
                    break
                arr = fr.to_ndarray().reshape(-1, 2) if fr.layout.name == 'stereo' else np.repeat(fr.to_ndarray().reshape(-1, 1), 2, axis=1)
                self._buf = np.concatenate([self._buf, arr.astype(np.int16)])
            if len(self._buf) >= BLOCK:
                chunk, self._buf = self._buf[:BLOCK], self._buf[BLOCK:]
            else:
                chunk = np.zeros((BLOCK, 2), dtype=np.int16)        # silêncio enquanto não chega áudio
            if len(self._buf) > BLOCK * 10:
                self._buf = self._buf[-BLOCK * 2:]                   # atraso acumulado: descarta o excesso
            frame = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format='s16', layout='stereo')
            frame.sample_rate, frame.pts, frame.time_base = RATE, self._pts, fractions.Fraction(1, RATE)
            self._pts += BLOCK
            return frame

    return ReceiverAudioTrack()

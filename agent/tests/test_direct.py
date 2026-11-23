"""Remote Play direto sem console: o receptor é alimentado com vídeo H.264 e áudio Opus REAIS (gerados aqui),
exatamente como a sessão faria com os pacotes do PS4. Valida decodificação, checagem de imagem, faixa de áudio,
vídeo WebRTC até um cliente e o controle (mapeamento para a sessão Remote Play)."""
import asyncio
import fractions
import sys
from pathlib import Path

import pytest

av = pytest.importorskip('av')
np = pytest.importorskip('numpy')
pytest.importorskip('aiortc')

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient  # noqa: E402

from consoleagent import links  # noqa: E402
from consoleagent.config import AgentConfig  # noqa: E402
from consoleagent.links import DirectLink, DirectPad, _make_receiver  # noqa: E402
from consoleagent.runtime import Deps  # noqa: E402
from consoleagent.server import create_app  # noqa: E402
from pyremoteplay.receiver import AVReceiver  # noqa: E402

H = {'Authorization': 'Bearer tok'}


def h264_packets(n=12, w=640, h=360):
    enc = av.CodecContext.create('libx264', 'w')
    enc.width, enc.height, enc.pix_fmt, enc.time_base = w, h, 'yuv420p', fractions.Fraction(1, 30)
    enc.options = {'tune': 'zerolatency', 'preset': 'ultrafast'}
    out = []
    for i in range(n):
        img = np.zeros((h, w, 3), np.uint8)
        img[:, ::64] = 255
        img[:, : 40 * (i + 1)] = (160, 64, 255)
        f = av.VideoFrame.from_ndarray(img, format='rgb24').reformat(format='yuv420p')
        f.pts = i
        out += [bytes(p) for p in enc.encode(f)]
    return out + [bytes(p) for p in enc.encode(None)]


def opus_packets(n=10):
    enc = av.CodecContext.create('libopus', 'w')
    enc.sample_rate, enc.layout, enc.format = 48000, 'stereo', 's16'
    enc.open()
    out = []
    for i in range(n):
        tone = (np.sin(2 * np.pi * 440 * np.arange(960) / 48000) * 12000).astype(np.int16)
        f = av.AudioFrame.from_ndarray(np.repeat(tone, 2).reshape(1, -1), format='s16', layout='stereo')
        f.sample_rate, f.pts = 48000, i * 960
        out += [bytes(p) for p in enc.encode(f)]
    return out


class Session:
    """O suficiente da sessão Remote Play para o receptor (eventos + codec)."""
    codec = 'h264'
    events = type('E', (), {'emit': staticmethod(lambda *a, **k: None)})()


def fed_link():
    link = DirectLink()
    rec = _make_receiver(AVReceiver)
    rec._set_session(Session())
    rec._get_video_codec()
    header = bytes([2, 16]) + (48000).to_bytes(4, 'big') + (480).to_bytes(4, 'big') + (0).to_bytes(4, 'big')
    rec._get_audio_codec(header)
    for p in h264_packets():
        rec.handle_video_data(p)
    for p in opus_packets():
        rec.handle_audio_data(p)
    link.receiver = rec
    return link


def test_receptor_decodifica_video_e_audio_reais_e_checa_imagem():
    link = fed_link()
    v = link.video_frame()
    assert v is not None and (v.width, v.height) == (640, 360) and v.format.name == 'yuv420p'
    assert link.receiver.video_frames >= 10
    f = link.frame()
    assert f.ok and 'Imagem recebida do console' in f.message and f.std > 3
    frames = link.receiver.audio_snapshot()
    assert frames and frames[-1].format.name == 's16' and frames[-1].sample_rate == 48000


def test_conexao_sem_quadros_novos_e_considerada_morta():
    """PS4 em repouso: a biblioteca não percebe, mas sem quadro novo por >10 s o link deixa de estar 'running'."""
    import time
    link = fed_link()
    link.device = type('D', (), {'session': type('S', (), {'is_stopped': False})(), 'connected': True, 'controller': FakeController()})()
    assert link.running is True
    link.receiver.last_video_at = time.monotonic() - (DirectLink.STALE_SECONDS + 1)
    assert link.running is False and 'parou de enviar imagem' in link.log_tail()


def test_faixa_de_audio_reempacota_em_20ms():
    link = fed_link()

    async def run():
        track = link.audio_track()
        got = [await track.recv() for _ in range(5)]
        return got
    got = asyncio.run(run())
    assert all(fr.samples == 960 and fr.sample_rate == 48000 and fr.layout.name == 'stereo' for fr in got)
    assert any(np.abs(fr.to_ndarray()).max() > 1000 for fr in got)        # tom de 440 Hz chegou (não é silêncio)


class FakeController:
    def __init__(self):
        self.calls = []

    def button(self, name, action='tap', delay=0.1):
        self.calls.append(('button', name, action))

    def stick(self, stick, axis=None, value=None, point=None):
        self.calls.append(('stick', stick, axis, value, point))


def test_controle_direto_mapeia_botoes_eixos_e_bloqueia_ps():
    c = FakeController()
    pad = DirectPad(c)
    pad.apply({'type': 'button', 'name': 'cross', 'pressed': True})
    pad.apply({'type': 'button', 'name': 'cross', 'pressed': True})         # repetição ignorada
    pad.apply({'type': 'button', 'name': 'dpad_up', 'pressed': True})
    pad.apply({'type': 'axis', 'name': 'left_y', 'value': -2})              # limitado a -1
    with pytest.raises(PermissionError):
        pad.apply({'type': 'button', 'name': 'ps', 'pressed': True})
    pad.press('ps')                                                         # roteiro interno pode usar PS
    pad.reset()
    assert ('button', 'CROSS', 'press') in c.calls and c.calls.count(('button', 'CROSS', 'press')) == 1
    assert ('button', 'UP', 'press') in c.calls and ('stick', 'left', 'y', -1.0, None) in c.calls
    assert ('button', 'PS', 'tap') in c.calls
    assert ('button', 'CROSS', 'release') in c.calls and ('button', 'UP', 'release') in c.calls
    assert ('stick', 'left', None, None, (0.0, 0.0)) in c.calls


def test_pareamento_exige_pin_e_conta_psn(tmp_path, monkeypatch):
    monkeypatch.setattr(links, 'DATA_DIR', tmp_path)
    link = DirectLink()
    t = type('T', (), {'host': '192.168.0.20', 'psn_user': '', 'regist_key': '', 'mac': ''})()
    ok, msg = link.pair(t, '123')
    assert not ok and '8 dígitos' in msg
    ok, msg = link.pair(t, '12345678')
    assert not ok and '--psn-login' in msg                                  # nenhuma conta PSN vinculada ainda


def test_video_do_modo_direto_chega_ao_cliente_webrtc():
    """Quadros decodificados (yuv420p) vão direto para o WebRTC, sem captura de tela."""
    link = fed_link()
    link.device = type('D', (), {'session': type('S', (), {'is_stopped': False})(), 'connected': True,
                                 'controller': FakeController()})()
    cfg = AgentConfig(api_url='http://x', agent_token='a', api_to_agent_token='tok', ice_servers=[], stream_audio=True)
    with TestClient(create_app(cfg, deps=Deps(link=link, sleep=lambda s: None))) as client:
        r = client.post('/v1/consoles/c1/stream/start', json={'session_id': 's1'}, headers=H).json()
        assert r['ok'], r
        from aiortc import RTCPeerConnection, RTCSessionDescription

        async def run():
            pc = RTCPeerConnection()
            pc.addTransceiver('video', direction='recvonly')
            pc.addTransceiver('audio', direction='recvonly')
            got = asyncio.get_running_loop().create_future()

            @pc.on('track')
            def on_track(track):
                if track.kind != 'video':
                    return

                async def read():
                    for _ in range(10):
                        f = await track.recv()
                    if not got.done():
                        got.set_result(f.to_ndarray(format='rgb24'))
                asyncio.ensure_future(read())

            await pc.setLocalDescription(await pc.createOffer())
            offer = {'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp}
            res = await asyncio.to_thread(lambda: client.post('/v1/consoles/c1/stream/webrtc', json={'session_id': 's1', 'offer': offer}, headers=H).json())
            assert res['ok'] and 'áudio' in res['message'], res
            await pc.setRemoteDescription(RTCSessionDescription(**res['data']['answer']))
            arr = await asyncio.wait_for(got, 20)
            await pc.close()
            return arr
        arr = asyncio.run(run())
    assert arr.shape[:2] == (360, 640)
    purple = ((arr[:, :, 0] > 110) & (arr[:, :, 2] > 170) & (arr[:, :, 1] < 130)).mean()
    assert purple > 0.5, purple                                             # conteúdo do "console" chegou

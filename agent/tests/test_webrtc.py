"""WebRTC de ponta a ponta: janela REAL (no lugar do chiaki-ng) → agente → cliente WebRTC (no lugar do navegador).

Confere que os quadros recebidos trazem o conteúdo da janela (listras roxas), não uma tela preta.
Só roda no Windows com aiortc instalado.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

aiortc = pytest.importorskip('aiortc')
if sys.platform != 'win32':
    pytest.skip('captura de janela só no Windows', allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from consoleagent import media  # noqa: E402
from consoleagent.config import AgentConfig  # noqa: E402
from consoleagent.runtime import Deps  # noqa: E402
from consoleagent.server import create_app  # noqa: E402

TOKEN = 'tok'
H = {'Authorization': f'Bearer {TOKEN}'}
WINDOW = r'''
import os, sys, tkinter as tk
open(sys.argv[1], 'w').write(str(os.getpid()))
r = tk.Tk(); r.geometry('640x360+80+80'); r.attributes('-topmost', True)
c = tk.Canvas(r, width=640, height=360, bg='black', highlightthickness=0); c.pack()
for i in range(0, 640, 64): c.create_rectangle(i, 0, i + 32, 360, fill='#a040ff', width=0)
r.after(25000, r.destroy); r.mainloop()
'''


class WindowChiaki:
    """chiaki-ng substituído por uma janela real (o resto do caminho é o de produção)."""
    path, available, running = 'janela-de-teste', True, True

    def __init__(self, pid):
        self.pid = pid

    def registered(self, nick):
        return True

    def stop(self):
        pass


@pytest.fixture
def window():
    d = tempfile.mkdtemp()
    script, pidf = os.path.join(d, 'w.py'), os.path.join(d, 'pid')
    Path(script).write_text(WINDOW, encoding='utf-8')
    p = subprocess.Popen([sys.executable, script, pidf])
    for _ in range(100):
        if os.path.exists(pidf) and Path(pidf).read_text():
            break
        time.sleep(0.1)
    time.sleep(1.5)
    yield int(Path(pidf).read_text())
    p.terminate()


def test_video_da_janela_chega_ao_cliente_webrtc(window):
    chiaki = WindowChiaki(window)
    deps = Deps(chiaki=chiaki, make_pad=lambda: type('P', (), {'reset': lambda s: None, 'apply': lambda s, c: None})(),
                frame=media.frame, audio=lambda pid, s=1.5: (None, ''), sleep=lambda s: None)
    cfg = AgentConfig(api_url='http://x', agent_token='a', api_to_agent_token=TOKEN, ice_servers=[], stream_audio=False, video_max_width=640)
    with TestClient(create_app(cfg, deps=deps)) as client:     # mantém o laço do servidor vivo (como o uvicorn)
        _run(client)


def _run(client):
    r = client.post('/v1/consoles/c1/stream/start', json={'session_id': 's1'}, headers=H).json()
    assert r['ok'], r

    from aiortc import RTCPeerConnection, RTCSessionDescription

    async def run():
        pc = RTCPeerConnection()
        pc.addTransceiver('video', direction='recvonly')
        got = asyncio.get_running_loop().create_future()

        @pc.on('track')
        def on_track(track):
            async def read():
                for _ in range(15):                       # descarta os primeiros quadros (aquecimento do codificador)
                    f = await track.recv()
                if not got.done():
                    got.set_result(f.to_ndarray(format='rgb24'))
            asyncio.ensure_future(read())

        await pc.setLocalDescription(await pc.createOffer())
        offer = {'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp}
        # Sessão diferente da ativa: recusada
        bad = await asyncio.to_thread(lambda: client.post('/v1/consoles/c1/stream/webrtc', json={'session_id': 'outra', 'offer': offer}, headers=H))
        assert bad.status_code == 403
        res = await asyncio.to_thread(lambda: client.post('/v1/consoles/c1/stream/webrtc', json={'session_id': 's1', 'offer': offer}, headers=H).json())
        assert res['ok'], res
        await pc.setRemoteDescription(RTCSessionDescription(**res['data']['answer']))
        arr = await asyncio.wait_for(got, 20)
        await pc.close()
        return arr

    arr = asyncio.run(run())
    h, w, _ = arr.shape
    assert (w, h) == (640, 360), (w, h)
    purple = ((arr[:, :, 0] > 120) & (arr[:, :, 2] > 180) & (arr[:, :, 1] < 120)).mean()
    black = (arr.max(axis=2) < 40).mean()
    assert purple > 0.3 and black > 0.3, (purple, black)     # listras roxas e pretas da janela real
    m = client.post('/v1/consoles/c1/metrics', json={}, headers=H).json()
    assert m['metrics'].get('fps') or m['metrics'] == {}      # fps medido enquanto conectado (fechado aqui)

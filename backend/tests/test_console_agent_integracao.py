"""Integração real API ⇄ ConsoleAgent (agent/consoleagent): HTTP de verdade em 127.0.0.1, sem dublês no caminho."""
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from conftest import Api, admin_api, at

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'agent'))
from consoleagent import heartbeat as agent_hb  # noqa: E402
from consoleagent.config import AgentConfig  # noqa: E402
from consoleagent.server import create_app  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_api_fala_com_agente_real_e_heartbeat_marca_online(freeze):
    freeze(at(1, 10))
    api, _ = admin_api()
    port = _free_port()
    created = api.post('/admin/agents', json={'name': 'pc-ps4', 'host_name': 'pc', 'endpoint_url': f'http://127.0.0.1:{port}'})
    assert created.status_code == 201, created.text
    tokens = created.json()
    cfg = AgentConfig(api_url='http://testserver', agent_token=tokens['agent_token'], api_to_agent_token=tokens['api_to_agent_token'],
                      listen_port=port, discovery_timeout_seconds=0.3, chiaki_path='Z:/inexistente/chiaki.exe')

    # Descoberta sem console na rede de teste: o agente procura de verdade e responde "nenhum console"
    server = uvicorn.Server(uvicorn.Config(create_app(cfg, discover_fn=lambda h, p, t: []), host='127.0.0.1', port=port, log_level='error'))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        c = api.post('/admin/consoles', json={'code': 'PS4-56', 'name': 'PS4 nº 56', 'platform_code': 'PS4'}).json()
        r = api.put(f"/admin/consoles/{c['id']}/connection", json={'method': 'remote_play_chiaki', 'agent_id': tokens['id'],
                                                                  'internal_host': '192.168.0.20'})
        assert r.status_code == 200, r.text
        t = api.post(f"/admin/consoles/{c['id']}/tests/heartbeat").json()      # health no agente real
        assert t['result'] == 'passed' and 'ConsoleAgent' in t['message'] and t['simulated'] is False
        t = api.post(f"/admin/consoles/{c['id']}/tests/discover").json()
        assert t['result'] == 'failed' and 'Nenhum console respondeu' in t['message']
        t = api.post(f"/admin/consoles/{c['id']}/tests/connection").json()
        # Parte 2: o agente tenta conectar de verdade; sem chiaki-ng instalado, falha com o motivo real (nunca simula)
        assert t['result'] == 'failed' and 'chiaki-ng não encontrado' in t['message'] and t['simulated'] is False
    finally:
        server.should_exit = True
        th.join(5)

    # Heartbeat do agente → API (cliente httpx apontando para a API de teste)
    ok, msg = agent_hb.send_once(cfg, client=Api().c)
    assert ok, msg
    agents = {a['id']: a for a in api.get('/admin/agents').json()}
    assert agents[tokens['id']]['status'] == 'online' and agents[tokens['id']]['agent_version']
    bad = AgentConfig(api_url='http://testserver', agent_token='errado', api_to_agent_token='x')
    ok, msg = agent_hb.send_once(bad, client=Api().c)
    assert not ok and '401' in msg

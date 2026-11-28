"""Testes do ConsoleAgent (sem rede real: a descoberta é substituída por um dublê)."""
import json
import socket
import sys
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from consoleagent import discovery  # noqa: E402
from consoleagent.config import AgentConfig, ConfigError, load  # noqa: E402
from consoleagent.server import create_app  # noqa: E402

TOKEN = 'api-para-agente-123'
H = {'Authorization': f'Bearer {TOKEN}'}


def cfg(**kw) -> AgentConfig:
    return AgentConfig(api_url='http://127.0.0.1:8000', agent_token='agente-para-api', api_to_agent_token=TOKEN,
                       chiaki_path=kw.pop('chiaki_path', 'Z:/nao/existe/chiaki.exe'), **kw)


PS4_ON = (b'HTTP/1.1 200 Ok\nhost-id:AABBCCDDEEFF\nhost-type:PS4\nhost-name:PS4-118\nhost-request-port:997\n'
          b'device-discovery-protocol-version:00020020\nsystem-version:12020001\n')


def test_parse_resposta_ligado_e_repouso():
    on = discovery.parse_response(PS4_ON, '192.168.0.20')
    assert on and on.state == 'ligado' and on.host_name == 'PS4-118' and on.host_id == 'AABBCCDDEEFF'
    standby = discovery.parse_response(PS4_ON.replace(b'200 Ok', b'620 Server Standby'), '192.168.0.20')
    assert standby and standby.state == 'em repouso'
    assert discovery.parse_response(b'lixo qualquer', '1.2.3.4') is None
    assert discovery.search_message('PS4').startswith(b'SRCH * HTTP/1.1\ndevice-discovery-protocol-version:00020020')
    assert b'00030010' in discovery.search_message('PS5')


def test_descoberta_udp_real_contra_servidor_local():
    """Sobe um 'console falso' em UDP local e confirma o ciclo SRCH → resposta."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(('127.0.0.1', 0))
    port = srv.getsockname()[1]

    def responder():
        data, addr = srv.recvfrom(1024)
        assert data.startswith(b'SRCH')
        srv.sendto(PS4_ON, addr)

    t = threading.Thread(target=responder, daemon=True)
    t.start()
    found = discovery.discover('127.0.0.1', 'PS4', timeout=2.0, port=port, attempts=1)
    srv.close()
    assert found and found[0].host_name == 'PS4-118' and found[0].state == 'ligado'


def test_autenticacao_obrigatoria():
    c = TestClient(create_app(cfg()))
    assert c.post('/v1/consoles/x/health', json={}).status_code == 401
    assert c.post('/v1/consoles/x/health', json={}, headers={'Authorization': 'Bearer errado'}).status_code == 401
    r = c.post('/v1/consoles/x/health', json={}, headers=H)
    assert r.status_code == 200 and r.json()['ok'] is True and r.json()['simulated'] is False
    assert 'NÃO encontrado' in r.json()['message']


def test_heartbeat_psn_preserves_authentication_and_requires_a_ps4_account():
    client = TestClient(create_app(cfg()))
    base = '/v1/consoles/ps4/'
    body = {'method': 'remote_play_native', 'target': {'route': 'internet_psn'}}
    assert client.post(base + 'health', json=body).status_code == 401
    health = client.post(base + 'health', json=body, headers=H)
    assert health.status_code == 200 and health.json()['ok']
    assert health.json()['state'] is None
    connect = client.post(base + 'connect', json=body, headers=H)
    assert connect.status_code == 422 and connect.json()['code'] == 'psn_account_required'
    body['target']['platform_code'] = 'PS5'
    connect = client.post(base + 'connect', json=body, headers=H)
    assert connect.status_code == 501 and connect.json()['code'] == 'psn_transport_pending'


def test_descoberta_usa_rota_e_nao_finge():
    calls = []

    def fake(host, platform, timeout):
        calls.append((host, platform))
        return [discovery.parse_response(PS4_ON, host or '192.168.0.20')]

    c = TestClient(create_app(cfg(), discover_fn=fake))
    r = c.post('/v1/consoles/x/discover', json={'route': 'lan', 'host': '192.168.0.20', 'platform_code': 'PS4',
                                                 'console_identifier': 'PS4-118'}, headers=H).json()
    assert r['ok'] and 'PS4-118' in r['message'] and 'ligado' in r['message'] and calls[-1] == ('192.168.0.20', 'PS4')
    r = c.post('/v1/consoles/x/discover', json={'route': 'lan', 'host': None, 'platform_code': 'PS4'}, headers=H).json()
    assert r['ok'] and calls[-1] == (None, 'PS4')            # descoberta na LAN = broadcast
    # Rota PSN: não há descoberta pela internet; o agente informa o motivo real (chiaki-ng ausente neste teste)
    r = c.post('/v1/consoles/x/discover', json={'route': 'internet_psn', 'platform_code': 'PS4', 'console_identifier': 'PS4-118'}, headers=H)
    assert r.status_code == 200 and r.json()['ok'] is False and 'PSN' in r.json()['message']
    r = c.post('/v1/consoles/x/discover', json={'route': 'internet_port_forward', 'host': None}, headers=H).json()
    assert r['ok'] is False


def test_nada_encontrado_responde_falha():
    c = TestClient(create_app(cfg(), discover_fn=lambda h, p, t: []))
    r = c.post('/v1/consoles/x/discover', json={'route': 'lan', 'host': '192.168.0.99'}, headers=H).json()
    assert r['ok'] is False and 'Nenhum console respondeu' in r['message']


def test_sem_chiaki_conectar_falha_com_motivo_real():
    c = TestClient(create_app(cfg()))
    target = {'route': 'lan', 'host': '192.168.0.20', 'console_identifier': 'PS4-118'}
    poll = c.post('/v1/consoles/x/connect', json={'target': target, 'poll_only': True}, headers=H).json()
    assert poll['state'] == 'stopped'
    r = c.post('/v1/consoles/x/connect', json={'target': target},
               headers=H).json()
    assert r['ok'] is False and r['simulated'] is False and 'chiaki-ng não encontrado' in r['message']
    assert c.post('/v1/consoles/x/connect', json={'target': target, 'poll_only': True}, headers=H).json() == r
    r = c.post('/v1/consoles/x/test/video-audio', json={}, headers=H).json()
    assert r['ok'] is False and 'não conectado' in r['message']
    r = c.post('/v1/consoles/x/input', json={'session_id': 's1', 'command': {'type': 'button', 'name': 'cross'}}, headers=H)
    assert r.status_code == 403 and r.json()['code'] == 'input_revoked'


def test_metricas_sem_valores_inventados():
    r = TestClient(create_app(cfg())).post('/v1/consoles/x/metrics', json={}, headers=H)
    assert r.status_code == 200 and r.json() == {'metrics': {}}


def test_config(tmp_path):
    p = tmp_path / 'config.json'
    p.write_text(json.dumps({'api_url': 'http://x/', 'agent_token': 'COLE_AQUI', 'api_to_agent_token': 'b'}), encoding='utf-8')
    with pytest.raises(ConfigError):
        load(p)
    p.write_text(json.dumps({'api_url': 'http://x/', 'agent_token': 'a', 'api_to_agent_token': 'b', 'listen_port': 9000}), encoding='utf-8')
    c = load(p)
    assert c.api_url == 'http://x' and c.listen_port == 9000

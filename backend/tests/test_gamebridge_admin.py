"""Contratos GameBridge e administração de consoles/conexões/vínculos."""
import ast
import inspect
from pathlib import Path

import pytest

from app.core.db import one, tx
from app.gamebridge import AdapterError, ConsoleRef, ConsoleStreamingAdapter, get_adapter
from app.gamebridge.registry import _ADAPTERS
from conftest import admin_api, at, login, make_user, pay, reserve

CONTRACT = ['discover_console', 'pair_console', 'connect', 'start_stream', 'stop_stream', 'get_stream_status',
            'get_metrics', 'send_input', 'revoke_input', 'disconnect', 'health_check']


@pytest.mark.parametrize('method', list(_ADAPTERS))
def test_todos_adaptadores_implementam_o_contrato(method):
    a = get_adapter(method)
    assert isinstance(a, ConsoleStreamingAdapter)
    for name in CONTRACT:
        assert callable(getattr(a, name)) and not getattr(getattr(type(a), name), '__isabstractmethod__', False)
    assert a.operational is False   # nenhum adaptador é declarado operacional sem hardware validado


def test_console_ref_usa_id_do_console(world):
    from app.services.consoles import console_ref
    with tx() as conn:
        ref = console_ref(conn, world['console']['id'])
    assert ref.console_id == str(world['console']['id']) and ref.method == 'simulated' and ref.platform_code == 'PS5'


def test_contrato_simulador_sessao_e_revogacao():
    a = get_adapter('simulated')
    ref = ConsoleRef('c1', 'PS5', 'simulated')
    assert a.connect(ref).simulated
    a.start_stream(ref, 's1')
    assert a.send_input(ref, 's1', {'type': 'button', 'name': 'cross'}).ok
    with pytest.raises(AdapterError):
        a.start_stream(ref, 's2')        # um controlador por console
    a.revoke_input(ref, 's1')
    with pytest.raises(AdapterError) as e:
        a.send_input(ref, 's1', {'type': 'button', 'name': 'cross'})
    assert e.value.code == 'input_revoked'
    m = a.get_metrics(ref, 's1')
    assert m.simulated and m.fps is None and m.rtt_ms is None     # nunca fabrica métricas


def test_adaptadores_de_hardware_recusam_sem_configuracao():
    with pytest.raises(AdapterError) as e:
        get_adapter('remote_play_chiaki').connect(ConsoleRef('c', 'PS5', 'remote_play_chiaki'))
    assert e.value.code == 'not_configured'
    with pytest.raises(AdapterError) as e:
        get_adapter('remote_play_chiaki').connect(ConsoleRef('c', 'SWITCH', 'remote_play_chiaki', 'https://a', 't'))
    assert e.value.code == 'unsupported_platform'
    with pytest.raises(AdapterError) as e:
        get_adapter('hdmi_capture').connect(ConsoleRef('c', 'PS5', 'hdmi_capture', 'https://a', 't', capture_device_identifier='cap'))
    assert 'controle separado' in e.value.message
    with pytest.raises(AdapterError) as e:
        get_adapter('native_remote_play').connect(ConsoleRef('c', 'PS5', 'native_remote_play'))
    assert e.value.code == 'not_implemented'


def test_servicos_de_negocio_nao_importam_adaptadores_concretos():
    root = Path(__file__).resolve().parents[1] / 'app'
    for f in list((root / 'services').glob('*.py')) + list((root / 'routers').glob('*.py')):
        tree = ast.parse(f.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(x in node.module for x in ('simulated', 'agent_client', 'chiaki')), f'{f.name} importa {node.module}'


def _new_console(api, code='PS5-09', platform='PS5'):
    r = api.post('/admin/consoles', json={'code': code, 'name': f'Console {code}', 'platform_code': platform})
    assert r.status_code == 201, r.text
    return r.json()


def test_hdmi_exige_capturadora_e_controle_separado_e_canal_exclusivo(freeze):
    freeze(at(1, 10))
    api, _ = admin_api()
    c1, c2 = _new_console(api, 'PS5-10'), _new_console(api, 'PS5-11')
    ag = api.post('/admin/agents', json={'name': 'pc-01', 'host_name': 'pc01', 'endpoint_url': 'https://agente.local'}).json()
    assert 'agent_token' in ag
    r = api.put(f"/admin/consoles/{c1['id']}/connection", json={'method': 'hdmi_capture', 'agent_id': ag['id']})
    assert r.status_code == 422 and {'capture_device_id', 'control_adapter_id'} <= set(r.json()['fields'])
    cap = api.post('/admin/capture-devices', json={'agent_id': ag['id'], 'manufacturer': 'X', 'model': 'Y', 'device_identifier': 'usb-1'}).json()
    ctl = api.post('/admin/control-adapters', json={'agent_id': ag['id'], 'adapter_type': 'usb_controller_interface',
                                                    'identifier': 'ctl-1', 'authorized': True}).json()
    r = api.put(f"/admin/consoles/{c1['id']}/connection", json={'method': 'hdmi_capture', 'agent_id': ag['id'], 'capture_device_id': cap['id']})
    assert r.status_code == 422 and 'control_adapter_id' in r.json()['fields']
    ok = api.put(f"/admin/consoles/{c1['id']}/connection", json={'method': 'hdmi_capture', 'agent_id': ag['id'],
                                                                 'capture_device_id': cap['id'], 'control_adapter_id': ctl['id']})
    assert ok.status_code == 200, ok.text
    r = api.put(f"/admin/consoles/{c2['id']}/connection", json={'method': 'hdmi_capture', 'agent_id': ag['id'],
                                                               'capture_device_id': cap['id'], 'control_adapter_id': ctl['id']})
    assert r.status_code == 422 and 'Já em uso' in str(r.json()['fields'])
    # Teste real falha (agente inacessível) e o console continua sem publicação
    t = api.post(f"/admin/consoles/{c1['id']}/tests/connection").json()
    assert t['result'] == 'failed' and t['simulated'] is False
    assert api.post(f"/admin/consoles/{c1['id']}/publish").status_code == 409


def test_remote_play_nao_aplicavel_a_xbox_e_matriz(freeze):
    freeze(at(1, 10))
    api, _ = admin_api()
    x = _new_console(api, 'XBOX-09', 'XBOX_SERIES')
    ag = api.post('/admin/agents', json={'name': 'pc-02', 'host_name': 'pc02'}).json()
    r = api.put(f"/admin/consoles/{x['id']}/connection", json={'method': 'remote_play_chiaki', 'agent_id': ag['id'], 'internal_host': '192.168.0.5'})
    assert r.status_code == 422 and 'method' in r.json()['fields']
    m = {i['method']: i for i in api.get('/admin/connection-methods?platform=XBOX_SERIES').json()}
    assert m['remote_play_chiaki']['applicable'] is False and m['hdmi_capture']['applicable'] is True


def test_validacao_simulada_publica_e_troca_de_metodo_bloqueada_com_reserva(world, freeze):
    freeze(at(2, 8))
    api, _ = admin_api()
    c = _new_console(api, 'PS5-12')
    sim = api.post('/admin/agents', json={'name': 'sim-x', 'host_name': 'sim', 'is_simulated': True}).json()
    assert api.put(f"/admin/consoles/{c['id']}/connection", json={'method': 'simulated', 'agent_id': sim['id']}).status_code == 200
    assert api.post(f"/admin/consoles/{c['id']}/publish").status_code == 409          # ainda não validado
    for t in ('connection', 'video_audio', 'controls', 'heartbeat'):
        res = api.post(f"/admin/consoles/{c['id']}/tests/{t}").json()
        assert res['result'] == 'passed' and res['simulated'] is True
    assert api.post(f"/admin/consoles/{c['id']}/publish").status_code == 200
    # console do cenário tem reserva paga → troca de método bloqueada
    u = login(make_user())
    r = reserve(u, world, 30, mode='scheduled', start_at=at(2, 9)).json()
    pay(u, r['id'])
    res = api.put(f"/admin/consoles/{world['console']['id']}/connection", json={'method': 'unconfigured'})
    assert res.status_code == 409 and res.json()['code'] == 'affected_reservations'
    # troca de adaptador não altera jogo/fila/reserva (independência do negócio)
    with tx() as conn:
        before = one(conn, 'select starts_at, ends_at, status, game_id from reservations where id=%s', (r['id'],))
    assert before['status'] == 'confirmed'


def test_vinculo_sobreposto_plataforma_e_recorrencia(world, freeze):
    freeze(at(1, 10))
    api, _ = admin_api()
    g = api.post('/admin/games', json={'slug': 'god-of-war', 'title': 'God of War', 'platform_codes': ['PS5'], 'genres': ['Ação']}).json()
    cid = str(world['console']['id'])
    r = api.post('/admin/assignments', json={'console_id': cid, 'game_id': g['id'], 'starts_at': at(2, 9).isoformat(), 'ends_at': at(2, 11).isoformat()})
    assert r.status_code == 409 and r.json()['code'] == 'overlap'               # conflita com GTA 08–10
    r = api.post('/admin/assignments', json={'console_id': cid, 'game_id': g['id'], 'starts_at': at(2, 10).isoformat(),
                                            'ends_at': at(2, 12).isoformat(), 'repeat': 'daily', 'occurrences': 3})
    assert r.status_code == 201 and len(r.json()) == 3                          # jogos distintos em horários distintos
    sw = api.post('/admin/games', json={'slug': 'zelda', 'title': 'Zelda', 'platform_codes': ['SWITCH']}).json()
    r = api.post('/admin/assignments', json={'console_id': cid, 'game_id': sw['id'], 'starts_at': at(3, 13).isoformat(), 'ends_at': at(3, 14).isoformat()})
    assert r.status_code == 422 and r.json()['code'] == 'platform_mismatch'


def test_alterar_janela_com_reserva_paga_exige_resolucao(world, freeze):
    freeze(at(2, 8))
    api, _ = admin_api()
    u = login(make_user())
    r = reserve(u, world, 30, mode='scheduled', start_at=at(2, 9, 30)).json()
    pay(u, r['id'])
    aid = str(world['assignment']['id'])
    res = api.patch(f'/admin/assignments/{aid}', json={'ends_at': at(2, 9, 45).isoformat(), 'reason': 'Ajuste'})
    assert res.status_code == 409 and res.json()['reservations'][0]['code'] == r['code']
    res = api.patch(f'/admin/assignments/{aid}', json={'ends_at': at(2, 9, 45).isoformat(), 'reason': 'Console reservado para evento',
                                                       'resolution': 'cancel_and_refund'})
    assert res.status_code == 200
    v = u.get(f"/reservations/{r['id']}").json()
    assert v['status'] == 'cancelled'
    assert u.get('/me/payments').json()[0]['refunded_cents'] == 5000
    assert any('Alteração na sua reserva' in n['title'] for n in u.get('/me/notifications').json())


def test_falha_de_heartbeat_marca_console_offline_e_cria_incidente(world, freeze):
    from app import worker
    freeze(at(2, 8))
    _ADAPTERS['simulated'].fail_health.add(str(world['console']['id']))
    worker.tick()
    with tx() as conn:
        assert one(conn, 'select status from consoles where id=%s', (world['console']['id'],))['status'] == 'offline'
        assert one(conn, "select count(*) n from service_incidents where kind='agent_offline'")['n'] == 1
    r = reserve(login(make_user()), world, 10)
    assert r.status_code == 409                       # console offline não vende
    _ADAPTERS['simulated'].fail_health.clear()
    worker.tick()
    with tx() as conn:
        assert one(conn, 'select status from consoles where id=%s', (world['console']['id'],))['status'] == 'online'


def test_relatorio_csv_neutraliza_formulas_e_kpis(world, freeze):
    freeze(at(2, 8))
    api, _ = admin_api()
    u = login(make_user())
    r = reserve(u, world, 30).json()
    pay(u, r['id'])
    k = api.get('/admin/overview').json()['kpis']
    assert k['revenue_today'] == 5000 and k['queue_waiting'] + k['sessions_active'] >= 0
    csv = api.get('/admin/reports/export.csv', params={'kind': 'payments', 'date_from': at(1, 0, month=1).isoformat(), 'date_to': at(31, 0).isoformat()})
    assert csv.status_code == 200 and 'amount_cents' in csv.text


def test_publicacao_bloqueada_no_banco_sem_validacao(world):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        with tx() as conn:
            conn.execute('update console_connection_configs set control_validated_at=null, validated_at=null')
            conn.execute('update consoles set is_published=false')
            conn.execute('update consoles set is_published=true')


def test_rota_de_rede_remote_play_pela_internet(freeze):
    """PS4 em outra rede: via PSN (sem portas) ou por portas abertas (exige IP público/DDNS)."""
    freeze(at(1, 10))
    api, _ = admin_api()
    c = _new_console(api, 'PS4-09', 'PS4')
    ag = api.post('/admin/agents', json={'name': 'pc-remoto', 'host_name': 'pcr'}).json()
    url = f"/admin/consoles/{c['id']}/connection"
    base = {'method': 'remote_play_chiaki', 'agent_id': ag['id']}
    r = api.put(url, json={**base, 'network_route': 'internet_port_forward'})
    assert r.status_code == 422 and 'public_host' in r.json()['fields']
    r = api.put(url, json={**base, 'network_route': 'internet_psn'})
    assert r.status_code == 422 and 'console_identifier' in r.json()['fields']
    r = api.put(url, json={**base, 'network_route': 'internet_port_forward', 'public_host': 'meuconsole.ddns.net', 'public_port': 9295,
                           'discovery_mode': 'lan_discovery'})
    assert r.status_code == 200, r.text
    cfg = r.json()['connection']
    assert cfg['network_route'] == 'internet_port_forward' and cfg['public_host'] == 'meuconsole.ddns.net'
    assert cfg['discovery_mode'] == 'manual'           # descoberta na LAN não se aplica pela internet
    r = api.put(url, json={**base, 'network_route': 'internet_psn', 'console_identifier': 'PS4-casa-vo'})
    assert r.status_code == 200 and r.json()['connection']['public_host'] is None
    r = api.put(url, json={'method': 'simulated', 'network_route': 'internet_psn'})
    assert r.status_code == 422 and 'network_route' in r.json()['fields']


def test_remote_play_direto_so_rede_local_com_ip_e_identificacao(freeze):
    """Remote Play direto (vários consoles por PC): exige agente, IP local e identificação; não aceita internet."""
    freeze(at(1, 10))
    api, _ = admin_api()
    c = _new_console(api, 'PS4-31', 'PS4')
    sw = _new_console(api, 'SW-31', 'SWITCH')
    ag = api.post('/admin/agents', json={'name': 'pc-loja', 'host_name': 'pcl'}).json()
    url = f"/admin/consoles/{c['id']}/connection"
    base = {'method': 'remote_play_direct', 'agent_id': ag['id']}
    r = api.put(url, json=base)
    assert r.status_code == 422 and {'internal_host', 'console_identifier'} <= set(r.json()['fields'])
    r = api.put(url, json={**base, 'internal_host': '192.168.0.31', 'console_identifier': 'PS4-31', 'network_route': 'internet_psn'})
    assert r.status_code == 422 and 'rede local' in r.json()['fields']['network_route']
    r = api.put(url, json={**base, 'internal_host': '192.168.0.31', 'console_identifier': 'PS4-31'})
    assert r.status_code == 200, r.text
    assert r.json()['connection']['method'] == 'remote_play_direct'                 # aceito pelo banco (migração 011)
    r = api.put(f"/admin/consoles/{sw['id']}/connection", json={**base, 'internal_host': '192.168.0.32', 'console_identifier': 'SW-31'})
    assert r.status_code == 422 and 'method' in r.json()['fields']                  # não aplicável a Switch


def test_limpar_historico_de_testes_mantem_validacoes(freeze):
    freeze(at(1, 10))
    api, _ = admin_api()
    c = _new_console(api, 'PS4-41', 'PS4')
    ag = api.post('/admin/agents', json={'name': 'sim', 'host_name': 'sim', 'is_simulated': True}).json()
    assert api.put(f"/admin/consoles/{c['id']}/connection", json={'method': 'simulated', 'agent_id': ag['id']}).status_code == 200
    for t in ('heartbeat', 'discover'):
        api.post(f"/admin/consoles/{c['id']}/tests/{t}")
    before = api.get(f"/admin/consoles/{c['id']}").json()
    assert len(before['tests']) == 2 and before['connection']['heartbeat_validated_at']
    r = api.delete(f"/admin/consoles/{c['id']}/tests")
    assert r.status_code == 200 and r.json()['removed'] == 2
    after = api.get(f"/admin/consoles/{c['id']}").json()
    assert after['tests'] == [] and after['connection']['heartbeat_validated_at'] == before['connection']['heartbeat_validated_at']
    assert api.delete('/admin/consoles/00000000-0000-0000-0000-000000000000/tests').status_code == 404


def test_excluir_console_bloqueia_com_reserva_e_libera_codigo(world, freeze):
    freeze(at(2, 8, 0))
    api, _ = admin_api()
    cid = str(world['console']['id'])
    user = login(make_user('excl_user'))
    rid = reserve(user, world, 10).json()['id']
    assert pay(user, rid).status_code == 200
    r = api.delete(f'/admin/consoles/{cid}')
    assert r.status_code == 409 and r.json()['code'] == 'has_reservations'
    # Sem reservas: exclui e o código pode ser reutilizado
    c = _new_console(api, 'PS4-77', 'PS4')
    assert api.delete(f"/admin/consoles/{c['id']}").status_code == 200
    assert api.delete(f"/admin/consoles/{c['id']}").status_code == 404
    assert not any(x['id'] == c['id'] for x in api.get('/admin/consoles').json())
    assert _new_console(api, 'PS4-77', 'PS4')['id'] != c['id']


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def _agent_console(api, monkeypatch, replies):
    """Console PS4 com Remote Play apontando para um agente local cujas respostas são controladas pelo teste."""
    import app.gamebridge.agent_client as ac
    ag = api.post('/admin/agents', json={'name': 'pc-local', 'host_name': 'pc', 'endpoint_url': 'http://127.0.0.1:8765'})
    assert ag.status_code == 201, ag.text
    c = _new_console(api, 'PS4-55', 'PS4')
    r = api.put(f"/admin/consoles/{c['id']}/connection", json={'method': 'remote_play_chiaki', 'agent_id': ag.json()['id'],
                                                              'internal_host': '192.168.0.20'})
    assert r.status_code == 200, r.text
    seen = []

    def fake_post(url, json=None, headers=None, timeout=None):
        action = url.split(f"/v1/consoles/{c['id']}/", 1)[1]
        seen.append((action, headers.get('Authorization', '').startswith('Bearer ')))
        return _Resp(*replies.get(action, (501, {'code': 'not_implemented', 'message': 'Parte 2'})))

    monkeypatch.setattr(ac.httpx, 'post', fake_post)
    return c, seen


def test_agente_local_http_em_dev_e_https_em_producao(freeze, monkeypatch):
    from app.config import settings as s
    freeze(at(1, 10))
    api, _ = admin_api()
    assert api.post('/admin/agents', json={'name': 'a1', 'host_name': 'h', 'endpoint_url': 'http://127.0.0.1:8765'}).status_code == 201
    assert api.post('/admin/agents', json={'name': 'a2', 'host_name': 'h', 'endpoint_url': 'http://192.168.0.5:8765'}).status_code == 422
    monkeypatch.setattr(s, 'env', 'production')
    assert api.post('/admin/agents', json={'name': 'a3', 'host_name': 'h', 'endpoint_url': 'http://127.0.0.1:8765'}).status_code == 422


def test_agente_real_descobre_e_parte2_fica_nao_disponivel(freeze, monkeypatch):
    freeze(at(1, 10))
    api, _ = admin_api()
    c, seen = _agent_console(api, monkeypatch, {
        'discover': (200, {'ok': True, 'simulated': False, 'message': 'PS4-118 encontrado: ligado', 'state': 'idle', 'data': {}}),
        'health': (200, {'ok': True, 'simulated': False, 'message': 'ConsoleAgent online', 'state': None, 'data': {}}),
    })
    t = api.post(f"/admin/consoles/{c['id']}/tests/discover").json()
    assert t['result'] == 'passed' and 'PS4-118' in t['message'] and t['simulated'] is False
    t = api.post(f"/admin/consoles/{c['id']}/tests/video_audio").json()
    assert t['result'] == 'not_available' and 'Parte 2' in t['message']
    t = api.post(f"/admin/consoles/{c['id']}/tests/heartbeat").json()
    assert t['result'] == 'passed'
    assert all(auth for _, auth in seen)
    assert api.post(f"/admin/consoles/{c['id']}/publish").status_code == 409


def test_resposta_simulada_de_agente_real_nao_valida_console(freeze, monkeypatch):
    freeze(at(1, 10))
    api, _ = admin_api()
    fake_ok = (200, {'ok': True, 'simulated': True, 'message': 'fingindo', 'state': 'idle', 'data': {}})
    c, _ = _agent_console(api, monkeypatch, {'test/video-audio': fake_ok, 'test/controls': fake_ok, 'health': fake_ok, 'connect': fake_ok})
    for t in ('video_audio', 'controls', 'heartbeat', 'connection'):
        r = api.post(f"/admin/consoles/{c['id']}/tests/{t}").json()
        assert r['result'] == 'not_available' and r['simulated'] is True and 'SIMULADA' in r['message']
    cfg = api.get(f"/admin/consoles/{c['id']}").json()['connection']
    assert not any(cfg[k] for k in ('video_validated_at', 'audio_validated_at', 'control_validated_at', 'heartbeat_validated_at'))
    assert api.post(f"/admin/consoles/{c['id']}/publish").status_code == 409

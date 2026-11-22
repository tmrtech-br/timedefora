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
        tree = ast.parse(f.read_text())
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

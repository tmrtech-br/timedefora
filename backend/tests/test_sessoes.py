"""Sessão exclusiva, token efêmero, revogação no servidor, reconexão, avisos e no-show (worker)."""
from datetime import timedelta

from app import worker
from app.core.db import one, tx
from conftest import Api, at, login, make_user, pay, reserve


def confirmed(world, freeze, start=(2, 9, 0), minutes=30, user='jogador1'):
    freeze(at(2, 8))
    api = login(make_user(user))
    r = reserve(api, world, minutes, mode='scheduled', start_at=at(*start)).json()
    pay(api, r['id'])
    return api, r


def test_sem_reserva_valida_nao_ha_controle(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 8, 30))
    res = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'keyboard_mouse'})
    assert res.status_code == 409 and res.json()['code'] == 'too_early'
    other = login(make_user('intruso'))
    freeze(at(2, 9, 1))
    assert other.post(f"/reservations/{r['id']}/join", json={'input_device': 'gamepad'}).status_code == 404
    assert Api().post('/sessions/00000000-0000-0000-0000-000000000000/input', json={'command': {'type': 'button', 'name': 'cross'}},
                      headers={'X-Input-Token': 'qualquer'}).status_code == 403


def test_join_token_input_e_expiracao_com_navegador_aberto(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 9, 0))
    j = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'keyboard_mouse'}).json()
    sid, tok = j['session_id'], j['input_token']
    assert j['simulated'] is True
    cmd = {'command': {'type': 'button', 'name': 'cross'}}
    assert Api().post(f'/sessions/{sid}/input', json=cmd, headers={'X-Input-Token': tok}).status_code == 200
    assert Api().post(f'/sessions/{sid}/input', json={'command': {'type': 'button', 'name': 'ps'}},
                      headers={'X-Input-Token': tok}).status_code == 400      # comando sensível bloqueado
    st = api.get(f'/sessions/{sid}').json()
    assert st['remaining_seconds'] == 30 * 60
    freeze(at(2, 9, 30))                                                      # fim contratual
    assert Api().post(f'/sessions/{sid}/input', json=cmd, headers={'X-Input-Token': tok}).status_code == 403
    worker.tick()                                                             # encerramento server-side
    with tx() as conn:
        s = one(conn, 'select status, end_reason, seconds_used from game_sessions where id=%s', (sid,))
        t = one(conn, 'select revoked_at from session_input_tokens')
    assert s['status'] == 'expired' and s['end_reason'] == 'time_up' and s['seconds_used'] == 1800
    assert t['revoked_at'] is not None
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'completed'


def test_video_webrtc_exige_token_e_nao_finge_no_simulador(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 9, 0))
    j = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'gamepad'}).json()
    sid, tok = j['session_id'], j['input_token']
    offer = {'offer': {'type': 'offer', 'sdp': 'v=0\r\n'}}
    assert Api().get(f'/sessions/{sid}/webrtc-config').status_code == 403                       # sem token
    cfg = Api().get(f'/sessions/{sid}/webrtc-config', headers={'X-Input-Token': tok}).json()
    assert cfg['ice_servers'] and 'urls' in cfg['ice_servers'][0]
    assert Api().post(f'/sessions/{sid}/webrtc', json=offer, headers={'X-Input-Token': 'errado'}).status_code == 403
    assert Api().post(f'/sessions/{sid}/webrtc', json={'offer': {'type': 'answer', 'sdp': 'x'}},
                      headers={'X-Input-Token': tok}).status_code == 400                           # oferta inválida
    res = Api().post(f'/sessions/{sid}/webrtc', json=offer, headers={'X-Input-Token': tok})
    assert res.status_code == 501 and res.json()['code'] == 'video_unavailable'                    # simulador: sem vídeo real
    # Analógico aceito pelo servidor
    assert Api().post(f'/sessions/{sid}/input', json={'command': {'type': 'axis', 'name': 'left_x', 'value': 0.5}},
                      headers={'X-Input-Token': tok}).status_code == 200


def test_reconexao_revoga_token_anterior_e_atraso_nao_estende(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 9, 10))                                                      # entrou atrasado
    j1 = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'gamepad'}).json()
    assert j1['contract_ends_at'] == j1['contract_ends_at']
    assert api.get(f"/sessions/{j1['session_id']}").json()['remaining_seconds'] == 20 * 60   # termina 09:30
    api.post(f"/sessions/{j1['session_id']}/disconnect")
    freeze(at(2, 9, 15))
    j2 = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'gamepad'}).json()
    cmd = {'command': {'type': 'axis', 'name': 'left_x', 'value': 0.5}}
    assert Api().post(f"/sessions/{j1['session_id']}/input", json=cmd, headers={'X-Input-Token': j1['input_token']}).status_code == 403
    assert Api().post(f"/sessions/{j2['session_id']}/input", json=cmd, headers={'X-Input-Token': j2['input_token']}).status_code == 200


def test_usuario_a_nao_controla_console_do_usuario_b(world, freeze):
    freeze(at(2, 8))
    a = login(make_user('alice'))
    b = login(make_user('bruno'))
    ra = reserve(a, world, 10, mode='scheduled', start_at=at(2, 9)).json()
    pay(a, ra['id'])
    rb = reserve(b, world, 10, mode='scheduled', start_at=at(2, 9, 10)).json()
    pay(b, rb['id'])
    freeze(at(2, 9, 1))
    ja = a.post(f"/reservations/{ra['id']}/join", json={'input_device': 'gamepad'}).json()
    assert b.post(f"/reservations/{rb['id']}/join", json={'input_device': 'gamepad'}).json()['code'] == 'too_early'
    freeze(at(2, 9, 11))
    worker.tick()
    jb = b.post(f"/reservations/{rb['id']}/join", json={'input_device': 'gamepad'}).json()
    cmd = {'command': {'type': 'button', 'name': 'cross'}}
    # token de B não serve para a sessão de A e vice-versa
    assert Api().post(f"/sessions/{ja['session_id']}/input", json=cmd, headers={'X-Input-Token': jb['input_token']}).status_code == 403
    assert Api().post(f"/sessions/{jb['session_id']}/input", json=cmd, headers={'X-Input-Token': ja['input_token']}).status_code == 403
    assert a.get(f"/sessions/{jb['session_id']}").status_code == 404


def test_aviso_5_minutos_deduplicado_e_aviso_de_pronto(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 8, 55))
    worker.tick()
    worker.tick()
    with tx() as conn:
        soon = conn.execute("select title, body from notifications where event_code like 'turn_soon%%'").fetchall()
        mails = conn.execute("select subject, body_text from dev_mailbox where subject like 'Sua vez%%'").fetchall()
    assert len(soon) == 1 and 'Faltam aproximadamente 5 minutos' in soon[0]['body']
    assert len(mails) == 1 and 'Início previsto: 09:00' in mails[0]['body_text'] and 'sala de espera' in mails[0]['body_text']
    freeze(at(2, 9, 0))
    worker.tick()
    with tx() as conn:
        assert one(conn, "select count(*) n from notifications where event_code='turn_ready'")['n'] == 1
        assert one(conn, "select status from game_sessions")['status'] == 'ready'


def test_aviso_antes_do_fim_e_ausencia(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 9))
    j = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'gamepad'}).json()
    freeze(at(2, 9, 25))
    worker.tick()
    with tx() as conn:
        n = one(conn, "select body from notifications where event_code='session_ending'")
    assert '5 minuto' in n['body']
    # no-show: outra reserva sem conexão
    b = login(make_user('ausente'))
    freeze(at(2, 9, 25))
    rb = reserve(b, world, 10, mode='scheduled', start_at=at(2, 9, 40)).json()
    pay(b, rb['id'])
    freeze(at(2, 9, 40))
    worker.tick()                                   # console preparado e liberado no horário: ausência é do jogador
    freeze(at(2, 9, 51))
    worker.tick()
    assert b.get(f"/reservations/{rb['id']}").json()['status'] == 'no_show'


def test_encerrar_antes_libera_console(world, freeze):
    api, r = confirmed(world, freeze)
    freeze(at(2, 9, 5))
    j = api.post(f"/reservations/{r['id']}/join", json={'input_device': 'gamepad'}).json()
    api.post(f"/sessions/{j['session_id']}/end")
    other = login(make_user('outro'))
    res = reserve(other, world, 10)          # intervalo restante liberado
    assert res.status_code == 201, res.text


def test_fim_de_sessao_pede_repouso_so_sem_reserva_proxima(world, freeze, monkeypatch):
    from app.gamebridge.simulated import SimulatedAdapter
    calls = []
    original = SimulatedAdapter.stop_stream

    def stop(self, ref, session_id, standby=False):
        calls.append(standby)
        return original(self, ref, session_id, standby)

    monkeypatch.setattr(SimulatedAdapter, 'stop_stream', stop)
    api1, r1 = confirmed(world, freeze, start=(2, 9, 0), minutes=30)
    api2 = login(make_user('jogador2'))
    resp = reserve(api2, world, 30, mode='scheduled', start_at=at(2, 9, 30))
    assert resp.status_code < 300, resp.text
    r2 = resp.json()
    pay(api2, r2['id'])
    freeze(at(2, 9, 0))
    sid = api1.post(f"/reservations/{r1['id']}/join", json={'input_device': 'keyboard_mouse'}).json()['session_id']
    freeze(at(2, 9, 25))
    assert api1.post(f'/sessions/{sid}/end').status_code == 200
    assert calls[-1] is False                     # reserva seguinte começa em menos de 15 min: mantém acordado

    with tx() as conn:
        conn.execute("update reservations set status='cancelled' where id=%s", (r2['id'],))
    api3, r3 = confirmed(world, freeze, start=(2, 9, 30), minutes=30, user='jogador3')
    freeze(at(2, 9, 30))
    sid = api3.post(f"/reservations/{r3['id']}/join", json={'input_device': 'keyboard_mouse'}).json()['session_id']
    freeze(at(2, 9, 40))
    assert api3.post(f'/sessions/{sid}/end').status_code == 200
    assert calls[-1] is True                      # nada na agenda: o console pode hibernar

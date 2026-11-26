"""Preparação do console antes da sessão e bloqueio do Share."""
from datetime import timedelta

from app import worker
from app.core.db import one, tx
from app.gamebridge.registry import _ADAPTERS

from conftest import Api, admin_api, at, login, make_user, pay, reserve


def _paid(world, freeze, when):
    freeze(when)
    user = login(make_user('prep_user'))
    rid = reserve(user, world, 10).json()['id']
    assert pay(user, rid).status_code == 200
    return user, rid


def _row(sql, *args):
    with tx() as conn:
        return one(conn, sql, args)


def test_worker_prepara_e_libera_sessao(world, freeze):
    user, rid = _paid(world, freeze, at(2, 8, 0))
    worker.tick()
    p = _row('select * from console_preparations where reservation_id=%s', rid)
    assert p and p['status'] == 'ready' and p['simulated'] is True
    assert _row('select status from game_sessions where reservation_id=%s', rid)['status'] == 'ready'
    assert user.get('/me/queues').json()[0]['queue']['status'] == 'next'
    assert user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'}).status_code == 200
    assert user.get('/me/queues').json()[0]['queue']['status'] == 'playing'


def test_falha_na_preparacao_nao_consome_tempo_e_avisa_equipe(world, freeze):
    admin, adm_user = admin_api('equipe_prep')
    _ADAPTERS['simulated'].fail_prepare.add(str(world['console']['id']))
    user, rid = _paid(world, freeze, at(2, 8, 0))
    # Dentro da tolerância: ainda "preparando"
    r = user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'})
    assert r.status_code == 409 and r.json()['code'] == 'console_preparing'
    assert _row('select status from reservations where id=%s', rid)['status'] == 'confirmed'
    # Passou da tolerância: falha definitiva
    freeze(at(2, 8, 1, ) + timedelta(seconds=5))
    worker.tick()
    res = _row('select status, resolution_notes from reservations where id=%s', rid)
    assert res['status'] == 'needs_resolution' and 'não foi consumido' in res['resolution_notes']
    assert not _row('select 1 from game_sessions where reservation_id=%s', rid)
    assert _row('select status from queue_entries where reservation_id=%s', rid)['status'] == 'left'
    with tx() as conn:
        conn.execute("update queue_entries set status='playing' where reservation_id=%s", (rid,))
    assert user.get('/me/queues').json() == []
    assert user.get(f'/reservations/{rid}').json()['public_queue'] == []
    worker.tick()
    assert _row('select status from queue_entries where reservation_id=%s', rid)['status'] == 'left'
    inc = _row("select * from service_incidents where reservation_id=%s and kind='console_failure'", rid)
    assert inc and inc['resolved_at'] is None
    assert _row("select 1 from notifications where event_code='console_not_ready' and user_id=(select user_id from reservations where id=%s)", rid)
    assert _row("select 1 from notifications where event_code='staff_incident' and user_id=%s", adm_user['id'])
    r = user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'})
    assert r.status_code == 409 and r.json()['code'] == 'console_unavailable'
    assert admin.get('/admin/incidents').status_code == 200


def test_nao_prepara_com_console_ocupado(world, freeze):
    # Jogador A ocupa o console; a reserva de B começa logo depois
    a_user, a_rid = _paid(world, freeze, at(2, 8, 0))
    assert a_user.post(f'/reservations/{a_rid}/join', json={'input_device': 'gamepad'}).status_code == 200
    b = login(make_user('prep_b'))
    b_rid = reserve(b, world, 10).json()['id']
    assert pay(b, b_rid).status_code == 200
    starts = _row('select starts_at from reservations where id=%s', b_rid)['starts_at']
    freeze(starts - timedelta(seconds=30))
    worker.tick()
    p = _row('select status, attempts from console_preparations where reservation_id=%s', b_rid)
    assert p is None or (p['status'] == 'pending' and p['attempts'] == 0)


def test_share_bloqueado_por_padrao(world, freeze):
    user, rid = _paid(world, freeze, at(2, 8, 0))
    j = user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'}).json()
    send = lambda name: Api().post(f"/sessions/{j['session_id']}/input", json={'command': {'type': 'button', 'name': name}},
                                   headers={'X-Input-Token': j['input_token']})
    r = send('share')
    assert r.status_code == 400 and r.json()['code'] == 'blocked_command'
    assert send('cross').status_code == 200
    adm, _ = admin_api('share_adm')
    assert adm.put('/admin/settings/share_button_enabled', json={'value': True, 'reason': 'teste'}).status_code == 200
    assert send('share').status_code == 200
    assert Api().get('/features').json()['share_button_enabled'] is True

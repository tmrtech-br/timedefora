"""Preparação do console antes da sessão e bloqueio do Share."""
from datetime import timedelta

from app import worker
from app.core.db import one, tx
from app.gamebridge.registry import _ADAPTERS
from app.services import preparation

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
    freeze(at(2, 8, 0) + preparation.PREP_GRACE_PSN + timedelta(seconds=5))
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


def test_sala_de_espera_so_libera_com_console_pronto(world, freeze):
    _ADAPTERS['simulated'].fail_prepare.add(str(world['console']['id']))
    user, rid = _paid(world, freeze, at(2, 8, 0))
    worker.tick()
    room = user.get(f'/reservations/{rid}/waiting-room').json()
    assert room['console_ready'] is False and room['can_join'] is False and room['preparation']['status'] == 'pending'
    _ADAPTERS['simulated'].fail_prepare.discard(str(world['console']['id']))
    worker.tick()
    room = user.get(f'/reservations/{rid}/waiting-room').json()
    assert room['console_ready'] is True and room['can_join'] is True


def _setting(key, value):
    with tx() as conn:
        conn.execute('''insert into global_settings(key, value) values (%s, to_jsonb(%s::int))
                        on conflict (key) do update set value=excluded.value''', (key, value))


def test_tempo_extra_reservado_na_agenda_e_somado_ao_fim(world, freeze):
    _setting('join_bonus_seconds', 30)
    user, rid = _paid(world, freeze, at(2, 8, 0))
    assert _row('select blocked_until from reservations where id=%s', rid)['blocked_until'] == at(2, 8, 10) + timedelta(seconds=30)
    other = login(make_user('prep_bonus_b'))
    nxt = reserve(other, world, 10).json()
    assert nxt['starts_at'].startswith('2026-12-02T08:11')          # a fila respeita o tempo extra do anterior
    worker.tick()
    s = _row('select contract_starts_at, contract_ends_at from game_sessions where reservation_id=%s', rid)
    assert s['contract_starts_at'] == at(2, 8, 0) and s['contract_ends_at'] == at(2, 8, 10) + timedelta(seconds=30)


def test_atraso_do_console_empurra_a_fila_seguinte(world, freeze):
    _ADAPTERS['simulated'].fail_prepare.add(str(world['console']['id']))
    a, a_rid = _paid(world, freeze, at(2, 8, 0))
    b = login(make_user('prep_fila_b'))
    b_rid = reserve(b, world, 10).json()['id']
    assert pay(b, b_rid).status_code == 200
    assert _row('select starts_at from reservations where id=%s', b_rid)['starts_at'] == at(2, 8, 10)
    worker.tick()
    _ADAPTERS['simulated'].fail_prepare.discard(str(world['console']['id']))
    freeze(at(2, 8, 3))
    worker.tick()
    assert _row('select ends_at from reservations where id=%s', a_rid)['ends_at'] == at(2, 8, 13)
    rb = _row('select starts_at, ends_at from reservations where id=%s', b_rid)
    assert rb['starts_at'] == at(2, 8, 13) and rb['ends_at'] == at(2, 8, 23)
    assert _row("select 1 from notifications where event_code='queue_changed' and user_id=(select user_id from reservations where id=%s)", b_rid)


def test_tempo_so_conta_com_console_pronto(world, freeze):
    """Console demorou a acordar (preparação começou no horário): o fim é empurrado pelo atraso."""
    _ADAPTERS['simulated'].fail_prepare.add(str(world['console']['id']))
    user, rid = _paid(world, freeze, at(2, 8, 0))
    worker.tick()                                                   # 08:00 preparação começa, console não fica pronto
    assert _row('select status from console_preparations where reservation_id=%s', rid)['status'] == 'pending'
    _ADAPTERS['simulated'].fail_prepare.discard(str(world['console']['id']))
    freeze(at(2, 8, 3))                                             # pronto 3 min depois do início
    worker.tick()
    r = _row('select ends_at, blocked_until from reservations where id=%s', rid)
    assert r['ends_at'] == at(2, 8, 13)                             # 10 min contados a partir de 08:03
    s = _row('select contract_starts_at, contract_ends_at from game_sessions where reservation_id=%s', rid)
    assert s['contract_starts_at'] == at(2, 8, 3) and s['contract_ends_at'] == at(2, 8, 13)


def test_preparacao_alem_do_fim_original_nao_vira_ausencia(world, freeze, monkeypatch):
    """Tolerância maior que a reserva: a preparação em andamento após o fim original não marca "não compareceu"."""
    monkeypatch.setattr(preparation, 'PREP_GRACE', timedelta(minutes=15))
    _ADAPTERS['simulated'].fail_prepare.add(str(world['console']['id']))
    user, rid = _paid(world, freeze, at(2, 8, 0))
    worker.tick()
    freeze(at(2, 8, 11))                                            # passou do fim original (08:10), ainda preparando
    worker.tick()
    assert _row('select status from reservations where id=%s', rid)['status'] == 'confirmed'
    r = user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'})
    assert r.status_code == 409 and r.json()['code'] == 'console_preparing'
    _ADAPTERS['simulated'].fail_prepare.discard(str(world['console']['id']))
    r = user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'})
    assert r.status_code == 200, r.text
    assert _row('select ends_at from reservations where id=%s', rid)['ends_at'] == at(2, 8, 21)


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

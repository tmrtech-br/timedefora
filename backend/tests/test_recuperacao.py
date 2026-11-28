"""Falha da plataforma: cliente escolhe remarcar (sem custo) ou estorno, uma única vez."""
from datetime import timedelta

from app import worker
from app.core.db import one, tx
from app.gamebridge.registry import _ADAPTERS
from app.services import preparation

from conftest import at, login, make_user, pay, reserve


def _falhou(world, freeze, user):
    """Reserva paga cujo console não ficou pronto → "Em resolução"."""
    _ADAPTERS['simulated'].fail_prepare.add(str(world['console']['id']))
    freeze(at(2, 8, 0))
    api = login(make_user(user))
    rid = reserve(api, world, 10).json()['id']
    assert pay(api, rid).status_code == 200
    worker.tick()
    freeze(at(2, 8, 0) + preparation.PREP_GRACE_PSN + timedelta(seconds=5))
    worker.tick()
    _ADAPTERS['simulated'].fail_prepare.discard(str(world['console']['id']))
    with tx() as conn:
        assert one(conn, 'select status from reservations where id=%s', (rid,))['status'] == 'needs_resolution'
    return api, rid


def test_remarcar_no_proximo_horario_sem_custo(world, freeze):
    api, rid = _falhou(world, freeze, 'rec_remarca')
    room = api.get(f'/reservations/{rid}/waiting-room').json()
    assert room['recovery']['minutes'] == 10 and room['recovery']['refund_cents'] > 0
    opts = api.get(f'/reservations/{rid}/recovery').json()
    assert opts['same_game'] is not None
    new = api.post(f'/reservations/{rid}/reschedule', json={})
    assert new.status_code == 200, new.text
    with tx() as conn:
        n = one(conn, 'select * from reservations where id=%s', (new.json()['reservation_id'],))
        old = one(conn, 'select status, resolution_notes from reservations where id=%s', (rid,))
    assert n['status'] == 'confirmed' and n['total_cents'] == 0 and n['minutes'] == 10 and str(n['rescheduled_from']) == rid
    assert old['status'] == 'cancelled' and old['resolution_notes'].startswith('Remarcada')
    # só uma vez
    assert api.post(f'/reservations/{rid}/reschedule', json={}).status_code == 409
    assert api.post(f'/reservations/{rid}/platform-refund').status_code == 409


def test_estorno_por_falha_da_plataforma(world, freeze):
    api, rid = _falhou(world, freeze, 'rec_estorno')
    r = api.post(f'/reservations/{rid}/platform-refund')
    assert r.status_code == 200, r.text
    with tx() as conn:
        assert one(conn, 'select status from reservations where id=%s', (rid,))['status'] == 'refunded'
        assert one(conn, "select count(*) n from refunds where reservation_id=%s", (rid,))['n'] == 1
    assert api.post(f'/reservations/{rid}/platform-refund').status_code == 409


def test_reserva_normal_nao_tem_recuperacao(world, freeze):
    freeze(at(2, 8, 0))
    api = login(make_user('rec_normal'))
    rid = reserve(api, world, 10).json()['id']
    pay(api, rid)
    assert api.get(f'/reservations/{rid}/waiting-room').json()['recovery'] is None
    assert api.get(f'/reservations/{rid}/recovery').status_code == 409

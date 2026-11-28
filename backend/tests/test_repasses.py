"""Repasse ao proprietário: 10 min após sessão sem problemas → agendado → pagamento manual → pago."""
from datetime import timedelta

from app import worker
from app.core.db import one, tx

from conftest import admin_api, at, login, make_user, pay, reserve


def _console_do_dono(world, owner, with_destination=True):
    with tx() as conn:
        conn.execute('update consoles set owner_user_id=%s, owner_review_status=%s, owner_approved_at=now() where id=%s',
                     (owner['id'], 'approved', world['console']['id']))
        conn.execute("""insert into owner_console_rates(console_id, min_minutes, max_minutes, rate_unit, rate_cents)
                        values (%s, 10, 60, 'minute', 100)""", (world['console']['id'],))
    api = login(owner)
    policy = api.get('/owner/terms').json()
    api.post('/owner/enrollment', json={'policy_version_id': policy['id'], 'accepted': True})
    if with_destination:
        assert api.put('/owner/payout-destination', json={'kind': 'pix', 'pix_key': 'dono@exemplo.com'}).status_code == 200
    return api


def test_repasse_agendado_10_min_e_pago_manual(world, freeze):
    owner = make_user('dono_repasse', roles=('client', 'owner'))
    dono = _console_do_dono(world, owner)
    freeze(at(2, 8, 0))
    player = login(make_user('jogador_repasse'))
    rid = reserve(player, world, 10).json()['id']
    assert pay(player, rid).status_code == 200
    worker.tick()
    j = player.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'}).json()
    freeze(at(2, 8, 5))
    assert player.post(f"/sessions/{j['session_id']}/end").status_code == 200
    with tx() as conn:
        st = one(conn, 'select * from owner_settlements where reservation_id=%s', (rid,))
    assert st['status'] == 'eligible' and st['owner_cents'] > 0
    freeze(at(2, 8, 10))                                   # 5 min depois: ainda não
    worker.tick()
    with tx() as conn:
        assert one(conn, 'select count(*) n from owner_payouts', ())['n'] == 0
    freeze(at(2, 8, 16))                                   # 11 min depois do fim: agenda e manda para pagamento manual
    worker.tick()
    with tx() as conn:
        po = one(conn, 'select * from owner_payouts where settlement_id=%s', (st['id'],))
    assert po['status'] == 'awaiting_manual' and po['amount_cents'] == st['owner_cents'] and po['destination_kind'] == 'pix'
    admin, _ = admin_api('chefe_repasse')
    lst = admin.get('/admin/owner-payouts').json()
    assert lst[0]['destination']['pix_key'] == 'dono@exemplo.com'
    assert admin.post(f"/admin/owner-payouts/{po['id']}/mark-paid", json={'proof_url': 'https://banco/comprovante', 'notes': 'Pix'}).status_code == 200
    with tx() as conn:
        assert one(conn, 'select status from owner_settlements where id=%s', (st['id'],))['status'] == 'paid'
    assert dono.get('/owner/payouts').json()[0]['status'] == 'paid'
    assert admin.post(f"/admin/owner-payouts/{po['id']}/mark-paid", json={}).status_code == 409


def test_repasse_espera_destino_cadastrado(world, freeze):
    owner = make_user('dono_sem_pix', roles=('client', 'owner'))
    dono = _console_do_dono(world, owner, with_destination=False)
    freeze(at(2, 8, 0))
    player = login(make_user('jogador_sem_pix'))
    rid = reserve(player, world, 10).json()['id']
    pay(player, rid)
    worker.tick()
    j = player.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'}).json()
    freeze(at(2, 8, 5))
    player.post(f"/sessions/{j['session_id']}/end")
    freeze(at(2, 8, 20))
    worker.tick()
    with tx() as conn:
        assert one(conn, 'select status from owner_payouts', ())['status'] == 'waiting_destination'
    dono.put('/owner/payout-destination', json={'kind': 'pix', 'pix_key': 'dono2@exemplo.com'})
    worker.tick()
    with tx() as conn:
        assert one(conn, 'select status from owner_payouts', ())['status'] == 'awaiting_manual'

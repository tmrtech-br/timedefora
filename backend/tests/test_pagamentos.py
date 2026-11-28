"""Checkout, webhooks Mercado Pago (assinatura, duplicidade, fora de ordem), pagamento tardio, reembolso."""
import hashlib
import hmac
import time

import pytest

from app.config import settings
from app.core.db import one, tx
from app.services import payment_providers
from app.services.payment_providers import ProviderPayment
from conftest import Api, at, login, make_user, pay, reserve


def sign(data_id, request_id='req-1', secret='whsec-test', ts=None):
    ts = ts or int(time.time())
    v1 = hmac.new(secret.encode(), f'id:{data_id};request-id:{request_id};ts:{ts};'.encode(), hashlib.sha256).hexdigest()
    return {'x-signature': f'ts={ts},v1={v1}', 'x-request-id': request_id}


@pytest.fixture
def mp(monkeypatch):
    """Mercado Pago com consulta server-to-server simulada por monkeypatch (sem rede)."""
    store = {}
    monkeypatch.setattr(settings, 'mp_webhook_secret', 'whsec-test')
    monkeypatch.setattr(payment_providers.MercadoPagoProvider, 'get_payment', lambda self, pid: store.get(pid))
    monkeypatch.setattr(payment_providers.MercadoPagoProvider, 'refund', lambda self, pid, amt, key: f'rf-{pid}')
    return store


def _mp_payment(reservation_api, world):
    r = reserve(reservation_api, world, 30).json()
    co = reservation_api.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).json()
    with tx() as conn:  # simula que o pagamento foi criado no Mercado Pago
        conn.execute("update payments set provider='mercadopago' where id=%s", (co['payment_id'],))
    return r, co['payment_id']


def test_checkout_simulado_confirma_e_notifica(world, freeze):
    freeze(at(2, 8))
    api = login(make_user())
    r = reserve(api, world, 30).json()
    co = api.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).json()
    assert co['simulated'] and co['checkout_url'].startswith('/checkout/simulado/')
    again = api.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).json()
    assert again['payment_id'] == co['payment_id']                 # idempotente
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'pending_payment'   # não confirma por callback do navegador
    api.post(f"/payments/simulated/{co['payment_id']}/notify", json={'outcome': 'approved'})
    v = api.get(f"/reservations/{r['id']}").json()
    assert v['status'] == 'confirmed' and v['queue']['position'] == 1
    titles = [n['title'] for n in api.get('/me/notifications').json()]
    assert any('Pagamento aprovado' in t for t in titles)


def test_historico_filtra_por_reserva_jogo_meio_status_e_data_local(world, freeze):
    freeze(at(2, 8))
    api = login(make_user())
    reservation = reserve(api, world, 30).json()
    payment_id = api.post(f"/reservations/{reservation['id']}/checkout", json={'method': 'pix'}).json()['payment_id']
    assert api.post(f'/payments/simulated/{payment_id}/notify', json={'outcome': 'approved'}).status_code == 200
    with tx() as conn:
        conn.execute('update payments set created_at=%s where id=%s', (at(2, 23, 30), payment_id))

    url = '/me/payments'
    filters = {'q': reservation['code'].lower(), 'method': 'pix', 'status': 'approved',
               'date_from': '2026-12-02', 'date_to': '2026-12-02'}
    response = api.get(url, params=filters)
    assert response.status_code == 200, response.text
    assert [row['id'] for row in response.json()] == [payment_id]
    assert [row['id'] for row in api.get(url, params={'q': 'gta vi'}).json()] == [payment_id]
    for override in ({'method': 'card'}, {'status': 'refunded'}, {'date_from': '2026-12-03', 'date_to': '2026-12-03'}):
        assert api.get(url, params={**filters, **override}).json() == []
    assert api.get(url, params={**filters, 'date_from': '2026-12-03'}).status_code == 422
    assert login(make_user('outro_pagante')).get(url, params=filters).json() == []


def test_webhook_assinatura_invalida_recusado(world, freeze, mp):
    freeze(at(2, 8))
    api = login(make_user())
    r, pid = _mp_payment(api, world)
    mp['123'] = ProviderPayment('123', 'approved', 'accredited', pid, 5000, 'pix')
    h = sign('123', secret='errado')
    res = Api().post('/webhooks/mercadopago?data.id=123&type=payment', json={'type': 'payment', 'data': {'id': '123'}}, headers=h)
    assert res.status_code == 401
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'pending_payment'
    old = sign('123', ts=int(time.time()) - 3600)                    # antirreplay
    assert Api().post('/webhooks/mercadopago?data.id=123&type=payment', json={'data': {'id': '123'}}, headers=old).status_code == 401


def test_webhook_valido_duplicado_e_fora_de_ordem(world, freeze, mp):
    freeze(at(2, 8))
    api = login(make_user())
    r, pid = _mp_payment(api, world)
    mp['555'] = ProviderPayment('555', 'approved', 'accredited', pid, 5000, 'pix')
    body = {'type': 'payment', 'action': 'payment.updated', 'data': {'id': '555'}}
    res = Api().post('/webhooks/mercadopago?data.id=555&type=payment', json=body, headers=sign('555'))
    assert res.status_code == 200 and res.json()['status'] == 'approved'
    dup = Api().post('/webhooks/mercadopago?data.id=555&type=payment', json=body, headers=sign('555'))
    assert dup.json()['status'] == 'duplicate'
    # notificação antiga "pending" chegando depois não regride o status
    mp['555'] = ProviderPayment('555', 'pending', '', pid, 5000, 'pix')
    Api().post('/webhooks/mercadopago?data.id=555&type=payment', json={**body, 'action': 'old'}, headers=sign('555', 'req-2'))
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'confirmed'
    with tx() as conn:
        assert one(conn, 'select status from payments where id=%s', (pid,))['status'] == 'approved'


def test_valor_divergente_nao_confirma(world, freeze, mp):
    freeze(at(2, 8))
    api = login(make_user())
    r, pid = _mp_payment(api, world)
    mp['777'] = ProviderPayment('777', 'approved', '', pid, 100, 'pix')   # pagou R$ 1,00
    Api().post('/webhooks/mercadopago?data.id=777&type=payment', json={'data': {'id': '777'}}, headers=sign('777'))
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'pending_payment'


def test_pagamento_tardio_com_horario_livre_reconfirma(world, freeze):
    freeze(at(2, 8))
    api = login(make_user())
    r = reserve(api, world, 30, mode='scheduled', start_at=at(2, 9)).json()
    co = api.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).json()
    freeze(at(2, 8, 10))                            # hold expirou
    api.post(f"/payments/simulated/{co['payment_id']}/notify", json={'outcome': 'approved'})
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'confirmed'


def test_pagamento_tardio_sem_horario_nao_fura_fila_e_reembolsa(world, freeze):
    freeze(at(2, 8))
    a = login(make_user('alice'))
    r = reserve(a, world, 30, mode='scheduled', start_at=at(2, 9)).json()
    co = a.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).json()
    freeze(at(2, 8, 10))
    b = login(make_user('bruno'))
    rb = reserve(b, world, 30, mode='scheduled', start_at=at(2, 9)).json()   # pega o horário liberado
    pay(b, rb['id'])
    a.post(f"/payments/simulated/{co['payment_id']}/notify", json={'outcome': 'approved'})
    v = a.get(f"/reservations/{r['id']}").json()
    assert v['status'] == 'refunded'
    assert b.get(f"/reservations/{rb['id']}").json()['status'] == 'confirmed'
    with tx() as conn:
        assert one(conn, "select status from refunds")['status'] == 'completed'
        assert one(conn, "select count(*) n from audit_logs where action='reservation.needs_resolution'")['n'] == 1


def test_cancelamento_com_antecedencia_reembolsa_automaticamente(world, freeze):
    freeze(at(2, 6))
    with tx() as conn:
        conn.execute("update console_game_assignments set starts_at=%s", (at(2, 6),))
    api = login(make_user())
    r = reserve(api, world, 30, mode='scheduled', start_at=at(2, 9)).json()
    pay(api, r['id'])
    res = api.post(f"/reservations/{r['id']}/cancel", json={'reason': 'Não poderei jogar'})
    assert res.json()['status'] == 'cancelled'
    pays = api.get('/me/payments').json()
    assert pays[0]['refunded_cents'] == 5000


def test_pagamento_recusado_permite_nova_tentativa(world, freeze):
    freeze(at(2, 8))
    api = login(make_user())
    r = reserve(api, world, 10).json()
    pay(api, r['id'], 'rejected')
    assert api.get(f"/reservations/{r['id']}").json()['status'] == 'pending_payment'
    assert pay(api, r['id']).json()['status'] == 'approved'


def test_simulado_bloqueado_quando_provedor_real(world, freeze, monkeypatch):
    freeze(at(2, 8))
    api = login(make_user())
    r = reserve(api, world, 10).json()
    co = api.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).json()
    monkeypatch.setattr(settings, 'payment_provider', 'mercadopago')
    assert api.post(f"/payments/simulated/{co['payment_id']}/notify", json={'outcome': 'approved'}).status_code == 403


def test_cartao_desligado_por_padrao(world, freeze):
    freeze(at(2, 8, 0))
    u = login(make_user('so_pix'))
    rid = reserve(u, world, 10).json()['id']
    r = u.post(f'/reservations/{rid}/checkout', json={'method': 'card'})
    assert r.status_code == 400 and r.json()['code'] == 'card_disabled'
    assert u.post(f'/reservations/{rid}/checkout', json={'method': 'pix'}).status_code == 200


def test_aviso_atrasado_usa_horario_de_aprovacao(world, freeze):
    """Fila paga às 08:01 (aprovação no provedor), aviso chega às 08:04: a vez começa às 08:01."""
    from datetime import timedelta
    from app.services import payments
    freeze(at(2, 8, 0))
    u = login(make_user('aviso_atrasado'))
    rid = reserve(u, world, 10).json()['id']
    pid = u.post(f'/reservations/{rid}/checkout', json={'method': 'pix'}).json()['payment_id']
    freeze(at(2, 8, 4))
    with tx() as conn:
        payments.apply_status(conn, pid, 'approved', 'webhook', {}, 'mp-1', None, 'pix', approved_at=at(2, 8, 1))
        r = one(conn, 'select status, starts_at, ends_at from reservations where id=%s', (rid,))
    assert r['status'] == 'confirmed' and r['starts_at'] == at(2, 8, 1) and r['ends_at'] == at(2, 8, 11)

"""Parâmetros liga/desliga do painel: aplicados no servidor (não só escondidos na interface)."""
from app.core.db import insert, tx

from conftest import Api, admin_api, at, login, make_user, pay, reserve


def _set(api: Api, key, value):
    r = api.put(f'/admin/settings/{key}', json={'value': value, 'reason': 'teste'})
    assert r.status_code == 200, r.text


def test_features_publico_traz_padroes():
    r = Api().get('/features')
    assert r.status_code == 200
    f = r.json()
    assert f['signup_enabled'] is True and f['disabled_platforms'] == [] and f['sales_paused'] is False


def test_desligar_plataforma_tira_jogo_do_catalogo_e_bloqueia_reserva(world, freeze):
    freeze(at(2, 8, 0))
    adm, _ = admin_api()
    user = login(make_user())
    assert any(g['slug'] == 'gta-vi' for g in Api().get('/catalog/games').json())
    _set(adm, 'disabled_platforms', ['PS5'])
    assert not any(g['slug'] == 'gta-vi' for g in Api().get('/catalog/games').json())
    assert Api().get('/catalog/games/gta-vi').status_code == 404
    assert 'PS5' not in [p['code'] for p in Api().get('/catalog/filters').json()['platforms']]
    r = reserve(user, world, 10)
    assert r.status_code in (404, 409, 422), r.text
    _set(adm, 'disabled_platforms', [])
    assert reserve(user, world, 10).status_code == 201


def test_plataforma_desconhecida_rejeitada():
    adm, _ = admin_api()
    r = adm.put('/admin/settings/disabled_platforms', json={'value': ['NAO_EXISTE'], 'reason': 'x'})
    assert r.status_code == 422


def test_modos_de_compra_desligados(world, freeze):
    freeze(at(2, 8, 0))
    adm, _ = admin_api()
    user = login(make_user())
    _set(adm, 'queue_mode_enabled', False)
    r = reserve(user, world, 10)
    assert r.status_code == 409 and r.json()['code'] == 'feature_disabled'
    _set(adm, 'scheduled_mode_enabled', False)
    r = reserve(user, world, 10, mode='scheduled', start_at=at(2, 9, 0))
    assert r.status_code == 409 and r.json()['code'] == 'feature_disabled'


def test_cupons_desligados(world, freeze):
    freeze(at(2, 8, 0))
    adm, _ = admin_api()
    with tx() as conn:
        insert(conn, 'coupons', {'code': 'DEZ', 'discount_type': 'percent', 'discount_value': 10})
    _set(adm, 'coupons_enabled', False)
    r = reserve(login(make_user()), world, 10, coupon_code='DEZ')
    assert r.status_code == 409 and r.json()['code'] == 'feature_disabled'


def test_cadastro_desligado():
    adm, _ = admin_api()
    _set(adm, 'signup_enabled', False)
    r = Api().post('/auth/register', json={'full_name': 'Fulano de Tal', 'username': 'fulano', 'email': 'f@teste.com',
                                           'password': 'SenhaForte123', 'password_confirm': 'SenhaForte123',
                                           'accept_terms': True, 'accept_privacy': True})
    assert r.status_code == 409 and r.json()['code'] == 'feature_disabled'


def test_teclado_mouse_desligado(world, freeze):
    freeze(at(2, 8, 0))
    adm, _ = admin_api()
    user = login(make_user())
    rid = reserve(user, world, 10).json()['id']
    assert pay(user, rid).status_code == 200
    _set(adm, 'keyboard_mouse_enabled', False)
    r = user.post(f'/reservations/{rid}/join', json={'input_device': 'keyboard_mouse'})
    assert r.status_code == 409 and r.json()['code'] == 'feature_disabled'
    assert user.post(f'/reservations/{rid}/join', json={'input_device': 'gamepad'}).status_code == 200


def test_menu_controles_desligado_bloqueia_edicao_e_preserva_mapeamento():
    adm, _ = admin_api()
    user = login(make_user())
    path = '/me/input-bindings'
    bindings = {'keys': {'cross': 'KeyX'}, 'mouse_look': True, 'mouse_sensitivity': 1.0}
    assert user.put(path, json=bindings).status_code == 200
    _set(adm, 'controls_menu_enabled', False)
    flags = Api().get('/features').json()
    assert flags['controls_menu_enabled'] is False and flags['keyboard_mouse_enabled'] is True
    assert user.put(path, json={**bindings, 'keys': {'cross': 'KeyZ'}}).status_code == 409
    assert user.delete(path).status_code == 409
    assert user.get(path).json() == bindings
    _set(adm, 'controls_menu_enabled', True)
    assert user.delete(path).status_code == 200


def test_chamados_desligados():
    adm, _ = admin_api()
    _set(adm, 'support_tickets_enabled', False)
    user = login(make_user())
    r = user.post('/support/tickets', json={'category': 'geral', 'subject': 'Ajuda aqui', 'message': 'Preciso de ajuda com algo.'})
    assert r.status_code == 409 and r.json()['code'] == 'feature_disabled'

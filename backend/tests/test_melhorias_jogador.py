"""Reserva provisória abandonada não empilha a fila; mensagens claras de indisponibilidade; teclas personalizadas."""
from app.core.db import one, tx
from conftest import Api, at, login, make_user, pay, reserve


def test_nova_reserva_do_mesmo_jogo_libera_a_provisoria_abandonada(world, freeze):
    api = login(make_user('hold_user'))
    r1 = reserve(api, world, 10).json()
    r2 = reserve(api, world, 10).json()                       # voltou e reservou de novo
    assert r1['starts_at'] == r2['starts_at'], 'o horário não pode ser empurrado pela reserva abandonada'
    with tx() as conn:
        assert one(conn, 'select status from reservations where id=%s', (r1['id'],))['status'] == 'cancelled'
    # A anterior com pagamento aprovado NÃO é tocada: a nova vai para depois dela
    assert pay(api, r2['id']).status_code == 200
    r3 = reserve(api, world, 10).json()
    with tx() as conn:
        assert one(conn, 'select status from reservations where id=%s', (r2['id'],))['status'] == 'confirmed'
    assert r3['starts_at'] > r2['starts_at']


def test_horario_fixo_explica_antecedencia_e_fim_da_janela(world, freeze):
    slug = world['game']['slug']
    a = Api()
    # world: agora 02/12 07:00; janela do jogo 08:00–10:00; antecedência mínima padrão do horário fixo = 10 min
    freeze(at(2, 8, 30))
    q = a.get(f'/catalog/games/{slug}/quote', params={'minutes': 10, 'mode': 'scheduled', 'start_at': at(2, 8, 32).isoformat()}).json()
    assert q['available'] is False and 'antecedência' in q['message'] and '08:40' in q['message']
    q = a.get(f'/catalog/games/{slug}/quote', params={'minutes': 30, 'mode': 'scheduled', 'start_at': at(2, 9, 45).isoformat()}).json()
    assert q['available'] is False and 'até 10:00' in q['message']


def test_teclas_personalizadas_salvam_validam_e_resetam():
    api = login(make_user('keys_user'))
    r = api.get('/me/input-bindings').json()
    assert r['keys'] is None and r['mouse_look'] is True                    # padrão do site
    ok = api.put('/me/input-bindings', json={'keys': {'cross': 'ControlLeft', 'r1': 'Space'}, 'mouse_look': False, 'mouse_sensitivity': 1.5})
    assert ok.status_code == 200 and ok.json()['keys']['cross'] == 'ControlLeft'
    assert api.get('/me/input-bindings').json()['mouse_sensitivity'] == 1.5
    dup = api.put('/me/input-bindings', json={'keys': {'cross': 'Space', 'circle': 'Space'}})
    assert dup.status_code == 422 and 'keys' in dup.json()['fields']
    bad = api.put('/me/input-bindings', json={'keys': {'ps': 'KeyP'}})       # botão PS nunca é mapeável
    assert bad.status_code == 422
    assert api.delete('/me/input-bindings').json()['keys'] is None

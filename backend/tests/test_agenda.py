"""Motor de disponibilidade, fila e reservas — casos obrigatórios do prompt (console disponível até 10h)."""
import threading
from datetime import timedelta

from app.core import timeutil
from app.core.db import insert, one, tx
from app.services.scheduling import fits_window
from datetime import datetime

from conftest import Api, at, login, make_user, pay, reserve


def dt(v):
    return datetime.fromisoformat(v)


def test_regra_central_fits_window_pura():
    a, b = at(2, 8), at(2, 10)
    assert fits_window(at(2, 9, 30), 30, a, b)          # termina exatamente em B
    assert not fits_window(at(2, 9, 50), 30, a, b)      # terminaria 10:20
    assert fits_window(at(2, 9, 50), 10, a, b)          # termina 10:00
    assert not fits_window(at(2, 10, 0), 10, a, b)      # iniciar em B é proibido
    assert not fits_window(at(2, 7, 59), 10, a, b)      # antes de A


def test_0930_compra_30min_aceita_terminando_1000(world, freeze):
    freeze(at(2, 9, 30))
    api = login(make_user())
    r = reserve(api, world, 30)
    assert r.status_code == 201, r.text
    with tx() as conn:
        row = one(conn, 'select starts_at, ends_at from reservations')
    assert row['starts_at'] == at(2, 9, 30) and row['ends_at'] == at(2, 10, 0)


def test_0950_compra_30min_bloqueada(world, freeze):
    freeze(at(2, 9, 50))
    r = reserve(login(make_user()), world, 30)
    assert r.status_code == 409 and r.json()['code'] == 'no_availability'


def test_0950_compra_10min_aceita(world, freeze):
    freeze(at(2, 9, 50))
    r = reserve(login(make_user()), world, 10)
    assert r.status_code == 201, r.text
    with tx() as conn:
        assert one(conn, 'select ends_at from reservations')['ends_at'] == at(2, 10)


def test_1000_nova_sessao_bloqueada(world, freeze):
    freeze(at(2, 10, 0))
    r = reserve(login(make_user()), world, 10)
    assert r.status_code == 409
    # horário fixo exatamente em B também é recusado
    freeze(at(2, 8, 0))
    r = reserve(login(make_user('outro')), world, 10, mode='scheduled', start_at=at(2, 10, 0))
    assert r.status_code == 409


def test_sessao_ate_0950_impede_nova_de_30min(world, freeze):
    freeze(at(2, 9, 30))
    a = login(make_user('alpha'))
    r = reserve(a, world, 10)  # 09:30–09:40
    assert r.status_code == 201
    assert pay(a, r.json()['id']).json()['status'] == 'approved'
    b = login(make_user('beta'))
    r2 = reserve(b, world, 10)  # 09:40–09:50
    assert r2.status_code == 201
    pay(b, r2.json()['id'])
    c = login(make_user('gama'))
    assert reserve(c, world, 30).status_code == 409   # 09:50–10:20 excederia a janela
    assert reserve(c, world, 10).status_code == 201   # 09:50–10:00 cabe


def test_fila_anterior_impede_compra_mesmo_com_console_livre_no_cadastro(world, freeze):
    freeze(at(2, 8, 0))
    users = [login(make_user(f'p{i}')) for i in range(4)]
    for api in users:                       # 4 × 30 min ocupam 08:00–10:00
        r = reserve(api, world, 30)
        assert r.status_code == 201, r.text
        pay(api, r.json()['id'])
    r = reserve(login(make_user('atrasado')), world, 10)
    assert r.status_code == 409


def test_fifo_posicoes_e_nomes_publicos(world, freeze):
    freeze(at(2, 8, 0))
    names = ['PlayerAlpha', 'GamerBR', 'Player2026', 'MeuUsuario']
    apis = []
    for nm in names:
        api = login(make_user(nm))
        r = reserve(api, world, 10)
        pay(api, r.json()['id'])
        apis.append(api)
    q = apis[3].get(f"/queues/console/{world['console']['id']}").json()['queue']
    assert [x['username'] for x in q] == names
    assert [x['position'] for x in q] == [1, 2, 3, 4]
    assert q[3]['is_me'] and not q[0]['is_me']
    assert all('email' not in x and 'full_name' not in x for x in q)


def test_setup_entre_jogadores_e_manutencao(world, freeze):
    freeze(at(2, 8, 0))
    with tx() as conn:
        conn.execute("update global_settings set value='5' where key='setup_minutes'")
        insert(conn, 'blackout_windows', {'console_id': world['console']['id'], 'starts_at': at(2, 8, 15), 'ends_at': at(2, 9, 0), 'reason': 'Manutenção'})
    a = login(make_user('a1'))
    r = reserve(a, world, 10).json()   # 08:00–08:10, bloqueado até 08:15
    assert dt(r['starts_at']) == at(2, 8, 0)
    pay(a, r['id'])
    r2 = reserve(login(make_user('a2')), world, 10).json()   # 08:15 livre? não: manutenção 08:15–09:00; 08:10–08:15 só cabe com setup → 09:00
    with tx() as conn:
        assert one(conn, 'select starts_at from reservations where id=%s', (r2['id'],))['starts_at'] == at(2, 9, 0)


def test_limite_agendado_termina_antes_do_bloqueio(world):
    with tx() as conn:
        insert(conn, 'blackout_windows', {
            'console_id': world['console']['id'], 'starts_at': at(2, 8, 45),
            'ends_at': at(2, 9), 'reason': 'Manutenção programada',
        })
    response = Api().get('/catalog/games/gta-vi/quote', params={
        'minutes': 1, 'mode': 'scheduled', 'start_at': at(2, 8).isoformat(), 'duration_limit': True,
    })
    assert response.status_code == 200
    assert response.json()['max_minutes'] == 45


def test_limite_agendado_desconta_preparacao_e_tempo_extra(world, freeze):
    freeze(at(2, 7, 0))
    with tx() as conn:
        conn.execute("update global_settings set value='5' where key='setup_minutes'")
        conn.execute("update global_settings set value='30' where key='join_bonus_seconds'")
    a = login(make_user('lim_a'))
    r = reserve(a, world, 10, mode='scheduled', start_at=at(2, 9, 0))
    assert r.status_code == 201, r.text
    response = Api().get('/catalog/games/gta-vi/quote', params={
        'minutes': 1, 'mode': 'scheduled', 'start_at': at(2, 8).isoformat(), 'duration_limit': True,
    })
    # 08:00 até a reserva das 09:00, menos 5 min de preparação e 30 s de tempo extra → 54 min inteiros
    assert response.json()['max_minutes'] == 54
    with tx() as conn:   # o limite calculado precisa caber de fato (mesma regra da reserva)
        from app.services import scheduling
        assert scheduling.find_slots(conn, world['game']['id'], 54, 'scheduled', at(2, 8))
        assert not scheduling.find_slots(conn, world['game']['id'], 55, 'scheduled', at(2, 8))


def test_hold_provisorio_bloqueia_e_expira(world, freeze):
    freeze(at(2, 9, 30))
    a = login(make_user('a1'))
    assert reserve(a, world, 30).status_code == 201         # hold 09:30–10:00
    b = login(make_user('b1'))
    assert reserve(b, world, 10).status_code == 409          # hold ocupa a janela
    freeze(at(2, 9, 36))                                     # hold expirou (5 min)
    r = reserve(b, world, 10)
    assert r.status_code == 201, r.text
    with tx() as conn:
        st = {x['status'] for x in conn.execute('select status from reservations').fetchall()}
    assert st == {'expired', 'pending_payment'}


def test_concorrencia_20_reservas_simultaneas_apenas_uma(world, freeze):
    freeze(at(2, 9, 30))
    apis = [login(make_user(f'c{i}')) for i in range(20)]
    codes = []
    lock = threading.Lock()

    def go(api):
        r = reserve(api, world, 30)
        with lock:
            codes.append(r.status_code)
    ts = [threading.Thread(target=go, args=(a,)) for a in apis]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert codes.count(201) == 1 and codes.count(409) == 19, codes
    with tx() as conn:
        assert one(conn, "select count(*) n from reservations where status='pending_payment'")['n'] == 1


def test_constraint_de_exclusao_no_banco_impede_overbooking_direto(world):
    import psycopg
    import pytest
    u = make_user('x')
    base = {'user_id': u['id'], 'game_id': world['game']['id'], 'console_id': world['console']['id'],
            'assignment_id': world['assignment']['id'], 'mode': 'scheduled', 'minutes': 30, 'status': 'confirmed',
            'price_cents': 1, 'total_cents': 1}
    with tx() as conn:
        insert(conn, 'reservations', {**base, 'code': 'LP-AAAAAA', 'starts_at': at(2, 9), 'ends_at': at(2, 9, 30), 'blocked_until': at(2, 9, 30)})
    with pytest.raises(psycopg.errors.ExclusionViolation):
        with tx() as conn:
            insert(conn, 'reservations', {**base, 'code': 'LP-BBBBBB', 'starts_at': at(2, 9, 15), 'ends_at': at(2, 9, 45), 'blocked_until': at(2, 9, 45)})


def test_horario_fixo_e_antecedencia(world, freeze):
    freeze(at(2, 8, 0))
    api = login(make_user())
    assert reserve(api, world, 30, mode='scheduled', start_at=at(2, 8, 5)).status_code == 409     # < 10 min de antecedência
    r = reserve(api, world, 30, mode='scheduled', start_at=at(2, 9, 30))
    assert r.status_code == 201
    assert reserve(login(make_user('y')), world, 10, mode='scheduled', start_at=at(2, 9, 45)).status_code == 409


def test_preco_e_pacote_definidos_no_servidor(world, freeze):
    freeze(at(2, 8, 0))
    api = login(make_user())
    assert reserve(api, world, 7).status_code == 422                           # pacote inexistente
    r = reserve(api, world, 10, price_cents=1, total_cents=1)                   # campos extras ignorados
    assert r.status_code == 201 and r.json()['total_cents'] == 3000


def test_cupom_percentual_e_limite_por_usuario(world, freeze):
    freeze(at(2, 8, 0))
    with tx() as conn:
        insert(conn, 'coupons', {'code': 'BEMVINDO', 'discount_type': 'percent', 'discount_value': 20})
    api = login(make_user())
    r = reserve(api, world, 30, coupon_code='bemvindo')
    assert r.status_code == 201 and r.json()['total_cents'] == 4000
    pay(api, r.json()['id'])
    assert reserve(api, world, 10, coupon_code='BEMVINDO').status_code == 422


def test_email_nao_verificado_nao_pode_reservar(world, freeze):
    freeze(at(2, 8, 0))
    r = reserve(login(make_user('novo', verified=False)), world, 10)
    assert r.status_code == 403 and r.json()['code'] == 'email_not_verified'


def test_jogo_sem_licenca_nao_vende_fora_do_modo_demo(world, freeze):
    freeze(at(2, 8, 0))
    with tx() as conn:
        conn.execute('update games set is_demo=false')
    r = reserve(login(make_user()), world, 10)
    assert r.status_code == 409 and r.json()['code'] == 'not_licensed'


def test_horario_de_funcionamento_do_console(world, freeze):
    freeze(at(2, 8, 0))
    with tx() as conn:   # quarta-feira (02/12/2026) 09:00–09:30 apenas
        insert(conn, 'console_operating_hours', {'console_id': world['console']['id'], 'weekday': 3,
                                                 'opens_at': __import__('datetime').time(9, 0), 'closes_at': __import__('datetime').time(9, 30)})
    r = reserve(login(make_user()), world, 30)
    assert r.status_code == 201 and dt(r.json()['starts_at']) == at(2, 9, 0)
    assert reserve(login(make_user('z')), world, 10).status_code == 409


def test_cancelamento_libera_e_antecipa_fila(world, freeze):
    freeze(at(2, 8, 0))
    a, b = login(make_user('a')), login(make_user('b'))
    ra = reserve(a, world, 30, mode='scheduled', start_at=at(2, 8, 30)).json()
    pay(a, ra['id'])
    rb = reserve(b, world, 30).json()     # fila: 08:00 já livre → 08:00
    assert dt(rb['starts_at']) == at(2, 8, 0)
    c = login(make_user('c'))
    rc = reserve(c, world, 30).json()     # próxima vaga: 09:00
    pay(c, rc['id'])
    assert dt(rc['starts_at']) == at(2, 9, 0)
    # a cancela com antecedência (≥ 2h? não: 30 min) → vira solicitação
    r = a.post(f"/reservations/{ra['id']}/cancel", json={'reason': 'imprevisto'})
    assert r.json()['status'] == 'requested'
    # b desiste do hold → c NÃO é antecipada antes de now+5min, mas pode ir para 08:00? (slot 08:00–08:30 livre)
    b.post(f"/reservations/{rb['id']}/cancel", json={'reason': 'desisti'})
    with tx() as conn:
        assert one(conn, 'select starts_at from reservations where id=%s', (rc['id'],))['starts_at'] == at(2, 9, 0)  # 08:05–08:35 conflita com 08:30


def test_reserva_por_minuto_usa_janela_e_tarifa_do_servidor(world, freeze):
    start = at(26, 10, month=11)
    end = at(30, 8, month=11)
    freeze(at(26, 8, month=11))
    with tx() as conn:
        conn.execute("insert into global_settings(key, value) values ('booking_rate_cents_per_minute', '100')")
        conn.execute('update console_game_assignments set starts_at=%s, ends_at=%s where id=%s',
                     (start, end, world['assignment']['id']))

    api = login(make_user())
    detail = api.get('/catalog/games/gta-vi').json()
    assert detail['availability']['consoles'][0]['last_free_minutes'] == 5640
    one_minute = api.get('/catalog/games/gta-vi/quote', params={'minutes': 1}).json()
    assert one_minute['price_cents'] == 100
    quote = api.get('/catalog/games/gta-vi/quote', params={
        'minutes': 5640, 'mode': 'scheduled', 'start_at': start.isoformat(),
    }).json()
    assert quote['available'] and quote['price_cents'] == 564000
    assert dt(quote['ends_at']) == end

    booking = reserve(api, world, 100, 'scheduled', start)
    assert booking.status_code == 201, booking.text
    assert booking.json()['total_cents'] == 10000
    assert api.get(f"/reservations/{booking.json()['id']}").json()['cancellation_policy']['version']

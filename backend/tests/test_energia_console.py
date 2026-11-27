"""Energia do console: ligar ao reservar, preparar antes, manter ligado para a próxima e hibernar ocioso."""
from datetime import timedelta

from app import worker
from app.core.db import one, tx
from app.gamebridge.registry import _ADAPTERS
from app.services import console_power, preparation
from app.services.consoles import console_ref

from conftest import at, login, make_user, pay, reserve


def _set(key, value):
    import json
    with tx() as conn:
        conn.execute('''insert into global_settings(key, value) values (%s, %s::jsonb)
                        on conflict (key) do update set value=excluded.value''', (key, json.dumps(value)))


def _calls(monkeypatch):
    sim = _ADAPTERS['simulated']
    calls = {'connect': 0, 'standby': 0}
    orig_prepare, orig_stop = sim.prepare_console, sim.stop_stream

    def prepare(ref, game):                         # checkout: prepara o console (acorda + abre o jogo)
        calls['connect'] += 1
        return orig_prepare(ref, game)

    def stop_stream(ref, session_id, standby=False):
        if standby:
            calls['standby'] += 1
        return orig_stop(ref, session_id, standby)
    monkeypatch.setattr(sim, 'prepare_console', prepare)
    monkeypatch.setattr(sim, 'stop_stream', stop_stream)
    return calls


def test_liga_o_console_ao_reservar(world, freeze, monkeypatch):
    calls = _calls(monkeypatch)
    freeze(at(2, 8, 0))
    user = login(make_user('energia_a'))
    assert reserve(user, world, 10).status_code == 201          # modo fila: começa já
    assert calls['connect'] == 1


def test_nao_liga_ao_reservar_quando_desligado(world, freeze, monkeypatch):
    calls = _calls(monkeypatch)
    _set('wake_on_reservation_enabled', False)
    freeze(at(2, 8, 0))
    user = login(make_user('energia_b'))
    assert reserve(user, world, 10).status_code == 201
    assert calls['connect'] == 0


def test_nao_liga_ao_reservar_horario_distante(world, freeze, monkeypatch):
    calls = _calls(monkeypatch)
    freeze(at(2, 7, 0))
    user = login(make_user('energia_c'))
    r = reserve(user, world, 10, mode='scheduled', start_at=at(2, 9, 0))
    assert r.status_code == 201, r.text
    assert calls['connect'] == 0                                  # 2 h antes: a preparação antecipada cuida depois


def test_preparacao_comeca_com_a_antecedencia_configurada(world, freeze):
    _set('prep_lead_minutes', 7)
    with tx() as conn:
        assert preparation.lead(conn) == timedelta(minutes=7)
    _set('prewake_enabled', False)
    with tx() as conn:
        assert preparation.lead(conn) == timedelta(minutes=1)     # setup_minutes=0 no cenário: mínimo 1 min


def test_mantem_ligado_para_a_proxima_e_hiberna_sem_proxima(world, freeze):
    freeze(at(2, 8, 0))
    user = login(make_user('energia_d'))
    rid = reserve(user, world, 10).json()['id']
    assert pay(user, rid).status_code == 200
    with tx() as conn:
        ref = console_ref(conn, world['console']['id'])
        # Reserva (a própria, confirmada) começando agora: mantém ligado
        assert console_power.should_standby(conn, ref, world['console']['id']) is False
        # Excluindo a própria reserva, não há próxima: hiberna
        assert console_power.should_standby(conn, ref, world['console']['id'], exclude_reservation=rid) is True
    _set('keep_awake_for_next_enabled', False)
    with tx() as conn:
        assert console_power.should_standby(conn, ref, world['console']['id']) is True
    _set('console_standby_enabled', False)
    with tx() as conn:
        assert console_power.should_standby(conn, ref, world['console']['id'], exclude_reservation=rid) is False


def test_reserva_nao_paga_expira_e_console_volta_a_hibernar(world, freeze, monkeypatch):
    calls = _calls(monkeypatch)
    monkeypatch.setattr(console_power, 'standby_if_idle', _standby_counting(calls))
    freeze(at(2, 8, 0))
    user = login(make_user('energia_e'))
    rid = reserve(user, world, 10).json()['id']
    freeze(at(2, 8, 30))                                          # prazo para pagar passou
    worker.tick()
    with tx() as conn:
        assert one(conn, 'select status from reservations where id=%s', (rid,))['status'] == 'expired'
    assert calls['idle_checked'] == 1


def _standby_counting(calls):
    calls['idle_checked'] = 0

    def fn(conn, console_id):
        calls['idle_checked'] += 1
        return False
    return fn

"""Energia do console: ligar antes da sessão e hibernar quando ninguém vai usar. Tudo parametrizável.

Parâmetros globais (menu Parâmetros) e do cadastro de cada console:
- console_standby_enabled (global) + standby_after_session (console): hibernar ao fim da sessão / quando ocioso.
- keep_awake_for_next_enabled (global) + keep_awake_minutes (console): não hibernar se houver reserva começando
  dentro desse intervalo (o próximo jogador não espera o console acordar).
- wake_on_reservation_enabled (global): ao criar a reserva (antes do pagamento), acordar o console se a sessão
  começar em breve. Se o pagamento não vier, o console volta a hibernar quando a reserva expira.
- prewake_enabled + prep_lead_minutes (global): a preparação (acordar + abrir o jogo) começa N minutos antes do
  início (ver preparation.lead).

Nunca mexe num console com sessão de outro jogador em andamento.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from ..core import timeutil
from ..core.db import tx
from ..gamebridge import AdapterError, get_adapter
from .consoles import console_ref
from .settings_store import get_settings

log = logging.getLogger('locaplay.console_power')
OCCUPYING = ('pending_payment', 'confirmed', 'active')


def keep_awake_minutes(ref) -> int:
    try:
        return max(0, int((ref.settings or {}).get('keep_awake_minutes', 15)))
    except (TypeError, ValueError):
        return 15


def _busy(conn, console_id, exclude_session=None) -> bool:
    """Outro jogador com sessão liberada/em andamento no console."""
    q = "select 1 from game_sessions where console_id=%s and status in ('ready','active')"
    args: list = [console_id]
    if exclude_session:
        q += ' and id<>%s'
        args.append(exclude_session)
    return bool(conn.execute(q + ' limit 1', args).fetchone())


def _upcoming(conn, console_id, within: timedelta, exclude_reservation=None) -> bool:
    q = '''select 1 from reservations r where r.console_id=%s and r.status = any(%s) and r.starts_at <= %s
           and not (r.status='pending_payment' and r.hold_expires_at <= %s)'''
    n = timeutil.now()
    args: list = [console_id, list(OCCUPYING), n + within, n]
    if exclude_reservation:
        q += ' and r.id<>%s'
        args.append(exclude_reservation)
    return bool(conn.execute(q + ' limit 1', args).fetchone())


def should_standby(conn, ref, console_id, exclude_session=None, exclude_reservation=None) -> bool:
    """Hibernar só se os parâmetros pedirem, o console estiver livre e não houver reserva começando em breve."""
    st = get_settings(conn)
    if not st.get('console_standby_enabled', True) or not (ref.settings or {}).get('standby_after_session', True):
        return False
    if _busy(conn, console_id, exclude_session):
        return False
    if conn.execute("select 1 from console_preparations where console_id=%s and status='pending' limit 1", (console_id,)).fetchone():
        return False                                    # alguém está sendo preparado neste console
    if st.get('keep_awake_for_next_enabled', True):
        window = timedelta(minutes=keep_awake_minutes(ref))
        if st.get('prewake_enabled', True):             # a próxima preparação começaria antes disso: não vale hibernar
            window = max(window, timedelta(minutes=int(st.get('prep_lead_minutes', 5) or 0)))
        if _upcoming(conn, console_id, window, exclude_reservation):
            return False
    return True


def wake_for_reservation(reservation_id) -> None:
    """Executado em segundo plano após criar a reserva: acorda o console se ele vai ser usado em breve."""
    try:
        with tx() as conn:
            st = get_settings(conn)
            if not st.get('wake_on_reservation_enabled', True):
                return
            r = conn.execute('select id, console_id, starts_at, status from reservations where id=%s', (reservation_id,)).fetchone()
            if not r or r['status'] not in ('pending_payment', 'confirmed') or not r['console_id']:
                return
            ref = console_ref(conn, r['console_id'])
            lead = timedelta(minutes=max(keep_awake_minutes(ref), int(st.get('prep_lead_minutes', 5) or 0)))
            if r['starts_at'] > timeutil.now() + lead:
                return                                  # longe demais: a preparação antecipada cuida disso depois
            if _busy(conn, r['console_id']):
                return                                  # outro jogador no console: ele já está ligado
            ahead = conn.execute('''select 1 from reservations where console_id=%s and id<>%s and status = any(%s)
                                    and starts_at < %s limit 1''',
                                 (r['console_id'], r['id'], list(OCCUPYING), r['starts_at'])).fetchone()
            if ahead:
                return                                  # há alguém antes: o console será preparado para essa pessoa
        adapter = get_adapter(ref.method)
        res = adapter.connect(ref)                      # só acorda e conecta; o jogo é aberto na preparação
        log.info('reserva %s: console acordado ao reservar (%s)', reservation_id, res.message[:120])
    except AdapterError as e:
        log.warning('reserva %s: não foi possível acordar o console ao reservar: %s', reservation_id, e.message)
    except Exception:  # nunca afeta a reserva
        log.exception('reserva %s: erro ao acordar o console', reservation_id)


def standby_if_idle(conn, console_id) -> bool:
    """Reserva expirou/cancelada (console pode ter sido acordado à toa): hiberna se ninguém for usar."""
    ref = console_ref(conn, console_id)
    if ref.method in ('unconfigured', 'simulated') or not should_standby(conn, ref, console_id):
        return False
    try:
        res = get_adapter(ref.method).stop_stream(ref, '', standby=True)
        log.info('console %s ocioso: %s', console_id, res.message[:120])
        return True
    except AdapterError as e:
        log.warning('console %s: falha ao hibernar ocioso: %s', console_id, e.message)
        return False

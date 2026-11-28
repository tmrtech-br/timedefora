"""Recuperação de reservas afetadas por falha da PLATAFORMA (console não ficou pronto, queda durante a sessão).

O cliente escolhe: remarcar (próximo horário livre do mesmo jogo, ou outro jogo com a mesma duração) ou estorno.
- Remarcar não cobra nada: a nova reserva já nasce confirmada com o valor pago como crédito (total 0) e aponta para a
  original (rescheduled_from), que guarda o pagamento.
- Falha no meio da sessão: o crédito são os minutos NÃO usados (arredondado para cima a favor do cliente).
- Estorno: Pix integral (ou proporcional aos minutos não usados), pelo provedor.
"""
from __future__ import annotations

import math
from datetime import timedelta

from ..core import timeutil
from ..core.db import audit_event, insert
from ..core.errors import conflict, not_found
from . import notifications, payments, scheduling
from .settings_store import get_settings

MAX_OTHER_GAMES = 6


def _root(conn, r: dict) -> dict:
    """Reserva original (a que tem o pagamento) seguindo remarcações anteriores."""
    seen = set()
    while r.get('rescheduled_from') and r['id'] not in seen:
        seen.add(r['id'])
        r = conn.execute('select * from reservations where id=%s', (r['rescheduled_from'],)).fetchone()
    return r


def _paid(conn, r: dict) -> dict | None:
    root = _root(conn, r)
    return conn.execute("select * from payments where reservation_id=%s and status='approved' order by approved_at desc limit 1",
                        (root['id'],)).fetchone()


def eligibility(conn, r: dict) -> dict | None:
    """Minutos e valor a recuperar, ou None se a reserva não foi afetada por falha da plataforma."""
    if (r.get('resolution_notes') or '').startswith(('Remarcada', 'Estorno')):
        return None                                      # recuperação já escolhida (uma vez por reserva)
    if r['status'] == 'needs_resolution':
        used = 0
    else:
        s = conn.execute("select * from game_sessions where reservation_id=%s and status='ended' and end_reason='failure'",
                         (r['id'],)).fetchone()
        if not s or r['status'] not in ('completed',):
            return None
        used = int(s['seconds_used'] or 0)
    minutes = max(0, r['minutes'] - math.floor(used / 60))   # minuto começado e interrompido volta para o cliente
    if minutes < 1:
        return None
    pay = _paid(conn, r)
    paid = pay['amount_cents'] if pay else 0
    refunded = conn.execute("select coalesce(sum(amount_cents),0) s from refunds where payment_id=%s and status in "
                            "('requested','processing','completed')", (pay['id'],)).fetchone()['s'] if pay else 0
    amount = min(paid - refunded, math.ceil(paid * minutes / r['minutes'])) if r['minutes'] else 0
    return {'minutes': minutes, 'refund_cents': max(0, amount), 'payment_id': str(pay['id']) if pay else None}


def options(conn, r: dict) -> dict:
    el = eligibility(conn, r)
    if not el:
        raise conflict('not_recoverable', 'Esta reserva não tem remarcação ou estorno disponível.')
    minutes = el['minutes']
    same = scheduling.find_slots(conn, r['game_id'], minutes, 'queue')
    other = []
    if not same:
        games = conn.execute('''select id, title, slug, cover_url from games where status='published' and deleted_at is null
                                and id<>%s order by title''', (r['game_id'],)).fetchall()
        for g in games:
            if len(other) >= MAX_OTHER_GAMES:
                break
            slots = scheduling.find_slots(conn, g['id'], minutes, 'queue')
            if slots:
                other.append({'game_id': str(g['id']), 'title': g['title'], 'slug': g['slug'], 'cover_url': g['cover_url'],
                              'starts_at': slots[0].start.isoformat(), 'console': slots[0].console_name})
    return {'minutes': minutes, 'refund_cents': el['refund_cents'],
            'same_game': ({'starts_at': same[0].start.isoformat(), 'console': same[0].console_name} if same else None),
            'other_games': other}


def reschedule(conn, user, r: dict, game_id=None) -> dict:
    el = eligibility(conn, r)
    if not el:
        raise conflict('not_recoverable', 'Esta reserva não tem remarcação disponível.')
    game_id = game_id or r['game_id']
    game = conn.execute("select * from games where id=%s and status='published' and deleted_at is null", (game_id,)).fetchone()
    if not game:
        raise not_found('Jogo indisponível.')
    st = get_settings(conn)
    scheduling.expire_stale_holds(conn)
    slots = scheduling.find_slots(conn, game['id'], el['minutes'], 'queue', lock=True)
    if not slots:
        raise conflict('no_availability', 'Não há horário livre agora para esta duração. Escolha outro jogo ou o estorno.')
    s = slots[0]
    inventory = conn.execute('select owner_user_id from consoles where id=%s', (s.console_id,)).fetchone()
    n = timeutil.now()
    new = insert(conn, 'reservations', {
        'code': scheduling._code(), 'user_id': r['user_id'], 'game_id': game['id'], 'console_id': s.console_id,
        'assignment_id': s.assignment_id, 'owner_user_id': inventory['owner_user_id'],
        'owner_share_bps': st['owner_share_bps'] if inventory['owner_user_id'] else None,
        'mode': 'queue', 'minutes': el['minutes'], 'setup_minutes': int(st['setup_minutes']),
        'starts_at': s.start, 'ends_at': s.end, 'blocked_until': s.blocked_until,
        'status': 'confirmed', 'confirmed_at': n, 'price_cents': el['refund_cents'], 'discount_cents': el['refund_cents'],
        'total_cents': 0, 'rescheduled_from': r['id']})
    conn.execute("""update reservations set status=case when status='needs_resolution' then 'cancelled' else status end,
                    resolution_notes=%s where id=%s""", (f"Remarcada para {new['code']} (sem custo).", r['id']))
    scheduling.recompute_queue(conn, s.console_id)
    audit_event(conn, 'reservation.rescheduled', 'reservations', r['id'], details={'new': str(new['id']), 'minutes': el['minutes']})
    notifications.notify(conn, str(r['user_id']), 'queue_changed',
                         {'jogo': game['title'], 'inicio_previsto': timeutil.fmt_time(s.start),
                          'mensagem': f"Reserva remarcada sem custo: {new['code']} ({el['minutes']} min)."},
                         dedupe=f"rescheduled:{new['id']}", link=f"/sessoes/{new['id']}")
    return new


def refund(conn, user, r: dict) -> dict:
    el = eligibility(conn, r)
    if not el or not el['payment_id'] or el['refund_cents'] <= 0:
        raise conflict('not_refundable', 'Não há valor a estornar para esta reserva.')
    rf = payments.create_refund(conn, el['payment_id'], el['refund_cents'],
                                'Falha da plataforma: estorno escolhido pelo cliente.', user.user_id)
    if r['status'] == 'needs_resolution':
        conn.execute("update reservations set status='refunded' where id=%s", (r['id'],))
    conn.execute("update reservations set resolution_notes=%s where id=%s",
                 (f"Estorno de {timeutil.money(el['refund_cents'])} solicitado.", r['id']))
    return rf

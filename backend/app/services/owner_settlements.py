"""Apuração do proprietário após o encerramento da sessão."""
from ..core.db import audit_event, all_, one


def refresh(conn, reservation_id) -> None:
    reservation = one(conn, '''
        select id, owner_user_id, owner_share_bps, total_cents from reservations
        where id=%s and owner_user_id is not null for update
    ''', (reservation_id,))
    if not reservation:
        return
    session = one(conn, 'select id, ended_at, end_reason from game_sessions where reservation_id=%s',
                  (reservation_id,))
    if not session or session['ended_at'] is None:
        return
    previous = one(conn, 'select id, status, owner_cents from owner_settlements where reservation_id=%s',
                   (reservation_id,))
    if previous and previous['status'] == 'paid':
        return
    incidents = all_(conn, '''
        select resolved_at, owner_fault, owner_approved_cents from service_incidents
        where reservation_id=%s
    ''', (reservation_id,))
    payment = one(conn, '''
        select 1 from payments where reservation_id=%s and status='approved'
    ''', (reservation_id,))
    base = reservation['total_cents']
    share = reservation['owner_share_bps']
    amount = (base * share + 5000) // 10000
    if any(i['resolved_at'] and i['owner_fault'] == 'renter' for i in incidents):
        status, amount = 'cancelled', 0
    elif any(i['resolved_at'] is None or i['owner_fault'] is None for i in incidents):
        status = 'held'
    elif not incidents and session['end_reason'] in ('failure', 'admin', 'no_show'):
        status = 'held'
    elif not payment:
        status = 'held'
    else:
        status = 'eligible'
        amounts = [i['owner_approved_cents'] for i in incidents if i['owner_approved_cents'] is not None]
        if amounts:
            amount = min(amounts)
        if not amount:
            status = 'cancelled'
    if previous and previous['status'] == status and previous['owner_cents'] == amount:
        return
    row = one(conn, '''
        insert into owner_settlements(session_id, reservation_id, owner_user_id, base_cents,
                                      owner_share_bps, owner_cents, status)
        values (%s,%s,%s,%s,%s,%s,%s)
        on conflict (reservation_id) do update
        set owner_cents=excluded.owner_cents, status=excluded.status, updated_at=now()
        returning id
    ''', (session['id'], reservation_id, reservation['owner_user_id'], base, share, amount, status))
    audit_event(conn, 'owner.settlement_changed', 'owner_settlements', row['id'],
                details={'reservation_id': str(reservation_id), 'session_id': str(session['id']),
                         'from': previous['status'] if previous else None, 'to': status,
                         'owner_cents': amount})

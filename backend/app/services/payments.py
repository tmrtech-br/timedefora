"""Pagamentos: criação idempotente no backend, máquina de estados, webhooks, conciliação e reembolsos.
A sessão NUNCA é liberada por callback do navegador; somente por status confirmado no servidor."""
from psycopg.types.json import Jsonb

from ..config import settings
from ..core import security, timeutil
from ..core.db import audit_event, insert, tx
from ..core.errors import AppError, bad_request, conflict, forbidden, not_found
from . import notifications, scheduling
from .payment_providers import get_provider

FINAL = {'approved', 'rejected', 'cancelled', 'expired', 'refunded', 'charged_back'}
ALLOWED = {
    'created': {'pending', 'approved', 'rejected', 'cancelled', 'expired'},
    'pending': {'approved', 'rejected', 'cancelled', 'expired'},
    'approved': {'refunded', 'charged_back'},
    'rejected': {'approved'},      # ex.: notificação fora de ordem
    'cancelled': {'approved'},
    'expired': {'approved'},       # pagamento tardio (tratado por confirm_reservation)
    'refunded': set(), 'charged_back': set(),
}


def start_checkout(user, reservation_id, method: str) -> dict:
    if method not in ('pix', 'card'):
        raise bad_request('invalid_method', 'Escolha Pix ou cartão.')
    with tx() as conn:
        r = conn.execute('select r.*, g.title from reservations r join games g on g.id=r.game_id where r.id=%s for update',
                         (reservation_id,)).fetchone()
        if not r or str(r['user_id']) != user.user_id:
            raise not_found('Reserva não encontrada.')
        if r['status'] != 'pending_payment' or r['hold_expires_at'] <= timeutil.now():
            raise conflict('hold_expired', 'Esta reserva provisória expirou. Faça uma nova reserva.')
        if r['total_cents'] == 0:
            scheduling.confirm_reservation(conn, r['id'], 'free')
            return {'free': True, 'status': 'confirmed'}
        existing = conn.execute("""select * from payments where reservation_id=%s and method=%s and status in ('created','pending')
                                   order by created_at desc limit 1""", (r['id'], method)).fetchone()
        if existing and existing['checkout_url']:
            return {'payment_id': str(existing['id']), 'checkout_url': existing['checkout_url'],
                    'provider': existing['provider'], 'simulated': existing['provider'] == 'simulated'}
        attempt = conn.execute('select count(*) n from payments where reservation_id=%s', (r['id'],)).fetchone()['n']
        provider = get_provider()
        p = insert(conn, 'payments', {
            'reservation_id': r['id'], 'user_id': user.user_id, 'provider': provider.name, 'method': method,
            'amount_cents': r['total_cents'], 'idempotency_key': f"res-{r['id']}-{method}-{attempt + 1}",
            'expires_at': r['hold_expires_at']})
        res = provider.create_checkout(p, r, r['title'], method)
        conn.execute("update payments set status='pending', provider_preference_id=%s, checkout_url=%s where id=%s",
                     (res['preference_id'], res['checkout_url'], p['id']))
        insert(conn, 'payment_events', {'payment_id': p['id'], 'from_status': 'created', 'to_status': 'pending', 'source': 'api',
                                        'details': Jsonb({'method': method})})
    return {'payment_id': str(p['id']), 'checkout_url': res['checkout_url'], 'provider': provider.name,
            'simulated': provider.name == 'simulated'}


def apply_status(conn, payment_id, new_status: str, source: str, details: dict | None = None,
                 provider_payment_id: str | None = None, amount_cents: int | None = None, method: str | None = None) -> str:
    p = conn.execute('select * from payments where id=%s for update', (payment_id,)).fetchone()
    if not p:
        raise not_found('Pagamento não encontrado.')
    if amount_cents is not None and new_status == 'approved' and amount_cents != p['amount_cents']:
        audit_event(conn, 'payment.amount_mismatch', 'payments', p['id'], details={'expected': p['amount_cents'], 'got': amount_cents})
        new_status = 'rejected'
        details = {**(details or {}), 'reason': 'valor divergente'}
    if new_status == p['status'] or new_status not in ALLOWED.get(p['status'], set()):
        insert(conn, 'payment_events', {'payment_id': p['id'], 'from_status': p['status'], 'to_status': new_status,
                                        'source': source, 'details': Jsonb({**(details or {}), 'ignored': True})})
        return p['status']
    upd = {'status': new_status}
    if provider_payment_id:
        upd['provider_payment_id'] = provider_payment_id
    if method:
        upd['method'] = method
    if new_status == 'approved':
        upd['approved_at'] = timeutil.now()
    sets = ', '.join(f'{k}=%s' for k in upd)
    conn.execute(f'update payments set {sets} where id=%s', (*upd.values(), p['id']))
    insert(conn, 'payment_events', {'payment_id': p['id'], 'from_status': p['status'], 'to_status': new_status,
                                    'source': source, 'details': Jsonb(details or {})})
    r = conn.execute('select r.*, g.title, c.name console_name from reservations r join games g on g.id=r.game_id '
                     'join consoles c on c.id=r.console_id where r.id=%s', (p['reservation_id'],)).fetchone()
    uid = str(p['user_id'])
    if new_status == 'approved':
        outcome = scheduling.confirm_reservation(conn, r['id'], source)
        if outcome == 'confirmed':
            r2 = conn.execute('select starts_at, ends_at from reservations where id=%s', (r['id'],)).fetchone()
            notifications.notify(conn, uid, 'payment_approved', {
                'jogo': r['title'], 'console': r['console_name'], 'duracao': f"{r['minutes']} minutos",
                'inicio_previsto': timeutil.fmt(r2['starts_at']), 'fim_previsto': timeutil.fmt_time(r2['ends_at']),
                'valor': timeutil.money(p['amount_cents']), 'codigo': r['code'],
                'modo': 'Início estimado (fila)' if r['mode'] == 'queue' else 'Horário reservado'},
                dedupe=f"payment_approved:{p['id']}", link=f"/sessoes/{r['id']}")
        else:
            create_refund(conn, p['id'], p['amount_cents'], 'Pagamento aprovado após expiração da reserva; horário indisponível.', None)
    elif new_status in ('rejected', 'cancelled') and r['status'] == 'pending_payment':
        notifications.notify(conn, uid, 'payment_rejected', {'jogo': r['title'], 'codigo': r['code']},
                             dedupe=f"payment_rejected:{p['id']}:{new_status}", link=f"/checkout/{r['id']}")
    elif new_status in ('refunded', 'charged_back'):
        if r['status'] in ('confirmed', 'pending_payment'):
            scheduling.release_reservation(conn, r, 'refunded' if new_status == 'refunded' else 'cancelled',
                                           f'Pagamento {new_status} no provedor')
        audit_event(conn, f'payment.{new_status}', 'payments', p['id'])
    return new_status


def create_refund(conn, payment_id, amount_cents: int, reason: str, by_user) -> dict:
    p = conn.execute('select * from payments where id=%s for update', (payment_id,)).fetchone()
    if not p or p['status'] != 'approved':
        raise conflict('not_refundable', 'Somente pagamentos aprovados podem ser reembolsados.')
    done = conn.execute("select coalesce(sum(amount_cents),0) s from refunds where payment_id=%s and status in ('requested','processing','completed')",
                        (payment_id,)).fetchone()['s']
    if amount_cents <= 0 or amount_cents + done > p['amount_cents']:
        raise bad_request('invalid_amount', 'Valor de reembolso inválido.')
    rf = insert(conn, 'refunds', {'payment_id': p['id'], 'reservation_id': p['reservation_id'], 'amount_cents': amount_cents,
                                  'reason': reason, 'status': 'processing', 'requested_by': by_user})
    provider = get_provider(p['provider'])
    try:
        pid = provider.refund(p['provider_payment_id'] or str(p['id']), amount_cents, f"refund-{rf['id']}")
    except AppError as e:
        conn.execute("update refunds set status='failed', error=%s where id=%s", (e.message, rf['id']))
        audit_event(conn, 'refund.failed', 'refunds', rf['id'], details={'error': e.message})
        return {**rf, 'status': 'failed'}
    conn.execute("update refunds set status='completed', provider_refund_id=%s, completed_at=%s where id=%s",
                 (pid, timeutil.now(), rf['id']))
    if amount_cents + done == p['amount_cents']:
        conn.execute("update payments set status='refunded' where id=%s", (p['id'],))
        insert(conn, 'payment_events', {'payment_id': p['id'], 'from_status': 'approved', 'to_status': 'refunded',
                                        'source': 'admin' if by_user else 'worker', 'details': Jsonb({'refund_id': str(rf['id'])})})
    r = conn.execute('select * from reservations where id=%s', (p['reservation_id'],)).fetchone()
    if r['status'] == 'needs_resolution':
        conn.execute("update reservations set status='refunded' where id=%s", (r['id'],))
    notifications.notify(conn, str(p['user_id']), 'refund_completed', {'valor': timeutil.money(amount_cents), 'codigo': r['code']},
                         dedupe=f"refund_completed:{rf['id']}", link='/pagamentos')
    audit_event(conn, 'refund.completed', 'refunds', rf['id'], reason=reason)
    return {**rf, 'status': 'completed'}


def record_webhook(conn, provider: str, dedupe_key: str, payload: dict, signature_valid: bool, topic: str | None,
                   resource_id: str | None, ts: int | None) -> dict | None:
    """Retorna o evento se for novo; None se duplicado (idempotência)."""
    row = conn.execute(
        """insert into webhook_events(provider, dedupe_key, topic, resource_id, signature_valid, request_ts, payload,
                                      processing_status)
           values (%s,%s,%s,%s,%s,%s,%s,%s) on conflict (provider, dedupe_key) do nothing returning *""",
        (provider, dedupe_key, topic, resource_id, signature_valid, ts, Jsonb(payload),
         'received' if signature_valid else 'rejected')).fetchone()
    return row


def process_mp_notification(data_id: str, webhook_id=None) -> str:
    """Consulta server-to-server o pagamento no Mercado Pago e aplica o status."""
    provider = get_provider('mercadopago')
    info = provider.get_payment(data_id)
    with tx() as conn:
        if info is None or not info.external_reference:
            if webhook_id:
                conn.execute("update webhook_events set processing_status='ignored', processed_at=%s, error='pagamento não encontrado' where id=%s",
                             (timeutil.now(), webhook_id))
            return 'ignored'
        result = apply_status(conn, info.external_reference, info.status, 'webhook',
                              {'status_detail': info.status_detail}, info.provider_payment_id, info.amount_cents, info.method)
        if webhook_id:
            conn.execute("update webhook_events set processing_status='processed', processed_at=%s where id=%s",
                         (timeutil.now(), webhook_id))
    return result


def simulate_provider_notification(payment_id, outcome: str, user) -> str:
    """SOMENTE DESENVOLVIMENTO: simula o provedor notificando o backend. Passa pelo mesmo registro de
    webhook (idempotente) e pela mesma máquina de estados usada pelo Mercado Pago."""
    if settings.payment_provider != 'simulated' or settings.is_production:
        raise forbidden('Pagamento simulado desabilitado neste ambiente.')
    if outcome not in ('approved', 'rejected'):
        raise bad_request('invalid_outcome', 'Resultado inválido.')
    with tx() as conn:
        p = conn.execute('select * from payments where id=%s', (payment_id,)).fetchone()
        if not p or p['provider'] != 'simulated' or (str(p['user_id']) != user.user_id and not user.has('admin')):
            raise not_found('Pagamento não encontrado.')
        provider_payment_id = f"sim-{security.new_token(6)}"
        ev = record_webhook(conn, 'simulated', f'{payment_id}:{outcome}', {'payment_id': str(payment_id), 'outcome': outcome},
                            True, 'payment', provider_payment_id, None)
        if ev is None:
            return conn.execute('select status from payments where id=%s', (payment_id,)).fetchone()['status']
        res = apply_status(conn, payment_id, outcome, 'webhook', {'simulated': True}, provider_payment_id,
                           p['amount_cents'], p['method'])
        conn.execute("update webhook_events set processing_status='processed', processed_at=%s where id=%s", (timeutil.now(), ev['id']))
    return res


def reconcile_pending(limit: int = 20) -> int:
    """Conciliação: consulta no provedor pagamentos pendentes (Mercado Pago) com referência conhecida."""
    if settings.payment_provider != 'mercadopago' or not settings.mp_access_token:
        return 0
    with tx() as conn:
        rows = conn.execute("""select id, provider_payment_id from payments where provider='mercadopago' and status='pending'
                               and provider_payment_id is not null and updated_at < %s limit %s""",
                            (timeutil.now() - __import__('datetime').timedelta(minutes=2), limit)).fetchall()
    n = 0
    for r in rows:
        try:
            process_mp_notification(r['provider_payment_id'])
            n += 1
        except AppError:
            continue
    return n

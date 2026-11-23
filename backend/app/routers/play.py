"""Rotas do jogador: reservas, cancelamento, checkout, sessões/controles, suporte. Webhooks e agentes."""
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from ..config import settings
from ..core import security, timeutil
from ..core.db import all_, audit_event, insert, one, tx
from ..core.deps import Principal, client_ip, current_user, verified_user
from ..core.errors import AppError, bad_request, conflict, not_found
from ..services import notifications, payments, scheduling, sessions
from ..services.payment_providers import verify_mp_signature
from ..services.settings_store import get_settings, require_enabled
from .common import jsonable

router = APIRouter(tags=['jogador'])


class ReservationIn(BaseModel):
    game_id: uuid.UUID
    minutes: int = Field(ge=1, le=480)
    mode: str = 'queue'
    start_at: datetime | None = None
    coupon_code: str | None = Field(default=None, max_length=30)
    accept_policy: bool = False
    console_id: uuid.UUID | None = None


def _reservation_view(conn, r: dict) -> dict:
    g = one(conn, 'select title, slug, cover_url from games where id=%s', (r['game_id'],))
    c = one(conn, 'select name from consoles where id=%s', (r['console_id'],))
    q = one(conn, 'select position, status from queue_entries where reservation_id=%s', (r['id'],))
    s = one(conn, 'select id, status from game_sessions where reservation_id=%s', (r['id'],))
    pay = one(conn, "select id, status, method, checkout_url, provider from payments where reservation_id=%s order by created_at desc limit 1", (r['id'],))
    cr = one(conn, "select status, decision_notes from cancellation_requests where reservation_id=%s order by created_at desc limit 1", (r['id'],))
    out = jsonable({k: r[k] for k in ('id', 'code', 'status', 'mode', 'minutes', 'starts_at', 'ends_at', 'price_cents', 'discount_cents',
                                      'total_cents', 'hold_expires_at', 'confirmed_at', 'cancel_reason', 'resolution_notes', 'created_at')})
    out.update({'game': jsonable(g), 'console_name': c['name'], 'queue': jsonable(q), 'session': jsonable(s), 'payment': jsonable(pay),
                'cancellation_request': jsonable(cr), 'server_time': timeutil.now().isoformat()})
    return out


@router.post('/reservations', status_code=201)
def create_reservation(body: ReservationIn, request: Request, p: Principal = Depends(verified_user)):
    security.rate_limit(f'reserve:{p.user_id}', 20, 600)
    with tx() as conn:
        r = scheduling.create_reservation(p, body.game_id, body.minutes, body.mode, body.start_at, body.coupon_code,
                                          body.accept_policy, body.console_id, client_ip(request), conn)
        return _reservation_view(conn, r)


@router.get('/me/reservations')
def my_reservations(p: Principal = Depends(current_user), scope: str = 'all'):
    with tx() as conn:
        q = 'select * from reservations where user_id=%s'
        if scope == 'upcoming':
            q += " and status in ('pending_payment','confirmed','active','needs_resolution')"
        rows = all_(conn, q + ' order by starts_at desc limit 200', (p.user_id,))
        return [_reservation_view(conn, r) for r in rows]


@router.get('/me/queues')
def my_queues(p: Principal = Depends(current_user)):
    with tx() as conn:
        rows = all_(conn, """select r.*, q.position from reservations r join queue_entries q on q.reservation_id=r.id
                             where r.user_id=%s and q.status in ('playing','next','waiting') order by r.starts_at""", (p.user_id,))
        out = []
        for r in rows:
            v = _reservation_view(conn, r)
            v['public_queue'] = scheduling.public_queue(conn, r['console_id'], p.user_id)
            out.append(v)
        return out


@router.get('/reservations/{rid}')
def get_reservation(rid: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        r = one(conn, 'select * from reservations where id=%s', (rid,))
        if not r or (str(r['user_id']) != p.user_id and not p.is_staff):   # BOLA/IDOR
            raise not_found('Reserva não encontrada.')
        v = _reservation_view(conn, r)
        v['public_queue'] = scheduling.public_queue(conn, r['console_id'], p.user_id)
        cp = one(conn, "select title, body from policy_documents where kind='cancellation' and is_current")
        v['cancellation_policy'] = jsonable(cp)
        return v


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post('/reservations/{rid}/cancel')
def cancel(rid: uuid.UUID, body: CancelIn, p: Principal = Depends(current_user)):
    with tx() as conn:
        r = one(conn, 'select * from reservations where id=%s for update', (rid,))
        if not r or str(r['user_id']) != p.user_id:
            raise not_found('Reserva não encontrada.')
        if r['status'] == 'pending_payment':
            scheduling.release_reservation(conn, r, 'cancelled', body.reason, p.user_id)
            return {'status': 'cancelled', 'message': 'Reserva provisória cancelada.'}
        if r['status'] != 'confirmed':
            raise conflict('not_cancellable', 'Esta reserva não pode ser cancelada pelo site. Abra um chamado no suporte.')
        st = get_settings(conn)
        minutes_before = (r['starts_at'] - timeutil.now()).total_seconds() / 60
        pay = one(conn, "select * from payments where reservation_id=%s and status='approved' order by created_at desc limit 1", (r['id'],))
        if minutes_before >= int(st['cancel_full_refund_min_minutes_before']):
            scheduling.release_reservation(conn, r, 'cancelled', body.reason, p.user_id)
            insert(conn, 'cancellation_requests', {'reservation_id': r['id'], 'user_id': p.user_id, 'reason': body.reason,
                                                   'status': 'approved', 'decided_at': timeutil.now(),
                                                   'decision_notes': 'Aprovado automaticamente pela política (antecedência).',
                                                   'refund_cents': pay['amount_cents'] if pay else 0})
            if pay:
                payments.create_refund(conn, pay['id'], pay['amount_cents'], 'Cancelamento dentro da política', None)
            notifications.notify(conn, p.user_id, 'reservation_cancelled', {'codigo': r['code']}, dedupe=f"cancel:{r['id']}", link='/pagamentos')
            return {'status': 'cancelled', 'message': 'Reserva cancelada e reembolso solicitado.'}
        if one(conn, "select 1 from cancellation_requests where reservation_id=%s and status='requested'", (r['id'],)):
            raise conflict('already_requested', 'Já existe uma solicitação em análise.')
        insert(conn, 'cancellation_requests', {'reservation_id': r['id'], 'user_id': p.user_id, 'reason': body.reason})
        audit_event(conn, 'reservation.cancellation_requested', 'reservations', r['id'], reason=body.reason)
        return {'status': 'requested', 'message': 'Solicitação registrada. A equipe analisará conforme a política e a legislação aplicável.'}


class CheckoutIn(BaseModel):
    method: str


@router.post('/reservations/{rid}/checkout')
def checkout(rid: uuid.UUID, body: CheckoutIn, p: Principal = Depends(verified_user)):
    security.rate_limit(f'checkout:{p.user_id}', 20, 600)
    return payments.start_checkout(p, rid, body.method)


class SimOutcomeIn(BaseModel):
    outcome: str


@router.get('/payments/{pid}')
def payment_status(pid: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        pay = one(conn, '''select pm.id, pm.status, pm.method, pm.provider, pm.amount_cents, pm.reservation_id, pm.user_id, pm.expires_at,
                                  r.code, g.title from payments pm join reservations r on r.id=pm.reservation_id
                           join games g on g.id=r.game_id where pm.id=%s''', (pid,))
    if not pay or (str(pay['user_id']) != p.user_id and not p.is_staff):
        raise not_found('Pagamento não encontrado.')
    pay.pop('user_id')
    return {**jsonable(pay), 'simulated': pay['provider'] == 'simulated'}


@router.post('/payments/simulated/{pid}/notify')
def simulated_notify(pid: uuid.UUID, body: SimOutcomeIn, p: Principal = Depends(current_user)):
    return {'status': payments.simulate_provider_notification(pid, body.outcome, p), 'simulated': True}


@router.post('/webhooks/mercadopago')
async def mp_webhook(request: Request, x_signature: str = Header(default=''), x_request_id: str = Header(default='')):
    raw = await request.body()
    try:
        payload = json.loads(raw or b'{}')
    except ValueError:
        raise bad_request('invalid_json', 'Payload inválido.')
    data_id = request.query_params.get('data.id') or str((payload.get('data') or {}).get('id') or '')
    topic = request.query_params.get('type') or payload.get('type') or payload.get('topic')
    valid, ts = verify_mp_signature(x_signature, x_request_id, data_id, settings.mp_webhook_secret)
    with tx() as conn:
        ev = payments.record_webhook(conn, 'mercadopago', f"{x_request_id or ''}:{data_id}:{payload.get('action', '')}",
                                     payload, valid, topic, data_id, ts)
    if not valid:
        raise AppError(401, 'invalid_signature', 'Assinatura inválida.')
    if ev is None:
        return {'status': 'duplicate'}
    if topic != 'payment' or not data_id:
        with tx() as conn:
            conn.execute("update webhook_events set processing_status='ignored', processed_at=%s where id=%s", (timeutil.now(), ev['id']))
        return {'status': 'ignored'}
    try:
        status = payments.process_mp_notification(data_id, ev['id'])
    except AppError as e:
        with tx() as conn:
            conn.execute("update webhook_events set processing_status='failed', error=%s where id=%s", (e.message, ev['id']))
        raise AppError(503, 'retry_later', 'Falha temporária; o Mercado Pago reenviará a notificação.')
    return {'status': status}


# ----------------------------------------------------------------- sessões
class JoinIn(BaseModel):
    input_device: str


@router.get('/reservations/{rid}/waiting-room')
def waiting_room(rid: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        r = one(conn, 'select * from reservations where id=%s', (rid,))
        if not r or str(r['user_id']) != p.user_id:
            raise not_found('Reserva não encontrada.')
        v = _reservation_view(conn, r)
        v['public_queue'] = scheduling.public_queue(conn, r['console_id'], p.user_id)
        n = timeutil.now()
        v['seconds_to_start'] = max(0, int((r['starts_at'] - n).total_seconds()))
        v['can_join'] = r['status'] in ('confirmed', 'active') and r['starts_at'] <= n < r['ends_at']
        v['allocation_policy'] = ('O intervalo contratado é exclusivo. Atrasos do jogador não estendem o término; '
                                  'é possível reconectar até o fim do período. Falhas da plataforma são compensadas.')
    return v


@router.post('/reservations/{rid}/join')
def join(rid: uuid.UUID, body: JoinIn, request: Request, p: Principal = Depends(verified_user)):
    return sessions.join(p, rid, body.input_device, client_ip(request), request.headers.get('user-agent', ''))


class InputIn(BaseModel):
    command: dict


@router.post('/sessions/{sid}/input')
def session_input(sid: uuid.UUID, body: InputIn, x_input_token: str = Header(default='')):
    """Autorização exclusivamente pelo token efêmero da sessão (verificado no servidor a cada comando)."""
    return sessions.send_input(sid, x_input_token, body.command)


@router.get('/sessions/{sid}/webrtc-config')
def session_webrtc_config(sid: uuid.UUID, x_input_token: str = Header(default='')):
    """Servidores STUN/TURN para o navegador do jogador (exige o token de controle da sessão)."""
    with tx() as conn:
        sessions._token_session(conn, sid, x_input_token)
    return {'ice_servers': settings.webrtc_ice_servers}


class WebRtcOfferIn(BaseModel):
    offer: dict


@router.post('/sessions/{sid}/webrtc')
def session_webrtc(sid: uuid.UUID, body: WebRtcOfferIn, x_input_token: str = Header(default='')):
    return sessions.webrtc_offer(sid, x_input_token, body.offer)


@router.get('/sessions/{sid}')
def session_state(sid: uuid.UUID, p: Principal = Depends(current_user)):
    return sessions.session_state(p, sid)


@router.post('/sessions/{sid}/disconnect')
def session_disconnect(sid: uuid.UUID, p: Principal = Depends(current_user)):
    sessions.disconnect(p, sid)
    return {'ok': True, 'message': 'Desconectado. Você pode voltar até o fim do período contratado.'}


@router.post('/sessions/{sid}/end')
def session_end(sid: uuid.UUID, p: Principal = Depends(current_user)):
    sessions.user_end(p, sid)
    return {'ok': True}


@router.get('/me/sessions-history')
def sessions_history(p: Principal = Depends(current_user)):
    with tx() as conn:
        rows = all_(conn, '''select s.id, s.status, s.contract_starts_at, s.contract_ends_at, s.first_connected_at, s.ended_at,
                                    s.end_reason, s.seconds_used, s.input_device, g.title, r.code, r.minutes, r.id reservation_id
                             from game_sessions s join reservations r on r.id=s.reservation_id join games g on g.id=r.game_id
                             where s.user_id=%s order by s.contract_starts_at desc limit 200''', (p.user_id,))
    return jsonable(rows)


# ----------------------------------------------------------------- suporte
class TicketIn(BaseModel):
    subject: str = Field(min_length=3, max_length=140)
    category: str = 'geral'
    message: str = Field(min_length=3, max_length=5000)
    reservation_id: uuid.UUID | None = None


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


@router.get('/support/tickets')
def my_tickets(p: Principal = Depends(current_user)):
    with tx() as conn:
        return jsonable(all_(conn, 'select id, subject, category, status, priority, reservation_id, created_at, updated_at from support_tickets where user_id=%s order by updated_at desc', (p.user_id,)))


@router.post('/support/tickets', status_code=201)
def open_ticket(body: TicketIn, p: Principal = Depends(current_user)):
    if body.category not in ('geral', 'pagamento', 'sessao', 'conta', 'reembolso', 'tecnico'):
        raise bad_request('invalid_category', 'Categoria inválida.')
    with tx() as conn:
        require_enabled(conn, 'support_tickets_enabled', 'A abertura de novos chamados está desativada no momento.')
    security.rate_limit(f'ticket:{p.user_id}', 5, 3600)
    with tx() as conn:
        if body.reservation_id and not one(conn, 'select 1 from reservations where id=%s and user_id=%s', (body.reservation_id, p.user_id)):
            raise not_found('Reserva não encontrada.')
        t = insert(conn, 'support_tickets', {'user_id': p.user_id, 'subject': body.subject, 'category': body.category,
                                             'reservation_id': body.reservation_id,
                                             'priority': 'high' if body.category in ('sessao', 'pagamento') else 'normal'})
        insert(conn, 'support_messages', {'ticket_id': t['id'], 'author_user_id': p.user_id, 'body': body.message})
    return jsonable(t)


@router.get('/support/tickets/{tid}')
def ticket(tid: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        t = one(conn, 'select * from support_tickets where id=%s', (tid,))
        if not t or (str(t['user_id']) != p.user_id and not p.is_staff):
            raise not_found('Chamado não encontrado.')
        msgs = all_(conn, '''select m.id, m.body, m.is_staff, m.created_at, u.username author from support_messages m
                             join users u on u.id=m.author_user_id where m.ticket_id=%s order by m.created_at''', (tid,))
    return {**jsonable(t), 'messages': jsonable(msgs)}


@router.post('/support/tickets/{tid}/messages', status_code=201)
def reply(tid: uuid.UUID, body: MessageIn, p: Principal = Depends(current_user)):
    with tx() as conn:
        t = one(conn, 'select * from support_tickets where id=%s for update', (tid,))
        if not t or (str(t['user_id']) != p.user_id and not p.is_staff):
            raise not_found('Chamado não encontrado.')
        if t['status'] == 'closed':
            raise conflict('ticket_closed', 'Chamado encerrado. Abra um novo chamado.')
        m = insert(conn, 'support_messages', {'ticket_id': tid, 'author_user_id': p.user_id, 'body': body.body,
                                              'is_staff': p.is_staff and str(t['user_id']) != p.user_id})
        conn.execute("update support_tickets set status=%s where id=%s",
                     ('in_progress' if m['is_staff'] else ('open' if t['status'] == 'resolved' else t['status']), tid))
        if m['is_staff']:
            notifications.notify(conn, str(t['user_id']), 'support_reply', {'assunto': t['subject']},
                                 dedupe=f"support:{m['id']}", link=f'/suporte/{tid}')
    return jsonable(m)


# ----------------------------------------------------------------- ConsoleAgent
class HeartbeatIn(BaseModel):
    agent_version: str | None = None
    consoles: list[dict] = []


@router.post('/agents/heartbeat')
def agent_heartbeat(body: HeartbeatIn, authorization: str = Header(default='')):
    """Heartbeat/telemetria do ConsoleAgent. Autenticação por token Bearer (hash em console_agents).
    Métricas aceitas apenas como medidas reais informadas pelo agente; nada é inventado aqui."""
    token = authorization.removeprefix('Bearer ').strip()
    if not token:
        raise AppError(401, 'auth_required', 'Token do agente ausente.')
    n = timeutil.now()
    with tx() as conn:
        ag = one(conn, 'select * from console_agents where credential_hash=%s', (security.sha256(token),))
        if not ag:
            raise AppError(401, 'invalid_agent', 'Agente não autorizado.')
        conn.execute("update console_agents set last_heartbeat_at=%s, status='online', agent_version=coalesce(%s, agent_version) where id=%s",
                     (n, body.agent_version, ag['id']))
        fields = ('fps', 'bitrate_kbps', 'rtt_ms', 'jitter_ms', 'packet_loss_pct', 'frames_dropped', 'input_latency_ms', 'temperature_c')
        for c in body.consoles[:32]:
            owned = one(conn, 'select console_id from console_connection_configs where console_id=%s and agent_id=%s',
                        (c.get('console_id'), ag['id']))
            if not owned:
                continue
            vals = {k: c.get(k) for k in fields if isinstance(c.get(k), (int, float))}
            status = c.get('status') if c.get('status') in ('online', 'degraded', 'offline', 'error') else 'online'
            conn.execute(f"insert into console_health_samples(console_id, agent_id, status{''.join(', ' + k for k in vals)}) "
                         f"values (%s,%s,%s{', %s' * len(vals)})", (owned['console_id'], ag['id'], status, *vals.values()))
            conn.execute('update console_connection_configs set last_check_at=%s where console_id=%s', (n, owned['console_id']))
    return {'ok': True, 'server_time': n.isoformat()}

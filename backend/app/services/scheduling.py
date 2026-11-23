"""MOTOR DE DISPONIBILIDADE, FILA E RESERVAS (módulo crítico).

Regra central: para confirmar uma reserva com início S, duração D na janela [A, B):
    S >= A  e  S + D <= B  e  sem conflito com reservas/holds/sessões/manutenção/setup.
B é exclusivo para INICIAR; uma sessão pode TERMINAR exatamente em B.

Concorrência: as linhas dos consoles candidatos são bloqueadas (SELECT ... FOR UPDATE) e a
constraint de exclusão `reservations_no_overlap` no PostgreSQL é a garantia final contra overbooking.
"""
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from ..config import settings as app_settings
from ..core import timeutil
from ..core.db import audit_event, insert
from ..core.errors import AppError, bad_request, conflict, forbidden, not_found, unprocessable
from . import notifications
from .settings_store import disabled_platforms, get_settings

OCCUPYING = ('pending_payment', 'confirmed', 'active')


@dataclass
class Slot:
    console_id: str
    console_code: str
    console_name: str
    assignment_id: str
    window_start: datetime
    window_end: datetime
    start: datetime
    end: datetime
    blocked_until: datetime


def fits_window(start: datetime, minutes: int, a: datetime, b: datetime) -> bool:
    """S >= A e S + D <= B (fim B exclusivo para início)."""
    return start >= a and start + timedelta(minutes=minutes) <= b and start < b


def expire_stale_holds(conn, console_ids: list | None = None) -> int:
    n = timeutil.now()
    q = "select id, user_id, console_id from reservations where status='pending_payment' and hold_expires_at <= %s"
    params: list = [n]
    if console_ids:
        q += ' and console_id = any(%s)'
        params.append(console_ids)
    rows = conn.execute(q + ' for update skip locked', params).fetchall()
    for r in rows:
        conn.execute("update reservations set status='expired' where id=%s", (r['id'],))
        conn.execute("update reservation_holds set released_at=%s, release_reason='expired' where reservation_id=%s and released_at is null", (n, r['id']))
        conn.execute("update coupon_redemptions set status='released' where reservation_id=%s", (r['id'],))
        conn.execute("update payments set status='expired' where reservation_id=%s and status in ('created','pending')", (r['id'],))
        notifications.notify(conn, str(r['user_id']), 'hold_expired', {}, dedupe=f"hold_expired:{r['id']}", link='/sessoes')
    return len(rows)


def game_sellable(conn, game: dict) -> None:
    if game is None or game['deleted_at'] or game['status'] != 'published':
        raise not_found('Jogo indisponível.')
    if game['commercial_license_status'] != 'authorized' and not (game['is_demo'] and app_settings.allow_demo_sales):
        raise AppError(409, 'not_licensed', 'Este jogo ainda não está liberado para exploração comercial.')


def eligible_consoles(conn, game_id, console_id=None, lock: bool = False) -> list[dict]:
    """Consoles publicados, validados e online que possuem vínculo ativo do jogo ainda não encerrado."""
    q = """select c.id, c.code, c.name, c.platform_id from consoles c
           join console_connection_configs cfg on cfg.console_id=c.id
           where c.deleted_at is null and c.is_published and c.status='online' and cfg.validated_at is not null
             and cfg.method <> 'unconfigured'
             and exists (select 1 from console_game_assignments a where a.console_id=c.id and a.game_id=%s
                         and a.status='active' and a.ends_at > %s)
             and not exists (select 1 from platforms pl where pl.id=c.platform_id and pl.code = any(%s))"""
    params: list = [game_id, timeutil.now(), disabled_platforms(conn)]
    if console_id:
        q += ' and c.id=%s'
        params.append(console_id)
    q += ' order by c.id' + (' for update of c' if lock else '')
    return conn.execute(q, params).fetchall()


def _busy(conn, console_id, a: datetime, b: datetime, exclude_reservation=None) -> list[tuple[datetime, datetime]]:
    rows = conn.execute(
        """select starts_at s, blocked_until e from reservations where console_id=%s and status = any(%s)
             and not (status='pending_payment' and hold_expires_at <= %s)
             and starts_at < %s and blocked_until > %s and id is distinct from %s
           union all
           select starts_at, ends_at from blackout_windows where console_id=%s and status='active' and starts_at < %s and ends_at > %s
           union all
           select greatest(s.contract_starts_at, %s), s.contract_ends_at from game_sessions s
             where s.console_id=%s and s.status in ('ready','active') and s.contract_ends_at > %s
           order by 1""",
        (console_id, list(OCCUPYING), timeutil.now(), b, a, exclude_reservation, console_id, b, a,
         timeutil.now(), console_id, a)).fetchall()
    return [(r['s'], r['e']) for r in rows]


def _hours(conn, console_id) -> list[dict]:
    return conn.execute('select weekday, opens_at, closes_at from console_operating_hours where console_id=%s', (console_id,)).fetchall()


def _within_hours(hours: list[dict], start: datetime, end: datetime) -> bool:
    if not hours:
        return True
    ls, le = timeutil.local(start), timeutil.local(end)
    wd = (ls.isoweekday() % 7)  # 0=domingo
    for h in hours:
        if h['weekday'] != wd:
            continue
        o = ls.replace(hour=h['opens_at'].hour, minute=h['opens_at'].minute, second=0, microsecond=0)
        c = ls.replace(hour=h['closes_at'].hour, minute=h['closes_at'].minute, second=0, microsecond=0)
        if ls >= o and le <= c:
            return True
    return False


def _next_opening(hours: list[dict], t: datetime, minutes: int) -> datetime | None:
    """Primeiro instante >= t em que cabe uma sessão de `minutes` dentro do horário de funcionamento."""
    lt = timeutil.local(t)
    for day in range(0, 8):
        d = (lt + timedelta(days=day)) if day == 0 else (lt + timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        wd = d.isoweekday() % 7
        for h in sorted((h for h in hours if h['weekday'] == wd), key=lambda h: h['opens_at']):
            o = d.replace(hour=h['opens_at'].hour, minute=h['opens_at'].minute, second=0, microsecond=0)
            c = d.replace(hour=h['closes_at'].hour, minute=h['closes_at'].minute, second=0, microsecond=0)
            cand = max(o, d)
            if cand + timedelta(minutes=minutes) <= c:
                return cand.astimezone(t.tzinfo)
    return None


def _ceil_minute(t: datetime) -> datetime:
    return t if (t.second == 0 and t.microsecond == 0) else (t.replace(second=0, microsecond=0) + timedelta(minutes=1))


def earliest_in_window(conn, console_id, a: datetime, b: datetime, minutes: int, setup: int, not_before: datetime,
                       exclude_reservation=None) -> datetime | None:
    d, block = timedelta(minutes=minutes), timedelta(minutes=minutes + setup)
    t = _ceil_minute(max(a, not_before))
    busy = _busy(conn, console_id, t, b + timedelta(minutes=setup), exclude_reservation)
    hours = _hours(conn, console_id)
    for _ in range(500):
        if t + d > b:
            return None
        if hours and not _within_hours(hours, t, t + d):
            nxt = _next_opening(hours, t, minutes)
            if nxt is None or nxt <= t:
                return None
            t = _ceil_minute(nxt)
            continue
        clash = next(((s, e) for s, e in busy if s < t + block and e > t), None)
        if clash is None:
            return t
        t = _ceil_minute(clash[1])
    return None


def find_slots(conn, game_id, minutes: int, mode: str, start_at: datetime | None = None, console_id=None,
               lock: bool = False, exclude_reservation=None) -> list[Slot]:
    """Retorna opções viáveis ordenadas (menor início, depois código do console) — regra transparente."""
    st = get_settings(conn)
    n = timeutil.now()
    setup = int(st['setup_minutes'])
    horizon = n + timedelta(days=int(st['booking_horizon_days']))
    consoles = eligible_consoles(conn, game_id, console_id, lock=lock)
    out: list[Slot] = []
    for c in consoles:
        windows = conn.execute(
            """select id, starts_at, ends_at from console_game_assignments where console_id=%s and game_id=%s
               and status='active' and ends_at > %s and starts_at < %s order by starts_at""",
            (c['id'], game_id, n, horizon)).fetchall()
        for w in windows:
            if mode == 'scheduled':
                s = start_at
                if s is None or not fits_window(s, minutes, w['starts_at'], w['ends_at']):
                    continue
                if s < n + timedelta(minutes=int(st['scheduled_lead_minutes'])):
                    continue
                busy = _busy(conn, c['id'], s, s + timedelta(minutes=minutes + setup), exclude_reservation)
                if any(bs < s + timedelta(minutes=minutes + setup) and be > s for bs, be in busy):
                    continue
                if not _within_hours(_hours(conn, c['id']), s, s + timedelta(minutes=minutes)):
                    continue
            else:
                s = earliest_in_window(conn, c['id'], w['starts_at'], w['ends_at'], minutes, setup,
                                       n + timedelta(minutes=int(st['queue_lead_minutes'])), exclude_reservation)
                if s is None:
                    continue
            out.append(Slot(str(c['id']), c['code'], c['name'], str(w['id']), w['starts_at'], w['ends_at'], s,
                            s + timedelta(minutes=minutes), s + timedelta(minutes=minutes + setup)))
            break  # primeira janela viável deste console
    out.sort(key=lambda x: (x.start, x.console_code))
    return out


def _hm(dt: datetime) -> str:
    loc = timeutil.local(dt)
    today = timeutil.local(timeutil.now()).date()
    return loc.strftime('%H:%M') if loc.date() == today else loc.strftime('%d/%m às %H:%M')


def explain_unavailable(conn, game_id, minutes: int, mode: str, start_at: datetime | None) -> str:
    """Motivo claro (e sugestão) quando o pacote não cabe — em vez de uma frase genérica."""
    st = get_settings(conn)
    n = timeutil.now()
    setup = int(st['setup_minutes'])
    consoles = eligible_consoles(conn, game_id)
    if not consoles:
        return 'Nenhum console está oferecendo este jogo no momento.'
    queue = find_slots(conn, game_id, minutes, 'queue')
    first = f' Primeiro horário livre para {minutes} min: {_hm(queue[0].start)}.' if queue else ''
    if mode != 'scheduled' or start_at is None:
        return ('Não há período livre suficiente para este pacote nas janelas em que o jogo está disponível.'
                + (first or ' Tente um pacote menor.'))
    lead = int(st['scheduled_lead_minutes'])
    if start_at < n + timedelta(minutes=lead):
        earliest = n + timedelta(minutes=lead)
        return (f'O horário fixo precisa ser marcado com pelo menos {lead} minutos de antecedência: escolha a partir de '
                f'{_hm(_ceil_minute(earliest))}. Para jogar agora, use "Entrar na fila".')
    reasons = []
    for c in consoles:
        windows = conn.execute("""select starts_at, ends_at from console_game_assignments where console_id=%s and game_id=%s
                                  and status='active' and ends_at > %s order by starts_at""", (c['id'], game_id, n)).fetchall()
        inside = [w for w in windows if w['starts_at'] <= start_at < w['ends_at']]
        if not inside:
            nxt = next((w for w in windows if w['starts_at'] > start_at), None)
            reasons.append(f'o jogo só fica disponível a partir de {_hm(nxt["starts_at"])}' if nxt
                           else 'o jogo não está disponível nesse horário')
            continue
        w = inside[0]
        if start_at + timedelta(minutes=minutes) > w['ends_at']:
            reasons.append(f'o jogo fica disponível só até {_hm(w["ends_at"])} — o pacote de {minutes} min precisa terminar até lá')
            continue
        if not _within_hours(_hours(conn, c['id']), start_at, start_at + timedelta(minutes=minutes)):
            reasons.append('o horário está fora do funcionamento do console')
            continue
        free = earliest_in_window(conn, c['id'], start_at, w['ends_at'], minutes, setup, start_at)
        reasons.append(f'já existe outra reserva nesse horário (com {setup} min de preparação entre jogadores)'
                       + (f'; próximo horário livre: {_hm(free)}' if free else ''))
    msg = reasons[0] if reasons else 'o horário não está livre'
    return msg[0].upper() + msg[1:] + '.'


# ------------------------------------------------------------------ preços
def resolve_package(conn, game: dict, console_id, platform_id, minutes: int, at: datetime) -> dict | None:
    lt = timeutil.local(at).time()
    rows = conn.execute(
        """select * from price_packages where active and minutes=%s
             and (game_id is null or game_id=%s) and (console_id is null or console_id=%s)
             and (platform_id is null or platform_id=%s)
             and (valid_from is null or valid_from <= %s) and (valid_until is null or valid_until > %s)
             and (local_start_time is null or (%s >= local_start_time and %s < local_end_time))
           order by ((game_id is not null)::int*4 + (console_id is not null)::int*2 + (platform_id is not null)::int) desc,
                    price_cents asc limit 1""",
        (minutes, game['id'], console_id, platform_id, at, at, lt, lt)).fetchone()
    if rows and not (game['min_minutes'] <= minutes <= game['max_minutes']):
        return None
    return rows


def offered_minutes(conn, game: dict) -> list[dict]:
    """Pacotes oferecidos (a partir de), calculados no servidor."""
    n = timeutil.now()
    rows = conn.execute(
        """select minutes, min(price_cents) price_cents, bool_or(is_promotion) promo from price_packages
           where active and (game_id is null or game_id=%s) and minutes between %s and %s
             and (valid_from is null or valid_from <= %s) and (valid_until is null or valid_until > %s)
           group by minutes order by minutes""",
        (game['id'], game['min_minutes'], game['max_minutes'], n, n)).fetchall()
    return [dict(r) for r in rows]


def apply_coupon(conn, code: str | None, user_id, game_id, minutes: int, price: int) -> tuple[dict | None, int]:
    if not code:
        return None, 0
    n = timeutil.now()
    c = conn.execute('select * from coupons where code=%s for update', (code.strip().upper(),)).fetchone()
    if not c or not c['active'] or (c['valid_from'] and c['valid_from'] > n) or (c['valid_until'] and c['valid_until'] <= n):
        raise unprocessable('invalid_coupon', 'Cupom inválido ou expirado.')
    if c['game_id'] and str(c['game_id']) != str(game_id):
        raise unprocessable('invalid_coupon', 'Cupom não é válido para este jogo.')
    if c['min_minutes'] and minutes < c['min_minutes']:
        raise unprocessable('invalid_coupon', f"Cupom exige pacote de pelo menos {c['min_minutes']} minutos.")
    used = conn.execute("select count(*) n from coupon_redemptions where coupon_id=%s and status<>'released'", (c['id'],)).fetchone()['n']
    mine = conn.execute("select count(*) n from coupon_redemptions where coupon_id=%s and user_id=%s and status<>'released'", (c['id'], user_id)).fetchone()['n']
    if c['max_redemptions'] is not None and used >= c['max_redemptions']:
        raise unprocessable('invalid_coupon', 'Cupom esgotado.')
    if mine >= c['per_user_limit']:
        raise unprocessable('invalid_coupon', 'Você já utilizou este cupom.')
    disc = price * c['discount_value'] // 100 if c['discount_type'] == 'percent' else c['discount_value']
    return c, min(price, disc)


# ------------------------------------------------------------------ reservas
def _code() -> str:
    return 'LP-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(6))


def create_reservation(user, game_id, minutes: int, mode: str, start_at: datetime | None, coupon_code: str | None,
                       accept_policy: bool, console_id=None, ip: str | None = None, conn=None) -> dict:
    if mode not in ('queue', 'scheduled'):
        raise unprocessable('validation_error', 'Modo de reserva inválido.')
    if mode == 'scheduled':
        if start_at is None or start_at.tzinfo is None:
            raise unprocessable('validation_error', 'Informe data e hora com fuso horário.')
        if start_at.second or start_at.microsecond:
            raise unprocessable('validation_error', 'O horário deve estar em minutos exatos.')
    if not accept_policy:
        raise unprocessable('policy_required', 'É necessário aceitar a política de agendamento, ausência e cancelamento.')
    st = get_settings(conn)
    if mode == 'queue' and not st['queue_mode_enabled']:
        raise AppError(409, 'feature_disabled', 'A compra em modo fila está desativada no momento.')
    if mode == 'scheduled' and not st['scheduled_mode_enabled']:
        raise AppError(409, 'feature_disabled', 'A compra com horário marcado está desativada no momento.')
    if coupon_code and not st['coupons_enabled']:
        raise AppError(409, 'feature_disabled', 'O uso de cupons está desativado no momento.')
    if st['sales_paused']:
        raise AppError(409, 'sales_paused', 'Vendas pausadas temporariamente. ' + (st.get('sales_paused_reason') or ''))
    game = conn.execute('select * from games where id=%s', (game_id,)).fetchone()
    game_sellable(conn, game)
    n = timeutil.now()
    # Reserva provisória abandonada do MESMO jogo (o jogador voltou e reservou de novo): libera o horário antigo para
    # não empilhar holds na fila. Não toca em reservas com pagamento em andamento (Pix gerado, cartão em análise).
    abandoned = conn.execute(
        """select * from reservations r where r.user_id=%s and r.game_id=%s and r.status='pending_payment' and r.hold_expires_at > %s
             and not exists (select 1 from payments p where p.reservation_id=r.id and p.status in ('pending','approved'))
           for update""", (user.user_id, game_id, n)).fetchall()
    for old in abandoned:
        release_reservation(conn, old, 'cancelled', 'Substituída por uma nova reserva do mesmo jogo.', user.user_id)
    pend = conn.execute("select count(*) n from reservations where user_id=%s and status='pending_payment' and hold_expires_at > %s",
                        (user.user_id, n)).fetchone()['n']
    if pend >= int(st['max_pending_holds_per_user']):
        raise conflict('too_many_holds', 'Você já tem reservas aguardando pagamento. Conclua ou cancele antes de criar outra.')
    fut = conn.execute("select count(*) n from reservations where user_id=%s and status in ('confirmed','active') and ends_at > %s",
                       (user.user_id, n)).fetchone()['n']
    if fut >= int(st['max_future_reservations_per_user']):
        raise conflict('too_many_reservations', 'Limite de reservas futuras atingido.')
    if not offered_minutes(conn, game) or minutes not in [o['minutes'] for o in offered_minutes(conn, game)]:
        raise unprocessable('invalid_package', 'Pacote de tempo indisponível para este jogo.')
    # Expira holds vencidos e trava os consoles candidatos (serializa reservas concorrentes por console).
    expire_stale_holds(conn)
    slots = find_slots(conn, game['id'], minutes, mode, start_at, console_id, lock=True)
    chosen, pkg = None, None
    for s in slots:
        plat = conn.execute('select platform_id from consoles where id=%s', (s.console_id,)).fetchone()['platform_id']
        pkg = resolve_package(conn, game, s.console_id, plat, minutes, s.start)
        if pkg:
            chosen = s
            break
    if not chosen:
        raise conflict('slot_unavailable' if mode == 'scheduled' else 'no_availability',
                       explain_unavailable(conn, game['id'], minutes, mode, start_at))
    coupon, discount = apply_coupon(conn, coupon_code, user.user_id, game['id'], minutes, pkg['price_cents'])
    try:
        with conn.transaction():
            r = insert(conn, 'reservations', {
                'code': _code(), 'user_id': user.user_id, 'game_id': game['id'], 'console_id': chosen.console_id,
                'assignment_id': chosen.assignment_id, 'package_id': pkg['id'], 'coupon_id': coupon['id'] if coupon else None,
                'mode': mode, 'minutes': minutes, 'setup_minutes': int(st['setup_minutes']),
                'starts_at': chosen.start, 'ends_at': chosen.end, 'blocked_until': chosen.blocked_until,
                'status': 'pending_payment', 'price_cents': pkg['price_cents'], 'discount_cents': discount,
                'total_cents': pkg['price_cents'] - discount, 'hold_expires_at': n + timedelta(minutes=int(st['hold_minutes']))})
    except psycopg.errors.ExclusionViolation:
        raise conflict('slot_taken', 'Outro jogador acabou de reservar este horário. Tente novamente.')
    insert(conn, 'reservation_holds', {'reservation_id': r['id'], 'expires_at': r['hold_expires_at']})
    if coupon:
        insert(conn, 'coupon_redemptions', {'coupon_id': coupon['id'], 'user_id': user.user_id, 'reservation_id': r['id'],
                                            'discount_cents': discount})
    conn.execute("""insert into policy_acceptances(user_id, policy_id, context, reservation_id, ip)
                    select %s, id, 'checkout', %s, %s from policy_documents where kind='cancellation' and is_current""",
                 (user.user_id, r['id'], ip))
    audit_event(conn, 'reservation.hold_created', 'reservations', r['id'],
                details={'mode': mode, 'minutes': minutes, 'console': chosen.console_code})
    return r


def confirm_reservation(conn, reservation_id, source: str) -> str:
    """Chamado pelo processamento de pagamento aprovado. Retorna o estado final.
    Pagamento tardio: se o hold expirou e o horário ainda está livre, reconfirma; se não, NÃO fura a fila:
    vai para needs_resolution (remarcação/reembolso)."""
    n = timeutil.now()
    r = conn.execute('select * from reservations where id=%s for update', (reservation_id,)).fetchone()
    if r['status'] in ('confirmed', 'active', 'completed'):
        return r['status']
    conn.execute('select id from consoles where id=%s for update', (r['console_id'],))
    if r['status'] == 'pending_payment' and r['hold_expires_at'] > n:
        conn.execute("update reservations set status='confirmed', confirmed_at=%s, hold_expires_at=null where id=%s", (n, r['id']))
        conn.execute("update reservation_holds set released_at=%s, release_reason='paid' where reservation_id=%s and released_at is null", (n, r['id']))
        conn.execute("update coupon_redemptions set status='redeemed' where reservation_id=%s", (r['id'],))
        recompute_queue(conn, r['console_id'])
        return 'confirmed'
    if r['status'] in ('pending_payment', 'expired'):
        still_ok = r['starts_at'] > n and not any(
            bs < r['blocked_until'] and be > r['starts_at'] for bs, be in _busy(conn, r['console_id'], r['starts_at'], r['blocked_until'], r['id']))
        a = conn.execute("select * from console_game_assignments where id=%s and status='active'", (r['assignment_id'],)).fetchone()
        if still_ok and a and fits_window(r['starts_at'], r['minutes'], a['starts_at'], a['ends_at']):
            try:
                with conn.transaction():
                    conn.execute("update reservations set status='confirmed', confirmed_at=%s, hold_expires_at=null where id=%s", (n, r['id']))
                conn.execute("update reservation_holds set release_reason='late_payment_reconfirmed' where reservation_id=%s", (r['id'],))
                conn.execute("update coupon_redemptions set status='redeemed' where reservation_id=%s", (r['id'],))
                audit_event(conn, 'reservation.late_payment_reconfirmed', 'reservations', r['id'], details={'source': source})
                recompute_queue(conn, r['console_id'])
                return 'confirmed'
            except psycopg.errors.ExclusionViolation:
                pass
    conn.execute("""update reservations set status='needs_resolution',
                    resolution_notes='Pagamento aprovado após expiração/cancelamento; horário indisponível. Reembolso ou remarcação necessários.'
                    where id=%s""", (r['id'],))
    audit_event(conn, 'reservation.needs_resolution', 'reservations', r['id'], details={'source': source, 'previous': r['status']})
    notifications.notify(conn, str(r['user_id']), 'needs_resolution', {'codigo': r['code']},
                         dedupe=f"needs_resolution:{r['id']}", link='/sessoes')
    return 'needs_resolution'


def recompute_queue(conn, console_id) -> None:
    """Atualiza queue_entries (posições, próximos, estimativas) a partir das reservas confirmadas."""
    n = timeutil.now()
    rows = conn.execute(
        """select r.id, r.user_id, r.starts_at, r.ends_at, r.status from reservations r
           where r.console_id=%s and r.status in ('confirmed','active') and r.ends_at > %s order by r.starts_at""",
        (console_id, n)).fetchall()
    ids = []
    playing_seen = False
    for i, r in enumerate(rows, start=1):
        is_playing = r['status'] == 'active' or r['starts_at'] <= n
        status = 'playing' if is_playing else ('next' if (i == 1 or (i == 2 and playing_seen)) else 'waiting')
        playing_seen = playing_seen or is_playing
        ids.append(r['id'])
        conn.execute(
            """insert into queue_entries(reservation_id, console_id, user_id, position, status, estimated_start_at, estimated_end_at)
               values (%s,%s,%s,%s,%s,%s,%s)
               on conflict (reservation_id) do update set position=excluded.position, status=excluded.status,
                 estimated_start_at=excluded.estimated_start_at, estimated_end_at=excluded.estimated_end_at
               where queue_entries.position is distinct from excluded.position or queue_entries.status is distinct from excluded.status
                 or queue_entries.estimated_start_at is distinct from excluded.estimated_start_at""",
            (r['id'], console_id, r['user_id'], i, status, r['starts_at'], r['ends_at']))
    conn.execute("""update queue_entries set status=case when status='playing' then 'done' else 'left' end
                    where console_id=%s and status in ('waiting','next','playing') and not (reservation_id = any(%s))""",
                 (console_id, ids))


def compact_queue(conn, console_id) -> int:
    """Quando um intervalo é liberado (cancelamento, término antecipado, no-show), reservas em MODO FILA
    podem ser antecipadas (nunca atrasadas). Horários fixos não mudam. Usuário é avisado."""
    st = get_settings(conn)
    n = timeutil.now()
    lead = n + timedelta(minutes=max(int(st['queue_lead_minutes']), 5))
    moved = 0
    rows = conn.execute(
        """select r.*, a.starts_at a_start, a.ends_at a_end, g.title from reservations r
           join console_game_assignments a on a.id=r.assignment_id join games g on g.id=r.game_id
           where r.console_id=%s and r.mode='queue' and r.status='confirmed' and r.starts_at > %s order by r.starts_at for update of r""",
        (console_id, lead)).fetchall()
    for r in rows:
        s = earliest_in_window(conn, console_id, r['a_start'], r['a_end'], r['minutes'], r['setup_minutes'], lead, r['id'])
        if s is None or s >= r['starts_at'] - timedelta(minutes=1):
            continue
        conn.execute('update reservations set starts_at=%s, ends_at=%s, blocked_until=%s where id=%s',
                     (s, s + timedelta(minutes=r['minutes']), s + timedelta(minutes=r['minutes'] + r['setup_minutes']), r['id']))
        moved += 1
        notifications.notify(conn, str(r['user_id']), 'queue_changed',
                             {'jogo': r['title'], 'inicio_previsto': timeutil.fmt_time(s),
                              'mensagem': 'Sua vez foi antecipada porque um horário anterior foi liberado.'},
                             dedupe=f"queue_changed:{r['id']}:{int(s.timestamp())}", link=f"/sessoes/{r['id']}")
    if moved:
        recompute_queue(conn, console_id)
    return moved


def release_reservation(conn, r: dict, new_status: str, reason: str, by_user=None) -> None:
    n = timeutil.now()
    conn.execute('update reservations set status=%s, cancelled_at=%s, cancel_reason=%s, cancelled_by=%s, hold_expires_at=null where id=%s',
                 (new_status, n, reason, by_user, r['id']))
    conn.execute("update reservation_holds set released_at=coalesce(released_at,%s), release_reason=coalesce(release_reason,'cancelled') where reservation_id=%s", (n, r['id']))
    conn.execute("update coupon_redemptions set status='released' where reservation_id=%s and status='reserved'", (r['id'],))
    conn.execute("update payments set status='cancelled' where reservation_id=%s and status in ('created','pending')", (r['id'],))
    recompute_queue(conn, r['console_id'])
    compact_queue(conn, r['console_id'])


def public_queue(conn, console_id, viewer_id=None) -> list[dict]:
    """Fila pública: somente nomes públicos (sem e-mail/nome civil)."""
    rows = conn.execute(
        """select q.position, q.status, q.estimated_start_at, q.estimated_end_at, u.username, q.user_id, r.minutes
           from queue_entries q join users u on u.id=q.user_id join reservations r on r.id=q.reservation_id
           where q.console_id=%s and q.status in ('playing','next','waiting') order by q.position""", (console_id,)).fetchall()
    return [{'position': r['position'], 'status': r['status'], 'username': r['username'], 'minutes': r['minutes'],
             'estimated_start_at': r['estimated_start_at'].isoformat(), 'estimated_end_at': r['estimated_end_at'].isoformat(),
             'is_me': viewer_id is not None and str(r['user_id']) == str(viewer_id)} for r in rows]


def availability_summary(conn, game: dict) -> dict:
    """Informações explícitas de disponibilidade por console para a página do jogo."""
    n = timeutil.now()
    st = get_settings(conn)
    lead = n + timedelta(minutes=int(st['queue_lead_minutes']))
    setup = int(st['setup_minutes'])
    offers = offered_minutes(conn, game)
    consoles_out = []
    for c in eligible_consoles(conn, game['id']):
        cur = conn.execute("""select * from console_game_assignments where console_id=%s and game_id=%s and status='active'
                              and starts_at <= %s and ends_at > %s""", (c['id'], game['id'], n, n)).fetchone()
        nxt = conn.execute("""select * from console_game_assignments where console_id=%s and game_id=%s and status='active'
                              and starts_at > %s order by starts_at limit 1""", (c['id'], game['id'], n)).fetchone()
        info = {'console_id': str(c['id']), 'console_name': c['name'], 'console_code': c['code'], 'messages': [],
                'current_window': None, 'next_window': None, 'packages': []}
        q = public_queue(conn, c['id'])
        info['queue_size'] = len(q)
        info['playing_now'] = next((x['username'] for x in q if x['status'] == 'playing'), None)
        if cur:
            remaining = int((cur['ends_at'] - n).total_seconds() // 60)
            info['current_window'] = {'starts_at': cur['starts_at'].isoformat(), 'ends_at': cur['ends_at'].isoformat(),
                                      'remaining_minutes': remaining}
            info['messages'].append(f"{game['title']} disponível até {timeutil.fmt(cur['ends_at'])} (horário de Fortaleza).")
            info['messages'].append(f'Restam {timeutil.fmt_minutes(remaining)} para o encerramento da janela atual.')
            # Maior período livre restante na janela atual (a partir do início mais cedo possível).
            longest = 0
            for m in range(5, min(remaining, game['max_minutes']) + 1, 5):
                if earliest_in_window(conn, c['id'], cur['starts_at'], cur['ends_at'], m, setup, lead) is not None:
                    longest = m
            info['last_free_minutes'] = longest
            if remaining <= 120:
                info['messages'].append(f"Atenção: o jogo ficará disponível somente até às {timeutil.fmt_time(cur['ends_at'])}.")
            if longest and offers and longest < max(o['minutes'] for o in offers):
                info['messages'].append(f'Último período livre nesta janela: {longest} minutos.')
            if not longest:
                info['messages'].append('Indisponível para novas reservas nesta janela.')
        if nxt:
            info['next_window'] = {'starts_at': nxt['starts_at'].isoformat(), 'ends_at': nxt['ends_at'].isoformat()}
            if not cur:
                info['messages'].append(f"Próxima disponibilidade: {timeutil.fmt(nxt['starts_at'])}.")
        for o in offers:
            s = find_slots(conn, game['id'], o['minutes'], 'queue', console_id=c['id'])
            info['packages'].append({'minutes': o['minutes'], 'price_cents': o['price_cents'], 'fits': bool(s),
                                     'estimated_start_at': s[0].start.isoformat() if s else None,
                                     'estimated_end_at': s[0].end.isoformat() if s else None})
        consoles_out.append(info)
    return {'server_time': n.isoformat(), 'consoles': consoles_out,
            'notice': 'Previsões dependem de reservas anteriores e de ajustes operacionais; o horário só é garantido após a confirmação do pagamento.'}

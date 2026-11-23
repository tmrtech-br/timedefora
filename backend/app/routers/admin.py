"""API administrativa. Autorização SEMPRE no servidor: operador < administrador < superadministrador.
Todas as mutações ficam no audit_logs (triggers) e ações sensíveis exigem justificativa."""
import csv
import io
import re
import time as time_mod
import uuid
from datetime import date, datetime, time, timedelta

import psycopg
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from ..config import settings
from ..core import security, timeutil
from ..core.db import all_, audit_event, insert, one, tx, update
from ..core.deps import Principal, require_role
from ..core.errors import AppError, bad_request, conflict, forbidden, not_found, unprocessable
from ..gamebridge import METHODS, AdapterError, get_adapter, method_info
from ..services import notifications, payments, scheduling, sessions
from ..services.consoles import console_ref
from ..services.settings_store import DEFAULTS, get_settings
from .common import jsonable

router = APIRouter(prefix='/admin', tags=['admin'])
OPERATOR = require_role('operator')
ADMIN = require_role('admin')
SUPER = require_role('superadmin')
SLUG_RE = re.compile(r'^[a-z0-9-]{2,80}$')


def _patch(conn, table: str, row_id, data: dict, allowed: set[str]) -> dict:
    data = {k: v for k, v in data.items() if k in allowed}
    row = update(conn, table, row_id, data)
    if not row:
        raise not_found()
    return row


def _future_paid(conn, console_id=None, assignment_id=None, start=None, end=None) -> list[dict]:
    q = "select id, code, user_id, starts_at, ends_at, status from reservations where status in ('pending_payment','confirmed','active') and ends_at > %s"
    params: list = [timeutil.now()]
    if console_id:
        q += ' and console_id=%s'
        params.append(console_id)
    if assignment_id:
        q += ' and assignment_id=%s'
        params.append(assignment_id)
    if start and end:
        q += ' and starts_at < %s and blocked_until > %s'
        params += [end, start]
    return all_(conn, q, params)


def _resolve_affected(conn, affected: list[dict], resolution: str | None, reason: str, actor: str) -> None:
    """Nunca cancela reserva paga silenciosamente: exige resolução explícita, notifica, reembolsa e audita."""
    if not affected:
        return
    if resolution != 'cancel_and_refund':
        raise conflict('affected_reservations', f'{len(affected)} reserva(s) de clientes seriam afetadas. Use a opção "reembolsar afetados" '
                       '(com justificativa) para cancelá-las com reembolso integral.',
                       reservations=[{'code': r['code'], 'starts_at': r['starts_at'].isoformat(), 'status': r['status']} for r in affected])
    if len(reason.strip()) < 5:
        raise unprocessable('reason_required', 'Informe a justificativa.')
    for r in affected:
        full = one(conn, 'select * from reservations where id=%s for update', (r['id'],))
        s = one(conn, "select * from game_sessions where reservation_id=%s and status in ('ready','active')", (r['id'],))
        if s:
            sessions.end_session(conn, s, 'admin')
        scheduling.release_reservation(conn, full, 'cancelled', f'Alteração operacional: {reason}', actor)
        pay = one(conn, "select * from payments where reservation_id=%s and status='approved'", (r['id'],))
        if pay:
            payments.create_refund(conn, pay['id'], pay['amount_cents'], f'Alteração operacional: {reason}', actor)
        notifications.notify(conn, str(r['user_id']), 'schedule_changed', {'codigo': r['code'], 'motivo': reason},
                             dedupe=f"schedule_changed:{r['id']}", link='/sessoes')
        audit_event(conn, 'reservation.cancelled_by_admin', 'reservations', r['id'], reason=reason)


# ================================================================== visão geral
@router.get('/overview')
def overview(p: Principal = Depends(OPERATOR)):
    n = timeutil.now()
    today = timeutil.local(n).replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    with tx() as conn:
        k = one(conn, """select
          (select count(*) from users where deleted_at is null) users_total,
          (select count(distinct user_id) from auth_sessions where revoked_at is null and last_seen_at > %s) users_online,
          (select count(*) from consoles where deleted_at is null) consoles_total,
          (select count(*) from consoles where deleted_at is null and is_published and status='online') consoles_available,
          (select count(distinct console_id) from game_sessions where status in ('ready','active')) consoles_busy,
          (select count(*) from consoles where deleted_at is null and status='maintenance') consoles_maintenance,
          (select count(*) from consoles where deleted_at is null and status in ('offline','degraded')) consoles_offline,
          (select count(*) from game_sessions where status in ('ready','active')) sessions_active,
          (select count(*) from queue_entries where status in ('next','waiting')) queue_waiting,
          (select coalesce(sum(amount_cents),0) from payments where status='approved' and approved_at >= %s) revenue_today,
          (select coalesce(sum(amount_cents),0) from payments where status='approved' and approved_at >= %s) revenue_month,
          (select coalesce(sum(r.minutes),0) from reservations r where r.status in ('confirmed','active','completed','no_show') and r.confirmed_at >= %s) minutes_sold_month,
          (select count(*) from payments where status in ('created','pending')) payments_pending,
          (select count(*) from service_incidents where resolved_at is null) incidents_open,
          (select count(*) from notification_deliveries where status='failed') deliveries_failed,
          (select count(*) from reservations where status='needs_resolution') reservations_needing_resolution,
          (select count(*) from cancellation_requests where status='requested') cancellation_requests_open""",
                (n - timedelta(minutes=15), today, month, month))
        util = all_(conn, """select c.name, coalesce(sum(extract(epoch from (least(r.ends_at,%s)-greatest(r.starts_at,%s))))/60,0)::int minutes
                             from consoles c left join reservations r on r.console_id=c.id and r.status in ('active','completed','confirmed')
                               and r.starts_at < %s and r.ends_at > %s
                             where c.deleted_at is null group by c.name order by c.name""", (n, month, n, month))
        top = all_(conn, """select g.title, count(r.id) reservations, coalesce(sum(p.amount_cents),0) revenue_cents
                            from games g left join reservations r on r.game_id=g.id and r.confirmed_at >= %s
                            left join payments p on p.reservation_id=r.id and p.status='approved'
                            where g.deleted_at is null group by g.title order by 2 desc limit 10""", (month,))
        alerts = all_(conn, 'select id, kind, description, started_at from service_incidents where resolved_at is null order by started_at desc limit 20')
    return {'kpis': jsonable(k), 'utilization_month': jsonable(util), 'top_games_month': jsonable(top), 'alerts': jsonable(alerts),
            'role': sorted(p.roles)}


# ================================================================== jogos
class GameIn(BaseModel):
    slug: str
    title: str = Field(min_length=1, max_length=120)
    short_description: str = Field(default='', max_length=300)
    description: str = Field(default='', max_length=5000)
    cover_url: str | None = None
    banner_url: str | None = None
    trailer_url: str | None = None
    trailer_licensed: bool = False
    age_rating: str | None = None
    release_date: date | None = None
    requirements: str = ''
    status: str = 'draft'
    min_minutes: int = 10
    max_minutes: int = 120
    featured_manual: bool = False
    featured_rank: int | None = None
    image_rights_notes: str = ''
    stream_rights_allowed: bool = False
    platform_codes: list[str] = []
    genres: list[str] = []


GAME_FIELDS = {'slug', 'title', 'short_description', 'description', 'cover_url', 'banner_url', 'trailer_url', 'trailer_licensed',
               'age_rating', 'release_date', 'requirements', 'status', 'min_minutes', 'max_minutes', 'featured_manual',
               'featured_rank', 'image_rights_notes', 'stream_rights_allowed'}


def _set_game_relations(conn, game_id, platform_codes: list[str] | None, genres: list[str] | None) -> None:
    if platform_codes is not None:
        plats = all_(conn, 'select id from platforms where code = any(%s)', (platform_codes,))
        if len(plats) != len(set(platform_codes)):
            raise unprocessable('invalid_platform', 'Plataforma inválida.')
        conn.execute('delete from game_platforms where game_id=%s and not (platform_id = any(%s))', (game_id, [x['id'] for x in plats]))
        for pl in plats:
            conn.execute('insert into game_platforms(game_id, platform_id) values (%s,%s) on conflict do nothing', (game_id, pl['id']))
    if genres is not None:
        ids = []
        for name in {g.strip() for g in genres if g.strip()}:
            slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
            g = one(conn, 'insert into genres(slug, name) values (%s,%s) on conflict (slug) do update set name=genres.name returning id', (slug, name))
            ids.append(g['id'])
        conn.execute('delete from game_genres where game_id=%s and not (genre_id = any(%s))', (game_id, ids))
        for gid in ids:
            conn.execute('insert into game_genres(game_id, genre_id) values (%s,%s) on conflict do nothing', (game_id, gid))


def _game_view(conn, g: dict) -> dict:
    out = jsonable(g)
    out['platform_codes'] = [r['code'] for r in all_(conn, 'select p.code from game_platforms gp join platforms p on p.id=gp.platform_id where gp.game_id=%s', (g['id'],))]
    out['genres'] = [r['name'] for r in all_(conn, 'select ge.name from game_genres gg join genres ge on ge.id=gg.genre_id where gg.game_id=%s', (g['id'],))]
    return out


@router.get('/games')
def list_games(p: Principal = Depends(OPERATOR), include_deleted: bool = False):
    with tx() as conn:
        rows = all_(conn, 'select * from games ' + ('' if include_deleted else 'where deleted_at is null ') + 'order by title')
        return [_game_view(conn, g) for g in rows]


@router.post('/games', status_code=201)
def create_game(body: GameIn, p: Principal = Depends(ADMIN)):
    if not SLUG_RE.match(body.slug):
        raise unprocessable('validation_error', 'Slug inválido (use letras minúsculas, números e hífen).')
    if body.status == 'published':
        raise unprocessable('validation_error', 'Cadastre como rascunho e publique após configurar licença e pacotes.')
    with tx() as conn:
        if one(conn, 'select 1 from games where slug=%s', (body.slug,)):
            raise conflict('slug_taken', 'Já existe um jogo com este slug.')
        data = {k: v for k, v in body.model_dump().items() if k in GAME_FIELDS}
        g = insert(conn, 'games', {**data, 'created_by': p.user_id, 'updated_by': p.user_id})
        _set_game_relations(conn, g['id'], body.platform_codes, body.genres)
        return _game_view(conn, g)


@router.get('/games/{gid}')
def get_game(gid: uuid.UUID, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        g = one(conn, 'select * from games where id=%s', (gid,))
        if not g:
            raise not_found()
        return _game_view(conn, g)


@router.patch('/games/{gid}')
def patch_game(gid: uuid.UUID, body: dict, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        g = one(conn, 'select * from games where id=%s and deleted_at is null for update', (gid,))
        if not g:
            raise not_found()
        if 'slug' in body and not SLUG_RE.match(str(body['slug'])):
            raise unprocessable('validation_error', 'Slug inválido.')
        if body.get('status') == 'published':
            if not all_(conn, 'select 1 from game_platforms where game_id=%s', (gid,)) and not body.get('platform_codes'):
                raise unprocessable('validation_error', 'Informe ao menos uma plataforma antes de publicar.')
        if body.get('status') in ('unpublished', 'archived') and _future_paid_for_game(conn, gid) and body.get('resolution') != 'keep_existing':
            raise conflict('affected_reservations', 'Há reservas futuras deste jogo. Envie resolution="keep_existing" para despublicar '
                           'mantendo as reservas existentes (novas vendas serão bloqueadas).')
        row = _patch(conn, 'games', gid, {**body, 'updated_by': p.user_id}, GAME_FIELDS | {'updated_by'})
        _set_game_relations(conn, gid, body.get('platform_codes'), body.get('genres'))
        return _game_view(conn, row)


def _future_paid_for_game(conn, gid) -> list:
    return all_(conn, "select id from reservations where game_id=%s and status in ('pending_payment','confirmed','active') and ends_at > %s",
                (gid, timeutil.now()))


class LicenseIn(BaseModel):
    status: str
    doc_url: str | None = None
    notes: str = Field(default='', max_length=2000)


@router.post('/games/{gid}/license')
def set_license(gid: uuid.UUID, body: LicenseIn, p: Principal = Depends(ADMIN)):
    if body.status not in ('not_verified', 'pending', 'authorized', 'denied'):
        raise unprocessable('validation_error', 'Situação inválida.')
    if body.status == 'authorized' and not body.doc_url:
        raise unprocessable('doc_required', 'Anexe a documentação de autorização comercial (URL do documento).')
    with tx() as conn:
        row = _patch(conn, 'games', gid, {'commercial_license_status': body.status, 'commercial_license_doc_url': body.doc_url,
                                          'commercial_license_notes': body.notes, 'license_verified_by': p.user_id,
                                          'license_verified_at': timeutil.now()},
                     {'commercial_license_status', 'commercial_license_doc_url', 'commercial_license_notes', 'license_verified_by', 'license_verified_at'})
        audit_event(conn, 'game.license_changed', 'games', gid, reason=body.notes, details={'status': body.status})
        return _game_view(conn, row)


@router.delete('/games/{gid}')
def delete_game(gid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        if _future_paid_for_game(conn, gid):
            raise conflict('has_reservations', 'Não é possível excluir: há reservas futuras deste jogo.')
        conn.execute("update games set deleted_at=%s, status='archived' where id=%s", (timeutil.now(), gid))
        conn.execute("update console_game_assignments set status='archived' where game_id=%s and status='active' and starts_at > %s", (gid, timeutil.now()))
    return {'ok': True}


# ================================================================== plataformas / agentes / dispositivos
@router.get('/platforms')
def platforms(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, 'select * from platforms order by name'))


@router.get('/connection-methods')
def connection_methods(platform: str | None = None, p: Principal = Depends(OPERATOR)):
    """Matriz de compatibilidade: indica o que é APLICÁVEL, não o que está garantido."""
    out = []
    for m in METHODS:
        item = dict(m)
        item['applicable'] = platform is None or not m['platforms'] or platform in m['platforms']
        item['operational'] = get_adapter(m['method']).operational if m['method'] != 'unconfigured' else False
        out.append(item)
    return out


class AgentIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    host_name: str = Field(min_length=1, max_length=120)
    description: str = ''
    location: str = ''
    endpoint_url: str | None = None
    is_simulated: bool = False
    cpu_limit_pct: int | None = None
    ram_limit_mb: int | None = None
    network_limit_mbps: int | None = None


@router.get('/agents')
def agents(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        rows = all_(conn, '''select id, name, host_name, description, location, agent_version, endpoint_url, status, is_simulated,
                                    last_heartbeat_at, cpu_limit_pct, ram_limit_mb, network_limit_mbps, created_at,
                                    credential_hash is not null has_credential, outbound_token_enc is not null has_outbound_token
                             from console_agents order by name''')
    return jsonable(rows)


def _check_agent_endpoint(url: str | None) -> None:
    """HTTPS obrigatório; em desenvolvimento aceita o agente no mesmo PC (http://127.0.0.1:porta)."""
    if not url:
        return
    local_dev = settings.env != 'production' and url.startswith('http://127.0.0.1')
    if not (url.startswith('https://') or local_dev):
        raise unprocessable('validation_error', 'O endpoint do agente deve usar HTTPS'
                            + ('.' if settings.env == 'production' else ' (em desenvolvimento: http://127.0.0.1:porta).'))


@router.post('/agents', status_code=201)
def create_agent(body: AgentIn, p: Principal = Depends(ADMIN)):
    _check_agent_endpoint(body.endpoint_url)
    inbound, outbound = security.new_token(), security.new_token()
    with tx() as conn:
        row = insert(conn, 'console_agents', {**body.model_dump(), 'credential_hash': security.sha256(inbound),
                                              'outbound_token_enc': security.encrypt(outbound),
                                              'status': 'online' if body.is_simulated else 'unknown'})
    return {'id': str(row['id']), 'agent_token': inbound, 'api_to_agent_token': outbound,
            'message': 'Guarde os tokens no cofre de segredos do agente agora. Eles não serão exibidos novamente.'}


@router.patch('/agents/{aid}')
def patch_agent(aid: uuid.UUID, body: dict, p: Principal = Depends(ADMIN)):
    _check_agent_endpoint(str(body['endpoint_url']) if body.get('endpoint_url') else None)
    with tx() as conn:
        row = _patch(conn, 'console_agents', aid, body, {'name', 'host_name', 'description', 'location', 'endpoint_url',
                                                         'cpu_limit_pct', 'ram_limit_mb', 'network_limit_mbps'})
    row.pop('credential_hash', None)
    row.pop('outbound_token_enc', None)
    return jsonable(row)


@router.post('/agents/{aid}/rotate-credentials')
def rotate_agent(aid: uuid.UUID, p: Principal = Depends(ADMIN)):
    inbound, outbound = security.new_token(), security.new_token()
    with tx() as conn:
        _patch(conn, 'console_agents', aid, {'credential_hash': security.sha256(inbound), 'outbound_token_enc': security.encrypt(outbound)},
               {'credential_hash', 'outbound_token_enc'})
        audit_event(conn, 'agent.credentials_rotated', 'console_agents', aid)
    return {'agent_token': inbound, 'api_to_agent_token': outbound}


class CaptureIn(BaseModel):
    agent_id: uuid.UUID
    manufacturer: str
    model: str
    device_identifier: str
    input_port: str = 'HDMI-1'
    supports_simultaneous_inputs: bool = False
    max_resolution: str = '1080p'
    max_fps: int = 60
    notes: str = ''


class ControlIn(BaseModel):
    agent_id: uuid.UUID
    adapter_type: str
    manufacturer: str = ''
    model: str = ''
    identifier: str
    mapping_profile: dict = {}
    authorized: bool = False
    notes: str = ''


@router.get('/capture-devices')
def capture_devices(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, '''select d.*, a.name agent_name, cfg.console_id used_by_console
                                      from capture_devices d join console_agents a on a.id=d.agent_id
                                      left join console_connection_configs cfg on cfg.capture_device_id=d.id order by a.name, d.input_port'''))


@router.post('/capture-devices', status_code=201)
def create_capture(body: CaptureIn, p: Principal = Depends(ADMIN)):
    try:
        with tx() as conn:
            if body.input_port != 'HDMI-1':
                multi = one(conn, 'select bool_or(supports_simultaneous_inputs) ok from capture_devices where agent_id=%s and device_identifier=%s',
                            (body.agent_id, body.device_identifier))
                if multi and multi['ok'] is False:
                    raise unprocessable('not_simultaneous', 'Este dispositivo não captura entradas simultaneamente; cada console exige captura independente.')
            return jsonable(insert(conn, 'capture_devices', body.model_dump()))
    except psycopg.errors.UniqueViolation:
        raise conflict('duplicate_device', 'Esta entrada de captura já está cadastrada neste agente.')


@router.delete('/capture-devices/{did}')
def delete_capture(did: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        if one(conn, 'select 1 from console_connection_configs where capture_device_id=%s', (did,)):
            raise conflict('in_use', 'Capturadora vinculada a um console.')
        conn.execute('delete from capture_devices where id=%s', (did,))
    return {'ok': True}


@router.get('/control-adapters')
def control_adapters(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, '''select ca.*, a.name agent_name, cfg.console_id used_by_console from control_adapters ca
                                      join console_agents a on a.id=ca.agent_id
                                      left join console_connection_configs cfg on cfg.control_adapter_id=ca.id order by a.name'''))


@router.post('/control-adapters', status_code=201)
def create_control(body: ControlIn, p: Principal = Depends(ADMIN)):
    try:
        with tx() as conn:
            d = body.model_dump()
            d['mapping_profile'] = Jsonb(d['mapping_profile'])
            return jsonable(insert(conn, 'control_adapters', d))
    except psycopg.errors.UniqueViolation:
        raise conflict('duplicate_adapter', 'Identificador já cadastrado neste agente.')
    except psycopg.errors.CheckViolation:
        raise unprocessable('validation_error', 'Tipo de adaptador inválido.')


@router.delete('/control-adapters/{cid}')
def delete_control(cid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        if one(conn, 'select 1 from console_connection_configs where control_adapter_id=%s', (cid,)):
            raise conflict('in_use', 'Adaptador vinculado a um console.')
        conn.execute('delete from control_adapters where id=%s', (cid,))
    return {'ok': True}


# ================================================================== consoles
class ConsoleIn(BaseModel):
    code: str
    name: str = Field(min_length=2, max_length=60)
    platform_code: str
    manufacturer: str = ''
    model: str = ''
    serial_number: str | None = None
    description: str = ''
    location: str = ''
    notes: str = ''


CONSOLE_FIELDS = {'code', 'name', 'manufacturer', 'model', 'serial_number', 'description', 'location', 'notes', 'updated_by'}


def _console_view(conn, c: dict) -> dict:
    out = jsonable(c)
    cfg = one(conn, 'select * from console_connection_configs where console_id=%s', (c['id'],))
    out['platform_code'] = one(conn, 'select code from platforms where id=%s', (c['platform_id'],))['code']
    out['connection'] = jsonable(cfg)
    if cfg:
        info = method_info(cfg['method'])
        out['connection']['method_label'] = info['label'] if info else cfg['method']
    out['tests'] = jsonable(all_(conn, 'select test_type, result, simulated, message, run_at from console_connection_tests where console_id=%s order by run_at desc limit 20', (c['id'],)))
    out['last_health'] = jsonable(one(conn, 'select * from console_health_samples where console_id=%s order by checked_at desc limit 1', (c['id'],)))
    out['current_assignment'] = jsonable(one(conn, '''select a.id, g.title, a.starts_at, a.ends_at from console_game_assignments a join games g on g.id=a.game_id
                                                      where a.console_id=%s and a.status='active' and a.starts_at <= %s and a.ends_at > %s''',
                                             (c['id'], timeutil.now(), timeutil.now())))
    out['pairing'] = jsonable(one(conn, "select id, status, paired_at, pairing_code_expires_at from remote_play_pairings where console_id=%s order by created_at desc limit 1", (c['id'],)))
    out['active_session'] = jsonable(one(conn, "select id, status, contract_ends_at from game_sessions where console_id=%s and status in ('ready','active')", (c['id'],)))
    return out


@router.get('/consoles')
def list_consoles(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return [_console_view(conn, c) for c in all_(conn, 'select * from consoles where deleted_at is null order by code')]


@router.post('/consoles', status_code=201)
def create_console(body: ConsoleIn, p: Principal = Depends(ADMIN)):
    code = body.code.strip().upper()
    if not re.match(r'^[A-Z0-9-]{3,30}$', code):
        raise unprocessable('validation_error', 'Código inválido (ex.: PS5-01).')
    with tx() as conn:
        plat = one(conn, 'select * from platforms where code=%s', (body.platform_code,))
        if not plat:
            raise unprocessable('invalid_platform', 'Plataforma inválida.')
        if one(conn, 'select 1 from consoles where code=%s and deleted_at is null', (code,)):
            raise conflict('code_taken', 'Já existe console com este código.')
        data = body.model_dump(exclude={'platform_code'})
        data['code'] = code
        c = insert(conn, 'consoles', {**data, 'platform_id': plat['id'], 'manufacturer': body.manufacturer or plat['manufacturer'],
                                      'created_by': p.user_id, 'updated_by': p.user_id})
        insert(conn, 'console_connection_configs', {'console_id': c['id'], 'method': 'unconfigured'})
        return _console_view(conn, c)


@router.get('/consoles/{cid}')
def get_console(cid: uuid.UUID, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        c = one(conn, 'select * from consoles where id=%s and deleted_at is null', (cid,))
        if not c:
            raise not_found()
        out = _console_view(conn, c)
        out['method_history'] = jsonable(all_(conn, 'select id, from_method, to_method, reason, changed_by, created_at from console_method_changes where console_id=%s order by created_at desc', (cid,)))
        out['hours'] = jsonable(all_(conn, 'select weekday, opens_at, closes_at from console_operating_hours where console_id=%s order by weekday, opens_at', (cid,)))
        return out


@router.patch('/consoles/{cid}')
def patch_console(cid: uuid.UUID, body: dict, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        if 'code' in body:
            body['code'] = str(body['code']).upper()
        c = _patch(conn, 'consoles', cid, {**body, 'updated_by': p.user_id}, CONSOLE_FIELDS)
        return _console_view(conn, c)


class StatusIn(BaseModel):
    status: str
    reason: str = Field(min_length=3, max_length=500)
    resolution: str | None = None


@router.post('/consoles/{cid}/status')
def set_console_status(cid: uuid.UUID, body: StatusIn, p: Principal = Depends(OPERATOR)):
    """Operador pode colocar em manutenção/desativar. Reservas afetadas exigem resolução explícita."""
    if body.status not in ('maintenance', 'online', 'disabled'):
        raise unprocessable('validation_error', 'Status inválido.')
    with tx() as conn:
        c = one(conn, 'select * from consoles where id=%s for update', (cid,))
        if not c:
            raise not_found()
        if body.status in ('maintenance', 'disabled'):
            _resolve_affected(conn, _future_paid(conn, console_id=cid), body.resolution, body.reason, p.user_id)
            conn.execute('update consoles set status=%s, is_published=false where id=%s', (body.status, cid))
        else:
            cfg = one(conn, 'select validated_at from console_connection_configs where console_id=%s', (cid,))
            conn.execute('update consoles set status=%s where id=%s', ('online' if cfg and cfg['validated_at'] else 'unconfigured', cid))
        audit_event(conn, 'console.status_changed', 'consoles', cid, reason=body.reason, details={'status': body.status})
        return _console_view(conn, one(conn, 'select * from consoles where id=%s', (cid,)))


@router.delete('/consoles/{cid}')
def delete_console(cid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        c = one(conn, 'select id from consoles where id=%s and deleted_at is null for update', (cid,))
        if not c:
            raise not_found('Console não encontrado.')
        if one(conn, "select 1 from game_sessions where console_id=%s and status in ('ready','active')", (cid,)):
            raise conflict('active_session', 'Não é possível excluir: há uma sessão de jogo ativa neste console.')
        fut = _future_paid(conn, console_id=cid)
        if fut:
            raise conflict('has_reservations', f'Não é possível excluir: {len(fut)} reserva(s) futura(s) neste console. '
                           'Coloque em manutenção com reembolso (ou remarque as reservas) antes de excluir.',
                           reservations=[{'code': r['code'], 'starts_at': r['starts_at'].isoformat()} for r in fut])
        audit_event(conn, 'console.deleted', 'consoles', cid)
        conn.execute("update consoles set deleted_at=%s, is_published=false, status='disabled' where id=%s", (timeutil.now(), cid))
        conn.execute("update console_game_assignments set status='archived' where console_id=%s and status='active' and ends_at > %s", (cid, timeutil.now()))
        conn.execute('update console_connection_configs set capture_device_id=null, control_adapter_id=null, connection_status=%s, method=%s where console_id=%s',
                     ('unconfigured', 'unconfigured', cid))
    return {'ok': True}


class ConnectionIn(BaseModel):
    method: str
    agent_id: uuid.UUID | None = None
    internal_host: str | None = Field(default=None, max_length=120)
    console_identifier: str | None = None
    discovery_mode: str = 'manual'
    network_route: str = 'lan'               # lan | internet_psn | internet_port_forward
    public_host: str | None = Field(default=None, max_length=253)
    public_port: int | None = Field(default=None, ge=1, le=65535)
    resolution: str = '1080p'
    fps: int = 60
    codec: str = 'h264'
    bitrate_kbps: int = 10000
    low_latency: bool = True
    audio_enabled: bool = True
    capture_device_id: uuid.UUID | None = None
    capture_color_space: str | None = None
    video_encoder: str | None = None
    control_adapter_id: uuid.UUID | None = None
    reason: str = ''


HOST_RE = re.compile(r'^(?:\d{1,3}\.){3}\d{1,3}$|^[A-Za-z0-9.-]{1,120}$')


@router.put('/consoles/{cid}/connection')
def set_connection(cid: uuid.UUID, body: ConnectionIn, p: Principal = Depends(ADMIN)):
    if body.method not in ('unconfigured', 'remote_play_chiaki', 'remote_play_direct', 'native_remote_play', 'hdmi_capture', 'simulated'):
        raise unprocessable('validation_error', 'Método de conexão inválido.')
    errors = {}
    with tx() as conn:
        c = one(conn, 'select c.*, p.code platform_code from consoles c join platforms p on p.id=c.platform_id where c.id=%s for update of c', (cid,))
        if not c:
            raise not_found()
        cfg = one(conn, 'select * from console_connection_configs where console_id=%s for update', (cid,))
        info = method_info(body.method)
        if body.method != 'unconfigured' and info['platforms'] and c['platform_code'] not in info['platforms']:
            errors['method'] = f"{info['label']} não é aplicável a {c['platform_code']}."
        if body.method in ('remote_play_chiaki', 'remote_play_direct', 'hdmi_capture', 'native_remote_play') and not body.agent_id:
            errors['agent_id'] = 'Selecione o agente local.'
        if body.network_route not in ('lan', 'internet_psn', 'internet_port_forward'):
            errors['network_route'] = 'Rota de rede inválida.'
        elif body.method == 'remote_play_direct' and body.network_route != 'lan':
            errors['network_route'] = 'O Remote Play direto funciona só na rede local: o PC do agente fica no mesmo lugar do console.'
        elif body.method != 'remote_play_chiaki' and body.network_route != 'lan':
            errors['network_route'] = 'Acesso pela internet só se aplica ao Remote Play.'
        if body.method == 'remote_play_direct':
            if not (body.internal_host and HOST_RE.match(body.internal_host)):
                errors['internal_host'] = 'Informe o IP do console na rede local (fixe o IP no roteador).'
            if not (body.console_identifier or '').strip():
                errors['console_identifier'] = 'Informe a identificação do console (a mesma usada no config.json do agente, ex.: PS4-118).'
        if body.method == 'remote_play_chiaki':
            if body.network_route == 'lan':
                if not (body.internal_host and HOST_RE.match(body.internal_host)) and body.discovery_mode == 'manual':
                    errors['internal_host'] = 'Informe o IP/hostname interno ou use descoberta na LAN.'
            elif body.network_route == 'internet_port_forward':
                if not (body.public_host and HOST_RE.match(body.public_host)):
                    errors['public_host'] = 'Informe o IP público ou o endereço DDNS do roteador onde o console está.'
            elif body.network_route == 'internet_psn' and not (body.console_identifier or '').strip():
                errors['console_identifier'] = 'Informe a identificação do console (nome ou ID exibido no pareamento PSN).'
        if body.network_route != 'lan':
            body.discovery_mode = 'manual'   # descoberta automática só funciona na rede local
        if body.network_route != 'internet_port_forward':
            body.public_host, body.public_port = None, None
        if body.method == 'hdmi_capture':
            if not body.capture_device_id:
                errors['capture_device_id'] = 'Selecione a capturadora/entrada HDMI.'
            if not body.control_adapter_id:
                errors['control_adapter_id'] = 'HDMI não controla o console: selecione um canal de controle separado.'
        if body.agent_id:
            ag = one(conn, 'select * from console_agents where id=%s', (body.agent_id,))
            if not ag:
                errors['agent_id'] = 'Agente inexistente.'
            elif body.method != 'simulated' and ag['is_simulated']:
                errors['agent_id'] = 'Agente simulado só pode ser usado com o método Simulador.'
        for fk, table in (('capture_device_id', 'capture_devices'), ('control_adapter_id', 'control_adapters')):
            v = getattr(body, fk)
            if v:
                row = one(conn, f'select * from {table} where id=%s', (v,))
                if not row or (body.agent_id and str(row['agent_id']) != str(body.agent_id)):
                    errors[fk] = 'Dispositivo inexistente ou pertencente a outro agente.'
                used = one(conn, f'select console_id from console_connection_configs where {fk}=%s and console_id<>%s', (v, cid))
                if used:
                    errors[fk] = 'Já em uso por outro console (canal físico exclusivo).'
                if fk == 'control_adapter_id' and row and not row['authorized']:
                    errors[fk] = 'Adaptador de controle não marcado como autorizado/compatível.'
        if errors:
            raise unprocessable('validation_error', 'Verifique a configuração.', fields=errors)
        if cfg['method'] != body.method:
            # Troca de método: bloqueada com sessão ativa ou reservas futuras.
            active = one(conn, "select 1 from game_sessions where console_id=%s and status in ('ready','active')", (cid,))
            if active:
                raise conflict('active_session', 'Não é possível trocar o método durante uma sessão ativa.')
            fut = _future_paid(conn, console_id=cid)
            if fut:
                raise conflict('affected_reservations', f'{len(fut)} reserva(s) futura(s) neste console. Coloque em manutenção '
                               '(com resolução das reservas) antes de trocar o método.',
                               reservations=[{'code': r['code'], 'starts_at': r['starts_at'].isoformat()} for r in fut])
            insert(conn, 'console_method_changes', {'console_id': cid, 'from_method': cfg['method'], 'to_method': body.method,
                                                    'config_snapshot': Jsonb(jsonable(cfg)), 'reason': body.reason, 'changed_by': p.user_id})
        data = body.model_dump(exclude={'reason'})
        data['connection_status'] = 'unconfigured' if body.method == 'unconfigured' else 'offline'
        # Qualquer alteração exige nova validação completa.
        data.update({'video_validated_at': None, 'audio_validated_at': None, 'control_validated_at': None,
                     'heartbeat_validated_at': None, 'validated_at': None, 'validated_by': None, 'version': cfg['version'] + 1})
        update(conn, 'console_connection_configs', cfg['id'], data)
        conn.execute("update consoles set is_published=false, status=%s where id=%s",
                     ('unconfigured' if body.method == 'unconfigured' else 'offline', cid))
        return _console_view(conn, one(conn, 'select * from consoles where id=%s', (cid,)))


@router.post('/consoles/{cid}/connection/rollback/{change_id}')
def rollback_connection(cid: uuid.UUID, change_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        ch = one(conn, 'select * from console_method_changes where id=%s and console_id=%s', (change_id, cid))
        if not ch:
            raise not_found()
    snap = ch['config_snapshot']
    body = ConnectionIn(**{k: snap.get(k) for k in ConnectionIn.model_fields if k in snap and snap.get(k) is not None},
                        reason=f'Rollback da alteração {change_id}')
    return set_connection(cid, body, p)


TEST_TYPES = ('discover', 'pair', 'connection', 'video_audio', 'controls', 'heartbeat', 'latency')
CONNECT_WAIT = 60.0      # segundos que o teste manual de conexão espera o agente concluir


class PairIn(BaseModel):
    code: str | None = Field(default=None, max_length=12)


@router.delete('/consoles/{cid}/tests')
def clear_tests(cid: uuid.UUID, p: Principal = Depends(ADMIN)):
    """Limpa o HISTÓRICO de testes exibido no painel. As validações (vídeo/áudio/controle/heartbeat) não mudam.
    Cada linha apagada fica registrada na auditoria (trigger), além do evento abaixo."""
    with tx() as conn:
        if not one(conn, 'select 1 from consoles where id=%s and deleted_at is null', (cid,)):
            raise not_found()
        n = conn.execute('delete from console_connection_tests where console_id=%s', (cid,)).rowcount
        audit_event(conn, 'console.tests_cleared', 'consoles', cid, details={'removed': n})
    return {'ok': True, 'removed': n}


@router.post('/consoles/{cid}/tests/{test_type}')
def run_test(cid: uuid.UUID, test_type: str, body: PairIn | None = None, p: Principal = Depends(ADMIN)):
    """Executa teste REAL via adaptador. O simulador responde como simulado; métodos não implementados falham."""
    if test_type not in TEST_TYPES:
        raise not_found()
    with tx() as conn:
        c = one(conn, 'select * from consoles where id=%s and deleted_at is null', (cid,))
        if not c:
            raise not_found()
        ref = console_ref(conn, cid)
    if ref.method == 'unconfigured':
        raise conflict('not_configured', 'Configure o método de conexão antes de testar.')
    adapter = get_adapter(ref.method)
    result, message, data, metrics = 'failed', '', {}, {}
    reported_simulated = in_progress = False
    try:
        if test_type == 'discover':
            r = adapter.discover_console(ref)
        elif test_type == 'pair':
            r = adapter.pair_console(ref, body.code if body else None)
        elif test_type == 'connection':
            # A conexão real (achar, autenticar, primeira imagem) leva de 5 a 60 s; cada chamada ao agente responde
            # em até ~5 s com o andamento. No teste manual do painel esperamos aqui até concluir (máx. CONNECT_WAIT).
            deadline = time_mod.monotonic() + CONNECT_WAIT
            r = adapter.connect(ref)
            while not r.ok and (getattr(r, 'data', {}) or {}).get('running') and time_mod.monotonic() < deadline:
                time_mod.sleep(2)
                r = adapter.connect(ref)
        elif test_type == 'video_audio':
            r = adapter.test_video_audio(ref)
        elif test_type == 'controls':
            r = adapter.test_controls(ref)
        elif test_type == 'latency':
            m = adapter.get_metrics(ref)
            metrics = m.to_dict()
            r = type('R', (), {'ok': m.rtt_ms is not None, 'message': 'Latência medida.' if m.rtt_ms is not None else
                               'Latência não disponível fora de uma sessão: é medida pelo navegador do jogador durante a partida.',
                               'data': {'no_measurement': m.rtt_ms is None}})()
        else:
            r = adapter.health_check(ref)
        result, message, data = ('passed' if r.ok else 'failed'), r.message, getattr(r, 'data', {}) or {}
        if test_type == 'latency' and data.get('no_measurement'):
            result = 'not_available'        # ausência de medição não é falha do console
        reported_simulated = bool(getattr(r, 'simulated', False))
        if not r.ok and data.get('running'):
            # Conexão real em andamento no agente (acordar + conectar leva até 1 min): ainda não é falha.
            in_progress, result = True, 'not_available'
            message = f'{message} Clique em "Testar" de novo em alguns segundos para ver o resultado.'
    except AdapterError as e:
        result = 'not_available' if e.code == 'not_implemented' else 'failed'
        message = e.message
    # Um agente real que responda "simulado" não pode validar canais de um console real.
    simulated = adapter.simulated or reported_simulated
    if reported_simulated and not adapter.simulated and result == 'passed':
        result = 'not_available'
        message = (message + ' ' if message else '') + '(resposta SIMULADA do agente — não valida o console real)'
    n = timeutil.now()
    with tx() as conn:
        insert(conn, 'console_connection_tests', {'console_id': cid, 'test_type': test_type, 'result': result,
                                                  'simulated': simulated, 'message': message,
                                                  'metrics': Jsonb(metrics), 'run_by': p.user_id})
        cfg = one(conn, 'select * from console_connection_configs where console_id=%s for update', (cid,))
        col = {'video_audio': ['video_validated_at', 'audio_validated_at'], 'controls': ['control_validated_at'],
               'heartbeat': ['heartbeat_validated_at'], 'connection': []}.get(test_type)
        if col is not None and not in_progress:
            if result == 'passed':
                for k in col:
                    conn.execute(f'update console_connection_configs set {k}=%s where id=%s', (n, cfg['id']))
                if test_type == 'connection':
                    conn.execute("update console_connection_configs set connection_status='online', last_check_at=%s where id=%s", (n, cfg['id']))
            else:
                for k in col:
                    conn.execute(f'update console_connection_configs set {k}=null, validated_at=null where id=%s', (cfg['id'],))
                conn.execute("update console_connection_configs set connection_status='error', last_check_at=%s where id=%s", (n, cfg['id']))
                conn.execute('update consoles set is_published=false where id=%s', (cid,))
        if test_type == 'pair' and result == 'passed' and data.get('secret_reference'):
            conn.execute("update remote_play_pairings set status='revoked', revoked_at=%s where console_id=%s and status in ('pending','paired')", (n, cid))
            insert(conn, 'remote_play_pairings', {'console_id': cid, 'agent_id': cfg['agent_id'], 'status': 'paired',
                                                  'secret_reference': data['secret_reference'], 'paired_at': n, 'initiated_by': p.user_id})
        cfg = one(conn, 'select * from console_connection_configs where console_id=%s', (cid,))
        if all(cfg[k] for k in ('video_validated_at', 'audio_validated_at', 'control_validated_at', 'heartbeat_validated_at')) \
                and cfg['connection_status'] == 'online' and not cfg['validated_at']:
            conn.execute('update console_connection_configs set validated_at=%s, validated_by=%s where id=%s', (n, p.user_id, cfg['id']))
            conn.execute("update consoles set status='online' where id=%s and status in ('offline','unconfigured','degraded')", (cid,))
    return {'test_type': test_type, 'result': result, 'message': message, 'simulated': simulated,
            'metrics': metrics or None}


@router.post('/consoles/{cid}/publish')
def publish_console(cid: uuid.UUID, p: Principal = Depends(ADMIN)):
    try:
        with tx() as conn:
            conn.execute('update consoles set is_published=true where id=%s', (cid,))
            audit_event(conn, 'console.published', 'consoles', cid)
            return _console_view(conn, one(conn, 'select * from consoles where id=%s', (cid,)))
    except psycopg.errors.CheckViolation:
        raise conflict('not_validated', 'Publicação bloqueada: valide vídeo, áudio, controle, heartbeat e conexão primeiro.')


@router.post('/consoles/{cid}/unpublish')
def unpublish_console(cid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        conn.execute('update consoles set is_published=false where id=%s', (cid,))
        return {'ok': True, 'message': 'Console despublicado. Reservas existentes foram mantidas; novas vendas bloqueadas.'}


class HoursIn(BaseModel):
    hours: list[dict]


@router.put('/consoles/{cid}/hours')
def set_hours(cid: uuid.UUID, body: HoursIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        conn.execute('delete from console_operating_hours where console_id=%s', (cid,))
        for h in body.hours:
            try:
                wd, o, c = int(h['weekday']), time.fromisoformat(h['opens_at']), time.fromisoformat(h['closes_at'])
            except (KeyError, ValueError, TypeError):
                raise unprocessable('validation_error', 'Horário inválido.')
            if not 0 <= wd <= 6 or o >= c:
                raise unprocessable('validation_error', 'Horário inválido.')
            insert(conn, 'console_operating_hours', {'console_id': cid, 'weekday': wd, 'opens_at': o, 'closes_at': c})
    return {'ok': True}


# ================================================================== vínculos (janelas) e calendário
class AssignmentIn(BaseModel):
    console_id: uuid.UUID
    game_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    repeat: str = 'none'        # none | daily | weekly
    occurrences: int = Field(default=1, ge=1, le=60)
    responsible_user_id: uuid.UUID | None = None
    notes: str = ''


def _check_platform(conn, console_id, game_id):
    ok = one(conn, '''select 1 from consoles c join game_platforms gp on gp.platform_id=c.platform_id
                      where c.id=%s and gp.game_id=%s''', (console_id, game_id))
    if not ok:
        raise unprocessable('platform_mismatch', 'A plataforma do console não corresponde às plataformas do jogo.')


@router.get('/assignments')
def list_assignments(console_id: uuid.UUID | None = None, game_id: uuid.UUID | None = None,
                     date_from: datetime | None = None, date_to: datetime | None = None, p: Principal = Depends(OPERATOR)):
    q = '''select a.*, g.title game_title, c.name console_name from console_game_assignments a join games g on g.id=a.game_id
           join consoles c on c.id=a.console_id where a.status='active' '''
    params: list = []
    if console_id: q += ' and a.console_id=%s'; params.append(console_id)
    if game_id: q += ' and a.game_id=%s'; params.append(game_id)
    if date_from: q += ' and a.ends_at > %s'; params.append(date_from)
    if date_to: q += ' and a.starts_at < %s'; params.append(date_to)
    with tx() as conn:
        return jsonable(all_(conn, q + ' order by a.starts_at limit 500', params))


@router.post('/assignments', status_code=201)
def create_assignment(body: AssignmentIn, p: Principal = Depends(ADMIN)):
    if body.starts_at.tzinfo is None or body.ends_at.tzinfo is None:
        raise unprocessable('validation_error', 'Informe data/hora com fuso horário.')
    if body.starts_at >= body.ends_at:
        raise unprocessable('validation_error', 'O início deve ser anterior ao fim.')
    if body.repeat not in ('none', 'daily', 'weekly'):
        raise unprocessable('validation_error', 'Recorrência inválida.')
    step = {'none': None, 'daily': timedelta(days=1), 'weekly': timedelta(days=7)}[body.repeat]
    count = 1 if step is None else body.occurrences
    group = uuid.uuid4() if count > 1 else None
    created = []
    try:
        with tx() as conn:
            c = one(conn, 'select * from consoles where id=%s and deleted_at is null', (body.console_id,))
            g = one(conn, 'select * from games where id=%s and deleted_at is null', (body.game_id,))
            if not c or not g:
                raise not_found('Console ou jogo inexistente.')
            _check_platform(conn, body.console_id, body.game_id)
            for i in range(count):
                off = step * i if step else timedelta(0)
                s, e = body.starts_at + off, body.ends_at + off
                blk = one(conn, "select 1 from blackout_windows where console_id=%s and status='active' and starts_at < %s and ends_at > %s",
                          (body.console_id, e, s))
                row = insert(conn, 'console_game_assignments', {
                    'console_id': body.console_id, 'game_id': body.game_id, 'starts_at': s, 'ends_at': e,
                    'recurrence_group_id': group, 'responsible_user_id': body.responsible_user_id or p.user_id,
                    'notes': body.notes + (' [há manutenção/bloqueio dentro desta janela]' if blk else ''),
                    'created_by': p.user_id, 'updated_by': p.user_id})
                created.append(row)
    except psycopg.errors.ExclusionViolation:
        raise conflict('overlap', 'Conflito: este console já possui um jogo vinculado em parte deste período.')
    return jsonable(created if count > 1 else created[0])


class AssignmentPatch(BaseModel):
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    notes: str | None = None
    reason: str = ''
    resolution: str | None = None


@router.patch('/assignments/{aid}')
def patch_assignment(aid: uuid.UUID, body: AssignmentPatch, p: Principal = Depends(ADMIN)):
    try:
        with tx() as conn:
            a = one(conn, "select * from console_game_assignments where id=%s and status='active' for update", (aid,))
            if not a:
                raise not_found()
            s, e = body.starts_at or a['starts_at'], body.ends_at or a['ends_at']
            if s >= e:
                raise unprocessable('validation_error', 'O início deve ser anterior ao fim.')
            # Reservas que deixariam de caber na nova janela
            affected = [r for r in all_(conn, """select * from reservations where assignment_id=%s and status in ('pending_payment','confirmed','active')""", (aid,))
                        if not (r['starts_at'] >= s and r['ends_at'] <= e)]
            _resolve_affected(conn, affected, body.resolution, body.reason, p.user_id)
            row = update(conn, 'console_game_assignments', aid, {k: v for k, v in {'starts_at': s, 'ends_at': e, 'notes': body.notes,
                                                                                   'updated_by': p.user_id}.items() if v is not None})
            audit_event(conn, 'assignment.changed', 'console_game_assignments', aid, reason=body.reason)
            return jsonable(row)
    except psycopg.errors.ExclusionViolation:
        raise conflict('overlap', 'Conflito com outra janela deste console.')


class ReasonIn(BaseModel):
    reason: str = Field(default='', max_length=500)
    resolution: str | None = None


@router.post('/assignments/{aid}/cancel')
def cancel_assignment(aid: uuid.UUID, body: ReasonIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        a = one(conn, "select * from console_game_assignments where id=%s and status='active' for update", (aid,))
        if not a:
            raise not_found()
        _resolve_affected(conn, _future_paid(conn, assignment_id=aid), body.resolution, body.reason, p.user_id)
        conn.execute("update console_game_assignments set status='cancelled', updated_by=%s where id=%s", (p.user_id, aid))
        audit_event(conn, 'assignment.cancelled', 'console_game_assignments', aid, reason=body.reason)
    return {'ok': True}


class BlackoutIn(BaseModel):
    console_id: uuid.UUID
    starts_at: datetime
    ends_at: datetime
    kind: str = 'maintenance'
    reason: str = Field(min_length=3, max_length=500)
    resolution: str | None = None


@router.get('/blackouts')
def list_blackouts(console_id: uuid.UUID | None = None, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        q = "select b.*, c.name console_name from blackout_windows b join consoles c on c.id=b.console_id where b.status='active' and b.ends_at > %s"
        params: list = [timeutil.now()]
        if console_id:
            q += ' and b.console_id=%s'
            params.append(console_id)
        return jsonable(all_(conn, q + ' order by b.starts_at', params))


@router.post('/blackouts', status_code=201)
def create_blackout(body: BlackoutIn, p: Principal = Depends(OPERATOR)):
    if body.starts_at >= body.ends_at or body.starts_at.tzinfo is None:
        raise unprocessable('validation_error', 'Período inválido.')
    with tx() as conn:
        _resolve_affected(conn, _future_paid(conn, console_id=body.console_id, start=body.starts_at, end=body.ends_at),
                          body.resolution, body.reason, p.user_id)
        row = insert(conn, 'blackout_windows', {**body.model_dump(exclude={'resolution'}), 'created_by': p.user_id})
    return jsonable(row)


@router.delete('/blackouts/{bid}')
def delete_blackout(bid: uuid.UUID, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        conn.execute("update blackout_windows set status='cancelled' where id=%s", (bid,))
    return {'ok': True}


@router.get('/calendar')
def calendar(date_from: datetime, date_to: datetime, console_id: uuid.UUID | None = None, p: Principal = Depends(OPERATOR)):
    if date_to - date_from > timedelta(days=62):
        raise bad_request('range_too_large', 'Período máximo de 62 dias.')
    cf = ' and console_id=%s' if console_id else ''
    extra = [console_id] if console_id else []
    with tx() as conn:
        consoles = all_(conn, 'select id, code, name, status, is_published from consoles where deleted_at is null' + (' and id=%s' if console_id else '') + ' order by code', extra)
        a = all_(conn, f"""select id, console_id, starts_at, ends_at, (select title from games where id=game_id) title, 'assignment' kind
                           from console_game_assignments where status='active' and starts_at < %s and ends_at > %s{cf}""", [date_to, date_from, *extra])
        b = all_(conn, f"""select id, console_id, starts_at, ends_at, reason title, 'blackout' kind from blackout_windows
                           where status='active' and starts_at < %s and ends_at > %s{cf}""", [date_to, date_from, *extra])
        # Reservas que ocupam o console: sem holds vencidos (pagamento não feito) nem canceladas/expiradas.
        r = all_(conn, f"""select r.id, r.console_id, r.starts_at, r.ends_at, r.code || ' · ' || u.username title, 'reservation' kind, r.status,
                                  exists(select 1 from cancellation_requests cr where cr.reservation_id=r.id and cr.status='requested') cancel_requested
                           from reservations r join users u on u.id=r.user_id
                           where r.status in ('pending_payment','confirmed','active','completed','no_show')
                             and not (r.status='pending_payment' and r.hold_expires_at <= %s)
                             and r.starts_at < %s and r.ends_at > %s{cf.replace('console_id', 'r.console_id')}""",
                   [timeutil.now(), date_to, date_from, *extra])
    return {'consoles': jsonable(consoles), 'events': jsonable(a + b + r)}


# ================================================================== preços e cupons
def _must_be_future(v: datetime | None) -> datetime | None:
    """'Válido até' no passado criaria pacote/cupom já vencido."""
    if v is not None and v <= timeutil.now():
        raise ValueError('Valor inválido.')
    return v


class PackageIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    minutes: int = Field(ge=5, le=480)
    price_cents: int = Field(ge=0, le=1_000_000)
    game_id: uuid.UUID | None = None
    console_id: uuid.UUID | None = None
    platform_code: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    local_start_time: time | None = None
    local_end_time: time | None = None
    is_promotion: bool = False
    active: bool = True
    sort_order: int = 0

    @field_validator('valid_until')
    @classmethod
    def _future(cls, v):
        return _must_be_future(v)


@router.get('/packages')
def packages(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, '''select pp.*, g.title game_title, c.name console_name, pl.code platform_code from price_packages pp
                                      left join games g on g.id=pp.game_id left join consoles c on c.id=pp.console_id
                                      left join platforms pl on pl.id=pp.platform_id order by pp.active desc, pp.minutes, pp.price_cents'''))


@router.post('/packages', status_code=201)
def create_package(body: PackageIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        data = body.model_dump(exclude={'platform_code'})
        if body.platform_code:
            pl = one(conn, 'select id from platforms where code=%s', (body.platform_code,))
            if not pl:
                raise unprocessable('invalid_platform', 'Plataforma inválida.')
            data['platform_id'] = pl['id']
        try:
            return jsonable(insert(conn, 'price_packages', {**data, 'created_by': p.user_id}))
        except psycopg.errors.CheckViolation:
            raise unprocessable('validation_error', 'Dados do pacote inválidos (verifique vigência e faixa horária).')


@router.patch('/packages/{pid}')
def patch_package(pid: uuid.UUID, body: dict, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(_patch(conn, 'price_packages', pid, body, {'name', 'price_cents', 'active', 'is_promotion', 'valid_from',
                                                                    'valid_until', 'sort_order'}))


class CouponIn(BaseModel):
    code: str
    description: str = ''
    discount_type: str
    discount_value: int = Field(gt=0)
    max_redemptions: int | None = Field(default=None, ge=1)
    per_user_limit: int = Field(default=1, ge=1)
    min_minutes: int | None = Field(default=None, ge=1)
    game_id: uuid.UUID | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    active: bool = True

    @field_validator('valid_until')
    @classmethod
    def _future(cls, v):
        return _must_be_future(v)


@router.get('/coupons')
def coupons(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, '''select c.*, (select count(*) from coupon_redemptions r where r.coupon_id=c.id and r.status='redeemed') used
                                      from coupons c order by c.created_at desc'''))


@router.post('/coupons', status_code=201)
def create_coupon(body: CouponIn, p: Principal = Depends(ADMIN)):
    try:
        with tx() as conn:
            return jsonable(insert(conn, 'coupons', {**body.model_dump(), 'code': body.code.strip().upper(), 'created_by': p.user_id}))
    except psycopg.errors.UniqueViolation:
        raise conflict('code_taken', 'Código de cupom já existe.')
    except psycopg.errors.CheckViolation:
        raise unprocessable('validation_error', 'Cupom inválido (código A-Z/0-9, percentual até 100).')


@router.patch('/coupons/{cid}')
def patch_coupon(cid: uuid.UUID, body: dict, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(_patch(conn, 'coupons', cid, body, {'description', 'active', 'valid_until', 'max_redemptions'}))


# ================================================================== transmissões públicas
class ChannelIn(BaseModel):
    console_id: uuid.UUID | None = None
    game_id: uuid.UUID | None = None
    provider: str
    channel_name: str | None = None
    external_url: str | None = None
    status: str = 'offline'
    privacy_mask_enabled: bool = True
    notes: str = ''


@router.get('/channels')
def channels(p: Principal = Depends(OPERATOR)):
    """Lista canais com diagnóstico: por que o canal (não) aparece na página do jogo."""
    n = timeutil.now()
    with tx() as conn:
        streams_on = bool(get_settings(conn).get('public_streams_enabled', True))
        rows = all_(conn, '''select s.*, c.name console_name, g.title game_title from streaming_channels s
                             left join consoles c on c.id=s.console_id left join games g on g.id=s.game_id order by s.created_at''')
        for r in rows:
            games = all_(conn, '''select id, title, stream_rights_allowed from games where deleted_at is null and status='published' and
                                  (id=%s or id in (select game_id from console_game_assignments where console_id=%s and status='active'
                                                   and starts_at <= %s and ends_at > %s))''', (r['game_id'], r['console_id'], n, n))
            issues = []
            if not streams_on:
                issues.append('Transmissões estão desligadas em Parâmetros.')
            if r['status'] == 'disabled':
                issues.append('Canal desativado.')
            elif r['status'] != 'live':
                issues.append('Status "offline": a página mostra "não há transmissão agora". Mude para "ao vivo".')
            if not games:
                issues.append('Nenhum jogo publicado ligado a este canal agora (escolha um jogo ou um console com vínculo ativo).')
            blocked = [g['title'] for g in games if not g['stream_rights_allowed']]
            if blocked:
                issues.append('Jogo(s) sem "Transmissão pública autorizada" (Painel → Jogos): ' + ', '.join(blocked) + '.')
            r['issues'] = issues
            r['shown_on'] = [g['title'] for g in games if g['stream_rights_allowed']] if streams_on and r['status'] != 'disabled' else []
        return jsonable(rows)


@router.post('/channels', status_code=201)
def create_channel(body: ChannelIn, p: Principal = Depends(ADMIN)):
    try:
        with tx() as conn:
            return jsonable(insert(conn, 'streaming_channels', body.model_dump()))
    except psycopg.errors.CheckViolation:
        raise unprocessable('validation_error', 'Canal inválido: informe console ou jogo; nome do canal (Twitch/Kick) ou URL https (externo).')


@router.patch('/channels/{chid}')
def patch_channel(chid: uuid.UUID, body: dict, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        try:
            return jsonable(_patch(conn, 'streaming_channels', chid, body, {'status', 'privacy_mask_enabled', 'channel_name', 'external_url', 'notes'}))
        except psycopg.errors.CheckViolation:
            raise unprocessable('validation_error', 'Dados do canal inválidos.')


@router.delete('/channels/{chid}')
def delete_channel(chid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        conn.execute('delete from streaming_channels where id=%s', (chid,))
    return {'ok': True}


# ================================================================== filas, reservas, sessões
@router.get('/queues')
def queues(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        cons = all_(conn, 'select id, code, name, status from consoles where deleted_at is null order by code')
        out = []
        for c in cons:
            rows = all_(conn, '''select q.position, q.status, q.estimated_start_at, q.estimated_end_at, u.username, r.code, r.mode, r.id reservation_id
                                 from queue_entries q join users u on u.id=q.user_id join reservations r on r.id=q.reservation_id
                                 where q.console_id=%s and q.status in ('playing','next','waiting') order by q.position''', (c['id'],))
            out.append({**jsonable(c), 'queue': jsonable(rows)})
    return out


@router.get('/reservations')
def reservations(status: str | None = None, q: str = '', limit: int = Query(100, le=500), p: Principal = Depends(OPERATOR)):
    sql = '''select r.id, r.code, r.status, r.mode, r.minutes, r.starts_at, r.ends_at, r.total_cents, r.created_at, r.resolution_notes,
                    u.username, g.title game_title, c.name console_name
             from reservations r join users u on u.id=r.user_id join games g on g.id=r.game_id join consoles c on c.id=r.console_id where true'''
    params: list = []
    if status:
        sql += ' and r.status=%s'; params.append(status)
    if q:
        sql += ' and (r.code ilike %s or u.username ilike %s)'; params += [f'%{q}%', f'%{q}%']
    with tx() as conn:
        return jsonable(all_(conn, sql + ' order by r.starts_at desc limit %s', [*params, limit]))


class AdminCancelIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    refund: bool = True


@router.post('/reservations/{rid}/cancel')
def admin_cancel(rid: uuid.UUID, body: AdminCancelIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        r = one(conn, 'select * from reservations where id=%s for update', (rid,))
        if not r or r['status'] not in ('pending_payment', 'confirmed', 'active', 'needs_resolution'):
            raise conflict('not_cancellable', 'Reserva não pode ser cancelada neste estado.')
        s = one(conn, "select * from game_sessions where reservation_id=%s and status in ('ready','active')", (rid,))
        if s:
            sessions.end_session(conn, s, 'admin')
        if r['status'] == 'needs_resolution':
            conn.execute("update reservations set status='cancelled', cancel_reason=%s, cancelled_by=%s, cancelled_at=%s where id=%s",
                         (body.reason, p.user_id, timeutil.now(), rid))
        else:
            scheduling.release_reservation(conn, r, 'cancelled', body.reason, p.user_id)
        pay = one(conn, "select * from payments where reservation_id=%s and status='approved'", (rid,))
        if pay and body.refund:
            payments.create_refund(conn, pay['id'], pay['amount_cents'], body.reason, p.user_id)
        notifications.notify(conn, str(r['user_id']), 'reservation_cancelled', {'codigo': r['code']}, dedupe=f'admin_cancel:{rid}', link='/sessoes')
        audit_event(conn, 'reservation.admin_cancel', 'reservations', rid, reason=body.reason, details={'refund': body.refund})
    return {'ok': True}


class RescheduleIn(BaseModel):
    start_at: datetime
    reason: str = Field(min_length=5, max_length=500)


@router.post('/reservations/{rid}/reschedule')
def admin_reschedule(rid: uuid.UUID, body: RescheduleIn, p: Principal = Depends(ADMIN)):
    """Remarcação (ex.: pagamento tardio ou falha operacional). Valida a nova janela com o mesmo motor."""
    with tx() as conn:
        r = one(conn, 'select * from reservations where id=%s for update', (rid,))
        if not r or r['status'] not in ('confirmed', 'needs_resolution'):
            raise conflict('not_reschedulable', 'Reserva não pode ser remarcada neste estado.')
        slots = scheduling.find_slots(conn, r['game_id'], r['minutes'], 'scheduled', body.start_at, lock=True, exclude_reservation=rid)
        if not slots:
            raise conflict('slot_unavailable', 'Horário indisponível para remarcação.')
        sl = slots[0]
        try:
            with conn.transaction():
                conn.execute("""update reservations set console_id=%s, assignment_id=%s, starts_at=%s, ends_at=%s, blocked_until=%s,
                                mode='scheduled', status='confirmed', confirmed_at=coalesce(confirmed_at,%s), resolution_notes=%s where id=%s""",
                             (sl.console_id, sl.assignment_id, sl.start, sl.end, sl.blocked_until, timeutil.now(), body.reason, rid))
        except psycopg.errors.ExclusionViolation:
            raise conflict('slot_taken', 'Horário acabou de ser ocupado.')
        scheduling.recompute_queue(conn, sl.console_id)
        if str(r['console_id']) != sl.console_id:
            scheduling.recompute_queue(conn, r['console_id'])
        notifications.notify(conn, str(r['user_id']), 'schedule_changed', {'codigo': r['code'], 'motivo': f'Remarcada para {timeutil.fmt(sl.start)}. {body.reason}'},
                             dedupe=f'resched:{rid}:{int(sl.start.timestamp())}', link=f'/sessoes/{rid}')
        audit_event(conn, 'reservation.rescheduled', 'reservations', rid, reason=body.reason)
    return {'ok': True, 'starts_at': sl.start.isoformat()}


@router.get('/sessions')
def admin_sessions(active_only: bool = True, p: Principal = Depends(OPERATOR)):
    q = '''select s.id, s.status, s.contract_starts_at, s.contract_ends_at, s.first_connected_at, s.input_device, s.adapter_method,
                  s.end_reason, s.seconds_used, u.username, g.title, c.name console_name, r.code
           from game_sessions s join users u on u.id=s.user_id join reservations r on r.id=s.reservation_id
           join games g on g.id=r.game_id join consoles c on c.id=s.console_id'''
    with tx() as conn:
        return jsonable(all_(conn, q + (" where s.status in ('ready','active')" if active_only else '') + ' order by s.contract_starts_at desc limit 200'))


class TerminateIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    compensation: str = 'none'


@router.post('/sessions/{sid}/terminate')
def terminate(sid: uuid.UUID, body: TerminateIn, p: Principal = Depends(OPERATOR)):
    if body.compensation not in ('none', 'extension', 'reschedule', 'refund'):
        raise unprocessable('validation_error', 'Compensação inválida.')
    with tx() as conn:
        sessions.admin_terminate(conn, sid, body.reason, body.compensation)
        if body.compensation != 'none':
            s = one(conn, 'select * from game_sessions where id=%s', (sid,))
            insert(conn, 'service_incidents', {'console_id': s['console_id'], 'reservation_id': s['reservation_id'], 'kind': 'other',
                                               'description': body.reason, 'compensation': body.compensation, 'created_by': p.user_id})
    return {'ok': True}


# ================================================================== incidentes
class IncidentIn(BaseModel):
    console_id: uuid.UUID | None = None
    reservation_id: uuid.UUID | None = None
    kind: str = 'other'
    description: str = Field(min_length=3, max_length=2000)


@router.get('/incidents')
def incidents(open_only: bool = True, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, 'select i.*, c.name console_name from service_incidents i left join consoles c on c.id=i.console_id'
                             + (' where i.resolved_at is null' if open_only else '') + ' order by i.started_at desc limit 200'))


@router.post('/incidents', status_code=201)
def create_incident(body: IncidentIn, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(insert(conn, 'service_incidents', {**body.model_dump(), 'created_by': p.user_id}))


class ResolveIncidentIn(BaseModel):
    compensation: str = 'none'
    compensation_notes: str = ''
    refund_cents: int | None = None


@router.post('/incidents/{iid}/resolve')
def resolve_incident(iid: uuid.UUID, body: ResolveIncidentIn, p: Principal = Depends(ADMIN)):
    if body.compensation not in ('none', 'extension', 'reschedule', 'refund'):
        raise unprocessable('validation_error', 'Compensação inválida. Escolha: sem compensação, tempo extra, remarcação ou reembolso.')
    if body.refund_cents is not None and body.refund_cents <= 0:
        raise unprocessable('validation_error', 'Valor de reembolso deve ser maior que zero.')
    with tx() as conn:
        i = one(conn, 'select * from service_incidents where id=%s for update', (iid,))
        if not i:
            raise not_found()
        if body.compensation == 'refund' and i['reservation_id']:
            pay = one(conn, "select * from payments where reservation_id=%s and status='approved'", (i['reservation_id'],))
            if pay:
                payments.create_refund(conn, pay['id'], body.refund_cents or pay['amount_cents'], f'Compensação de incidente: {i["description"]}', p.user_id)
        conn.execute('update service_incidents set resolved_at=%s, compensation=%s, compensation_notes=%s where id=%s',
                     (timeutil.now(), body.compensation, body.compensation_notes, iid))
    return {'ok': True}


# ================================================================== financeiro
@router.get('/payments')
def admin_payments(status: str | None = None, p: Principal = Depends(ADMIN)):
    q = '''select pm.id, pm.status, pm.method, pm.provider, pm.amount_cents, pm.created_at, pm.approved_at, pm.provider_payment_id,
                  r.code reservation_code, u.username
           from payments pm join reservations r on r.id=pm.reservation_id join users u on u.id=pm.user_id'''
    with tx() as conn:
        return jsonable(all_(conn, q + (' where pm.status=%s' if status else '') + ' order by pm.created_at desc limit 300', [status] if status else []))


class RefundIn(BaseModel):
    amount_cents: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=500)


@router.post('/payments/{pid}/refund')
def admin_refund(pid: uuid.UUID, body: RefundIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(payments.create_refund(conn, pid, body.amount_cents, body.reason, p.user_id))


@router.post('/payments/{pid}/reconcile')
def reconcile(pid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        pay = one(conn, 'select * from payments where id=%s', (pid,))
    if not pay:
        raise not_found()
    if pay['provider'] != 'mercadopago' or not pay['provider_payment_id']:
        return {'status': pay['status'], 'message': 'Nada a conciliar (sem identificador do provedor).'}
    return {'status': payments.process_mp_notification(pay['provider_payment_id'])}


@router.get('/refunds')
def refunds(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, '''select rf.*, r.code reservation_code from refunds rf join reservations r on r.id=rf.reservation_id
                                      order by rf.created_at desc limit 300'''))


@router.get('/webhooks')
def webhooks(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, 'select id, provider, topic, resource_id, signature_valid, processing_status, error, received_at from webhook_events order by received_at desc limit 200'))


@router.get('/cancellation-requests')
def cancel_requests(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, '''select cr.*, r.code, r.starts_at, u.username from cancellation_requests cr
                                      join reservations r on r.id=cr.reservation_id join users u on u.id=cr.user_id
                                      order by (cr.status='requested') desc, cr.created_at desc limit 200'''))


class DecideIn(BaseModel):
    approve: bool
    notes: str = Field(min_length=3, max_length=1000)
    refund_cents: int | None = None


@router.post('/cancellation-requests/{crid}/decide')
def decide(crid: uuid.UUID, body: DecideIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        cr = one(conn, "select * from cancellation_requests where id=%s and status='requested' for update", (crid,))
        if not cr:
            raise not_found()
        conn.execute('update cancellation_requests set status=%s, decided_by=%s, decided_at=%s, decision_notes=%s, refund_cents=%s where id=%s',
                     ('approved' if body.approve else 'denied', p.user_id, timeutil.now(), body.notes, body.refund_cents, crid))
        r = one(conn, 'select * from reservations where id=%s for update', (cr['reservation_id'],))
        if body.approve:
            if r['status'] in ('confirmed', 'pending_payment'):
                scheduling.release_reservation(conn, r, 'cancelled', cr['reason'], p.user_id)
            pay = one(conn, "select * from payments where reservation_id=%s and status='approved'", (r['id'],))
            if pay and (body.refund_cents is None or body.refund_cents > 0):
                payments.create_refund(conn, pay['id'], body.refund_cents or pay['amount_cents'], body.notes, p.user_id)
        notifications.notify(conn, str(cr['user_id']), 'cancellation_decided',
                             {'codigo': r['code'], 'decisao': 'aprovada' if body.approve else 'negada', 'observacao': body.notes},
                             dedupe=f'cancel_decided:{crid}', link='/sessoes')
    return {'ok': True}


# ================================================================== usuários e papéis
@router.get('/users')
def users(q: str = '', p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        rows = all_(conn, '''select u.id, u.username, u.full_name, u.email, u.status, u.created_at, u.last_login_at,
                                    coalesce((select array_agg(r.code) from role_assignments ra join roles r on r.id=ra.role_id
                                              where ra.user_id=u.id and ra.revoked_at is null), '{}') roles
                             from users u where u.deleted_at is null and (u.username ilike %s or u.email ilike %s or u.full_name ilike %s)
                             order by u.created_at desc limit 100''', (f'%{q}%',) * 3)
    if not p.has('admin'):
        for r in rows:  # operador vê dados mínimos
            r['email'] = r['email'][:2] + '***@' + r['email'].split('@')[-1]
            r['full_name'] = r['full_name'].split(' ')[0]
    return jsonable(rows)


@router.get('/users/{uid}')
def user_detail(uid: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        u = one(conn, '''select id, username, full_name, email, status, email_verified_at, created_at, last_login_at, suspended_reason
                         from users where id=%s''', (uid,))
        if not u:
            raise not_found()
        u = jsonable(u)
        u['reservations'] = jsonable(all_(conn, 'select code, status, starts_at, total_cents from reservations where user_id=%s order by starts_at desc limit 50', (uid,)))
        u['payments'] = jsonable(all_(conn, 'select status, amount_cents, created_at from payments where user_id=%s order by created_at desc limit 50', (uid,)))
        u['roles'] = [r['code'] for r in all_(conn, 'select r.code from role_assignments ra join roles r on r.id=ra.role_id where ra.user_id=%s and ra.revoked_at is null', (uid,))]
        audit_event(conn, 'user.viewed_by_admin', 'users', uid)
    return u


class SuspendIn(BaseModel):
    suspend: bool
    reason: str = Field(min_length=5, max_length=500)


@router.post('/users/{uid}/suspension')
def suspend(uid: uuid.UUID, body: SuspendIn, p: Principal = Depends(ADMIN)):
    if str(uid) == p.user_id:
        raise bad_request('self', 'Você não pode suspender a própria conta.')
    with tx() as conn:
        target_roles = {r['code'] for r in all_(conn, 'select r.code from role_assignments ra join roles r on r.id=ra.role_id where ra.user_id=%s and ra.revoked_at is null', (uid,))}
        if 'superadmin' in target_roles and not p.has('superadmin'):
            raise forbidden()
        conn.execute('update users set status=%s, suspended_reason=%s where id=%s',
                     ('suspended' if body.suspend else 'active', body.reason if body.suspend else None, uid))
        if body.suspend:
            conn.execute("update auth_sessions set revoked_at=%s, revoked_reason='suspended' where user_id=%s and revoked_at is null", (timeutil.now(), uid))
        audit_event(conn, 'user.suspended' if body.suspend else 'user.reactivated', 'users', uid, reason=body.reason)
    return {'ok': True}


class RoleIn(BaseModel):
    role: str
    grant: bool


@router.post('/users/{uid}/roles')
def set_role(uid: uuid.UUID, body: RoleIn, p: Principal = Depends(SUPER)):
    if body.role not in ('client', 'operator', 'admin', 'superadmin'):
        raise unprocessable('validation_error', 'Papel inválido.')
    with tx() as conn:
        role = one(conn, 'select id from roles where code=%s', (body.role,))
        if body.grant:
            conn.execute('insert into role_assignments(user_id, role_id, granted_by) values (%s,%s,%s) on conflict do nothing', (uid, role['id'], p.user_id))
        else:
            if str(uid) == p.user_id and body.role == 'superadmin':
                raise bad_request('self', 'Você não pode remover o próprio papel de superadministrador.')
            conn.execute('update role_assignments set revoked_at=%s, revoked_by=%s where user_id=%s and role_id=%s and revoked_at is null',
                         (timeutil.now(), p.user_id, uid, role['id']))
        conn.execute("update auth_sessions set mfa_verified_at=null where user_id=%s", (uid,))
    return {'ok': True}


# ================================================================== relatórios
def _check_range(date_from: datetime, date_to: datetime) -> None:
    if date_from > date_to:
        raise bad_request('invalid_range', 'A data inicial não pode ser maior que a data final.')


@router.get('/reports/summary')
def report_summary(date_from: datetime, date_to: datetime, p: Principal = Depends(ADMIN)):
    _check_range(date_from, date_to)
    with tx() as conn:
        rev_game = all_(conn, '''select g.title, count(*) payments, sum(pm.amount_cents) revenue_cents from payments pm
                                 join reservations r on r.id=pm.reservation_id join games g on g.id=r.game_id
                                 where pm.status='approved' and pm.approved_at between %s and %s group by g.title order by 3 desc''', (date_from, date_to))
        rev_console = all_(conn, '''select c.name, count(*) payments, sum(pm.amount_cents) revenue_cents, sum(r.minutes) minutes_sold from payments pm
                                    join reservations r on r.id=pm.reservation_id join consoles c on c.id=r.console_id
                                    where pm.status='approved' and pm.approved_at between %s and %s group by c.name order by 3 desc''', (date_from, date_to))
        tot = one(conn, '''select coalesce(sum(amount_cents) filter (where status in ('approved','refunded')),0) gross_cents,
                                  count(*) filter (where status='charged_back') chargebacks
                           from payments where created_at between %s and %s''', (date_from, date_to))
        ref = one(conn, "select coalesce(sum(amount_cents),0) c from refunds where status='completed' and completed_at between %s and %s", (date_from, date_to))
        used = one(conn, '''select coalesce(sum(seconds_used),0)/60 minutes_played, count(*) sessions,
                                   count(*) filter (where end_reason='no_show') no_shows from game_sessions where contract_starts_at between %s and %s''', (date_from, date_to))
    return {'revenue_by_game': jsonable(rev_game), 'revenue_by_console': jsonable(rev_console),
            'gross_cents': tot['gross_cents'], 'refunds_cents': ref['c'], 'net_cents': tot['gross_cents'] - ref['c'],
            'chargebacks': tot['chargebacks'], **jsonable(used)}


@router.get('/reports/export.csv')
def export_csv(kind: str, date_from: datetime, date_to: datetime, p: Principal = Depends(ADMIN)):
    _check_range(date_from, date_to)
    queries = {
        'payments': '''select pm.created_at, pm.approved_at, pm.status, pm.method, pm.provider, pm.amount_cents, r.code reserva, u.username
                       from payments pm join reservations r on r.id=pm.reservation_id join users u on u.id=pm.user_id
                       where pm.created_at between %s and %s order by pm.created_at''',
        'reservations': '''select r.code, r.status, r.mode, r.starts_at, r.ends_at, r.minutes, r.total_cents, g.title jogo, c.name console, u.username
                           from reservations r join games g on g.id=r.game_id join consoles c on c.id=r.console_id join users u on u.id=r.user_id
                           where r.created_at between %s and %s order by r.starts_at''',
        'sessions': '''select s.contract_starts_at, s.contract_ends_at, s.first_connected_at, s.ended_at, s.end_reason, s.seconds_used,
                              s.input_device, c.name console, u.username
                       from game_sessions s join consoles c on c.id=s.console_id join users u on u.id=s.user_id
                       where s.contract_starts_at between %s and %s order by s.contract_starts_at''',
        'refunds': '''select rf.created_at, rf.completed_at, rf.status, rf.amount_cents, rf.reason, r.code reserva from refunds rf
                      join reservations r on r.id=rf.reservation_id where rf.created_at between %s and %s order by rf.created_at''',
    }
    if kind not in queries:
        raise bad_request('invalid_kind', 'Tipo de exportação inválido.')
    with tx() as conn:
        rows = all_(conn, queries[kind], (date_from, date_to))
        audit_event(conn, 'report.exported', None, None, details={'kind': kind})
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=';')
    if rows:
        w.writerow(rows[0].keys())
        for r in rows:
            # Neutraliza injeção de fórmulas em planilhas
            w.writerow([("'" + str(v)) if isinstance(v, str) and v[:1] in '=+-@' else v for v in jsonable(r).values()])
    return StreamingResponse(iter(['﻿' + buf.getvalue()]), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': f'attachment; filename="locaplay-{kind}.csv"'})


# ================================================================== notificações
@router.get('/notification-templates')
def templates(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, 'select * from notification_templates order by code, channel'))


class TemplateIn(BaseModel):
    subject: str = Field(max_length=200)
    body_text: str = Field(max_length=10000)
    body_html: str = Field(default='', max_length=20000)
    active: bool = True


@router.put('/notification-templates/{tid}')
def put_template(tid: uuid.UUID, body: TemplateIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        conn.execute('update notification_templates set subject=%s, body_text=%s, body_html=%s, active=%s, version=version+1, updated_by=%s where id=%s',
                     (body.subject, body.body_text, body.body_html, body.active, p.user_id, tid))
    return {'ok': True}


@router.get('/notification-deliveries')
def deliveries(status: str | None = None, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, '''select id, channel, event_code, to_address, status, attempts, last_error, sent_at, created_at
                                      from notification_deliveries''' + (' where status=%s' if status else '') + ' order by created_at desc limit 200',
                             [status] if status else []))


@router.post('/notification-deliveries/{did}/retry')
def retry_delivery(did: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        conn.execute("update notification_deliveries set status='pending', next_attempt_at=%s, attempts=least(attempts, max_attempts-1) where id=%s",
                     (timeutil.now(), did))
    return notifications.process_deliveries(only_id=str(did))


# ================================================================== auditoria, suporte, LGPD, configurações
@router.get('/audit')
def audit(table_name: str | None = None, record_id: str | None = None, actor: uuid.UUID | None = None,
          limit: int = Query(200, le=1000), p: Principal = Depends(ADMIN)):
    q = 'select a.*, u.username actor_username from audit_logs a left join users u on u.id=a.actor_user_id where true'
    params: list = []
    if table_name: q += ' and a.table_name=%s'; params.append(table_name)
    if record_id: q += ' and a.record_id=%s'; params.append(record_id)
    if actor: q += ' and a.actor_user_id=%s'; params.append(actor)
    if not p.has('superadmin'):
        q += " and coalesce(a.table_name,'') not in ('auth_sessions','mfa_factors','mfa_recovery_codes','password_reset_tokens','email_verification_codes','oauth_states')"
    with tx() as conn:
        return jsonable(all_(conn, q + ' order by a.id desc limit %s', [*params, limit]))


@router.get('/support/tickets')
def support_tickets(status: str | None = None, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        return jsonable(all_(conn, '''select t.*, u.username from support_tickets t join users u on u.id=t.user_id'''
                             + (' where t.status=%s' if status else '') + ' order by t.updated_at desc limit 200', [status] if status else []))


@router.patch('/support/tickets/{tid}')
def patch_ticket(tid: uuid.UUID, body: dict, p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        try:
            return jsonable(_patch(conn, 'support_tickets', tid, body, {'status', 'priority', 'assigned_to'}))
        except psycopg.errors.CheckViolation:
            raise unprocessable('validation_error', 'Status ou prioridade inválidos.')


@router.get('/data-requests')
def data_requests(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, '''select d.*, u.username from data_subject_requests d join users u on u.id=d.user_id
                                      order by (d.status in ('open','in_progress')) desc, d.created_at desc'''))


class DataResolveIn(BaseModel):
    status: str
    resolution: str = Field(min_length=3, max_length=2000)


@router.post('/data-requests/{did}/resolve')
def resolve_data(did: uuid.UUID, body: DataResolveIn, p: Principal = Depends(ADMIN)):
    if body.status not in ('in_progress', 'completed', 'rejected'):
        raise unprocessable('validation_error', 'Status inválido.')
    with tx() as conn:
        d = one(conn, 'select * from data_subject_requests where id=%s for update', (did,))
        if not d:
            raise not_found()
        if d['request_type'] == 'deletion' and body.status == 'completed':
            # Anonimização: mantém registros financeiros exigidos por lei, remove dados pessoais identificáveis.
            anon = f"removido-{str(d['user_id'])[:8]}"
            conn.execute('''update users set full_name='Usuário removido', username=%s, email=%s, password_hash=null, avatar_url=null,
                            status='deleted', deleted_at=%s where id=%s''', (anon, f'{anon}@removido.invalid', timeutil.now(), d['user_id']))
            conn.execute("update auth_sessions set revoked_at=%s, revoked_reason='account_deleted' where user_id=%s and revoked_at is null", (timeutil.now(), d['user_id']))
            conn.execute('update linked_accounts set unlinked_at=%s where user_id=%s and unlinked_at is null', (timeutil.now(), d['user_id']))
        conn.execute('update data_subject_requests set status=%s, resolution=%s, resolved_by=%s, resolved_at=%s where id=%s',
                     (body.status, body.resolution, p.user_id, timeutil.now() if body.status != 'in_progress' else None, did))
    return {'ok': True}


CRITICAL_SETTINGS = {'sales_paused', 'cancel_full_refund_min_minutes_before', 'hold_minutes'}


@router.get('/settings')
def get_all_settings(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        current = get_settings(conn)
    return {'values': current, 'defaults': DEFAULTS, 'critical': sorted(CRITICAL_SETTINGS)}


class SettingIn(BaseModel):
    value: object
    reason: str = Field(default='', max_length=500)


@router.put('/settings/{key}')
def put_setting(key: str, body: SettingIn, p: Principal = Depends(ADMIN)):
    if key not in DEFAULTS:
        raise not_found('Configuração desconhecida.')
    if key in CRITICAL_SETTINGS - {'sales_paused'} and not p.has('superadmin'):
        raise forbidden('Somente superadministradores alteram esta configuração.')
    default = DEFAULTS[key]
    if isinstance(default, bool) and not isinstance(body.value, bool) or \
       isinstance(default, int) and not isinstance(default, bool) and not isinstance(body.value, int) or \
       isinstance(default, list) and not isinstance(body.value, list) or isinstance(default, str) and not isinstance(body.value, str):
        raise unprocessable('validation_error', 'Tipo de valor inválido para esta configuração.')
    with tx() as conn:
        if key == 'disabled_platforms':
            known = {r['code'] for r in conn.execute('select code from platforms').fetchall()}
            if not all(isinstance(v, str) and v in known for v in body.value):
                raise unprocessable('validation_error', 'Plataforma desconhecida.')
        conn.execute('''insert into global_settings(key, value, updated_by) values (%s,%s,%s)
                        on conflict (key) do update set value=excluded.value, updated_by=excluded.updated_by''', (key, Jsonb(body.value), p.user_id))
        audit_event(conn, 'settings.changed', 'global_settings', key, reason=body.reason, details={'value': body.value})
    return {'ok': True}


@router.get('/policies')
def policies(p: Principal = Depends(ADMIN)):
    with tx() as conn:
        return jsonable(all_(conn, 'select * from policy_documents order by kind, created_at desc'))


class PolicyIn(BaseModel):
    kind: str
    version: str = Field(min_length=1, max_length=20)
    title: str
    body: str = Field(min_length=20)


@router.post('/policies', status_code=201)
def publish_policy(body: PolicyIn, p: Principal = Depends(SUPER)):
    if body.kind not in ('terms', 'privacy', 'cancellation'):
        raise unprocessable('validation_error', 'Tipo inválido.')
    with tx() as conn:
        conn.execute('update policy_documents set is_current=false where kind=%s', (body.kind,))
        try:
            row = insert(conn, 'policy_documents', {**body.model_dump(), 'is_current': True, 'published_at': timeutil.now()})
        except psycopg.errors.UniqueViolation:
            raise conflict('version_exists', 'Versão já publicada.')
    return jsonable(row)

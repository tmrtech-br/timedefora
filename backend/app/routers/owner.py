"""Cadastro e consultas restritas ao proprietário."""
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictBool

from ..core.context import actor_ip_var
from ..core import security, timeutil
from ..core.db import all_, audit_event, insert, one, tx
from ..core.deps import Principal, verified_user
from ..core.errors import conflict, forbidden, not_found, unprocessable
from .common import jsonable
from . import admin, psn_accounts

router = APIRouter(prefix='/owner', tags=['owner'])


def invited_owner(p: Principal = Depends(verified_user)) -> Principal:
    if 'owner' not in p.roles or p.is_staff:
        raise forbidden()
    return p


def current_terms(conn, lock: bool = False) -> dict:
    query = "select id, version, title, body from policy_documents where kind='owner_terms' and is_current"
    terms = one(conn, query + (' for share' if lock else ''))
    if terms is None:
        raise not_found()
    return terms


@router.get('/terms')
def terms(p: Principal = Depends(invited_owner)):
    with tx() as conn:
        policy = current_terms(conn)
        accepted = one(conn, '''
            select accepted_at from policy_acceptances
            where user_id=%s and policy_id=%s and context='owner_enrollment'
        ''', (p.user_id, policy['id']))
    return jsonable({**policy, 'accepted_at': accepted['accepted_at'] if accepted else None})


class EnrollmentIn(BaseModel):
    policy_version_id: UUID
    accepted: StrictBool


@router.post('/enrollment')
def enroll(body: EnrollmentIn, p: Principal = Depends(invited_owner)):
    if not body.accepted:
        raise unprocessable('acceptance_required', 'Confirme explicitamente o aceite dos termos.')
    with tx(p.user_id) as conn:
        policy = current_terms(conn, lock=True)
        if body.policy_version_id != policy['id']:
            raise conflict('outdated_terms', 'Recarregue a versão vigente dos termos.')
        accepted = one(conn, '''
            insert into policy_acceptances(user_id, policy_id, context, ip)
            values (%s, %s, 'owner_enrollment', %s)
            on conflict (user_id, policy_id) where context='owner_enrollment' do nothing
            returning id
        ''', (p.user_id, policy['id'], actor_ip_var.get()))
        if accepted:
            audit_event(conn, 'owner.terms_accepted', 'policy_acceptances', accepted['id'],
                        details={'version': policy['version']})
    return {'ok': True}


def enrolled_owner(p: Principal = Depends(invited_owner)) -> Principal:
    with tx() as conn:
        accepted = one(conn, '''
            select 1 from policy_acceptances a join policy_documents d on d.id=a.policy_id
            where a.user_id=%s and a.context='owner_enrollment' and d.kind='owner_terms'
              and d.is_current
        ''', (p.user_id,))
    if not accepted:
        raise forbidden('Aceite os termos vigentes para acessar o portal.')
    return p


@router.get('/psn-accounts')
def accounts(p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        return jsonable(all_(conn, '''
            select id, label, online_id, status, last_check_at, agent_id from psn_accounts
            where owner_user_id=%s order by label
        ''', (p.user_id,)))


@router.get('/consoles')
def consoles(p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        return jsonable(all_(conn, '''
            select c.id, c.code, c.name, c.status, c.is_published, p.code platform_code,
                   coalesce(c.owner_onboarding_agent_id, cfg.agent_id) agent_id, cfg.psn_account_id,
                   c.owner_requested_psn_account_id
            from consoles c join platforms p on p.id=c.platform_id
            left join console_connection_configs cfg on cfg.console_id=c.id
            where c.owner_user_id=%s and c.deleted_at is null order by c.name
        ''', (p.user_id,)))


class ConsoleIn(BaseModel):
    code: str
    name: str = Field(min_length=2, max_length=60)
    platform_code: Literal['PS4', 'PS5']


@router.post('/consoles', status_code=201)
def create_console(body: ConsoleIn, p: Principal = Depends(enrolled_owner)):
    row = admin.register_console(admin.ConsoleIn(**body.model_dump()), p.user_id, p.user_id)
    return {key: row[key] for key in ('id', 'code', 'name', 'status', 'is_published', 'platform_code')}


def owned_console(conn, console_id: UUID, owner_id: str, *, edit: bool = False):
    row = one(conn, '''
        select c.id, c.is_published, c.platform_id, coalesce(c.owner_onboarding_agent_id, cfg.agent_id) agent_id
        from consoles c join console_connection_configs cfg on cfg.console_id=c.id
        where c.id=%s and c.owner_user_id=%s and c.deleted_at is null
    ''' + (' for update of c, cfg' if edit else ''), (console_id, owner_id))
    if not row:
        raise not_found()
    if edit and row['is_published']:
        raise conflict('console_published', 'Solicite a despublicação do console para alterar o cadastro.')
    return row


class OwnerAccountIn(BaseModel):
    console_id: UUID
    label: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_.\- ]+$')


@router.post('/psn-accounts', status_code=201)
def create_account(body: OwnerAccountIn, p: Principal = Depends(enrolled_owner)):
    label = body.label.strip()
    if len(label) < 2:
        raise unprocessable('invalid_label', 'Informe um rótulo com pelo menos dois caracteres.')
    try:
        with tx(p.user_id) as conn:
            console = owned_console(conn, body.console_id, p.user_id, edit=True)
            agent_id = console['agent_id']
            if not agent_id:
                raise conflict('agent_required', 'A equipe precisa configurar o agente do console primeiro.')
            psn_accounts._agent(conn, agent_id)
            row = insert(conn, 'psn_accounts', {'label': label, 'agent_id': agent_id,
                                               'owner_user_id': p.user_id, 'created_by': p.user_id},
                         returning='id, label, status')
            audit_event(conn, 'psn.account_created', 'psn_accounts', row['id'])
    except psycopg.errors.UniqueViolation:
        raise conflict('label_taken', 'Já existe uma conta PSN com esse rótulo neste agente.')
    return jsonable(row)


@router.post('/psn-accounts/{account_id}/login/start')
def start_login(account_id: UUID, p: Principal = Depends(enrolled_owner)):
    return psn_accounts.start_account_login(account_id, p.user_id)


@router.post('/psn-accounts/{account_id}/login/finish')
def finish_login(account_id: UUID, body: psn_accounts.FinishLogin, p: Principal = Depends(enrolled_owner)):
    row = psn_accounts.finish_account_login(account_id, body, p.user_id)
    return {key: row[key] for key in ('id', 'label', 'status', 'online_id')}


@router.post('/psn-accounts/{account_id}/test')
def test_login(account_id: UUID, p: Principal = Depends(enrolled_owner)):
    return psn_accounts.test_account_login(account_id, p.user_id)


class ConnectionRequestIn(BaseModel):
    psn_account_id: UUID


@router.put('/consoles/{console_id}/connection')
def request_connection(console_id: UUID, body: ConnectionRequestIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        console = owned_console(conn, console_id, p.user_id, edit=True)
        account = psn_accounts._account(conn, body.psn_account_id, lock=True, owner_user_id=p.user_id)
        if not console['agent_id'] or account['agent_id'] != console['agent_id'] or account['status'] != 'linked':
            raise conflict('account_not_ready', 'Selecione uma conta PSN vinculada ao agente do console.')
        conn.execute('update consoles set owner_requested_psn_account_id=%s where id=%s', (account['id'], console_id))
        audit_event(conn, 'owner.console_psn_requested', 'consoles', console_id,
                    details={'psn_account_id': str(account['id'])})
    return {'status': 'requested'}


@router.get('/consoles/{console_id}/games')
def games(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        console = owned_console(conn, console_id, p.user_id)
        catalog = all_(conn, '''
            select g.id, g.title from games g join game_platforms gp on gp.game_id=g.id
            where gp.platform_id=%s and g.status='published' and g.deleted_at is null order by g.title
        ''', (console['platform_id'],))
        assignments = all_(conn, '''
            select a.id, a.starts_at, a.ends_at, g.title
            from console_game_assignments a join games g on g.id=a.game_id
            where a.console_id=%s and a.status='active' and a.ends_at>%s order by a.starts_at
        ''', (console_id, timeutil.now()))
    return jsonable({'games': catalog, 'assignments': assignments})


class GameWindowIn(BaseModel):
    game_id: UUID
    starts_at: datetime
    ends_at: datetime


@router.post('/consoles/{console_id}/games', status_code=201)
def add_game(console_id: UUID, body: GameWindowIn, p: Principal = Depends(enrolled_owner)):
    return admin.register_assignment(admin.AssignmentIn(console_id=console_id, **body.model_dump()),
                                     p.user_id, p.user_id)


class RateIn(BaseModel):
    min_minutes: int = Field(ge=1, le=480)
    max_minutes: int = Field(ge=1, le=480)
    rate_unit: Literal['minute', 'hour']
    rate_cents: int = Field(ge=1, le=1_000_000)


@router.get('/consoles/{console_id}/availability')
def availability(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        owned_console(conn, console_id, p.user_id)
        return one(conn, '''
            select min_minutes, max_minutes, rate_unit, rate_cents
            from owner_console_rates where console_id=%s
        ''', (console_id,))


@router.put('/consoles/{console_id}/availability')
def save_availability(console_id: UUID, body: RateIn, p: Principal = Depends(enrolled_owner)):
    if body.min_minutes > body.max_minutes:
        raise unprocessable('invalid_duration', 'A duração máxima precisa ser maior ou igual à mínima.')
    with tx(p.user_id) as conn:
        owned_console(conn, console_id, p.user_id, edit=True)
        conn.execute('''
            insert into owner_console_rates(console_id, min_minutes, max_minutes, rate_unit, rate_cents)
            values (%s,%s,%s,%s,%s)
            on conflict (console_id) do update set min_minutes=excluded.min_minutes,
              max_minutes=excluded.max_minutes, rate_unit=excluded.rate_unit, rate_cents=excluded.rate_cents
        ''', (console_id, body.min_minutes, body.max_minutes, body.rate_unit, body.rate_cents))
        audit_event(conn, 'owner.console_rate_changed', 'consoles', console_id)
    return body.model_dump()


@router.get('/dashboard')
def dashboard(p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        totals = one(conn, '''
            select count(*) sessions, coalesce(sum(s.seconds_used),0) seconds_used,
                   coalesce(sum(r.minutes),0) rented_minutes
            from game_sessions s join reservations r on r.id=s.reservation_id
            where r.owner_user_id=%s and s.status='ended' and s.first_connected_at is not null
        ''', (p.user_id,))
        history = all_(conn, '''
            select s.id, s.ended_at, s.seconds_used, c.name
            from game_sessions s join consoles c on c.id=s.console_id
            join reservations r on r.id=s.reservation_id
            where r.owner_user_id=%s and s.status='ended' and s.first_connected_at is not null
            order by s.ended_at desc limit 30
        ''', (p.user_id,))
        earnings = one(conn, '''
            select coalesce(sum(owner_cents) filter (where status='paid'),0) paid_cents,
                   coalesce(sum(owner_cents) filter (where status in ('eligible','held')),0) pending_cents
            from owner_settlements where owner_user_id=%s
        ''', (p.user_id,))
    return jsonable({'totals': {**totals, **earnings}, 'history': history})


@router.get('/settlements')
def settlements(limit: int = 30, offset: int = 0, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        return jsonable(all_(conn, '''
            select id, session_id, base_cents, owner_cents, status, updated_at
            from owner_settlements where owner_user_id=%s
            order by updated_at desc, id limit %s offset %s
        ''', (p.user_id, max(1, min(limit, 100)), max(0, offset))))


@router.get('/settlements/{settlement_id}')
def settlement(settlement_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        row = one(conn, '''
            select id, session_id, base_cents, owner_share_bps, owner_cents, status, updated_at
            from owner_settlements where id=%s and owner_user_id=%s
        ''', (settlement_id, p.user_id))
    if not row:
        raise not_found()
    return jsonable(row)


class PayoutIn(BaseModel):
    kind: Literal['pix', 'bank']
    pix_key: str | None = Field(default=None, max_length=140)
    bank_code: str | None = Field(default=None, pattern=r'^\d{3}$')
    branch: str | None = Field(default=None, pattern=r'^\d{1,8}$')
    account_number: str | None = Field(default=None, pattern=r'^\d{1,16}(-[0-9A-Za-z])?$')
    account_type: Literal['checking', 'savings'] | None = None
    holder_document: str | None = Field(default=None, pattern=r'^(\d{11}|\d{14})$')


@router.get('/payout-destination')
def payout_destination(p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        return jsonable(one(conn, '''
            select kind, masked, updated_at from owner_payout_destinations where user_id=%s
        ''', (p.user_id,)))


@router.put('/payout-destination')
def save_payout_destination(body: PayoutIn, p: Principal = Depends(enrolled_owner)):
    if body.kind == 'pix':
        key = (body.pix_key or '').strip()
        if len(key) < 5:
            raise unprocessable('invalid_pix_key', 'Informe uma chave PIX válida.')
        fields = {'pix_key': key}
        masked = f'••••{key[-2:]}'
    else:
        fields = body.model_dump(include={'bank_code', 'branch', 'account_number', 'account_type', 'holder_document'})
        if not all(fields.values()):
            raise unprocessable('bank_details_required', 'Preencha todos os dados bancários.')
        masked = f'Banco {body.bank_code} · ••••{body.account_number[-2:]}'
    with tx(p.user_id) as conn:
        row = one(conn, '''
            insert into owner_payout_destinations(user_id, kind, destination_enc, masked)
            values (%s,%s,%s,%s)
            on conflict (user_id) do update set kind=excluded.kind,
              destination_enc=excluded.destination_enc, masked=excluded.masked, updated_at=now()
            returning id, kind, masked, updated_at
        ''', (p.user_id, body.kind, security.encrypt(json.dumps(fields)), masked))
        audit_event(conn, 'owner.payout_destination_changed', 'owner_payout_destinations', row['id'],
                    details={'kind': body.kind})
    return jsonable({key: row[key] for key in ('kind', 'masked', 'updated_at')})

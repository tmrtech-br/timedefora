"""Cadastro e consultas restritas ao proprietário."""
import json
import re
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
from .common import DeleteIn, jsonable
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
            select c.id, c.code, c.name, c.status, c.is_published, p.code platform_code, c.model, c.location, c.description, c.serial_number,
                   coalesce(c.owner_onboarding_agent_id, cfg.agent_id) agent_id, cfg.psn_account_id,
                   c.owner_requested_psn_account_id, c.owner_review_status review_status, c.owner_review_notes review_notes,
                   c.owner_submitted_at submitted_at, c.owner_reviewed_at reviewed_at, c.owner_approved_at approved_at,
                   c.owner_pending pending
            from consoles c join platforms p on p.id=c.platform_id
            left join console_connection_configs cfg on cfg.console_id=c.id
            where c.owner_user_id=%s and c.deleted_at is null order by c.name
        ''', (p.user_id,)))


class ConsoleIn(BaseModel):
    code: str
    name: str = Field(min_length=2, max_length=60)
    platform_code: Literal['PS4', 'PS5', 'XBOX_SERIES', 'XBOX_ONE', 'SWITCH']
    model: str = Field(default='', max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    location: str = Field(default='', max_length=120)
    description: str = Field(default='', max_length=500)
    agent_id: UUID | None = None        # agente da plataforma liberado para proprietários (permite o login PSN já)


@router.post('/consoles', status_code=201)
def create_console(body: ConsoleIn, p: Principal = Depends(enrolled_owner)):
    if body.agent_id:
        with tx() as conn:
            _owner_agent(conn, body.agent_id)
    row = admin.register_console(admin.ConsoleIn(**body.model_dump(exclude={'agent_id'})), p.user_id, p.user_id)
    if body.agent_id:
        with tx(p.user_id) as conn:
            conn.execute('update consoles set owner_onboarding_agent_id=%s where id=%s', (body.agent_id, row['id']))
    return {key: row[key] for key in ('id', 'code', 'name', 'status', 'is_published', 'platform_code')}


def owned_console(conn, console_id: UUID, owner_id: str, *, edit: bool = False, allow_published: bool = False):
    row = one(conn, '''
        select c.id, c.name, c.is_published, c.platform_id, p.code platform_code, c.owner_review_status, c.owner_approved_at,
               c.owner_pending, coalesce(c.owner_onboarding_agent_id, cfg.agent_id) agent_id
        from consoles c join console_connection_configs cfg on cfg.console_id=c.id
        join platforms p on p.id=c.platform_id
        where c.id=%s and c.owner_user_id=%s and c.deleted_at is null
    ''' + (' for update of c, cfg' if edit else ''), (console_id, owner_id))
    if not row:
        raise not_found()
    if edit and not allow_published and row['owner_review_status'] == 'submitted':
        raise conflict('under_review', 'Console em análise: aguarde a equipe ou cancele o envio para editar.')
    return row


def _changed(conn, row) -> None:
    """Edição num console já aprovado: fica pendente de nova validação (o console segue no ar com o aprovado)."""
    if row['owner_approved_at'] is not None:
        conn.execute("update consoles set owner_review_status='changes_pending' where id=%s", (row['id'],))


class OwnerAccountIn(BaseModel):
    console_id: UUID | None = None
    label: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_.\- ]+$')


@router.post('/psn-accounts', status_code=201)
def create_account(body: OwnerAccountIn, p: Principal = Depends(enrolled_owner)):
    label = body.label.strip()
    if len(label) < 2:
        raise unprocessable('invalid_label', 'Informe um rótulo com pelo menos dois caracteres.')
    try:
        with tx(p.user_id) as conn:
            console = owned_console(conn, body.console_id, p.user_id) if body.console_id else None
            if console and console['platform_code'] not in ('PS4', 'PS5'):
                raise unprocessable('invalid_platform', 'Selecione um console PlayStation.')
            agent_id = console['agent_id'] if console else None
            if agent_id:
                psn_accounts._agent(conn, agent_id)
            row = insert(conn, 'psn_accounts', {'label': label, 'agent_id': agent_id,
                                               'owner_user_id': p.user_id, 'created_by': p.user_id},
                         returning='id, label, status')
            audit_event(conn, 'psn.account_created', 'psn_accounts', row['id'])
            if console:   # já associa ao console escolhido (a equipe aprova o vínculo)
                conn.execute('update consoles set owner_requested_psn_account_id=coalesce(owner_requested_psn_account_id, %s) where id=%s',
                             (row['id'], console['id']))
    except psycopg.errors.UniqueViolation:
        raise conflict('label_taken', 'Já existe uma conta PSN com esse rótulo neste agente.')
    return jsonable(row)


class AccountConsoleIn(BaseModel):
    console_id: UUID


@router.put('/psn-accounts/{account_id}/agent')
def assign_psn_agent(account_id: UUID, body: AccountConsoleIn, p: Principal = Depends(enrolled_owner)):
    try:
        with tx(p.user_id) as conn:
            console = owned_console(conn, body.console_id, p.user_id)
            if console['platform_code'] not in ('PS4', 'PS5'):
                raise unprocessable('invalid_platform', 'Selecione um console PlayStation.')
            account = psn_accounts._account(conn, account_id, lock=True, owner_user_id=p.user_id)
            if account['agent_id'] is not None:
                raise conflict('agent_already_set', 'Esta conta PSN já tem um agente definido.')
            if not console['agent_id']:
                raise conflict('agent_required', 'A equipe precisa autorizar o agente deste console.')
            psn_accounts._agent(conn, console['agent_id'])
            conn.execute('update psn_accounts set agent_id=%s where id=%s', (console['agent_id'], account_id))
            audit_event(conn, 'psn.owner_agent_assigned', 'psn_accounts', account_id)
    except psycopg.errors.UniqueViolation:
        raise conflict('label_taken', 'Já existe uma conta PSN com esse rótulo neste agente.')
    return {'ok': True}


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
        if console['agent_id'] and account['agent_id'] and account['agent_id'] != console['agent_id']:
            raise conflict('account_not_ready', 'Esta conta PSN pertence a outro agente. Use uma conta deste console.')
        previous = one(conn, '''select c.owner_requested_psn_account_id, cfg.psn_account_id from consoles c
                                left join console_connection_configs cfg on cfg.console_id=c.id where c.id=%s''', (console_id,))
        conn.execute('update consoles set owner_requested_psn_account_id=%s where id=%s', (account['id'], console_id))
        if previous['owner_requested_psn_account_id'] or previous['psn_account_id']:
            _changed(conn, console)          # trocar a conta de um console aprovado volta para análise; a 1ª conexão não
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
            select a.id, a.starts_at, a.ends_at, a.status, g.status game_status,
                   g.title || case when a.status='pending_review' then ' (aguardando validação)' else '' end title
            from console_game_assignments a join games g on g.id=a.game_id
            where a.console_id=%s and a.status in ('active','pending_review') and a.ends_at>%s order by a.starts_at
        ''', (console_id, timeutil.now()))
        drafts = all_(conn, '''
            select g.id, g.title from games g join game_platforms gp on gp.game_id=g.id
            where gp.platform_id=%s and g.created_by=%s and g.status='draft' and g.deleted_at is null
            order by g.title
        ''', (console['platform_id'], p.user_id))
    return jsonable({'games': catalog, 'assignments': assignments, 'drafts': drafts})


class GameWindowIn(BaseModel):
    game_id: UUID
    starts_at: datetime
    ends_at: datetime


@router.post('/consoles/{console_id}/games', status_code=201)
def add_game(console_id: UUID, body: GameWindowIn, p: Principal = Depends(enrolled_owner)):
    return admin.register_assignment(admin.AssignmentIn(console_id=console_id, **body.model_dump()),
                                     p.user_id, p.user_id)


class GameDraftIn(admin.GameIn):
    title: str = Field(min_length=2, max_length=120)
    slug: str = ''


@router.post('/consoles/{console_id}/game-drafts', status_code=201)
def create_game_draft(console_id: UUID, body: GameDraftIn, p: Principal = Depends(enrolled_owner)):
    title = body.title.strip()
    if len(title) < 2:
        raise unprocessable('invalid_title', 'Informe o título do jogo.')
    with tx(p.user_id) as conn:
        console = owned_console(conn, console_id, p.user_id, edit=True)
        platform = one(conn, 'select code from platforms where id=%s', (console['platform_id'],))
        conn.execute('select pg_advisory_xact_lock(hashtext(%s))', (platform['code'] + ':' + title.lower(),))
        if one(conn, '''
            select 1 from games g join game_platforms gp on gp.game_id=g.id
            where gp.platform_id=%s and lower(g.title)=lower(%s) and g.deleted_at is null
              and (g.status='published' or g.created_by=%s)
        ''', (console['platform_id'], title, p.user_id)):
            raise conflict('game_exists', 'Já existe um jogo ou rascunho com esse título para a plataforma.')
        slug = body.slug or 'proprietario-' + security.new_token(12).lower().replace('_', '-')
        if not admin.SLUG_RE.fullmatch(slug) or not 1 <= body.min_minutes <= body.max_minutes <= 480:
            raise unprocessable('invalid_game', 'Verifique o slug e o intervalo de duração do jogo.')
        metadata = body.model_dump(include={
            'short_description', 'description', 'cover_url', 'banner_url', 'trailer_url',
            'age_rating', 'release_date', 'requirements', 'min_minutes', 'max_minutes', 'image_rights_notes',
        })
        if metadata['age_rating'] not in (None, 'L', '10', '12', '14', '16', '18'):
            raise unprocessable('invalid_age_rating', 'Classificação etária inválida.')
        for field in ('cover_url', 'banner_url', 'trailer_url'):
            value = metadata[field]
            if value and (len(value) > 500 or not value.lower().startswith(('https://', 'http://'))):
                raise unprocessable('invalid_media_url', 'Informe URLs de mídia HTTP ou HTTPS.')
        try:
            row = insert(conn, 'games', {**metadata, 'title': title, 'slug': slug, 'status': 'draft',
                                         'created_by': p.user_id, 'updated_by': p.user_id},
                         returning='id, title, status')
        except psycopg.errors.UniqueViolation:
            raise conflict('slug_taken', 'Já existe um jogo com este slug.')
        admin._set_game_relations(conn, row['id'], [platform['code']], body.genres[:30])
        _changed(conn, console)
        audit_event(conn, 'owner.game_draft_created', 'games', row['id'])
    return jsonable(row)


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
            select min_minutes, max_minutes, rate_unit, rate_cents, paused
            from owner_console_rates where console_id=%s
        ''', (console_id,))


@router.put('/consoles/{console_id}/availability')
def save_availability(console_id: UUID, body: RateIn, p: Principal = Depends(enrolled_owner)):
    if body.min_minutes > body.max_minutes:
        raise unprocessable('invalid_duration', 'A duração máxima precisa ser maior ou igual à mínima.')
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        if row['owner_approved_at'] is not None:
            # Console aprovado: a nova tarifa só vale depois que a equipe validar.
            conn.execute('''update consoles set owner_review_status='changes_pending',
                            owner_pending = owner_pending || jsonb_build_object('rate', %s::jsonb) where id=%s''',
                         (json.dumps(body.model_dump()), console_id))
            audit_event(conn, 'owner.console_rate_change_requested', 'consoles', console_id)
            return {**body.model_dump(), 'pending': True}
        conn.execute('''
            insert into owner_console_rates(console_id, min_minutes, max_minutes, rate_unit, rate_cents)
            values (%s,%s,%s,%s,%s)
            on conflict (console_id) do update set min_minutes=excluded.min_minutes,
              max_minutes=excluded.max_minutes, rate_unit=excluded.rate_unit, rate_cents=excluded.rate_cents
        ''', (console_id, body.min_minutes, body.max_minutes, body.rate_unit, body.rate_cents))
        audit_event(conn, 'owner.console_rate_changed', 'consoles', console_id)
    return body.model_dump()


class PauseAvailabilityIn(BaseModel):
    paused: StrictBool


@router.patch('/consoles/{console_id}/availability')
def pause_availability(console_id: UUID, body: PauseAvailabilityIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        owned_console(conn, console_id, p.user_id, edit=True, allow_published=True)
        if not conn.execute('update owner_console_rates set paused=%s where console_id=%s',
                            (body.paused, console_id)).rowcount:
            raise not_found()
        audit_event(conn, 'owner.console_availability_paused' if body.paused else 'owner.console_availability_resumed',
                    'consoles', console_id)
    return body.model_dump()


@router.delete('/consoles/{console_id}/availability')
def delete_availability(console_id: UUID, body: DeleteIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        if row['owner_approved_at'] is not None:
            raise conflict('approved_console', 'Console aprovado: pause a disponibilidade ou envie uma nova tarifa para análise.')
        if not conn.execute('delete from owner_console_rates where console_id=%s', (console_id,)).rowcount:
            raise not_found()
        audit_event(conn, 'owner.console_availability_deleted', 'consoles', console_id, reason=body.reason)
    return {'ok': True}


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


@router.get('/payouts')
def my_payouts(p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        return jsonable(all_(conn, '''
            select po.id, po.amount_cents, po.status, po.destination_masked, po.scheduled_for, po.paid_at, po.proof_url, g.title game
            from owner_payouts po join owner_settlements st on st.id=po.settlement_id
            join reservations r on r.id=st.reservation_id join games g on g.id=r.game_id
            where po.owner_user_id=%s order by po.created_at desc limit 100''', (p.user_id,)))


# ------------------------------------------------------------------ validação pela equipe
def _checklist(conn, console_id) -> list[str]:
    """O que falta para enviar o console para análise."""
    c = one(conn, '''select c.*, p.code platform_code, cfg.psn_account_id from consoles c join platforms p on p.id=c.platform_id
                     left join console_connection_configs cfg on cfg.console_id=c.id where c.id=%s''', (console_id,))
    missing = []
    conn_cfg = (c['owner_pending'] or {}).get('connection')
    cfg_method = one(conn, 'select method from console_connection_configs where console_id=%s', (console_id,))
    if not conn_cfg and (not cfg_method or cfg_method['method'] == 'unconfigured'):
        missing.append('Configure a conexão e a transmissão do console (Cadastro de console).')
    if c['platform_code'] in ('PS4', 'PS5') and not (c['owner_requested_psn_account_id'] or c['psn_account_id']):
        missing.append('Cadastre a conta PSN e associe ao console (Contas PSN).')
    if not one(conn, 'select 1 from owner_console_rates where console_id=%s', (console_id,)) and not (c['owner_pending'] or {}).get('rate'):
        missing.append('Defina a tarifa e a duração das sessões.')
    if not one(conn, """select 1 from console_game_assignments where console_id=%s and status in ('active','pending_review')
                        and ends_at > %s""", (console_id, timeutil.now())):
        missing.append('Cadastre pelo menos um jogo com período de disponibilidade.')
    return missing


@router.get('/consoles/{console_id}/review')
def review_state(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        row = owned_console(conn, console_id, p.user_id)
        c = one(conn, '''select owner_review_status status, owner_review_notes notes, owner_submitted_at submitted_at,
                         owner_reviewed_at reviewed_at, owner_approved_at approved_at, owner_pending pending, is_published
                         from consoles where id=%s''', (console_id,))
        pending_windows = all_(conn, """select a.id, g.title, a.starts_at, a.ends_at from console_game_assignments a
                                       join games g on g.id=a.game_id where a.console_id=%s and a.status='pending_review'
                                         and a.ends_at>%s and g.deleted_at is null
                                       order by a.starts_at""", (console_id, timeutil.now()))
        return jsonable({**c, 'missing': _checklist(conn, console_id), 'pending_windows': pending_windows,
                         'agent_linked': bool(row['agent_id'])})


@router.post('/consoles/{console_id}/submit')
def submit_review(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        missing = _checklist(conn, console_id)
        if missing:
            raise unprocessable('incomplete', 'Complete o cadastro antes de enviar: ' + ' '.join(missing))
        if row['owner_review_status'] == 'approved':
            raise conflict('nothing_to_review', 'Nenhuma alteração pendente para enviar.')
        conn.execute("update consoles set owner_review_status='submitted', owner_submitted_at=%s where id=%s",
                     (timeutil.now(), console_id))
        audit_event(conn, 'owner.console_submitted', 'consoles', console_id)
        from ..services.preparation import notify_staff
        kind = 'alterações de um console já aprovado' if row['owner_approved_at'] else 'um novo console'
        notify_staff(conn, 'staff_incident', {'incidente': f'Proprietário enviou {kind} para análise',
                                              'detalhe': f"Console {row['name']}: valide os dados, vincule o agente e aprove ou recuse"},
                     dedupe=f'owner_submit:{console_id}:{int(timeutil.now().timestamp())}', link='/admin/aprovacoes')
    return {'status': 'submitted'}


@router.post('/consoles/{console_id}/withdraw')
def withdraw_review(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, allow_published=True)
        if row['owner_review_status'] != 'submitted':
            raise conflict('not_submitted', 'Este console não está em análise.')
        back = 'changes_pending' if row['owner_approved_at'] else 'draft'
        conn.execute('update consoles set owner_review_status=%s where id=%s', (back, console_id))
    return {'status': back}


@router.post('/consoles/{console_id}/publish')
def owner_publish(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        row = owned_console(conn, console_id, p.user_id, allow_published=True)
        if row['owner_approved_at'] is None:
            raise conflict('not_approved', 'A equipe precisa validar o console e vincular o agente antes da publicação.')
    return admin._publish_console(console_id)


@router.post('/consoles/{console_id}/unpublish')
def owner_unpublish(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        owned_console(conn, console_id, p.user_id, allow_published=True)
        conn.execute('update consoles set is_published=false where id=%s', (console_id,))
        audit_event(conn, 'owner.console_unpublished', 'consoles', console_id)
    return {'ok': True, 'message': 'Console fora do ar para novas reservas. As já pagas continuam valendo.'}


@router.get('/consoles/{console_id}/history')
def console_history(console_id: UUID, limit: int = 100, p: Principal = Depends(enrolled_owner)):
    """Filas e sessões que o console teve (jogador identificado só pelas iniciais)."""
    with tx() as conn:
        owned_console(conn, console_id, p.user_id)
        rows = all_(conn, '''
            select r.code, r.status, r.mode, r.minutes, r.starts_at, r.ends_at, r.total_cents, g.title game,
                   upper(left(u.username, 2)) || '***' player, s.seconds_used, s.end_reason, s.first_connected_at
            from reservations r join games g on g.id=r.game_id join users u on u.id=r.user_id
            left join game_sessions s on s.reservation_id=r.id
            where r.console_id=%s and r.status not in ('pending_payment','expired')
            order by r.starts_at desc limit %s
        ''', (console_id, max(1, min(limit, 500))))
    return jsonable(rows)


# ------------------------------------------------------------------ cadastro do console (portal reorganizado)
CODE_RE = re.compile(r'^[A-Z0-9-]{3,30}$')


@router.get('/agents')
def owner_agents(p: Principal = Depends(enrolled_owner)):
    """Agentes da plataforma liberados pela equipe para os proprietários escolherem."""
    with tx() as conn:
        return jsonable(all_(conn, '''select id, name, location, status from console_agents
                                      where available_to_owners and not is_simulated order by name'''))


@router.get('/consoles/code-check')
def code_check(code: str = '', p: Principal = Depends(enrolled_owner)):
    """Validação do código enquanto o proprietário digita."""
    c = code.strip().upper()
    if not CODE_RE.fullmatch(c):
        return {'valid': False, 'available': False, 'message': 'Use de 3 a 30 letras maiúsculas, números ou hífen (ex.: PS5-JOAO-01).'}
    with tx() as conn:
        taken = one(conn, 'select 1 from consoles where code=%s and deleted_at is null', (c,))
    return {'valid': True, 'available': not taken, 'message': 'Código já usado por outro console.' if taken else 'Código disponível.'}


def _owner_agent(conn, agent_id) -> None:
    a = one(conn, 'select available_to_owners, is_simulated from console_agents where id=%s', (agent_id,))
    if not a or not a['available_to_owners'] or a['is_simulated']:
        raise unprocessable('invalid_agent', 'Escolha um dos agentes disponíveis para proprietários.')


class ConsoleEditIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=60)
    model: str | None = Field(default=None, max_length=120)
    serial_number: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    agent_id: UUID | None = None


@router.patch('/consoles/{console_id}')
def edit_console(console_id: UUID, body: ConsoleEditIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        fields = {k: v for k, v in body.model_dump(exclude={'agent_id'}).items() if k in body.model_fields_set}
        if fields.get('name') is not None:
            fields['name'] = fields['name'].strip()
        if 'agent_id' in body.model_fields_set and body.agent_id:
            if row['owner_approved_at'] is not None and str(body.agent_id) != str(row['agent_id']):
                raise conflict('approved_console', 'Console aprovado: fale com a equipe para trocar o agente.')
            _owner_agent(conn, body.agent_id)
            conn.execute('update consoles set owner_onboarding_agent_id=%s where id=%s', (body.agent_id, console_id))
        if fields:
            sets = ', '.join(f'{k}=%s' for k in fields)
            conn.execute(f'update consoles set {sets}, updated_by=%s where id=%s', (*fields.values(), p.user_id, console_id))
        _changed(conn, row)
        audit_event(conn, 'owner.console_edited', 'consoles', console_id, details={'fields': sorted(fields)})
    return {'ok': True}


@router.delete('/consoles/{console_id}')
def delete_console(console_id: UUID, body: DeleteIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        owned_console(conn, console_id, p.user_id, allow_published=True)
        if one(conn, """select 1 from reservations where console_id=%s and status in ('pending_payment','confirmed','active')
                        and ends_at > %s""", (console_id, timeutil.now())):
            raise conflict('has_reservations', 'Há reservas futuras neste console. Tire-o do ar e aguarde elas terminarem para excluir.')
        n = timeutil.now()
        conn.execute("update consoles set deleted_at=%s, is_published=false, status='disabled' where id=%s", (n, console_id))
        conn.execute("""update console_game_assignments set status='archived' where console_id=%s
                        and status in ('active','pending_review') and ends_at > %s""", (console_id, n))
        audit_event(conn, 'owner.console_deleted', 'consoles', console_id, reason=body.reason)
    return {'ok': True}


class HourIn(BaseModel):
    weekday: int = Field(ge=0, le=6)        # 0 = domingo
    opens_at: str
    closes_at: str


class HoursIn(BaseModel):
    hours: list[HourIn] = Field(max_length=50)


@router.get('/consoles/{console_id}/hours')
def get_hours(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        row = owned_console(conn, console_id, p.user_id)
        hours = all_(conn, '''select weekday, to_char(opens_at,'HH24:MI') opens_at, to_char(closes_at,'HH24:MI') closes_at
                              from console_operating_hours where console_id=%s order by weekday, opens_at''', (console_id,))
        return {'hours': hours, 'pending': (row['owner_pending'] or {}).get('hours')}


def _valid_hours(hours: list[HourIn]) -> list[dict]:
    from datetime import time as dtime
    out = []
    for h in hours:
        try:
            o, c = dtime.fromisoformat(h.opens_at), dtime.fromisoformat(h.closes_at)
        except ValueError:
            raise unprocessable('validation_error', 'Horário inválido (use HH:MM).')
        if o >= c:
            raise unprocessable('validation_error', 'O horário de abertura precisa ser antes do fechamento.')
        out.append({'weekday': h.weekday, 'opens_at': o.strftime('%H:%M'), 'closes_at': c.strftime('%H:%M')})
    return out


def apply_hours(conn, console_id, hours: list[dict]) -> None:
    conn.execute('delete from console_operating_hours where console_id=%s', (console_id,))
    for h in hours:
        insert(conn, 'console_operating_hours', {'console_id': console_id, 'weekday': h['weekday'],
                                                 'opens_at': h['opens_at'], 'closes_at': h['closes_at']})


@router.put('/consoles/{console_id}/hours')
def put_hours(console_id: UUID, body: HoursIn, p: Principal = Depends(enrolled_owner)):
    hours = _valid_hours(body.hours)
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        if row['owner_approved_at'] is not None:     # aprovado: vale depois da validação da equipe
            conn.execute('''update consoles set owner_review_status='changes_pending',
                            owner_pending = owner_pending || jsonb_build_object('hours', %s::jsonb) where id=%s''',
                         (json.dumps(hours), console_id))
            return {'hours': hours, 'pending': True}
        apply_hours(conn, console_id, hours)
        audit_event(conn, 'owner.console_hours_changed', 'consoles', console_id)
    return {'hours': hours, 'pending': False}


@router.get('/report')
def owner_report(date_from: str | None = None, date_to: str | None = None, console_id: UUID | None = None,
                 p: Principal = Depends(enrolled_owner)):
    """Dados do dashboard do proprietário (filtráveis por período e console)."""
    from datetime import date as ddate, timedelta
    try:
        d1 = ddate.fromisoformat(date_from) if date_from else timeutil.local(timeutil.now()).date() - timedelta(days=29)
        d2 = ddate.fromisoformat(date_to) if date_to else timeutil.local(timeutil.now()).date()
    except ValueError:
        raise unprocessable('validation_error', 'Datas inválidas.')
    if d2 < d1 or (d2 - d1).days > 366:
        raise unprocessable('validation_error', 'Escolha um período de até 1 ano.')
    tz = 'America/Fortaleza'
    args: list = [p.user_id, d1, d2]
    extra = ''
    if console_id:
        extra = ' and r.console_id=%s'
        args.append(console_id)
    with tx() as conn:
        rows = all_(conn, f'''
            select r.code, r.status, r.minutes, r.total_cents, r.starts_at, g.title game, c.name console,
                   (r.starts_at at time zone '{tz}')::date as day, s.seconds_used, s.end_reason,
                   st.owner_cents, st.status settlement_status, po.status payout_status
            from reservations r join games g on g.id=r.game_id join consoles c on c.id=r.console_id
            left join game_sessions s on s.reservation_id=r.id
            left join owner_settlements st on st.reservation_id=r.id
            left join owner_payouts po on po.settlement_id=st.id
            where r.owner_user_id=%s and (r.starts_at at time zone '{tz}')::date between %s and %s
              and r.status not in ('pending_payment','expired'){extra}
            order by r.starts_at desc''', tuple(args))
        consoles = all_(conn, 'select id, name from consoles where owner_user_id=%s and deleted_at is null order by name', (p.user_id,))
    return jsonable({'date_from': d1.isoformat(), 'date_to': d2.isoformat(), 'consoles': consoles, 'rows': rows})


# ------------------------------------------------------------------ conexão/transmissão proposta + testes após aprovação
class ConnectionSettingsIn(BaseModel):
    # Proprietário: somente Remote Play pela internet (PSN) — o console fica na casa dele, longe do agente.
    method: Literal['remote_play_native'] = 'remote_play_native'
    network_route: Literal['internet_psn'] = 'internet_psn'
    console_identifier: str | None = Field(default=None, max_length=80)
    internal_host: str | None = Field(default=None, max_length=120)
    public_host: str | None = Field(default=None, max_length=253)
    public_port: int | None = Field(default=None, ge=1, le=65535)
    resolution: Literal['720p', '1080p'] = '720p'
    fps: Literal[30, 60] = 30
    bitrate_kbps: int = Field(default=6000, ge=1500, le=15000)
    standby_after_session: bool = True
    keep_awake_minutes: int = Field(default=15, ge=0, le=240)


@router.get('/consoles/{console_id}/connection-settings')
def get_connection_settings(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        row = owned_console(conn, console_id, p.user_id)
        cfg = one(conn, '''select method, network_route, console_identifier, internal_host, public_host, public_port, resolution, fps,
                           bitrate_kbps, standby_after_session, keep_awake_minutes, validated_at, video_validated_at, audio_validated_at,
                           control_validated_at, heartbeat_validated_at, connection_status
                           from console_connection_configs where console_id=%s''', (console_id,))
        return jsonable({'current': cfg, 'pending': (row['owner_pending'] or {}).get('connection')})


@router.put('/consoles/{console_id}/connection-settings')
def put_connection_settings(console_id: UUID, body: ConnectionSettingsIn, p: Principal = Depends(enrolled_owner)):
    """Proposta do proprietário: aplicada (com o agente) depois que a equipe aprovar, no botão "Aplicar e testar"."""
    body.internal_host, body.public_host, body.public_port = None, None, None
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        if row['platform_code'] != 'PS4':
            raise unprocessable('validation_error', 'Por enquanto o aluguel pela internet (PSN) funciona só com PS4.')
        conn.execute('''update consoles set owner_pending = owner_pending || jsonb_build_object('connection', %s::jsonb) where id=%s''',
                     (json.dumps(body.model_dump()), console_id))
        _changed(conn, row)
        audit_event(conn, 'owner.connection_proposed', 'consoles', console_id)
    return {**body.model_dump(), 'pending': True}


def _psn_for(conn, console_id) -> dict | None:
    c = one(conn, '''select coalesce(c.owner_requested_psn_account_id, cfg.psn_account_id) acc from consoles c
                     left join console_connection_configs cfg on cfg.console_id=c.id where c.id=%s''', (console_id,))
    return one(conn, 'select * from psn_accounts where id=%s', (c['acc'],)) if c and c['acc'] else None


@router.post('/consoles/{console_id}/diagnostics', status_code=202)
def owner_run_diagnostics(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    """Depois da aprovação: aplica a conexão proposta (com o agente e a conta PSN aprovados) e roda todos os testes."""
    with tx() as conn:
        row = owned_console(conn, console_id, p.user_id, allow_published=True)
        if row['owner_approved_at'] is None or not row['agent_id']:
            raise conflict('not_approved', 'Os testes ficam liberados depois que a equipe aprovar e vincular o agente.')
        pending = (row['owner_pending'] or {}).get('connection')
        cfg = one(conn, 'select method from console_connection_configs where console_id=%s', (console_id,))
        acc = _psn_for(conn, console_id)
        needs_psn = (pending or {}).get('network_route') == 'internet_psn'
        if needs_psn and (not acc or acc['status'] != 'linked'):
            raise conflict('psn_login_required', 'Faça o login Sony da conta PSN do console (menu Contas PSN) antes de testar.')
        if not pending and (not cfg or cfg['method'] == 'unconfigured'):
            raise conflict('not_configured', 'Configure a conexão e a transmissão do console antes de testar.')
    if acc and acc['agent_id'] is None:      # conta escolhida depois da aprovação: passa a usar o agente do console
        try:
            with tx(p.user_id) as conn:
                conn.execute('update psn_accounts set agent_id=%s where id=%s and agent_id is null', (row['agent_id'], acc['id']))
        except psycopg.errors.UniqueViolation:
            raise conflict('label_taken', 'Já existe uma conta PSN com esse nome no agente. Renomeie a conta e tente de novo.')
    if acc and acc['credentials_enc']:       # login Sony feito no portal: entrega ao cofre do agente antes do teste
        psn_accounts.push_server_credentials(acc['id'])
    if pending:
        admin.set_connection(console_id, admin.ConnectionIn(**pending, agent_id=row['agent_id'],
                                                            psn_account_id=acc['id'] if acc and needs_psn else None,
                                                            reason='Configuração enviada pelo proprietário e aprovada pela equipe.'), p)
        with tx(p.user_id) as conn:
            conn.execute("update consoles set owner_pending = owner_pending - 'connection' where id=%s", (console_id,))
    with tx(p.user_id) as conn:
        active = one(conn, "select id, status from console_diagnostic_runs where console_id=%s and status in ('queued','running','cancelling')",
                     (console_id,))
        if active:
            return jsonable(active)
        run = insert(conn, 'console_diagnostic_runs', {'console_id': console_id, 'requested_by': p.user_id}, returning='id, status')
        audit_event(conn, 'owner.diagnostics_queued', 'console_diagnostic_runs', run['id'])
    return jsonable(run)


@router.get('/consoles/{console_id}/diagnostics')
def owner_diagnostics(console_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        owned_console(conn, console_id, p.user_id)
        run = one(conn, '''select id, status, results, error, created_at, finished_at, requested_by=%s can_cancel
                           from console_diagnostic_runs where console_id=%s order by created_at desc limit 1''',
                  (p.user_id, console_id))
        cfg = one(conn, '''select validated_at, video_validated_at, audio_validated_at, control_validated_at, heartbeat_validated_at,
                           connection_status, method, network_route from console_connection_configs where console_id=%s''', (console_id,))
    return jsonable({'run': run, 'validation': cfg})


@router.post('/consoles/{console_id}/diagnostics/{run_id}/cancel')
def owner_cancel_diagnostics(console_id: UUID, run_id: UUID, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        owned_console(conn, console_id, p.user_id, allow_published=True)
        if not one(conn, 'select 1 from console_diagnostic_runs where id=%s and console_id=%s and requested_by=%s',
                   (run_id, console_id, p.user_id)):
            raise not_found()
        return admin.cancel_console_diagnostic(conn, console_id, run_id)


# ------------------------------------------------------------------ exclusões do proprietário
@router.delete('/psn-accounts/{account_id}')
def delete_psn_account(account_id: UUID, body: DeleteIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        row = psn_accounts._account(conn, account_id, lock=True, owner_user_id=p.user_id)
        used = all_(conn, '''select c.name from console_connection_configs cfg join consoles c on c.id=cfg.console_id
                             where cfg.psn_account_id=%s and c.deleted_at is null''', (account_id,))
        if used:
            raise conflict('account_in_use', 'Conta em uso pelo console ' + ', '.join(u['name'] for u in used)
                           + '. Associe outra conta ao console (ou exclua o console) antes de excluir esta.')
        conn.execute('update consoles set owner_requested_psn_account_id=null where owner_requested_psn_account_id=%s', (account_id,))
        psn_accounts.clear_deleted_console_bindings(conn, account_id)
        if row['agent_id'] is not None:
            try:
                psn_accounts._call_agent(conn, row, '', method='DELETE')   # apaga o login guardado no agente
            except Exception:
                pass                                                       # agente fora do ar: a conta some daqui mesmo assim
        audit_event(conn, 'owner.psn_account_deleted', 'psn_accounts', account_id, reason=body.reason)
        conn.execute('delete from psn_accounts where id=%s', (account_id,))
    return {'ok': True}


@router.delete('/consoles/{console_id}/games/{assignment_id}')
def delete_game_window(console_id: UUID, assignment_id: UUID, body: DeleteIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        row = owned_console(conn, console_id, p.user_id, edit=True)
        a = one(conn, "select * from console_game_assignments where id=%s and console_id=%s and status in ('active','pending_review') for update",
                (assignment_id, console_id))
        if not a:
            raise not_found('Período não encontrado.')
        if one(conn, """select 1 from reservations where assignment_id=%s and status in ('pending_payment','confirmed','active')""", (assignment_id,)):
            raise conflict('has_reservations', 'Há reservas neste período. Aguarde elas terminarem para excluir.')
        conn.execute("update console_game_assignments set status='cancelled', updated_by=%s where id=%s", (p.user_id, assignment_id))
        if a['status'] == 'active':
            _changed(conn, row)
        audit_event(conn, 'owner.game_window_deleted', 'console_game_assignments', assignment_id, reason=body.reason)
    return {'ok': True}


@router.delete('/consoles/{console_id}/game-drafts/{game_id}')
def delete_game_draft(console_id: UUID, game_id: UUID, body: DeleteIn, p: Principal = Depends(enrolled_owner)):
    with tx(p.user_id) as conn:
        owned_console(conn, console_id, p.user_id, edit=True)
        g = one(conn, "select id from games where id=%s and created_by=%s and status='draft' and deleted_at is null for update", (game_id, p.user_id))
        if not g:
            raise not_found('Só é possível excluir jogos seus ainda em revisão.')
        conn.execute("""update console_game_assignments set status='cancelled' where game_id=%s and status in ('active','pending_review')""", (game_id,))
        conn.execute("update games set deleted_at=%s, status='archived' where id=%s", (timeutil.now(), game_id))
        audit_event(conn, 'owner.game_draft_deleted', 'games', game_id, reason=body.reason)
    return {'ok': True}

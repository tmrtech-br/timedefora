"""Cadastro e consultas restritas ao proprietário."""
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictBool

from ..core.context import actor_ip_var
from ..core.db import all_, audit_event, one, tx
from ..core.deps import Principal, verified_user
from ..core.errors import conflict, forbidden, not_found, unprocessable
from .common import jsonable

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
            select id, label, online_id, status, last_check_at from psn_accounts
            where owner_user_id=%s order by label
        ''', (p.user_id,)))


@router.get('/consoles')
def consoles(p: Principal = Depends(enrolled_owner)):
    with tx() as conn:
        return jsonable(all_(conn, '''
            select id, name, status, is_published from consoles
            where owner_user_id=%s and deleted_at is null order by name
        ''', (p.user_id,)))

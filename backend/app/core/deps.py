"""Dependências FastAPI: usuário autenticado, papéis (RBAC), MFA administrativo, CSRF."""
from dataclasses import dataclass, field

from fastapi import Depends, Request

from ..config import settings
from . import timeutil
from .context import actor_id_var
from .db import get_pool
from .errors import AppError, forbidden, unauthorized
from .security import sha256

SESSION_COOKIE = 'lp_session'
CSRF_COOKIE = 'lp_csrf'
STAFF_ROLES = {'operator', 'admin', 'superadmin'}
ROLE_RANK = {'client': 0, 'operator': 1, 'admin': 2, 'superadmin': 3}


@dataclass
class Principal:
    user_id: str
    session_id: str
    username: str
    full_name: str
    email: str
    status: str
    email_verified: bool
    roles: set[str] = field(default_factory=set)
    mfa_enabled: bool = False
    mfa_verified: bool = False

    @property
    def is_staff(self) -> bool:
        return bool(self.roles & STAFF_ROLES)

    def has(self, minimum: str) -> bool:
        return any(ROLE_RANK.get(r, -1) >= ROLE_RANK[minimum] for r in self.roles)


def load_principal(token: str | None) -> Principal | None:
    if not token:
        return None
    with get_pool().connection() as conn:
        row = conn.execute(
            """select s.id sid, s.mfa_verified_at, s.last_seen_at, u.*,
                      exists(select 1 from mfa_factors f where f.user_id=u.id and f.confirmed_at is not null and f.disabled_at is null) mfa_enabled,
                      coalesce((select array_agg(r.code) from role_assignments ra join roles r on r.id=ra.role_id
                                where ra.user_id=u.id and ra.revoked_at is null), '{}') roles
               from auth_sessions s join users u on u.id=s.user_id
               where s.token_hash=%s and s.revoked_at is null and s.expires_at > %s and u.deleted_at is null""",
            (sha256(token), timeutil.now())).fetchone()
        if not row or row['status'] == 'suspended':
            return None
        if (timeutil.now() - row['last_seen_at']).total_seconds() > 300:
            conn.execute('update auth_sessions set last_seen_at=%s where id=%s', (timeutil.now(), row['sid']))
    return Principal(user_id=str(row['id']), session_id=str(row['sid']), username=row['username'],
                     full_name=row['full_name'], email=row['email'], status=row['status'],
                     email_verified=row['email_verified_at'] is not None, roles=set(row['roles']),
                     mfa_enabled=row['mfa_enabled'], mfa_verified=row['mfa_verified_at'] is not None)


def optional_user(request: Request) -> Principal | None:
    p = getattr(request.state, 'principal', None)
    if p:
        actor_id_var.set(p.user_id)
    return p


def current_user(p: Principal | None = Depends(optional_user)) -> Principal:
    if not p:
        raise unauthorized()
    return p


def verified_user(p: Principal = Depends(current_user)) -> Principal:
    if not p.email_verified or p.status != 'active':
        raise AppError(403, 'email_not_verified', 'Confirme seu e-mail para usar recursos pagos.')
    return p


def require_role(minimum: str):
    def dep(p: Principal = Depends(current_user)) -> Principal:
        if not p.has(minimum):
            raise forbidden()
        if settings.require_admin_mfa and minimum in STAFF_ROLES:
            if not p.mfa_enabled:
                raise AppError(403, 'mfa_setup_required', 'Ative a autenticação em dois fatores para acessar o painel.')
            if not p.mfa_verified:
                raise AppError(403, 'mfa_required', 'Confirme o código de autenticação em dois fatores.')
        return p
    return dep


def client_ip(request: Request) -> str:
    # Atrás de proxy confiável, configure o servidor (uvicorn --proxy-headers) para preencher client.host.
    return request.client.host if request.client else 'unknown'

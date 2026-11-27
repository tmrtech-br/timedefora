"""Perfil do jogador: dados, segurança, sessões, MFA, contas vinculadas, preferências, favoritos,
estatísticas, notificações, LGPD (exportação e solicitações)."""
import os
import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field

from ..core import timeutil
from ..core.db import all_, audit_event, insert, one, tx
from ..core.deps import Principal, current_user, optional_user
from ..core.errors import bad_request, conflict, forbidden, not_found, unprocessable
from ..core.usernames import username_problem
from ..services import auth
from ..services.settings_store import require_enabled
from .common import clear_session_cookies, jsonable, pick

router = APIRouter(prefix='/me', tags=['perfil'])
MEDIA_DIR = Path(os.getenv('MEDIA_DIR', Path(__file__).resolve().parents[2] / 'media'))


def _profile(conn, user_id: str) -> dict:
    u = one(conn, 'select * from users where id=%s', (user_id,))
    roles = [r['code'] for r in all_(conn, '''select r.code from role_assignments ra join roles r on r.id=ra.role_id
                                              where ra.user_id=%s and ra.revoked_at is null''', (user_id,))]
    mfa = one(conn, 'select confirmed_at from mfa_factors where user_id=%s and disabled_at is null', (user_id,))
    out = pick(u, 'id', 'full_name', 'username', 'email', 'status', 'avatar_url', 'locale', 'timezone',
               'created_at', 'last_login_at', 'marketing_opt_in')
    out.update({'email_verified': u['email_verified_at'] is not None, 'roles': roles,
                'mfa_enabled': bool(mfa and mfa['confirmed_at']), 'has_password': u['password_hash'] is not None})
    return out


@router.get('/session', tags=['perfil'])
def session(p: Principal | None = Depends(optional_user)):
    """Estado da sessão sem erro 401 (evita ruído no navegador para visitantes)."""
    if not p:
        return {'authenticated': False}
    return {'authenticated': True, 'user': me(p)}


@router.get('')
def me(p: Principal = Depends(current_user)):
    with tx() as conn:
        out = _profile(conn, p.user_id)
    out['mfa_verified'] = p.mfa_verified
    out['permission_overrides'] = p.permissions
    out['unread_notifications'] = 0
    with tx() as conn:
        out['unread_notifications'] = one(conn, '''select count(*) n from notifications
                                                   where user_id=%s and read_at is null and hidden_by_user_at is null''',
                                          (p.user_id,))['n']
    return out


@router.get('/permissions')
def permissions(p: Principal = Depends(current_user)):
    return {'roles': sorted(p.roles), 'overrides': p.permissions}


class ProfileIn(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    username: str | None = Field(default=None, max_length=24)
    marketing_opt_in: bool | None = None


@router.patch('')
def update_me(body: ProfileIn, p: Principal = Depends(current_user)):
    data = body.model_dump(exclude_none=True)
    if 'full_name' in data and not 3 <= len(data['full_name'].strip()) <= 120:
        raise unprocessable('validation_error', 'Nome inválido.', fields={'full_name': 'Informe 3 a 120 caracteres.'})
    if 'username' in data and data['username'] != p.username:
        if problem := username_problem(data['username']):
            raise unprocessable('validation_error', 'Nome de usuário inválido.', fields={'username': problem})
    with tx() as conn:
        if 'username' in data and one(conn, 'select 1 from users where lower(username)=lower(%s) and id<>%s', (data['username'], p.user_id)):
            raise conflict('username_taken', 'Este nome de usuário já está em uso.', fields={'username': 'Indisponível.'})
        if data:
            sets = ', '.join(f'{k}=%s' for k in data)
            conn.execute(f'update users set {sets} where id=%s', (*[v.strip() if isinstance(v, str) else v for v in data.values()], p.user_id))
        if 'marketing_opt_in' in data:
            conn.execute('update notification_preferences set email_marketing=%s where user_id=%s', (data['marketing_opt_in'], p.user_id))
        return _profile(conn, p.user_id)


_MAGIC = {b'\x89PNG\r\n\x1a\n': 'png', b'\xff\xd8\xff': 'jpg', b'RIFF': 'webp'}


@router.post('/avatar')
async def upload_avatar(file: UploadFile = File(...), p: Principal = Depends(current_user)):
    data = await file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise bad_request('file_too_large', 'A imagem deve ter no máximo 2 MB.')
    ext = next((e for m, e in _MAGIC.items() if data.startswith(m)), None)
    if ext == 'webp' and data[8:12] != b'WEBP':
        ext = None
    if not ext:
        raise bad_request('invalid_image', 'Envie uma imagem PNG, JPEG ou WebP.')
    (MEDIA_DIR / 'avatars').mkdir(parents=True, exist_ok=True)
    name = f'{uuid.uuid4()}.{ext}'
    (MEDIA_DIR / 'avatars' / name).write_bytes(data)
    with tx() as conn:
        conn.execute('update users set avatar_url=%s where id=%s', (f'/api/media/avatars/{name}', p.user_id))
    return {'avatar_url': f'/api/media/avatars/{name}'}


class PasswordIn(BaseModel):
    current_password: str = Field(default='', max_length=128)
    new_password: str = Field(max_length=128)
    new_password_confirm: str = Field(max_length=128)


@router.post('/password')
def change_password(body: PasswordIn, p: Principal = Depends(current_user)):
    auth.change_password(p.user_id, p.session_id, body.current_password, body.new_password, body.new_password_confirm)
    return {'message': 'Senha alterada. As outras sessões foram encerradas.'}


class CodeIn(BaseModel):
    code: str = Field(max_length=20)


@router.get('/sessions')
def sessions(p: Principal = Depends(current_user)):
    with tx() as conn:
        rows = all_(conn, '''select id, ip, user_agent, created_at, last_seen_at, expires_at from auth_sessions
                             where user_id=%s and revoked_at is null and expires_at > %s order by last_seen_at desc''',
                    (p.user_id, timeutil.now()))
    return [{**jsonable(r), 'current': str(r['id']) == p.session_id} for r in rows]


@router.delete('/sessions/{session_id}')
def revoke_session(session_id: uuid.UUID, response: Response, p: Principal = Depends(current_user)):
    with tx() as conn:
        r = conn.execute("update auth_sessions set revoked_at=%s, revoked_reason='user_revoked' where id=%s and user_id=%s and revoked_at is null returning id",
                         (timeutil.now(), session_id, p.user_id)).fetchone()
    if not r:
        raise not_found('Sessão não encontrada.')
    if str(session_id) == p.session_id:
        clear_session_cookies(response)
    return {'ok': True}


@router.post('/sessions/revoke-others')
def revoke_others(p: Principal = Depends(current_user)):
    with tx() as conn:
        auth.revoke_all_sessions(conn, p.user_id, 'user_revoked_others', except_session=p.session_id)
    return {'ok': True}


@router.post('/mfa/setup')
def mfa_setup(p: Principal = Depends(current_user)):
    if not p.is_staff:
        raise forbidden('Autenticação em duas etapas reservada à equipe administrativa.')
    return auth.mfa_setup(p.user_id, p.username)


@router.post('/mfa/confirm')
def mfa_confirm(body: CodeIn, p: Principal = Depends(current_user)):
    if not p.is_staff:
        raise forbidden('Autenticação em duas etapas reservada à equipe administrativa.')
    return {'recovery_codes': auth.mfa_confirm(p.user_id, p.session_id, body.code),
            'message': 'Guarde os códigos de recuperação em local seguro. Eles não serão exibidos novamente.'}


@router.post('/mfa/disable')
def mfa_disable(body: CodeIn, p: Principal = Depends(current_user)):
    if not p.is_staff:
        raise forbidden('Autenticação em duas etapas reservada à equipe administrativa.')
    auth.mfa_disable(p.user_id, body.code)
    return {'ok': True}


# ------------------------------------------------------------ contas vinculadas
class LinkIn(BaseModel):
    provider: str
    public_url: str = Field(max_length=300)


PROFILE_PATTERNS = {
    'twitch': re.compile(r'^https://(www\.)?twitch\.tv/[A-Za-z0-9_]{3,25}/?$'),
    'kick': re.compile(r'^https://(www\.)?kick\.com/[A-Za-z0-9_-]{3,25}/?$'),
    'discord': re.compile(r'^https://(www\.)?discord\.com/users/\d{15,20}/?$'),
}


@router.get('/linked-accounts')
def linked(p: Principal = Depends(current_user)):
    with tx() as conn:
        rows = all_(conn, '''select id, provider, link_type, provider_email, display_name, public_url, linked_at
                             from linked_accounts where user_id=%s and unlinked_at is null order by provider''', (p.user_id,))
    return jsonable(rows)


@router.post('/linked-accounts', status_code=201)
def link_profile(body: LinkIn, p: Principal = Depends(current_user)):
    """Twitch/Kick/Discord: apenas URL de perfil PÚBLICO, claramente identificado (sem OAuth, nunca senha)."""
    pat = PROFILE_PATTERNS.get(body.provider)
    if not pat:
        raise bad_request('invalid_provider', 'Use o botão "Vincular Google" para contas Google.')
    if not pat.match(body.public_url.strip()):
        raise unprocessable('invalid_url', 'URL de perfil público inválida para este serviço.')
    with tx() as conn:
        if one(conn, 'select 1 from linked_accounts where user_id=%s and provider=%s and unlinked_at is null', (p.user_id, body.provider)):
            raise conflict('already_linked', 'Já existe um perfil deste serviço vinculado.')
        row = insert(conn, 'linked_accounts', {'user_id': p.user_id, 'provider': body.provider, 'link_type': 'public_profile',
                                               'public_url': body.public_url.strip(),
                                               'display_name': body.public_url.rstrip('/').rsplit('/', 1)[-1]})
    return jsonable(row)


@router.delete('/linked-accounts/{link_id}')
def unlink(link_id: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        row = one(conn, 'select * from linked_accounts where id=%s and user_id=%s and unlinked_at is null', (link_id, p.user_id))
        if not row:
            raise not_found()
        u = one(conn, 'select password_hash from users where id=%s', (p.user_id,))
        if row['provider'] == 'google' and not u['password_hash']:
            raise bad_request('needs_password', 'Defina uma senha antes de desvincular o Google para não perder o acesso.')
        conn.execute('update linked_accounts set unlinked_at=%s where id=%s', (timeutil.now(), link_id))
    return {'ok': True}


# ------------------------------------------------------------ preferências
class PrefsIn(BaseModel):
    email_queue_updates: bool | None = None
    email_reminders: bool | None = None
    email_marketing: bool | None = None
    in_app_enabled: bool | None = None
    reminder_minutes: list[int] | None = None


@router.get('/notification-preferences')
def get_prefs(p: Principal = Depends(current_user)):
    with tx() as conn:
        conn.execute('insert into notification_preferences(user_id) values (%s) on conflict (user_id) do nothing', (p.user_id,))
        return pick(one(conn, 'select * from notification_preferences where user_id=%s', (p.user_id,)),
                    'email_queue_updates', 'email_reminders', 'email_marketing', 'in_app_enabled', 'reminder_minutes')


@router.put('/notification-preferences')
def put_prefs(body: PrefsIn, p: Principal = Depends(current_user)):
    data = body.model_dump(exclude_none=True)
    if 'reminder_minutes' in data:
        if any(m not in (15, 10, 5, 1) for m in data['reminder_minutes']):
            raise unprocessable('validation_error', 'Avisos permitidos: 15, 10, 5 e 1 minuto.')
        data['reminder_minutes'] = sorted(set(data['reminder_minutes']) | {5}, reverse=True)  # 5 min é obrigatório
    with tx() as conn:
        conn.execute('insert into notification_preferences(user_id) values (%s) on conflict (user_id) do nothing', (p.user_id,))
        if data:
            sets = ', '.join(f'{k}=%s' for k in data)
            conn.execute(f'update notification_preferences set {sets} where user_id=%s', (*data.values(), p.user_id))
    return get_prefs(p)


# ------------------------------------------------------------ favoritos
# ----------------------------------------------------------------- teclas personalizadas (teclado/mouse → controle)
# Mesmas ações de frontend/src/lib/keymap.ts. Botões PS/Touchpad nunca são mapeáveis (bloqueados por segurança).
BINDABLE = {'cross', 'circle', 'square', 'triangle', 'l1', 'r1', 'l2', 'r2', 'l3', 'r3', 'options', 'share',
            'dpad_up', 'dpad_down', 'dpad_left', 'dpad_right',
            'ls_up', 'ls_down', 'ls_left', 'ls_right', 'rs_up', 'rs_down', 'rs_left', 'rs_right'}
KEY_CODE = re.compile(r'^(?:[A-Z][A-Za-z0-9]{1,23}|Mouse[0-4])$')     # KeyboardEvent.code ("KeyW", "ControlLeft") ou Mouse0–4


class BindingsIn(BaseModel):
    keys: dict[str, str] = Field(default_factory=dict)
    mouse_look: bool = True
    mouse_sensitivity: float = Field(default=1.0, ge=0.1, le=3.0)


@router.get('/input-bindings')
def get_bindings(p: Principal = Depends(current_user)):
    """null em "keys" = o jogador ainda usa o padrão do site."""
    with tx() as conn:
        u = one(conn, 'select input_bindings from users where id=%s', (p.user_id,))
    return u['input_bindings'] or {'keys': None, 'mouse_look': True, 'mouse_sensitivity': 1.0}


@router.put('/input-bindings')
def put_bindings(body: BindingsIn, p: Principal = Depends(current_user)):
    errors = {}
    for action, code in body.keys.items():
        if action not in BINDABLE:
            errors[f'keys.{action}'] = 'Ação desconhecida ou não mapeável.'
        elif not KEY_CODE.match(code or ''):
            errors[f'keys.{action}'] = 'Tecla inválida.'
    used = [c for c in body.keys.values()]
    dup = {c for c in used if used.count(c) > 1}
    if dup:
        errors['keys'] = 'A mesma tecla não pode fazer duas ações: ' + ', '.join(sorted(dup)) + '.'
    if errors:
        raise unprocessable('validation_error', 'Revise as teclas.', fields=errors)
    from psycopg.types.json import Jsonb
    data = body.model_dump()
    with tx() as conn:
        require_enabled(conn, 'controls_menu_enabled', 'A personalização de teclado e mouse está desativada.')
        conn.execute('update users set input_bindings=%s where id=%s', (Jsonb(data), p.user_id))
    return data


@router.delete('/input-bindings')
def reset_bindings(p: Principal = Depends(current_user)):
    with tx() as conn:
        require_enabled(conn, 'controls_menu_enabled', 'A personalização de teclado e mouse está desativada.')
        conn.execute('update users set input_bindings=null where id=%s', (p.user_id,))
    return {'keys': None, 'mouse_look': True, 'mouse_sensitivity': 1.0}


@router.get('/favorites')
def favorites(p: Principal = Depends(current_user)):
    with tx() as conn:
        return [str(r['game_id']) for r in all_(conn, 'select game_id from favorites where user_id=%s order by created_at desc', (p.user_id,))]


@router.put('/favorites/{game_id}')
def add_favorite(game_id: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        if not one(conn, "select 1 from games where id=%s and status='published' and deleted_at is null", (game_id,)):
            raise not_found('Jogo não encontrado.')
        conn.execute('insert into favorites(user_id, game_id) values (%s,%s) on conflict do nothing', (p.user_id, game_id))
    return {'ok': True}


@router.delete('/favorites/{game_id}')
def del_favorite(game_id: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        conn.execute('delete from favorites where user_id=%s and game_id=%s', (p.user_id, game_id))
    return {'ok': True}


# ------------------------------------------------------------ estatísticas e histórico
@router.get('/stats')
def stats(p: Principal = Depends(current_user)):
    with tx() as conn:
        s = one(conn, '''select coalesce(sum(seconds_used),0) secs, count(*) filter (where status in ('ended','expired')) sessions
                         from game_sessions where user_id=%s''', (p.user_id,))
        spent = one(conn, "select coalesce(sum(amount_cents),0) c from payments where user_id=%s and status='approved'", (p.user_id,))
        refunded = one(conn, '''select coalesce(sum(r.amount_cents),0) c from refunds r join payments pm on pm.id=r.payment_id
                                where pm.user_id=%s and r.status='completed' ''', (p.user_id,))
        fav = one(conn, 'select count(*) n from favorites where user_id=%s', (p.user_id,))
        top = all_(conn, '''select g.title, sum(s.seconds_used) secs from game_sessions s join reservations r on r.id=s.reservation_id
                            join games g on g.id=r.game_id where s.user_id=%s group by g.title order by 2 desc limit 3''', (p.user_id,))
    return {'minutes_played': int(s['secs']) // 60, 'sessions': s['sessions'],
            'total_spent_cents': int(spent['c']) - int(refunded['c']), 'favorites': fav['n'],
            'top_games': [{'title': t['title'], 'minutes': int(t['secs']) // 60} for t in top]}


@router.get('/payments')
def my_payments(p: Principal = Depends(current_user), q: str = Query('', max_length=120),
                method: str = '', status: str = '', date_from: date | None = None, date_to: date | None = None):
    if date_from and date_to and date_from > date_to:
        raise unprocessable('validation_error', 'A data final deve ser igual ou posterior à inicial.')
    conditions = ['pm.user_id=%s']
    params = [p.user_id]
    query = q.strip()
    if query:
        conditions.append('(strpos(lower(r.code), lower(%s)) > 0 or strpos(lower(g.title), lower(%s)) > 0)')
        params.extend((query, query))
    if method:
        conditions.append('pm.method=%s')
        params.append(method)
    if status:
        conditions.append('pm.status=%s')
        params.append(status)
    if date_from:
        conditions.append('(pm.created_at at time zone %s)::date >= %s')
        params.extend((timeutil.TZ.key, date_from))
    if date_to:
        conditions.append('(pm.created_at at time zone %s)::date <= %s')
        params.extend((timeutil.TZ.key, date_to))
    with tx() as conn:
        rows = all_(conn, f'''select pm.id, pm.status, pm.method, pm.provider, pm.amount_cents, pm.created_at, pm.approved_at,
                                    r.code reservation_code, g.title game_title,
                                    (select coalesce(sum(amount_cents),0) from refunds rf where rf.payment_id=pm.id and rf.status='completed') refunded_cents
                             from payments pm join reservations r on r.id=pm.reservation_id join games g on g.id=r.game_id
                             where {' and '.join(conditions)} order by pm.created_at desc, pm.id limit 200''', params)
    return jsonable(rows)


# ------------------------------------------------------------ notificações in-app
@router.get('/notifications')
def notifications_list(p: Principal = Depends(current_user), unread: bool = False):
    with tx() as conn:
        rows = all_(conn, '''select id, event_code, title, body, link, read_at, created_at from notifications
                            where user_id=%s and hidden_by_user_at is null and (not %s or read_at is null)
                            order by created_at desc, id limit 100''', (p.user_id, unread))
    return jsonable(rows)


@router.post('/notifications/{nid}/read')
def notif_read(nid: uuid.UUID, p: Principal = Depends(current_user)):
    with tx() as conn:
        conn.execute('''update notifications set read_at=%s
                        where id=%s and user_id=%s and read_at is null and hidden_by_user_at is null''',
                     (timeutil.now(), nid, p.user_id))
    return {'ok': True}


@router.post('/notifications/read-all')
def notif_read_all(p: Principal = Depends(current_user)):
    with tx() as conn:
        conn.execute('''update notifications set read_at=%s
                        where user_id=%s and read_at is null and hidden_by_user_at is null''', (timeutil.now(), p.user_id))
    return {'ok': True}


@router.delete('/notifications', status_code=204)
def clear_notifications(p: Principal = Depends(current_user)):
    with tx() as conn:
        cleared = conn.execute('''update notifications set hidden_by_user_at=%s
                                  where user_id=%s and hidden_by_user_at is null''', (timeutil.now(), p.user_id)).rowcount
        if cleared:
            audit_event(conn, 'notifications.cleared_by_user', 'notifications', details={'count': cleared})


# ------------------------------------------------------------ LGPD
@router.get('/export')
def export(p: Principal = Depends(current_user)):
    """Portabilidade/acesso: dados pessoais do titular em JSON (sem segredos)."""
    with tx() as conn:
        data = {
            'perfil': _profile(conn, p.user_id),
            'reservas': all_(conn, 'select code, status, starts_at, ends_at, minutes, total_cents, created_at from reservations where user_id=%s', (p.user_id,)),
            'pagamentos': all_(conn, 'select status, method, amount_cents, created_at from payments where user_id=%s', (p.user_id,)),
            'sessoes': all_(conn, 'select status, contract_starts_at, contract_ends_at, seconds_used from game_sessions where user_id=%s', (p.user_id,)),
            'favoritos': all_(conn, 'select g.title from favorites f join games g on g.id=f.game_id where f.user_id=%s', (p.user_id,)),
            'contas_vinculadas': all_(conn, 'select provider, link_type, public_url, linked_at from linked_accounts where user_id=%s', (p.user_id,)),
            'aceites': all_(conn, '''select d.kind, d.version, a.accepted_at, a.context from policy_acceptances a
                                     join policy_documents d on d.id=a.policy_id where a.user_id=%s''', (p.user_id,)),
            'chamados': all_(conn, 'select subject, status, created_at from support_tickets where user_id=%s', (p.user_id,)),
        }
        audit_event(conn, 'lgpd.export', 'users', p.user_id)
    return jsonable(data)


class DataRequestIn(BaseModel):
    request_type: str
    details: str = Field(default='', max_length=2000)


@router.get('/data-requests')
def data_requests(p: Principal = Depends(current_user)):
    with tx() as conn:
        return jsonable(all_(conn, 'select * from data_subject_requests where user_id=%s order by created_at desc', (p.user_id,)))


@router.post('/data-requests', status_code=201)
def create_data_request(body: DataRequestIn, p: Principal = Depends(current_user)):
    if body.request_type not in ('access', 'rectification', 'deletion', 'portability', 'consent_revocation'):
        raise unprocessable('validation_error', 'Tipo de solicitação inválido.')
    with tx() as conn:
        if one(conn, "select 1 from data_subject_requests where user_id=%s and request_type=%s and status in ('open','in_progress')",
               (p.user_id, body.request_type)):
            raise conflict('request_open', 'Já existe uma solicitação deste tipo em andamento.')
        row = insert(conn, 'data_subject_requests', {'user_id': p.user_id, 'request_type': body.request_type, 'details': body.details})
    return jsonable(row)

"""Google OAuth 2.0 / OpenID Connect (Authorization Code + PKCE).

Não associa contas apenas por coincidência de e-mail: se já existir conta com o
mesmo e-mail e sem vínculo Google, o usuário precisa entrar com senha e vincular
pelo perfil (prova de propriedade das duas contas).
BLOQUEADO POR DEPENDÊNCIA EXTERNA até GOOGLE_CLIENT_ID/SECRET serem configurados.
"""
import base64
import hashlib
import re
import secrets
from datetime import timedelta
from urllib.parse import urlencode

import httpx

from ..config import settings
from ..core import security, timeutil
from ..core.db import insert, tx
from ..core.errors import AppError
from ..core.usernames import username_problem
from . import auth
from .settings_store import get_settings

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    return settings.frontend_url.rstrip('/') + '/api/auth/google/callback'


def start(intent: str, user_id: str | None) -> str:
    if not configured():
        raise AppError(503, 'google_not_configured', 'Login com Google ainda não foi configurado neste ambiente.')
    state = security.new_token()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    with tx(actor_id=user_id) as conn:
        insert(conn, 'oauth_states', {'provider': 'google', 'state_hash': security.sha256(state), 'code_verifier': verifier,
                                      'intent': intent, 'user_id': user_id, 'expires_at': timeutil.now() + timedelta(minutes=10)})
    return AUTH_URL + '?' + urlencode({'client_id': settings.google_client_id, 'redirect_uri': redirect_uri(),
                                       'response_type': 'code', 'scope': 'openid email profile', 'state': state,
                                       'code_challenge': challenge, 'code_challenge_method': 'S256',
                                       'prompt': 'select_account'})


def _unique_username(conn, name: str) -> str:
    base = re.sub(r'[^A-Za-z0-9_]', '', (name or 'jogador').split(' ')[0])[:16] or 'jogador'
    if len(base) < 3:
        base = (base + 'jogador')[:8]
    if username_problem(base):
        base = 'jogador'
    candidate = base
    while conn.execute('select 1 from users where lower(username)=lower(%s)', (candidate,)).fetchone():
        candidate = f'{base}{secrets.randbelow(9999):04d}'
    return candidate


def callback(code: str, state: str, ip: str, ua: str) -> dict:
    """Retorna {'session_token'?, 'redirect'}."""
    if not configured():
        raise AppError(503, 'google_not_configured', 'Login com Google não configurado.')
    with tx() as conn:
        st = conn.execute('select * from oauth_states where state_hash=%s for update', (security.sha256(state or ''),)).fetchone()
        if not st or st['used_at'] or st['expires_at'] <= timeutil.now():
            raise AppError(400, 'invalid_state', 'Sessão de login expirada. Tente novamente.')
        conn.execute('update oauth_states set used_at=%s where id=%s', (timeutil.now(), st['id']))
    try:
        tok = httpx.post(TOKEN_URL, timeout=10, data={
            'code': code, 'client_id': settings.google_client_id, 'client_secret': settings.google_client_secret,
            'redirect_uri': redirect_uri(), 'grant_type': 'authorization_code', 'code_verifier': st['code_verifier']})
        tok.raise_for_status()
        info = httpx.get(USERINFO_URL, timeout=10, headers={'Authorization': f"Bearer {tok.json()['access_token']}"})
        info.raise_for_status()
        info = info.json()
    except (httpx.HTTPError, KeyError, ValueError):
        raise AppError(502, 'google_error', 'Não foi possível concluir o login com Google.')
    sub, email = info.get('sub'), (info.get('email') or '').lower()
    if not sub or not email or not info.get('email_verified'):
        raise AppError(400, 'google_email_unverified', 'A conta Google precisa ter e-mail verificado.')
    with tx(actor_id=str(st['user_id']) if st['user_id'] else None) as conn:
        linked = conn.execute("""select l.user_id from linked_accounts l join users u on u.id=l.user_id
                                 where l.provider='google' and l.provider_subject=%s and l.unlinked_at is null
                                 and u.deleted_at is null""", (sub,)).fetchone()
        if st['intent'] == 'link':
            if linked and str(linked['user_id']) != str(st['user_id']):
                return {'redirect': '/perfil?google=ja_vinculado'}
            if not linked:
                insert(conn, 'linked_accounts', {'user_id': st['user_id'], 'provider': 'google', 'link_type': 'oauth',
                                                 'provider_subject': sub, 'provider_email': email,
                                                 'display_name': info.get('name')})
            return {'redirect': '/perfil?google=vinculado'}
        if linked:
            user_id = str(linked['user_id'])
            u = conn.execute('select status from users where id=%s', (user_id,)).fetchone()
            if u['status'] == 'suspended':
                return {'redirect': '/entrar?erro=conta_suspensa'}
        else:
            if conn.execute('select 1 from users where lower(email)=%s and deleted_at is null', (email,)).fetchone():
                return {'redirect': '/entrar?erro=google_vincular'}
            if not get_settings(conn).get('signup_enabled', True):
                return {'redirect': '/entrar?erro=cadastro_desativado'}
            u = insert(conn, 'users', {'full_name': (info.get('name') or email.split('@')[0])[:120].ljust(3, '_'),
                                       'username': _unique_username(conn, info.get('given_name') or info.get('name') or ''),
                                       'email': email, 'status': 'active', 'email_verified_at': timeutil.now(),
                                       'password_hash': None})
            user_id = str(u['id'])
            conn.execute("insert into role_assignments(user_id, role_id) select %s, id from roles where code='client'", (user_id,))
            conn.execute('insert into notification_preferences(user_id) values (%s)', (user_id,))
            insert(conn, 'linked_accounts', {'user_id': user_id, 'provider': 'google', 'link_type': 'oauth',
                                             'provider_subject': sub, 'provider_email': email, 'display_name': info.get('name')})
        conn.execute('update users set last_login_at=%s where id=%s', (timeutil.now(), user_id))
        token = auth.create_session(conn, user_id, ip, ua)
    return {'session_token': token, 'redirect': '/'}

"""Login Sony (OAuth do Remote Play) executado pelo servidor.

Usado quando a conta PSN do proprietário ainda não tem agente (antes da aprovação).
Mesma lógica de agent/remoteplay/psn/oauth.py. As credenciais do cliente são
identificadores públicos do aplicativo Remote Play, não dados do usuário.
"""
from __future__ import annotations

import base64
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from ..core.errors import AppError, unprocessable

CLIENT_ID = 'ba495a24-818c-472b-b12d-ff231c1b5745'
CLIENT_SECRET = base64.b64decode('bXZhaVprUnNBc0kxSUJrWQ==').decode('ascii')
REDIRECT = 'https://remoteplay.dl.playstation.net/remoteplay/redirect'
TOKEN_URL = 'https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token'
AUTHORIZE_URL = 'https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize'
SCOPE = ('psn:clientapp referenceDataService:countryConfig.read pushNotification:webSocket.desktop.connect '
         'sessionManager:remotePlaySession.system.update')
REMOTE_PLAY_DUID_PREFIX = '0000000700410080'


def login_url() -> str:
    params = {'service_entity': 'urn:service-entity:psn', 'response_type': 'code',
              'client_id': CLIENT_ID, 'redirect_uri': REDIRECT, 'scope': SCOPE,
              'request_locale': 'pt_BR', 'ui': 'pr', 'service_logo': 'ps',
              'layout_type': 'popup', 'smcid': 'remoteplay', 'prompt': 'always',
              'PlatformPrivacyWs1': 'minimal',
              'duid': REMOTE_PLAY_DUID_PREFIX + secrets.token_hex(16)}
    return AUTHORIZE_URL + '?' + urlencode(params)


def parse_redirect(redirect_url: str) -> str:
    u, expected = urlparse(redirect_url.strip()), urlparse(REDIRECT)
    if u.scheme != 'https' or u.netloc != expected.netloc or u.path != expected.path:
        raise unprocessable('psn_login_failed', 'URL inválida: copie o endereço completo da página de retorno da Sony.')
    q = parse_qs(u.query)
    if q.get('error'):
        raise unprocessable('psn_login_failed', 'O login PSN foi recusado. Comece o login de novo e autorize.')
    code = q.get('code', [''])[0]
    if not (2 <= len(code) <= 4096):
        raise unprocessable('psn_login_failed', 'A URL da Sony não contém código de autorização válido.')
    return code


def request_token(client: httpx.Client, *, code: str | None = None, refresh_token: str | None = None) -> dict:
    payload = ({'grant_type': 'authorization_code', 'code': code}
               if code is not None else {'grant_type': 'refresh_token', 'refresh_token': refresh_token})
    payload.update(scope=SCOPE, redirect_uri=REDIRECT)
    try:
        res = client.post(TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET), data=payload, timeout=20,
                          headers={'Content-Type': 'application/x-www-form-urlencoded'})
    except httpx.HTTPError as e:
        raise AppError(502, 'sony_unreachable', 'A Sony não respondeu durante a autenticação. Tente novamente.') from e
    if res.status_code != 200:
        try:
            details = res.json()
        except ValueError:
            details = None
        if isinstance(details, dict) and details.get('error') == 'invalid_grant':
            raise unprocessable('psn_token_expired', 'A Sony recusou a autorização (código usado ou expirado). Faça o login de novo.')
        raise AppError(502, 'psn_login_failed', f'A Sony recusou a solicitação de autenticação (HTTP {res.status_code}).')
    data = res.json()
    if not data.get('access_token'):
        raise AppError(502, 'psn_login_failed', 'O serviço Sony não retornou um token de acesso.')
    return {'access_token': str(data['access_token']),
            'refresh_token': str(data.get('refresh_token') or refresh_token or ''),
            'expires_at': int(time.time()) + max(0, int(data.get('expires_in', 3600)))}


def account_info(client: httpx.Client, access_token: str) -> dict:
    try:
        res = client.get(f'{TOKEN_URL}/{access_token}', auth=(CLIENT_ID, CLIENT_SECRET), timeout=20)
    except httpx.HTTPError as e:
        raise AppError(502, 'sony_unreachable', 'Não foi possível consultar o perfil PSN na Sony.') from e
    if res.status_code in (401, 403):
        raise unprocessable('psn_token_expired', 'A Sony recusou o token de acesso. Faça o login de novo.')
    if res.status_code != 200:
        raise AppError(502, 'psn_login_failed', f'A Sony não retornou os dados da conta (HTTP {res.status_code}).')
    info = res.json()
    user_id = str(info.get('user_id') or '')
    if not user_id.isdecimal():
        raise AppError(502, 'psn_login_failed', 'A Sony retornou um account-id inválido.')
    return {'account_id': base64.b64encode(int(user_id).to_bytes(8, 'little')).decode('ascii'),
            'online_id': str(info.get('online_id') or info.get('username') or '')}


def login(redirect_url: str) -> tuple[dict, dict]:
    code = parse_redirect(redirect_url)
    with httpx.Client(follow_redirects=False) as client:
        credentials = request_token(client, code=code)
        return credentials, account_info(client, credentials['access_token'])


def refresh(refresh_token: str) -> tuple[dict, dict]:
    with httpx.Client(follow_redirects=False) as client:
        credentials = request_token(client, refresh_token=refresh_token)
        return credentials, account_info(client, credentials['access_token'])

# SPDX-License-Identifier: AGPL-3.0-only
"""Sony Remote Play OAuth — isolated from the API/database.

The Sony endpoints and OAuth client constants can change without prior notice.
The client credentials below are public application identifiers from the
previously embedded pyremoteplay OAuth module, not the user's PSN credentials.
"""
from __future__ import annotations

import base64
import logging
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CLIENT_ID = 'ba495a24-818c-472b-b12d-ff231c1b5745'
CLIENT_SECRET = base64.b64decode('bXZhaVprUnNBc0kxSUJrWQ==').decode('ascii')
REDIRECT = 'https://remoteplay.dl.playstation.net/remoteplay/redirect'
TOKEN_URL = 'https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/token'
AUTHORIZE_URL = 'https://auth.api.sonyentertainmentnetwork.com/2.0/oauth/authorize'
SCOPE = 'psn:clientapp referenceDataService:countryConfig.read pushNotification:webSocket.desktop.connect sessionManager:remotePlaySession.system.update'
REMOTE_PLAY_DUID_PREFIX = '0000000700410080'


class OAuthError(RuntimeError):
    pass


class OAuthCredentialsRejected(OAuthError):
    pass


def _hide_token_url(record: logging.LogRecord) -> bool:
    # O HTTPX registra a URL da requisição como argumento do log INFO.
    if isinstance(record.args, tuple):
        record.args = tuple(
            TOKEN_URL + '/[redacted]' if str(arg).startswith(TOKEN_URL + '/') else arg
            for arg in record.args
        )
    return True


logging.getLogger('httpx').addFilter(_hide_token_url)


def login_url() -> str:
    params = {'service_entity': 'urn:service-entity:psn', 'response_type': 'code',
              'client_id': CLIENT_ID, 'redirect_uri': REDIRECT, 'scope': SCOPE,
              'request_locale': 'pt_BR', 'ui': 'pr', 'service_logo': 'ps',
              'layout_type': 'popup', 'smcid': 'remoteplay', 'prompt': 'always',
              'PlatformPrivacyWs1': 'minimal',
              # Identifica esta autorização como originada de um cliente Remote Play.
              'duid': REMOTE_PLAY_DUID_PREFIX + secrets.token_hex(16)}
    return AUTHORIZE_URL + '?' + urlencode(params)


def parse_redirect(redirect_url: str) -> str:
    if len(redirect_url) > 8192:
        raise OAuthError('URL de retorno muito longa.')
    u, expected = urlparse(redirect_url), urlparse(REDIRECT)
    if u.scheme != 'https' or u.netloc != expected.netloc or u.path != expected.path:
        raise OAuthError('URL inválida: copie o endereço completo da página de retorno da Sony.')
    q = parse_qs(u.query)
    if q.get('error'):
        raise OAuthError('O login PSN foi recusado. Abra o vínculo e autorize novamente.')
    code = q.get('code', [''])[0]
    if not (2 <= len(code) <= 4096):
        raise OAuthError('A URL da Sony não contém código de autorização válido.')
    return code


async def request_token(client: httpx.AsyncClient, *, code: str | None = None, refresh_token: str | None = None) -> dict:
    if bool(code) == bool(refresh_token):
        raise OAuthError('Informe um código OU um refresh token.')
    payload = ({'grant_type': 'authorization_code', 'code': code}
               if code is not None else {'grant_type': 'refresh_token', 'refresh_token': refresh_token})
    payload.update(scope=SCOPE, redirect_uri=REDIRECT)
    try:
        res = await client.post(TOKEN_URL, auth=(CLIENT_ID, CLIENT_SECRET),
                                data=payload, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=20)
    except httpx.HTTPError as e:
        raise OAuthError('A Sony não respondeu durante a autenticação. Tente novamente.') from e
    if res.status_code != 200:
        try:
            details = res.json()
        except ValueError:
            details = None
        if isinstance(details, dict) and details.get('error') == 'invalid_grant':
            raise OAuthCredentialsRejected('A Sony recusou a autorização (invalid_grant). Vincule a conta novamente.')
        raise OAuthError(f'A Sony recusou a solicitação de autenticação (HTTP {res.status_code}).')
    try:
        data = res.json()
    except ValueError as e:
        raise OAuthError('Resposta inválida do serviço de login Sony.') from e
    if not data.get('access_token'):
        raise OAuthError('O serviço Sony não retornou um token de acesso.')
    return {'access_token': str(data['access_token']),
            'refresh_token': str(data.get('refresh_token') or refresh_token or ''),
            'expires_at': int(time.time()) + max(0, int(data.get('expires_in', 3600))) }


async def account_info(client: httpx.AsyncClient, access_token: str) -> dict:
    try:
        # Endpoint already used by the incorporated pyremoteplay library.
        res = await client.get(f'{TOKEN_URL}/{access_token}', auth=(CLIENT_ID, CLIENT_SECRET), timeout=20)
    except httpx.HTTPError as e:
        raise OAuthError('Não foi possível consultar o perfil PSN na Sony.') from e
    if res.status_code in (401, 403):
        raise OAuthCredentialsRejected('A Sony recusou o token de acesso. Vincule a conta novamente.')
    if res.status_code != 200:
        raise OAuthError(f'A Sony não retornou os dados da conta (HTTP {res.status_code}).')
    info = res.json()
    user_id = str(info.get('user_id') or '')
    if not user_id.isdecimal():
        raise OAuthError('A Sony retornou um account-id inválido.')
    return {'account_id': base64.b64encode(int(user_id).to_bytes(8, 'little')).decode('ascii'),
            'online_id': str(info.get('online_id') or info.get('username') or '')}

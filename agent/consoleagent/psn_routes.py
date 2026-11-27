"""PSN account management endpoints for the existing ConsoleAgent.

All routes require the same API->agent Bearer token as console actions.
No access/refresh token, pairing key or redirect code is returned or logged.
"""
from __future__ import annotations

import asyncio
import hmac
import os
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from remoteplay.psn.accounts import DEFAULT_PATH, PsnAccountStore, AccountError, shared_store
from remoteplay.psn.oauth import OAuthCredentialsRejected, OAuthError, account_info, login_url, parse_redirect, request_token
from remoteplay.psn.devices import DeviceDiscoveryUnavailable, list_psn_devices
from remoteplay.psn.connection import open_ps4_connection, reserve_ps4_account
from remoteplay.psn.negotiation import NegotiationError
from pyremoteplay.receiver import AVReceiver
from .links import _make_receiver
from . import discovery


class Start(BaseModel):
    label: str = Field(min_length=1, max_length=80)


class Finish(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    redirect_url: str = Field(min_length=10, max_length=8192)


class ChiakiImport(BaseModel):
    label: str = Field(min_length=1, max_length=80)


def create_psn_router(token: str, data_path: str | Path | None = None, protector=None,
                      *, discover=discovery.discover) -> APIRouter:
    """Lazy store loading allows the existing legacy agent to run unmodified.

    If DPAPI fails, endpoints return explicit errors; credentials never fall back
    to cleartext or any shared server-side key.
    """
    router = APIRouter(prefix='/v1/psn/accounts', tags=['psn'])
    path = Path(data_path) if data_path else DEFAULT_PATH
    expected = f'Bearer {token}'.encode('utf-8')
    pending: dict[str, float] = {}
    remote_diagnostics: set[str] = set()
    store: PsnAccountStore | None = None

    def error(status: int, code: str, detail: str) -> JSONResponse:
        return JSONResponse(status_code=status, content={'code': code, 'message': detail})

    def vault() -> PsnAccountStore:
        nonlocal store
        if store is None:
            # Sem protetor de teste: a mesma instância usada pelas conexões PSN (tokens e travas em comum).
            store = shared_store(path) if protector is None else PsnAccountStore(path, protector=protector)
        return store

    def authorize(req: Request):
        if not hmac.compare_digest((req.headers.get('authorization') or '').encode('utf-8'), expected):
            return error(401, 'unauthorized', 'Credencial do ConsoleAgent inválida.')
        return None

    @router.post('/{account_id}/login/start')
    async def login_start(account_id: str, body: Start, request: Request):
        if failure := authorize(request):
            return failure
        try:
            vault().upsert(account_id, body.label)
        except (AccountError, RuntimeError) as e:
            return error(503, 'vault_error', str(e))
        pending[account_id] = time.monotonic() + 600
        return {'ok': True, 'login_url': login_url(), 'message': 'Abra a página Sony e cole a URL final no painel em até 10 minutos.'}

    @router.post('/{account_id}/login/finish')
    async def login_finish(account_id: str, body: Finish, request: Request):
        if failure := authorize(request):
            return failure
        if pending.get(account_id, 0) < time.monotonic():
            return error(409, 'login_expired', 'Inicie o login novamente no painel (prazo: 10 minutos).')
        try:
            code = parse_redirect(body.redirect_url)
            async with httpx.AsyncClient() as client:
                credentials = await request_token(client, code=code)
                profile = await account_info(client, credentials['access_token'])
            meta = vault().upsert(account_id, body.label, **credentials, **profile, status='linked',
                                  last_check_at=time.time(), last_error='')
            pending.pop(account_id, None)
            return {'ok': True, 'account': meta}
        except (OAuthError, AccountError, RuntimeError) as e:
            return error(422, 'psn_login_failed', str(e))

    @router.post('/{account_id}/test')
    async def test(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            s = vault()
            async with s.refresh_lock(account_id):
                record = s.get(account_id)
                if not record:
                    raise AccountError('Conta não vinculada no agente.')
                if record.get('status') == 'disabled':
                    raise AccountError('Conta desativada no painel.')
                access = record.get('access_token')
                renewed = not access or float(record.get('expires_at') or 0) <= time.time()
                async with httpx.AsyncClient() as client:
                    if renewed:
                        if not record.get('refresh_token'):
                            raise OAuthCredentialsRejected('A conta não possui refresh token. Faça o login novamente.')
                        credentials = await request_token(client, refresh_token=record['refresh_token'])
                        access = credentials['access_token']
                        s.update(account_id, **credentials)
                    profile = await account_info(client, access)
                meta = s.update(account_id, **profile, status='linked',
                                last_check_at=time.time(), last_error='')
                action = 'renovado e validado' if renewed else 'validado'
                return {'ok': True, 'account': meta, 'message': f'Token Sony {action}. A conexão com o videogame ainda não foi testada.'}
        except OAuthCredentialsRejected as e:
            try:
                vault().update(account_id, status='expired', last_error=str(e), last_check_at=time.time())
            except AccountError:
                pass
            return error(422, 'psn_token_expired', str(e))
        except OAuthError as e:
            return error(502, 'psn_validation_failed', str(e))
        except (AccountError, RuntimeError) as e:
            return error(422, 'psn_test_failed', str(e))

    @router.get('/{account_id}')
    async def get_account(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            data = vault().public_get(account_id)
            if not data:
                return error(404, 'not_found', 'Conta PSN não encontrada no agente.')
            return data
        except (AccountError, RuntimeError) as e:
            return error(503, 'vault_error', str(e))

    @router.post('/{account_id}/disable')
    async def disable(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            return {'ok': True, 'account': vault().update(account_id, status='disabled')}
        except (AccountError, RuntimeError) as e:
            return error(404, 'not_found', str(e))

    @router.post('/{account_id}/enable')
    async def enable(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            return {'ok': True, 'account': vault().update(account_id, status='pending',
                                                             last_error='É necessário validar o login Sony novamente.')}
        except (AccountError, RuntimeError) as e:
            return error(404, 'not_found', str(e))

    @router.delete('/{account_id}')
    async def remove(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            return {'ok': vault().delete(account_id)}
        except (AccountError, RuntimeError) as e:
            return error(503, 'vault_error', str(e))

    @router.post('/{account_id}/import/chiaki')
    async def import_from_chiaki(account_id: str, body: ChiakiImport, request: Request):
        if failure := authorize(request):
            return failure
        if os.name != 'nt':
            return error(501, 'windows_only', 'Importação do Chiaki disponível somente no Windows.')
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Chiaki\Chiaki\settings') as key:
                def val(name):
                    try:
                        return str(winreg.QueryValueEx(key, name)[0])
                    except FileNotFoundError:
                        return ''
                refresh = val('psn_refresh_token')
                access = val('psn_auth_token')
                expiry = val('psn_auth_token_expiry')
                identifier = val('psn_account_id')
            if not refresh:
                raise AccountError('Chiaki não possui refresh token nesse usuário Windows. Faça login no Chiaki primeiro.')
            try:
                expires_at = float(expiry)
            except ValueError:
                expires_at = 0
            meta = vault().upsert(account_id, body.label, refresh_token=refresh, access_token=access,
                                  expires_at=expires_at, account_id=identifier, online_id='',
                                  status='pending', last_check_at=time.time(), last_error='Valide o token importado.')
            return {'ok': True, 'account': meta, 'message': 'Credencial importada e cifrada. Execute "Testar conta" para verificar na Sony.'}
        except (OSError, AccountError, RuntimeError) as e:
            return error(422, 'chiaki_import_failed', str(e))

    @router.post('/{account_id}/diagnose/ps4-psn')
    async def diagnose_ps4_psn(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        if account_id in remote_diagnostics:
            return error(409, 'psn_diagnostic_running', 'Já existe um diagnóstico PSN para esta conta.')
        remote_diagnostics.add(account_id)
        messages = []
        stage = duid = None

        def progress(next_stage, message, identifier=None):
            nonlocal stage, duid
            stage = next_stage
            duid = identifier or duid
            messages.append(message)

        async def run():
            with reserve_ps4_account(account_id):
                async with asyncio.timeout(58), httpx.AsyncClient(follow_redirects=False) as client:
                    token = await vault().access_token(
                        account_id, lambda refresh: request_token(client, refresh_token=refresh),
                    )
                    async with open_ps4_connection(client, token, _make_receiver(AVReceiver), progress):
                        messages.append('Áudio e controles ainda não foram verificados.')

        try:
            # Laço próprio numa thread: a decodificação do vídeo não pode travar o WebRTC dos outros consoles.
            await run_in_threadpool(asyncio.run, run())
        except (NegotiationError, OSError) as exc:
            if stage is None:
                code = getattr(exc, 'stage', 'transport_unavailable')
                status = 504 if isinstance(exc, TimeoutError) else 422
                return error(status, f'psn_{code}', str(exc) or 'O diagnóstico PSN excedeu o tempo limite.')
            messages.append(str(exc) or 'O diagnóstico PSN excedeu o tempo limite.')
        except AccountError as exc:
            return error(422, 'psn_account_unavailable', str(exc))
        finally:
            remote_diagnostics.discard(account_id)
        return {'ok': True, 'stage': stage, 'duid': duid, 'message': ' '.join(messages)}

    @router.post('/{account_id}/devices/ps4-lan')
    async def discover_ps4(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            consoles = await run_in_threadpool(discover, None, 'PS4')
        except OSError:
            return error(503, 'lan_discovery_failed', 'O agente não conseguiu buscar PS4 na rede local.')
        return {'ok': True, 'devices': [console.to_dict() for console in consoles]}

    @router.post('/{account_id}/devices')
    async def list_devices(account_id: str, request: Request):
        if failure := authorize(request):
            return failure
        try:
            s = vault()
            async with s.refresh_lock(account_id):
                record = s.get(account_id)
                if not record or record.get('status') != 'linked':
                    raise AccountError('Conta PSN não está vinculada e ativa. Entre novamente na Sony.')
                async with httpx.AsyncClient() as client:
                    token = record.get('access_token', '')
                    if not token or float(record.get('expires_at') or 0) < time.time() + 120:
                        if not record.get('refresh_token'):
                            raise OAuthError('Refresh token ausente. Faça o login novamente.')
                        credentials = await request_token(client, refresh_token=record['refresh_token'])
                        s.update(account_id, **credentials)
                        token = credentials['access_token']
                    devices = await list_psn_devices(client, token)
            return {'ok': True, 'devices': devices, 'ps4_note':
                    'A Sony não expõe o PS4 principal nesta listagem PS5. O PS4 principal da conta é alcançado pela negociação PSN '
                    '(use "Diagnosticar PS4 pela PSN" ou o teste de conexão do console).',
                    'message': f'{len(devices)} PS5 consultado(s) na Sony. A consulta não testa o streaming.'}
        except (AccountError, OAuthError, DeviceDiscoveryUnavailable, RuntimeError) as e:
            return error(422, 'psn_devices_failed', str(e))

    return router

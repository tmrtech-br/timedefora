"""PSN accounts (metadata only). Secrets remain encrypted inside the Windows ConsoleAgent.

Admin endpoints use existing cookie auth, CSRF protection and audit trail.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import settings
from ..core import security
from ..core.db import all_, audit_event, insert, one, tx, update
from ..core.deps import Principal, require_role
from ..core.errors import AppError, conflict, forbidden, not_found, unprocessable
from ..services import psn_oauth
from .common import DeleteIn, jsonable

router = APIRouter(prefix='/admin/psn-accounts', tags=['admin-psn'])
OPERATOR = require_role('operator')
ADMIN = require_role('admin')


class NewAccount(BaseModel):
    label: str = Field(min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_.\- ]+$')
    agent_id: uuid.UUID


class ChangeAccount(BaseModel):
    label: str | None = Field(default=None, min_length=2, max_length=80, pattern=r'^[a-zA-Z0-9_.\- ]+$')
    status: str | None = None


class FinishLogin(BaseModel):
    redirect_url: str = Field(min_length=10, max_length=8192)


def _account(conn, account_id, lock=False, owner_user_id: str | None = None):
    row = one(conn, 'select * from psn_accounts where id=%s' + (' for update' if lock else ''), (account_id,))
    if not row or (owner_user_id is not None and str(row['owner_user_id']) != owner_user_id):
        raise not_found('Conta PSN não encontrada.')
    return row


def _agent(conn, agent_id):
    a = one(conn, 'select id, name, endpoint_url, outbound_token_enc, is_simulated from console_agents where id=%s', (agent_id,))
    if not a:
        raise not_found('Agente não encontrado.')
    if a['is_simulated']:
        raise unprocessable('invalid_agent', 'Não é possível vincular PSN a um agente simulado.')
    if not a['endpoint_url'] or not a['outbound_token_enc']:
        raise unprocessable('agent_not_ready', 'Configure o endpoint e os tokens do agente antes de vincular uma conta PSN.')
    return a


def _agent_target(conn, row) -> tuple[str, str]:
    """Endereço e credencial do agente da conta (lidos dentro da transação; a chamada HTTP fica fora dela)."""
    if row['agent_id'] is None:
        raise conflict('agent_required', 'Associe um console com agente autorizado antes de vincular o login Sony.')
    a = _agent(conn, row['agent_id'])
    return f"{a['endpoint_url'].rstrip('/')}/v1/psn/accounts/{row['id']}", security.decrypt(a['outbound_token_enc'])


def _call_agent(conn, row, suffix: str, payload: dict | None = None, method='POST') -> dict:
    return _send_agent(_agent_target(conn, row), suffix, payload, method)


def _send_agent(target: tuple[str, str], suffix: str, payload: dict | None = None, method='POST') -> dict:
    base, token = target
    url = base + suffix
    try:
        with httpx.Client(timeout=65, follow_redirects=False) as c:
            response = c.request(method, url, headers={'Authorization': f'Bearer {token}'},
                                 json=payload if payload is not None else {})
    except httpx.HTTPError as e:
        raise AppError(502, 'agent_unreachable', 'O agente não respondeu. Confira se o programa está executando no PC.') from e
    try:
        data = response.json()
    except ValueError:
        raise AppError(502, 'agent_invalid_response', 'O agente devolveu uma resposta inválida.')
    if not isinstance(data, dict):
        raise AppError(502, 'agent_invalid_response', 'O agente devolveu uma resposta inválida.')
    if not response.is_success:
        message = str(data.get('message') or 'Ocorreu uma falha no agente.')[0:500]
        raise AppError(response.status_code if 400 <= response.status_code < 500 else 502,
                       str(data.get('code') or 'agent_error')[:80], message)
    return data


@router.get('')
def list_accounts(p: Principal = Depends(OPERATOR)):
    with tx() as conn:
        rows = all_(conn, '''select p.id, p.agent_id, p.owner_user_id, a.name agent_name, p.label, p.online_id, p.account_id, p.status,
                                    p.last_check_at, p.last_error, p.created_at, p.updated_at,
                                    array(select distinct pl.code from console_connection_configs cfg
                                          join consoles c on c.id=cfg.console_id and c.deleted_at is null
                                          join platforms pl on pl.id=c.platform_id
                                          where cfg.psn_account_id=p.id and pl.code in ('PS4', 'PS5')
                                          order by pl.code) platforms
                             from psn_accounts p left join console_agents a on a.id=p.agent_id
                             order by a.name, p.label''')
        return jsonable(rows)


@router.post('', status_code=201)
def create_account(body: NewAccount, p: Principal = Depends(ADMIN)):
    label = body.label.strip()
    if len(label) < 2:
        raise unprocessable('invalid_label', 'Informe um rótulo com pelo menos dois caracteres.')
    with tx() as conn:
        _agent(conn, body.agent_id)
        if one(conn, 'select 1 from psn_accounts where agent_id=%s and lower(label)=lower(%s)',
               (body.agent_id, label)):
            raise conflict('label_taken', 'Já existe uma conta PSN com esse rótulo neste agente.')
        row = insert(conn, 'psn_accounts', {'label': label, 'agent_id': body.agent_id,
                                           'created_by': p.user_id})
        audit_event(conn, 'psn.account_created', 'psn_accounts', row['id'])
        return jsonable(row)


@router.patch('/{account_id}')
def change_account(account_id: uuid.UUID, body: ChangeAccount, p: Principal = Depends(ADMIN)):
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    if 'status' in values and values['status'] not in ('disabled', 'pending'):
        raise unprocessable('invalid_status', 'Somente desativar ou redefinir para pendente é permitido manualmente.')
    if 'label' in values:
        values['label'] = values['label'].strip()
        if len(values['label']) < 2:
            raise unprocessable('invalid_label', 'Informe um rótulo com pelo menos dois caracteres.')
    with tx() as conn:
        row = _account(conn, account_id, lock=True)
        if 'label' in values and values['label'] != row['label']:
            if one(conn, 'select 1 from psn_accounts where agent_id=%s and lower(label)=lower(%s) and id<>%s',
                   (row['agent_id'], values['label'], account_id)):
                raise conflict('label_taken', 'Já existe uma conta PSN com esse rótulo neste agente.')
        if row['agent_id'] is not None and values.get('status') == 'disabled':
            _call_agent(conn, row, '/disable')
        elif row['agent_id'] is not None and values.get('status') == 'pending':
            _call_agent(conn, row, '/enable')
        values['updated_at'] = datetime.now(timezone.utc)
        updated = update(conn, 'psn_accounts', account_id, values)
        audit_event(conn, 'psn.account_changed', 'psn_accounts', account_id,
                    details={'fields': sorted(k for k in values if k != 'updated_at')})
        return jsonable(updated)


@router.delete('/{account_id}')
def remove_account(account_id: uuid.UUID, body: DeleteIn, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        row = _account(conn, account_id, lock=True)
        used = all_(conn, '''select c.code from console_connection_configs cfg
                             join consoles c on c.id=cfg.console_id
                             where cfg.psn_account_id=%s and c.deleted_at is null order by c.code''', (account_id,))
        if used:
            codes = ', '.join(console['code'] for console in used)
            raise conflict('account_in_use',
                           f'Abra Consoles e conexão e use Desvincular conta PSN nos consoles vinculados ({codes}) antes de excluir a conta.')
        clear_deleted_console_bindings(conn, account_id)
        if row['agent_id'] is not None:
            _call_agent(conn, row, '', method='DELETE')
        audit_event(conn, 'psn.account_deleted', 'psn_accounts', account_id, reason=body.reason)
        conn.execute('delete from psn_accounts where id=%s', (account_id,))
    return {'ok': True}


def clear_deleted_console_bindings(conn, account_id):
    # O método Remote Play pela internet exige PSN mesmo em um cadastro já excluído.
    conn.execute('''update console_connection_configs cfg
                    set psn_account_id=null, psn_device_uid=null,
                        method='unconfigured', connection_status='unconfigured'
                    from consoles c
                    where cfg.console_id=c.id and c.deleted_at is not null and cfg.psn_account_id=%s''', (account_id,))


@router.post('/{account_id}/login/start')
def start_login(account_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    return start_account_login(account_id)


def _ready_account(account_id, owner_user_id, disabled_message):
    """Valida a conta e devolve (linha, agente) sem manter a transação aberta durante a chamada ao agente."""
    with tx() as conn:
        row = _account(conn, account_id, owner_user_id=owner_user_id)
        if row['status'] == 'disabled':
            raise conflict('account_disabled', disabled_message)
        return row, _agent_target(conn, row)


def _locked_account(conn, account_id, owner_user_id, disabled_message):
    """Relê com trava antes de gravar: a conta pode ter sido desativada/excluída durante a chamada ao agente."""
    row = _account(conn, account_id, lock=True, owner_user_id=owner_user_id)
    if row['status'] == 'disabled':
        raise conflict('account_disabled', disabled_message)
    return row


def start_account_login(account_id: uuid.UUID, owner_user_id: str | None = None):
    if (server := _server_login_account(account_id, owner_user_id, 'Ative a conta antes de iniciar o login.')):
        with tx() as conn:
            conn.execute('update psn_accounts set login_started_at=now() where id=%s', (server['id'],))
            audit_event(conn, 'psn.login_started', 'psn_accounts', account_id, details={'via': 'server'})
        return {'login_url': psn_oauth.login_url(),
                'message': 'Abra a página Sony, entre na conta e cole a URL final aqui em até 10 minutos.'}
    row, target = _ready_account(account_id, owner_user_id, 'Ative a conta antes de iniciar o login.')
    response = _send_agent(target, '/login/start', {'label': row['label']})
    with tx() as conn:
        _account(conn, account_id, owner_user_id=owner_user_id)
        audit_event(conn, 'psn.login_started', 'psn_accounts', account_id)
    return {'login_url': response['login_url'], 'message': response.get('message', '')}


def _server_login_account(account_id, owner_user_id, disabled_message):
    """O login do proprietário usa o servidor, independentemente do vínculo com o agente."""
    if owner_user_id is None:
        return None
    with tx() as conn:
        row = _account(conn, account_id, owner_user_id=owner_user_id)
        if row['status'] == 'disabled':
            raise conflict('account_disabled', disabled_message)
        return row


def _store_server_credentials(conn, account_id, credentials: dict, profile: dict):
    return update(conn, 'psn_accounts', account_id, {
        'credentials_enc': security.encrypt(json.dumps({**credentials, **profile})),
        'online_id': profile.get('online_id'), 'account_id': profile.get('account_id'), 'status': 'linked',
        'last_error': '', 'last_check_at': datetime.now(timezone.utc), 'login_started_at': None})


def push_server_credentials(account_id) -> bool:
    """Repassa ao cofre do agente o login Sony guardado no servidor e o apaga daqui.

    Chamado antes dos testes; falhas deixam o
    acesso cifrado no banco para nova tentativa."""
    with tx() as conn:
        row = one(conn, 'select * from psn_accounts where id=%s', (account_id,))
        if not row or row['agent_id'] is None or not row['credentials_enc']:
            return False
        target = _agent_target(conn, row)
        credentials = json.loads(security.decrypt(row['credentials_enc']))
    _send_agent(target, '/import/credentials', {'label': row['label'], **credentials})
    with tx() as conn:
        conn.execute('update psn_accounts set credentials_enc=null where id=%s and credentials_enc=%s',
                     (account_id, row['credentials_enc']))
        audit_event(conn, 'psn.credentials_pushed', 'psn_accounts', account_id, details={'agent_id': str(row['agent_id'])})
    return True


@router.post('/{account_id}/login/finish')
def finish_login(account_id: uuid.UUID, body: FinishLogin, p: Principal = Depends(ADMIN)):
    return finish_account_login(account_id, body)


def finish_account_login(account_id: uuid.UUID, body: FinishLogin, owner_user_id: str | None = None):
    message = 'Ative a conta antes de concluir o login.'
    if (server := _server_login_account(account_id, owner_user_id, message)):
        started = server['login_started_at']
        if started is None or (datetime.now(timezone.utc) - started).total_seconds() > 600:
            raise conflict('login_expired', 'Clique em "Fazer login Sony" de novo (prazo: 10 minutos).')
        credentials, profile = psn_oauth.login(body.redirect_url)
        with tx() as conn:
            _locked_account(conn, account_id, owner_user_id, message)
            updated = _store_server_credentials(conn, account_id, credentials, profile)
            audit_event(conn, 'psn.login_linked', 'psn_accounts', account_id, details={'via': 'server'})
        return jsonable(updated)
    row, target = _ready_account(account_id, owner_user_id, message)
    response = _send_agent(target, '/login/finish', {'label': row['label'], 'redirect_url': body.redirect_url})
    with tx() as conn:
        _locked_account(conn, account_id, owner_user_id, message)
        profile = response['account']
        updated = update(conn, 'psn_accounts', account_id, {'online_id': profile.get('online_id'),
                         'account_id': profile.get('account_id'), 'status': 'linked', 'credentials_enc': None,
                         'last_error': '', 'last_check_at': datetime.now(timezone.utc)})
        audit_event(conn, 'psn.login_linked', 'psn_accounts', account_id)
        return jsonable(updated)


@router.post('/{account_id}/test')
def test_account(account_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    return test_account_login(account_id)


def test_account_login(account_id: uuid.UUID, owner_user_id: str | None = None):
    message = 'Esta conta está desativada.'
    if (server := _server_login_account(account_id, owner_user_id, message)) and server['agent_id'] is None:
        if not server['credentials_enc']:
            return {'ok': False, 'message': 'Faça o login Sony desta conta primeiro.'}
        saved = json.loads(security.decrypt(server['credentials_enc']))
        try:
            credentials, profile = psn_oauth.refresh(saved.get('refresh_token') or '')
        except AppError as e:
            if e.code != 'psn_token_expired':
                raise
            with tx() as conn:
                _locked_account(conn, account_id, owner_user_id, message)
                update(conn, 'psn_accounts', account_id, {'status': 'expired', 'credentials_enc': None, 'last_error': e.message})
            return {'ok': False, 'message': e.message}
        with tx() as conn:
            _locked_account(conn, account_id, owner_user_id, message)
            _store_server_credentials(conn, account_id, credentials, profile)
            audit_event(conn, 'psn.token_validated', 'psn_accounts', account_id, details={'via': 'server'})
        return {'ok': True, 'message': 'Conta verificada na Sony.'}
    with tx() as conn:   # conta já no agente com acesso pendente de repasse
        pending = one(conn, 'select credentials_enc from psn_accounts where id=%s', (account_id,))
    if pending and pending['credentials_enc']:
        push_server_credentials(account_id)
    _, target = _ready_account(account_id, owner_user_id, message)
    try:
        response = _send_agent(target, '/test')
    except AppError as e:
        if e.code != 'psn_token_expired':
            raise
        with tx() as conn:
            _locked_account(conn, account_id, owner_user_id, message)
            update(conn, 'psn_accounts', account_id, {'status': 'expired', 'last_error': e.message})
            audit_event(conn, 'psn.token_expired', 'psn_accounts', account_id)
        return {'ok': False, 'message': e.message}
    with tx() as conn:
        _locked_account(conn, account_id, owner_user_id, message)
        profile = response['account']
        update(conn, 'psn_accounts', account_id, {'online_id': profile.get('online_id'),
               'account_id': profile.get('account_id'), 'status': 'linked', 'last_error': '',
               'last_check_at': datetime.now(timezone.utc)})
        audit_event(conn, 'psn.token_validated', 'psn_accounts', account_id)
        return {'ok': True, 'message': response.get('message', 'Conta verificada na Sony.')}


@router.get('/options')
def import_options(p: Principal = Depends(ADMIN)):
    return {'chiaki_import_enabled': settings.psn_chiaki_import_enabled}


@router.post('/{account_id}/import/chiaki')
def import_chiaki(account_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    if not settings.psn_chiaki_import_enabled:
        raise forbidden('A importação do Chiaki está desabilitada.', code='chiaki_import_disabled')
    with tx() as conn:
        row = _account(conn, account_id)
        response = _call_agent(conn, row, '/import/chiaki', {'label': row['label']})
        audit_event(conn, 'psn.chiaki_credentials_imported', 'psn_accounts', account_id)
        return {'ok': response.get('ok', False), 'message': response.get('message', '')}


@router.post('/{account_id}/devices')
def list_devices(account_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        row = _account(conn, account_id)
        # Consulta PS5 na PSN; NÃO garante conexão, vídeo, áudio ou holepunch.
        return _call_agent(conn, row, '/devices')


@router.post('/{account_id}/devices/ps4-lan')
def discover_ps4(account_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        row = _account(conn, account_id)
        return _call_agent(conn, row, '/devices/ps4-lan')


@router.post('/{account_id}/diagnose/ps4-psn')
def diagnose_ps4_psn(account_id: uuid.UUID, p: Principal = Depends(ADMIN)):
    with tx() as conn:
        row = _account(conn, account_id)
        if row['status'] != 'linked':
            raise conflict('account_not_linked', 'Vincule e valide a conta PSN antes de iniciar o diagnóstico.')
        return _call_agent(conn, row, '/diagnose/ps4-psn')

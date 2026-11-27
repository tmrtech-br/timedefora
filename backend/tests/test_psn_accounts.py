import uuid

import httpx

from app.core.db import insert, tx
from app.routers import psn_accounts
from conftest import Api, admin_api, login, make_user


def test_admin_manages_psn_metadata_and_agent_failures(monkeypatch):
    admin, _ = admin_api()
    client = login(make_user())
    base = '/admin/psn-accounts'
    assert Api().get(base).status_code == 401
    assert client.get(base).status_code == 403
    assert client.post(base, json={'label': 'teste', 'agent_id': str(uuid.uuid4())}).status_code == 403

    agent = admin.post('/admin/agents', json={
        'name': 'pc-psn', 'host_name': 'pc', 'endpoint_url': 'http://127.0.0.1:18765',
    })
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()['id']
    assert admin.post(base, json={'label': '   ', 'agent_id': agent_id}).status_code == 422
    created = admin.post(base, json={'label': '  Conta A  ', 'agent_id': agent_id})
    assert created.status_code == 201, created.text
    account = created.json()
    assert account['label'] == 'Conta A'
    assert admin.post(base, json={'label': 'conta a', 'agent_id': agent_id}).status_code == 409
    listed = admin.get(base).json()
    assert listed[0]['id'] == account['id']
    assert not {'access_token', 'refresh_token', 'outbound_token_enc'}.intersection(listed[0])
    path = f"{base}/{account['id']}"
    assert admin.patch(path, json={'label': '   '}).status_code == 422
    monkeypatch.setattr(psn_accounts.settings, 'psn_chiaki_import_enabled', False)
    assert admin.get(base + '/options').json() == {'chiaki_import_enabled': False}
    assert client.get(base + '/options').status_code == 403
    result = admin.post(path + '/import/chiaki')
    assert result.status_code == 403
    assert result.json()['code'] == 'chiaki_import_disabled'

    response = httpx.Response(200, json=[])
    real_client = httpx.Client

    def open_agent(**kwargs):
        return real_client(transport=httpx.MockTransport(lambda request: response), **kwargs)

    monkeypatch.setattr(psn_accounts.httpx, 'Client', open_agent)
    assert admin.post(path + '/test').status_code == 502
    response = httpx.Response(401, json={'code': 'psn_token_expired', 'message': 'Token expirado.'})
    assert admin.post(path + '/test').json()['ok'] is False
    assert admin.get(base).json()[0]['status'] == 'expired'
    response = httpx.Response(200, json={'ok': True})
    monkeypatch.setattr(psn_accounts.settings, 'psn_chiaki_import_enabled', True)
    assert admin.get(base + '/options').json() == {'chiaki_import_enabled': True}
    assert admin.post(path + '/import/chiaki').json()['ok'] is True
    assert admin.patch(path, json={'status': 'disabled'}).status_code == 200
    assert admin.post(path + '/login/finish', json={'redirect_url': 'https://example.test/redirect'}).status_code == 409
    assert admin.delete(path).status_code == 200
    assert admin.get(base).json() == []


def test_psn_metadata_has_row_level_security():
    with tx() as conn:
        enabled, policies = conn.execute("""
            select c.relrowsecurity, count(p.polname)
            from pg_class c left join pg_policy p on p.polrelid=c.oid
            where c.oid='public.psn_accounts'::regclass
            group by c.relrowsecurity
        """).fetchone().values()
    assert enabled
    assert policies == 0


def test_native_internet_ps4_uses_linked_account_without_device_uid(monkeypatch):
    admin, _ = admin_api()
    with tx() as conn:
        agent = insert(conn, 'console_agents', {'name': 'pc-psn', 'host_name': 'pc', 'is_simulated': False})
        account = insert(conn, 'psn_accounts', {'agent_id': agent['id'], 'label': 'Conta PSN', 'status': 'linked'})

    def connection_url(code, platform):
        result = admin.post('/admin/consoles', json={'code': code, 'name': code, 'platform_code': platform})
        assert result.status_code == 201, result.text
        return f"/admin/consoles/{result.json()['id']}/connection"

    config = {'method': 'remote_play_native', 'network_route': 'internet_psn', 'agent_id': str(agent['id'])}
    ps4_url = connection_url('PS4-01', 'PS4')
    missing = admin.put(ps4_url, json=config)
    assert missing.status_code == 422
    assert 'psn_account_id' in missing.json()['fields']

    config['psn_account_id'] = str(account['id'])
    result = admin.put(ps4_url, json=config)
    assert result.status_code == 200, result.text
    assert result.json()['connection']['psn_device_uid'] is None
    assert result.json()['connection']['psn_account_id'] == str(account['id'])
    assert admin.get('/admin/psn-accounts').json()[0]['platforms'] == ['PS4']
    result = admin.put(ps4_url, json={**config, 'psn_device_uid': 'main_ps4'})
    assert result.status_code == 200, result.text
    assert result.json()['connection']['psn_device_uid'] is None

    duplicate = admin.put(connection_url('PS4-02', 'PS4'), json=config)
    assert duplicate.status_code == 422
    assert 'psn_account_id' in duplicate.json()['fields']
    ps5_url = connection_url('PS5-01', 'PS5')
    # O agente só negocia PS4 pela PSN: o cadastro recusa PS5 nessa rota (com ou sem DUID).
    refused = admin.put(ps5_url, json={**config, 'psn_device_uid': 'ab' * 32})
    assert refused.status_code == 422
    assert 'network_route' in refused.json()['fields']
    blocked = admin.delete(f"/admin/psn-accounts/{account['id']}")
    assert blocked.status_code == 409
    assert 'PS4-01' in blocked.json()['detail']

    result = admin.put(ps4_url, json={
        'method': 'unconfigured', 'agent_id': str(agent['id']), 'reason': 'Conta PSN desvinculada no painel',
    })
    assert result.status_code == 200, result.text
    assert result.json()['connection']['psn_account_id'] is None
    assert result.json()['connection']['agent_id'] == str(agent['id'])
    ps4_replacement = connection_url('PS4-03', 'PS4')
    assert admin.put(ps4_replacement, json=config).status_code == 200

    for path in (ps4_replacement, ps5_url):
        assert admin.delete(path.removesuffix('/connection')).status_code == 200
    with tx() as conn:
        linked = conn.execute('select 1 from console_connection_configs where psn_account_id=%s', (account['id'],))
        assert linked.fetchone() is None
        # Simulate a console deleted before its PSN binding was cleared.
        conn.execute('''update console_connection_configs set psn_account_id=%s, psn_device_uid=%s
                        where console_id=%s''', (account['id'], 'ab' * 32, ps5_url.split('/')[-2]))
    monkeypatch.setattr(psn_accounts, '_call_agent', lambda *args, **kwargs: {'ok': True})
    assert admin.delete(f"/admin/psn-accounts/{account['id']}").status_code == 200
    assert admin.get('/admin/psn-accounts').json() == []

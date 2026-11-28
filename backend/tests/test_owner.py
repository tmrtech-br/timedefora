from uuid import uuid4

from app.core.db import tx
from conftest import admin_api, login, make_user


def test_owner_invitation_acceptance_and_inventory(world):
    admin, _ = admin_api()
    user = make_user('locador')
    api = login(user)
    assert api.get('/owner/terms').status_code == 403
    assert admin.post(f"/admin/users/{user['id']}/roles", json={'role': 'owner', 'grant': True}).status_code == 200
    assert api.get('/admin/overview').status_code == 403
    assert api.get('/owner/consoles').status_code == 403
    policy = api.get('/owner/terms').json()
    assert policy['accepted_at'] is None
    assert api.post('/owner/enrollment', json={'policy_version_id': policy['id'], 'accepted': False}).status_code == 422
    assert api.post('/owner/enrollment', json={'policy_version_id': str(uuid4()), 'accepted': True}).status_code == 409

    body = {'policy_version_id': policy['id'], 'accepted': True}
    assert api.post('/owner/enrollment', json=body).status_code == 200
    assert api.post('/owner/enrollment', json=body).status_code == 200
    assert api.get('/owner/consoles').json() == []
    with tx() as conn:
        conn.execute('update consoles set owner_user_id=%s where id=%s', (user['id'], world['console']['id']))
        assert conn.execute("select count(*) n from audit_logs where action='owner.terms_accepted'").fetchone()['n'] == 1
    assert [row['id'] for row in api.get('/owner/consoles').json()] == [str(world['console']['id'])]
    other = login(make_user('outra_locadora', roles=('owner',)))
    assert other.post('/owner/enrollment', json=body).status_code == 200
    assert other.get('/owner/consoles').json() == []
    assert admin.post(f"/admin/users/{user['id']}/roles", json={'role': 'operator', 'grant': True}).status_code == 409


def test_diagnostics_batch(world):
    api, _ = admin_api()
    path = f"/admin/consoles/{world['console']['id']}/diagnostics/run-all"
    assert login(make_user('locador', roles=('owner',))).post(path).status_code == 403
    response = api.post(path)
    assert response.status_code == 200, response.text
    results = {item['test_type']: item for item in response.json()['results']}
    assert set(results) == {'discover', 'pair', 'connection', 'video_audio', 'controls', 'heartbeat', 'latency'}
    assert results['connection']['result'] == 'passed'
    assert results['connection']['duration_ms'] >= 0
    assert results['latency']['result'] == 'not_available'


def _owner(username='dono_valida'):
    from conftest import login, make_user
    user = make_user(username, roles=('client', 'owner'))
    api = login(user)
    policy = api.get('/owner/terms').json()
    assert api.post('/owner/enrollment', json={'policy_version_id': policy['id'], 'accepted': True}).status_code == 200
    return api, user


def test_fluxo_de_validacao_do_console_do_proprietario(world, freeze):
    from conftest import at
    freeze(at(2, 7, 0))
    admin, _ = admin_api('chefe_valida')
    api, user = _owner()
    c = api.post('/owner/consoles', json={'code': 'DONO-01', 'name': 'PS5 do dono', 'platform_code': 'PS5'})
    assert c.status_code == 201, c.text
    cid = c.json()['id']
    # incompleto: não envia
    r = api.post(f'/owner/consoles/{cid}/submit')
    assert r.status_code == 422 and r.json()['code'] == 'incomplete'
    assert api.put(f'/owner/consoles/{cid}/availability', json={'min_minutes': 10, 'max_minutes': 60, 'rate_unit': 'minute', 'rate_cents': 100}).status_code == 200
    w = api.post(f'/owner/consoles/{cid}/games', json={'game_id': str(world['game']['id']), 'starts_at': at(3, 8).isoformat(), 'ends_at': at(3, 12).isoformat()})
    assert w.status_code == 201, w.text
    assert api.get(f'/owner/consoles/{cid}/review').json()['missing'] == []
    # sem aprovação não publica
    assert api.post(f'/owner/consoles/{cid}/publish').status_code == 409
    assert api.post(f'/owner/consoles/{cid}/submit').status_code == 200
    # em análise: edição bloqueada
    assert api.put(f'/owner/consoles/{cid}/availability', json={'min_minutes': 10, 'max_minutes': 60, 'rate_unit': 'minute', 'rate_cents': 200}).status_code == 409
    queue = admin.get('/admin/owner-reviews').json()
    assert [q['id'] for q in queue] == [cid] and queue[0]['status'] == 'submitted'
    # pedir ajustes exige observação
    assert admin.post(f'/admin/owner-reviews/{cid}/reject', json={'notes': ''}).status_code == 422
    assert admin.post(f'/admin/owner-reviews/{cid}/reject', json={'notes': 'Ajuste as artes do jogo.'}).json()['status'] == 'rejected'
    assert api.get(f'/owner/consoles/{cid}/review').json()['status'] == 'rejected'
    assert api.post(f'/owner/consoles/{cid}/submit').status_code == 200
    from app.core import security
    from app.core.db import insert
    with tx() as conn:   # agente real (não simulado) com endereço e credencial, como em produção
        agent = str(insert(conn, 'console_agents', {'name': 'agente-dono', 'host_name': 'pc', 'is_simulated': False, 'status': 'online',
                                                    'endpoint_url': 'https://agente.exemplo', 'outbound_token_enc': security.encrypt('tok')})['id'])
    assert admin.post(f'/admin/owner-reviews/{cid}/approve', json={'agent_id': agent, 'notes': 'ok'}).status_code == 200
    st = api.get(f'/owner/consoles/{cid}/review').json()
    assert st['status'] == 'approved' and st['approved_at'] and st['agent_linked'] is True
    # edição de console aprovado: fica pendente (tarifa atual continua)
    assert api.put(f'/owner/consoles/{cid}/availability', json={'min_minutes': 10, 'max_minutes': 90, 'rate_unit': 'minute', 'rate_cents': 150}).json()['pending'] is True
    assert api.get(f'/owner/consoles/{cid}/availability').json()['rate_cents'] == 100
    w2 = api.post(f'/owner/consoles/{cid}/games', json={'game_id': str(world['game']['id']), 'starts_at': at(4, 8).isoformat(), 'ends_at': at(4, 12).isoformat()})
    assert w2.status_code == 201 and w2.json()['status'] == 'pending_review'
    st = api.get(f'/owner/consoles/{cid}/review').json()
    assert st['status'] == 'changes_pending' and st['pending']['rate']['rate_cents'] == 150 and len(st['pending_windows']) == 1
    assert api.post(f'/owner/consoles/{cid}/submit').status_code == 200
    assert admin.post(f'/admin/owner-reviews/{cid}/approve', json={'notes': ''}).status_code == 200
    assert api.get(f'/owner/consoles/{cid}/availability').json()['rate_cents'] == 150
    with tx() as conn:
        assert conn.execute("select count(*) n from console_game_assignments where console_id=%s and status='active'", (cid,)).fetchone()['n'] == 2
    assert api.get(f'/owner/consoles/{cid}/history').status_code == 200

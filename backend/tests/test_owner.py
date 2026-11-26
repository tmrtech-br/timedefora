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

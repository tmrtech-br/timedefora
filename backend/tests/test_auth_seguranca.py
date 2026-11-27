"""Cadastro, verificação por código, login, recuperação, troca de e-mail, MFA, RBAC, CSRF, IDOR, rate limit, auditoria."""
import re
from datetime import timedelta

import pyotp

from app.core import security, timeutil
from app.core.db import get_pool, insert, one, tx
from conftest import Api, admin_api, at, last_email, login, make_user, pay, reserve

GOOD = {'full_name': 'Maria Silva', 'username': 'mariasilva', 'email': 'maria@teste.com', 'password': 'Jogar2026agora',
        'password_confirm': 'Jogar2026agora', 'accept_terms': True, 'accept_privacy': True}


def code_from_mail(to):
    m = last_email(to)
    return re.search(r'\b(\d{6})\b', m['body_text']).group(1)


def test_cadastro_validacoes():
    api = Api()
    r = api.post('/auth/register', json={**GOOD, 'password_confirm': 'outra', 'accept_terms': False})
    assert r.status_code == 422
    assert set(r.json()['fields']) >= {'password_confirm', 'accept_terms'}
    r = api.post('/auth/register', json={**GOOD, 'password': 'curta', 'password_confirm': 'curta'})
    assert r.status_code == 422 and 'password' in r.json()['fields']


def test_nome_publico_recusa_ofensas_no_perfil_e_no_cadastro():
    u = make_user('jogador_teste')
    api = login(u)
    for username in ('CaRaLhO_22', 'v.1.a.d.0', 'macaco_preto', 'fora.imigrantes'):
        r = api.patch('/me', json={'username': username})
        assert r.status_code == 422
        assert 'conteúdo discriminatório' in r.json()['fields']['username']
    assert api.get('/me').json()['username'] == u['username']
    assert api.patch('/me', json={'username': 'Enviado_2026'}).status_code == 200
    assert api.patch('/me', json={'username': 'JogadorGay'}).status_code == 200
    r = Api().post('/auth/register', json={**GOOD, 'username': 'p0rr4'})
    assert r.status_code == 422
    assert 'conteúdo discriminatório' in r.json()['fields']['username']


def test_cadastro_codigo_correto_ativa_conta_e_guarda_hash(freeze):
    freeze(at(1, 10))
    api = Api()
    r = api.post('/auth/register', json=GOOD)
    assert r.status_code == 201, r.text
    assert api.get('/me').json()['email_verified'] is False
    code = code_from_mail('maria@teste.com')
    with tx() as conn:
        row = one(conn, 'select code_hash from email_verification_codes')
        acc = one(conn, 'select count(*) n from policy_acceptances')['n']
    assert code not in row['code_hash'] and len(row['code_hash']) == 64
    assert acc == 2  # termos + privacidade
    assert api.post('/auth/verify-email', json={'code': code}).json()['verified']
    me = api.get('/me').json()
    assert me['email_verified'] and me['status'] == 'active'


def test_codigo_incorreto_limite_de_tentativas_e_expiracao(freeze):
    freeze(at(1, 10))
    api = Api()
    api.post('/auth/register', json=GOOD)
    good = code_from_mail('maria@teste.com')
    wrong = '000000' if good != '000000' else '111111'
    for left in (4, 3, 2, 1):
        r = api.post('/auth/verify-email', json={'code': wrong})
        assert r.status_code == 400 and f'restantes: {left}' in r.json()['detail']
    r = api.post('/auth/verify-email', json={'code': wrong})
    assert r.status_code == 429
    assert api.post('/auth/verify-email', json={'code': good}).status_code == 400   # código invalidado
    # reenvio respeita cooldown de 60s
    assert api.post('/auth/resend-code').status_code == 200
    assert api.post('/auth/resend-code').status_code == 429
    new = code_from_mail('maria@teste.com')
    freeze(at(1, 10, 11))  # > 10 minutos
    r = api.post('/auth/verify-email', json={'code': new})
    assert r.status_code == 400 and r.json()['code'] == 'code_expired'


def test_login_generico_bloqueio_e_rate_limit(freeze):
    freeze(at(1, 10))
    u = make_user('fulano')
    api = Api()
    r = api.post('/auth/login', json={'email': 'naoexiste@x.com', 'password': 'x'})
    assert r.status_code == 401 and r.json()['detail'] == 'E-mail ou senha incorretos.'
    for _ in range(8):
        api.post('/auth/login', json={'email': u['email'], 'password': 'errada'})
    r = api.post('/auth/login', json={'email': u['email'], 'password': u['password']})
    assert r.status_code == 429  # bloqueio temporário OU rate limit por e-mail


def test_recuperacao_de_senha_revoga_sessoes(freeze):
    freeze(at(1, 10))
    u = make_user('fulano')
    s1 = login(u)
    api = Api()
    assert api.post('/auth/password/forgot', json={'email': u['email']}).status_code == 200
    assert api.post('/auth/password/forgot', json={'email': 'ninguem@x.com'}).status_code == 200   # mesma resposta
    token = re.search(r'token=([\w-]+)', last_email(u['email'])['body_text']).group(1)
    r = api.post('/auth/password/reset', json={'token': token, 'password': 'NovaSenha2026', 'password_confirm': 'NovaSenha2026'})
    assert r.status_code == 200
    assert s1.get('/me').status_code == 401                      # sessão antiga revogada
    assert api.post('/auth/password/reset', json={'token': token, 'password': 'OutraSenha2026', 'password_confirm': 'OutraSenha2026'}).status_code == 400
    login({**u, 'password': 'NovaSenha2026'})


def test_perfil_nao_permite_troca_de_email(freeze):
    freeze(at(1, 10))
    u = make_user('fulano')
    api = login(u)
    assert api.post('/me/email', json={'new_email': 'novo@teste.com', 'password': u['password']}).status_code == 404
    assert api.post('/me/email/confirm', json={'code': '000000'}).status_code == 404
    assert api.post('/me/email/resend').status_code == 404
    assert api.get('/me').json()['email'] == u['email']


def test_alterar_senha_valida_os_campos_e_revoga_as_outras_sessoes(freeze):
    freeze(at(1, 10))
    user = make_user('senha_perfil')
    api, other_session = login(user), login(user)
    change = {'current_password': user['password'], 'new_password': 'NovaChave2026', 'new_password_confirm': 'NovaChave2026'}
    wrong = api.post('/me/password', json={**change, 'current_password': 'incorreta'})
    assert wrong.status_code == 400 and wrong.json()['code'] == 'wrong_password'
    for fields, expected in (
        ({'new_password_confirm': 'diferente'}, 'new_password_confirm'),
        ({'new_password': 'curta', 'new_password_confirm': 'curta'}, 'new_password'),
        ({'new_password': user['password'], 'new_password_confirm': user['password']}, 'new_password'),
    ):
        response = api.post('/me/password', json={**change, **fields})
        assert response.status_code == 422 and expected in response.json()['fields']
    assert api.post('/me/password', json=change).status_code == 200
    assert api.get('/me').status_code == 200
    assert other_session.get('/me').status_code == 401
    login({**user, 'password': change['new_password']})


def test_csrf_obrigatorio_e_origem(freeze):
    freeze(at(1, 10))
    api = login(make_user('fulano'))
    r = api.c.patch('/me', json={'full_name': 'Hacker Teste'})        # sem header CSRF
    assert r.status_code == 403 and r.json()['code'] == 'csrf'
    r = api.patch('/me', json={'full_name': 'Nome Novo'}, headers={'Origin': 'https://evil.example'})
    assert r.status_code == 403
    assert api.patch('/me', json={'full_name': 'Nome Novo'}).status_code == 200


def test_rbac_admin_exige_papel_e_mfa(freeze):
    freeze(at(1, 10))
    cli = login(make_user('cliente'))
    assert cli.get('/admin/overview').status_code == 403
    u = make_user('gerente', roles=('client', 'admin'))
    adm = login(u)
    r = adm.get('/admin/overview')
    assert r.status_code == 403 and r.json()['code'] == 'mfa_setup_required'
    secret = adm.post('/me/mfa/setup').json()['secret']
    adm.post('/me/mfa/confirm', json={'code': pyotp.TOTP(secret).at(timeutil.now())})
    assert adm.get('/admin/overview').status_code == 200
    # novo login exige o segundo fator
    adm2 = login(u)
    assert adm2.get('/admin/overview').json()['code'] == 'mfa_required'
    freeze(at(1, 10, 1))
    assert adm2.post('/auth/mfa/verify', json={'code': pyotp.TOTP(secret).at(timeutil.now())}).status_code == 200
    assert adm2.get('/admin/overview').status_code == 200
    # código reutilizado é recusado (antirreplay)
    adm3 = login(u)
    assert adm3.post('/auth/mfa/verify', json={'code': pyotp.TOTP(secret).at(timeutil.now())}).status_code == 400
    # operador não acessa finanças; admin não altera papéis
    op, _ = admin_api('operador1', role='operator')
    assert op.get('/admin/payments').status_code == 403
    assert op.get('/admin/queues').status_code == 200
    assert adm2.post(f"/admin/users/{u['id']}/roles", json={'role': 'superadmin', 'grant': True}).status_code == 403


def test_idor_reserva_de_outro_usuario(world, freeze):
    freeze(at(2, 8))
    a, b = login(make_user('alice')), login(make_user('bruno'))
    r = reserve(a, world, 10).json()
    assert b.get(f"/reservations/{r['id']}").status_code == 404
    assert b.post(f"/reservations/{r['id']}/checkout", json={'method': 'pix'}).status_code == 404
    assert b.post(f"/reservations/{r['id']}/cancel", json={'reason': 'tentativa'}).status_code == 404
    pay(a, r['id'])
    pid = a.get(f"/reservations/{r['id']}").json()['payment']['id']
    assert b.get(f'/payments/{pid}').status_code == 404


def test_lgpd_exportacao_sem_segredos_e_solicitacao(freeze):
    freeze(at(1, 10))
    api = login(make_user('fulano'))
    data = api.get('/me/export').json()
    flat = str(data)
    assert 'argon2' not in flat and 'password_hash' not in flat
    assert api.post('/me/data-requests', json={'request_type': 'deletion', 'details': 'Quero excluir'}).status_code == 201
    assert api.post('/me/data-requests', json={'request_type': 'deletion'}).status_code == 409


def test_auditoria_registra_insert_update_delete_com_ator_e_mascara(freeze):
    freeze(at(1, 10))
    u = make_user('fulano')
    api = login(u)
    api.patch('/me', json={'full_name': 'Fulano Alterado'})
    api.put('/me/favorites/00000000-0000-0000-0000-000000000000')  # inexistente → 404, sem log
    with tx() as conn:
        rows = conn.execute("select action, changed_fields, actor_user_id, new_data from audit_logs where table_name='users' order by id").fetchall()
    assert rows[0]['action'] == 'INSERT' and rows[0]['new_data']['password_hash'] == '[REDACTED]'
    upd = [r for r in rows if r['action'] == 'UPDATE' and r['changed_fields'] == ['full_name']]
    assert upd and str(upd[0]['actor_user_id']) == str(u['id'])
    with tx() as conn:
        conn.execute("delete from notification_preferences where user_id=%s", (u['id'],))
        assert one(conn, "select count(*) n from audit_logs where table_name='notification_preferences' and action='DELETE'")['n'] == 1
    import psycopg
    import pytest
    with pytest.raises(psycopg.errors.RaiseException):
        with get_pool().connection() as c:
            c.execute('delete from audit_logs')


def test_cliente_com_mfa_legado_confirma_email_sem_totp():
    user = make_user(username='cliente_legado', verified=False)
    with tx() as conn:
        insert(conn, 'mfa_factors', {'user_id': user['id'], 'totp_secret_enc': security.encrypt(pyotp.random_base32()),
                                     'confirmed_at': timeutil.now()})
    api = Api()
    response = api.post('/auth/login', json={'email': user['email'], 'password': user['password']})
    assert response.status_code == 200
    assert response.json() == {'mfa_required': False, 'email_verified': False}
    assert api.post('/me/mfa/setup').status_code == 403
    assert api.post('/auth/mfa/verify', json={'code': '123456'}).status_code == 403

"""Regras de conta: cadastro, verificação de e-mail, login, recuperação, troca de e-mail, MFA, sessões."""
import re
from datetime import timedelta

import pyotp

from ..config import settings
from ..core import security, timeutil
from ..core.db import audit_event, get_pool, insert, tx
from ..core.errors import AppError, bad_request, conflict, unprocessable
from . import notifications

CODE_TTL = timedelta(minutes=10)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 5
MAX_FAILED_LOGINS = 8
LOCK_TIME = timedelta(minutes=15)
USERNAME_RE = re.compile(r'^[A-Za-z0-9_.]{3,24}$')
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$')


def _norm_email(e: str) -> str:
    e = (e or '').strip().lower()
    if not EMAIL_RE.match(e) or len(e) > 254:
        raise unprocessable('invalid_email', 'Informe um e-mail válido.')
    return e


def create_session(conn, user_id: str, ip: str, ua: str, mfa_verified: bool = False) -> str:
    token = security.new_token()
    insert(conn, 'auth_sessions', {
        'user_id': user_id, 'token_hash': security.sha256(token), 'ip': ip, 'user_agent': (ua or '')[:300],
        'expires_at': timeutil.now() + timedelta(days=settings.session_days),
        'mfa_verified_at': timeutil.now() if mfa_verified else None})
    return token


def _issue_code(conn, user_id: str, purpose: str, target_email: str) -> None:
    n = timeutil.now()
    last = conn.execute(
        """select * from email_verification_codes where user_id=%s and purpose=%s
           and consumed_at is null and invalidated_at is null order by created_at desc limit 1""",
        (user_id, purpose)).fetchone()
    sent_last_hour = conn.execute(
        'select coalesce(sum(send_count),0) n from email_verification_codes where user_id=%s and created_at > %s',
        (user_id, n - timedelta(hours=1))).fetchone()['n']
    if last and n - last['last_sent_at'] < RESEND_COOLDOWN:
        wait = int((RESEND_COOLDOWN - (n - last['last_sent_at'])).total_seconds()) + 1
        raise AppError(429, 'resend_cooldown', f'Aguarde {wait}s para reenviar o código.', {'retry_after': wait})
    if sent_last_hour >= MAX_SENDS_PER_HOUR:
        raise AppError(429, 'too_many_codes', 'Limite de envios atingido. Tente novamente em 1 hora.', {'retry_after': 3600})
    conn.execute("""update email_verification_codes set invalidated_at=%s where user_id=%s and purpose=%s
                    and consumed_at is null and invalidated_at is null""", (n, user_id, purpose))
    code = security.new_numeric_code(6)
    row = insert(conn, 'email_verification_codes', {
        'user_id': user_id, 'purpose': purpose, 'target_email': target_email,
        'code_hash': security.hmac_hex('email-code', user_id, purpose, code), 'expires_at': n + CODE_TTL,
        'last_sent_at': n, 'created_at': n})
    notifications.notify(conn, user_id, 'verify_email' if purpose == 'signup' else 'email_change',
                         {'codigo': code, 'validade': '10 minutos'}, dedupe=f"code:{row['id']}",
                         in_app=False, email_to=target_email)


def register(data: dict, ip: str, ua: str) -> tuple[dict, str]:
    full_name = (data.get('full_name') or '').strip()
    username = (data.get('username') or '').strip()
    email = _norm_email(data.get('email'))
    pw, pw2 = data.get('password') or '', data.get('password_confirm') or ''
    errors = {}
    if not 3 <= len(full_name) <= 120: errors['full_name'] = 'Informe seu nome completo.'
    if not USERNAME_RE.match(username): errors['username'] = 'Use 3 a 24 letras, números, "_" ou ".".'
    if pw != pw2: errors['password_confirm'] = 'As senhas não conferem.'
    probs = security.password_problems(pw, email, username)
    if probs: errors['password'] = ' '.join(probs)
    if not data.get('accept_terms') or not data.get('accept_privacy'):
        errors['accept_terms'] = 'É necessário aceitar os termos de uso e a política de privacidade.'
    if errors:
        raise unprocessable('validation_error', 'Verifique os campos do formulário.', fields=errors)
    security.rate_limit(f'register:{ip}', 10, 3600)
    pw_hash = security.hash_password(pw)
    with tx() as conn:
        if conn.execute('select 1 from users where lower(username)=lower(%s)', (username,)).fetchone():
            raise conflict('username_taken', 'Este nome de usuário já está em uso.', fields={'username': 'Indisponível.'})
        if conn.execute('select 1 from users where lower(email)=%s and deleted_at is null', (email,)).fetchone():
            # Mensagem genérica para não confirmar existência de contas por e-mail
            raise conflict('email_unavailable', 'Não foi possível cadastrar com este e-mail. Tente entrar ou recuperar a senha.')
        user = insert(conn, 'users', {'full_name': full_name, 'username': username, 'email': email,
                                      'password_hash': pw_hash, 'status': 'pending_verification',
                                      'marketing_opt_in': bool(data.get('marketing_opt_in'))})
        conn.execute("insert into role_assignments(user_id, role_id) select %s, id from roles where code='client'", (user['id'],))
        conn.execute('insert into notification_preferences(user_id, email_marketing) values (%s,%s)',
                     (user['id'], bool(data.get('marketing_opt_in'))))
        for kind in ('terms', 'privacy'):
            conn.execute("""insert into policy_acceptances(user_id, policy_id, context, ip)
                            select %s, id, 'signup', %s from policy_documents where kind=%s and is_current""",
                         (user['id'], ip, kind))
        _issue_code(conn, str(user['id']), 'signup', email)
        token = create_session(conn, str(user['id']), ip, ua)
    notifications.process_deliveries(limit=5)
    return user, token


def verify_code(user_id: str, purpose: str, code: str) -> dict:
    code = (code or '').strip()
    n = timeutil.now()
    error: AppError | None = None
    with tx(actor_id=user_id) as conn:
        row = conn.execute(
            """select * from email_verification_codes where user_id=%s and purpose=%s and consumed_at is null
               and invalidated_at is null order by created_at desc limit 1 for update""", (user_id, purpose)).fetchone()
        if not row:
            raise bad_request('no_code', 'Nenhum código ativo. Solicite um novo código.')
        if row['expires_at'] <= n:
            conn.execute('update email_verification_codes set invalidated_at=%s where id=%s', (n, row['id']))
            error = bad_request('code_expired', 'Código expirado. Solicite um novo código.')
        elif row['attempts'] >= row['max_attempts']:
            conn.execute('update email_verification_codes set invalidated_at=%s where id=%s', (n, row['id']))
            error = AppError(429, 'too_many_attempts', 'Muitas tentativas. Solicite um novo código.')
        elif not security.consteq(row['code_hash'], security.hmac_hex('email-code', user_id, purpose, code)):
            attempts = row['attempts'] + 1
            conn.execute('update email_verification_codes set attempts=%s where id=%s', (attempts, row['id']))
            left = row['max_attempts'] - attempts
            error = bad_request('invalid_code', f'Código incorreto. Tentativas restantes: {left}.') if left > 0 else \
                AppError(429, 'too_many_attempts', 'Muitas tentativas. Solicite um novo código.')
            if left <= 0:
                conn.execute('update email_verification_codes set invalidated_at=%s where id=%s', (n, row['id']))
        else:
            conn.execute('update email_verification_codes set consumed_at=%s where id=%s', (n, row['id']))
            if purpose == 'signup':
                conn.execute("update users set email_verified_at=%s, status='active' where id=%s and status='pending_verification'",
                             (n, user_id))
                conn.execute('update users set email_verified_at=coalesce(email_verified_at,%s) where id=%s', (n, user_id))
            else:
                taken = conn.execute('select 1 from users where lower(email)=lower(%s) and id<>%s and deleted_at is null',
                                     (row['target_email'], user_id)).fetchone()
                if taken:
                    raise conflict('email_unavailable', 'Este e-mail não está disponível.')
                old = conn.execute('select email from users where id=%s', (user_id,)).fetchone()['email']
                conn.execute('update users set email=%s, email_verified_at=%s where id=%s', (row['target_email'], n, user_id))
                notifications.notify(conn, user_id, 'security_email_changed', {'email_novo': row['target_email']},
                                     dedupe=f"emailchg:{row['id']}", template='security_alert', email_to=old)
            return {'verified': True}
    # Commit das tentativas acontece antes de sinalizar o erro.
    raise error


def resend_code(user_id: str, purpose: str = 'signup') -> None:
    with tx(actor_id=user_id) as conn:
        u = conn.execute('select email, status from users where id=%s', (user_id,)).fetchone()
        if purpose == 'signup' and u['status'] != 'pending_verification':
            raise bad_request('already_verified', 'Seu e-mail já está confirmado.')
        target = u['email']
        if purpose == 'email_change':
            last = conn.execute("""select target_email from email_verification_codes where user_id=%s and purpose='email_change'
                                   order by created_at desc limit 1""", (user_id,)).fetchone()
            if not last:
                raise bad_request('no_code', 'Nenhuma troca de e-mail em andamento.')
            target = last['target_email']
        _issue_code(conn, user_id, purpose, target)
    notifications.process_deliveries(limit=5)


def login(email: str, password: str, ip: str, ua: str) -> tuple[dict, str, bool]:
    security.rate_limit(f'login-ip:{ip}', 30, 900)
    email_n = (email or '').strip().lower()
    security.rate_limit(f'login-email:{email_n}', 10, 900)
    n = timeutil.now()
    generic = AppError(401, 'invalid_credentials', 'E-mail ou senha incorretos.')
    with get_pool().connection() as conn:
        user = conn.execute('select * from users where lower(email)=%s and deleted_at is null', (email_n,)).fetchone()
    if not user:
        security.verify_password(None, password)
        raise generic
    if user['locked_until'] and user['locked_until'] > n:
        raise AppError(429, 'account_locked', 'Conta temporariamente bloqueada por tentativas inválidas. Tente mais tarde.')
    ok = security.verify_password(user['password_hash'], password)
    with tx(actor_id=str(user['id'])) as conn:
        if not ok:
            fails = user['failed_login_count'] + 1
            conn.execute('update users set failed_login_count=%s, locked_until=%s where id=%s',
                         (fails if fails < MAX_FAILED_LOGINS else 0, n + LOCK_TIME if fails >= MAX_FAILED_LOGINS else None, user['id']))
        elif user['status'] == 'suspended':
            pass
        else:
            conn.execute('update users set failed_login_count=0, locked_until=null, last_login_at=%s where id=%s', (n, user['id']))
            token = create_session(conn, str(user['id']), ip, ua)
            mfa = conn.execute('select 1 from mfa_factors where user_id=%s and confirmed_at is not null and disabled_at is null',
                               (user['id'],)).fetchone() is not None
            known = conn.execute('select 1 from auth_sessions where user_id=%s and ip=%s and created_at < %s limit 1',
                                 (user['id'], ip, n)).fetchone()
            if not known:
                notifications.notify(conn, str(user['id']), 'new_login', {'ip': ip, 'quando': timeutil.fmt(n)},
                                     dedupe=f'login:{user["id"]}:{ip}', template='security_alert', in_app=True)
            return user, token, mfa
    if user['status'] == 'suspended':
        raise AppError(403, 'account_suspended', 'Conta suspensa. Entre em contato com o suporte.')
    raise generic


def logout(session_id: str) -> None:
    with tx() as conn:
        conn.execute("update auth_sessions set revoked_at=%s, revoked_reason='logout' where id=%s", (timeutil.now(), session_id))


def revoke_all_sessions(conn, user_id: str, reason: str, except_session: str | None = None) -> None:
    conn.execute('update auth_sessions set revoked_at=%s, revoked_reason=%s where user_id=%s and revoked_at is null and id is distinct from %s',
                 (timeutil.now(), reason, user_id, except_session))


def forgot_password(email: str, ip: str) -> None:
    security.rate_limit(f'forgot:{ip}', 10, 3600)
    email_n = (email or '').strip().lower()
    security.rate_limit(f'forgot-email:{email_n}', 3, 3600)
    with tx() as conn:
        user = conn.execute("select id from users where lower(email)=%s and deleted_at is null and status<>'suspended'",
                            (email_n,)).fetchone()
        if not user:
            return  # resposta idêntica: não revela existência
        conn.execute('update password_reset_tokens set invalidated_at=%s where user_id=%s and used_at is null and invalidated_at is null',
                     (timeutil.now(), user['id']))
        token = security.new_token()
        row = insert(conn, 'password_reset_tokens', {'user_id': user['id'], 'token_hash': security.sha256(token), 'ip': ip,
                                                     'expires_at': timeutil.now() + timedelta(minutes=30)})
        notifications.notify(conn, str(user['id']), 'password_reset', {'validade': '30 minutos'},
                             dedupe=f"reset:{row['id']}", link=f'/redefinir-senha?token={token}', in_app=False)
    notifications.process_deliveries(limit=5)


def reset_password(token: str, password: str, password_confirm: str) -> None:
    if password != password_confirm:
        raise unprocessable('validation_error', 'As senhas não conferem.', fields={'password_confirm': 'As senhas não conferem.'})
    n = timeutil.now()
    with tx() as conn:
        row = conn.execute('''select t.*, u.email, u.username from password_reset_tokens t join users u on u.id=t.user_id
                              where t.token_hash=%s for update''', (security.sha256(token or ''),)).fetchone()
        if not row or row['used_at'] or row['invalidated_at'] or row['expires_at'] <= n:
            raise bad_request('invalid_token', 'Link inválido ou expirado. Solicite uma nova recuperação.')
        probs = security.password_problems(password, row['email'], row['username'])
        if probs:
            raise unprocessable('validation_error', ' '.join(probs), fields={'password': ' '.join(probs)})
        conn.execute("select set_config('app.actor_id', %s, true)", (str(row['user_id']),))
        conn.execute('update password_reset_tokens set used_at=%s where id=%s', (n, row['id']))
        conn.execute('update users set password_hash=%s, failed_login_count=0, locked_until=null where id=%s',
                     (security.hash_password(password), row['user_id']))
        revoke_all_sessions(conn, str(row['user_id']), 'password_reset')
        notifications.notify(conn, str(row['user_id']), 'password_changed', {'quando': timeutil.fmt(n)},
                             dedupe=f"pwchg:{row['id']}", template='security_alert')


def change_password(user_id: str, session_id: str, current: str, new: str, confirm: str) -> None:
    security.rate_limit(f'chpw:{user_id}', 5, 900)
    with tx(actor_id=user_id) as conn:
        u = conn.execute('select * from users where id=%s', (user_id,)).fetchone()
        if u['password_hash'] and not security.verify_password(u['password_hash'], current or ''):
            raise AppError(400, 'wrong_password', 'Senha atual incorreta.')
        if new != confirm:
            raise unprocessable('validation_error', 'As senhas não conferem.')
        probs = security.password_problems(new, u['email'], u['username'])
        if probs:
            raise unprocessable('validation_error', ' '.join(probs), fields={'password': ' '.join(probs)})
        conn.execute('update users set password_hash=%s where id=%s', (security.hash_password(new), user_id))
        revoke_all_sessions(conn, user_id, 'password_changed', except_session=session_id)
        notifications.notify(conn, user_id, 'password_changed', {'quando': timeutil.fmt(timeutil.now())},
                             dedupe=f'pwchg:{user_id}:{int(timeutil.now().timestamp())}', template='security_alert')


def request_email_change(user_id: str, new_email: str, password: str) -> None:
    new_email = _norm_email(new_email)
    security.rate_limit(f'emailchg:{user_id}', 5, 3600)
    with tx(actor_id=user_id) as conn:
        u = conn.execute('select * from users where id=%s', (user_id,)).fetchone()
        if u['password_hash'] and not security.verify_password(u['password_hash'], password or ''):
            raise AppError(400, 'wrong_password', 'Senha atual incorreta.')
        if new_email == u['email'].lower():
            raise bad_request('same_email', 'Informe um e-mail diferente do atual.')
        if conn.execute('select 1 from users where lower(email)=%s and deleted_at is null', (new_email,)).fetchone():
            raise conflict('email_unavailable', 'Este e-mail não está disponível.')
        _issue_code(conn, user_id, 'email_change', new_email)
    notifications.process_deliveries(limit=5)


# ---------------------------------------------------------------- MFA (TOTP)
def mfa_setup(user_id: str, username: str) -> dict:
    secret = pyotp.random_base32()
    with tx(actor_id=user_id) as conn:
        if conn.execute('select 1 from mfa_factors where user_id=%s and confirmed_at is not null and disabled_at is null',
                        (user_id,)).fetchone():
            raise conflict('mfa_already_enabled', 'A autenticação em dois fatores já está ativa.')
        conn.execute('delete from mfa_factors where user_id=%s and confirmed_at is null', (user_id,))
        insert(conn, 'mfa_factors', {'user_id': user_id, 'totp_secret_enc': security.encrypt(secret)})
    return {'secret': secret, 'otpauth_uri': pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name='timedefora')}


def _check_totp(conn, factor: dict, code: str) -> bool:
    totp = pyotp.TOTP(security.decrypt(factor['totp_secret_enc']))
    now_ts = timeutil.now().timestamp()
    for offset in (-1, 0, 1):
        step = int(now_ts // 30) + offset
        if factor['last_used_step'] is not None and step <= factor['last_used_step']:
            continue
        if security.consteq(totp.at(step * 30), (code or '').strip()):
            conn.execute('update mfa_factors set last_used_step=%s where id=%s', (step, factor['id']))
            return True
    return False


def mfa_confirm(user_id: str, session_id: str, code: str) -> list[str]:
    security.rate_limit(f'mfa:{user_id}', 10, 300)
    with tx(actor_id=user_id) as conn:
        f = conn.execute('select * from mfa_factors where user_id=%s and confirmed_at is null and disabled_at is null for update',
                         (user_id,)).fetchone()
        if not f:
            raise bad_request('no_pending_mfa', 'Inicie a configuração da autenticação em dois fatores.')
        if not _check_totp(conn, f, code):
            raise bad_request('invalid_code', 'Código inválido.')
        conn.execute('update mfa_factors set confirmed_at=%s where id=%s', (timeutil.now(), f['id']))
        conn.execute('delete from mfa_recovery_codes where user_id=%s', (user_id,))
        codes = [security.new_token(6)[:10].upper() for _ in range(8)]
        for c in codes:
            insert(conn, 'mfa_recovery_codes', {'user_id': user_id, 'code_hash': security.hmac_hex('recovery', user_id, c)})
        conn.execute('update auth_sessions set mfa_verified_at=%s where id=%s', (timeutil.now(), session_id))
        audit_event(conn, 'mfa.enabled', 'users', user_id)
    return codes


def mfa_verify_session(user_id: str, session_id: str, code: str) -> None:
    security.rate_limit(f'mfa:{user_id}', 10, 300)
    with tx(actor_id=user_id) as conn:
        f = conn.execute('select * from mfa_factors where user_id=%s and confirmed_at is not null and disabled_at is null for update',
                         (user_id,)).fetchone()
        if not f:
            raise bad_request('mfa_not_enabled', 'Autenticação em dois fatores não está ativa.')
        ok = _check_totp(conn, f, code)
        if not ok:
            rc = conn.execute('select id from mfa_recovery_codes where user_id=%s and code_hash=%s and used_at is null',
                              (user_id, security.hmac_hex('recovery', user_id, (code or '').strip().upper()))).fetchone()
            if rc:
                conn.execute('update mfa_recovery_codes set used_at=%s where id=%s', (timeutil.now(), rc['id']))
                ok = True
        if not ok:
            raise bad_request('invalid_code', 'Código inválido.')
        conn.execute('update auth_sessions set mfa_verified_at=%s where id=%s', (timeutil.now(), session_id))


def mfa_disable(user_id: str, code: str) -> None:
    with tx(actor_id=user_id) as conn:
        f = conn.execute('select * from mfa_factors where user_id=%s and confirmed_at is not null and disabled_at is null for update',
                         (user_id,)).fetchone()
        if not f or not _check_totp(conn, f, code):
            raise bad_request('invalid_code', 'Código inválido.')
        conn.execute('update mfa_factors set disabled_at=%s where id=%s', (timeutil.now(), f['id']))
        conn.execute('update auth_sessions set mfa_verified_at=null where user_id=%s', (user_id,))
        audit_event(conn, 'mfa.disabled', 'users', user_id)

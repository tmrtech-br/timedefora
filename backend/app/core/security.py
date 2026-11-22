"""Senhas (Argon2id), tokens opacos, HMAC de códigos, criptografia AES-GCM e rate limit."""
import base64
import hashlib
import hmac
import os
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..config import settings
from . import timeutil
from .errors import too_many

_ph = PasswordHasher()  # Argon2id com parâmetros recomendados pela biblioteca


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw_hash: str | None, pw: str) -> bool:
    if not pw_hash:
        _ph.hash(pw)  # custo constante mesmo sem hash
        return False
    try:
        return _ph.verify(pw_hash, pw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problems(pw: str, email: str = '', username: str = '') -> list[str]:
    p = []
    if len(pw) < 10: p.append('A senha deve ter pelo menos 10 caracteres.')
    if len(pw) > 128: p.append('A senha deve ter no máximo 128 caracteres.')
    if not any(c.isalpha() for c in pw) or not any(c.isdigit() for c in pw):
        p.append('Use letras e números.')
    low = pw.lower()
    if (email and email.split('@')[0].lower() in low) or (username and username.lower() in low):
        p.append('A senha não pode conter seu e-mail ou nome de usuário.')
    return p


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hmac_hex(*parts: str) -> str:
    return hmac.new(settings.secret_key.encode(), '|'.join(parts).encode(), hashlib.sha256).hexdigest()


def new_numeric_code(digits: int = 6) -> str:
    return f'{secrets.randbelow(10 ** digits):0{digits}d}'


def consteq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def _aes() -> AESGCM:
    return AESGCM(hashlib.sha256(('enc|' + settings.secret_key).encode()).digest())


def encrypt(plain: str) -> str:
    nonce = os.urandom(12)
    return base64.urlsafe_b64encode(nonce + _aes().encrypt(nonce, plain.encode(), b'locaplay')).decode()


def decrypt(token: str) -> str:
    raw = base64.urlsafe_b64decode(token.encode())
    return _aes().decrypt(raw[:12], raw[12:], b'locaplay').decode()


def rate_limit(key: str, limit: int, window_seconds: int) -> None:
    """Janela fixa persistida no banco (funciona com várias instâncias da API).
    Roda em transação própria para que a contagem persista mesmo se a requisição falhar."""
    from .db import get_pool
    n = timeutil.now()
    with get_pool().connection() as conn:
        row = conn.execute(
            """insert into rate_limit_buckets(bucket_key, window_started_at, hits) values (%s, %s, 1)
               on conflict (bucket_key) do update set
                 hits = case when rate_limit_buckets.window_started_at <= %s then 1 else rate_limit_buckets.hits + 1 end,
                 window_started_at = case when rate_limit_buckets.window_started_at <= %s then %s else rate_limit_buckets.window_started_at end
               returning hits, window_started_at""",
            (key, n, n - timedelta(seconds=window_seconds), n - timedelta(seconds=window_seconds), n)).fetchone()
    if row['hits'] > limit:
        retry = int((row['window_started_at'] + timedelta(seconds=window_seconds) - n).total_seconds()) + 1
        raise too_many(retry_after=max(1, retry))

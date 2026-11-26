# SPDX-License-Identifier: AGPL-3.0-only
"""Encrypted PSN account store, scoped to this ConsoleAgent Windows account.

Only sanitized metadata leaves this module. The JSON payload is encrypted in its
entirety before it touches disk. Atomic replacement prevents interrupted writes.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from pathlib import Path
from typing import Protocol

from .secrets import WindowsDpapi

MAGIC = b'LOCAPLAY-PSN-DPAPI-V1\n'


class Protector(Protocol):
    def encrypt(self, value: bytes) -> bytes: ...
    def decrypt(self, value: bytes) -> bytes: ...


class AccountError(ValueError):
    pass


class PsnAccountStore:
    def __init__(self, path: str | Path, protector: Protector | None = None):
        self.path = Path(path)
        self.protector = protector if protector is not None else WindowsDpapi()
        self._io_lock = threading.RLock()
        self._refresh_locks: dict[str, asyncio.Lock] = {}
        self._items: dict[str, dict] = self._read()

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        raw = self.path.read_bytes()
        if not raw.startswith(MAGIC):
            raise AccountError('Arquivo de contas PSN inválido ou não cifrado. Não foi carregado.')
        try:
            decrypted = self.protector.decrypt(base64.b64decode(raw[len(MAGIC):], validate=True))
            data = json.loads(decrypted)
        except Exception as e:
            raise AccountError('Não foi possível abrir as contas PSN. Confira o usuário Windows/DPAPI.') from e
        if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k, v in data.items()):
            raise AccountError('Formato do cofre PSN inválido.')
        return data

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(self._items, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        encoded = MAGIC + base64.b64encode(self.protector.encrypt(raw))
        temp = self.path.with_name(self.path.name + '.tmp')
        try:
            with temp.open('wb') as f:
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)

    @staticmethod
    def public(record: dict) -> dict:
        return {k: record.get(k) for k in ('id', 'label', 'status', 'online_id', 'account_id',
                                             'expires_at', 'last_check_at', 'last_error')}

    def get(self, account_id: str) -> dict | None:
        with self._io_lock:
            value = self._items.get(account_id)
            return dict(value) if value else None

    def public_get(self, account_id: str) -> dict | None:
        value = self.get(account_id)
        return self.public(value) if value else None

    def upsert(self, record_id: str, label: str, **updates) -> dict:
        if not record_id or not label or len(label) > 80:
            raise AccountError('Identificador/rótulo PSN inválido.')
        allowed = {'access_token', 'refresh_token', 'expires_at', 'online_id', 'account_id',
                   'status', 'last_check_at', 'last_error'}
        if set(updates) - allowed:
            raise AccountError('Campo não permitido no cofre PSN.')
        with self._io_lock:
            record = dict(self._items.get(record_id, {'id': record_id, 'status': 'pending'}))
            record.update({'id': record_id, 'label': label, **updates})
            self._items[record_id] = record
            self._write()
            return self.public(record)

    def update(self, record_id: str, **updates) -> dict:
        record = self.get(record_id)
        if record is None:
            raise AccountError('Conta PSN não encontrada no agente. Inicie o vínculo novamente.')
        return self.upsert(record_id, record['label'], **updates)

    def delete(self, account_id: str) -> bool:
        with self._io_lock:
            if account_id not in self._items:
                return False
            del self._items[account_id]
            self._write()
            self._refresh_locks.pop(account_id, None)
            return True

    def refresh_lock(self, account_id: str) -> asyncio.Lock:
        with self._io_lock:
            return self._refresh_locks.setdefault(account_id, asyncio.Lock())

    async def access_token(self, record_id: str, renew, skew_seconds: int = 120) -> str:
        """Return a valid token, calling `await renew(refresh_token)` just once per account.

        Separate accounts have separate locks; a Sony outage for A never locks B.
        `renew` must return credentials in the request_token() shape.
        """
        async with self.refresh_lock(record_id):
            record = self.get(record_id)
            if not record or record.get('status') in ('disabled', 'expired', 'error'):
                raise AccountError('Conta PSN indisponível; verifique a autenticação.')
            token = record.get('access_token')
            expires = float(record.get('expires_at') or 0)
            if token and expires > time.time() + skew_seconds:
                return str(token)
            refresh = record.get('refresh_token')
            if not refresh:
                self.update(record_id, status='expired', last_error='Refresh token ausente.')
                raise AccountError('Refresh token ausente; refaça o login Sony.')
            try:
                new = await renew(str(refresh))
                if not new.get('access_token'):
                    raise ValueError('Token de acesso ausente')
                self.update(record_id, **new, status='linked', last_error='', last_check_at=time.time())
                return str(new['access_token'])
            except Exception as e:
                self.update(record_id, status='expired', last_error='Renovação PSN falhou; faça login novamente.')
                raise AccountError('Renovação PSN falhou; faça login novamente.') from e

    def expire_if_needed(self, account_id: str) -> dict:
        with self._io_lock:
            record = self._items.get(account_id)
            if record is None:
                raise AccountError('Conta PSN não encontrada.')
            if record.get('expires_at') and float(record['expires_at']) <= time.time() and not record.get('refresh_token'):
                return self.update(account_id, status='expired', last_error='Token expirado. Vincule a conta novamente.')
            return self.public(record)

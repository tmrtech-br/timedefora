"""Acesso ao PostgreSQL/Supabase com pool e transações que registram o ator na auditoria."""
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from ..config import settings
from .context import actor_id_var, actor_ip_var, request_id_var

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # prepare_threshold=None: compatível com o pooler do Supabase (modo transação).
        _pool = ConnectionPool(settings.database_url, min_size=1, max_size=10, open=True,
                               kwargs={'row_factory': dict_row, 'autocommit': True, 'prepare_threshold': None})
        import atexit
        atexit.register(close_pool)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx(actor_id: str | None = None) -> Iterator[psycopg.Connection]:
    """Abre transação; define app.actor_id/app.actor_ip/app.request_id para os triggers de auditoria."""
    with get_pool().connection() as conn:
        with conn.transaction():
            conn.execute(
                "select set_config('app.actor_id', %s, true), set_config('app.actor_ip', %s, true), "
                "set_config('app.request_id', %s, true)",
                (actor_id or actor_id_var.get() or '', actor_ip_var.get() or '', request_id_var.get() or ''))
            yield conn


def one(conn, query: str, params: Any = None) -> dict | None:
    return conn.execute(query, params).fetchone()


def all_(conn, query: str, params: Any = None) -> list[dict]:
    return conn.execute(query, params).fetchall()


def insert(conn, table: str, data: dict, returning: str = '*') -> dict:
    cols = list(data.keys())
    q = sql.SQL('insert into {t} ({c}) values ({v}) returning ' + returning).format(
        t=sql.Identifier(table), c=sql.SQL(',').join(map(sql.Identifier, cols)),
        v=sql.SQL(',').join(sql.Placeholder() * len(cols)))
    return conn.execute(q, [data[c] for c in cols]).fetchone()


def update(conn, table: str, row_id: Any, data: dict, returning: str = '*') -> dict | None:
    if not data:
        return conn.execute(sql.SQL('select * from {t} where id=%s').format(t=sql.Identifier(table)), (row_id,)).fetchone()
    sets = sql.SQL(',').join(sql.SQL('{c}=%s').format(c=sql.Identifier(c)) for c in data)
    q = sql.SQL('update {t} set {s} where id=%s returning ' + returning).format(t=sql.Identifier(table), s=sets)
    return conn.execute(q, [*data.values(), row_id]).fetchone()


def audit_event(conn, action: str, table_name: str | None = None, record_id: Any = None,
                reason: str | None = None, details: dict | None = None) -> None:
    """Evento de negócio explícito (além dos triggers de linha)."""
    from psycopg.types.json import Jsonb
    conn.execute(
        "insert into audit_logs(source, action, table_name, record_id, actor_user_id, actor_ip, request_id, reason, details) "
        "values ('app', %s, %s, %s, nullif(current_setting('app.actor_id', true),'')::uuid, "
        "nullif(current_setting('app.actor_ip', true),''), nullif(current_setting('app.request_id', true),''), %s, %s)",
        (action, table_name, str(record_id) if record_id is not None else None, reason, Jsonb(details or {})))

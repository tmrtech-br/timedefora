"""Executor de migrations versionadas (funciona no Supabase e em PostgreSQL local).

Uso:  python -m app.migrate            # aplica pendentes
      python -m app.migrate --status   # lista aplicadas/pendentes
Cada arquivo migrations/NNN_*.sql roda em uma transação e é registrado em
schema_migrations com checksum; alterar um arquivo já aplicado gera erro.
"""
import hashlib
import sys
from pathlib import Path

import psycopg

from .config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / 'migrations'


def _files():
    return sorted(p for p in MIGRATIONS_DIR.glob('[0-9][0-9][0-9]_*.sql'))


def migrate(dsn: str | None = None, verbose: bool = True) -> list[str]:
    applied_now: list[str] = []
    with psycopg.connect(dsn or settings.database_url, autocommit=True, prepare_threshold=None) as conn:
        conn.execute("""create table if not exists public.schema_migrations(
            version text primary key, checksum text not null, applied_at timestamptz not null default now())""")
        conn.execute('alter table public.schema_migrations enable row level security')
        done = {r[0]: r[1] for r in conn.execute('select version, checksum from public.schema_migrations')}
        for f in _files():
            sql = f.read_text(encoding='utf-8')
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            if f.name in done:
                if done[f.name] != checksum:
                    raise RuntimeError(f'Migration {f.name} foi alterada após aplicada; crie uma nova migration.')
                continue
            with conn.transaction():
                conn.execute(sql)
                conn.execute('insert into public.schema_migrations(version, checksum) values (%s,%s)', (f.name, checksum))
            applied_now.append(f.name)
            if verbose:
                print('aplicada', f.name)
    return applied_now


if __name__ == '__main__':
    if '--status' in sys.argv:
        with psycopg.connect(settings.database_url, prepare_threshold=None) as c:
            done = {r[0] for r in c.execute('select version from public.schema_migrations')}
        for f in _files():
            print(('[x] ' if f.name in done else '[ ] ') + f.name)
    else:
        migrate()

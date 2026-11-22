"""Relógio canônico do servidor (UTC) e formatação para America/Fortaleza."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo('America/Fortaleza')
_override: datetime | None = None   # usado apenas por testes


def now() -> datetime:
    return _override if _override is not None else datetime.now(timezone.utc)


def set_now(value: datetime | None) -> None:
    global _override
    _override = value


def local(dt: datetime) -> datetime:
    return dt.astimezone(TZ)


def fmt(dt: datetime | None) -> str:
    if dt is None:
        return '—'
    return local(dt).strftime('%d/%m/%Y às %H:%M')


def fmt_time(dt: datetime) -> str:
    return local(dt).strftime('%H:%M')


def fmt_minutes(total: int) -> str:
    h, m = divmod(max(0, int(total)), 60)
    return f'{h}h{m:02d}' if h else f'{m} min'


def money(cents: int) -> str:
    return 'R$ ' + f'{cents/100:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

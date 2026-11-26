"""Utilitários de rotas: cookies de sessão, serialização."""
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import Response
from psycopg.types.range import Range
from pydantic import BaseModel, StringConstraints

from ..config import settings
from ..core.deps import CSRF_COOKIE, SESSION_COOKIE
from ..core.security import new_token


class DeleteIn(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]


class SupportMessageIn(BaseModel):
    body: Annotated[str, StringConstraints(min_length=1, max_length=5000)]


def set_session_cookies(resp: Response, token: str) -> None:
    max_age = settings.session_days * 86400
    resp.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=settings.cookie_secure,
                    samesite='lax', path='/', domain=settings.cookie_domain)
    resp.set_cookie(CSRF_COOKIE, new_token(16), max_age=max_age, httponly=False, secure=settings.cookie_secure,
                    samesite='lax', path='/', domain=settings.cookie_domain)


def clear_session_cookies(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE, path='/', domain=settings.cookie_domain)
    resp.delete_cookie(CSRF_COOKIE, path='/', domain=settings.cookie_domain)


def jsonable(v):
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, Range):
        return {'lower': jsonable(v.lower), 'upper': jsonable(v.upper)}
    return v


def pick(row: dict | None, *keys: str) -> dict | None:
    if row is None:
        return None
    return {k: jsonable(row.get(k)) for k in keys}

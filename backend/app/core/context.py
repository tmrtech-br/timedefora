"""Contexto da requisição (ator, IP, request id) propagado para a auditoria do banco."""
from contextvars import ContextVar

actor_id_var: ContextVar[str | None] = ContextVar('actor_id', default=None)
actor_ip_var: ContextVar[str | None] = ContextVar('actor_ip', default=None)
request_id_var: ContextVar[str | None] = ContextVar('request_id', default=None)

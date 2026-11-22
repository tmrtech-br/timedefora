"""Erros de aplicação com mensagens em pt-BR e código estável para o frontend."""


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}


def bad_request(code: str, msg: str, **extra): return AppError(400, code, msg, extra)
def unauthorized(msg: str = 'Faça login para continuar.'): return AppError(401, 'auth_required', msg)
def forbidden(msg: str = 'Você não tem permissão para esta ação.', code: str = 'forbidden'): return AppError(403, code, msg)
def not_found(msg: str = 'Registro não encontrado.'): return AppError(404, 'not_found', msg)
def conflict(code: str, msg: str, **extra): return AppError(409, code, msg, extra)
def unprocessable(code: str, msg: str, **extra): return AppError(422, code, msg, extra)
def too_many(msg: str = 'Muitas tentativas. Aguarde e tente novamente.', retry_after: int = 60):
    return AppError(429, 'rate_limited', msg, {'retry_after': retry_after})

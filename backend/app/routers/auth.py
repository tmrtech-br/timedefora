"""Rotas de autenticação: cadastro, verificação, login, logout, recuperação, MFA, Google."""
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from ..config import settings
from ..core.deps import Principal, client_ip, current_user, optional_user
from ..core.errors import AppError
from ..services import auth, google_oauth
from .common import clear_session_cookies, set_session_cookies

router = APIRouter(prefix='/auth', tags=['auth'])


class RegisterIn(BaseModel):
    full_name: str = Field(max_length=120)
    username: str = Field(max_length=24)
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)
    password_confirm: str = Field(max_length=128)
    accept_terms: bool = False
    accept_privacy: bool = False
    marketing_opt_in: bool = False


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)


class CodeIn(BaseModel):
    code: str = Field(max_length=20)


class ForgotIn(BaseModel):
    email: str = Field(max_length=254)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=128)
    password_confirm: str = Field(max_length=128)


@router.post('/register', status_code=201)
def register(body: RegisterIn, request: Request, response: Response):
    user, token = auth.register(body.model_dump(), client_ip(request), request.headers.get('user-agent', ''))
    set_session_cookies(response, token)
    return {'id': str(user['id']), 'status': user['status'],
            'message': 'Conta criada. Enviamos um código de 6 dígitos para o seu e-mail.'}


@router.post('/verify-email')
def verify_email(body: CodeIn, p: Principal = Depends(current_user)):
    return auth.verify_code(p.user_id, 'signup', body.code)


@router.post('/resend-code')
def resend(p: Principal = Depends(current_user)):
    auth.resend_code(p.user_id, 'signup')
    return {'message': 'Novo código enviado.'}


@router.post('/login')
def login(body: LoginIn, request: Request, response: Response):
    user, token, mfa = auth.login(body.email, body.password, client_ip(request), request.headers.get('user-agent', ''))
    set_session_cookies(response, token)
    return {'mfa_required': mfa, 'email_verified': user['email_verified_at'] is not None}


@router.post('/logout')
def logout(response: Response, p: Principal | None = Depends(optional_user)):
    if p:
        auth.logout(p.session_id)
    clear_session_cookies(response)
    return {'ok': True}


@router.post('/password/forgot')
def forgot(body: ForgotIn, request: Request):
    auth.forgot_password(body.email, client_ip(request))
    return {'message': 'Se houver uma conta com este e-mail, enviaremos instruções em instantes.'}


@router.post('/password/reset')
def reset(body: ResetIn):
    auth.reset_password(body.token, body.password, body.password_confirm)
    return {'message': 'Senha alterada. Todas as sessões foram encerradas; entre novamente.'}


@router.post('/mfa/verify')
def mfa_verify(body: CodeIn, p: Principal = Depends(current_user)):
    auth.mfa_verify_session(p.user_id, p.session_id, body.code)
    return {'ok': True}


@router.get('/google/start')
def google_start(intent: str = 'login', p: Principal | None = Depends(optional_user)):
    if intent not in ('login', 'link'):
        raise AppError(400, 'invalid_intent', 'Intenção inválida.')
    if intent == 'link' and not p:
        raise AppError(401, 'auth_required', 'Entre para vincular sua conta Google.')
    return RedirectResponse(google_oauth.start(intent, p.user_id if p else None), status_code=302)


@router.get('/google/status')
def google_status():
    return {'configured': google_oauth.configured()}


@router.get('/google/callback')
def google_callback(request: Request, code: str = '', state: str = '', error: str = ''):
    base = settings.frontend_url.rstrip('/')
    if error or not code:
        return RedirectResponse(base + '/entrar?erro=google_cancelado', status_code=302)
    try:
        result = google_oauth.callback(code, state, client_ip(request), request.headers.get('user-agent', ''))
    except AppError as e:
        return RedirectResponse(base + f'/entrar?erro={e.code}', status_code=302)
    resp = RedirectResponse(base + result['redirect'], status_code=302)
    if result.get('session_token'):
        set_session_cookies(resp, result['session_token'])
    return resp

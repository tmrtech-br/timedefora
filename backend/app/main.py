"""LocaPlay API — FastAPI + PostgreSQL/Supabase."""
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .core.context import actor_id_var, actor_ip_var, request_id_var
from .core.db import close_pool, get_pool
from .core.deps import CSRF_COOKIE, SESSION_COOKIE, client_ip, load_principal
from .core.errors import AppError
from .gamebridge import CONTRACT_VERSION
from .routers import admin, auth, catalog, launch_scripts, me, owner, play, psn_accounts
from .routers.me import MEDIA_DIR

log = logging.getLogger('locaplay')
CSRF_EXEMPT_PREFIXES = ('/webhooks/', '/agents/')


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.validate()
    get_pool()
    worker = None
    if settings.run_worker:
        from .worker import WorkerThread
        worker = WorkerThread()
        worker.start()
    yield
    if worker:
        worker.stop()
    close_pool()


app = FastAPI(title='LocaPlay API', version='1.0.0', lifespan=lifespan,
              docs_url=None if settings.is_production else '/docs', redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
                   allow_headers=['Content-Type', 'X-CSRF-Token', 'X-Input-Token'])


@app.middleware('http')
async def security_middleware(request: Request, call_next):
    rid = request.headers.get('x-request-id') or uuid.uuid4().hex
    request_id_var.set(rid[:64])
    actor_ip_var.set(client_ip(request))
    actor_id_var.set(None)
    request.state.principal = None
    path = request.url.path
    token = request.cookies.get(SESSION_COOKIE)
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and not path.startswith(CSRF_EXEMPT_PREFIXES):
        origin = request.headers.get('origin')
        if origin and origin not in settings.cors_origins:
            return JSONResponse({'detail': 'Origem não permitida.', 'code': 'bad_origin'}, status_code=403)
        if token:
            header, cookie = request.headers.get('x-csrf-token'), request.cookies.get(CSRF_COOKIE)
            if not header or not cookie or header != cookie:
                return JSONResponse({'detail': 'Falha na verificação CSRF. Recarregue a página.', 'code': 'csrf'}, status_code=403)
    if token:
        p = load_principal(token)
        request.state.principal = p
        if p:
            actor_id_var.set(p.user_id)
    response = await call_next(request)
    response.headers['X-Request-ID'] = rid[:64]
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Cache-Control'] = response.headers.get('Cache-Control', 'no-store')
    if settings.cookie_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    headers = {'Retry-After': str(exc.extra['retry_after'])} if 'retry_after' in exc.extra else None
    return JSONResponse({'detail': exc.message, 'code': exc.code, **exc.extra}, status_code=exc.status, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = {}
    for e in exc.errors():
        loc = [str(x) for x in e['loc'] if x not in ('body', 'query', 'path')]
        fields['.'.join(loc) or 'request'] = 'Valor inválido.' if e['type'] != 'missing' else 'Campo obrigatório.'
    return JSONResponse({'detail': 'Verifique os dados enviados.', 'code': 'validation_error', 'fields': fields}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception('Erro não tratado (request_id=%s)', request_id_var.get())
    return JSONResponse({'detail': 'Erro interno. Tente novamente.', 'code': 'internal_error', 'request_id': request_id_var.get()},
                        status_code=500)


@app.get('/health')
def health():
    db_ok = True
    try:
        with get_pool().connection() as c:
            c.execute('select 1')
    except Exception:  # noqa: BLE001
        db_ok = False
    return {'status': 'ok' if db_ok else 'degraded', 'database': db_ok, 'env': settings.env,
            'payment_provider': settings.payment_provider, 'payments_simulated': settings.payment_provider == 'simulated',
            'email_provider': settings.email_provider, 'gamebridge_contract': CONTRACT_VERSION,
            'real_consoles_validated': False}


for r in (auth.router, me.router, catalog.router, play.router, admin.router, psn_accounts.router, owner.router,
          launch_scripts.owner_router, launch_scripts.admin_router):
    app.include_router(r)

MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount('/media', StaticFiles(directory=str(MEDIA_DIR)), name='media')

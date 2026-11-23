"""API HTTP do agente: recebe os comandos da API LocaPlay (protocolo de backend/app/gamebridge/agent_client.py).

POST /v1/consoles/{console_id}/{acao}   Authorization: Bearer <token API→agente>
Resposta: {"ok": bool, "simulated": false, "message": str, "state": str|null, "data": {...}}
Ações ainda não implementadas respondem 501 {"code": "not_implemented", "message": ...} → o painel mostra "não disponível".
"""
from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import VERSION, discovery
from .config import AgentConfig

log = logging.getLogger('consoleagent')

PART2 = {
    'pair': 'Pareamento',
    'connect': 'Conexão com o console',
    'stream/start': 'Início da transmissão',
    'stream/stop': 'Encerramento da transmissão',
    'stream/status': 'Status da transmissão',
    'input': 'Envio de comandos',
    'input/revoke': 'Revogação de comandos',
    'test/video-audio': 'Teste de imagem e áudio',
    'test/controls': 'Teste de controles',
    'disconnect': 'Desconexão',
    'console/prepare': 'Preparação do console (acordar e abrir o jogo)',
}


def _result(ok: bool, message: str, state: str | None = None, data: dict | None = None) -> dict:
    return {'ok': ok, 'simulated': False, 'message': message, 'state': state, 'data': data or {}}


def _not_implemented(label: str) -> JSONResponse:
    return JSONResponse(status_code=501, content={
        'code': 'not_implemented',
        'message': f'{label}: chega na Parte 2 do ConsoleAgent (integração com o chiaki-ng). Nada foi executado no console.'})


def create_app(cfg: AgentConfig, discover_fn: Callable = discovery.discover) -> FastAPI:
    app = FastAPI(title='LocaPlay ConsoleAgent', version=VERSION, docs_url=None, redoc_url=None)
    expected = f'Bearer {cfg.api_to_agent_token}'.encode()

    @app.get('/')
    def root():
        # Sem dados sensíveis: só para conferir no navegador que o agente está de pé.
        return {'service': 'LocaPlay ConsoleAgent', 'version': VERSION}

    @app.post('/v1/consoles/{console_id}/{action:path}')
    async def command(console_id: str, action: str, request: Request):
        auth = (request.headers.get('authorization') or '').encode()
        if not hmac.compare_digest(auth, expected):
            log.warning('comando recusado: credencial inválida (ação %s)', action)
            return JSONResponse(status_code=401, content={'code': 'unauthorized', 'message': 'Credencial inválida.'})
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        log.info('comando %s para console %s', action, console_id)

        if action == 'health':
            chiaki = 'chiaki-ng encontrado' if cfg.chiaki_found else f'chiaki-ng NÃO encontrado em {cfg.chiaki_path}'
            return _result(True, f'ConsoleAgent {VERSION} online. {chiaki}.', None,
                           {'agent_version': VERSION, 'chiaki_found': cfg.chiaki_found})

        if action == 'discover':
            return _discover(cfg, body, discover_fn)

        if action == 'metrics':
            # Nenhuma medição real ainda: valores ausentes (o painel mostra "não disponível").
            return {'metrics': {}}

        if action in PART2:
            return _not_implemented(PART2[action])

        return JSONResponse(status_code=404, content={'code': 'unknown_action', 'message': f'Ação desconhecida: {action}'})

    return app


def _discover(cfg: AgentConfig, body: dict, discover_fn: Callable) -> dict | JSONResponse:
    route = body.get('route') or 'lan'
    platform = body.get('platform_code') or 'PS4'
    if route == 'internet_psn':
        return _not_implemented('Descoberta pela PSN (console em outra rede, sem portas abertas)')
    host = (body.get('host') or '').strip() or None
    if route == 'internet_port_forward' and not host:
        return _result(False, 'Informe o IP público/DDNS do roteador do console no cadastro.')
    # A descoberta usa sempre a porta padrão (UDP 987 no PS4, 9302 no PS5); a "porta base" do cadastro é a do streaming.
    try:
        found = discover_fn(host, platform, cfg.discovery_timeout_seconds)
    except OSError as e:
        return _result(False, f'Falha de rede ao procurar o console: {e}', 'error')
    where = host or 'rede local (broadcast)'
    if not found:
        hint = ('Confira se o console está ligado ou em repouso com "Permanecer conectado à Internet" ativo, '
                'se o IP está correto e se o firewall do Windows permite o ConsoleAgent.')
        if route == 'internet_port_forward':
            hint = 'Confira o redirecionamento da porta UDP de descoberta (987 no PS4, 9302 no PS5) no roteador do console e se não há CGNAT.'
        return _result(False, f'Nenhum console respondeu em {where}. {hint}', 'unavailable')
    ident = (body.get('console_identifier') or '').strip().lower()
    chosen = next((c for c in found if ident and (c.host_name or '').lower() == ident), found[0])
    others = [c.to_dict() for c in found if c is not chosen]
    msg = f"{chosen.host_name or 'Console'} ({chosen.host_type or platform}) encontrado em {chosen.address}: {chosen.state}"
    if chosen.system_version:
        msg += f' · sistema {chosen.system_version}'
    if ident and (chosen.host_name or '').lower() != ident:
        msg += f' · ATENÇÃO: nome diferente do cadastrado ("{body.get("console_identifier")}")'
    return _result(True, msg + '.', 'idle', {'console': chosen.to_dict(), 'others': others})

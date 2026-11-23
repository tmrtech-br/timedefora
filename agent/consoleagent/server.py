"""API HTTP do agente: recebe os comandos da API LocaPlay (protocolo de backend/app/gamebridge/agent_client.py).

POST /v1/consoles/{console_id}/{acao}   Authorization: Bearer <token API→agente>
Resposta: {"ok": bool, "simulated": false, "message": str, "state": str|null, "data": {...}}
O corpo traz "target": {route, host, platform_code, console_identifier} enviado pela API.
"""
from __future__ import annotations

import hmac
import importlib.util
import logging
import time
from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import VERSION, discovery
from .chiaki import ChiakiDriver
from .config import AgentConfig
from .gamepad import GamepadUnavailable
from .runtime import ConsoleRuntime, Deps, Target, target_from
from .webrtc import WebRtcHub, WebRtcUnavailable

log = logging.getLogger('consoleagent')


def _result(ok: bool, message: str, state: str | None = None, data: dict | None = None) -> dict:
    return {'ok': ok, 'simulated': False, 'message': message, 'state': state, 'data': data or {}}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={'code': code, 'message': message})


def _has(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def create_app(cfg: AgentConfig, discover_fn: Callable = discovery.discover, deps: Deps | None = None) -> FastAPI:
    app = FastAPI(title='LocaPlay ConsoleAgent', version=VERSION, docs_url=None, redoc_url=None)
    expected = f'Bearer {cfg.api_to_agent_token}'.encode()
    base = deps or Deps(chiaki=ChiakiDriver(cfg.chiaki_path), discover=discover_fn)
    runtimes: dict[str, ConsoleRuntime] = {}
    hub = WebRtcHub(cfg.ice_servers, int(cfg.video_max_width), bool(cfg.stream_audio))
    app.state.webrtc = hub

    def rt(console_id: str) -> ConsoleRuntime:
        if console_id not in runtimes:
            # Um chiaki-ng por console; as demais dependências são compartilhadas.
            d = base if not runtimes else Deps(**{**base.__dict__, 'chiaki': ChiakiDriver(cfg.chiaki_path)})
            runtimes[console_id] = ConsoleRuntime(cfg, d)
        return runtimes[console_id]

    app.state.runtimes = runtimes

    @app.get('/')
    def root():
        # Sem dados sensíveis: só para conferir no navegador que o agente está de pé.
        return {'service': 'LocaPlay ConsoleAgent', 'version': VERSION}

    @app.post('/v1/consoles/{console_id}/{action:path}')
    async def command(console_id: str, action: str, request: Request):
        auth = (request.headers.get('authorization') or '').encode()
        if not hmac.compare_digest(auth, expected):
            log.warning('comando recusado: credencial inválida (ação %s)', action)
            return _error(401, 'unauthorized', 'Credencial inválida.')
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if action != 'input':                    # comandos do jogador são muitos: não poluir o log
            log.info('comando %s para console %s', action, console_id)
        sid = str(body.get('session_id') or '')
        if action == 'stream/webrtc':
            return await _webrtc(console_id, sid, body.get('offer') or {})
        # As ações podem esperar (capturas de tela, preparação): fora do laço assíncrono do servidor.
        res = await run_in_threadpool(handle, console_id, action, body)
        if action in ('input/revoke', 'stream/stop'):
            await hub.close(console_id, sid or None)          # vídeo acompanha o controle
        elif action == 'disconnect':
            await hub.close(console_id)
        return res

    async def _webrtc(console_id: str, sid: str, offer: dict):
        r = rt(console_id)
        if not sid or sid != r.session_id:
            return _error(403, 'input_revoked', 'Vídeo só para a sessão ativa neste console.')
        if not r.streaming:
            return _result(False, 'O console não está transmitindo (preparação não concluída).', 'stopped')
        if offer.get('type') != 'offer' or not isinstance(offer.get('sdp'), str):
            return _error(400, 'invalid_offer', 'Oferta de vídeo inválida.')
        try:
            answer, msg = await hub.answer(console_id, sid, offer, lambda: r.d.chiaki.pid)
        except WebRtcUnavailable as e:
            return _result(False, str(e), 'degraded')
        except Exception as e:  # nunca derrubar o agente por falha de negociação
            log.exception('falha ao negociar WebRTC')
            return _result(False, f'Falha ao iniciar o vídeo: {e.__class__.__name__}: {e}', 'error')
        return _result(True, msg, 'streaming', {'answer': answer})

    def handle(console_id: str, action: str, body: dict):
        t = target_from(cfg, console_id, body)
        r = rt(console_id)
        sid = str(body.get('session_id') or '')

        if action == 'health':
            return _health(cfg, r)
        if action == 'discover':
            return _discover(cfg, body, t, r, base.discover)
        if action == 'metrics':
            fps = hub.fps(console_id)            # quadros reais enviados ao navegador (medidos), senão ausente
            return {'metrics': {'fps': fps} if fps is not None else {}}
        if action == 'pair':
            return _pair(t, r)
        if action in ('connect', 'console/prepare'):
            return _job(r.start_job(t, 'prepare' if action == 'console/prepare' else 'connect', body.get('game')))
        if action == 'stream/start':
            ok, msg = r.start_session(sid)
            if not ok:
                r.start_job(t, 'connect', wait=0)            # tenta reconectar em segundo plano
            return _result(ok, msg, 'streaming' if ok else 'connecting')
        if action == 'stream/status':
            return _result(r.streaming, 'Transmitindo.' if r.streaming else 'Console desconectado.',
                           'streaming' if r.streaming else 'stopped', {'session_active': bool(r.session_id)})
        if action == 'input':
            try:
                r.input(sid, body.get('command') or {})
            except PermissionError as e:
                code = 'blocked_command' if 'bloqueado' in str(e) else 'input_revoked'
                return _error(403, code, str(e))
            except (ValueError, TypeError) as e:
                return _error(400, 'invalid_command', str(e))
            except GamepadUnavailable as e:
                return _error(503, 'gamepad_unavailable', str(e))
            return _result(True, '', 'streaming')
        if action == 'input/revoke':
            r.revoke(sid or None)
            return _result(True, 'Controle revogado.', 'streaming' if r.streaming else 'stopped')
        if action == 'stream/stop':
            r.revoke(sid or None)
            if cfg.stop_chiaki_after_session:
                r.disconnect()
            return _result(True, 'Sessão encerrada no console.', 'idle' if r.streaming else 'stopped')
        if action == 'disconnect':
            r.disconnect()
            return _result(True, 'chiaki-ng encerrado e controle virtual removido.', 'stopped')
        if action == 'test/video-audio':
            return _test_video_audio(r)
        if action == 'test/controls':
            return _test_controls(cfg, r)
        return _error(404, 'unknown_action', f'Ação desconhecida: {action}')

    return app


# ---------------------------------------------------------------- ações
def _health(cfg: AgentConfig, r: ConsoleRuntime) -> dict:
    ch = r.d.chiaki
    parts = [f'ConsoleAgent {VERSION} online',
             'chiaki-ng encontrado' if ch.available else f'chiaki-ng NÃO encontrado em {cfg.chiaki_path}',
             'controle virtual: ' + ('pacote vgamepad instalado' if _has('vgamepad') else 'vgamepad NÃO instalado'),
             'captura de imagem: ' + ('ok' if _has('PIL') else 'Pillow NÃO instalado'),
             'medição de áudio: ' + ('ok' if _has('pycaw') else 'pycaw NÃO instalado')]
    if not cfg.consoles:
        parts.append('nenhum console em "consoles" no config.json')
    return _result(True, '. '.join(parts) + '.', 'streaming' if r.streaming else None,
                   {'agent_version': VERSION, 'chiaki_found': ch.available, 'vgamepad': _has('vgamepad'),
                    'pillow': _has('PIL'), 'pycaw': _has('pycaw'), 'consoles_configured': sorted(cfg.consoles)})


def _job(j) -> dict:
    if j.state == 'ok':
        return _result(True, j.message, 'streaming', {'step': j.step})
    if j.state == 'failed':
        return _result(False, j.message, 'error', {'step': j.step})
    secs = int(time.monotonic() - j.started)
    return _result(False, f'Em andamento ({secs}s): {j.step}…', 'connecting', {'step': j.step, 'running': True})


def _pair(t: Target, r: ConsoleRuntime) -> dict:
    """O registro (PIN do console) é feito na interface do chiaki-ng; aqui só conferimos se já existe."""
    reg = r.d.chiaki.registered(t.nickname) if t.nickname else None
    if reg:
        return _result(True, f'"{t.nickname}" está registrado no chiaki-ng deste PC.', 'idle')
    how = ('No PC do agente: abra o chiaki-ng → adicione/registre o console com o PIN de Configurações → '
           'Configurações da Conexão de Uso Remoto → Adicionar Dispositivo. Use como apelido a identificação do painel.')
    if reg is None:
        return _result(False, 'Não foi possível consultar os consoles do chiaki-ng. ' + how, 'unavailable')
    return _result(False, f'"{t.nickname}" ainda não está registrado no chiaki-ng. ' + how, 'unavailable')


def _test_video_audio(r: ConsoleRuntime) -> dict:
    if not r.streaming:
        return _result(False, 'Console não conectado: use "Conectar" (ou aguarde a preparação) antes do teste.', 'stopped')
    pid = r.d.chiaki.pid
    a = r.d.frame(pid)
    time.sleep(0.6)
    b = r.d.frame(pid)
    mv = None
    if a.ok and b.ok:
        from .media import motion
        mv = motion(a, b)
    peak, amsg = r.d.audio(pid, 1.5)
    video_ok = a.ok and b.ok
    audio_ok = peak is not None and peak > 0.001
    msg = 'Imagem: ' + (b.message if b.ok else a.message if not a.ok else b.message)
    if mv is not None:
        msg += f' Movimento entre capturas: {mv} ({"imagem em movimento" if mv > 0.5 else "imagem parada"}).'
    msg += f' Áudio: {amsg}'
    if video_ok and not audio_ok:
        msg += ' O teste só passa com som real: deixe o console numa tela com música/efeitos e teste de novo.'
    # Aprovado somente com imagem E áudio medidos de verdade (a API marca os dois como validados).
    return _result(video_ok and audio_ok, msg, 'streaming' if video_ok else 'degraded',
                   {'video': b.to_dict(), 'motion': mv, 'audio_peak': peak, 'video_ok': video_ok, 'audio_ok': audio_ok})


def _test_controls(cfg: AgentConfig, r: ConsoleRuntime) -> dict:
    if not r.streaming:
        return _result(False, 'Console não conectado: use "Conectar" antes do teste de controles.', 'stopped')
    if r.session_id:
        return _result(False, 'Há um jogador usando o console agora: teste bloqueado para não interferir.', 'streaming')
    try:
        pad = r.ensure_pad()
    except GamepadUnavailable as e:
        return _result(False, str(e), 'degraded')
    btn = (cfg.control_test_button or '').strip().lower()
    if not btn:
        # Sem apertar nada não há como provar que o console recebe os comandos: não aprova.
        return _result(False, 'Controle virtual DS4 ativo e chiaki-ng conectado, mas a resposta do console não foi medida. '
                       'Defina "control_test_button" no config.json (botão inofensivo na tela atual, ex.: "dpad_right" '
                       'no menu inicial) e teste de novo.', 'streaming')
    pid = r.d.chiaki.pid
    before = r.d.frame(pid)
    pad.press(btn, 0.15)
    time.sleep(0.9)
    after = r.d.frame(pid)
    from .media import motion
    mv = motion(before, after)
    if mv is None:
        return _result(False, f'Botão "{btn}" enviado, mas a imagem não pôde ser comparada. {after.message}', 'degraded')
    changed = mv > 0.5
    return _result(changed, f'Botão "{btn}" enviado ao console. Mudança na tela: {mv} — '
                   + ('o console respondeu.' if changed else 'nenhuma reação visível (o botão pode não ter efeito nesta tela).'),
                   'streaming', {'motion': mv, 'button': btn})


def _discover(cfg: AgentConfig, body: dict, t: Target, r: ConsoleRuntime, discover_fn: Callable) -> dict:
    route = t.route
    platform = t.platform
    if route == 'internet_psn':
        reg = r.d.chiaki.registered(t.nickname) if t.nickname else None
        base = ('Rota PSN: o console não responde à descoberta pela internet (limitação do Remote Play). ')
        if reg:
            return _result(True, base + f'"{t.nickname}" está registrado no chiaki-ng; a conexão será feita pela PSN.', 'idle')
        if reg is None:
            return _result(False, base + 'Não foi possível consultar o chiaki-ng deste PC.', 'unavailable')
        return _result(False, base + f'"{t.nickname}" ainda não está registrado no chiaki-ng deste PC.', 'unavailable')
    host = t.host
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
    ident = t.identifier.lower()
    chosen = next((c for c in found if ident and (c.host_name or '').lower() == ident), found[0])
    others = [c.to_dict() for c in found if c is not chosen]
    msg = f"{chosen.host_name or 'Console'} ({chosen.host_type or platform}) encontrado em {chosen.address}: {chosen.state}"
    if chosen.system_version:
        msg += f' · sistema {chosen.system_version}'
    if ident and (chosen.host_name or '').lower() != ident:
        msg += f' · ATENÇÃO: nome diferente do cadastrado ("{t.identifier}")'
    return _result(True, msg + '.', 'idle', {'console': chosen.to_dict(), 'others': others})

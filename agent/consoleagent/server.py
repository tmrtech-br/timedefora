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
from .config import AgentConfig
from .gamepad import GamepadUnavailable
from .links import ChiakiLink, DirectLink, PsnLink
from .runtime import ConsoleRuntime, Deps, Target, target_from
from .psn_routes import create_psn_router
from .webrtc import WebRtcHub, WebRtcUnavailable, set_bitrate

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


DIRECT_METHODS = {'remote_play_direct', 'remote_play_native'}


def create_app(cfg: AgentConfig, discover_fn: Callable = discovery.discover, deps: Deps | None = None) -> FastAPI:
    """deps: dublês para testes (todos os consoles usam o mesmo link). Sem deps, cada console ganha o seu link:
    Remote Play direto (método remote_play_direct) ou chiaki-ng (demais)."""
    app = FastAPI(title='LocaPlay ConsoleAgent', version=VERSION, docs_url=None, redoc_url=None)
    expected = f'Bearer {cfg.api_to_agent_token}'.encode()
    runtimes: dict[str, ConsoleRuntime] = {}
    kinds: dict[str, str] = {}
    hub = WebRtcHub(
        cfg.ice_servers, int(cfg.video_max_width), bool(cfg.stream_audio), int(cfg.video_max_kbps),
        experimental_h264_passthrough=cfg.experimental_h264_passthrough,
    )
    app.state.webrtc = hub
    discover = deps.discover if deps else discover_fn

    def rt(console_id: str, body: dict) -> ConsoleRuntime:
        method = body.get('method')
        route = (body.get('target') or {}).get('route')
        if method == 'remote_play_native' and route == 'internet_psn':
            kind = 'psn'
        else:
            kind = 'direct' if method in DIRECT_METHODS else 'chiaki' if method else kinds.get(console_id, 'chiaki')
        r = runtimes.get(console_id)
        if r is not None and (deps is not None or kinds.get(console_id) == kind or not method):
            return r
        if r is not None:                                     # método do console mudou no painel: troca o link
            r.disconnect()
        if kind == 'psn':
            link = PsnLink()
        elif kind == 'direct':
            link = DirectLink()
        else:
            link = ChiakiLink(cfg.chiaki_path, hide_window=cfg.chiaki_hide_window)
        runtimes[console_id] = ConsoleRuntime(cfg, deps or Deps(link=link, discover=discover_fn))
        kinds[console_id] = kind
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
        if body.get('method') == 'remote_play_native' and (body.get('target') or {}).get('route') == 'internet_psn':
            target = body['target']
            if action != 'health' and target.get('platform_code', 'PS4') != 'PS4':
                return _error(501, 'psn_transport_pending', 'O transporte nativo via PSN está disponível para PS4.')
            if action in ('discover', 'pair', 'connect', 'console/prepare') and not target.get('psn_account_id'):
                return _error(422, 'psn_account_required', 'Vincule uma conta PSN ao PS4 antes de conectar.')
        if action == 'stream/webrtc':
            return await _webrtc(console_id, sid, body.get('offer') or {}, body)
        # As ações podem esperar (capturas de tela, preparação): fora do laço assíncrono do servidor.
        peer = hub.peers.get(console_id) if action == 'disconnect' else None
        res = await run_in_threadpool(handle, console_id, action, body)
        if action in ('input/revoke', 'stream/stop'):
            await hub.close(console_id, sid or None)          # vídeo acompanha o controle
        elif action == 'disconnect' and res['ok'] and peer is not None and hub.peers.get(console_id) is peer:
            await hub.close(console_id)
        return res

    async def _webrtc(console_id: str, sid: str, offer: dict, body: dict):
        r = rt(console_id, body)
        if not sid or sid != r.session_id:
            return _error(403, 'input_revoked', 'Vídeo só para a sessão ativa neste console.')
        if not r.streaming:
            # Console caiu (repouso, rede): dispara a reconexão em segundo plano (acorda + conecta); o navegador tenta de novo.
            t = target_from(cfg, console_id, body)
            await run_in_threadpool(r.start_job, t, 'connect', None, 0)
            return _result(False, 'O console está reconectando (acordando/conectando). Tente de novo em alguns segundos.', 'connecting')
        if offer.get('type') != 'offer' or not isinstance(offer.get('sdp'), str):
            return _error(400, 'invalid_offer', 'Oferta de vídeo inválida.')
        mk = body.get('video_max_kbps')                       # parâmetro do painel (sobrepõe o config.json)
        if isinstance(mk, (int, float)) and 500 <= mk <= 20000:
            set_bitrate(int(mk))
        try:
            answer, msg = await hub.answer(console_id, sid, offer, r.link, on_input=lambda cmd: r.input(sid, cmd))
        except WebRtcUnavailable as e:
            return _result(False, str(e), 'degraded')
        except Exception as e:  # nunca derrubar o agente por falha de negociação
            log.exception('falha ao negociar WebRTC')
            return _result(False, f'Falha ao iniciar o vídeo: {e.__class__.__name__}: {e}', 'error')
        return _result(True, msg, 'streaming', {'answer': answer})

    def handle(console_id: str, action: str, body: dict):
        if action == 'disconnect':
            current = runtimes.get(console_id)
            if current is not None and not current.disconnect_if_idle():
                return _result(False, 'Há uma sessão de jogo em andamento neste console.', 'streaming')
            return _result(True, 'Conexão com o console encerrada e controle removido.', 'stopped')
        if action == 'discover-lan':
            target = body.get('target')
            platform = target.get('platform_code') if isinstance(target, dict) else None
            if platform not in ('PS4', 'PS5'):
                return _result(False, 'Selecione um console PS4 ou PS5.')
            try:
                found = discover(None, platform, cfg.discovery_timeout_seconds)
            except OSError:
                return _result(False, 'O agente não conseguiu pesquisar na rede local.')
            return _result(True, 'Pesquisa na rede local concluída.', data={
                'devices': [{'address': item.address, 'name': item.host_name or ''} for item in found],
            })
        t = target_from(cfg, console_id, body)
        r = rt(console_id, body)
        sid = str(body.get('session_id') or '')

        if action == 'health':
            return _health(cfg, r)
        if action == 'discover':
            if isinstance(r.link, PsnLink):
                return _job(r.start_job(t, 'connect'))
            return _discover(cfg, body, t, r, discover)
        if action == 'metrics':
            fps = hub.fps(console_id)            # quadros reais enviados ao navegador (medidos), senão ausente
            return {'metrics': {'fps': fps} if fps is not None else {}}
        if action == 'pair':
            if isinstance(r.link, PsnLink):
                return _job(r.start_job(t, 'connect'))
            ok, msg = r.link.pair(t, str(body.get('code') or ''))
            return _result(ok, msg, 'idle' if ok else 'unavailable')
        if action in ('connect', 'console/prepare'):
            if action == 'connect' and body.get('poll_only') is True:
                return _job(r.job) if r.job else _result(False, 'A tentativa de conexão não está mais disponível.', 'stopped')
            return _job(r.start_job(t, 'prepare' if action == 'console/prepare' else 'connect', body.get('game')))
        if action == 'script/test':
            # Teste do roteiro pelo painel: nunca com jogador no console.
            if r.session_id:
                return _error(409, 'session_active', 'Há uma sessão de jogo em andamento neste console.')
            game = dict(body.get('game') or {})
            game['force'] = True
            return _job(r.start_job(t, 'prepare', game))
        if action == 'script/status':
            return _job(r.job) if r.job else _result(False, 'Nenhum teste de roteiro em andamento.', 'stopped')
        if action == 'screen/snapshot':
            return _snapshot(t, r)
        if action == 'secondscreen/pair':
            from .runtime import Fail, System
            try:
                return _result(True, System(t, discover).pair(str(body.get('pin') or '')), 'idle')
            except Fail as e:
                return _result(False, str(e), 'error')
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
            if sid and r.session_id and sid != r.session_id:
                return _result(True, 'Sessão já encerrada neste console.', 'streaming' if r.streaming else 'stopped')
            if body.get('standby') and hasattr(r.link, 'standby'):
                ok, msg = r.standby()       # a API decide: hibernar ao fim e sem reserva próxima
                return _result(True, f'Sessão encerrada no console. {msg}', 'stopped', {'standby': ok})
            r.revoke(sid or None)
            if cfg.stop_chiaki_after_session:
                r.disconnect()
            return _result(True, 'Sessão encerrada no console.', 'idle' if r.streaming else 'stopped')
        if action == 'test/video-audio':
            return _test_video_audio(r)
        if action == 'test/controls':
            return _test_controls(cfg, r)
        return _error(404, 'unknown_action', f'Ação desconhecida: {action}')

    app.include_router(create_psn_router(cfg.api_to_agent_token, discover=discover))
    return app


# ---------------------------------------------------------------- ações
def _health(cfg: AgentConfig, r: ConsoleRuntime) -> dict:
    link = r.link
    direct = DirectLink()
    direct_ok = direct.available
    chiaki_ok = ChiakiLink(cfg.chiaki_path).available
    mode = 'Remote Play pela PSN' if isinstance(link, PsnLink) else ('Remote Play direto' if link.kind == 'direct' else 'chiaki-ng')
    parts = [f'ConsoleAgent {VERSION} online',
             f'modo deste console: {mode}',
             'Remote Play direto: ' + ('disponível' if direct_ok else direct.unavailable_reason),
             'chiaki-ng encontrado' if chiaki_ok else f'chiaki-ng NÃO encontrado em {cfg.chiaki_path}',
             'vídeo no navegador: ' + ('ok' if _has('aiortc') else 'aiortc NÃO instalado')]
    if link.kind == 'chiaki':
        parts += ['controle virtual: ' + ('vgamepad instalado' if _has('vgamepad') else 'vgamepad NÃO instalado'),
                  'medição de áudio: ' + ('ok' if _has('pycaw') else 'pycaw NÃO instalado')]
    if not cfg.consoles:
        parts.append('nenhum console em "consoles" no config.json')
    j = r.job
    if j:   # andamento da última conexão/preparação (diagnóstico sem disparar nova conexão)
        parts.append(f'última conexão: {j.state} há {int(time.monotonic() - j.started)}s — {j.step}'
                     + (f': {j.message}' if j.message else ''))
    return _result(True, '. '.join(parts) + '.', 'streaming' if r.streaming else None,
                   {'agent_version': VERSION, 'mode': link.kind, 'direct_available': direct_ok, 'chiaki_found': chiaki_ok,
                    'vgamepad': _has('vgamepad'), 'aiortc': _has('aiortc'), 'pycaw': _has('pycaw'),
                    'consoles_configured': sorted(cfg.consoles)})


def _job(j) -> dict:
    if j.state == 'ok':
        return _result(True, j.message, 'streaming', {'step': j.step, **(j.data or {})})
    if j.state == 'failed':
        return _result(False, j.message, 'error', {'step': j.step, **(j.data or {})})
    secs = int(time.monotonic() - j.started)
    return _result(False, f'Em andamento ({secs}s): {j.step}…', 'connecting', {'step': j.step, 'running': True})


def _snapshot(t, r: ConsoleRuntime) -> dict:
    """Imagem atual do console (tons de cinza, PNG) e o texto lido nela, para montar o roteiro no painel."""
    if not r.streaming:
        if r.session_id is None:
            r.start_job(t, 'connect', None, 0)                   # conecta em segundo plano; o painel tenta de novo
        return _result(False, 'Conectando ao console para capturar a tela. Tente de novo em alguns segundos.', 'connecting')
    f = r.link.frame()
    if f.image is None:
        return _result(False, f'Sem imagem do console: {f.message}', 'degraded')
    from .vision import VisionUnavailable, png_base64, read_text
    try:
        lines, ocr = read_text(f.image), None
    except VisionUnavailable as e:
        lines, ocr = [], str(e)
    except Exception as e:  # OCR é auxiliar: a captura vale mesmo sem ele
        lines, ocr = [], f'Falha na leitura de texto: {e}'
    running = None
    try:                                             # jogo aberto segundo o próprio console (só na rede local)
        from .runtime import System
        code, name = System(t).running_app()
        running = {'title_id': code, 'name': name}
    except Exception:
        pass
    return _result(True, f.message, 'streaming', {'png': png_base64(f.image), 'width': f.image.width,
                                                  'height': f.image.height, 'text': lines, 'ocr_error': ocr,
                                                  'running_app': running})


def _test_video_audio(r: ConsoleRuntime) -> dict:
    if not r.streaming:
        return _result(False, 'Console não conectado: use "Conectar" (ou aguarde a preparação) antes do teste.', 'stopped')
    a = r.link.frame()
    time.sleep(0.6)
    b = r.link.frame()
    mv = None
    if a.ok and b.ok:
        from .media import motion
        mv = motion(a, b)
    peak, amsg = r.link.audio_peak(1.5)
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
        return _result(False, 'Controle ativo e console conectado, mas a resposta do console não foi medida. '
                       'Defina "control_test_button" no config.json (botão inofensivo na tela atual, ex.: "dpad_right" '
                       'no menu inicial) e teste de novo.', 'streaming')
    before = r.link.frame()
    pad.press(btn, 0.15)
    time.sleep(0.9)
    after = r.link.frame()
    # Direcional: aperta o lado oposto para devolver a seleção da tela ao lugar (o teste não deixa rastro).
    back = {'dpad_down': 'dpad_up', 'dpad_up': 'dpad_down', 'dpad_left': 'dpad_right', 'dpad_right': 'dpad_left'}.get(btn)
    if back:
        pad.press(back, 0.15)
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
        reg = r.link.registered(t)
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

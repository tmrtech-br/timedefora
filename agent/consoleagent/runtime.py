"""Estado e orquestração por console: preparar (acordar + conectar + abrir o jogo), sessão do jogador e testes.

Operações demoradas (acordar e conectar levam de 20 a 60 s) rodam em segundo plano; cada chamada da API
(limite de 5 s) recebe o andamento. A API repete a chamada até o prazo de tolerância.
Nenhum resultado é simulado: sucesso só com imagem real do console (captura da janela ou quadro decodificado).
A conversa com o console fica num "link" (links.py): chiaki-ng ou Remote Play direto.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import discovery
from .chiaki import ChiakiError
from .config import AgentConfig
from .gamepad import GamepadUnavailable
from .links import LinkError

log = logging.getLogger('consoleagent.runtime')
DIRECT_ROUTES = ('lan', 'internet_port_forward')
PSN_NO_SESSION_SECONDS = 45      # chiaki-ng aberto sem sessão nenhuma após isso = tentativa perdida
PSN_RETRY_GAP_SECONDS = 15


@dataclass
class Target:
    console_id: str
    route: str
    host: str | None
    platform: str
    identifier: str
    nickname: str
    regist_key: str = ''
    passcode: str = ''
    profile: str = ''
    psn_gui_steps: list = field(default_factory=list)
    games: dict = field(default_factory=dict)
    psn_user: str = ''              # Remote Play direto: conta PSN usada (vazio = a registrada no console)
    psn_account_id: str = ''
    mac: str = ''
    resolution: str = '720p'
    fps: int = 30
    bitrate_kbps: int = 0           # 0 = padrão do método (Remote Play pela PSN usa 6 Mbps)
    codec: str = 'h264'
    local_host: str = ''            # IP do console na rede local (abrir/confirmar o jogo pelo sistema, mesmo na rota PSN)

    @property
    def direct(self) -> bool:
        return self.route in DIRECT_ROUTES


def target_from(cfg: AgentConfig, console_id: str, body: dict) -> Target:
    """Junta o que a API envia (rota/endereço/qualidade) com o que só o agente guarda (chave, senha, roteiros)."""
    t = body.get('target') or {}
    settings = body.get('settings') or {}
    route = t.get('route') or settings.get('network_route') or body.get('route') or 'lan'
    ident = (t.get('console_identifier') or settings.get('console_identifier') or body.get('console_identifier') or '').strip()
    entry = cfg.consoles.get(ident) or cfg.consoles.get(console_id) or {}
    host = entry.get('host') or t.get('host') or body.get('host')
    if not host and route == 'internet_port_forward':
        host = settings.get('public_host')
    try:
        fps = int(t.get('fps') or settings.get('fps') or 30)
    except (TypeError, ValueError):
        fps = 30
    try:
        bitrate = int(t.get('bitrate_kbps') or settings.get('bitrate_kbps') or 0)
    except (TypeError, ValueError):
        bitrate = 0
    return Target(console_id=console_id, route=route, host=(host or '').strip() or None,
                  platform=(t.get('platform_code') or body.get('platform_code') or entry.get('platform') or 'PS4'),
                  identifier=ident, nickname=(entry.get('nickname') or ident).strip(),
                  regist_key=str(entry.get('regist_key') or ''), passcode=str(entry.get('passcode') or ''),
                  profile=str(entry.get('profile') or ''), psn_gui_steps=list(entry.get('psn_gui_steps') or []),
                  games=dict(entry.get('games') or {}), psn_user=str(entry.get('psn_user') or ''),
                  psn_account_id=str(t.get('psn_account_id') or settings.get('psn_account_id') or ''),
                  mac=str(entry.get('mac') or ''), resolution=str(t.get('resolution') or settings.get('resolution') or '720p'),
                  fps=fps, codec=str(t.get('codec') or settings.get('codec') or 'h264'), bitrate_kbps=max(0, bitrate),
                  local_host=str(entry.get('host') or t.get('local_host') or (host if route in DIRECT_ROUTES else '') or '').strip())


@dataclass
class Deps:
    """Dependências trocáveis (os testes usam dublês; nada de hardware)."""
    link: object
    discover: Callable = discovery.discover
    wake: Callable = discovery.wakeup
    sleep: Callable = time.sleep


class Fail(Exception):
    pass


@dataclass
class Job:
    kind: str                      # connect | prepare
    game_slug: str | None
    state: str = 'running'         # running | ok | failed
    step: str = 'iniciando'
    message: str = ''
    started: float = field(default_factory=time.monotonic)
    data: dict = field(default_factory=dict)        # ex.: jogo reconhecido (title ID, nome)


class ConsoleRuntime:
    def __init__(self, cfg: AgentConfig, deps: Deps):
        self.cfg, self.d = cfg, deps
        self.pad = None
        self.session_id: str | None = None
        self.job: Job | None = None
        self.ready_game: str | None = None       # jogo aberto pela última preparação bem-sucedida
        self.woke = False                        # esta preparação acordou o console (rede local)
        self._lock = threading.RLock()

    @property
    def link(self):
        return self.d.link

    # ------------------------------------------------------------ estado
    @property
    def streaming(self) -> bool:
        return self.link.running

    def ensure_pad(self):
        if self.pad is None:
            self.pad = self.link.new_pad()
        return self.pad

    def _drop_pad(self):
        if self.pad is not None:
            try:
                self.pad.close()
            except Exception:
                pass
            self.pad = None

    # ------------------------------------------------------------ jobs
    def start_job(self, t: Target, kind: str, game: dict | None = None, wait: float = 3.0) -> Job:
        slug = (game or {}).get('slug')
        with self._lock:
            j = self.job
            reusable = j and j.kind in (kind, 'prepare') and j.game_slug == slug
            if j and j.state == 'running':
                return j                                           # já em andamento
            force = bool((game or {}).get('force'))                # teste do roteiro: sempre roda de novo
            if reusable and j.state == 'ok' and self.streaming and not force:
                return j                                           # pronto (idempotente)
            if (kind == 'prepare' and not force and self.streaming and self.ready_game is not None
                    and slug == self.ready_game):
                self.job = Job(kind, slug, 'ok', 'pronto', 'Console já conectado com este jogo aberto.')
                return self.job
            self.job = j = Job(kind, slug)
        th = threading.Thread(target=self._run, args=(t, j, game), daemon=True, name=f'job-{kind}-{t.console_id[:8]}')
        th.start()
        th.join(wait)                                              # resposta rápida quando já está tudo pronto
        return j

    def _run(self, t: Target, j: Job, game: dict | None) -> None:
        try:
            j.message = self._bringup(t, j)
            if j.kind == 'prepare':
                j.message += ' ' + self._open_game(t, j, game or {})
            j.state, j.step = 'ok', 'pronto'
        except (Fail, ChiakiError, LinkError, GamepadUnavailable, ValueError, OSError) as e:
            j.message = f'{j.step}: {e}'
            log.warning('preparação falhou (%s): %s', t.identifier or t.console_id, j.message)
            self._release_after_failure()
            j.state = 'failed'
        except Exception as e:  # nunca derrubar o agente
            j.message = f'{j.step}: erro inesperado {e.__class__.__name__}: {e}'
            log.exception('erro inesperado na preparação')
            self._release_after_failure()
            j.state = 'failed'

    def _release_after_failure(self) -> None:
        """Conexão que falhou não pode ficar meio aberta: o console recusaria a próxima ("sessão em uso")."""
        if self.session_id or self.link.kind == 'chiaki' or self.streaming:
            return                      # jogador ligado, chiaki-ng (processo próprio) ou conexão boa (ex.: só o roteiro falhou)
        try:
            self._drop_pad()
            self.link.stop()
        except Exception as e:
            log.warning('falha ao liberar a conexão depois do erro: %s', e)

    def _bringup(self, t: Target, j: Job) -> str:
        link, cfg = self.link, self.cfg
        j.step = 'verificando a conexão do agente'
        if not link.available:
            raise Fail(link.unavailable_reason or 'Forma de conexão indisponível neste agente.')
        if link.kind == 'chiaki' and not t.nickname:
            raise Fail('Identificação do console não informada (cadastro do console no painel).')
        if self.streaming:
            j.step = 'conferindo a imagem'
            f = link.frame()
            if f.ok:
                self.ensure_pad()
                return f'Console já conectado. {f.message}'
            self._drop_pad()
            link.stop()                                            # conectado sem imagem: reinicia
        # Conexão nova: o console pode ter hibernado e acordado no menu. O jogo aberto por uma preparação anterior
        # não vale mais; o roteiro de abertura precisa rodar de novo.
        self.ready_game = None
        self.woke = False
        notes: list[str] = []
        if link.kind == 'chiaki':                                  # no modo direto o registro é conferido ao conectar
            reg = link.registered(t)
            if reg is False:
                raise Fail(f'"{t.nickname}" não está registrado no chiaki-ng deste PC. Registre o console no chiaki-ng '
                           '(mesmo apelido do cadastro) e tente de novo.')
            if reg is None:
                notes.append('(não foi possível listar os consoles do chiaki-ng)')

        if t.direct:
            if not t.host:
                raise Fail('Endereço do console não informado (IP na rede local ou IP público/DDNS).')
            notes.append(self._wake(t, j))
        else:
            notes.append('Rota PSN: o console deve estar ligado ou em repouso com o Remote Play ativado.')

        self._drop_pad()
        if link.kind == 'chiaki':
            j.step = 'criando o controle virtual'
            self.ensure_pad()                                      # o chiaki-ng precisa ver o controle ao abrir
        # Pela PSN a conexão (descoberta pela Sony + atravessar os roteadores) leva bem mais que na rede local, e a
        # primeira tentativa costuma falhar quando o console está em repouso (ele acorda durante ela): tenta de novo.
        psn = t.route == 'internet_psn'
        attempts = max(1, int(cfg.psn_connect_attempts)) if psn else 1
        wait = float(cfg.stream_timeout_seconds) * (2 if psn else 1)
        why = ''
        for attempt in range(1, attempts + 1):
            j.step = 'conectando ao console' + (f' (tentativa {attempt} de {attempts})' if attempts > 1 else '')
            try:
                started = link.start(t, self.d.sleep)
            except LinkError as e:
                # Pela PSN o próprio link negocia até a 1ª imagem: a falha dele também precisa de nova tentativa
                # (console em repouso acorda durante a 1ª e quase sempre a perde).
                if not psn or attempt >= attempts or not getattr(e, 'retryable', True):
                    raise
                why = str(e)
                log.info('rota PSN: tentativa %s falhou (%s); tentando de novo', attempt, why)
                link.stop()
                self.d.sleep(PSN_RETRY_GAP_SECONDS)
                continue
            if started:
                notes.append(started)
            if link.kind != 'chiaki':
                j.step = 'criando o controle'
                self.ensure_pad()                                  # direto: o controle pertence à sessão
            j.step = 'aguardando a imagem do console' + (f' (tentativa {attempt} de {attempts})' if attempts > 1 else '')
            deadline = time.monotonic() + wait
            last = None
            while time.monotonic() < deadline:
                if not link.running:
                    why = 'A conexão com o console caiu antes de transmitir. ' + (
                        (link.stream_hint() if psn and hasattr(link, 'stream_hint') else '') or link.log_tail() or 'Veja agent/logs.')
                    break
                if psn and getattr(link, 'stalled', None) and link.stalled(PSN_NO_SESSION_SECONDS):
                    why = (f'O chiaki-ng não iniciou a conexão em {PSN_NO_SESSION_SECONDS} s (ficou no menu ou em '
                           '"Waiting for console"). Confira no chiaki-ng se "Main PS4 Console" aparece na lista da PSN.')
                    break
                last = link.frame()
                if last.ok:
                    if attempt > 1:
                        notes.append(f'Conectou na tentativa {attempt}.')
                    return ' '.join(x for x in [*notes, f'Conectado. {last.message}'] if x)
                self.d.sleep(2)
            else:
                why = 'Sem imagem do console dentro do prazo. ' + (last.message if last else '')
            if attempt < attempts:
                log.info('rota PSN: tentativa %s falhou (%s); tentando de novo', attempt, why)
                link.stop()
                # A PSN leva alguns segundos para apagar a sessão anterior; reabrir logo dá "Holepunch session was
                # deleted on PSN server" / "Failed to create session".
                self.d.sleep(PSN_RETRY_GAP_SECONDS)
        raise Fail(why)

    def _wake(self, t: Target, j: Job) -> str:
        j.step = 'procurando o console'
        found = self.d.discover(t.host, t.platform, self.cfg.discovery_timeout_seconds)
        state = found[0].state if found else None
        if state == 'ligado':
            return 'Console ligado.'
        key = self.link.regist_key(t)
        if not key:
            if state == 'em repouso':
                raise Fail('Console em repouso e sem chave de registro para acordá-lo (pareie o console ou preencha "regist_key").')
            raise Fail(f'Console não respondeu em {t.host} (desligado, fora da rede ou porta bloqueada).')
        j.step = 'acordando o console'
        self.d.wake(t.host, key, t.platform)
        deadline = time.monotonic() + float(self.cfg.wake_timeout_seconds)
        while time.monotonic() < deadline:
            self.d.sleep(3)
            found = self.d.discover(t.host, t.platform, self.cfg.discovery_timeout_seconds)
            if found and found[0].state == 'ligado':
                self.d.sleep(5)                                  # o Remote Play sobe alguns segundos depois
                self.woke = True
                return 'Console acordado.'
        raise Fail('O console não ligou após o comando de acordar (confira "Ativar ligar o console pela rede" e a chave de registro).')

    def _open_game(self, t: Target, j: Job, game: dict) -> str:
        slug, title = game.get('slug'), game.get('title') or game.get('slug') or 'jogo'
        launch = game.get('launch') if isinstance(game.get('launch'), dict) else {}
        if game.get('title_id') or game.get('detect'):
            return self._standard_open(t, j, game, title)
        # Roteiro do painel (proprietário/equipe) tem prioridade; senão o do config.json deste agente.
        steps = list(launch.get('steps') or []) or (t.games.get(slug) if slug else None)
        source = 'do painel' if launch.get('steps') else 'do agente'
        j.step = f'abrindo "{title}"'
        if not steps:
            if self.cfg.require_game_script:
                raise Fail(f'Sem roteiro para abrir "{title}": cadastre o roteiro no menu Roteiros do painel '
                           f'(ou games.{slug} no config.json do agente).')
            self.ready_game = slug
            return f'Jogo "{title}": sem roteiro de abertura configurado; confirme na tela que ele está aberto.'
        refs = {}
        for name, data in (launch.get('images') or {}).items():
            try:
                from .vision import decode_reference
                refs[name] = decode_reference(name, data)
            except Exception as e:
                raise Fail(f'Imagem de referência "{name}" inválida: {e}')
        pad = self.ensure_pad()
        screen = Screen(self.link, refs, System(t, self.d.discover))

        def progress(i: int, raw: str) -> None:
            j.step = f'abrindo "{title}" — passo {i} de {len(steps)}: {raw}'

        run_pad_steps(pad, steps, self.d.sleep, screen=screen, on_step=progress)
        j.step = f'conferindo "{title}"'
        self.d.sleep(2)
        f = self.link.frame()
        if not f.ok:
            raise Fail(f'Após o roteiro de "{title}" a imagem sumiu: {f.message}')
        self.ready_game = slug
        checked = ' Jogo confirmado na tela.' if screen.confirmed else ' (roteiro sem confirmação visual do jogo)'
        return f'Roteiro de abertura de "{title}" executado ({len(steps)} passos, roteiro {source}).{checked}'

    def _standard_open(self, t: Target, j: Job, game: dict, title: str) -> str:
        """Fluxo padrão (sem roteiro): estado pela presença PSN e/ou DDP, perfil → menu → ícone do jogo → confirmação."""
        from .presence import PsnPresence, StateReader
        from .standard_flow import FlowError, open_game
        lan = System(t, self.d.discover) if (t.local_host or t.direct) else None
        state = StateReader(PsnPresence(t.psn_account_id) if t.psn_account_id else None, lan)

        def progress(step: str) -> None:
            j.step = f'"{title}": {step}'

        trace = None
        if game.get('force'):                    # teste pelo painel: guarda a tela depois de cada toque (agent/logs/flow-*)
            from pathlib import Path
            folder = Path(__file__).resolve().parents[1] / 'logs' / time.strftime('flow-%Y%m%d-%H%M%S')
            folder.mkdir(parents=True, exist_ok=True)
            count = [0]

            def trace(label: str) -> None:
                count[0] += 1
                try:
                    f = self.link.frame()
                    if f.image is not None:
                        f.image.save(folder / f'{count[0]:02d}-{time.strftime("%H%M%S")}-{label}.png')
                except Exception:
                    pass
            log.info('diagnóstico do fluxo em %s', folder)
        try:
            settle = float(game.get('settle_seconds') or self.cfg.game_settle_seconds)
            r = open_game(self.ensure_pad(), state, lambda: self.link.frame().ok, str(game.get('title_id') or ''),
                          woke=self.woke, detect=bool(game.get('detect')), sleep=self.d.sleep, progress=progress,
                          settle=0 if game.get('detect') else settle, trace=trace,
                          expected_name=str(game.get('title') or '') if game.get('detect') else '')
        except FlowError as e:
            j.data = {'seen': e.seen}
            raise Fail(str(e))
        j.data = {'title_id': r.title_id, 'title_name': r.title_name, 'path': r.path, 'tile': r.tile, 'seen': r.seen or []}
        if not game.get('detect'):
            self.ready_game = game.get('slug')
        return f'{r.message} Caminho: {r.path}. Jogo confirmado pelo console.'

    # ------------------------------------------------------------ sessão do jogador
    def start_session(self, session_id: str) -> tuple[bool, str]:
        with self._lock:
            if not self.streaming:
                return False, 'Console não está conectado (a preparação não terminou).'
            # A conexão com o console basta: tela preta/carregando/aviso aberto no momento não pode travar o jogador
            # (a imagem foi validada na preparação; aqui ela é só informativa).
            f = self.link.frame()
            pad = self.ensure_pad()
            pad.reset()
            self.session_id = session_id
            return True, f'Sessão liberada. {f.message}'

    def input(self, session_id: str, command: dict) -> None:
        if not session_id or session_id != self.session_id:
            raise PermissionError('Controle revogado ou sessão diferente da ativa neste console.')
        self.ensure_pad().apply(command)

    def revoke(self, session_id: str | None = None) -> None:
        if session_id and self.session_id and session_id != self.session_id:
            return                                                   # pedido de outra sessão: não afeta a atual
        if self.session_id:
            # O jogador pode ter saído do jogo (menu, outro app): a próxima preparação roda o roteiro de novo.
            self.ready_game = None
        self.session_id = None
        if self.pad is not None:
            try:
                self.pad.reset()
            except Exception as e:
                log.warning('falha ao soltar os controles: %s', e)

    def disconnect(self) -> None:
        self.revoke()
        self._drop_pad()
        self.link.stop()
        self.ready_game, self.job = None, None

    def disconnect_if_idle(self) -> bool:
        with self._lock:
            if self.session_id:
                return False
            self.disconnect()
            return True

    def standby(self) -> tuple[bool, str]:
        """Fim de sessão com hibernação: solta os controles, pede repouso ao console e encerra a conexão."""
        if self.job and self.job.state == 'running':
            return False, 'Conexão/preparação em andamento: o console não foi colocado em repouso.'
        self.revoke()
        self._drop_pad()
        fn = getattr(self.link, 'standby', None)
        ok = False
        if fn is not None and self.streaming:
            try:
                ok = bool(fn())
            except Exception as e:  # repouso é melhor esforço: nunca impede o encerramento
                log.warning('falha ao pedir repouso ao console: %s', e)
        self.link.stop()
        self.ready_game, self.job = None, None
        if fn is None:
            return False, 'Este método de conexão não coloca o console em repouso; conexão encerrada.'
        return ok, 'Console colocado em repouso.' if ok else 'O console não confirmou o repouso; conexão encerrada.'


class System:
    """O que o próprio PS4/PS5 informa na rede local: jogo aberto (descoberta UDP) e abrir jogo pelo código (Second Screen)."""

    def __init__(self, t: Target, discover: Callable = discovery.discover):
        self.t, self.discover = t, discover
        self._host: str | None = None

    def host(self) -> tuple[str, str]:
        """(IP, ID do console) na rede local: o IP cadastrado ou, sem ele, o console com o mesmo nome na rede."""
        if self._host:
            return self._host, self._id
        names = {n.lower() for n in (self.t.nickname, self.t.identifier) if n}
        if self.t.local_host:
            found = self.discover(self.t.local_host, self.t.platform, 3.0)
        else:
            found = [c for c in self.discover(None, self.t.platform, 3.0) if (c.host_name or '').lower() in names]
        if not found:
            raise Fail('O console não respondeu na rede local deste agente. Abrir/confirmar o jogo pelo sistema só funciona '
                       'com o agente na mesma rede do console (informe o IP local do console no cadastro).')
        self._host, self._id = found[0].address, found[0].host_id or found[0].address
        return self._host, self._id

    def running_app(self) -> tuple[str, str]:
        """(código, nome) do jogo aberto agora; vazios na tela inicial."""
        host, _ = self.host()
        found = self.discover(host, self.t.platform, 3.0)
        raw = found[0].raw if found else {}
        return raw.get('running-app-titleid', ''), raw.get('running-app-name', '')

    def is_running(self, wanted: str) -> bool:
        from .vision import contains_text
        code, name = self.running_app()
        w = wanted.strip()
        return bool(code) and (code.upper() == w.upper() or contains_text(name, w))

    def boot(self, title_id: str) -> None:
        if discovery.family(self.t.platform) != 'PS4':
            raise Fail('Abrir o jogo pelo código está disponível só para PS4; no PS5 use os passos de navegação.')
        from .secondscreen import SecondScreenError, Session, credential_for
        host, console_id = self.host()
        try:
            with Session(host, credential_for(console_id)) as s:
                s.boot(title_id)
        except SecondScreenError as e:
            raise Fail(str(e))

    def pair(self, pin: str) -> str:
        if discovery.family(self.t.platform) != 'PS4':
            raise Fail('O registro de aplicativo (PIN) é usado só no PS4.')
        from .secondscreen import SecondScreenError, Session, credential_for
        host, console_id = self.host()
        try:
            Session(host, credential_for(console_id), pin=pin.strip()).open().close()
        except SecondScreenError as e:
            raise Fail(str(e))
        return f'Agente registrado no console ({host}). Os passos "abrir pelo código" já podem ser usados.'


class Screen:
    """O que está na tela agora: texto (OCR) e imagens de referência. Usado pelos passos visuais do roteiro."""

    def __init__(self, link, refs: dict | None = None, system: System | None = None):
        self.link, self.refs, self.system = link, refs or {}, system
        self.confirmed = False                  # algum passo de espera/confirmação visual passou
        self.last_text = ''

    def _image(self):
        f = self.link.frame()
        if f.image is None:
            raise Fail(f'Sem imagem do console para conferir a tela: {f.message}')
        return f.image

    def has_text(self, wanted: str) -> bool:
        from .vision import VisionUnavailable, contains_text, read_text
        try:
            lines = read_text(self._image())
        except VisionUnavailable as e:
            raise Fail(str(e))
        self.last_text = ' | '.join(lines)[:300]
        return contains_text(' '.join(lines), wanted)

    def has_image(self, name: str) -> bool:
        from .vision import MATCH_THRESHOLD, match_score
        ref = self.refs.get(name)
        if ref is None:
            raise Fail(f'Imagem de referência "{name}" não cadastrada neste roteiro.')
        return match_score(self._image(), ref) >= MATCH_THRESHOLD

    def seen(self, kind: str, target: str) -> bool:
        return self.has_text(target) if kind == 'text' else self.has_image(target)

    def describe(self, kind: str, target: str) -> str:
        what = f'o texto "{target}"' if kind == 'text' else f'a imagem "{target}"'
        shown = f' Texto na tela: {self.last_text}.' if kind == 'text' and self.last_text else ''
        return what + shown


def _visual(screen: Screen | None, raw: str) -> Screen:
    if screen is None:
        raise Fail(f'Passo "{raw}" precisa da leitura de tela (indisponível neste roteiro).')
    return screen


def run_pad_steps(pad, steps: list, sleep=time.sleep, screen: Screen | None = None, on_step=None) -> None:
    """Roteiro de abertura. Passos (um por linha):
    - botão: "ps", "cross", "dpad_right"…; "wait:SEGUNDOS"; "hold:BOTÃO:SEGUNDOS"
    - "wait_text:SEGUNDOS:TEXTO" / "wait_image:SEGUNDOS:NOME" — espera aparecer na tela (senão falha)
    - "press_until_text:BOTÃO:MÁX:TEXTO" / "press_until_image:BOTÃO:MÁX:NOME" — aperta até aparecer (navegar até o jogo)
    - "press_if_text:BOTÃO:TEXTO" / "press_if_image:BOTÃO:NOME" — aperta só se estiver na tela (ex.: "Seja bem-vindo")
    - "boot:CUSA00000" — abre o jogo pelo código (PS4 na rede local; agente registrado com PIN)
    - "wait_app:SEGUNDOS:CUSA00000" — o próprio console confirma que o jogo (código ou nome) está aberto
    """
    for i, raw in enumerate(steps, 1):
        text = str(raw).strip()
        s = text.lower()
        if on_step:
            on_step(i, text)
        if s.startswith('wait:'):
            sleep(float(s.split(':', 1)[1]))
        elif s.startswith('hold:'):
            _, name, secs = s.split(':')
            pad.press(name, float(secs))
        elif s.startswith(('wait_text:', 'wait_image:')):
            kind = 'text' if s.startswith('wait_text:') else 'image'
            _, secs, target = text.split(':', 2)
            sc = _visual(screen, text)
            deadline = time.monotonic() + float(secs)
            while not sc.seen(kind, target):
                if time.monotonic() >= deadline:
                    raise Fail(f'Não apareceu {sc.describe(kind, target)} em {secs} s.')
                sleep(1.0)
            sc.confirmed = True
        elif s.startswith(('press_until_text:', 'press_until_image:')):
            kind = 'text' if s.startswith('press_until_text:') else 'image'
            _, button, limit, target = text.split(':', 3)
            sc = _visual(screen, text)
            presses = 0
            while not sc.seen(kind, target):
                if presses >= int(limit):
                    raise Fail(f'Não encontrou {sc.describe(kind, target)} após {limit} toques em "{button}".')
                pad.press(button.lower())
                presses += 1
                sleep(1.0)
            sc.confirmed = True
        elif s.startswith('boot:'):
            sc = _visual(screen, text)
            if sc.system is None:
                raise Fail('Abrir pelo código exige o console na rede local do agente.')
            sc.system.boot(text.split(':', 1)[1])
        elif s.startswith('wait_app:'):
            _, secs, target = text.split(':', 2)
            sc = _visual(screen, text)
            if sc.system is None:
                raise Fail('Confirmar pelo sistema exige o console na rede local do agente.')
            deadline = time.monotonic() + float(secs)
            while not sc.system.is_running(target):
                if time.monotonic() >= deadline:
                    code, name = sc.system.running_app()
                    now = f'{name} ({code})' if code else 'nenhum jogo (tela inicial)'
                    raise Fail(f'O console não confirmou "{target}" aberto em {secs} s. Aberto agora: {now}.')
                sleep(2.0)
            sc.confirmed = True
        elif s.startswith(('press_if_text:', 'press_if_image:')):
            kind = 'text' if s.startswith('press_if_text:') else 'image'
            _, button, target = text.split(':', 2)
            if _visual(screen, text).seen(kind, target):
                pad.press(button.lower())
                sleep(1.0)
        else:
            pad.press(s)
        sleep(0.4)

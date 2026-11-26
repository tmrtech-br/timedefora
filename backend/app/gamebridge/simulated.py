"""Adaptador SIMULADO — ambiente de desenvolvimento e testes contratuais.
Não conecta a nenhum console. Toda resposta tem simulated=True e métricas None."""
import threading

from .contract import (AdapterError, AdapterResult, ConsoleRef, ConsoleStreamingAdapter, StreamMetrics, StreamState,
                       validate_command)


class SimulatedAdapter(ConsoleStreamingAdapter):
    method = 'simulated'
    label = 'Simulador (sem hardware)'
    simulated = True
    operational = False

    def __init__(self):
        self._lock = threading.Lock()
        self._streams: dict[str, str] = {}          # session_id -> console_id
        self._revoked: set[str] = set()
        self.inputs: list[tuple[str, dict]] = []    # histórico para testes contratuais
        self.fail_health: set[str] = set()          # consoles com falha injetada (testes)
        self.fail_prepare: set[str] = set()         # consoles que "não ficam prontos" (testes)

    def _r(self, msg: str, state=None, **data) -> AdapterResult:
        return AdapterResult(ok=True, simulated=True, message=msg, state=state, data=data)

    def prepare_console(self, ref, game):
        if ref.console_id in self.fail_prepare:
            raise AdapterError('prepare_failed', 'Falha injetada: o console simulado não abriu o jogo.')
        return self._r(f"Console preparado: {game.get('title', 'jogo')} aberto (SIMULADO).", StreamState.IDLE)

    def discover_console(self, ref):
        return self._r('Console simulado encontrado.', console_identifier=f'SIM-{ref.console_id[:8]}')

    def pair_console(self, ref, code):
        if code is not None and (len(code) != 8 or not code.isdigit()):
            raise AdapterError('pair_failed', 'Código de pareamento simulado deve ter 8 dígitos.')
        return self._r('Pareamento simulado concluído.', secret_reference=f'sim-vault://{ref.console_id}')

    def connect(self, ref):
        if ref.console_id in self.fail_health:
            raise AdapterError('agent_unreachable', 'Falha injetada no simulador.')
        return self._r('Conexão simulada estabelecida.', StreamState.IDLE)

    def start_stream(self, ref, session_id):
        with self._lock:
            if any(c == ref.console_id and s != session_id for s, c in self._streams.items()):
                raise AdapterError('console_busy', 'Console simulado já está transmitindo para outra sessão.')
            self._streams[session_id] = ref.console_id
            self._revoked.discard(session_id)
        return self._r('Stream simulado iniciado (sem vídeo real).', StreamState.STREAMING, stream_url=None)

    def stop_stream(self, ref, session_id):
        with self._lock:
            self._streams.pop(session_id, None)
        return self._r('Stream simulado encerrado.', StreamState.STOPPED)

    def get_stream_status(self, ref, session_id):
        active = self._streams.get(session_id) == ref.console_id
        return self._r('', StreamState.STREAMING if active else StreamState.IDLE, active=active)

    def get_metrics(self, ref, session_id=None):
        return StreamMetrics(simulated=True)

    def send_input(self, ref, session_id, command):
        with self._lock:
            if session_id in self._revoked or self._streams.get(session_id) != ref.console_id:
                raise AdapterError('input_revoked', 'Entrada revogada ou sessão inativa.')
        cmd = validate_command(command)
        self.inputs.append((session_id, cmd))
        return self._r('Comando aceito pelo simulador.', accepted=True)

    def revoke_input(self, ref, session_id):
        with self._lock:
            self._revoked.add(session_id)
        return self._r('Entrada revogada.')

    def disconnect(self, ref):
        with self._lock:
            for s in [s for s, c in self._streams.items() if c == ref.console_id]:
                self._streams.pop(s)
                self._revoked.add(s)
        return self._r('Desconectado.', StreamState.STOPPED)

    def health_check(self, ref):
        if ref.console_id in self.fail_health:
            return AdapterResult(ok=False, simulated=True, message='Falha injetada no simulador.', state=StreamState.ERROR)
        return self._r('Simulador saudável.', StreamState.IDLE)

    def test_video_audio(self, ref):
        return self._r('Imagem e áudio SIMULADOS — nenhum vídeo real foi verificado.')

    def test_controls(self, ref):
        return self._r('Controles SIMULADOS — nenhum console real recebeu comandos.')

"""Adaptadores que delegam ao ConsoleAgent local (PC ao lado do console) via HTTPS.

O ConsoleAgent é quem executa Chiaki-NG / captura HDMI / interface de controle.
Este módulo só fala o protocolo do agente; nenhuma biblioteca de terceiros
(Chiaki, drivers de captura) é importada pela API central.
"""
import httpx

from .contract import (AdapterError, AdapterResult, ConsoleRef, ConsoleStreamingAdapter, StreamMetrics, StreamState,
                       validate_command)


class AgentDelegatingAdapter(ConsoleStreamingAdapter):
    simulated = False
    operational = False  # só após validação real com hardware e autorização
    timeout = 5.0

    def _check(self, ref: ConsoleRef) -> None:
        if not ref.agent_endpoint or not ref.agent_token:
            raise AdapterError('not_configured', 'ConsoleAgent não configurado (endpoint/credencial ausentes).')
        if not ref.agent_endpoint.startswith('https://') and not ref.agent_endpoint.startswith('http://127.0.0.1'):
            raise AdapterError('not_configured', 'O endpoint do ConsoleAgent deve usar HTTPS.')

    def _call(self, ref: ConsoleRef, action: str, payload: dict | None = None) -> dict:
        self._check(ref)
        url = f"{ref.agent_endpoint.rstrip('/')}/v1/consoles/{ref.console_id}/{action}"
        try:
            r = httpx.post(url, json={'method': self.method, **(payload or {})},
                           headers={'Authorization': f'Bearer {ref.agent_token}'}, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise AdapterError('agent_unreachable', f'ConsoleAgent inacessível: {e.__class__.__name__}')
        if r.status_code >= 400:
            raise AdapterError('agent_error', f'ConsoleAgent respondeu {r.status_code}.')
        return r.json()

    def _res(self, data: dict) -> AdapterResult:
        state = data.get('state')
        return AdapterResult(ok=bool(data.get('ok')), simulated=bool(data.get('simulated', False)),
                             message=str(data.get('message', '')), state=StreamState(state) if state else None,
                             data=data.get('data', {}))

    def discover_console(self, ref): return self._res(self._call(ref, 'discover', {'host': ref.internal_host}))
    def pair_console(self, ref, code): return self._res(self._call(ref, 'pair', {'code': code}))
    def connect(self, ref): return self._res(self._call(ref, 'connect', {'settings': ref.settings}))
    def start_stream(self, ref, session_id): return self._res(self._call(ref, 'stream/start', {'session_id': session_id}))
    def stop_stream(self, ref, session_id): return self._res(self._call(ref, 'stream/stop', {'session_id': session_id}))
    def get_stream_status(self, ref, session_id): return self._res(self._call(ref, 'stream/status', {'session_id': session_id}))

    def get_metrics(self, ref, session_id=None):
        d = self._call(ref, 'metrics', {'session_id': session_id}).get('metrics', {})
        allowed = StreamMetrics.__dataclass_fields__.keys()
        return StreamMetrics(**{k: v for k, v in d.items() if k in allowed})

    def send_input(self, ref, session_id, command):
        return self._res(self._call(ref, 'input', {'session_id': session_id, 'command': validate_command(command)}))

    def revoke_input(self, ref, session_id): return self._res(self._call(ref, 'input/revoke', {'session_id': session_id}))
    def disconnect(self, ref): return self._res(self._call(ref, 'disconnect'))
    def health_check(self, ref): return self._res(self._call(ref, 'health'))
    def test_video_audio(self, ref): return self._res(self._call(ref, 'test/video-audio'))
    def test_controls(self, ref): return self._res(self._call(ref, 'test/controls'))


class ChiakiWebRemotePlayAdapter(AgentDelegatingAdapter):
    """EXPERIMENTAL. Requer ConsoleAgent com Chiaki-NG(-Web) instalado em processo isolado,
    análise da licença AGPL-3.0 e autorização de uso. Não validado com hardware."""
    method = 'remote_play_chiaki'
    label = 'Remote Play — Chiaki (experimental)'

    def _check(self, ref):
        if ref.platform_code not in ('PS4', 'PS5'):
            raise AdapterError('unsupported_platform', 'Remote Play via Chiaki só é aplicável a PS4/PS5.')
        super()._check(ref)


class HdmiCaptureAdapter(AgentDelegatingAdapter):
    """Captura HDMI (vídeo/áudio) + canal de controle SEPARADO. Não validado com hardware."""
    method = 'hdmi_capture'
    label = 'Placa de captura HDMI + controle separado'

    def _check(self, ref):
        if not ref.capture_device_identifier:
            raise AdapterError('not_configured', 'Selecione a capturadora HDMI.')
        if not ref.control_adapter_identifier:
            raise AdapterError('not_configured', 'HDMI não controla o console: selecione um canal de controle separado.')
        super()._check(ref)


class NativeRemotePlayAdapter(ConsoleStreamingAdapter):
    """GameBridge Native — FUTURO. Não operacional; todos os métodos recusam."""
    method = 'native_remote_play'
    label = 'GameBridge Native (futuro, não operacional)'

    def _no(self, *a, **k):
        raise AdapterError('not_implemented', 'GameBridge Native ainda não foi desenvolvido.')

    discover_console = pair_console = connect = start_stream = stop_stream = _no
    get_stream_status = send_input = revoke_input = disconnect = _no

    def get_metrics(self, ref, session_id=None):
        return StreamMetrics()

    def health_check(self, ref):
        return AdapterResult(ok=False, simulated=False, message='Não operacional.', state=StreamState.UNAVAILABLE)

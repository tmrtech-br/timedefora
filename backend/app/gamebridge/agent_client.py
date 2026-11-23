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

    @staticmethod
    def _target(ref: ConsoleRef) -> dict:
        """Onde está o console. Segredos do console (chave de registro, senha) ficam só no agente."""
        s = ref.settings or {}
        route = s.get('network_route') or 'lan'
        return {'route': route, 'host': ref.internal_host if route == 'lan' else s.get('public_host'),
                'port': s.get('public_port'), 'platform_code': ref.platform_code,
                'console_identifier': s.get('console_identifier'),
                # qualidade pedida ao console (usada pelo Remote Play direto)
                'resolution': s.get('resolution'), 'fps': s.get('fps'), 'codec': s.get('codec'),
                'bitrate_kbps': s.get('bitrate_kbps')}

    def _call(self, ref: ConsoleRef, action: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        self._check(ref)
        url = f"{ref.agent_endpoint.rstrip('/')}/v1/consoles/{ref.console_id}/{action}"
        try:
            r = httpx.post(url, json={'method': self.method, 'target': self._target(ref), **(payload or {})},
                           headers={'Authorization': f'Bearer {ref.agent_token}'}, timeout=timeout or self.timeout)
        except httpx.HTTPError as e:
            raise AdapterError('agent_unreachable', f'ConsoleAgent inacessível: {e.__class__.__name__}')
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            msg = str(body.get('message') or body.get('detail') or f'ConsoleAgent respondeu {r.status_code}.')
            if r.status_code == 501 or body.get('code') == 'not_implemented':
                raise AdapterError('not_implemented', msg)
            if r.status_code in (401, 403):
                raise AdapterError('agent_error', 'ConsoleAgent recusou a credencial (token API→agente). Rotacione os tokens e atualize o agente.')
            raise AdapterError('agent_error', msg)
        return r.json()

    def _res(self, data: dict) -> AdapterResult:
        state = data.get('state')
        return AdapterResult(ok=bool(data.get('ok')), simulated=bool(data.get('simulated', False)),
                             message=str(data.get('message', '')), state=StreamState(state) if state else None,
                             data=data.get('data', {}))

    def discover_console(self, ref):
        return self._res(self._call(ref, 'discover', self._target(ref)))  # campos no topo: compatível com o agente v0.1
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

    def webrtc_offer(self, ref, session_id, offer):
        # O agente coleta os candidatos de rede (STUN) antes de responder: pode levar alguns segundos.
        return self._res(self._call(ref, 'stream/webrtc', {'session_id': session_id, 'offer': offer}, timeout=20.0))
    def disconnect(self, ref): return self._res(self._call(ref, 'disconnect'))
    def health_check(self, ref): return self._res(self._call(ref, 'health'))
    def test_video_audio(self, ref): return self._res(self._call(ref, 'test/video-audio'))
    def test_controls(self, ref): return self._res(self._call(ref, 'test/controls'))

    def prepare_console(self, ref, game):
        return self._res(self._call(ref, 'console/prepare', {'game': {k: game.get(k) for k in ('id', 'slug', 'title')},
                                                            'settings': ref.settings}))


class ChiakiWebRemotePlayAdapter(AgentDelegatingAdapter):
    """EXPERIMENTAL. Requer ConsoleAgent com Chiaki-NG(-Web) instalado em processo isolado,
    análise da licença AGPL-3.0 e autorização de uso. Não validado com hardware."""
    method = 'remote_play_chiaki'
    label = 'Remote Play — Chiaki (experimental)'

    def _check(self, ref):
        if ref.platform_code not in ('PS4', 'PS5'):
            raise AdapterError('unsupported_platform', 'Remote Play via Chiaki só é aplicável a PS4/PS5.')
        super()._check(ref)


class DirectRemotePlayAdapter(AgentDelegatingAdapter):
    """EXPERIMENTAL. O ConsoleAgent fala o protocolo Remote Play direto com o console (biblioteca pyremoteplay
    incorporada, GPL-3.0): sem chiaki-ng, sem janelas, um controle próprio por console — vários consoles por PC.
    Só rede local. Não validado com hardware."""
    method = 'remote_play_direct'
    label = 'Remote Play direto (experimental)'

    def _check(self, ref):
        if ref.platform_code not in ('PS4', 'PS5'):
            raise AdapterError('unsupported_platform', 'Remote Play só é aplicável a PS4/PS5.')
        if ((ref.settings or {}).get('network_route') or 'lan') != 'lan':
            raise AdapterError('not_configured', 'O Remote Play direto funciona só na rede local do agente.')
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

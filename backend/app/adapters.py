"""GameBridge: replaceable console streaming adapters.
Only the simulated adapter is implemented; hardware integrations are deliberately unavailable.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

class AdapterKind(str, Enum):
    SIMULATED = 'simulated'
    CHIAKI = 'chiaki_web_remote_play'
    NATIVE = 'native_remote_play'
    HDMI = 'hdmi_capture'

class AdapterError(Exception):
    pass

@dataclass
class Metrics:
    fps: float | None = None
    rtt_ms: float | None = None
    jitter_ms: float | None = None
    bitrate_kbps: float | None = None
    frames_dropped: int | None = None

class ConsoleStreamingAdapter(ABC):
    @abstractmethod
    async def discover_console(self, console_id: str): ...
    @abstractmethod
    async def pair_console(self, console_id: str, code: str): ...
    @abstractmethod
    async def connect(self, console_id: str): ...
    @abstractmethod
    async def start_stream(self, session_id: str): ...
    @abstractmethod
    async def stop_stream(self, session_id: str): ...
    @abstractmethod
    async def get_stream_status(self, session_id: str): ...
    @abstractmethod
    async def get_metrics(self, session_id: str) -> Metrics: ...
    @abstractmethod
    async def send_input(self, session_id: str, command: dict): ...
    @abstractmethod
    async def revoke_input(self, session_id: str): ...
    @abstractmethod
    async def disconnect(self, console_id: str): ...
    @abstractmethod
    async def health_check(self) -> bool: ...

class SimulatedAdapter(ConsoleStreamingAdapter):
    def __init__(self): self.sessions: set[str] = set();self.revoked: set[str] = set()
    async def discover_console(self, console_id): return {'id':console_id,'simulated':True}
    async def pair_console(self, console_id, code): return {'simulated':True}
    async def connect(self, console_id): return {'simulated':True}
    async def start_stream(self, session_id): self.sessions.add(session_id);return {'simulated':True,'stream_url':None}
    async def stop_stream(self, session_id): self.sessions.discard(session_id)
    async def get_stream_status(self, session_id): return {'active':session_id in self.sessions,'simulated':True}
    async def get_metrics(self, session_id): return Metrics()
    async def send_input(self, session_id, command):
        if session_id not in self.sessions or session_id in self.revoked: raise AdapterError('Input revoked or inactive')
        return {'accepted':True,'simulated':True}
    async def revoke_input(self, session_id):self.revoked.add(session_id)
    async def disconnect(self, console_id): return None
    async def health_check(self): return True

class UnsupportedHardwareAdapter(ConsoleStreamingAdapter):
    def _unsupported(self): raise AdapterError('Hardware adapter not implemented or validated')
    async def discover_console(self, console_id):self._unsupported()
    async def pair_console(self, console_id, code):self._unsupported()
    async def connect(self, console_id):self._unsupported()
    async def start_stream(self, session_id):self._unsupported()
    async def stop_stream(self, session_id):self._unsupported()
    async def get_stream_status(self, session_id):self._unsupported()
    async def get_metrics(self, session_id):self._unsupported()
    async def send_input(self, session_id, command):self._unsupported()
    async def revoke_input(self, session_id):self._unsupported()
    async def disconnect(self, console_id):self._unsupported()
    async def health_check(self):return False

ADAPTERS={AdapterKind.SIMULATED:SimulatedAdapter(),AdapterKind.CHIAKI:UnsupportedHardwareAdapter(),AdapterKind.NATIVE:UnsupportedHardwareAdapter(),AdapterKind.HDMI:UnsupportedHardwareAdapter()}

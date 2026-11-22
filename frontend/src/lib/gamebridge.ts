// Contrato GameBridge (somente tipos, espelho de backend/app/gamebridge/contract.py — versão 1.0).
// O navegador NUNCA fala com adaptadores; usa a API de sessão com token efêmero.
export type StreamState = 'idle' | 'connecting' | 'streaming' | 'degraded' | 'stopped' | 'error' | 'unavailable';
export type StreamMetrics = {
  fps: number | null; bitrate_kbps: number | null; rtt_ms: number | null; jitter_ms: number | null;
  packet_loss_pct: number | null; frames_dropped: number | null; input_latency_ms: number | null; simulated: boolean;
};
export type InputCommand =
  | { type: 'button'; name: string; pressed: boolean }
  | { type: 'axis'; name: 'left_x' | 'left_y' | 'right_x' | 'right_y'; value: number };
export interface ConsoleStreamingAdapterContract {
  discoverConsole(): Promise<unknown>; pairConsole(code?: string): Promise<unknown>; connect(): Promise<unknown>;
  startStream(sessionId: string): Promise<unknown>; stopStream(sessionId: string): Promise<unknown>;
  getStreamStatus(sessionId: string): Promise<{ state: StreamState }>; getMetrics(sessionId?: string): Promise<StreamMetrics>;
  sendInput(sessionId: string, cmd: InputCommand): Promise<unknown>; revokeInput(sessionId: string): Promise<unknown>;
  disconnect(): Promise<unknown>; healthCheck(): Promise<{ ok: boolean }>;
}

/** Transporte de comandos de baixa latência do navegador até o ConsoleAgent.
 * Uma conexão por sessão. Quando o DataChannel não está ativo, o chamador
 * deve conservar a rota HTTP já existente; nunca descartar comandos silenciosamente.
 */
export type ConsoleCommand =
  | { type: 'button'; name: string; pressed: boolean }
  | { type: 'axis'; name: string; value: number };
const channels = new Map<string, RTCDataChannel>();
const sequence = new Map<string, number>();

export function registerWebRtcControls(sessionId: string, channel: RTCDataChannel): () => void {
  channels.set(sessionId, channel);
  sequence.set(sessionId, 0);
  return () => { if (channels.get(sessionId) === channel) { channels.delete(sessionId); sequence.delete(sessionId); } };
}

export function sendWebRtcControl(sessionId: string, command: ConsoleCommand): boolean {
  const channel = channels.get(sessionId);
  if (!channel || channel.readyState !== 'open' || channel.bufferedAmount > 16_384) return false;
  try {
    const seq = (sequence.get(sessionId) || 0) + 1;
    sequence.set(sessionId, seq);
    const payload = JSON.stringify({ ...command, seq });
    channel.send(payload);
    // Canal sem retransmissão: uma segunda cópia de transições de botões
    // reduz risco de tecla solta permanecer pressionada após perda UDP.
    if (command.type === 'button' && channel.bufferedAmount < 16_384) channel.send(payload);
    return true;
  }
  catch { return false; }
}

export function hasWebRtcControl(sessionId: string): boolean {
  return channels.get(sessionId)?.readyState === 'open';
}

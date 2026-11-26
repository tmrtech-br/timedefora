'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Loader2, RefreshCw, Volume2, VolumeX } from 'lucide-react';
import { csrfToken } from '@/lib/api';
import { registerWebRtcControls } from '@/lib/webrtc-controls';

export type VideoStats = { fps: number | null; bitrate_kbps: number | null; rtt_ms: number | null; jitter_ms: number | null; packet_loss_pct: number | null };
type Phase = 'connecting' | 'retrying' | 'live' | 'failed';
const MAX_AUTO = 8;          // ~1 min de tentativas automáticas (o console pode estar acordando/reconectando)
const RETRY_MS = 6000;

/**
 * Vídeo do console (WebRTC). A oferta vai para a API com o token de controle; o agente do console responde.
 * Métricas vêm do próprio navegador (getStats): valores medidos, nunca estimados.
 */
export default function ConsoleVideo({ sessionId, token, onStats }: { sessionId: string; token: string; onStats?: (s: VideoStats) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const [phase, setPhase] = useState<Phase>('connecting');
  const [error, setError] = useState('');
  const [muted, setMuted] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const last = useRef<{ t: number; bytes: number; frames: number; lost: number; recv: number } | null>(null);

  const call = useCallback(async (path: string, init?: RequestInit) => {
    const res = await fetch(`/api/sessions/${sessionId}/${path}`, { ...init, headers: { 'Content-Type': 'application/json', 'X-Input-Token': token, 'X-CSRF-Token': csrfToken(), ...(init?.headers || {}) } });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw Object.assign(new Error(body.detail || body.message || `Erro ${res.status}`), { status: res.status, code: body.code });
    return body;
  }, [sessionId, token]);
  // Tentativas automáticas (console reconectando, rede oscilando). Sessão encerrada/acesso revogado não tenta de novo.
  const auto = useRef(0);
  const retryLater = useCallback((reason: string) => {
    if (auto.current >= MAX_AUTO) { setPhase('failed'); setError(reason); return; }
    auto.current += 1;
    setPhase('retrying');
    setTimeout(() => setAttempt((x) => x + 1), RETRY_MS);
  }, []);

  useEffect(() => {
    let closed = false;
    const pc = { current: null as RTCPeerConnection | null };
    let unregisterControl: (() => void) | null = null;
    (async () => {
      setPhase('connecting'); setError('');
      try {
        const cfg = await call('webrtc-config');
        const conn = new RTCPeerConnection({ iceServers: cfg.ice_servers || [] });
        pc.current = conn; pcRef.current = conn;
        const control = conn.createDataChannel('locaplay-controls', { ordered: false, maxRetransmits: 0 });
        unregisterControl = registerWebRtcControls(sessionId, control);
        conn.addTransceiver('video', { direction: 'recvonly' });
        conn.addTransceiver('audio', { direction: 'recvonly' });
        const stream = new MediaStream();
        conn.ontrack = (e) => {
          stream.addTrack(e.track);
          if (video.current && video.current.srcObject !== stream) { video.current.srcObject = stream; video.current.play().catch(() => {}); }
        };
        conn.onconnectionstatechange = () => {
          if (closed) return;
          if (conn.connectionState === 'connected') { auto.current = 0; setPhase('live'); }
          if (conn.connectionState === 'failed') retryLater('A conexão de vídeo caiu (rede bloqueada ou instável).');
        };
        await conn.setLocalDescription(await conn.createOffer());
        // Espera a coleta de candidatos (máx. 3 s): a troca é feita numa única ida e volta.
        await new Promise<void>((ok) => {
          if (conn.iceGatheringState === 'complete') return ok();
          const t = setTimeout(ok, 3000);
          conn.onicegatheringstatechange = () => { if (conn.iceGatheringState === 'complete') { clearTimeout(t); ok(); } };
        });
        const res = await call('webrtc', { method: 'POST', body: JSON.stringify({ offer: { type: 'offer', sdp: conn.localDescription?.sdp } }) });
        if (closed) return;
        await conn.setRemoteDescription(res.answer);
      } catch (e) {
        if (closed) return;
        const err = e as Error & { status?: number; code?: string };
        if (err.status === 403) { setPhase('failed'); setError('Sua sessão terminou ou o acesso ao controle foi encerrado nesta aba.'); return; }
        retryLater('Não conseguimos ligar a imagem do console agora. A equipe pode ajudar pelo botão Suporte.');
      }
    })();
    return () => { closed = true; unregisterControl?.(); pc.current?.close(); pcRef.current = null; last.current = null; };
  }, [call, attempt, retryLater]);

  // Métricas reais do navegador, a cada 2 s.
  useEffect(() => {
    if (phase !== 'live' || !onStats) return;
    const t = setInterval(async () => {
      const conn = pcRef.current;
      if (!conn) return;
      const rep = await conn.getStats();
      let inbound: RTCInboundRtpStreamStats | undefined; let rtt: number | null = null;
      rep.forEach((s) => {
        if (s.type === 'inbound-rtp' && (s as RTCInboundRtpStreamStats).kind === 'video') inbound = s as RTCInboundRtpStreamStats;
        if (s.type === 'candidate-pair' && (s as RTCIceCandidatePairStats).state === 'succeeded' && (s as RTCIceCandidatePairStats).nominated)
          rtt = (s as RTCIceCandidatePairStats).currentRoundTripTime ?? null;
      });
      if (!inbound) return;
      const now = performance.now(), bytes = inbound.bytesReceived ?? 0, frames = inbound.framesDecoded ?? 0;
      const lost = inbound.packetsLost ?? 0, recv = inbound.packetsReceived ?? 0;
      const p = last.current;
      last.current = { t: now, bytes, frames, lost, recv };
      if (!p) return;
      const dt = (now - p.t) / 1000, dLost = lost - p.lost, dRecv = recv - p.recv;
      onStats({
        fps: inbound.framesPerSecond ?? Math.round((frames - p.frames) / dt),
        bitrate_kbps: Math.round(((bytes - p.bytes) * 8) / dt / 1000),
        rtt_ms: rtt !== null ? Math.round(rtt * 1000) : null,
        jitter_ms: inbound.jitter !== undefined ? Math.round(inbound.jitter * 1000) : null,
        packet_loss_pct: dLost + dRecv > 0 ? Math.round((dLost / (dLost + dRecv)) * 1000) / 10 : 0,
      });
    }, 2000);
    return () => clearInterval(t);
  }, [phase, onStats]);

  return (
    <div className="console-video">
      <video ref={video} autoPlay playsInline muted={muted} aria-label="Imagem do console" />
      {phase !== 'live' && (
        <div className="cv-overlay" role="status">
          {phase === 'connecting' ? <><Loader2 className="spin" size={36} aria-hidden /><p className="cv-title">Sua partida já vai começar! 🎮</p>
            <p className="small">Estamos ligando a imagem do console para você. Pegue o controle — leva só alguns segundos.</p></>
            : phase === 'retrying' ? <><Loader2 className="spin" size={36} aria-hidden /><p className="cv-title">Reconectando ao console…</p>
              <p className="small">A imagem caiu por um instante e já estamos trazendo de volta. Seu tempo e o controle continuam garantidos. (tentativa {auto.current} de {MAX_AUTO})</p></>
            : <><p className="cv-title">Não foi possível mostrar a imagem agora</p><p className="small">{error}</p>
              <button className="btn sm cv-retry" onClick={() => { auto.current = 0; setAttempt((x) => x + 1); }}><RefreshCw size={14} aria-hidden />Tentar de novo</button></>}
        </div>)}
      {phase === 'live' && (
        <button className="cv-sound" onClick={() => setMuted(!muted)} aria-label={muted ? 'Ativar som' : 'Silenciar'}>
          {muted ? <><VolumeX size={16} aria-hidden />Ativar som</> : <Volume2 size={16} aria-hidden />}</button>)}
    </div>
  );
}

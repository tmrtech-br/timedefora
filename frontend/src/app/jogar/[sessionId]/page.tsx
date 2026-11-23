'use client';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Gamepad2, Headphones, Maximize, Power, Unplug } from 'lucide-react';
import RequireAuth from '@/components/RequireAuth';
import { GAMEPAD_BUTTONS } from '@/components/InputTester';
import { Alert, ErrorBox, Skeleton } from '@/components/ui';
import { csrfToken, post } from '@/lib/api';
import { useApi, useServerClock } from '@/lib/hooks';
import { duration } from '@/lib/format';
import { useFeatures } from '@/lib/features';
import { toast } from '@/components/Toaster';
import type { InputCommand, StreamMetrics } from '@/lib/gamebridge';

type State = { id: string; status: string; game: string; console: string; contract_ends_at: string; server_time: string; remaining_seconds: number;
  input_device: string; simulated: boolean; metrics: StreamMetrics | null; end_reason: string | null };
const KEYMAP: Record<string, string> = { Space: 'cross', KeyE: 'circle', KeyQ: 'square', KeyR: 'triangle', ShiftLeft: 'l1', ControlLeft: 'r1',
  ArrowUp: 'dpad_up', ArrowDown: 'dpad_down', ArrowLeft: 'dpad_left', ArrowRight: 'dpad_right', Enter: 'options' };
// Botões do controle (índices do "standard mapping") que nunca são enviados ao console.
const BLOCKED_PAD: Record<number, string> = { 16: 'PS', 17: 'Touchpad' };

function Player() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const { data: s, error, reload } = useApi<State>(`/sessions/${sessionId}`, 5000);
  const now = useServerClock(s?.server_time);
  const [token, setToken] = useState<string | null>(null);
  const [inputStatus, setInputStatus] = useState('aguardando');
  const [sent, setSent] = useState(0);
  const screen = useRef<HTMLDivElement>(null);
  const prev = useRef<boolean[]>([]);
  const shareOn = useFeatures()?.share_button_enabled === true;   // Share bloqueado por padrão (Parâmetros)
  const lastBlock = useRef<Record<string, number>>({});
  /** Avisa (no máximo a cada 4 s por botão) que o botão está bloqueado por segurança. */
  const warnBlocked = useCallback((name: string) => {
    const t = Date.now();
    if (t - (lastBlock.current[name] || 0) < 4000) return;
    lastBlock.current[name] = t;
    toast('error', `Botão ${name} bloqueado por segurança`);
  }, []);
  useEffect(() => { try { setToken(sessionStorage.getItem(`lp_input_${sessionId}`)); } catch { setToken(null); } }, [sessionId]);
  const send = useCallback(async (command: InputCommand) => {
    if (!token) return;
    const res = await fetch(`/api/sessions/${sessionId}/input`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Input-Token': token, 'X-CSRF-Token': csrfToken() }, body: JSON.stringify({ command }) });
    if (res.status === 400) {
      const body = await res.json().catch(() => ({}));
      if (body.code === 'blocked_command' && command.type === 'button') warnBlocked(command.name === 'share' ? 'Share' : command.name.toUpperCase());
    }
    else if (res.status === 403) {
      const body = await res.json().catch(() => ({}));
      if (['input_revoked', 'invalid_input_token'].includes(body.code)) { setInputStatus('revogado'); setToken(null); reload(); }
      else setInputStatus(`recusado: ${body.detail || res.status}`);
    }
    else if (res.ok) { setInputStatus('ativo'); setSent((x) => x + 1); }
  }, [token, sessionId, reload, warnBlocked]);
  useEffect(() => {
    if (!token) return;
    const down = (e: KeyboardEvent) => { const n = KEYMAP[e.code]; if (n && !e.repeat) { e.preventDefault(); send({ type: 'button', name: n, pressed: true }); } };
    const up = (e: KeyboardEvent) => { const n = KEYMAP[e.code]; if (n) send({ type: 'button', name: n, pressed: false }); };
    window.addEventListener('keydown', down); window.addEventListener('keyup', up);
    let raf = 0;
    const loop = () => {
      const pad = (navigator.getGamepads?.() || []).find(Boolean);
      if (pad) pad.buttons.forEach((b, i) => {
        const changed = b.pressed !== prev.current[i];
        if (changed && b.pressed && BLOCKED_PAD[i]) warnBlocked(BLOCKED_PAD[i]);
        else if (changed && b.pressed && GAMEPAD_BUTTONS[i] === 'share' && !shareOn) warnBlocked('Share');
        else if (i < GAMEPAD_BUTTONS.length && changed && (GAMEPAD_BUTTONS[i] !== 'share' || shareOn)) send({ type: 'button', name: GAMEPAD_BUTTONS[i], pressed: b.pressed });
        prev.current[i] = b.pressed;
      });
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); cancelAnimationFrame(raf); };
  }, [token, send, shareOn, warnBlocked]);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!s) return <Skeleton h={420} />;
  const left = Math.max(0, (new Date(s.contract_ends_at).getTime() - now()) / 1000);
  const ended = !['ready', 'active'].includes(s.status) || left <= 0;
  const warn = left <= 30 ? 'Restam 30 segundos!' : left <= 60 ? 'Resta 1 minuto.' : left <= 300 ? 'Restam 5 minutos.' : left <= 600 ? 'Restam 10 minutos.' : '';
  return (
    <div className="stack">
      <div className="spread"><h1 style={{ margin: 0 }}>{s.game} <span className="small muted">· {s.console}</span></h1>
        <div className="countdown" style={{ fontSize: 34 }} aria-live="polite">{duration(left)}</div></div>
      {s.simulated && <Alert kind="warn">Sessão <b>SIMULADA</b>: não há vídeo de console real. Os comandos são validados pelo servidor e aceitos pelo simulador GameBridge.</Alert>}
      {warn && !ended && <Alert kind="info">{warn}</Alert>}
      {ended && <Alert kind="ok">Sessão encerrada. O controle do console foi revogado pelo servidor.</Alert>}
      <div className="player" ref={screen} tabIndex={0} aria-label="Tela do jogo">
        <div className="sim-screen"><Gamepad2 size={64} aria-hidden /><h2>{s.simulated ? 'Stream simulado' : 'Conectando ao stream…'}</h2>
          <p>Entrada: {inputStatus} · comandos enviados: {sent}</p>
          {!token && !ended && <p>Token de controle ausente nesta aba. <button className="btn sm" onClick={() => router.push(`/sessoes`)}>Reconectar pela sala de espera</button></p>}</div>
      </div>
      <div className="row">
        <button className="btn" onClick={() => screen.current?.requestFullscreen?.()}><Maximize size={16} />Tela cheia</button>
        <button className="btn" onClick={async () => { await post(`/sessions/${sessionId}/disconnect`); setToken(null); router.push('/sessoes'); }} disabled={ended}><Unplug size={16} />Sair (posso voltar)</button>
        <button className="btn danger" onClick={async () => { if (confirm('Encerrar a sessão agora? O tempo restante não é transferido.')) { await post(`/sessions/${sessionId}/end`); reload(); } }} disabled={ended}><Power size={16} />Encerrar sessão</button>
        <a className="btn" href="/suporte"><Headphones size={16} />Suporte</a>
      </div>
      <section className="card small"><h3>Métricas</h3>
        <p>FPS: {s.metrics?.fps ?? 'não disponível'} · RTT: {s.metrics?.rtt_ms ?? 'não disponível'} · Jitter: {s.metrics?.jitter_ms ?? 'não disponível'} · Bitrate: {s.metrics?.bitrate_kbps ?? 'não disponível'}</p>
        <p className="dim">Valores só aparecem quando medidos de verdade pelo agente do console.</p></section>
    </div>
  );
}
export default function Page() { return <RequireAuth><Player /></RequireAuth>; }

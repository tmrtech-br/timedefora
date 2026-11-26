'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CalendarPlus, Gamepad2, Headphones, Keyboard, ListOrdered, Maximize, Power, Unplug, X } from 'lucide-react';
import ConsoleVideo, { type VideoStats } from '@/components/ConsoleVideo';
import { sendWebRtcControl } from '@/lib/webrtc-controls';
import { CustomizeLink, KeyLegend } from '@/components/KeyBindings';
import RequireAuth from '@/components/RequireAuth';
import SupportPanel from '@/components/SupportPanel';
import { GAMEPAD_BUTTONS } from '@/components/InputTester';
import { Alert, ErrorBox, Modal, Skeleton } from '@/components/ui';
import { csrfToken, post } from '@/lib/api';
import { useApi, useServerClock } from '@/lib/hooks';
import { duration } from '@/lib/format';
import { useFeatures } from '@/lib/features';
import { type Action, byCode, useBindings } from '@/lib/keymap';
import { toast } from '@/components/Toaster';
import type { InputCommand, StreamMetrics } from '@/lib/gamebridge';

type State = { id: string; status: string; game: string; slug?: string; console: string; reservation_id?: string; contract_ends_at: string; server_time: string;
  remaining_seconds: number; input_device: string; simulated: boolean; metrics: StreamMetrics | null; end_reason: string | null };
// Botões do controle (índices do "standard mapping") que nunca são enviados ao console.
const BLOCKED_PAD: Record<number, string> = { 16: 'PS', 17: 'Touchpad' };
// "standard mapping": axes[0..3] = analógico esquerdo X/Y, direito X/Y (Y negativo = para cima, igual ao DS4).
const AXES = ['left_x', 'left_y', 'right_x', 'right_y'] as const;
type AxisName = typeof AXES[number];
const DEADZONE = 0.12;
const STICK_KEYS: Partial<Record<Action, [AxisName, number]>> = {
  ls_left: ['left_x', -1], ls_right: ['left_x', 1], ls_up: ['left_y', -1], ls_down: ['left_y', 1],
  rs_left: ['right_x', -1], rs_right: ['right_x', 1], rs_up: ['right_y', -1], rs_down: ['right_y', 1],
};
const END_REASON: Record<string, string> = { time_up: 'O tempo contratado terminou.', user_ended: 'Você encerrou a sessão.', admin: 'A sessão foi encerrada pela equipe.',
  failure: 'A sessão foi encerrada por uma falha da plataforma — o tempo perdido será compensado conforme a política.', no_show: 'A sessão terminou por ausência.' };

/** Aviso de tempo coerente com o cronômetro (antes: "Restam 5 minutos" aparecia até faltar 1 minuto). */
function timeWarning(left: number): string {
  if (left <= 0) return '';
  if (left <= 30) return `Restam ${Math.ceil(left)} segundos!`;
  if (left <= 60) return 'Falta menos de 1 minuto.';
  if (left <= 600) return `Faltam menos de ${Math.ceil(left / 60)} minutos.`;
  return '';
}

function Player() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const router = useRouter();
  const { data: s, error, reload } = useApi<State>(`/sessions/${sessionId}`, 5000);
  const now = useServerClock(s?.server_time);
  const [token, setToken] = useState<string | null>(null);
  const [inputStatus, setInputStatus] = useState('aguardando');
  const screen = useRef<HTMLDivElement>(null);
  const area = useRef<HTMLDivElement>(null);       // vídeo + painel lateral (tela cheia leva os dois)
  const prev = useRef<boolean[]>([]);
  const axes = useRef<Record<string, number>>({});
  const axesAt = useRef<Record<string, number>>({});
  const [vstats, setVstats] = useState<VideoStats | null>(null);
  const [side, setSide] = useState<'support' | 'controls' | null>(null);
  const [unread, setUnread] = useState(0);
  const [confirmEnd, setConfirmEnd] = useState(false);
  const [ending, setEnding] = useState(false);
  const [locked, setLocked] = useState(false);
  const shareOn = useFeatures()?.share_button_enabled === true;   // Share bloqueado por padrão (Parâmetros)
  const { bindings } = useBindings();
  const codeToAction = useMemo(() => byCode(bindings.keys), [bindings.keys]);
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
    if (sendWebRtcControl(sessionId, command)) { setInputStatus('ativo'); return; }
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
    else if (res.ok) setInputStatus('ativo');
  }, [token, sessionId, reload, warnBlocked]);
  /** Envia o eixo só quando muda (e no máximo ~15×/s, exceto a volta ao centro). */
  const sendAxis = useCallback((name: AxisName, v: number, force = false) => {
    const t = performance.now();
    if (axes.current[name] === v || (!force && v !== 0 && t - (axesAt.current[name] || 0) < 66)) return;
    axes.current[name] = v; axesAt.current[name] = t;
    send({ type: 'axis', name, value: v });
  }, [send]);

  // ------------------------------------------------------------------ teclado, mouse e controle
  useEffect(() => {
    if (!token) return;
    const held = new Set<Action>();
    const mouse = { dx: 0, dy: 0 };
    const padAxes: Record<string, number> = { left_x: 0, left_y: 0, right_x: 0, right_y: 0 };
    // Digitando num campo (ex.: suporte): as teclas são do texto, não do console.
    const typing = (e: Event) => { const el = e.target as HTMLElement | null; return !!el && (el.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)); };
    const stickFromKeys = () => {
      const v: Record<AxisName, number> = { left_x: 0, left_y: 0, right_x: 0, right_y: 0 };
      held.forEach((a) => { const m = STICK_KEYS[a]; if (m) v[m[0]] += m[1]; });
      return v;
    };
    const applyKeySticks = () => { const v = stickFromKeys(); sendAxis('left_x', v.left_x, true); sendAxis('left_y', v.left_y, true);
      if (!document.pointerLockElement) { sendAxis('right_x', v.right_x, true); sendAxis('right_y', v.right_y, true); } };
    const press = (a: Action, down: boolean) => {
      if (STICK_KEYS[a]) { if (down) held.add(a); else held.delete(a); applyKeySticks(); return; }
      if (a === 'share' && !shareOn) { if (down) warnBlocked('Share'); return; }
      send({ type: 'button', name: a, pressed: down });
    };
    const keyDown = (e: KeyboardEvent) => { const a = codeToAction[e.code]; if (!a || e.repeat || typing(e)) return; e.preventDefault(); press(a, true); };
    const keyUp = (e: KeyboardEvent) => { const a = codeToAction[e.code]; if (!a || typing(e)) return; press(a, false); };
    const onScreen = (e: Event) => !!screen.current && screen.current.contains(e.target as Node);
    const mouseDown = (e: MouseEvent) => {
      if (!onScreen(e)) return;
      // Botões sobre a imagem (Tentar de novo, Ativar som…) são cliques normais: não prendem o mouse nem viram comando.
      if (!document.pointerLockElement && (e.target as HTMLElement)?.closest('button, a, input, textarea, select')) return;
      const playing = (screen.current?.querySelector('video')?.videoWidth || 0) > 0;
      if (bindings.mouse_look && !document.pointerLockElement) {          // 1º clique só "prende" o mouse — e só com o jogo na tela
        if (playing) screen.current?.requestPointerLock?.();
        return;
      }
      const a = codeToAction[`Mouse${e.button}`]; if (a) { e.preventDefault(); press(a, true); }
    };
    const mouseUp = (e: MouseEvent) => { const a = codeToAction[`Mouse${e.button}`]; if (a && (document.pointerLockElement || onScreen(e))) press(a, false); };
    const mouseMove = (e: MouseEvent) => { if (document.pointerLockElement === screen.current) { mouse.dx += e.movementX; mouse.dy += e.movementY; } };
    const noMenu = (e: MouseEvent) => { if (onScreen(e)) e.preventDefault(); };
    const lockChange = () => {
      const on = document.pointerLockElement === screen.current;
      setLocked(on);
      if (on) toast('ok', 'Mouse preso no jogo. Aperte Esc para liberar o cursor.');
    };
    // Perder o foco da aba solta tudo (senão o personagem continuaria andando sozinho).
    const blur = () => { held.clear(); applyKeySticks(); };
    window.addEventListener('keydown', keyDown); window.addEventListener('keyup', keyUp);
    window.addEventListener('mousedown', mouseDown); window.addEventListener('mouseup', mouseUp);
    window.addEventListener('mousemove', mouseMove); window.addEventListener('contextmenu', noMenu); window.addEventListener('blur', blur);
    document.addEventListener('pointerlockchange', lockChange);
    let raf = 0;
    const loop = () => {
      // Mouse → analógico direito (câmera): deslocamento do quadro × sensibilidade, volta ao centro quando para.
      if (document.pointerLockElement === screen.current && bindings.mouse_look) {
        const k = 0.05 * bindings.mouse_sensitivity;
        const clamp = (x: number) => Math.max(-1, Math.min(1, Math.round(x * k * 50) / 50));
        const keys = stickFromKeys();
        sendAxis('right_x', mouse.dx ? clamp(mouse.dx) : keys.right_x, mouse.dx === 0);
        sendAxis('right_y', mouse.dy ? clamp(mouse.dy) : keys.right_y, mouse.dy === 0);
        mouse.dx = 0; mouse.dy = 0;
      }
      const pad = (navigator.getGamepads?.() || []).find(Boolean);
      if (pad) {
        AXES.forEach((name, i) => {
          const raw = pad.axes[i] ?? 0;
          const v = Math.abs(raw) < DEADZONE ? 0 : Math.round(raw * 50) / 50;
          if (v !== padAxes[name]) { padAxes[name] = v; sendAxis(name, v, v === 0); }   // só quando o analógico do controle muda
        });
        pad.buttons.forEach((b, i) => {
          const changed = b.pressed !== prev.current[i];
          if (changed && b.pressed && BLOCKED_PAD[i]) warnBlocked(BLOCKED_PAD[i]);
          else if (changed && b.pressed && GAMEPAD_BUTTONS[i] === 'share' && !shareOn) warnBlocked('Share');
          else if (i < GAMEPAD_BUTTONS.length && changed && (GAMEPAD_BUTTONS[i] !== 'share' || shareOn)) send({ type: 'button', name: GAMEPAD_BUTTONS[i], pressed: b.pressed });
          prev.current[i] = b.pressed;
        });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      window.removeEventListener('keydown', keyDown); window.removeEventListener('keyup', keyUp);
      window.removeEventListener('mousedown', mouseDown); window.removeEventListener('mouseup', mouseUp);
      window.removeEventListener('mousemove', mouseMove); window.removeEventListener('contextmenu', noMenu); window.removeEventListener('blur', blur);
      document.removeEventListener('pointerlockchange', lockChange);
      cancelAnimationFrame(raf);
    };
  }, [token, send, sendAxis, shareOn, warnBlocked, codeToAction, bindings.mouse_look, bindings.mouse_sensitivity]);

  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!s) return <Skeleton h={420} />;
  const left = Math.max(0, (new Date(s.contract_ends_at).getTime() - now()) / 1000);
  const ended = !['ready', 'active'].includes(s.status) || left <= 0;
  const warn = ended ? '' : timeWarning(left);

  async function endNow() {
    setEnding(true);
    try { await post(`/sessions/${sessionId}/end`); setConfirmEnd(false); reload(); }
    catch { toast('error', 'Não foi possível encerrar agora. Tente de novo.'); }
    setEnding(false);
  }

  return (
    <div className="stack">
      <div className="spread"><h1 style={{ margin: 0 }}>{s.game} <span className="small muted">· {s.console}</span></h1>
        <div className={`countdown${!ended && left <= 60 ? ' urgent' : ''}`} style={{ fontSize: 34 }} aria-live="polite">{duration(left)}</div></div>
      {s.simulated && <Alert kind="warn">Sessão <b>SIMULADA</b>: não há vídeo de console real. Os comandos são validados pelo servidor e aceitos pelo simulador GameBridge.</Alert>}
      {warn && <Alert kind={left <= 60 ? 'warn' : 'info'}>{warn}</Alert>}

      {ended ? (
        <section className="card session-over">
          <Gamepad2 size={44} aria-hidden />
          <h2>Sessão encerrada</h2>
          <p className="muted">{(s.end_reason && END_REASON[s.end_reason]) || 'O tempo contratado terminou.'} O controle do console foi liberado para o próximo jogador.</p>
          <div className="row" style={{ justifyContent: 'center' }}>
            {s.slug && <Link className="btn primary" href={`/jogos/${s.slug}`}><CalendarPlus size={16} aria-hidden />Jogar de novo — nova reserva</Link>}
            <Link className="btn" href="/jogos"><ListOrdered size={16} aria-hidden />Ver outros jogos</Link>
            <Link className="btn" href="/sessoes">Minhas sessões</Link>
          </div>
        </section>
      ) : (
        <>
          <div className={`play-area${side ? ' with-support' : ''}`} ref={area}>
            <div className="player" ref={screen} tabIndex={0} aria-label="Tela do jogo">
              {!s.simulated && token
                ? <ConsoleVideo sessionId={sessionId} token={token} onStats={setVstats} />
                : <div className="sim-screen"><Gamepad2 size={64} aria-hidden /><h2>{s.simulated ? 'Stream simulado' : 'Sua partida está quase pronta…'}</h2>
                  {s.simulated && <p>Entrada: {inputStatus}</p>}
                  {!token && <p>Esta aba não tem o acesso ao controle. <button className="btn sm" onClick={() => router.push('/sessoes')}>Reconectar pela sala de espera</button></p>}</div>}
              {bindings.mouse_look && token && vstats && (locked
                ? <span className="mouse-hint locked" role="status">🖱️ Mouse preso no jogo — aperte <kbd>Esc</kbd> para liberar</span>
                : <span className="mouse-hint">Clique na imagem para usar o mouse como câmera · <kbd>Esc</kbd> libera</span>)}
            </div>
            {s.reservation_id && <SupportPanel open={side === 'support'} onClose={() => { setSide(null); screen.current?.focus(); }} reservationId={s.reservation_id}
              game={s.game} consoleName={s.console} onStaffReply={setUnread} />}
            {side === 'controls' && (
              <aside className="support-panel controls-panel" role="dialog" aria-label="Comandos do jogo">
                <header><div><b><Keyboard size={16} aria-hidden /> Comandos</b><small>{bindings.custom ? 'Seus controles personalizados' : 'Controles padrão do site'}</small></div>
                  <button className="icon-btn" onClick={() => { setSide(null); screen.current?.focus(); }} aria-label="Fechar comandos"><X size={18} /></button></header>
                <div className="support-body">
                  <KeyLegend bindings={bindings} compact />
                  <p className="small dim" style={{ margin: 0 }}>Controle USB/Bluetooth: os botões funcionam como no console. PS, Touchpad{!shareOn && ' e Share'} ficam bloqueados por segurança.</p>
                  <p className="small" style={{ margin: 0 }}>Quer outras teclas? <a className="link-purple" href="/configuracoes#controles" target="_blank" rel="noopener noreferrer">Personalizar em nova aba</a> e depois recarregue esta página.</p>
                </div>
              </aside>)}
          </div>
          <div className="row">
            <button className="btn" onClick={() => area.current?.requestFullscreen?.()}><Maximize size={16} />Tela cheia</button>
            <button className={`btn${side === 'controls' ? ' primary' : ''}`} onClick={() => setSide(side === 'controls' ? null : 'controls')} aria-expanded={side === 'controls'}>
              <Keyboard size={16} />{side === 'controls' ? 'Ocultar comandos' : 'Ver comandos'}</button>
            <button className={`btn${side === 'support' ? ' primary' : ''}`} onClick={() => setSide(side === 'support' ? null : 'support')} aria-expanded={side === 'support'}>
              <Headphones size={16} />Suporte{unread > 0 && side !== 'support' && <span className="badge-dot" aria-label={`${unread} resposta(s) nova(s)`}>{unread}</span>}</button>
            <button className="btn" onClick={async () => { await post(`/sessions/${sessionId}/disconnect`); setToken(null); router.push('/sessoes'); }}><Unplug size={16} />Sair (posso voltar)</button>
            <button className="btn danger" onClick={() => setConfirmEnd(true)}><Power size={16} />Encerrar sessão</button>
          </div>
          <section className="card small"><h3>Métricas</h3>
            {(() => { const m = { ...(s.metrics || {}), ...Object.fromEntries(Object.entries(vstats || {}).filter(([, v]) => v !== null)) } as Partial<VideoStats>;
              const v = (x: number | null | undefined, unit: string) => (x === null || x === undefined ? 'não disponível' : `${x}${unit}`);
              return <p>FPS: {v(m.fps, '')} · Atraso (RTT): {v(m.rtt_ms, ' ms')} · Jitter: {v(m.jitter_ms, ' ms')} · Taxa: {v(m.bitrate_kbps, ' kbps')} · Perda: {v(m.packet_loss_pct, '%')}</p>; })()}
            <p className="dim">Valores medidos de verdade (pelo seu navegador na conexão de vídeo e pelo agente do console); sem medição aparece “não disponível”.</p></section>
        </>
      )}

      {confirmEnd && (
        <Modal title="Encerrar a sessão agora?" onClose={() => setConfirmEnd(false)}>
          <div className="stack">
            <p style={{ margin: 0 }}>Ainda restam <b>{duration(left)}</b>. Ao encerrar, o controle é liberado para o próximo jogador e <b>o tempo restante não é transferido</b>.</p>
            <p className="small muted" style={{ margin: 0 }}>Só quer pausar? Use <b>Sair (posso voltar)</b>: você pode voltar enquanto o seu horário não terminar.</p>
            <div className="row">
              <button className="btn danger" disabled={ending} onClick={endNow}><Power size={16} />{ending ? 'Encerrando…' : 'Encerrar sessão'}</button>
              <button className="btn" onClick={() => setConfirmEnd(false)}>Continuar jogando</button>
            </div>
          </div>
        </Modal>)}
    </div>
  );
}
export default function Page() { return <RequireAuth><Player /></RequireAuth>; }

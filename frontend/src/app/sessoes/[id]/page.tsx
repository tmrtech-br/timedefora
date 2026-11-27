'use client';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { Gamepad2, Keyboard, Volume2 } from 'lucide-react';
import InputTester from '@/components/InputTester';
import NetworkTest from '@/components/NetworkTest';
import { useFeatures } from '@/lib/features';
import QueueList from '@/components/QueueList';
import RequireAuth from '@/components/RequireAuth';
import { Alert, ErrorBox, Field, PageHeader, Skeleton, StatusPill } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useApi, useServerClock } from '@/lib/hooks';
import { CANCEL_REQUEST_STATUS, RESERVATION_STATUS, dateTime, duration, money, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';

type Room = Reservation & { seconds_to_start: number; can_join: boolean; allocation_policy: string };

function Room() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: r, error, reload } = useApi<Room>(`/reservations/${id}/waiting-room`, 5000);
  const now = useServerClock(r?.server_time);
  const [device, setDevice] = useState<'keyboard_mouse' | 'gamepad'>('gamepad');
  const features = useFeatures();
  const kbAllowed = features?.keyboard_mouse_enabled !== false;
  const [audioOk, setAudioOk] = useState(false);
  const [err, setErr] = useState('');
  const [reason, setReason] = useState('');
  const [msg, setMsg] = useState('');
  // Console sendo ligado/preparado: a página tenta entrar sozinha até ele ficar pronto (sem segundo clique).
  const [preparing, setPreparing] = useState('');
  const [joining, setJoining] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => { if (!kbAllowed && device === 'keyboard_mouse') setDevice('gamepad'); }, [kbAllowed, device]);
  // Só reagenda a cada nova resposta "preparando" (o relógio da tela re-renderiza a cada segundo e não pode
  // reiniciar o temporizador, senão ele nunca dispara).
  useEffect(() => {
    if (!preparing) return;
    const timer = window.setTimeout(() => { void join(); }, 4000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preparing, retry]);
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!r) return <Skeleton h={300} />;
  const startIn = (new Date(r.starts_at).getTime() - now()) / 1000;
  // Reserva confirmada após o início fica liberada: se o console ainda está sendo preparado, o servidor decide.
  const canJoin = ['confirmed', 'active'].includes(r.status) && startIn <= 0
    && (r.status === 'confirmed' || new Date(r.ends_at).getTime() > now());
  async function join() {
    if (joining) return;
    setErr(''); setJoining(true);
    try {
      const j = await post<{ session_id: string; input_token: string }>(`/reservations/${id}/join`, { input_device: device });
      setPreparing('');
      try { sessionStorage.setItem(`lp_input_${j.session_id}`, j.input_token); } catch { /* armazenamento indisponível */ }
      router.push(`/jogar/${j.session_id}`);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'console_preparing') { setPreparing(e.message); setRetry((n) => n + 1); }
      else { setPreparing(''); setErr(e instanceof ApiError ? e.message : 'Erro ao entrar.'); reload(); }
    } finally { setJoining(false); }
  }
  async function cancel() {
    try { const res = await post<{ message: string }>(`/reservations/${id}/cancel`, { reason }); setMsg(res.message); reload(); }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Erro.'); }
  }
  async function testAudio() {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx(); const o = ctx.createOscillator(); o.frequency.value = 440; o.connect(ctx.destination); o.start(); setTimeout(() => { o.stop(); ctx.close(); setAudioOk(true); }, 400);
  }
  return (
    <div className="stack">
      <PageHeader title="Sala de espera" subtitle={`${r.game.title} · ${r.console_name} · reserva ${r.code}`}><StatusPill status={r.status} map={RESERVATION_STATUS} /></PageHeader>
      {r.resolution_notes && <Alert kind="warn">{r.resolution_notes}</Alert>}
      <div className="grid2">
        <section className="card" style={{ textAlign: 'center' }}>
          {['confirmed', 'active'].includes(r.status) ? (startIn > 0 ? <>
            <p className="muted">{r.mode === 'queue' ? 'Início estimado em' : 'Começa em'}</p>
            <div className="countdown" aria-live="polite">{duration(startIn)}</div>
            <p>{dateTime(r.starts_at)} – {time(r.ends_at)} · {r.minutes} min</p>
            {startIn <= 300 && <Alert kind="info">Sua vez está chegando! Prepare controle ou teclado/mouse e verifique sua conexão.</Alert>}
          </> : preparing && r.status === 'confirmed' ? <>
            <p className="muted">Ligando o console e abrindo o jogo</p>
            <div className="countdown" aria-live="polite">{r.minutes} min</div>
            <p className="small muted">Seu tempo ainda não começou: ele conta a partir de quando o console estiver pronto.</p>
          </> : <>
            <p className="muted">Tempo restante do período contratado</p>
            <div className="countdown">{duration((new Date(r.ends_at).getTime() - now()) / 1000)}</div>
          </>) : r.status === 'pending_payment' ? <Link className="btn primary" href={`/checkout/${r.id}`}>Concluir pagamento ({money(r.total_cents)})</Link>
            : <p className="muted">Esta reserva está {RESERVATION_STATUS[r.status].toLowerCase()}.</p>}
          {['confirmed', 'active'].includes(r.status) && (
            <button className="btn primary block" style={{ marginTop: 14, height: 48 }} disabled={!canJoin || !!preparing || joining} onClick={join}>
              {preparing ? 'Preparando o console…' : canJoin ? 'Começar a jogar' : 'O botão será liberado no horário de início'}</button>)}
          {preparing && <div style={{ marginTop: 10 }} role="status" aria-live="polite"><Alert kind="info">{preparing}</Alert></div>}
          {err && <div style={{ marginTop: 10 }}><Alert kind="error">{err}</Alert></div>}
          {r.public_queue && r.public_queue.length > 0 && (
            <div className="waiting-queue">
              <div className="spread"><h2 style={{ margin: 0, fontSize: 18 }}>Fila do console</h2>
                <span className="small muted">{r.public_queue.length} {r.public_queue.length === 1 ? 'pessoa' : 'pessoas'}</span></div>
              <QueueList items={r.public_queue} maxVisible={5} />
            </div>)}
        </section>
        <section className="card stack">
          <h2>Prepare-se</h2>
          <div className="row" role="radiogroup" aria-label="Dispositivo de entrada">
            <button className={`btn ${device === 'gamepad' ? 'primary' : ''}`} role="radio" aria-checked={device === 'gamepad'} onClick={() => setDevice('gamepad')}><Gamepad2 size={16} />Controle</button>
            {kbAllowed && <button className={`btn ${device === 'keyboard_mouse' ? 'primary' : ''}`} role="radio" aria-checked={device === 'keyboard_mouse'} onClick={() => setDevice('keyboard_mouse')}><Keyboard size={16} />Teclado e mouse</button>}
          </div>
          <InputTester mode={device} />
          <div className="prep-tests">
            <div><button className="btn sm" onClick={testAudio}><Volume2 size={15} aria-hidden />Testar áudio</button>
              <span className="small dim">{audioOk ? 'Ouviu um bipe? Então o áudio está funcionando.' : 'Toca um bipe curto nos seus fones/alto-falantes.'}</span></div>
            <NetworkTest />
          </div>
        </section>
      </div>
      <section className="card small"><h3>Política de alocação</h3><p className="muted">{r.allocation_policy}</p>
        {r.status === 'confirmed' && !r.cancellation_request && (
          <div className="stack" style={{ maxWidth: 520 }}>
            <Field label="Solicitar cancelamento (motivo)"><input maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            <button className="btn danger" disabled={reason.length < 3} onClick={cancel}>Solicitar cancelamento</button>
          </div>)}
        {r.cancellation_request && <p>Solicitação de cancelamento: <b>{CANCEL_REQUEST_STATUS[r.cancellation_request.status] || r.cancellation_request.status}</b> {r.cancellation_request.decision_notes}</p>}
        {msg && <Alert kind="ok">{msg}</Alert>}
      </section>
    </div>
  );
}
export default function Page() { return <RequireAuth><Room /></RequireAuth>; }

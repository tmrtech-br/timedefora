'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { CalendarClock, Gamepad2, Undo2 } from 'lucide-react';
import { Alert } from '@/components/ui';
import { ApiError, get, post } from '@/lib/api';
import { dateTime, money } from '@/lib/format';

type Options = {
  minutes: number; refund_cents: number;
  same_game: { starts_at: string; console: string } | null;
  other_games: { game_id: string; title: string; slug: string; cover_url: string | null; starts_at: string; console: string }[];
};

/** Falha da plataforma: o cliente escolhe remarcar (sem custo) ou receber o estorno. */
export default function RecoveryPanel({ reservationId, gameTitle }: { reservationId: string; gameTitle: string }) {
  const router = useRouter();
  const [opts, setOpts] = useState<Options | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState('');
  useEffect(() => {
    get<Options>(`/reservations/${reservationId}/recovery`).then(setOpts)
      .catch((e) => setErr(e instanceof ApiError ? e.message : 'Não foi possível carregar as opções.'));
  }, [reservationId]);

  async function reschedule(gameId?: string) {
    setBusy(true); setErr('');
    try {
      const r = await post<{ reservation_id: string; code: string }>(`/reservations/${reservationId}/reschedule`, gameId ? { game_id: gameId } : {});
      router.push(`/sessoes/${r.reservation_id}`);
    } catch (e) { setErr(e instanceof ApiError ? e.message : 'Não foi possível remarcar.'); setBusy(false); }
  }
  async function refund() {
    setBusy(true); setErr('');
    try {
      const r = await post<{ status: string; amount_cents: number }>(`/reservations/${reservationId}/platform-refund`);
      setDone(r.status === 'completed' ? `Estorno de ${money(r.amount_cents)} enviado para o seu Pix. Pode levar alguns minutos para aparecer.`
        : 'Estorno solicitado. Nossa equipe vai concluir e você será avisado.');
    } catch (e) { setErr(e instanceof ApiError ? e.message : 'Não foi possível solicitar o estorno.'); }
    setBusy(false);
  }

  if (done) return <Alert kind="ok">{done}</Alert>;
  return (
    <section className="card stack recovery-panel" aria-labelledby="t-recovery">
      <h2 id="t-recovery">Tivemos um problema técnico. Como prefere seguir?</h2>
      <p className="small muted" style={{ margin: 0 }}>A falha foi da plataforma: você não paga nada a mais.
        {opts && ` Você tem ${opts.minutes} min de crédito em ${gameTitle}.`}</p>
      {err && <Alert kind="error">{err}</Alert>}
      {!opts && !err && <p className="small muted" role="status">Procurando o horário livre mais próximo…</p>}
      {opts && <>
        {opts.same_game ? (
          <button className="btn primary" disabled={busy} onClick={() => reschedule()}>
            <CalendarClock size={16} aria-hidden />Remarcar {gameTitle}: {dateTime(opts.same_game.starts_at)} ({opts.minutes} min, {opts.same_game.console})
          </button>
        ) : <Alert kind="info">Não há horário livre agora para {gameTitle} com {opts.minutes} min.
          {opts.other_games.length ? ' Você pode usar o crédito em outro jogo:' : ''}</Alert>}
        {!opts.same_game && opts.other_games.map((g) => (
          <button key={g.game_id} className="btn" disabled={busy} onClick={() => reschedule(g.game_id)}>
            <Gamepad2 size={16} aria-hidden />{g.title}: {dateTime(g.starts_at)} ({opts.minutes} min)
          </button>))}
        {opts.refund_cents > 0 && <button className="btn" disabled={busy} onClick={refund}>
          <Undo2 size={16} aria-hidden />Prefiro o estorno de {money(opts.refund_cents)} via Pix</button>}
      </>}
    </section>
  );
}

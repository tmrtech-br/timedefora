'use client';
import { useParams, useRouter } from 'next/navigation';
import { useState } from 'react';
import { CreditCard, QrCode } from 'lucide-react';
import RequireAuth from '@/components/RequireAuth';
import { Alert, ErrorBox, PageHeader, Skeleton } from '@/components/ui';
import { ApiError, post } from '@/lib/api';
import { useApi, useServerClock } from '@/lib/hooks';
import { dateTime, duration, money, RESERVATION_STATUS, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';

function Checkout() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: r, error, reload } = useApi<Reservation & { cancellation_policy: { title: string; body: string } | null }>(`/reservations/${id}`, 5000);
  const now = useServerClock(r?.server_time);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!r) return <Skeleton h={300} />;
  const left = r.hold_expires_at ? (new Date(r.hold_expires_at).getTime() - now()) / 1000 : 0;
  async function pay(method: 'pix' | 'card') {
    setBusy(true); setErr('');
    try {
      const res = await post<{ checkout_url?: string; free?: boolean; simulated?: boolean }>(`/reservations/${id}/checkout`, { method });
      if (res.free) return router.push(`/sessoes/${id}`);
      if (res.checkout_url?.startsWith('/')) router.push(res.checkout_url);
      else if (res.checkout_url) window.location.href = res.checkout_url;   // Mercado Pago (Checkout Pro)
    } catch (e) { setErr(e instanceof ApiError ? e.message : 'Erro ao iniciar pagamento.'); }
    finally { setBusy(false); }
  }
  async function cancel() {
    await post(`/reservations/${id}/cancel`, { reason: 'Desistiu no checkout' });
    router.push('/jogos');
  }
  return (
    <div className="stack" style={{ maxWidth: 760 }}>
      <PageHeader title="Pagamento" subtitle={`Reserva ${r.code}`} />
      {r.status !== 'pending_payment' ? (
        <Alert kind={r.status === 'confirmed' ? 'ok' : 'warn'}>Status da reserva: <b>{RESERVATION_STATUS[r.status]}</b>. {r.status === 'confirmed' && <a className="link-purple" href={`/sessoes/${id}`}>Abrir sala de espera</a>}</Alert>
      ) : left <= 0 ? <Alert kind="error">A reserva provisória expirou. Faça uma nova reserva.</Alert>
        : <Alert kind="warn">Reserva provisória: conclua o pagamento em <b>{duration(left)}</b> ou o horário será liberado.</Alert>}
      <section className="card">
        <dl className="kv">
          <dt>Jogo</dt><dd>{r.game.title}</dd>
          <dt>Console</dt><dd>{r.console_name}</dd>
          <dt>Tempo</dt><dd>{r.minutes} minutos</dd>
          <dt>{r.mode === 'queue' ? 'Início estimado' : 'Início reservado'}</dt><dd>{dateTime(r.starts_at)}</dd>
          <dt>Término</dt><dd>{time(r.ends_at)} (horário de Fortaleza)</dd>
          <dt>Preço</dt><dd>{money(r.price_cents)}</dd>
          {r.discount_cents > 0 && <><dt>Desconto</dt><dd>− {money(r.discount_cents)}</dd></>}
          <dt>Total</dt><dd><b style={{ fontSize: 18 }}>{money(r.total_cents)}</b></dd>
        </dl>
        {r.mode === 'queue' && <p className="small muted">O início é estimado: pode ser antecipado se a fila andar, nunca atrasado após a confirmação. O tempo conta a partir do início reservado.</p>}
        {r.cancellation_policy && <details className="small"><summary>{r.cancellation_policy.title}</summary><p className="muted" style={{ whiteSpace: 'pre-line' }}>{r.cancellation_policy.body}</p></details>}
      </section>
      {err && <Alert kind="error">{err}</Alert>}
      {r.status === 'pending_payment' && left > 0 && (
        <div className="grid2">
          <button className="btn primary" style={{ height: 56 }} disabled={busy} onClick={() => pay('pix')}><QrCode aria-hidden />Pagar com Pix</button>
          <button className="btn" style={{ height: 56 }} disabled={busy} onClick={() => pay('card')}><CreditCard aria-hidden />Pagar com cartão</button>
        </div>
      )}
      {r.status === 'pending_payment' && <button className="btn danger" onClick={cancel}>Cancelar reserva provisória</button>}
      <p className="small dim">Pagamentos processados pelo Mercado Pago (Checkout Pro). A timedefora não armazena dados de cartão. A confirmação chega ao servidor pelo provedor — fechar esta página não cancela um pagamento em andamento.</p>
    </div>
  );
}
export default function Page() { return <RequireAuth><Checkout /></RequireAuth>; }

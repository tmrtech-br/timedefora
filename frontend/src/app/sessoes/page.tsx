'use client';
import Link from 'next/link';
import RequireAuth from '@/components/RequireAuth';
import { Empty, ErrorBox, PageHeader, Skeleton, StatusPill } from '@/components/ui';
import { useApi } from '@/lib/hooks';
import { ApiError, post } from '@/lib/api';
import { toast } from '@/components/Toaster';
import { RESERVATION_STATUS, dateTime, money, time } from '@/lib/format';
import type { Reservation } from '@/lib/types';

function Sessoes() {
  const res = useApi<Reservation[]>('/me/reservations', 10000);
  return (
    <>
      <PageHeader title="Minhas sessões" subtitle="Acompanhe suas reservas e sessões em andamento.">
        <Link className="btn" href="/sessoes/historico">Histórico de sessões</Link>
      </PageHeader>
      <ErrorBox error={res.error} onRetry={res.reload} />
      <h2>Reservas</h2>
      {!res.data ? <Skeleton h={160} /> : !res.data.length ? <Empty>Nenhuma reserva ainda. <Link className="link-purple" href="/jogos">Ver catálogo</Link></Empty> : (
        <div className="table-wrap card max10"><table className="table"><thead><tr><th>Reserva</th><th>Jogo</th><th>Período</th><th>Valor</th><th>Status</th><th /></tr></thead>
          <tbody>{res.data.map((r) => (
            <tr key={r.id}><td>{r.code}</td><td>{r.game.title}<div className="small dim">{r.console_name}</div></td>
              <td>{dateTime(r.starts_at)} – {time(r.ends_at)}<div className="small dim">{r.mode === 'queue' ? 'início estimado' : 'horário fixo'}</div></td>
              <td>{money(r.total_cents)}</td><td><StatusPill status={r.status} map={RESERVATION_STATUS} /></td>
              <td>{r.status === 'pending_payment' ? <div className="row" style={{ gap: 6, flexWrap: 'nowrap' }}>
                  <Link className="btn sm primary" href={`/checkout/${r.id}`}>Pagar</Link>
                  <button className="btn sm" title="Libera o horário para outros jogadores" onClick={async () => {
                    try { await post(`/reservations/${r.id}/cancel`, { reason: 'Desistiu antes de pagar' }); toast('ok', 'Reserva provisória cancelada. O horário foi liberado.'); res.reload(); }
                    catch (e) { toast('error', e instanceof ApiError ? e.message : 'Não foi possível cancelar.'); }
                  }}>Desistir</button></div>
                : ['confirmed', 'active'].includes(r.status) ? <Link className="btn sm primary" href={`/sessoes/${r.id}`}>Sala de espera</Link>
                : <Link className="btn sm" href={`/sessoes/${r.id}`}>Detalhes</Link>}</td></tr>
          ))}</tbody></table></div>
      )}
    </>
  );
}
export default function Page() { return <RequireAuth><Sessoes /></RequireAuth>; }
